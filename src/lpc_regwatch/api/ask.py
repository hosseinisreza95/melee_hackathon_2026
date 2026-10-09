"""/ask: natural-language questions answered ONLY from database rows (G3, cahier §16).

Pipeline:
1. `plan()`     deterministic intent + entity resolution (regex over product names, aliases, species, countries).
2. `run_tools()` predefined read-only queries (queries.py). Their rows ARE the evidence.
3. `phrase()`   if an LLM is configured, it rewrites the facts into a short answer in the user's language, with
                tool-calling restricted to the same predefined tools. If no key / failure, a template answer is used.
4. `guard()`    every registration number, country code and number in the LLM text must appear in the facts;
                otherwise the LLM text is dropped and the template answer is returned with a warning.
The LLM therefore never adds a fact: it can only choose tools and reformulate.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..config import DISCLAIMER, settings
from ..db.models import Product, ProductAlias
from ..llm import LLMUnavailable, get_client
from ..parsers.base import norm_name
from . import queries as Q

log = logging.getLogger(__name__)

COUNTRY_WORDS = {
    "CA": ["canada", "canadian", "canadien", "canadienne"], "US": ["usa", "united states", "u.s.", "etats-unis", "états-unis", "etats unis", "american", "américain", "epa"],
    "FR": ["france", "french", "français", "francais", "française", "anses", "e-phy", "ephy"], "BR": ["brazil", "brésil", "bresil", "brazilian", "brésilien", "agrofit"],
    "DE": ["germany", "allemagne", "german", "allemand"], "BE": ["belgium", "belgique"], "MX": ["mexico", "mexique"], "UY": ["uruguay"],
    "ES": ["spain", "espagne"], "IT": ["italy", "italie"], "NL": ["netherlands", "pays-bas"], "GB": ["united kingdom", "royaume-uni", "uk"],
}
INTENTS = {
    "sister_product": [r"\bs[oœ]urs?\b", r"\bsister", r"jumeau", r"équivalent", r"equivalent", r"même produit", r"same product", r"candidat"],
    "data_quality": [r"incertain", r"uncertain", r"manquant", r"missing", r"absent", r"qualit", r"valid", r"confiance", r"confidence", r"fiab"],
    "expiry": [r"expir", r"échéance", r"echeance", r"renouvel", r"renew", r"fin de validité"],
    "source": [r"source", r"preuve", r"evidence", r"d'où", r"provenance", r"citation", r"url"],
    "changes": [r"chang", r"nouveaut", r"what's new", r"modif", r"diff"],
    "ingredient_search": [r"contenant", r"containing", r"à base de", r"based on", r"microorganism", r"micro-organisme", r"souche", r"strain", r"espèce"],
    "use_comparison": [r"compar", r"usages?", r"uses", r"dose", r"culture", r"crop", r"cible", r"target", r"restriction", r"différence"],
    "registration_lookup": [r"homologu", r"registered", r"enregistr", r"autoris", r"approved", r"quels pays", r"which countr", r"où ", r"where"],
}
SPECIES = ["Coniothyrium minitans", "Clonostachys rosea", "Gliocladium catenulatum", "Metarhizium brunneum", "Metarhizium anisopliae",
           "Beauveria bassiana", "Trichoderma", "Bacillus", "Streptomyces", "Cordyceps javanica"]
CROP_WORDS = {"tomate": "Tomato", "tomato": "Tomato", "tomatoes": "Tomato", "fraise": "Strawberry", "fraisier": "Strawberry", "strawberry": "Strawberry",
              "laitue": "Lettuce", "lettuce": "Lettuce", "vigne": "Grapevine", "grape": "Grapevine", "soja": "Soybean", "soybean": "Soybean",
              "concombre": "Cucumber", "cucumber": "Cucumber", "pomme de terre": "Potato", "potato": "Potato", "poivron": "Sweet pepper", "pepper": "Sweet pepper",
              "colza": "Oilseed rape", "canola": "Oilseed rape", "carotte": "Carrot", "carrot": "Carrot", "oignon": "Onion", "onion": "Onion"}


@dataclass
class Plan:
    intent: str
    product_ids: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    species: str | None = None
    crop: str | None = None
    months: int = 12
    unresolved_names: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- 1. plan
def _product_index(session: Session) -> list[tuple[str, str, str]]:
    """(normalized name, product_id, kind) for every commercial name and alias, longest first."""
    idx: list[tuple[str, str, str]] = []
    for p in session.query(Product):
        idx.append((norm_name(p.commercial_name), p.product_id, "name"))
    for a in session.query(ProductAlias):
        idx.append((norm_name(a.alias_name), a.product_id, "alias"))
    return sorted({i for i in idx if len(i[0]) >= 4}, key=lambda t: -len(t[0]))


def plan(session: Session, question: str) -> Plan:
    q = question.lower()
    qn = " " + norm_name(question) + " "
    intent = "registration_lookup"
    for name, pats in INTENTS.items():
        if any(re.search(p, q) for p in pats):
            intent = name
            break
    countries = [cc for cc, words in COUNTRY_WORDS.items() if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", q) for w in words)]
    countries += [m for m in re.findall(r"\b([A-Z]{2})\b", question) if m in COUNTRY_WORDS and m not in countries]
    pids: list[str] = []
    consumed = qn
    for nname, pid, kind in _product_index(session):
        if f" {nname} " in consumed and pid not in pids:
            pids.append(pid)
            consumed = consumed.replace(f" {nname} ", " ")
            if kind == "name" and len(pids) >= 3:
                break
    species = next((s for s in SPECIES if s.lower() in q), None)
    crop = next((v for k, v in CROP_WORDS.items() if re.search(rf"\b{k}s?\b", q)), None)
    m = re.search(r"(\d{1,2})\s*(mois|months?)", q)
    months = int(m.group(1)) if m else 12
    unresolved = []
    if not pids and intent in ("registration_lookup", "use_comparison", "sister_product", "data_quality", "source"):
        for tok in re.findall(r"\b([A-Z][A-Z0-9]{3,}(?:\s[A-Z0-9]{1,4})?)\b", question):  # UPPERCASE tokens look like product names
            if tok not in COUNTRY_WORDS and norm_name(tok) not in {"EPPO", "ANSES"}:
                unresolved.append(tok)
    if species and not pids and intent in ("registration_lookup", "use_comparison"):
        intent = "ingredient_search"
    return Plan(intent, pids, countries, species, crop, months, unresolved)


# --------------------------------------------------------------------------- 2. tools (the only data access)
def run_tools(session: Session, pl: Plan) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Return (facts, evidence, warnings, tools_used). Facts are compact rows the LLM may phrase."""
    facts: list[dict] = []
    evidence: list[dict] = []
    warnings: list[str] = []
    tools: list[str] = []

    def add_reg(r: dict, product_name: str | None = None, uses_limit: int = 0):
        facts.append({"type": "registration", "product": product_name or r["productId"], "country": r["countryCode"],
                      "registrationNumber": r["registrationNumber"], "statusOriginal": r["statusOriginal"], "statusNormalized": r["statusNormalized"],
                      "authority": r["authorityName"], "holder": r["holderOriginal"], "approvalDate": r["approvalDate"], "expirationDate": r["expirationDate"],
                      "usesCount": r["usesCount"], "validationStatus": r["evidence"]["validationStatus"], "sourceId": r["evidence"]["sourceId"],
                      "sourceUrl": r["evidence"]["sourceUrl"], "collectedAt": r["evidence"]["collectedAt"].isoformat()})
        evidence.append(r["evidence"])
        for u in r["uses"][:uses_limit]:
            facts.append({"type": "use", "country": r["countryCode"], "registrationNumber": r["registrationNumber"], "crop": u["cropOriginal"],
                          "cropNormalized": u["cropNormalized"], "eppoCropCode": u["eppoCropCode"], "target": u["targetOriginal"],
                          "targetNormalized": u["targetNormalized"], "dose": u["doseValue"], "doseUnit": u["doseUnitOriginal"],
                          "phiDays": u["phiDays"], "maxApplications": u["maxApplications"], "restrictions": (u["restrictionsOriginal"] or "")[:300] or None,
                          "pairing": u["pairing"], "extractionMethod": u["evidence"]["extractionMethod"]})

    if pl.intent == "expiry":
        tools.append("expiring")
        rows = Q.expiring(session, pl.months)
        for r in rows:
            add_reg(r, r["productName"])
            facts[-1]["daysLeft"] = r["daysLeft"]
        if not rows:
            warnings.append(f"No registration with an expiry date within {pl.months} months in the collected sources; BR and US sources give no expiry dates.")
        warnings.append("Expiry dates exist only in CA-PPID and FR-EPHY (withdrawal date); US-EPA-PPLS and BR-AGROFIT do not publish them.")
        return facts, evidence, warnings, tools

    if pl.intent == "changes":
        tools.append("changes")
        for c in Q.changes(session, 50):
            facts.append({"type": "change", **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in c.items()}})
        if not facts:
            warnings.append("No change detected yet: change detection needs at least two collections of the same source.")
        return facts, evidence, warnings, tools

    if pl.intent == "ingredient_search" or (pl.species and not pl.product_ids):
        tools.append("products_by_active_entity")
        sp = pl.species or ""
        rows = Q.products_by_active_entity(session, sp, pl.crop, pl.countries or None) if sp else []
        for r in rows:
            add_reg(r, r["productName"])
            facts[-1]["activeEntityNormalized"] = r["activeEntityNormalized"]
            facts[-1]["matchingUsesCount"] = r["matchingUsesCount"]
            for u in r["matchingUses"][:3]:
                facts.append({"type": "use", "country": r["countryCode"], "registrationNumber": r["registrationNumber"], "product": r["productName"],
                              "crop": u["cropOriginal"], "cropNormalized": u["cropNormalized"], "target": u["targetOriginal"], "dose": u["doseValue"],
                              "doseUnit": u["doseUnitOriginal"], "pairing": u["pairing"]})
        if not sp:
            warnings.append("No micro-organism species recognised in the question (known: " + ", ".join(SPECIES) + ").")
        elif not rows:
            warnings.append(f"No product with '{sp}'" + (f" on crop '{pl.crop}'" if pl.crop else "") + " in the collected sources - not proof of absence.")
        if pl.crop:
            warnings.append("Crop filter applied on normalized and original crop wording; CA/US crop lists are not paired with targets by the source.")
        return facts, evidence, warnings, tools

    if not pl.product_ids:
        warnings.append("No known product name recognised in the question" + (f" (unresolved: {', '.join(pl.unresolved_names)})" if pl.unresolved_names else "")
                        + ". Nothing was found in the collected sources; this is not proof of no registration. Try the exact commercial name or an alias.")
        return facts, evidence, warnings, tools

    for pid in pl.product_ids:
        p = session.get(Product, pid)
        pname = p.commercial_name if p else pid
        if pl.intent == "sister_product":
            tools.append("aliases_for")
            for a in Q.aliases_for(session, pid):
                facts.append({"type": "alias", "product": pname, **a})
            warnings.append("Sister-product candidates are hypotheses with a review status; none is a confirmed equivalent unless review_status=validated.")
            for r in Q.registrations_for(session, pid, with_uses=False):
                evidence.append(r["evidence"])
            continue
        if pl.intent == "data_quality":
            tools.append("data_quality")
            dq = Q.data_quality(session, pid)
            for i in dq["registrations"]:
                facts.append({"type": "data_quality", "product": pname, "country": i["countryCode"], "registrationId": i["registrationId"],
                              "validationStatus": i["validationStatus"], "missingOrUncertain": i["missingOrUncertain"], "pairing": i["pairing"]})
                evidence.append(i["evidence"])
            warnings += dq["warnings"]
            continue
        countries = pl.countries or sorted(Q.COUNTRY_SOURCES)
        tools.append("compare")
        cmp_ = Q.compare(session, pid, countries)
        uses_limit = 12 if pl.intent == "use_comparison" else 0
        for r in cmp_["registrations"]:
            add_reg(r, pname, uses_limit)
        for c in cmp_["coverage"]:
            if c["coverage"] != "found":
                facts.append({"type": "coverage", "product": pname, "country": c["countryCode"], "coverage": c["coverage"], "note": c["note"]})
        warnings += cmp_["warnings"]
    return facts, evidence, warnings, tools


