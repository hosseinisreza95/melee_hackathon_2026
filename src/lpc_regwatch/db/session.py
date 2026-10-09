"""Engine/session helpers. SQLite for dev, PostgreSQL via DATABASE_URL on the server."""
from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import ROOT, settings
from .models import Base, Source

_engine: Engine | None = None


def get_engine(url: str | None = None) -> Engine:
    global _engine
    if _engine is None or url:
        u = url or settings.database_url
        if u.startswith("sqlite"):
            Path(u.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(u, future=True)
        if u.startswith("sqlite"):
            @event.listens_for(eng, "connect")
            def _fk_on(dbapi_conn, _):  # enforce FK in SQLite
                dbapi_conn.execute("PRAGMA foreign_keys=ON")
        if url:
            return eng
        _engine = eng
    return _engine


def get_session(url: str | None = None) -> Session:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)()


def init_db(url: str | None = None, seed_sources: bool = True) -> Engine:
    """Create all tables and seed the `sources` table from data/source_registry.csv."""
    eng = get_engine(url)
    Base.metadata.create_all(eng)
    if seed_sources:
        with sessionmaker(bind=eng)() as s:
            path = ROOT / "data" / "source_registry.csv"
            with path.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if not row.get("source_id"):
                        continue
                    s.merge(Source(
                        source_id=row["source_id"],
                        official_name=row["official_name"],
                        country_or_region=row["country_or_region"],
                        base_url=row.get("base_url") or "",
                        access_method=row["access_method"],
                        data_format=row.get("data_format") or "",
                        license_name=row.get("license_name") or None,
                        access_and_reuse_limits=row.get("access_and_reuse_limits") or None,
                        manual_validation_required=str(row.get("manual_validation_required", "true")).lower() == "true",
                        notes=row.get("notes") or None,
                    ))
            s.commit()
    return eng
