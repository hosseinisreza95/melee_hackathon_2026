#!/usr/bin/env python3
"""Build output/submission.json (evaluation/expected_output_template.json) by asking the API's /ask engine the
five gold questions against the current database, then score it with the organiser's evaluator.

Usage: python scripts/build_submission.py [--product "LALSTOP CONTANS WG"] [--countries FR,CA]
"""
import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpc_regwatch import __version__  # noqa: E402
from lpc_regwatch.api.ask import ask  # noqa: E402
from lpc_regwatch.config import settings  # noqa: E402
from lpc_regwatch.db import get_session, init_db  # noqa: E402

LIMITS = [
    "Not an official regulatory source: Regulatory Affairs validation is required before any operational use.",
    "Four sources only (CA-PPID, US-EPA-PPLS, FR-EPHY, BR-AGROFIT); a product absent from them is 'not found in source', never 'not registered'.",
    "Canada and United States structured data give crops and pests as unpaired lists and no dose; doses for CA/US come only from label PDFs "
    "(AI-extracted rows are flagged extraction_method=llm_pdf, pairing=llm_paired, validation_status=automatically_extracted).",
    "Brazil AGROFIT open file lists active registrations only and carries no dates; expiry alerts therefore cover CA and FR only.",
    "EPPO codes are starter candidates (mapping_status=to_verify); unmapped crop/target wording keeps the original text and no code.",
    "Taxonomic synonyms are applied only from documented evidence (Gliocladium->Clonostachys; Metarhizium anisopliae F52->brunneum).",
    "Sister-product candidates are hypotheses (review_status=to_verify) until a Regulatory Affairs reviewer validates them via POST /review.",
    "Change detection works between two collections of the same source; the first collection has no baseline.",
    "The natural-language answer is phrased by an LLM only when a key is configured; a grounding guard rejects any number or country not present in the facts.",
]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="LALSTOP CONTANS WG")
    ap.add_argument("--countries", default="France et Canada")
    ap.add_argument("--out", default=str(ROOT / "output" / "submission.json"))
    a = ap.parse_args()
    init_db()
    s = get_session()
    gold = list(csv.DictReader((ROOT / "evaluation" / "gold_questions.csv").open(encoding="utf-8-sig")))
    questions = {
        "T01": f"Dans quels pays le produit {a.product} est-il homologué ?",
        "T02": f"Comparer les usages de {a.product} entre {a.countries}.",
        "T03": f"Quels champs sont incertains ou manquants pour {a.product} ?",
        "T04": f"Quels produits pourraient être des produits sœurs de {a.product} ?",
        "T05": f"Donne la source officielle de chaque donnée pour {a.product}.",
    }
    answers = []
    for g in gold:
        q = questions[g["test_id"]]
        res = ask(s, q, "fr")
        facts = [{k: v for k, v in f.items() if k not in ("restrictions",)} for f in res["facts"][:40]]
        answers.append({"test_id": g["test_id"], "question": q, "answer": res["answer"], "facts": facts,
                        "evidence": [{"source_id": e["sourceId"], "source_url": e["sourceUrl"], "collected_at": e["collectedAt"].isoformat().replace("+00:00", "Z"),
                                      "validation_status": e["validationStatus"], "excerpt": e.get("excerpt")} for e in res["evidence"][:25]],
                        "warnings": res["warnings"], "disclaimer": res["disclaimer"], "model": res["model"], "tools_used": res["toolsUsed"]})
    sub = {"submission_id": "melee-2026-lpc-regwatch", "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "version": __version__, "answers": answers,
           "m365_integration": {"mechanism": "api", "documentation_url": "m365/README.md",
                                "details": "OpenAPI 3.1 served at /openapi.json + Power Platform custom connector definition (m365/apiDefinition.swagger.json), "
                                           "Copilot Studio action on POST /ask, Power Automate flow on GET /export.csv -> SharePoint; Entra ID design documented."},
           "known_limitations": LIMITS, "ai_provider": settings.ai_provider if settings.ai_enabled else None, "ai_model": settings.ai_model if settings.ai_enabled else None}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sub, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written", out)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate_submission.py"), str(out)], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    s.close()
    sys.exit(r.returncode)
