"""Load parsed batches into the canonical store and export the starter-kit CSV contract.

Upsert policy (MVP): a registration is identified by its official number; re-parsing the same
source replaces its use rows and refreshes its fields (snapshot_id, collected_at move forward).
Products are created on first sight and only completed afterwards (never overwritten), so the
first official wording of the active entity is kept. Change detection across snapshots is a
bonus item (docs/SPEC.md A1) and is not done here.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .db.models import AuthorizedUse, Product, ProductAlias, Registration, Source
from .parsers.base import Batch

STARTER_COLUMNS = {
    "products": ["product_id", "commercial_name", "active_entity_original", "active_entity_normalized", "formulation_code",
                 "is_synthetic", "validation_status", "strain"],
    "product_aliases": ["alias_id", "product_id", "alias_name", "country_code", "relationship_type", "confidence", "evidence",
                        "review_status", "is_synthetic", "source_record_url"],
    "registrations": ["registration_id", "product_id", "country_code", "authority_name", "registration_number", "status_original",
                      "status_normalized", "approval_date", "expiration_date", "source_id", "source_record_url", "collected_at",
                      "validation_status", "is_synthetic", "holder_original", "formulation_original", "active_entity_original",
                      "extraction_method", "snapshot_id", "evidence_excerpt"],
    "uses": ["use_id", "registration_id", "crop_name_original", "crop_name_normalized", "eppo_crop_code", "target_name_original",
             "target_name_normalized", "eppo_target_code", "application_method", "dose_value", "dose_unit_original",
             "dose_unit_normalized", "max_applications", "application_interval_days", "phi_days", "rei_hours",
             "restrictions_original", "validation_status", "is_synthetic", "pairing", "growth_stage_min", "growth_stage_max",
             "use_status_original", "source_record_url", "collected_at", "extraction_method", "evidence_excerpt"],
}


def load_batch(session: Session, b: Batch) -> dict[str, int]:
    counts = {"products_new": 0, "aliases": 0, "registrations": 0, "uses": 0}
    for pid, p in b.products.items():
        existing = session.get(Product, pid)
        if existing is None:
            session.add(Product(**p))
            counts["products_new"] += 1
        else:
            for k, v in p.items():
                if getattr(existing, k, None) in (None, "") and v not in (None, ""):
                    setattr(existing, k, v)
    session.flush()
    for a in b.aliases.values():
        if session.get(ProductAlias, a["alias_id"]) is None:
            session.add(ProductAlias(**a))
            counts["aliases"] += 1
    reg_ids = [r["registration_id"] for r in b.registrations]
    if reg_ids:
        session.execute(delete(AuthorizedUse).where(AuthorizedUse.registration_id.in_(reg_ids)))
    for r in b.registrations:
        session.merge(Registration(**r))
        counts["registrations"] += 1
    session.flush()
    for u in b.uses:
        session.add(AuthorizedUse(**u))
        counts["uses"] += 1
    session.commit()
    return counts


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ") if v.tzinfo or v.hour or v.minute else v.strftime("%Y-%m-%d")
    if hasattr(v, "value"):
        return v.value
    return str(v)


def export_csv(session: Session, out_dir: Path) -> dict[str, int]:
    """Write the canonical CSVs in the starter-kit column order (extra columns appended at the end)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "products": session.query(Product).order_by(Product.product_id).all(),
        "product_aliases": session.query(ProductAlias).order_by(ProductAlias.alias_id).all(),
        "registrations": session.query(Registration).order_by(Registration.registration_id).all(),
        "uses": session.query(AuthorizedUse).order_by(AuthorizedUse.use_id).all(),
    }
    counts = {}
    for name, rows in tables.items():
        cols = STARTER_COLUMNS[name]
        with (out_dir / f"{name}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                row = []
                for c in cols:
                    v = getattr(r, c, None)
                    if c in ("approval_date", "expiration_date") and isinstance(v, dt.datetime):
                        v = v.strftime("%Y-%m-%d")
                    elif c == "collected_at" and isinstance(v, dt.datetime):
                        v = v.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if v.tzinfo else v.strftime("%Y-%m-%dT%H:%M:%SZ")
                    row.append(_fmt(v))
                w.writerow(row)
        counts[name] = len(rows)
    counts["sources"] = session.query(Source).count()
    return counts
