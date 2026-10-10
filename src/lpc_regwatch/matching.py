"""Step 3: normalisation of stored rows + product identity across markets + sister-product hypotheses.

Three strictly separated levels of certainty (MAPPING_README, SPEC M5/N5):
1. `link_official_equivalents`: a registration that carries a pilot name as alternate/historical name
   (EPA altbrandnames, PPID application history) links its product to the pilot as `related_product`
   with the official field as evidence - it is NOT merged (LPC, 2026-10-10: PRESTOP WG CA 32404 is a
   distinct product from LALSTOP G46 WG). E-Phy "seconds noms commerciaux" stay plain alternate names
   of the same AMM.
   `load_curated_relations`: statements made by LPC (data/lpc_curated_relations.csv) are applied last and
   override hypotheses with the same name.
2. `load_starter_candidates`: hypotheses provided by LPC in product_name_mapping.csv -> aliases with the kit's
   confidence and review_status (never upgraded by us).
3. `propose_sister_candidates`: same canonical species AND same strain, different registration/name ->
   `sister_product_candidate`, review_status=to_verify, confidence by rule. Species alone never proposes.
"""
from __future__ import annotations

import csv
import logging

from sqlalchemy.orm import Session

from .config import ROOT
from .db.models import AliasRelation, AuthorizedUse, ChangeLog, Product, ProductAlias, Registration, ValidationStatus
from .normalize import canonical_active_entity, normalize_crop, normalize_dose, normalize_target
from .parsers.base import norm_name, pilot_name_index, slug
from .pilots import pilot_product_ids

log = logging.getLogger(__name__)
LALLEMAND = ("DANSTAR", "LALLEMAND")


# --------------------------------------------------------------------------- 0. row normalisation
def apply_normalization(session: Session) -> dict[str, int]:
    stats = {"uses": 0, "crop_mapped": 0, "target_mapped": 0, "dose_normalized": 0, "products": 0, "taxonomy_synonyms": 0}
    for u in session.query(AuthorizedUse).yield_per(2000):
        stats["uses"] += 1
        c = normalize_crop(u.crop_name_original)
        u.crop_name_normalized, u.eppo_crop_code, u.eppo_crop_status = c.normalized, c.eppo_code, c.status
        stats["crop_mapped"] += bool(c.eppo_code)
        t = normalize_target(u.target_name_original)
        u.target_name_normalized, u.eppo_target_code, u.eppo_target_status = t.normalized, t.eppo_code, t.status
        stats["target_mapped"] += bool(t.eppo_code)
        v, unit = normalize_dose(u.dose_value, u.dose_unit_original)
        u.dose_value_normalized, u.dose_unit_normalized = v, unit
        stats["dose_normalized"] += v is not None
    for p in session.query(Product):
        stats["products"] += 1
        # prefer the most explicit wording among this product's registrations (longest original)
        originals = [r.active_entity_original for r in p.registrations if r.active_entity_original] or [p.active_entity_original]
        best = max((o for o in originals if o), key=len, default=None)
        sp, st, norm, note = canonical_active_entity(best)
        if norm:
            p.active_entity_normalized = norm
        if st:
            p.strain = st
        if note:
            stats["taxonomy_synonyms"] += 1
    session.commit()
    return stats


# --------------------------------------------------------------------------- 1. official name links (no merge)
def link_official_equivalents(session: Session) -> list[str]:
    """A non-pilot product whose OFFICIAL alias (same registration) is a pilot name becomes a `related_product`
    of that pilot - never merged (LPC answer 2026-10-10: PRESTOP WG CA 32404 is not LALSTOP G46 WG)."""
    pilots = set(pilot_product_ids())
    pilot_idx = pilot_name_index()
    out: list[str] = []
    for prod in list(session.query(Product).filter(~Product.product_id.in_(pilots))):
        for a in prod.aliases:
            if a.relationship_type not in (AliasRelation.alternate_name, AliasRelation.historical_name):
                continue
            pid = pilot_idx.get(norm_name(a.alias_name))
            if pid not in pilots:
                continue
            pilot = session.get(Product, pid)
            regs = list(prod.registrations)
            if not regs:
                continue
            cc = regs[0].country_code
            aid = f"A-{pid}-{slug(prod.commercial_name)}-{cc}"
            existing = session.get(ProductAlias, aid)
            evidence = (f"Official registration {regs[0].registration_number} ({cc}) of '{prod.commercial_name}' also carries the name "
                        f"'{a.alias_name}' ({a.evidence}). Distinct product, not merged (LPC guidance 2026-10-10).")
            if existing is None:
                session.add(ProductAlias(alias_id=aid, product_id=pid, alias_name=prod.commercial_name, country_code=cc,
                                         relationship_type=AliasRelation.related_product, confidence=0.9, evidence=evidence,
                                         source_record_url=regs[0].source_record_url, review_status=ValidationStatus.to_verify))
                out.append(f"{pilot.commercial_name} <- related: {prod.commercial_name} ({cc} {regs[0].registration_number})")
            break
    session.commit()
    return out


