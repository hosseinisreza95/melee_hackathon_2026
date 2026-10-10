#!/usr/bin/env python3
"""Run the jury question set (evaluation/jury_questions.jsonl) through ask() and write output/jury_answers.json.

    python scripts/jury_run.py                 # deterministic path (no key) and, if a key is configured, the LLM path too
    python scripts/jury_run.py --no-llm        # deterministic only
    python scripts/jury_run.py --ids J08,J10   # subset

Prints a compact view (intent, headline, first rows, caveats) so weak answers can be spotted and fixed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpc_regwatch.api import ask as A  # noqa: E402
from lpc_regwatch.config import settings  # noqa: E402
from lpc_regwatch.db.session import get_session  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--ids", default="")
    ap.add_argument("--out", default=str(ROOT / "output" / "jury_answers.json"))
    args = ap.parse_args()
    qs = [json.loads(line) for line in (ROOT / "evaluation" / "jury_questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.ids:
        keep = set(args.ids.split(","))
        qs = [q for q in qs if q["id"] in keep]
    modes = ["deterministic"] + ([] if args.no_llm or not settings.ai_enabled else ["llm"])
    out = []
    orig_key = settings.ai_api_key
    with get_session() as s:
        for q in qs:
            row = {"id": q["id"], "lang": q["lang"], "question": q["question"], "expect": q.get("expect"), "answers": {}}
            for mode in modes:
                object.__setattr__(settings, "ai_api_key", "" if mode == "deterministic" else orig_key)
                t0 = time.time()
                try:
                    a = A.ask(s, q["question"], q["lang"])
                except Exception as e:  # noqa: BLE001
                    a = {"error": f"{type(e).__name__}: {e}"}
                a["seconds"] = round(time.time() - t0, 1)
                row["answers"][mode] = a
                sa = a.get("structured") or {}
                print(f"\n=== {q['id']} [{mode}] intent={a.get('intent')} extra={a.get('extraIntents')} lang={a.get('language')} model={a.get('model')} {a['seconds']}s")
                print("Q:", q["question"])
                if "error" in a:
                    print("ERROR", a["error"])
                    continue
                print("H:", sa.get("headline"))
                for it in (sa.get("items") or [])[:4]:
                    print("  -", {k: v for k, v in it.items() if v})
                for sec in sa.get("sections") or []:
                    print("  ##", sec.get("title"), "|", (sec.get("text") or "")[:120], "| rows", len(sec.get("items") or []))
                for c in sa.get("caveats") or []:
                    print("  !", c[:140])
            out.append(row)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\nwritten {args.out} ({len(out)} questions, modes {modes})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
