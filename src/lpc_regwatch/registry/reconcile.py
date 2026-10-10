"""Reconciliation of LPC's internal registration registry (SharePoint list, structure in
schema/registre_interne_colonnes_LPC.md) with the official sources in the canonical store.

LPC shared the structure only, with its imperfections: full country names, free-text actives, conventional dates
(12/31/2999 = no expiry), commercial status mixed with regulatory status, marketing crops that are not authorised
uses. This module (1) normalises each registry row into canonical fields while keeping every original value,
(2) matches it to official registrations by (country, number) then by (country, product name/alias), and
(3) reports agreements and discrepancies with the official evidence. Nothing is corrected automatically.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import DISCLAIMER, ROOT
from ..db.models import Product, ProductAlias, Registration
from ..normalize import canonical_active_entity
from ..parsers.base import norm_name

COUNTRY_ISO = {
    "canada": "CA", "united states": "US", "usa": "US", "united states of america": "US", "france": "FR", "brazil": "BR", "brasil": "BR",
    "germany": "DE", "belgium": "BE", "mexico": "MX", "uruguay": "UY", "spain": "ES", "italy": "IT", "netherlands": "NL", "the netherlands": "NL",
    "poland": "PL", "united kingdom": "GB", "uk": "GB", "portugal": "PT", "greece": "GR", "austria": "AT", "switzerland": "CH", "ireland": "IE",
    "denmark": "DK", "sweden": "SE", "finland": "FI", "norway": "NO", "czech republic": "CZ", "czechia": "CZ", "hungary": "HU", "romania": "RO",
    "bulgaria": "BG", "slovakia": "SK", "slovenia": "SI", "croatia": "HR", "lithuania": "LT", "latvia": "LV", "estonia": "EE", "turkey": "TR",
    "morocco": "MA", "south africa": "ZA", "australia": "AU", "new zealand": "NZ", "japan": "JP", "south korea": "KR", "korea": "KR", "china": "CN",
    "india": "IN", "argentina": "AR", "chile": "CL", "colombia": "CO", "peru": "PE", "ecuador": "EC", "costa rica": "CR", "guatemala": "GT",
}
NO_EXPIRY_YEARS = {"2999", "9999"}
NO_NUMBER = re.compile(r"no\s+registration\s+number|n/?a|none|-+", re.I)
REGISTRY_COLUMNS = ["Product_TS", "Title", "Trademark Name", "Country", "Registration Status", "Registration Number", "Registration Renewal Date",
                    "Renewal Submission Date", "Reg Type", "Regulatory Classification", "Product Category", "Registration Holder", "Company Name (label)",
                    "Declared Manufacturer", "Guaranteed Actives", "Formulation Code", "RegState Registered / Pending / Not Applicable", "Organic listing",
                    "Crops / Target / Application rate", "Status", "Shelf life (DECLARED)", "Packaging formats (DECLARED)"]
NON_PPP_CATEGORIES = {"fertilizer", "fertiliser", "soil amendment", "biostimulant", "bioestimulante"}


def _status_map() -> dict[str, str]:
    with (ROOT / "data" / "registry_status_mapping.csv").open(encoding="utf-8-sig", newline="") as f:
        return {r["registry_status_original"].strip().lower(): r["status_normalized"] for r in csv.DictReader(f)}


def _parse_date(s: str | None) -> tuple[str | None, str | None]:
    """Return (iso_date or None, flag). Conventional 12/31/2999 -> (None, 'no_expiry_convention')."""
    s = (s or "").strip()
    if not s:
        return None, None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%y"):
        try:
            d = dt.datetime.strptime(s, fmt)
            if str(d.year) in NO_EXPIRY_YEARS:
                return None, "no_expiry_convention"
            return d.strftime("%Y-%m-%d"), None
        except ValueError:
            continue
    return None, "unparsed_date"


def read_registry_file(data: bytes, filename: str = "registry.csv") -> list[dict]:
    """CSV (UTF-8/BOM or cp1252, ',' or ';') or XLSX export of the SharePoint list -> list of dict rows."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        return [{header[i]: ("" if v is None else str(v)) for i, v in enumerate(r) if i < len(header)} for r in rows[1:] if any(v not in (None, "") for v in r)]
    text = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    text = text or data.decode("utf-8", "replace")
    sep = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    return [dict(r) for r in csv.DictReader(io.StringIO(text), delimiter=sep)]


