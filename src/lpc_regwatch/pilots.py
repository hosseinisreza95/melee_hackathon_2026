"""Pilot products and the search terms derived from the starter-kit mapping files.

Why: the challenge says the MVP must not depend on one exact commercial name per source.
We therefore search every source by (a) every known name variant and (b) the active
microorganism species, both read from the CSVs in data/ so the list is transparent and editable.
"""
from __future__ import annotations

import csv
from functools import lru_cache

from .config import ROOT

DATA = ROOT / "data"


def _rows(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@lru_cache
def pilot_product_ids() -> list[str]:
    return [r["product_id"] for r in _rows("products.csv") if r["product_id"].startswith("P-LPC-")]


@lru_cache
def name_variants() -> list[str]:
    """All commercial-name variants (canonical, historical, sister candidates) for pilot products."""
    names = {r["commercial_name"] for r in _rows("products.csv") if r["product_id"] in pilot_product_ids()}
    names |= {r["name_variant"] for r in _rows("product_name_mapping.csv") if r["product_id"] in pilot_product_ids()}
    names |= {r["alias_name"] for r in _rows("product_aliases.csv") if r["product_id"] in pilot_product_ids()}
    return sorted(n.strip() for n in names if n and n.strip())


@lru_cache
def species_terms() -> list[str]:
    """Genus + species (current and former taxonomic names) for the pilot microorganisms."""
    out: set[str] = set()
    for r in _rows("active_entity_mapping.csv"):
        if r["product_id"] not in pilot_product_ids():
            continue
        for field in ("canonical_species", "name_variant"):
            words = (r.get(field) or "").split()
            if len(words) >= 2:
                out.add(" ".join(words[:2]))  # 'Metarhizium anisopliae var. ...' -> 'Metarhizium anisopliae'
    return sorted(out)


@lru_cache
def short_name_tokens() -> list[str]:
    """Distinctive tokens for substring searches (EPA partial-name endpoint)."""
    toks: set[str] = set()
    for n in name_variants():
        for w in n.replace("®", " ").split():
            if len(w) >= 5 and w.isalnum() and sum(ch.isalpha() for ch in w) >= 3:  # keeps MET52, drops 'WG'/'4B'
                toks.add(w.upper())
    return sorted(toks)
