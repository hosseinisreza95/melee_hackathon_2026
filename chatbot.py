"""
chatbot.py - A conversational agent that uses a Pinecone-backed retrieval tool.

Usage:
    python chatbot.py
"""
import os
import uuid

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from ingest import get_vector_store

load_dotenv()

from langchain_ollama import ChatOllama

llm = ChatOllama(
    model=os.getenv("CHAT_MODEL", "qwen3.5:9b"),
    temperature=0.2,   # low = sticks closer to retrieved text
    num_ctx=16384,     # Ollama's default context is small; retrieved chunks + history need room
    reasoning=False,   # skip Qwen's "thinking" phase: much faster, fine for RAG Q&A
)
vector_store = get_vector_store()


@tool(response_format="content_and_artifact")
def search_knowledge_base(query: str):
    """Search the internal knowledge base (PDFs, JSON, docs, spreadsheets, web pages).
    Use this for any question about our products, policies, data or documents."""
    docs = vector_store.similarity_search(query, k=5)
    text = "\n\n".join(
        f"[Source: {d.metadata.get('source', 'unknown')}"
        f"{', page ' + str(d.metadata['page'] + 1) if 'page' in d.metadata else ''}]\n"
        f"{d.page_content}"
        for d in docs
    )
    return text or "No relevant documents found.", docs  # (what the LLM sees, raw docs)


SYSTEM_PROMPT = """You are a helpful assistant for our company.
Use the search_knowledge_base tool to find information before answering factual questions.
You may search more than once with different wording if the first results are weak.
Answer only from what the tool returns; if the answer isn't there, say you don't know.
Cite the source file for each fact you use."""

agent = create_agent(
    model=llm,
    tools=[search_knowledge_base],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=InMemorySaver(),  # conversation memory per thread_id
)


def main() -> None:
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print("Ask me anything (Ctrl+C to quit)\n")
    while True:
        question = input("You: ").strip()
        if not question:
            continue
        result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config)
        print(f"\nBot: {result['messages'][-1].content}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
