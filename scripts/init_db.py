#!/usr/bin/env python3
"""Create the database schema and seed the sources table.

Usage:  python scripts/init_db.py            # uses DATABASE_URL from .env or SQLite default
        python scripts/init_db.py --reset    # drop and recreate (dev only)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import inspect  # noqa: E402

from lpc_regwatch.config import settings  # noqa: E402
from lpc_regwatch.db import init_db  # noqa: E402
from lpc_regwatch.db.models import Base  # noqa: E402
from lpc_regwatch.db.session import get_engine  # noqa: E402

if __name__ == "__main__":
    if "--reset" in sys.argv:
        Base.metadata.drop_all(get_engine())
    eng = init_db()
    tables = inspect(eng).get_table_names()
    print(f"database: {settings.database_url}")
    print(f"tables ({len(tables)}): {', '.join(sorted(tables))}")