# --------------------------------------------------------------------------- 3. template answer (always available)
def template_answer(pl: Plan, facts: list[dict], warnings: list[str], language: str) -> str:
    fr = language.lower().startswith("fr")
    regs = [f for f in facts if f["type"] == "registration"]
    lines: list[str] = []
    if pl.intent == "sister_product":
        al = [f for f in facts if f["type"] == "alias"]
        cands = [a for a in al if a["relationshipType"] in ("sister_product_candidate", "related_formulation")]
        offi = [a for a in al if a["relationshipType"] in ("alternate_name", "historical_name")]
        lines.append(("Hypothèses de produits sœurs (à confirmer) : " if fr else "Sister-product hypotheses (to confirm): ") + (", ".join(
            f"{a['aliasName']} [{a['relationshipType']}, confiance {a['confidence']}, statut {a['reviewStatus']}]" for a in cands) or ("aucune" if fr else "none")))
        if offi:
            lines.append(("Noms officiels équivalents (même enregistrement) : " if fr else "Official equivalent names (same registration): ") + ", ".join(f"{a['aliasName']} ({a['countryCode'] or '-'})" for a in offi))
    elif pl.intent == "data_quality":
        for f in facts:
            if f["type"] == "data_quality":
                lines.append(f"{f['country']} {f['registrationId']}: {'statut de validation' if fr else 'validation status'} = {f['validationStatus']}; "
                             f"{'champs manquants/incertains' if fr else 'missing/uncertain'} = {', '.join(f['missingOrUncertain']) or '-'}")
    elif pl.intent == "expiry":
        for f in regs:
            lines.append(f"{f['product']} — {f['country']} {f['registrationNumber']}: {'expire le' if fr else 'expires on'} {f['expirationDate']} ({f.get('daysLeft')} {'jours' if fr else 'days'}) — {f['sourceId']}")
    elif pl.intent == "changes":
        for f in facts[:20]:
            lines.append(f"{f.get('entityId')}: {f.get('field')} {f.get('oldValue')!r} -> {f.get('newValue')!r} ({'snapshot' if fr else 'snapshot'} {f.get('fromSnapshotId')}->{f.get('toSnapshotId')})")
    else:
        for f in regs:
            lines.append(f"{f['product']} — {Q.COUNTRY_NAMES.get(f['country'], f['country'])} ({f['country']}): {'n°' if fr else 'no.'} {f['registrationNumber']}, "
                         f"{'statut' if fr else 'status'} {f['statusNormalized']} (« {f['statusOriginal']} »), "
                         f"{f['usesCount']} {'usages' if fr else 'uses'}, {'source' if fr else 'source'} {f['sourceId']} "
                         f"{'collectée le' if fr else 'collected'} {f['collectedAt'][:10]}, {'validation' if fr else 'validation'}: {f['validationStatus']}")
        for f in facts:
            if f["type"] == "coverage":
                lines.append(f"{f['product']} — {Q.COUNTRY_NAMES.get(f['country'], f['country'])} ({f['country']}): {f['note']}")
        uses = [f for f in facts if f["type"] == "use"]
        if uses:
            lines.append("")
            lines.append("Usages (extrait) :" if fr else "Uses (excerpt):")
            for u in uses[:24]:
                dose = f"{u['dose']} {u['doseUnit']}" if u.get("dose") is not None else ("dose non structurée" if fr else "dose not in structured source")
                lines.append(f"  {u['country']} {u['registrationNumber']}: {u.get('crop')} → {u.get('target')} | {dose}"
                             + (f" | PHI {u['phiDays']} j" if u.get("phiDays") is not None else "") + (f" | max {u['maxApplications']} appl." if u.get("maxApplications") else "")
                             + (f" | {u['pairing']}" if u.get("pairing") and u["pairing"] != "source_paired" else ""))
    if not lines:
        lines.append("Aucune donnée trouvée dans les sources collectées pour cette question. Absence de résultat ≠ absence d'homologation." if fr
                     else "No data found in the collected sources for this question. No result is not proof of no registration.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 4. LLM phrasing + guard
SYSTEM = """You are the answer writer of a regulatory-watch prototype for plant protection products.
You receive FACTS (database rows from official sources) and WARNINGS. Write a concise answer in the requested language.
Absolute rules:
- Use ONLY the facts given. Never add a country, product, number, date, dose or status that is not in FACTS.
- If facts are empty or do not answer the question, say so and say that no result is not proof of no registration.
- Keep original wording in quotes when you cite a status or a dose; mention the source id and collection date for each registration.
- Never present a sister-product candidate as a confirmed equivalent; say 'hypothesis' / 'à confirmer'.
- Do not give advice on product use. Max 220 words. Plain text, no markdown tables."""


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d\-/.,]*\d|\d", text))