def normalize_registry_rows(rows: list[dict]) -> list[dict]:
    smap = _status_map()
    out = []
    for i, r in enumerate(rows, 1):
        g = lambda k: (r.get(k) or "").strip()  # noqa: E731
        flags: list[str] = []
        country_raw = g("Country")
        cc = COUNTRY_ISO.get(country_raw.lower()) or (country_raw.upper() if re.fullmatch(r"[A-Za-z]{2}", country_raw) else None)
        if not cc:
            flags.append("country_not_mapped")
        number_raw = g("Registration Number")
        number = None if (not number_raw or NO_NUMBER.fullmatch(number_raw)) else re.sub(r"\s+", "", number_raw)
        if number is None:
            flags.append("no_registration_number")
        expiry, flag = _parse_date(g("Registration Renewal Date"))
        if flag:
            flags.append(flag)
        status_raw = g("Registration Status")
        status_norm = smap.get(status_raw.lower(), "unknown")
        if status_norm == "unknown" and status_raw:
            flags.append("registry_status_not_mapped")
        pts = g("Product_TS")
        if not pts or pts.lower().startswith("(unassigned"):
            flags.append("product_unassigned")
            pts = ""
        if g("Reg Type").lower().startswith("sold without"):
            flags.append("sold_without_registration")
        if g("Product Category").lower() in NON_PPP_CATEGORIES:
            flags.append("not_a_ppp")
        sp, st, ae_norm, note = canonical_active_entity(g("Guaranteed Actives"))
        form_raw = g("Formulation Code")
        form = form_raw.split("-")[0].strip().upper() if form_raw else None
        out.append({
            "row": i, "product_ts": pts or None, "title": g("Title"), "trademark": g("Trademark Name") or None,
            "country_original": country_raw, "country_code": cc, "status_original": status_raw, "status_normalized": status_norm,
            "registration_number_original": number_raw, "registration_number": number, "expiration_date_original": g("Registration Renewal Date"),
            "expiration_date": expiry, "renewal_submission_date": g("Renewal Submission Date") or None, "reg_type": g("Reg Type") or None,
            "regulatory_classification_original": g("Regulatory Classification") or None, "product_category": g("Product Category") or None,
            "holder_original": g("Registration Holder") or None, "company_name_label": g("Company Name (label)") or None,
            "declared_manufacturer": g("Declared Manufacturer") or None, "active_entity_original": g("Guaranteed Actives") or None,
            "active_entity_normalized": ae_norm, "species": sp, "strain": st, "taxonomy_note": note,
            "formulation_original": form_raw or None, "formulation_code": form,
            "us_states": g("RegState Registered / Pending / Not Applicable").split() or None, "organic_listing": g("Organic listing") or None,
            "marketing_crops_targets_rate": g("Crops / Target / Application rate") or None, "commercial_status": g("Status") or None,
            "shelf_life_declared": g("Shelf life (DECLARED)") or None, "packaging_declared": g("Packaging formats (DECLARED)") or None,
            "is_synthetic": g("is_synthetic").lower() in ("true", "1", "yes", "oui"), "flags": flags,
        })
    return out


def _resolve_product(session: Session, names: list[str]) -> Product | None:
    for n in names:
        if not n:
            continue
        qn = norm_name(n)
        for p in session.query(Product):
            if norm_name(p.commercial_name) == qn:
                return p
        for a in session.query(ProductAlias):
            if norm_name(a.alias_name) == qn:
                return a.product
    return None


def _ev(reg: Registration) -> dict:
    return {"sourceId": reg.source_id, "sourceUrl": reg.source_record_url, "collectedAt": reg.collected_at.isoformat(),
            "validationStatus": reg.validation_status.value, "excerpt": reg.evidence_excerpt}


