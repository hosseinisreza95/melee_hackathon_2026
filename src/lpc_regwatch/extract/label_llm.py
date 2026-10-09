"""Step 7: AI-assisted extraction of authorised uses (crop, target, dose, restrictions) from official label PDFs.

Why: in Canada and the United States the structured sources give crops and pests as unpaired lists and no
dose; the dose exists only in the label PDF. This module reads the PDF text (PyMuPDF) and asks the LLM for a
strict JSON list of uses. Anti-hallucination gate: every returned row must quote a verbatim excerpt of the PDF
text (`evidence_excerpt`); rows whose excerpt is not found in the PDF are REJECTED and counted. Accepted rows
become `uses` with extraction_method=llm_pdf, pairing=llm_paired, validation_status=automatically_extracted,
confidence from the model, and raw_document_id pointing at the stored PDF. Results are cached by PDF sha256.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import ROOT, settings
from ..db.models import AuthorizedUse, ExtractionMethod, RawDocument, Registration, ValidationStatus
from ..llm import LLMUnavailable, get_client
from ..normalize import normalize_crop, normalize_dose, normalize_target

log = logging.getLogger(__name__)
CACHE = ROOT / "data" / "processed" / "label_extractions"

SCHEMA = {
    "type": "object",
    "properties": {
        "product_name_on_label": {"type": ["string", "null"]},
        "epa_registration_number_on_label": {"type": ["string", "null"]},
        "uses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "crop": {"type": "string", "description": "crop or use site exactly as written"},
                    "target": {"type": ["string", "null"], "description": "pest/disease exactly as written, null if not stated for this row"},
                    "application_method": {"type": ["string", "null"]},
                    "dose_value": {"type": ["number", "null"]},
                    "dose_unit": {"type": ["string", "null"], "description": "unit exactly as written, e.g. 'lb/acre', 'oz/1000 sq ft'"},
                    "dose_text": {"type": ["string", "null"], "description": "the dose as written, e.g. '1-2 lbs per acre'"},
                    "max_applications": {"type": ["integer", "null"]},
                    "application_interval_days": {"type": ["number", "null"]},
                    "phi_days": {"type": ["number", "null"]},
                    "rei_hours": {"type": ["number", "null"]},
                    "restrictions": {"type": ["string", "null"]},
                    "evidence_excerpt": {"type": "string", "description": "VERBATIM substring (20-300 chars) copied from the label text that supports this row"},
                    "page": {"type": ["integer", "null"]},
                    "confidence": {"type": "number"},
                },
                "required": ["crop", "evidence_excerpt", "confidence"],
            },
        },
    },
    "required": ["uses"],
}

SYSTEM = """You extract authorised uses from an official pesticide LABEL text for a regulatory database.
Return JSON only, matching the schema. Rules:
- One row per (crop or use site, target, dose) combination that the label states. Do not merge rows.
- Copy wording EXACTLY as written for crop, target, unit; convert nothing. dose_value is the maximum single value when a range is given
  (put the full range in dose_text).
- evidence_excerpt MUST be a verbatim, contiguous substring of the provided text (20-300 characters) containing the dose or the crop row.
  If you cannot quote it verbatim, do not output the row.