def load_curated_relations(session: Session) -> int:
    """Relations stated by LPC itself (data/lpc_curated_relations.csv): they override kit hypotheses and automatic links
    with the same alias name on the same product, and are the only rows allowed to be `validated` without a review log entry."""
    path = ROOT / "data" / "lpc_curated_relations.csv"
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if session.get(Product, r["product_id"]) is None:
                continue
            rel = AliasRelation(r["relationship_type"])
            same = [a for a in session.query(ProductAlias).filter(ProductAlias.product_id == r["product_id"])
                    if norm_name(a.alias_name) == norm_name(r["alias_name"])]
            if same:
                a = same[0]
                for extra in same[1:]:
                    session.delete(extra)
                a.relationship_type, a.confidence, a.evidence = rel, float(r["confidence"]), r["evidence"]
                a.review_status, a.country_code = ValidationStatus(r["review_status"]), r["country_code"] or a.country_code
                a.source_record_url = r["source_record_url"] or a.source_record_url
            else:
                session.add(ProductAlias(alias_id=f"A-{r['product_id']}-{slug(r['alias_name'])}-LPC", product_id=r["product_id"],
                                         alias_name=r["alias_name"], country_code=r["country_code"] or None, relationship_type=rel,
                                         confidence=float(r["confidence"]), evidence=r["evidence"], source_record_url=r["source_record_url"] or None,
                                         review_status=ValidationStatus(r["review_status"])))
            n += 1
    session.commit()
    return n


# --------------------------------------------------------------------------- 2. starter hypotheses
def load_starter_candidates(session: Session) -> int:
    n = 0
    rel_map = {"sister_product_candidate": AliasRelation.sister_product_candidate, "related_formulation": AliasRelation.related_formulation,
               "historical_or_market_name": AliasRelation.historical_name}
    with (ROOT / "data" / "product_name_mapping.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rel = rel_map.get(r["relationship_type"])
            if rel is None or r["review_status"] == "validated" and rel == AliasRelation.historical_name:
                continue
            pid = r["product_id"]
            if session.get(Product, pid) is None:
                continue
            aid = f"A-{pid}-{slug(r['name_variant'])}-KIT"
            if session.get(ProductAlias, aid) is not None:
                continue
            status = ValidationStatus.validated if r["review_status"] == "validated" else ValidationStatus.to_verify
            session.add(ProductAlias(alias_id=aid, product_id=pid, alias_name=r["name_variant"],
                                     country_code=r["market_or_country"] if len(r["market_or_country"]) == 2 else None,
                                     relationship_type=rel, confidence=float(r["confidence_score"]),
                                     evidence=f"LPC starter kit {r['mapping_id']} ({r['evidence_type']}): {r['evidence_summary']}",
                                     source_record_url=None, review_status=status))
            n += 1
    session.commit()
    return n


# --------------------------------------------------------------------------- 3. sister candidates from data
def propose_sister_candidates(session: Session) -> list[str]:
    out: list[str] = []
    pilots = [session.get(Product, pid) for pid in pilot_product_ids()]
    for pilot in pilots:
        if not pilot or not pilot.active_entity_normalized or not pilot.strain:
            continue
        existing = {norm_name(a.alias_name) for a in pilot.aliases}
        for other in session.query(Product).filter(Product.product_id != pilot.product_id,
                                                   Product.active_entity_normalized == pilot.active_entity_normalized):
            if norm_name(other.commercial_name) in existing:
                continue
            regs = list(other.registrations)
            if not regs:
                continue
            holders = {(r.holder_original or "").upper() for r in regs}
            same_group = any(any(k in h for k in LALLEMAND) for h in holders)
            technical = "TECHNICAL" in other.commercial_name.upper()
            conf = 0.8 if same_group else 0.6
            if technical:
                conf = 0.3
            countries = sorted({r.country_code for r in regs})
            numbers = ", ".join(f"{r.country_code} {r.registration_number}" for r in regs[:4])
            evidence = (f"Same active entity '{pilot.active_entity_normalized}' (species + strain) in {', '.join(countries)} "
                        f"[{numbers}]; registrant(s): {', '.join(sorted(h for h in holders if h))}; "
                        f"different commercial name and registration -> hypothesis, not identity"
                        + ("; technical-grade product, not a commercial sister" if technical else ""))
            aid = f"A-{pilot.product_id}-{slug(other.commercial_name)}-{countries[0]}"
            if session.get(ProductAlias, aid) is None:
                session.add(ProductAlias(alias_id=aid, product_id=pilot.product_id, alias_name=other.commercial_name,
                                         country_code=countries[0] if len(countries) == 1 else None,
                                         relationship_type=AliasRelation.sister_product_candidate, confidence=conf, evidence=evidence,
                                         source_record_url=regs[0].source_record_url, review_status=ValidationStatus.to_verify))
                existing.add(norm_name(other.commercial_name))
                out.append(f"{pilot.product_id}: {other.commercial_name} ({', '.join(countries)}, conf {conf})")
    session.commit()
    return out


def run_all(session: Session) -> dict:
    report: dict = {}
    report["normalization"] = apply_normalization(session)
    report["official_links"] = link_official_equivalents(session)
    report["starter_candidates_added"] = load_starter_candidates(session)
    report["sister_candidates"] = propose_sister_candidates(session)
    report["lpc_curated_relations"] = load_curated_relations(session)  # last: LPC's own statements win
    return report
