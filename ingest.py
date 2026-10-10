"""
ingest.py - Load files of (almost) any format, chunk them, embed them,
and upsert them into a Pinecone index.

Usage:
    python ingest.py ./data                 # a folder (recursive)
    python ingest.py report.pdf faq.json    # individual files
    python ingest.py https://example.com    # web pages
"""
import hashlib
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec
from langchain_community.document_loaders import (
    BSHTMLLoader,
    CSVLoader,
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
    WebBaseLoader,
)

load_dotenv()

INDEX_NAME = os.getenv("PINECONE_INDEX", "chatbot-kb-local")
NAMESPACE = os.getenv("PINECONE_NAMESPACE", "default")
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "ollama")  # "ollama" (local) or "openai"
EMBED_MODEL = os.getenv("EMBED_MODEL", "qwen3-embedding:0.6b")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))  # must match the embedding model's output size


def get_embeddings():
    if EMBED_PROVIDER == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model=EMBED_MODEL)
    return OpenAIEmbeddings(model=EMBED_MODEL)


# ---------------------------------------------------------------------------
# 1. Format-specific loaders
# ---------------------------------------------------------------------------
def _flatten(obj, prefix=""):
    """Turn nested JSON into 'path.to.key: value' lines (embeds far better than raw JSON)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{prefix}[{i}]")
    else:
        yield f"{prefix}: {obj}"


def load_json(path: Path) -> list[Document]:
    """Works on any JSON shape without needing a jq schema. One Document per record."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        records = data if isinstance(data, list) else [data]
    return [
        Document(
            page_content="\n".join(_flatten(rec)),
            metadata={"source": str(path), "record": i},
        )
        for i, rec in enumerate(records)
    ]


def load_unstructured(path: Path, **kwargs) -> list[Document]:
    """Catch-all for xlsx, pptx, eml, epub, odt, images (OCR), scanned PDFs, etc."""
    from langchain_unstructured import UnstructuredLoader  # imported lazily: heavy dependency

    return UnstructuredLoader(str(path), **kwargs).load()


def load_pdf(path: Path) -> list[Document]:
    docs = PyPDFLoader(str(path)).load()
    # Scanned PDFs have no text layer -> fall back to OCR via Unstructured
    if not any(d.page_content.strip() for d in docs):
        print(f"  (no text layer in {path.name}, falling back to OCR)")
        docs = load_unstructured(path, strategy="hi_res")
    return docs


LOADERS = {
    ".pdf": load_pdf,
    ".json": load_json,
    ".jsonl": load_json,
    ".csv": lambda p: CSVLoader(str(p), encoding="utf-8").load(),  # one Document per row
    ".txt": lambda p: TextLoader(str(p), autodetect_encoding=True).load(),
    ".md": lambda p: TextLoader(str(p), autodetect_encoding=True).load(),
    ".docx": lambda p: Docx2txtLoader(str(p)).load(),
    ".html": lambda p: BSHTMLLoader(str(p)).load(),
    ".htm": lambda p: BSHTMLLoader(str(p)).load(),
}


def load_source(src: str) -> list[Document]:
    if src.startswith(("http://", "https://")):
        return WebBaseLoader(src).load()
    path = Path(src)
    loader = LOADERS.get(path.suffix.lower(), load_unstructured)  # unknown -> Unstructured
    return loader(path)


# ---------------------------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------------------------
def clean_metadata(meta: dict) -> dict:
    """Pinecone metadata only accepts str, number, bool, or list of str."""
    out = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = v
    return out


def chunk_id(source: str, i: int) -> str:
    """Deterministic IDs: re-ingesting the same file overwrites instead of duplicating."""
    return hashlib.sha256(f"{source}::{i}".encode()).hexdigest()


def expand_inputs(args: list[str]) -> list[str]:
    sources = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            sources += [str(f) for f in sorted(p.rglob("*")) if f.is_file() and not f.name.startswith(".")]
        else:
            sources.append(a)
    return sources


def get_vector_store() -> PineconeVectorStore:
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    if not pc.has_index(INDEX_NAME):
        pc.create_index(
            name=INDEX_NAME,
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    embeddings = get_embeddings()
    return PineconeVectorStore(index=pc.Index(INDEX_NAME), embedding=embeddings, namespace=NAMESPACE)


# ---------------------------------------------------------------------------
# 3. Pipeline
# ---------------------------------------------------------------------------
def main(args: list[str]) -> None:
    store = get_vector_store()
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)

    for src in expand_inputs(args):
        try:
            docs = load_source(src)
        except Exception as e:  # one bad file shouldn't kill the whole run
            print(f"SKIP {src}: {e}")
            continue

        chunks = splitter.split_documents(docs)
        chunks = [c for c in chunks if c.page_content.strip()]
        if not chunks:
            print(f"SKIP {src}: no text extracted")
            continue

        for c in chunks:
            c.metadata = clean_metadata({**c.metadata, "source": src})
        ids = [chunk_id(src, i) for i in range(len(chunks))]

        store.add_documents(chunks, ids=ids)
        print(f"OK   {src}: {len(chunks)} chunks")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
