#!/usr/bin/env python3
"""RAGAS evaluation of the assistant on evaluation/qa_validation.jsonl (question, ground_truth written from the official data).

For each question: ask() -> answer text (structured answer flattened) + contexts (one string per fact row, i.e. the retrieved
official rows) ; RAGAS computes faithfulness, answer relevancy, context precision and context recall with an OpenAI judge.

    python scripts/ragas_eval.py                       # LLM-phrased answers (key required), judge = RAGAS_JUDGE_MODEL or gpt-5-mini
    python scripts/ragas_eval.py --deterministic       # answers without the LLM (the no-key path)
    python scripts/ragas_eval.py --ids V01,V02

Writes output/ragas_report.json and prints a table. The key is read from the environment / .env only (never printed).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpc_regwatch.api import ask as A  # noqa: E402
from lpc_regwatch.config import settings  # noqa: E402
from lpc_regwatch.db.session import get_session  # noqa: E402


def fact_to_text(f: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in f.items() if v not in (None, "", [], {}))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deterministic", action="store_true")
    ap.add_argument("--ids", default="")
    ap.add_argument("--judge", default=os.getenv("RAGAS_JUDGE_MODEL", "gpt-5-mini"))
    ap.add_argument("--out", default=str(ROOT / "output" / "ragas_report.json"))
    args = ap.parse_args()
    if not settings.ai_enabled:
        print("No AI key configured (AI_API_KEY / OPENAI_API_KEY): RAGAS needs a judge model.")
        return 2
    qs = [json.loads(line) for line in (ROOT / "evaluation" / "qa_validation.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.ids:
        keep = set(args.ids.split(","))
        qs = [q for q in qs if q["id"] in keep]
    key = settings.ai_api_key
    samples = []
    with get_session() as s:
        for q in qs:
            object.__setattr__(settings, "ai_api_key", "" if args.deterministic else key)
            a = A.ask(s, q["question"], q.get("lang", "fr"))
            contexts = [fact_to_text(f) for f in a["facts"][:40]] or ["(no fact retrieved)"]
            samples.append({"id": q["id"], "user_input": q["question"], "response": a["answer"], "retrieved_contexts": contexts, "reference": q["ground_truth"],
                            "intent": a["intent"], "model": a["model"]})
            print(f"{q['id']}: intent={a['intent']} model={a['model']} facts={len(a['facts'])}")
    object.__setattr__(settings, "ai_api_key", key)
    os.environ.setdefault("OPENAI_API_KEY", key)

    from datasets import Dataset  # noqa: E402
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings  # noqa: E402
    from ragas import evaluate  # noqa: E402
    from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
    from ragas.llms import LangchainLLMWrapper  # noqa: E402
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness  # noqa: E402

    judge = LangchainLLMWrapper(ChatOpenAI(model=args.judge, timeout=180))
    emb = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small"))
    ds = Dataset.from_list([{"question": x["user_input"], "answer": x["response"], "contexts": x["retrieved_contexts"], "ground_truth": x["reference"]} for x in samples])
    result = evaluate(ds, metrics=[faithfulness, answer_relevancy, context_precision, context_recall], llm=judge, embeddings=emb, raise_exceptions=False)
    df = result.to_pandas()
    df.insert(0, "id", [x["id"] for x in samples])
    df["intent"] = [x["intent"] for x in samples]
    cols = ["id", "intent", "faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    print(df[cols].to_string(index=False))
    means = {c: round(float(df[c].mean()), 3) for c in cols[2:]}
    print("MEANS", means)
    report = {"mode": "deterministic" if args.deterministic else f"llm:{settings.ai_model}", "judge": args.judge, "n": len(samples), "means": means,
              "rows": json.loads(df[cols + ["question", "answer"]].to_json(orient="records", force_ascii=False))}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
