#!/usr/bin/env python3
"""Run one or all collectors: fetch official files, store them with provenance, register a snapshot.

Usage:  python scripts/collect.py --source all
        python scripts/collect.py --source ca_ppid us_epa_ppls
Exit code 1 if any collector failed (its snapshot is recorded with status=failed).
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.collectors import COLLECTORS  # noqa: E402
from lpc_regwatch.db import get_session, init_db  # noqa: E402
from lpc_regwatch.db.models import RawDocument  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", nargs="+", default=["all"], choices=["all", *COLLECTORS])
    ap.add_argument("--no-labels", action="store_true", help="US: skip label PDF downloads")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    names = list(COLLECTORS) if "all" in args.source else args.source
    failed = []
    for name in names:
        s = get_session()
        kw = {"fetch_labels": not args.no_labels} if name == "us_epa_ppls" else {}
        try:
            snap = COLLECTORS[name](s, **kw).run()
            docs = s.query(RawDocument).filter_by(snapshot_id=snap.snapshot_id).all()
            print(f"OK   {name:12} snapshot={snap.snapshot_id} docs={len(docs)} bytes={sum(d.bytes for d in docs):,} dir={Path(docs[0].local_path).parent if docs else '-'}")
            if snap.notes:
                print("     notes: " + snap.notes.replace("\n", "\n            "))
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            print(f"FAIL {name:12} {type(e).__name__}: {e}")
        finally:
            s.close()
    sys.exit(1 if failed else 0)