- Never infer a dose from another crop. Never output a crop that is not in the text.
- confidence in [0,1]: 0.9+ when crop, target and dose are in the same table row; lower when you had to associate across lines.
- Ignore first-aid, storage, disposal and marketing sections."""


def pdf_text(path: str | Path) -> list[str]:
    import pymupdf

    with pymupdf.open(str(path)) as doc:
        return [page.get_text() for page in doc]


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def excerpt_found(excerpt: str, pages: list[str]) -> int | None:
    """Return the 1-based page where the (whitespace-normalised) excerpt occurs, else None."""
    e = _norm_ws(excerpt)
    if len(e) < 12:
        return None
    for i, p in enumerate(pages, 1):
        if e in _norm_ws(p):
            return i
    full = _norm_ws(" ".join(pages))
    return 0 if e in full else None  # 0 = found across a page break


def extract_label(pdf_path: str | Path, model: str | None = None, force: bool = False) -> dict:
    pdf_path = Path(pdf_path)
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / f"{sha}.json"
    if cache_file.exists() and not force:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    pages = pdf_text(pdf_path)
    text = "\n\n".join(f"=== PAGE {i} ===\n{p}" for i, p in enumerate(pages, 1))
    client = get_client()
    if model:
        client.model = model
    raw = client.chat_json(SYSTEM, f"LABEL FILE: {pdf_path.name}\n\n{text[:180000]}", schema=SCHEMA, max_tokens=12000)
    accepted, rejected = [], []
    for row in raw.get("uses", []):
        page = excerpt_found(row.get("evidence_excerpt", ""), pages)
        if page is None:
            rejected.append({**row, "reject_reason": "evidence_excerpt not found verbatim in PDF text"})
            continue
        if not row.get("crop"):
            rejected.append({**row, "reject_reason": "no crop"})
            continue
        if row.get("page") in (None, 0) and page:
            row["page"] = page
        accepted.append(row)
    result = {"pdf": pdf_path.name, "sha256": sha, "model": client.model, "pages": len(pages), "chars": sum(len(p) for p in pages),
              "product_name_on_label": raw.get("product_name_on_label"), "epa_registration_number_on_label": raw.get("epa_registration_number_on_label"),
              "accepted": accepted, "rejected": rejected, "n_returned": len(raw.get("uses", [])), "usage": None}
    cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def load_label_uses(session: Session, result: dict, raw_doc: RawDocument, registration: Registration) -> int:
    """Insert accepted rows as llm_pdf uses of `registration`; replaces earlier llm_pdf rows of that registration/PDF."""
    old = (session.query(AuthorizedUse).filter(AuthorizedUse.registration_id == registration.registration_id,
                                              AuthorizedUse.extraction_method == ExtractionMethod.llm_pdf).all())
    for u in old:
        session.delete(u)
    session.flush()
    n = 0
    for i, row in enumerate(result["accepted"], 1):
        c = normalize_crop(row.get("crop"))
        t = normalize_target(row.get("target"))
        v, unit = normalize_dose(row.get("dose_value"), row.get("dose_unit"))
        session.add(AuthorizedUse(
            use_id=f"U-{registration.registration_id}-LBL{i}", registration_id=registration.registration_id,
            crop_name_original=row.get("crop"), crop_name_normalized=c.normalized, eppo_crop_code=c.eppo_code, eppo_crop_status=c.status,
            target_name_original=row.get("target"), target_name_normalized=t.normalized, eppo_target_code=t.eppo_code, eppo_target_status=t.status,
            application_method=row.get("application_method"), dose_value=row.get("dose_value"), dose_unit_original=row.get("dose_unit"),
            dose_value_normalized=v, dose_unit_normalized=unit, max_applications=row.get("max_applications"),
            application_interval_days=row.get("application_interval_days"), phi_days=row.get("phi_days"), rei_hours=row.get("rei_hours"),
            restrictions_original=(f"dose as written: {row['dose_text']}. " if row.get("dose_text") else "") + (row.get("restrictions") or "") or None,
            pairing="llm_paired", source_record_url=raw_doc.url, collected_at=raw_doc.collected_at, raw_document_id=raw_doc.raw_document_id,
            extraction_method=ExtractionMethod.llm_pdf,
            evidence_excerpt=f"label p.{row.get('page')}: \"{row['evidence_excerpt'][:400]}\" (model {result['model']}, excerpt verified verbatim in PDF)",
            confidence=float(row.get("confidence", 0.5)), validation_status=ValidationStatus.automatically_extracted, is_synthetic=False))
        n += 1
    session.commit()
    return n


def pilot_label_documents(session: Session) -> list[tuple[RawDocument, Registration]]:
    """Pair each stored label PDF (latest snapshot) with its registration via the EPA file name 064137-00034-... -> 64137-34."""
    out = []
    docs = session.query(RawDocument).filter(RawDocument.document_kind == "label_pdf").order_by(RawDocument.raw_document_id.desc()).all()
    seen = set()
    for d in docs:
        m = re.match(r"0*(\d+)-0*(\d+)-\d{8}\.pdf$", Path(d.local_path).name)
        if not m:
            continue
        regno = f"{m.group(1)}-{m.group(2)}"
        if regno in seen:
            continue
        reg = session.get(Registration, f"R-US-{regno}")
        if reg is None or not Path(d.local_path).exists():
            continue
        seen.add(regno)
        out.append((d, reg))
    return out


def run(session: Session, only_pilots: bool = True, model: str | None = None, force: bool = False) -> list[dict]:
    if not settings.ai_enabled:
        raise LLMUnavailable("AI_API_KEY not configured: label extraction skipped (deterministic data remains valid)")
    report = []
    pilot_ids = {"P-LPC-CONTANS", "P-LPC-G46", "P-LPC-M52"}
    for doc, reg in pilot_label_documents(session):
        if only_pilots and reg.product_id not in pilot_ids:
            continue
        res = extract_label(doc.local_path, model=model, force=force)
        n = load_label_uses(session, res, doc, reg)
        report.append({"registration": reg.registration_id, "pdf": res["pdf"], "pages": res["pages"], "returned": res["n_returned"],
                       "accepted": len(res["accepted"]), "rejected": len(res["rejected"]), "loaded": n, "model": res["model"]})
        log.info("label %s: %s", reg.registration_id, report[-1])
    return report