def guard(llm_text: str, facts: list[dict], warnings: list[str]) -> tuple[bool, str | None]:
    """Reject any LLM answer containing a number or country code not present in the facts/warnings."""
    allowed = _numbers(json.dumps(facts, ensure_ascii=False, default=str) + " " + " ".join(warnings))
    for n in _numbers(llm_text):
        if n not in allowed and not re.fullmatch(r"\d{1,2}", n):  # small counts (e.g. '3 countries') are tolerated
            return False, f"unsupported number '{n}' in model text"
    ccs = set(re.findall(r"\b([A-Z]{2})\b", llm_text)) & set(Q.COUNTRY_SOURCES) | set(re.findall(r"\b(DE|BE|MX|UY|ES|IT|NL|GB)\b", llm_text))
    fact_ccs = {f.get("country") for f in facts if f.get("country")} | set(re.findall(r"\(([A-Z]{2})\)", " ".join(warnings)))
    for cc in ccs - fact_ccs:
        if cc in Q.COUNTRY_WORDS if hasattr(Q, "COUNTRY_WORDS") else cc in COUNTRY_WORDS:
            return False, f"country {cc} not in facts"
    return True, None


def ask(session: Session, question: str, language: str = "fr") -> dict:
    pl = plan(session, question)
    facts, evidence, warnings, tools = run_tools(session, pl)
    text = template_answer(pl, facts, warnings, language)
    model = None
    if settings.ai_enabled and facts:
        try:
            client = get_client()
            user = (f"QUESTION ({language}): {question}\n\nFACTS (JSON rows):\n{json.dumps(facts[:60], ensure_ascii=False, default=str)}\n\n"
                    f"WARNINGS:\n- " + "\n- ".join(warnings[:12]) + f"\n\nDETERMINISTIC DRAFT (you may improve wording, not content):\n{text}")
            resp = client.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], max_tokens=600)
            cand = (resp.choices[0].message.content or "").strip()
            ok, why = guard(cand, facts, warnings)
            if ok and cand:
                text, model = cand, client.model
            else:
                warnings.append(f"AI phrasing rejected by the grounding guard ({why}); deterministic answer shown instead.")
        except LLMUnavailable as e:
            kind = str(e).split(":", 1)[0].strip() or "error"
            warnings.append(f"AI provider unavailable ({kind}); deterministic answer shown, built from the same facts.")
    # dedupe evidence by (source url, snapshot)
    seen = set()
    ev = []
    for e in evidence:
        k = (e["sourceUrl"], e.get("snapshotId"))
        if k not in seen:
            seen.add(k)
            ev.append(e)
    return {"answer": text, "evidence": ev[:50], "warnings": list(dict.fromkeys(warnings)), "disclaimer": DISCLAIMER,
            "facts": facts[:200], "intent": pl.intent, "toolsUsed": list(dict.fromkeys(tools)), "model": model}
