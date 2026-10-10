#!/usr/bin/env python3
"""Export the canonical store in the LPC Dataverse target structure (schema/dataverse_tables.xlsx) and validate
the result against that workbook. Output: output/dataverse/<table>.csv (+ README.txt) and output/dataverse.xlsx.

Usage: python scripts/export_dataverse.py [--out output/dataverse]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpc_regwatch.dataverse import build_tables, validate_against_workbook, write_csvs, xlsx_bytes  # noqa: E402
from lpc_regwatch.db import get_session, init_db  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "output" / "dataverse"))
    a = ap.parse_args()
    init_db()
    s = get_session()
    tables = build_tables(s)
    counts = write_csvs(tables, Path(a.out))
    Path(a.out).with_suffix(".xlsx").write_bytes(xlsx_bytes(tables))
    report = validate_against_workbook(tables)
    print(json.dumps({"rows": counts, "validation_ok": report["ok"], "tables_with_issues": report["errors"]}, indent=2))
    for t in report["errors"]:
        print(t, {k: v for k, v in report["tables"][t].items() if v and k != "rows"})
    s.close()
    sys.exit(0 if report["ok"] else 1)
