#!/usr/bin/env python3
"""End-to-end evaluation of every pipeline step on the CURRENT database, with and without the LLM.

Produces output/evaluation_report.json and prints a summary. Sections:
 1. collectors   snapshots per source (ok/failed), bytes, raw documents
 2. parsers      rows, 100 % traceability checks (source, URL, date, status), originals kept
 3. normalisation EPPO coverage, dose conversion, status 'unknown' count, taxonomy synonyms
 4. matching     pilots resolved per country, relation types, hypotheses never validated without review
 5. labels (AI)  accepted/rejected per PDF, grounding modes, plausibility vs the EPA site list
 6. /ask         gold + jury-style questions: deterministic path checks, then LLM phrasing checks when a key exists
                 (guard verdict, facts coverage, forbidden claims)
 7. submission   organiser evaluator score
Usage: python scripts/evaluate_pipeline.py [--no-llm]
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import func  # noqa: E402

from lpc_regwatch.api.ask import ask, guard  # noqa: E402
from lpc_regwatch.config import settings  # noqa: E402
from lpc_regwatch.db import get_session, init_db  # noqa: E402
from lpc_regwatch.db.models import (AliasRelation, AuthorizedUse, ExtractionMethod, Product, ProductAlias, RawDocument, RegStatus,  # noqa: E402
                                    Registration, ReviewLog, Snapshot, ValidationStatus)

QUESTIONS = [
    ("T01", "Dans quels pays le produit LALSTOP CONTANS WG est-il homologué ?", {"29066", "64137-34", "9900189"}, ["BR"]),
    ("T02", "Comparer les usages de LALSTOP CONTANS WG entre la France et le Canada.", {"9900189", "29066", "4.0", "kg/ha"}, []),
    ("T03", "Quels champs sont incertains ou manquants pour LALGUARD M52 OD ?", {"automatically_extracted"}, []),
    ("T04", "Quels produits pourraient être des produits sœurs de LALSTOP G46 WG ?", {"PRESTOP"}, []),
    ("T05", "Donne la source officielle de chaque donnée pour LALGUARD M52 OD.", {"CA-PPID", "US-EPA-PPLS", "FR-EPHY"}, []),
    ("J01", "Where is PRESTOP registered and with which status?", {"28820", "64137-11", "2120177"}, []),
    ("J02", "Which products containing Clonostachys rosea are registered on strawberries?", {"2230771", "32404"}, []),
    ("J03", "Kamoi Pro est-il homologué au Brésil et au Canada ?", {"27520"}, ["CA"]),
    ("J04", "LALSTOP G46 WG est-il homologué au Canada ?", {"32404"}, ["CA"]),
    ("J05", "Quelles autorisations expirent dans les 12 prochains mois ?", {"32404", "2026-12-31"}, []),
    ("J06", "Compare the uses of LALGUARD M52 OD between France and the United States.", {"2150990", "64137-33", "1.25"}, []),
    ("J07", "Quels produits à base de Metarhizium brunneum sont autorisés sur vigne ?", {"2150990"}, []),
    ("J08", "Dans quels pays le produit FOOBARIX 3000 est-il homologué ?", set(), []),
]
FORBIDDEN = [r"pas homologu", r"non homologu", r"n'est pas enregistr", r"not registered\b", r"no registration in", r"is not authori[sz]ed"]


def section_collectors(s):
    out = {}
    for snap in s.query(Snapshot).order_by(Snapshot.snapshot_id):
        docs = s.query(RawDocument).filter_by(snapshot_id=snap.snapshot_id).all()
        out.setdefault(snap.source_id, []).append({"snapshot": snap.snapshot_id, "status": snap.status, "documents": len(docs),
                                                   "bytes": sum(d.bytes for d in docs), "collected_at": snap.collected_at.isoformat()})
    return out


def section_parsers(s):
    n_reg = s.query(Registration).count()
    n_use = s.query(AuthorizedUse).count()
    bad = {
        "registrations_without_url": s.query(Registration).filter(~Registration.source_record_url.like("http%")).count(),
        "registrations_without_evidence_excerpt": s.query(Registration).filter((Registration.evidence_excerpt.is_(None)) | (Registration.evidence_excerpt == "")).count(),
        "uses_without_url": s.query(AuthorizedUse).filter(~AuthorizedUse.source_record_url.like("http%")).count(),
        "uses_without_collected_at": s.query(AuthorizedUse).filter(AuthorizedUse.collected_at.is_(None)).count(),
        "normalized_crop_without_original": s.query(AuthorizedUse).filter(AuthorizedUse.crop_name_normalized.isnot(None), AuthorizedUse.crop_name_original.is_(None)).count(),
        "synthetic_rows": s.query(Registration).filter(Registration.is_synthetic.is_(True)).count() + s.query(AuthorizedUse).filter(AuthorizedUse.is_synthetic.is_(True)).count(),
    }
    per_source = {src: {"registrations": n, "uses": s.query(func.count(AuthorizedUse.use_id)).join(Registration).filter(Registration.source_id == src).scalar()}
                  for src, n in s.query(Registration.source_id, func.count()).group_by(Registration.source_id)}
    return {"registrations": n_reg, "uses": n_use, "per_source": per_source, "traceability_violations": bad, "traceability_ok": not any(bad.values())}


def section_normalisation(s):
    n_use = s.query(AuthorizedUse).count()
    crop_code = s.query(AuthorizedUse).filter(AuthorizedUse.eppo_crop_code.isnot(None)).count()
    target_code = s.query(AuthorizedUse).filter(AuthorizedUse.eppo_target_code.isnot(None)).count()
    crop_status = dict(s.query(AuthorizedUse.eppo_crop_status, func.count()).group_by(AuthorizedUse.eppo_crop_status))
    dose_rows = s.query(AuthorizedUse).filter(AuthorizedUse.dose_value.isnot(None)).count()
    dose_norm = s.query(AuthorizedUse).filter(AuthorizedUse.dose_value_normalized.isnot(None)).count()
    unknown = s.query(Registration).filter(Registration.status_normalized == RegStatus.unknown).count()
    species = {p.active_entity_normalized.split()[0] + " " + p.active_entity_normalized.split()[1] for p in s.query(Product) if p.active_entity_normalized and len(p.active_entity_normalized.split()) >= 2}
    return {"uses": n_use, "eppo_crop_code_rate": round(crop_code / n_use, 3) if n_use else 0, "eppo_target_code_rate": round(target_code / n_use, 3) if n_use else 0,
            "eppo_crop_status": crop_status, "dose_rows": dose_rows, "dose_normalized": dose_norm, "status_unknown_registrations": unknown,
            "distinct_species": len(species), "no_genus_only_species_codes": s.query(AuthorizedUse).filter(AuthorizedUse.target_name_original.in_(["Thrips", "Acariens", "Aleurodes"]), AuthorizedUse.eppo_target_code.isnot(None)).count() == 0}


def section_matching(s):
    pilots = {}
    for pid in ("P-LPC-CONTANS", "P-LPC-G46", "P-LPC-M52"):
        p = s.get(Product, pid)
        regs = {r.country_code: r.registration_number for r in p.registrations}
        rel = {a.alias_name: f"{a.relationship_type.value}/{a.review_status.value}" for a in p.aliases if a.relationship_type.value in ("related_product", "confirmed_sister_product", "related_formulation", "sister_product_candidate")}
        pilots[pid] = {"registrations": regs, "relations": rel}
    bad = [a.alias_id for a in s.query(ProductAlias).filter(ProductAlias.relationship_type == AliasRelation.sister_product_candidate, ProductAlias.review_status == ValidationStatus.validated)
           if s.query(ReviewLog).filter_by(entity_type="alias", entity_id=a.alias_id).count() == 0]
    counts = dict((k.value, v) for k, v in s.query(ProductAlias.relationship_type, func.count()).group_by(ProductAlias.relationship_type))
    return {"pilots": pilots, "relation_counts": counts, "hypotheses_validated_without_review": bad, "ok": not bad}


def section_labels(s):
    rows = s.query(AuthorizedUse).filter(AuthorizedUse.extraction_method == ExtractionMethod.llm_pdf).all()
    per_reg = {}
    for u in rows:
        d = per_reg.setdefault(u.registration_id, {"rows": 0, "with_dose": 0, "verbatim": 0, "partial": 0, "crop_matches_epa_site": 0, "confidence_mean": 0.0})
        d["rows"] += 1
        d["with_dose"] += u.dose_value is not None
        d["verbatim" if "verified verbatim" in (u.evidence_excerpt or "") and "start" not in (u.evidence_excerpt or "") else "partial"] += 1
        d["confidence_mean"] += u.confidence or 0
    for rid, d in per_reg.items():
        d["confidence_mean"] = round(d["confidence_mean"] / d["rows"], 2)
        sites = {(x.crop_name_original or "").upper() for x in s.query(AuthorizedUse).filter(AuthorizedUse.registration_id == rid, AuthorizedUse.pairing == "unpaired_lists")}
        tokens = {w for site in sites for w in re.findall(r"[A-Z]{4,}", site)}
        hits = 0
        for u in [x for x in rows if x.registration_id == rid]:
            words = set(re.findall(r"[A-Za-z]{4,}", (u.crop_name_original or "").upper()))
            hits += bool(words & tokens)
        d["crop_matches_epa_site"] = round(hits / d["rows"], 2) if d["rows"] else None
    rep_path = ROOT / "data" / "processed" / "label_extraction_report.json"
    report = json.loads(rep_path.read_text(encoding="utf-8")) if rep_path.exists() else None
    return {"rows_in_store": len(rows), "per_registration": per_reg, "last_extraction_report": report}


def _check(answer: dict, must: set[str], not_found_cc: list[str]) -> dict:
    text = json.dumps(answer["facts"], ensure_ascii=False) + " " + answer["answer"]
    missing = [m for m in must if m not in text]
    forb = [p for p in FORBIDDEN if re.search(p, answer["answer"], re.I)]
    cov_ok = all(any(f["type"] == "coverage" and f["country"] == cc for f in answer["facts"]) for cc in not_found_cc)
    ev_ok = all(e["sourceUrl"].startswith("http") and e["collectedAt"] and e["validationStatus"] for e in answer["evidence"])
    return {"missing_required": missing, "forbidden_claims": forb, "coverage_explained": cov_ok, "evidence_ok": ev_ok,
            "evidence": len(answer["evidence"]), "warnings": len(answer["warnings"]), "model": answer["model"],
            "guard_rejected": any("grounding guard" in w for w in answer["warnings"]),
            "pass": not missing and not forb and cov_ok and ev_ok}


def section_ask(s, use_llm: bool):
    import lpc_regwatch.api.ask as askmod
    from lpc_regwatch.config import Settings

    results = {}
    saved = askmod.settings
    try:
        askmod.settings = Settings(ai_api_key="")
        det = {tid: _check(ask(s, q, "fr" if not q[0].isupper() or "é" in q else "en"), must, nf) for tid, q, must, nf in QUESTIONS}
        results["deterministic"] = {"pass_rate": round(sum(v["pass"] for v in det.values()) / len(det), 2), "per_question": det}
        if use_llm and saved.ai_enabled:
            askmod.settings = saved
            llm = {}
            for tid, q, must, nf in QUESTIONS:
                a = ask(s, q, "fr" if "é" in q or q.startswith(("Dans", "Compar", "Quel", "Donne", "Kamoi", "LALSTOP")) else "en")
                r = _check(a, must, nf)
                r["answer_chars"] = len(a["answer"])
                ok, why = guard(a["answer"], a["facts"], a["warnings"])
                r["guard_recheck"] = ok
                r["answer_preview"] = a["answer"][:240]
                llm[tid] = r
            results["llm"] = {"model": saved.ai_model, "pass_rate": round(sum(v["pass"] for v in llm.values()) / len(llm), 2),
                              "phrased_by_llm": sum(1 for v in llm.values() if v["model"]), "guard_rejections": sum(1 for v in llm.values() if v["guard_rejected"]),
                              "per_question": llm}
    finally:
        askmod.settings = saved
    return results


def section_submission():
    out = ROOT / "output" / "submission.json"
    if not out.exists():
        return {"score": None}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate_submission.py"), str(out)], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": r.stderr[:200]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    init_db()
    s = get_session()
    report = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "database": settings.database_url.split("@")[-1],
              "ai_enabled": settings.ai_enabled and not a.no_llm, "ai_model": settings.ai_model}
    report["1_collectors"] = section_collectors(s)
    report["2_parsers"] = section_parsers(s)
    report["3_normalisation"] = section_normalisation(s)
    report["4_matching"] = section_matching(s)
    report["5_labels_ai"] = section_labels(s)
    report["6_ask"] = section_ask(s, not a.no_llm)
    report["7_submission"] = section_submission()
    out = ROOT / "output" / "evaluation_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    p, n, m, L = report["2_parsers"], report["3_normalisation"], report["4_matching"], report["5_labels_ai"]
    print(f"collectors: {sum(len(v) for v in report['1_collectors'].values())} snapshots, failed={sum(1 for v in report['1_collectors'].values() for x in v if x['status'] != 'ok')}")
    print(f"parsers: {p['registrations']} registrations, {p['uses']} uses, traceability_ok={p['traceability_ok']} violations={p['traceability_violations']}")
    print(f"normalisation: crop code {n['eppo_crop_code_rate']:.0%}, target code {n['eppo_target_code_rate']:.0%}, dose normalized {n['dose_normalized']}/{n['dose_rows']}, unknown status {n['status_unknown_registrations']}, genus-only guard ok={n['no_genus_only_species_codes']}")
    print(f"matching: ok={m['ok']} relations={m['relation_counts']}")
    for pid, v in m["pilots"].items():
        print(f"   {pid}: {v['registrations']} | related: {v['relations']}")
    print(f"labels(AI): {L['rows_in_store']} rows; per registration: {L['per_registration']}")
    for mode, r in report["6_ask"].items():
        print(f"/ask [{mode}]: pass_rate={r['pass_rate']}" + (f" phrased_by_llm={r['phrased_by_llm']}/{len(r['per_question'])} guard_rejections={r['guard_rejections']}" if mode == "llm" else ""))
        for tid, v in r["per_question"].items():
            if not v["pass"]:
                print(f"   FAIL {tid}: missing={v['missing_required']} forbidden={v['forbidden_claims']} coverage={v['coverage_explained']} evidence={v['evidence_ok']}")
    print(f"submission: {report['7_submission']}")
    print("report:", out)
    s.close()