def reconcile(session: Session, rows: list[dict]) -> dict:
    """Match normalised registry rows with official registrations and list agreements / discrepancies."""
    results = []
    counts = {"matched_by_number": 0, "matched_by_name": 0, "not_found_in_source": 0, "source_not_collected": 0, "discrepancies": 0}
    covered = {r[0] for r in session.query(Registration.country_code).distinct()}
    for n in rows:
        res = {**n, "match": None, "official": None, "comparison": [], "evidence": None}
        cc = n["country_code"]
        product = _resolve_product(session, [n["product_ts"], n["title"], n["trademark"]])
        res["product_id"] = product.product_id if product else None
        res["product_name"] = product.commercial_name if product else None
        reg = None
        if cc and n["registration_number"]:
            cand = session.query(Registration).filter(Registration.country_code == cc).all()
            key = re.sub(r"[^0-9A-Za-z]", "", n["registration_number"]).lstrip("0").upper()
            reg = next((r for r in cand if re.sub(r"[^0-9A-Za-z]", "", r.registration_number or "").lstrip("0").upper() == key), None)
            if reg:
                res["match"] = "registration_number"
                counts["matched_by_number"] += 1
        if reg is None and cc and product:
            reg = next((r for r in product.registrations if r.country_code == cc), None)
            if reg:
                res["match"] = "product_name"
                counts["matched_by_name"] += 1
        if reg is None:
            if cc in covered:
                res["match"] = "not_found_in_source"
                counts["not_found_in_source"] += 1
                res["comparison"].append({"field": "registration", "registry": n["registration_number_original"] or "-", "official": None,
                                          "verdict": "not_found_in_source", "note": f"No official row in the collected source for {cc}; not proof of no registration."})
            else:
                res["match"] = "source_not_collected"
                counts["source_not_collected"] += 1
                res["comparison"].append({"field": "registration", "registry": n["registration_number_original"] or "-", "official": None,
                                          "verdict": "source_not_collected", "note": f"No official source connected for {cc or n['country_original']}: cannot confirm or contradict."})
            results.append(res)
            continue
        res["official"] = {"registrationId": reg.registration_id, "productId": reg.product_id, "productName": reg.product.commercial_name,
                           "registrationNumber": reg.registration_number, "statusOriginal": reg.status_original, "statusNormalized": reg.status_normalized.value,
                           "expirationDate": reg.expiration_date.strftime("%Y-%m-%d") if reg.expiration_date else None, "holder": reg.holder_original,
                           "activeEntityOriginal": reg.active_entity_original, "isCurrent": reg.is_current}
        res["evidence"] = _ev(reg)
        comp = res["comparison"]

        def cmp(field, rv, ov, equal, note=""):
            verdict = "agree" if equal else "discrepancy"
            if rv in (None, "") or ov in (None, ""):
                verdict = "not_comparable"
            comp.append({"field": field, "registry": rv, "official": ov, "verdict": verdict, "note": note})

        cmp("status", f"{n['status_original']} -> {n['status_normalized']}", f"{reg.status_original} -> {reg.status_normalized.value}",
            n["status_normalized"] == reg.status_normalized.value, "regulatory status only; the registry's commercial Status column is not compared")
        off_exp = reg.expiration_date.strftime("%Y-%m-%d") if reg.expiration_date else None
        if "no_expiry_convention" in n["flags"]:
            comp.append({"field": "expiration_date", "registry": n["expiration_date_original"], "official": off_exp, "verdict": "not_comparable",
                         "note": "12/31/2999 means 'no expiry' in the registry" + ("; official source carries no date either" if not off_exp else "; the official source gives a date")})
        else:
            cmp("expiration_date", n["expiration_date"], off_exp, n["expiration_date"] == off_exp)
        if product and reg.product_id != product.product_id:
            comp.append({"field": "product_identity", "registry": product.commercial_name, "official": reg.product.commercial_name, "verdict": "discrepancy",
                         "note": "the official number belongs to another product in the store (e.g. a related product); check the Product_TS link"})
        off_sp, off_st, off_norm, _ = canonical_active_entity(reg.active_entity_original)
        cmp("active_entity", n["active_entity_normalized"], off_norm, (n["active_entity_normalized"] or "").lower() == (off_norm or "").lower(),
            "species + strain compared after canonicalisation; concentration not compared")
        if n["holder_original"] and reg.holder_original:
            cmp("holder", n["holder_original"], reg.holder_original, norm_name(n["holder_original"]).split()[0] in norm_name(reg.holder_original),
                "first word of the holder name compared")
        if n["formulation_code"] and reg.product.formulation_code:
            cmp("formulation_code", n["formulation_code"], reg.product.formulation_code, n["formulation_code"] == reg.product.formulation_code)
        if any(c["verdict"] == "discrepancy" for c in comp):
            counts["discrepancies"] += 1
        results.append(res)
    return {"rows": results, "counts": counts, "total": len(results), "disclaimer": DISCLAIMER,
            "warnings": ["The internal registry is not compared on its commercial 'Status' nor on 'Crops / Target / Application rate' (marketing, not authorised uses).",
                         "A discrepancy is a signal for Regulatory Affairs; nothing is corrected automatically. 'not_found_in_source' is not proof of no registration."]}


def sample_rows() -> list[dict]:
    p = ROOT / "data" / "synthetic" / "lpc_internal_registry_sample.csv"
    return read_registry_file(p.read_bytes(), p.name)
