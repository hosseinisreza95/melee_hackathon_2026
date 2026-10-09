#!/usr/bin/env python3
"""Step 3: normalise stored rows (EPPO, units, taxonomy), merge official equivalents, load starter
hypotheses, propose sister-product candidates, then re-export the canonical CSVs and validate them.

Usage: python scripts/normalize.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpc_regwatch.db import get_session, init_db  # noqa: E402
from lpc_regwatch.loader import export_csv  # noqa: E402
from lpc_regwatch.matching import run_all  # noqa: E402

if __name__ == "__main__":
    init_db()
    s = get_session()
    report = run_all(s)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("exported:", export_csv(s, ROOT / "data"))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_data.py")], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    s.close()
    sys.exit(r.returncode)
