#!/usr/bin/env python3
"""Parse the latest successful snapshot of each source into the canonical store, then export
the starter-kit CSVs (data/products.csv, product_aliases.csv, registrations.csv, uses.csv)
and run the organiser's validator on them.

Usage:  python scripts/parse.py --source all
        python scripts/parse.py --source fr_ephy --no-export
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpc_regwatch.db import get_session, init_db  # noqa: E402
from lpc_regwatch.loader import export_csv, load_batch  # noqa: E402
from lpc_regwatch.parsers import PARSERS  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", nargs="+", default=["all"], choices=["all", *PARSERS])
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args()
    init_db()
    names = list(PARSERS) if "all" in args.source else args.source
    failed = []
    s = get_session()
    for name in names:
        try:
            batch = PARSERS[name](s).parse()
            counts = load_batch(s, batch)
            print(f"OK   {name:12} snapshot={batch.snapshot_id} products_new={counts['products_new']} aliases={counts['aliases']} "
                  f"registrations={counts['registrations']} uses={counts['uses']}")
            for n in batch.notes[:8]:
                print(f"     note: {n}")
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            s.rollback()
            print(f"FAIL {name:12} {type(e).__name__}: {e}")
    if not args.no_export:
        counts = export_csv(s, ROOT / "data")
        print("exported:", counts)
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_data.py")], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode:
            failed.append("validate_data")
    s.close()
    sys.exit(1 if failed else 0)
