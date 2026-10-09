"""Read-side queries used by both the REST endpoints and the /ask tools.

Every function returns plain dicts shaped like the API schemas, with evidence attached to each
regulatory assertion. No LLM here; this is the only place the agent gets facts from (G3).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from ..config import DISCLAIMER
from ..db.models import AuthorizedUse, ChangeLog, Product, ProductAlias, Registration, RegStatus, Source
from ..parsers.base import norm_name

COUNTRY_SOURCES = {"CA": "CA-PPID", "US": "US-EPA-PPLS", "FR": "FR-EPHY", "BR": "BR-AGROFIT"}
COUNTRY_NAMES = {"CA": "Canada", "US": "United States", "FR": "France", "BR": "Brazil", "DE": "Germany", "BE": "Belgium",
                 "UY": "Uruguay", "MX": "Mexico", "ES": "Spain", "IT": "Italy", "NL": "Netherlands", "PL": "Poland", "GB": "United Kingdom"}


def _utc(d: dt.datetime | None) -> dt.datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _date(d) -> str | None:
    return d.strftime("%Y-%m-%d") if d else None


def evidence_of(obj, source_id: str | None = None) -> dict:
    return {"sourceId": source_id or getattr(obj, "source_id", None) or "", "sourceUrl": obj.source_record_url,
            "collectedAt": _utc(obj.collected_at), "validationStatus": obj.validation_status.value,
            "excerpt": obj.evidence_excerpt, "extractionMethod": obj.extraction_method.value if obj.extraction_method else None,
            "confidence": obj.confidence, "snapshotId": getattr(obj, "snapshot_id", None)}


def use_dict(u: AuthorizedUse, source_id: str) -> dict:
    return {"useId": u.use_id, "cropOriginal": u.crop_name_original, "cropNormalized": u.crop_name_normalized,
            "eppoCropCode": u.eppo_crop_code, "eppoCropStatus": u.eppo_crop_status, "targetOriginal": u.target_name_original,
            "targetNormalized": u.target_name_normalized, "eppoTargetCode": u.eppo_target_code, "eppoTargetStatus": u.eppo_target_status,
            "applicationMethod": u.application_method, "doseValue": u.dose_value, "doseUnitOriginal": u.dose_unit_original,
            "doseValueNormalized": u.dose_value_normalized, "doseUnitNormalized": u.dose_unit_normalized,
            "maxApplications": u.max_applications, "phiDays": u.phi_days, "growthStageMin": u.growth_stage_min,
            "growthStageMax": u.growth_stage_max, "restrictionsOriginal": u.restrictions_original, "pairing": u.pairing,
            "evidence": evidence_of(u, source_id)}


def registration_dict(r: Registration, with_uses: bool = True, max_uses: int | None = None) -> dict:
    uses = sorted(r.uses, key=lambda x: (x.crop_name_normalized or x.crop_name_original or "", x.use_id)) if with_uses else []
    if max_uses is not None:
        uses = uses[:max_uses]
    return {"registrationId": r.registration_id, "productId": r.product_id, "countryCode": r.country_code,
            "authorityName": r.authority_name, "registrationNumber": r.registration_number, "statusOriginal": r.status_original,
            "statusNormalized": r.status_normalized.value, "approvalDate": _date(r.approval_date), "expirationDate": _date(r.expiration_date),
            "holderOriginal": r.holder_original, "activeEntityOriginal": r.active_entity_original,
            "formulationOriginal": r.formulation_original, "isCurrent": r.is_current, "usesCount": len(r.uses),
            "uses": [use_dict(u, r.source_id) for u in uses], "evidence": evidence_of(r)}


def product_dict(p: Product, matched_on: str | None = None) -> dict:
    return {"productId": p.product_id, "commercialName": p.commercial_name, "activeEntityOriginal": p.active_entity_original,
            "activeEntityNormalized": p.active_entity_normalized, "formulationCode": p.formulation_code, "isSynthetic": p.is_synthetic,
            "strain": p.strain, "countries": sorted({r.country_code for r in p.registrations}), "matchedOn": matched_on}


# --------------------------------------------------------------------------- search
def search_products(session: Session, q: str | None, limit: int = 50) -> list[dict]:
    """Match on commercial name, any alias (official or hypothesis) or active entity; exact-ish, no fuzzy guessing."""
    base = session.query(Product).options(selectinload(Product.registrations))
    if not q or not q.strip():
        return [product_dict(p) for p in base.order_by(Product.commercial_name).limit(limit)]
    qn = norm_name(q)
    like = f"%{q.strip()}%"
    out: dict[str, dict] = {}
    for p in base.filter(Product.commercial_name.ilike(like)).limit(limit):
        out[p.product_id] = product_dict(p, "name")
    for p in base.filter(Product.product_id.in_(
            session.query(ProductAlias.product_id).filter(ProductAlias.alias_name.ilike(like)))).limit(limit):
        out.setdefault(p.product_id, product_dict(p, "alias"))
    for p in base.filter(or_(Product.active_entity_normalized.ilike(like), Product.active_entity_original.ilike(like))).limit(limit):
        out.setdefault(p.product_id, product_dict(p, "active_entity"))
    # exact normalized name wins ordering
    return sorted(out.values(), key=lambda d: (norm_name(d["commercialName"]) != qn, d["matchedOn"] != "name", d["commercialName"]))


def resolve_product(session: Session, name_or_id: str) -> Product | None:
    p = session.get(Product, name_or_id)
    if p:
        return p
    qn = norm_name(name_or_id)
    for p in session.query(Product):
        if norm_name(p.commercial_name) == qn:
            return p
    a = next((a for a in session.query(ProductAlias) if norm_name(a.alias_name) == qn), None)
    return a.product if a else None


# --------------------------------------------------------------------------- registrations / compare
def registrations_for(session: Session, product_id: str, country: str | None = None, with_uses: bool = True) -> list[dict]:
    q = session.query(Registration).options(selectinload(Registration.uses)).filter(Registration.product_id == product_id)
    if country:
        q = q.filter(Registration.country_code == country.upper())
    return [registration_dict(r, with_uses) for r in q.order_by(Registration.country_code, Registration.registration_number)]


def source_collected_at(session: Session, source_id: str) -> dt.datetime | None:
    v = session.query(func.max(Registration.collected_at)).filter(Registration.source_id == source_id).scalar()
    return _utc(v)


def coverage_for(session: Session, product_id: str, countries: list[str], regs: list[dict]) -> tuple[list[dict], list[str]]:
    """Explain, per requested country, whether we found a row, looked and found nothing, or never collected that market."""
    cov: list[dict] = []
    warnings: list[str] = []
    found = {r["countryCode"] for r in regs}
    for cc in countries:
        src = COUNTRY_SOURCES.get(cc)
        name = COUNTRY_NAMES.get(cc, cc)
        if cc in found:
            cov.append({"countryCode": cc, "sourceId": src, "collectedAt": source_collected_at(session, src) if src else None,
                        "coverage": "found", "note": f"{len([r for r in regs if r['countryCode'] == cc])} registration(s) found in {src}"})
        elif src:
            at = source_collected_at(session, src)
            cov.append({"countryCode": cc, "sourceId": src, "collectedAt": at, "coverage": "not_found_in_source",
                        "note": f"No row for this product in {src} (collected {at:%Y-%m-%d} UTC). Not proof of no registration: "
                                f"name variants, distributor registrations or a newer approval may exist."})
            warnings.append(f"{name} ({cc}): not found in {src} as of {at:%Y-%m-%d} - this is not proof of no registration.")
        else:
            cov.append({"countryCode": cc, "sourceId": None, "collectedAt": None, "coverage": "source_not_collected",
                        "note": f"No official source for {name} is connected in this prototype; nothing can be said about {cc}."})
            warnings.append(f"{name} ({cc}): no source connected - unknown, not 'not registered'.")
    return cov, warnings


def quality_warnings(regs: list[dict]) -> list[str]:
    w: list[str] = []
    for r in regs:
        cc = r["countryCode"]
        if r["usesCount"] and all(u["doseValue"] is None for u in r["uses"]):
            w.append(f"{cc} {r['registrationNumber']}: dose is not in the structured source; only the official label PDF states it.")
        if any(u["pairing"] == "unpaired_lists" for u in r["uses"]):
            w.append(f"{cc} {r['registrationNumber']}: the source lists crops and targets as two independent lists; crop-target pairs are not asserted by the source.")
        if any(u["pairing"] == "llm_paired" for u in r["uses"]):
            w.append(f"{cc} {r['registrationNumber']}: some uses were extracted from the label PDF by an AI model (extraction_method=llm_pdf) and are not yet validated.")
        if r["approvalDate"] is None and r["expirationDate"] is None:
            w.append(f"{cc} {r['registrationNumber']}: no approval or expiry date in the structured source.")
        if r["statusNormalized"] == "unknown":
            w.append(f"{cc} {r['registrationNumber']}: status '{r['statusOriginal']}' is not in the status mapping table -> unknown.")
        if not r["isCurrent"]:
            w.append(f"{cc} {r['registrationNumber']}: no longer listed by the source in the latest snapshot (not a withdrawal statement).")
        if r["evidence"]["validationStatus"] == "automatically_extracted":
            w.append(f"{cc} {r['registrationNumber']}: automatically extracted, not yet validated by Regulatory Affairs.")
    return list(dict.fromkeys(w))


def compare(session: Session, product_id: str, countries: list[str], max_uses_per_registration: int | None = None) -> dict:
    p = session.get(Product, product_id)
    regs = [registration_dict(r, True, max_uses_per_registration) for r in
            session.query(Registration).options(selectinload(Registration.uses))
            .filter(Registration.product_id == product_id, Registration.country_code.in_(countries))
            .order_by(Registration.country_code, Registration.registration_number)]
    cov, warnings = coverage_for(session, product_id, countries, regs)
    warnings += quality_warnings(regs)
    return {"productId": product_id, "commercialName": p.commercial_name if p else None, "countries": countries,
            "registrations": regs, "coverage": cov, "warnings": warnings, "disclaimer": DISCLAIMER}


# --------------------------------------------------------------------------- aliases / sisters
def aliases_for(session: Session, product_id: str, relationship: str | None = None) -> list[dict]:
    q = session.query(ProductAlias).filter(ProductAlias.product_id == product_id)
    out = []
    for a in q.order_by(ProductAlias.relationship_type, ProductAlias.alias_name):
        if relationship and a.relationship_type.value != relationship:
            continue
        out.append({"aliasId": a.alias_id, "productId": a.product_id, "aliasName": a.alias_name, "countryCode": a.country_code,
                    "relationshipType": a.relationship_type.value, "confidence": a.confidence, "evidence": a.evidence,
                    "sourceRecordUrl": a.source_record_url, "reviewStatus": a.review_status.value})
    return out


# --------------------------------------------------------------------------- active entity / crop search
def products_by_active_entity(session: Session, species: str, crop: str | None = None, countries: list[str] | None = None) -> list[dict]:
    """Products whose canonical active entity contains `species`; optionally restricted to a crop wording (normalized or original)."""
    like = f"%{species.strip()}%"
    q = (session.query(Registration).options(selectinload(Registration.uses), selectinload(Registration.product))
         .join(Product).filter(or_(Product.active_entity_normalized.ilike(like), Product.active_entity_original.ilike(like),
                                   Registration.active_entity_original.ilike(like))))
    if countries:
        q = q.filter(Registration.country_code.in_(countries))
    out = []
    for r in q.order_by(Registration.country_code, Registration.registration_number):
        uses = r.uses
        if crop:
            cl = crop.strip().lower()
            uses = [u for u in r.uses if cl in (u.crop_name_normalized or "").lower() or cl in (u.crop_name_original or "").lower()]
            if not uses:
                continue
        d = registration_dict(r, False)
        d["productName"] = r.product.commercial_name
        d["activeEntityNormalized"] = r.product.active_entity_normalized
        d["matchingUses"] = [use_dict(u, r.source_id) for u in uses[:10]]
        d["matchingUsesCount"] = len(uses)
        out.append(d)
    return out


# --------------------------------------------------------------------------- expiry / changes / quality
def expiring(session: Session, months: int = 12, reference: dt.date | None = None) -> list[dict]:
    ref = reference or dt.date.today()
    limit = ref + dt.timedelta(days=int(months * 30.44))
    # only registrations that are active today and whose expiry falls inside the window; a FR 'date de retrait'
    # on a withdrawn product is a past event, not an upcoming expiry
    q = (session.query(Registration).options(selectinload(Registration.product))
         .filter(Registration.expiration_date.isnot(None), Registration.expiration_date <= dt.datetime.combine(limit, dt.time()),
                 Registration.expiration_date >= dt.datetime.combine(ref, dt.time()), Registration.status_normalized == RegStatus.active,
                 Registration.is_current.is_(True)).order_by(Registration.expiration_date))
    out = []
    for r in q:
        d = registration_dict(r, False)
        d["productName"] = r.product.commercial_name
        d["daysLeft"] = (r.expiration_date.date() - ref).days
        out.append(d)
    return out


def changes(session: Session, limit: int = 200) -> list[dict]:
    return [{"changeId": c.change_id, "entityType": c.entity_type, "entityId": c.entity_id, "field": c.field, "oldValue": c.old_value,
             "newValue": c.new_value, "fromSnapshotId": c.from_snapshot_id, "toSnapshotId": c.to_snapshot_id, "detectedAt": _utc(c.detected_at)}
            for c in session.query(ChangeLog).order_by(ChangeLog.detected_at.desc(), ChangeLog.change_id.desc()).limit(limit)]


def data_quality(session: Session, product_id: str) -> dict:
    """Which fields are missing or uncertain for a product, per registration, with validation status."""
    regs = registrations_for(session, product_id, with_uses=True)
    issues = []
    for r in regs:
        missing = [f for f in ("approvalDate", "expirationDate", "formulationOriginal", "holderOriginal") if not r.get(f)]
        uses = r["uses"]
        if uses:
            if all(u["doseValue"] is None for u in uses):
                missing.append("dose (all uses)")
            unmapped = sum(1 for u in uses if u["eppoCropCode"] is None)
            if unmapped:
                missing.append(f"eppoCropCode ({unmapped}/{len(uses)} uses unmapped or list)")
            llm = sum(1 for u in uses if u["pairing"] == "llm_paired")
            if llm:
                missing.append(f"{llm} use(s) extracted by AI from the label PDF, to verify")
        else:
            missing.append("uses (none in source)")
        issues.append({"registrationId": r["registrationId"], "countryCode": r["countryCode"], "validationStatus": r["evidence"]["validationStatus"],
                       "statusNormalized": r["statusNormalized"], "missingOrUncertain": missing,
                       "pairing": sorted({u["pairing"] for u in uses}) if uses else [], "evidence": r["evidence"]})
    return {"productId": product_id, "registrations": issues, "warnings": quality_warnings(regs), "disclaimer": DISCLAIMER}


def sources_summary(session: Session) -> list[dict]:
    out = []
    for s in session.query(Source).order_by(Source.source_id):
        n = session.query(func.count(Registration.registration_id)).filter(Registration.source_id == s.source_id).scalar()
        out.append({"sourceId": s.source_id, "officialName": s.official_name, "countryOrRegion": s.country_or_region, "baseUrl": s.base_url,
                    "accessMethod": s.access_method, "dataFormat": s.data_format, "licenseName": s.license_name,
                    "accessAndReuseLimits": s.access_and_reuse_limits, "manualValidationRequired": s.manual_validation_required,
                    "registrations": n, "lastCollectedAt": source_collected_at(session, s.source_id), "notes": s.notes})
    return out
