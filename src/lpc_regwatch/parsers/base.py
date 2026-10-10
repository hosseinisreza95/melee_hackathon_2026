"""Parser base: deterministic conversion of raw official files into canonical rows.

Rules enforced here (docs/SPEC.md M3, G2, G5, G6):
- every registration/use carries source_id, source_record_url, collected_at, snapshot_id,
  raw_document_id, extraction_method and an evidence_excerpt built from the source row itself;
- *_original fields are copied verbatim; *_normalized fields are filled only by exact,
  versioned mappings (data/status_mapping.csv) — everything else stays for Step 3;
- product identity: pilot products come from data/product_name_mapping.csv (canonical and
  historical names); any other product gets a deterministic id from its normalized name.
  Sister-product candidates are NEVER merged here.

Scope filter (why): the MVP loads Lallemand products plus every product whose active
microorganism species is one of the pilot species (= competitors on the same microorganism).
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy.orm import Session

from ..config import ROOT
from ..db.models import RawDocument, Snapshot
from ..pilots import name_variants, species_terms

LALLEMAND = re.compile(r"DANSTAR|LALLEMAND", re.I)
STRAIN_RE = re.compile(r"(?:strain|souche|cepa|isolado|isolate|stamm)\s*:?\s*([A-Za-z0-9][^(),;|]*)", re.I)
FORMULATION_CODES = {"WG", "OD", "GR", "WP", "SC", "EC", "WS", "SL", "DS", "CS", "SE", "ME", "EW", "FS", "DP", "GB"}


def norm_name(s: str | None) -> str:
    s = (s or "").replace("®", " ").replace("™", " ").upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def slug(s: str) -> str:
    return norm_name(s).replace(" ", "-")


def strain_of(active: str | None) -> str | None:
    m = STRAIN_RE.search(active or "")
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip(" *.:")[:40] or None


def species_of(active: str | None) -> str | None:
    """Genus + species from free text, e.g. 'CONIOTHYRIUM MINITANS STRAIN ...' -> 'Coniothyrium minitans'."""
    m = re.search(r"\b([A-Za-z]{4,})\s+([a-z]{3,}|[A-Z]{3,})\b", (active or "").replace(",", " "))
    if not m:
        return None
    return f"{m.group(1).capitalize()} {m.group(2).lower()}"


def active_normalized(active: str | None) -> str | None:
    sp = species_of(active)
    if not sp:
        return None
    st = strain_of(active)
    return f"{sp} {st}" if st else sp


def formulation_code_from_name(name: str) -> str | None:
    toks = norm_name(name).split()
    return toks[-1] if toks and toks[-1] in FORMULATION_CODES else None


def parse_date(s: str | None) -> dt.datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def to_float(s) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def to_int(s) -> int | None:
    f = to_float(s)
    return int(f) if f is not None and float(f).is_integer() else None


def excerpt(row: dict, keys: list[str], maxlen: int = 700) -> str:
    parts = [f"{k}={str(row.get(k)).strip()}" for k in keys if row.get(k) not in (None, "", "nan")]
    s = " | ".join(parts)
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


@lru_cache
def status_map() -> dict[tuple[str, str], str]:
    with (ROOT / "data" / "status_mapping.csv").open(encoding="utf-8-sig", newline="") as f:
        return {(r["source_id"], r["status_original"].strip().upper()): r["status_normalized"] for r in csv.DictReader(f)}


def normalize_status(source_id: str, original: str | None) -> str:
    return status_map().get((source_id, (original or "").strip().upper()), "unknown")


@lru_cache
def pilot_name_index() -> dict[str, str]:
    """normalized name -> pilot product_id, for canonical and historical/market names only."""
    idx: dict[str, str] = {}
    with (ROOT / "data" / "product_name_mapping.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["relationship_type"] in ("canonical_name", "historical_or_market_name"):
                idx[norm_name(r["name_variant"])] = r["product_id"]
    # NOTE (LPC answer 2026-10-10): a registration that carries a pilot name as alternate name (e.g. CA 32404
    # 'PRESTOP WG' with application history 'LALSTOP G46 WG') is NOT merged into the pilot product; it stays a
    # distinct, related product. Only the kit's canonical and historical names map to a pilot id.
    return idx


@lru_cache
def canonical_names() -> dict[str, str]:
    with (ROOT / "data" / "products.csv").open(encoding="utf-8-sig", newline="") as f:
        return {r["product_id"]: r["commercial_name"] for r in csv.DictReader(f) if r["product_id"].startswith("P-LPC-")}


def canonical_name_for(pid: str) -> str | None:
    return canonical_names().get(pid)


def product_id_for(name: str) -> str:
    n = norm_name(name)
    return pilot_name_index().get(n) or f"P-{n.replace(' ', '-')}"


@lru_cache
def _pilot_norm_names() -> set[str]:
    return {norm_name(n) for n in name_variants()}


@lru_cache
def _pilot_species_lower() -> list[str]:
    return [s.lower() for s in species_terms()]


def is_relevant(name: str | None, holder: str | None, active: str | None) -> bool:
    if holder and LALLEMAND.search(holder):
        return True
    if norm_name(name) in _pilot_norm_names():
        return True
    a = (active or "").lower()
    return any(sp in a for sp in _pilot_species_lower())


# --------------------------------------------------------------------------- batch
@dataclass
class Batch:
    source_id: str
    snapshot_id: int
    collected_at: dt.datetime
    products: dict[str, dict] = field(default_factory=dict)
    aliases: dict[str, dict] = field(default_factory=dict)
    registrations: list[dict] = field(default_factory=list)
    uses: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add_product(self, name: str, active_original: str | None, formulation_code: str | None = None,
                    url: str | None = None, country: str | None = None) -> str:
        pid = product_id_for(name)
        canonical = canonical_name_for(pid) or name.replace("®", "").strip()
        p = self.products.setdefault(pid, {
            "product_id": pid, "commercial_name": canonical,
            "active_entity_original": active_original or None,
            "active_entity_normalized": active_normalized(active_original),
            "strain": strain_of(active_original),
            "formulation_code": formulation_code or formulation_code_from_name(name),
            "is_synthetic": False, "validation_status": "automatically_extracted",
        })
        if norm_name(name) != norm_name(canonical) and url:
            # the source writes the pilot product under another (equivalent) name: keep that wording as an official alias
            self.add_alias(pid, name, "alternate_name", f"Name as written in the {self.source_id} record", url, country)
        return p["product_id"]

    def add_alias(self, product_id: str, alias: str, relationship: str, evidence: str, url: str,
                  country: str | None = None, confidence: float = 1.0) -> None:
        alias = alias.replace("®", "").strip().strip('"')
        if not alias or norm_name(alias) == norm_name(self.products.get(product_id, {}).get("commercial_name", "")):
            return
        aid = f"A-{product_id}-{slug(alias)}-{country or 'XX'}"
        self.aliases.setdefault(aid, {
            "alias_id": aid, "product_id": product_id, "alias_name": alias, "country_code": country,
            "relationship_type": relationship, "confidence": confidence, "evidence": evidence,
            "source_record_url": url, "review_status": "automatically_extracted", "is_synthetic": False,
        })

    def add_registration(self, registration_id: str, product_id: str, country: str, authority: str, number: str,
                         status_original: str | None, url: str, raw_document_id: int | None, method: str,
                         evidence: str, **extra) -> str:
        self.registrations.append({
            "registration_id": registration_id, "product_id": product_id, "country_code": country,
            "authority_name": authority, "registration_number": number, "status_original": status_original,
            "status_normalized": normalize_status(self.source_id, status_original),
            "source_id": self.source_id, "source_record_url": url, "collected_at": self.collected_at,
            "snapshot_id": self.snapshot_id, "raw_document_id": raw_document_id, "extraction_method": method,
            "evidence_excerpt": evidence, "confidence": 1.0, "validation_status": "automatically_extracted",
            "is_synthetic": False, "is_current": True, **extra,
        })
        return registration_id

    def add_use(self, use_id: str, registration_id: str, url: str, raw_document_id: int | None, method: str,
                evidence: str, **fields) -> None:
        self.uses.append({
            "use_id": use_id, "registration_id": registration_id, "source_record_url": url,
            "collected_at": self.collected_at, "raw_document_id": raw_document_id, "extraction_method": method,
            "evidence_excerpt": evidence, "confidence": 1.0, "validation_status": "automatically_extracted",
            "is_synthetic": False, "is_current": True, "pairing": "source_paired", **fields,
        })


class BaseParser:
    source_id: str = ""
    country: str = ""
    authority: str = ""

    def __init__(self, session: Session):
        self.session = session

    def latest_snapshot(self) -> Snapshot:
        snap = (self.session.query(Snapshot).filter_by(source_id=self.source_id, status="ok")
                .order_by(Snapshot.snapshot_id.desc()).first())
        if snap is None:
            raise RuntimeError(f"{self.source_id}: no successful snapshot; run scripts/collect.py first")
        return snap

    def docs(self, snapshot_id: int, kind: str | None = None, name_suffix: str | None = None) -> list[RawDocument]:
        q = self.session.query(RawDocument).filter_by(snapshot_id=snapshot_id)
        if kind:
            q = q.filter_by(document_kind=kind)
        docs = q.order_by(RawDocument.raw_document_id).all()
        if name_suffix:
            docs = [d for d in docs if d.local_path.replace("\\", "/").endswith(name_suffix)]
        return docs

    def new_batch(self, snap: Snapshot) -> Batch:
        ca = snap.collected_at
        if ca.tzinfo is None:  # SQLite returns naive datetimes; collectors always write UTC
            ca = ca.replace(tzinfo=dt.timezone.utc)
        return Batch(source_id=self.source_id, snapshot_id=snap.snapshot_id, collected_at=ca)

    def parse(self, snap: Snapshot | None = None) -> Batch:  # pragma: no cover - abstract
        raise NotImplementedError
