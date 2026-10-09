#!/usr/bin/env python3
"""Step 7: extract uses (crop, target, dose) from the stored pilot label PDFs with the configured LLM.

Requires AI_API_KEY (or OPENAI_API_KEY / OPEN_AI) in .env. Without a key the script exits 0 and changes nothing.
Usage: python scripts/extract_labels.py [--all] [--model gpt-4.1] [--force]
"""
import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpc_regwatch.db import get_session, init_db  # noqa: E402
from lpc_regwatch.extract.label_llm import run  # noqa: E402
from lpc_regwatch.llm import LLMUnavailable  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="all Lallemand labels, not only the 3 pilot products")
    ap.add_argument("--model", default=None)
    ap.add_argument("--force", action="store_true", help="ignore the sha256 cache")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    s = get_session()
    try:
        rep = run(s, only_pilots=not a.all, model=a.model, force=a.force)
        print(json.dumps(rep, indent=2))
        (ROOT / "data" / "processed" / "label_extraction_report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    except LLMUnavailable as e:
        print(f"SKIPPED: {e}")
    finally:
        s.close()
