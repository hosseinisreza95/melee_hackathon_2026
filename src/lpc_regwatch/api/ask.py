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
from .answer_model import SCHEMA as ANSWER_SCHEMA, AnswerItem, StructuredAnswer

log = logging.getLogger(__name__)

COUNTRY_WORDS = {
    "CA": ["canada", "canadian", "canadien", "canadienne", "canadá"], "US": ["usa", "united states", "u.s.", "etats-unis", "états-unis", "etats unis", "american", "américain", "epa", "estados unidos", "eua"],
    "FR": ["france", "french", "français", "francais", "française", "anses", "e-phy", "ephy", "frança", "francês"], "BR": ["brazil", "brésil", "bresil", "brazilian", "brésilien", "agrofit", "brasil", "brasileiro"],
    "DE": ["germany", "allemagne", "german", "allemand", "alemanha", "alemão"], "BE": ["belgium", "belgique", "bélgica", "belgica"], "MX": ["mexico", "mexique", "méxico"],
    "UY": ["uruguay", "uruguai"], "ES": ["spain", "espagne", "espanha", "españa"], "IT": ["italy", "italie", "itália", "italia"],
    "NL": ["netherlands", "pays-bas", "países baixos", "paises baixos", "holanda"], "GB": ["united kingdom", "royaume-uni", "uk", "reino unido"],
    "PL": ["poland", "pologne", "polônia", "polonia", "polish", "polonais"],
}
INTENTS = {
    "sister_product": [r"\bs[oœ]urs?\b", r"\bsister", r"jumeau", r"irmã", r"irmão", r"équivalent", r"equivalent", r"même produit", r"same product", r"candidat"],
    "data_quality": [r"incertain", r"uncertain", r"manquant", r"missing", r"absent", r"qualit", r"valid", r"confiance", r"confidence", r"fiab"],
    "expiry": [r"expir", r"échéance", r"echeance", r"renouvel", r"renew", r"fin de validité"],
    "source": [r"source", r"preuve", r"evidence", r"d'où", r"provenance", r"citation", r"url"],
    "changes": [r"chang", r"nouveaut", r"what's new", r"modif", r"diff"],
    "ingredient_search": [r"contenant", r"containing", r"contain", r"à base de", r"based on", r"microorganism", r"micro-organisme", r"souche", r"strain", r"espèce", r"species", r"same active", r"même (?:micro|substance|matière)"],
    "use_comparison": [r"compar", r"usages?", r"\buses?\b", r"dose", r"culture", r"crop", r"cible", r"target", r"restriction", r"différence", r"difference", r"label", r"étiquette", r"délai"],
    "registration_lookup": [r"homologu", r"register", r"enregistr", r"autoris", r"approv", r"quels pays", r"which countr", r"où ", r"where", r"status", r"statut", r"licen", r"registrad", r"quais países", r"onde"],
}
SPECIES_STATIC = ["Coniothyrium minitans", "Clonostachys rosea", "Gliocladium catenulatum", "Metarhizium brunneum", "Metarhizium anisopliae",
                  "Beauveria bassiana", "Trichoderma", "Bacillus", "Streptomyces", "Cordyceps javanica"]
# French/English words that appear in questions but are not EPPO aliases (fruit name -> crop concept id)
CROP_EXTRA = {"fraise": "strawberry", "fraises": "strawberry", "raisin": "grapevine", "grape": "grapevine", "grapes": "grapevine", "pomme": "apple",
              "pommes": "apple", "poire": "pear", "pêche": "peach", "cerise": "cherry", "tomates": "tomato", "salade": "lettuce", "salad": "lettuce",
              "tomatoes": "tomato", "potatoes": "potato", "onions": "onion", "carrots": "carrot", "cucumbers": "cucumber", "lettuces": "lettuce"}


def species_in_db(session: Session) -> list[str]:
    """Genus+species present in the store (any product), so questions about any micro-organism resolve, not only the pilots."""
    out = set(SPECIES_STATIC)
    for (ae,) in session.query(Product.active_entity_normalized).filter(Product.active_entity_normalized.isnot(None)):
        w = ae.split()
        if len(w) >= 2:
            out.add(f"{w[0]} {w[1]}")
    return sorted(out, key=len, reverse=True)


def crop_in_question(q: str) -> str | None:
    """Crop concept from the question using the EPPO alias index (starter languages + observed wordings) plus CROP_EXTRA."""
    from ..normalize.eppo import _index

    concepts, alias = _index("crop")
    ql = " " + re.sub(r"[^\w\s-]", " ", q.lower()) + " "
    best = None
    for name, cid in list(alias.items()) + list(CROP_EXTRA.items()):
        if len(name) >= 4 and f" {name} " in ql and (best is None or len(name) > len(best[0])):
            best = (name, cid)
    if best:
        c = concepts.get(best[1])
        return c.name_normalized if c else best[1]
    return None


@dataclass
class Plan:
    intent: str
    product_ids: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    species: str | None = None
    crop: str | None = None
    months: int = 12
    unresolved_names: list[str] = field(default_factory=list)
    scope: str = "all"  # country_portfolio: 'lallemand' (holder LALLEMAND/DANSTAR) or 'all'
    inherited: list[str] = field(default_factory=list)  # what a follow-up question took from the conversation context


ALL_COUNTRIES_RE = re.compile(r"quels pays|which countr|quais pa[ií]ses|dans quels|em quais|where|où |onde|partout|everywhere|tous les pays|all countries|todos os pa[ií]ses")


PORTFOLIO_RE = re.compile(r"quels? produits?|which products?|what products?|quais produtos|liste des produits|list (?:of |the )?products|produits (?:lallemand|homologu|enregistr|autoris)"
                          r"|lallemand products|produtos (?:lallemand|registrad)|portefeuille|portfolio|tous les produits|all (?:the )?products|todos os produtos")


# --------------------------------------------------------------------------- 1. plan
def _product_index(session: Session) -> list[tuple[str, str, str]]:
    """(normalized name, product_id, kind) for every commercial name and alias, longest first."""
    idx: list[tuple[str, str, str]] = []
    for p in session.query(Product):
        idx.append((norm_name(p.commercial_name), p.product_id, "name"))
    for a in session.query(ProductAlias):
        idx.append((norm_name(a.alias_name), a.product_id, "alias"))
    # longest first; for the same wording a product's own name wins over another product's alias (PRESTOP WG carries
    # 'LALSTOP G46 WG' as an alternate name, but the question is about LALSTOP G46 WG itself)
    return sorted({i for i in idx if len(i[0]) >= 4}, key=lambda t: (-len(t[0]), t[2] != "name", t[1]))


def plan(session: Session, question: str, context: dict | None = None) -> Plan:
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
    species = next((s for s in species_in_db(session) if s.lower() in q), None)
    crop = crop_in_question(question)
    m = re.search(r"(\d{1,2})\s*(mois|months?)", q)
    months = int(m.group(1)) if m else 12
    unresolved = []
    if not pids and intent in ("registration_lookup", "use_comparison", "sister_product", "data_quality", "source"):
        for tok in re.findall(r"\b([A-Z][A-Z0-9]{3,}(?:\s[A-Z0-9]{1,4})?)\b", question):  # UPPERCASE tokens look like product names
            if tok not in COUNTRY_WORDS and norm_name(tok) not in {"EPPO", "ANSES"}:
                unresolved.append(tok)
    if species and not pids and intent in ("registration_lookup", "use_comparison"):
        intent = "ingredient_search"
    scope = "lallemand" if re.search(r"lallemand|danstar", q) else "all"
    if not pids and not species and countries and PORTFOLIO_RE.search(q):  # 'which (Lallemand) products are registered in Brazil?'
        intent = "country_portfolio"
        unresolved = []
    # follow-up questions ('et en France ?', 'et ses usages ?'): take the subject from the previous turn, deterministically
    inherited: list[str] = []
    ctx = context or {}
    if ctx and not pids and not species and intent not in ("expiry", "changes", "country_portfolio"):
        if ctx.get("productIds"):
            pids = [p for p in ctx["productIds"] if session.get(Product, p)]
            if pids:
                inherited.append("product")
                unresolved = []
                if intent == "ingredient_search":
                    intent = "registration_lookup"
        elif ctx.get("species"):  # previous turn was about a micro-organism: 'and in Canada?' keeps species (and crop)
            species = ctx["species"]
            inherited.append("species")
            if intent in ("registration_lookup", "use_comparison", "ingredient_search"):
                intent = "ingredient_search"
            if not crop and ctx.get("crop"):
                crop = ctx["crop"]
    if inherited and not countries and ctx.get("countries") and not ALL_COUNTRIES_RE.search(q):
        countries = list(ctx["countries"])
        inherited.append("countries")
    return Plan(intent, pids, countries, species, crop, months, unresolved, scope, inherited)


# --------------------------------------------------------------------------- 2. tools (the only data access)
def run_tools(session: Session, pl: Plan) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Return (facts, evidence, warnings, tools_used). Facts are compact rows the LLM may phrase."""
    facts: list[dict] = []
    evidence: list[dict] = []
    warnings: list[str] = []
    tools: list[str] = []
    if pl.inherited:  # say explicitly what was taken from the conversation
        parts = []
        if "product" in pl.inherited:
            parts.append(", ".join((session.get(Product, p).commercial_name if session.get(Product, p) else p) for p in pl.product_ids))
        if "species" in pl.inherited:
            parts.append(f"{pl.species}" + (f" ({pl.crop})" if pl.crop else ""))
        if "countries" in pl.inherited:
            parts.append(", ".join(pl.countries))
        warnings.append("Context taken from the conversation: " + " · ".join(parts) + ".")

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
            warnings.append("No micro-organism species recognised in the question (known species are those present in the store, e.g. " + ", ".join(SPECIES_STATIC[:5]) + ").")
        elif not rows:
            warnings.append(f"No product with '{sp}'" + (f" on crop '{pl.crop}'" if pl.crop else "") + " in the collected sources - not proof of absence.")
        if pl.crop:
            warnings.append("Crop filter applied on normalized and original crop wording; CA/US crop lists are not paired with targets by the source.")
        return facts, evidence, warnings, tools

    if pl.intent == "country_portfolio":
        tools.append("overview")
        ov = Q.overview(session, pl.scope, None, pl.months)
        for c in ov["countries"]:
            cc = c["countryCode"]
            if cc not in pl.countries:
                continue
            regs = c["registrations"]
            name = Q.COUNTRY_NAMES.get(cc, cc)
            for r in regs[:40]:
                facts.append({"type": "registration", "product": r["productName"], "country": cc, "registrationNumber": r["registrationNumber"],
                              "statusOriginal": r["statusOriginal"], "statusNormalized": r["statusNormalized"], "holder": r["holder"],
                              "expirationDate": r["expirationDate"], "usesCount": r["usesCount"], "activeEntityNormalized": r["activeEntityNormalized"],
                              "validationStatus": r["validationStatus"], "sourceId": r["sourceId"], "sourceUrl": r["sourceUrl"],
                              "collectedAt": r["collectedAt"].isoformat() if r["collectedAt"] else None})
                evidence.append({"sourceId": r["sourceId"], "sourceUrl": r["sourceUrl"], "collectedAt": r["collectedAt"], "validationStatus": r["validationStatus"]})
            facts.append({"type": "portfolio", "country": cc, "scope": pl.scope, "total": len(regs), "shown": min(len(regs), 40), "coverage": c["coverage"],
                          "sourceId": c["sourceId"], "collectedAt": c["collectedAt"].isoformat() if c["collectedAt"] else None})
            if c["coverage"] == "source_not_collected":
                warnings.append(f"{name} ({cc}): no source connected - unknown, not 'not registered'.")
            elif not regs:
                warnings.append(f"{name} ({cc}): no product of scope '{pl.scope}' found in {c['sourceId']} as of {c['collectedAt']:%Y-%m-%d} - this is not proof of no registration.")
            elif len(regs) > 40:
                warnings.append(f"{name} ({cc}): {len(regs)} registrations in scope '{pl.scope}', only the first 40 are listed - narrow the question (e.g. 'Lallemand products').")
        if pl.scope == "lallemand":
            warnings.append("Scope 'Lallemand' = registrations whose holder contains LALLEMAND or DANSTAR in the official source; distributor registrations are not included.")
        if pl.crop:
            warnings.append(f"Crop '{pl.crop}' was not applied to this country listing; ask with a product or a micro-organism to filter by crop.")
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
        for rp in cmp_["relatedProducts"]:
            for r in rp["registrations"]:
                facts.append({"type": "related_registration", "product": pname, "relatedProduct": rp["commercialName"], "relationship": rp["relationship"],
                              "reviewStatus": rp["reviewStatus"], "country": r["countryCode"], "registrationNumber": r["registrationNumber"],
                              "statusNormalized": r["statusNormalized"], "statusOriginal": r["statusOriginal"], "sourceId": r["evidence"]["sourceId"],
                              "sourceUrl": r["evidence"]["sourceUrl"], "collectedAt": r["evidence"]["collectedAt"].isoformat(),
                              "validationStatus": r["evidence"]["validationStatus"]})
                evidence.append(r["evidence"])
        warnings += cmp_["warnings"]
    return facts, evidence, warnings, tools


# --------------------------------------------------------------------------- 3. template answer (always available)
LBL = {
    "fr": {"sisters": "Hypothèses de produits sœurs (à confirmer) : ", "none": "aucune", "official": "Noms officiels équivalents (même enregistrement) : ", "conf": "confiance",
           "status_w": "statut", "vstatus": "statut de validation", "missing": "champs manquants/incertains", "expires": "expire le", "days": "jours", "no": "n°",
           "uses": "usages", "source": "source", "collected": "collectée le", "validation": "validation", "related": "Produits liés (produits distincts, jamais fusionnés) :",
           "uses_h": "Usages (extrait) :", "nodose": "dose non structurée", "phi": "DAR", "maxapp": "appl. max",
           "nothing": "Aucune donnée trouvée dans les sources collectées pour cette question. Absence de résultat ≠ absence d'homologation."},
    "en": {"sisters": "Sister-product hypotheses (to confirm): ", "none": "none", "official": "Official equivalent names (same registration): ", "conf": "confidence",
           "status_w": "status", "vstatus": "validation status", "missing": "missing/uncertain", "expires": "expires on", "days": "days", "no": "no.",
           "uses": "uses", "source": "source", "collected": "collected", "validation": "validation", "related": "Related products (distinct products, never merged):",
           "uses_h": "Uses (excerpt):", "nodose": "dose not in structured source", "phi": "PHI", "maxapp": "max appl.",
           "nothing": "No data found in the collected sources for this question. No result is not proof of no registration."},
    "pt": {"sisters": "Hipóteses de produtos irmãos (a confirmar): ", "none": "nenhuma", "official": "Nomes oficiais equivalentes (mesmo registro): ", "conf": "confiança",
           "status_w": "situação", "vstatus": "estado de validação", "missing": "campos ausentes/incertos", "expires": "expira em", "days": "dias", "no": "nº",
           "uses": "usos", "source": "fonte", "collected": "coletada em", "validation": "validação", "related": "Produtos relacionados (produtos distintos, nunca fundidos):",
           "uses_h": "Usos (extrato):", "nodose": "dose não estruturada na fonte", "phi": "carência", "maxapp": "aplic. máx.",
           "nothing": "Nenhum dado encontrado nas fontes coletadas para esta pergunta. Ausência de resultado ≠ ausência de registro."},
}


def template_answer(pl: Plan, facts: list[dict], warnings: list[str], language: str) -> str:
    lang = (language or "fr").lower()[:2]
    L = LBL.get(lang, LBL["en"])
    fr = lang == "fr"
    regs = [f for f in facts if f["type"] == "registration"]
    lines: list[str] = []
    if pl.intent == "sister_product":
        al = [f for f in facts if f["type"] == "alias"]
        cands = [a for a in al if a["relationshipType"] in ("sister_product_candidate", "related_formulation")]
        offi = [a for a in al if a["relationshipType"] in ("alternate_name", "historical_name")]
        lines.append(L["sisters"] + (", ".join(f"{a['aliasName']} [{a['relationshipType']}, {L['conf']} {a['confidence']}, {L['status_w']} {a['reviewStatus']}]" for a in cands) or L["none"]))
        if offi:
            lines.append(L["official"] + ", ".join(f"{a['aliasName']} ({a['countryCode'] or '-'})" for a in offi))
    elif pl.intent == "data_quality":
        for f in facts:
            if f["type"] == "data_quality":
                lines.append(f"{f['country']} {f['registrationId']}: {L['vstatus']} = {f['validationStatus']}; {L['missing']} = {', '.join(f['missingOrUncertain']) or '-'}")
    elif pl.intent == "expiry":
        for f in regs:
            lines.append(f"{f['product']} — {f['country']} {f['registrationNumber']}: {L['expires']} {f['expirationDate']} ({f.get('daysLeft')} {L['days']}) — {f['sourceId']}")
    elif pl.intent == "changes":
        for f in facts[:20]:
            lines.append(f"{f.get('entityId')}: {f.get('field')} {f.get('oldValue')!r} -> {f.get('newValue')!r} ({'snapshot' if fr else 'snapshot'} {f.get('fromSnapshotId')}->{f.get('toSnapshotId')})")
    else:
        for f in regs:
            lines.append(f"{f['product']} — {Q.COUNTRY_NAMES.get(f['country'], f['country'])} ({f['country']}): {L['no']} {f['registrationNumber']}, "
                         f"{L['status_w']} {f['statusNormalized']} (« {f['statusOriginal']} »), {f['usesCount']} {L['uses']}, {L['source']} {f['sourceId']} "
                         f"{L['collected']} {f['collectedAt'][:10]}, {L['validation']}: {f['validationStatus']}")
        for f in facts:
            if f["type"] == "coverage":
                lines.append(f"{f['product']} — {Q.COUNTRY_NAMES.get(f['country'], f['country'])} ({f['country']}): {f['note']}")
        rel = [f for f in facts if f["type"] == "related_registration"]
        if rel:
            lines.append("")
            lines.append(L["related"])
            for f in rel:
                lines.append(f"  {f['relatedProduct']} [{f['relationship']}, {f['reviewStatus']}] — {Q.COUNTRY_NAMES.get(f['country'], f['country'])} "
                             f"({f['country']}): {L['no']} {f['registrationNumber']}, {f['statusNormalized']} (« {f['statusOriginal']} »), {f['sourceId']} {f['collectedAt'][:10]}")
        uses = [f for f in facts if f["type"] == "use"]
        if uses:
            lines.append("")
            lines.append(L["uses_h"])
            for u in uses[:24]:
                dose = f"{u['dose']} {u['doseUnit']}" if u.get("dose") is not None else L["nodose"]
                lines.append(f"  {u['country']} {u['registrationNumber']}: {u.get('crop')} → {u.get('target')} | {dose}"
                             + (f" | {L['phi']} {u['phiDays']} j" if u.get("phiDays") is not None else "") + (f" | {L['maxapp']} {u['maxApplications']}" if u.get("maxApplications") else "")
                             + (f" | {u['pairing']}" if u.get("pairing") and u["pairing"] != "source_paired" else ""))
    if not lines:
        lines.append(L["nothing"])
    return "\n".join(lines)



# --------------------------------------------------------------------------- 3b. structured answer (deterministic)
CNAME = {"fr": {"CA": "Canada", "US": "États-Unis", "FR": "France", "BR": "Brésil", "DE": "Allemagne", "BE": "Belgique", "MX": "Mexique", "UY": "Uruguay", "ES": "Espagne", "IT": "Italie", "NL": "Pays-Bas", "GB": "Royaume-Uni", "PL": "Pologne"},
         "en": {"CA": "Canada", "US": "United States", "FR": "France", "BR": "Brazil", "DE": "Germany", "BE": "Belgium", "MX": "Mexico", "UY": "Uruguay", "ES": "Spain", "IT": "Italy", "NL": "Netherlands", "GB": "United Kingdom", "PL": "Poland"},
         "pt": {"CA": "Canadá", "US": "Estados Unidos", "FR": "França", "BR": "Brasil", "DE": "Alemanha", "BE": "Bélgica", "MX": "México", "UY": "Uruguai", "ES": "Espanha", "IT": "Itália", "NL": "Países Baixos", "GB": "Reino Unido", "PL": "Polônia"}}

# English warning templates (API contract, tests) -> French / Portuguese wording for the caveats shown to the reader.
WARN_I18N: list[tuple[re.Pattern, dict[str, str]]] = [
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): not found in (?P<src>\S+) as of (?P<date>\d{4}-\d\d-\d\d) - this is not proof of no registration\.$"),
     {"fr": "{name} ({cc}) : non trouvé dans {src} au {date} — ce n'est pas une preuve d'absence d'homologation.",
      "pt": "{name} ({cc}): não encontrado em {src} em {date} — isto não prova ausência de registro."}),
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): no source connected - unknown, not 'not registered'\.$"),
     {"fr": "{name} ({cc}) : aucune source connectée — inconnu, pas « non homologué ».", "pt": "{name} ({cc}): nenhuma fonte conectada — desconhecido, não « não registrado »."}),
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): no registration of this product, but related product '(?P<rel>.+?)' \((?P<type>[a-z_]+), (?P<review>[a-z_]+)\) has n° (?P<num>\S+) - a distinct product, not an equivalent\.$"),
     {"fr": "{name} ({cc}) : pas d'enregistrement de ce produit, mais le produit lié « {rel} » ({type}, {review}) porte le n° {num} — produit distinct, pas un équivalent.",
      "pt": "{name} ({cc}): nenhum registro deste produto, mas o produto relacionado « {rel} » ({type}, {review}) tem o nº {num} — produto distinto, não equivalente."}),
    (re.compile(r"^(?P<cc>\w\w) (?P<num>\S+): dose is not in the structured source; only the official label PDF states it\.$"),
     {"fr": "{cc} {num} : la dose n'est pas dans la source structurée ; seule l'étiquette officielle (PDF) l'indique.",
      "pt": "{cc} {num}: a dose não está na fonte estruturada; apenas o rótulo oficial (PDF) a indica."}),
    (re.compile(r"^(?P<cc>\w\w) (?P<num>\S+): the source lists crops and targets as two independent lists; crop-target pairs are not asserted by the source\.$"),
     {"fr": "{cc} {num} : la source liste cultures et cibles comme deux listes indépendantes ; les couples culture-cible ne sont pas affirmés par la source.",
      "pt": "{cc} {num}: a fonte lista culturas e alvos como duas listas independentes; os pares cultura-alvo não são afirmados pela fonte."}),
    (re.compile(r"^(?P<cc>\w\w) (?P<num>\S+): some uses were extracted from the label PDF by an AI model \(extraction_method=llm_pdf\) and are not yet validated\.$"),
     {"fr": "{cc} {num} : certains usages ont été extraits de l'étiquette PDF par un modèle d'IA (extraction_method=llm_pdf) et ne sont pas encore validés.",
      "pt": "{cc} {num}: alguns usos foram extraídos do rótulo PDF por um modelo de IA (extraction_method=llm_pdf) e ainda não foram validados."}),
    (re.compile(r"^(?P<cc>\w\w) (?P<num>\S+): automatically extracted, not yet validated by Regulatory Affairs\.$"),
     {"fr": "{cc} {num} : extraction automatique, non encore validée par Regulatory Affairs.", "pt": "{cc} {num}: extração automática, ainda não validada pelo Regulatory Affairs."}),
    (re.compile(r"^No known product name recognised in the question(?P<unres> \(unresolved: .+?\))?\. Nothing was found in the collected sources; this is not proof of no registration\. Try the exact commercial name or an alias\.$"),
     {"fr": "Aucun nom de produit connu reconnu dans la question{unres}. Rien n'a été trouvé dans les sources collectées ; ce n'est pas une preuve d'absence d'homologation. Essayez le nom commercial exact ou un alias.",
      "pt": "Nenhum nome de produto conhecido reconhecido na pergunta{unres}. Nada foi encontrado nas fontes coletadas; isto não prova ausência de registro. Tente o nome comercial exato ou um alias."}),
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): no product of scope '(?P<scope>\w+)' found in (?P<src>\S+) as of (?P<date>\d{4}-\d\d-\d\d) - this is not proof of no registration\.$"),
     {"fr": "{name} ({cc}) : aucun produit du périmètre « {scope} » dans {src} au {date} — ce n'est pas une preuve d'absence d'homologation.",
      "pt": "{name} ({cc}): nenhum produto do escopo « {scope} » em {src} em {date} — isto não prova ausência de registro."}),
    (re.compile(r"^(?P<name>.+?) \((?P<cc>\w\w)\): (?P<n>\d+) registrations in scope '(?P<scope>\w+)', only the first 40 are listed - narrow the question \(e\.g\. 'Lallemand products'\)\.$"),
     {"fr": "{name} ({cc}) : {n} enregistrements dans le périmètre « {scope} », seuls les 40 premiers sont listés — précisez la question (ex. « produits Lallemand »).",
      "pt": "{name} ({cc}): {n} registros no escopo « {scope} », apenas os 40 primeiros são listados — restrinja a pergunta (ex. « produtos Lallemand »)."}),
    (re.compile(r"^Scope 'Lallemand' = registrations whose holder contains LALLEMAND or DANSTAR in the official source; distributor registrations are not included\.$"),
     {"fr": "Périmètre « Lallemand » = enregistrements dont le titulaire contient LALLEMAND ou DANSTAR dans la source officielle ; les enregistrements de distributeurs ne sont pas inclus.",
      "pt": "Escopo « Lallemand » = registros cujo titular contém LALLEMAND ou DANSTAR na fonte oficial; registros de distribuidores não estão incluídos."}),
    (re.compile(r"^Crop '(?P<crop>.+?)' was not applied to this country listing; ask with a product or a micro-organism to filter by crop\.$"),
     {"fr": "La culture « {crop} » n'a pas été appliquée à cette liste par pays ; posez la question avec un produit ou un micro-organisme pour filtrer par culture.",
      "pt": "A cultura « {crop} » não foi aplicada a esta lista por país; pergunte com um produto ou um microrganismo para filtrar por cultura."}),
    (re.compile(r"^Context taken from the conversation: (?P<what>.+)\.$"),
     {"fr": "Contexte repris de la conversation : {what}.", "pt": "Contexto retomado da conversa: {what}."}),
    (re.compile(r"^Sister-product candidates are hypotheses with a review status; none is a confirmed equivalent unless review_status=validated\.$"),
     {"fr": "Les candidats « produit sœur » sont des hypothèses avec un statut de revue ; aucun n'est un équivalent confirmé sauf review_status=validated.",
      "pt": "Os candidatos a « produto irmão » são hipóteses com um estado de revisão; nenhum é equivalente confirmado salvo review_status=validated."}),
    (re.compile(r"^No registration with an expiry date within (?P<m>\d+) months in the collected sources; BR and US sources give no expiry dates\.$"),
     {"fr": "Aucun enregistrement avec une date d'expiration dans les {m} mois dans les sources collectées ; les sources BR et US ne donnent pas de date d'expiration.",
      "pt": "Nenhum registro com data de vencimento nos próximos {m} meses nas fontes coletadas; as fontes BR e US não informam datas de vencimento."}),
    (re.compile(r"^Expiry dates exist only in CA-PPID and FR-EPHY \(withdrawal date\); US-EPA-PPLS and BR-AGROFIT do not publish them\.$"),
     {"fr": "Les dates d'expiration n'existent que dans CA-PPID et FR-EPHY (date de retrait) ; US-EPA-PPLS et BR-AGROFIT ne les publient pas.",
      "pt": "As datas de vencimento existem apenas em CA-PPID e FR-EPHY (data de retirada); US-EPA-PPLS e BR-AGROFIT não as publicam."}),
    (re.compile(r"^No change detected yet: change detection needs at least two collections of the same source\.$"),
     {"fr": "Aucun changement détecté pour l'instant : la détection nécessite au moins deux collectes de la même source.",
      "pt": "Nenhuma mudança detectada ainda: a detecção exige pelo menos duas coletas da mesma fonte."}),
    (re.compile(r"^No micro-organism species recognised in the question \(known species are those present in the store, e\.g\. (?P<ex>.+?)\)\.$"),
     {"fr": "Aucune espèce de micro-organisme reconnue dans la question (espèces connues : celles présentes dans la base, ex. {ex}).",
      "pt": "Nenhuma espécie de microrganismo reconhecida na pergunta (espécies conhecidas: as presentes na base, ex. {ex})."}),
    (re.compile(r"^No product with '(?P<sp>.+?)'(?P<crop> on crop '.+?')? in the collected sources - not proof of absence\.$"),
     {"fr": "Aucun produit avec « {sp} »{crop} dans les sources collectées — pas une preuve d'absence.",
      "pt": "Nenhum produto com « {sp} »{crop} nas fontes coletadas — não prova ausência."}),
    (re.compile(r"^Crop filter applied on normalized and original crop wording; CA/US crop lists are not paired with targets by the source\.$"),
     {"fr": "Filtre culture appliqué sur le libellé normalisé et original ; les listes de cultures CA/US ne sont pas appariées aux cibles par la source.",
      "pt": "Filtro de cultura aplicado ao texto normalizado e original; as listas de culturas CA/US não são pareadas com os alvos pela fonte."}),
    (re.compile(r"^AI phrasing rejected by the grounding guard \((?P<why>.+)\); deterministic answer shown instead\.$"),
     {"fr": "Formulation IA rejetée par le garde-fou d'ancrage ({why}) ; réponse déterministe affichée.",
      "pt": "Formulação da IA rejeitada pela proteção de fundamentação ({why}); resposta determinística exibida."}),
    (re.compile(r"^AI provider unavailable \((?P<kind>.+)\); deterministic answer shown, built from the same facts\.$"),
     {"fr": "Fournisseur d'IA indisponible ({kind}) ; réponse déterministe affichée, construite à partir des mêmes faits.",
      "pt": "Provedor de IA indisponível ({kind}); resposta determinística exibida, construída a partir dos mesmos fatos."}),
]


def localize_warning(w: str, lang: str) -> str:
    """French/Portuguese wording of a known English warning; unknown wording is returned unchanged."""
    if lang == "en":
        return w
    for rx, tpl in WARN_I18N:
        m = rx.match(w)
        if m and lang in tpl:
            gd = {k: (v or "") for k, v in m.groupdict().items()}
            if gd.get("cc") in CNAME.get(lang, {}) and "name" in gd:
                gd["name"] = CNAME[lang][gd["cc"]]  # country name in the reader's language
            return tpl[lang].format(**gd)
    return w


def build_structured(pl: Plan, facts: list[dict], warnings: list[str], language: str) -> StructuredAnswer:
    """Compact, question-shaped answer from the facts: one headline, only the relevant rows, short caveats."""
    lang = (language or "fr").lower()[:2]
    L = LBL.get(lang, LBL["en"])
    H = HEAD.get(lang, HEAD["en"])
    regs = [f for f in facts if f["type"] == "registration"]
    cov = [f for f in facts if f["type"] == "coverage"]
    rel = [f for f in facts if f["type"] == "related_registration"]
    items: list[AnswerItem] = []
    caveats: list[str] = []
    name = regs[0]["product"] if regs else (cov[0]["product"] if cov else None)

    def item_from_reg(f, detail=None):
        return AnswerItem(country=f["country"], product=f.get("product"), registrationNumber=f.get("registrationNumber"), status=f.get("statusNormalized"),
                          statusOriginal=f.get("statusOriginal"), expiry=f.get("expirationDate"), detail=detail, sourceId=f.get("sourceId"),
                          collectedAt=(f.get("collectedAt") or "")[:10] or None)

    if pl.intent == "sister_product":
        al = [f for f in facts if f["type"] == "alias"]
        cands = [a for a in al if a["relationshipType"] in ("sister_product_candidate", "related_formulation", "confirmed_sister_product", "related_product")]
        for a in cands[:12]:
            items.append(AnswerItem(product=a["aliasName"], country=a.get("countryCode"), relationship=f"{a['relationshipType']} · {a['reviewStatus']} · {L['conf']} {a['confidence']}",
                                    detail=(a.get("evidence") or "")[:160] or None, sourceId=None))
        n_conf = sum(1 for a in cands if a["reviewStatus"] == "validated")
        headline = H["sisters"].format(product=al[0]["product"] if al else "", n=len(cands), nc=n_conf)
        caveats.append(H["sisters_caveat"])
    elif pl.intent == "data_quality":
        dq = [f for f in facts if f["type"] == "data_quality"]
        for f in dq:
            items.append(AnswerItem(country=f["country"], product=f.get("product"), registrationNumber=f["registrationId"].split("-", 2)[-1], status=f["validationStatus"],
                                    detail=", ".join(f["missingOrUncertain"]) or "—"))
        headline = H["quality"].format(product=dq[0]["product"] if dq else "", n=len(dq))
    elif pl.intent == "expiry":
        for f in regs[:12]:
            items.append(item_from_reg(f, detail=f"{f.get('daysLeft')} {L['days']}" if f.get("daysLeft") is not None else None))
        headline = H["expiry"].format(n=len(regs), m=pl.months)
    elif pl.intent == "changes":
        ch = [f for f in facts if f["type"] == "change"]
        for f in ch[:12]:
            items.append(AnswerItem(registrationNumber=f.get("entityId"), detail=f"{f.get('field')}: {f.get('oldValue')} → {f.get('newValue')}", collectedAt=(f.get("detectedAt") or "")[:10]))
        headline = H["changes"].format(n=len(ch))
    elif pl.intent == "country_portfolio":
        CN = CNAME.get(lang, CNAME["en"])
        scope_txt = H["scope_lallemand"] if pl.scope == "lallemand" else ""
        for f in regs[:12]:
            items.append(item_from_reg(f, detail=f.get("activeEntityNormalized") or f.get("holder")))
        parts = []
        for f in [x for x in facts if x["type"] == "portfolio"]:
            cn = CN.get(f["country"], f["country"])
            if f["coverage"] == "source_not_collected":
                parts.append(H["pf_nosrc"].format(country=cn))
            elif f["total"] == 0:
                parts.append(H["pf_none"].format(country=cn, scope=scope_txt, source=f.get("sourceId"), date=(f.get("collectedAt") or "")[:10]))
            else:
                parts.append(H["pf"].format(country=cn, n=f["total"], scope=scope_txt, source=f.get("sourceId"), date=(f.get("collectedAt") or "")[:10]))
                if f["total"] > 12:
                    caveats.append(H["pf_more"].format(more=f["total"] - 12))
        headline = " ".join(parts) or L["nothing"]
    elif pl.intent in ("ingredient_search",):
        for f in regs[:12]:
            uses = [u for u in facts if u["type"] == "use" and u.get("registrationNumber") == f["registrationNumber"]]
            det = "; ".join(f"{u.get('crop')} → {u.get('target')}" + (f", {u['dose']} {u['doseUnit']}" if u.get("dose") is not None else "") for u in uses[:2]) or None
            items.append(item_from_reg(f, detail=det))
        headline = H["ingredient"].format(species=pl.species or "", crop=f" · {pl.crop}" if pl.crop else "", n=len(regs), nc=len({f["country"] for f in regs}))
    else:  # registration_lookup, use_comparison, source
        for f in regs[:12]:
            if pl.intent == "use_comparison":
                uses = [u for u in facts if u["type"] == "use" and u.get("registrationNumber") == f["registrationNumber"]
                        and (u.get("target") or "").strip().upper() not in ("NO PEST", "")]
                nodose_all = bool(uses) and all(u.get("dose") is None for u in uses)
                short = lambda x, n=38: (x or "")[:n] + ("…" if x and len(x) > n else "")  # noqa: E731
                det = "; ".join(f"{short(u.get('crop'))} → {short(u.get('target'), 30)}" + (f", {u['dose']} {u['doseUnit']}" if u.get("dose") is not None else "") for u in uses[:3])
                det = (det + (f" … +{len(uses) - 3}" if len(uses) > 3 else "") + (f" · {L['nodose']}" if nodose_all else "")) or None
            else:
                det = f"{f.get('usesCount')} {L['uses']}" if f.get("usesCount") is not None else None
            items.append(item_from_reg(f, detail=det))
        for c in cov:
            items.append(AnswerItem(country=c["country"], product=c.get("product"), status=c["coverage"], detail=H["cov_" + c["coverage"]], sourceId=None))
        for r in rel[:6]:
            items.append(AnswerItem(country=r["country"], product=r["relatedProduct"], registrationNumber=r.get("registrationNumber"), status=r.get("statusNormalized"),
                                    statusOriginal=r.get("statusOriginal"), relationship=f"{r['relationship']} · {r['reviewStatus']}", sourceId=r.get("sourceId"),
                                    collectedAt=(r.get("collectedAt") or "")[:10]))
        found = sorted({f["country"] for f in regs})
        not_found = sorted({c["country"] for c in cov if c["coverage"] == "not_found_in_source"})
        no_src = sorted({c["country"] for c in cov if c["coverage"] == "source_not_collected"})
        if regs:
            headline = H["lookup"].format(product=name or "", countries=", ".join(found), n=len(regs))
            if not_found:
                headline += " " + H["lookup_nf"].format(countries=", ".join(not_found))
            if no_src:
                headline += " " + H["lookup_ns"].format(countries=", ".join(no_src))
        elif cov:
            headline = H["lookup_none"].format(product=name or "", nf=", ".join(not_found) or "—", ns=", ".join(no_src) or "—")
        else:
            headline = L["nothing"]
        if pl.intent == "use_comparison" and regs:
            headline = H["compare"].format(product=name or "", countries=", ".join(found), n=sum(f.get("usesCount") or 0 for f in regs))
    for w in warnings:
        if len(caveats) >= 4:
            break
        if any(k in w for k in ("Context taken", "not proof", "dose is not", "two independent lists", "AI model", "hypotheses", "no source connected", "only the first", "Scope 'Lallemand'", "was not applied")):
            caveats.append(localize_warning(w, lang))
    return StructuredAnswer(headline=headline, items=items[:12], caveats=caveats[:4])


HEAD = {
    "fr": {"lookup": "{product} : {n} enregistrement(s) trouvé(s) dans les sources officielles collectées pour {countries}.",
           "lookup_nf": "Non trouvé dans la source officielle de : {countries} (≠ non homologué).", "lookup_ns": "Aucune source connectée pour : {countries}.",
           "lookup_none": "{product} : aucun enregistrement dans les sources collectées (non trouvé : {nf} ; source non connectée : {ns}). Ce n'est pas une preuve d'absence d'homologation.",
           "compare": "{product} : usages comparés pour {countries} ({n} usages au total).", "sisters": "{product} : {n} produit(s) lié(s) ou sœur(s), dont {nc} confirmé(s) par LPC ; le reste est une hypothèse à confirmer.",
           "sisters_caveat": "Les candidats sont des hypothèses tant qu'un relecteur ne les a pas validés.", "quality": "{product} : {n} enregistrement(s) ; champs manquants ou incertains listés par pays.",
           "expiry": "{n} autorisation(s) active(s) expirent dans les {m} prochains mois (sources avec date : Canada, France).", "changes": "{n} changement(s) détecté(s) entre deux collectes.",
           "ingredient": "{species}{crop} : {n} enregistrement(s) dans {nc} pays.",
           "cov_not_found_in_source": "non trouvé dans la source officielle collectée — pas une preuve d'absence", "cov_source_not_collected": "aucune source officielle connectée — inconnu",
           "pf": "{country} : {n} enregistrement(s){scope} dans {source} (collecte du {date}).", "pf_none": "{country} : aucun enregistrement{scope} dans {source} (collecte du {date}) — pas une preuve d'absence.",
           "pf_nosrc": "{country} : aucune source officielle connectée — inconnu.", "pf_more": "{more} autre(s) enregistrement(s) non affiché(s) ; précisez la question (ex. « produits Lallemand »).",
           "scope_lallemand": " de titulaire Lallemand/Danstar"},
    "en": {"lookup": "{product}: {n} registration(s) found in the collected official sources for {countries}.",
           "lookup_nf": "Not found in the official source of: {countries} (≠ not registered).", "lookup_ns": "No source connected for: {countries}.",
           "lookup_none": "{product}: no registration in the collected sources (not found: {nf}; source not connected: {ns}). This is not proof of no registration.",
           "compare": "{product}: uses compared for {countries} ({n} uses in total).", "sisters": "{product}: {n} related or sister product(s), {nc} confirmed by LPC; the rest are hypotheses to confirm.",
           "sisters_caveat": "Candidates remain hypotheses until a reviewer validates them.", "quality": "{product}: {n} registration(s); missing or uncertain fields listed per country.",
           "expiry": "{n} active authorisation(s) expire within the next {m} months (sources with dates: Canada, France).", "changes": "{n} change(s) detected between two collections.",
           "ingredient": "{species}{crop}: {n} registration(s) in {nc} countries.",
           "cov_not_found_in_source": "not found in the collected official source — not proof of absence", "cov_source_not_collected": "no official source connected — unknown",
           "pf": "{country}: {n} registration(s){scope} in {source} (collected {date}).", "pf_none": "{country}: no registration{scope} in {source} (collected {date}) — not proof of absence.",
           "pf_nosrc": "{country}: no official source connected — unknown.", "pf_more": "{more} more registration(s) not shown; narrow the question (e.g. 'Lallemand products').",
           "scope_lallemand": " held by Lallemand/Danstar"},
    "pt": {"lookup": "{product}: {n} registro(s) encontrado(s) nas fontes oficiais coletadas para {countries}.",
           "lookup_nf": "Não encontrado na fonte oficial de: {countries} (≠ não registrado).", "lookup_ns": "Nenhuma fonte conectada para: {countries}.",
           "lookup_none": "{product}: nenhum registro nas fontes coletadas (não encontrado: {nf}; fonte não conectada: {ns}). Isto não prova ausência de registro.",
           "compare": "{product}: usos comparados para {countries} ({n} usos no total).", "sisters": "{product}: {n} produto(s) relacionado(s) ou irmão(s), {nc} confirmado(s) pela LPC; o restante são hipóteses a confirmar.",
           "sisters_caveat": "Os candidatos permanecem hipóteses até que um revisor os valide.", "quality": "{product}: {n} registro(s); campos ausentes ou incertos listados por país.",
           "expiry": "{n} autorização(ões) ativa(s) vencem nos próximos {m} meses (fontes com data: Canadá, França).", "changes": "{n} mudança(s) detectada(s) entre duas coletas.",
           "ingredient": "{species}{crop}: {n} registro(s) em {nc} países.",
           "cov_not_found_in_source": "não encontrado na fonte oficial coletada — não prova ausência", "cov_source_not_collected": "nenhuma fonte oficial conectada — desconhecido",
           "pf": "{country}: {n} registro(s){scope} em {source} (coleta de {date}).", "pf_none": "{country}: nenhum registro{scope} em {source} (coleta de {date}) — não prova ausência.",
           "pf_nosrc": "{country}: nenhuma fonte oficial conectada — desconhecido.", "pf_more": "{more} outro(s) registro(s) não exibido(s); restrinja a pergunta (ex. « produtos Lallemand »).",
           "scope_lallemand": " de titular Lallemand/Danstar"},
}

# --------------------------------------------------------------------------- 4. LLM phrasing + guard
SYSTEM = """You are the answer writer of a regulatory-watch prototype for plant protection products, used by Regulatory Affairs.
You receive the QUESTION, FACTS (rows from official sources, already filtered) and WARNINGS, plus a DRAFT built deterministically.
Return a JSON object matching the schema (headline, items, caveats) in the requested language.
Rules:
- headline: answer the question directly in one or two sentences. No row dump, no list of columns.
- items: ONLY the rows that support the headline, and in each item ONLY the fields that matter for this question
  (e.g. for 'in which countries' -> country, registrationNumber, status, expiry; for a use comparison -> crop → target, dose; for sister products -> relationship).
  Keep product names, numbers, dates, statuses and doses exactly as written in FACTS. Max 12 items.
- caveats: at most 4 short sentences from WARNINGS that the reader must know (dose not in structured source, unpaired lists, not proof of absence, hypothesis).
- Never add a country, product, number, date, dose or status that is not in FACTS. If FACTS are empty, say that nothing was found and that this is not proof of no registration.
- A sister-product candidate is a hypothesis unless its review status is 'validated'.
- Write the headline, the item details and the caveats in the requested language (translate WARNINGS; keep identifiers, numbers, dates and status values as written).
- CONVERSATION (earlier turns) is given for wording only: never reuse a number, product or country from it unless it is in FACTS.
- No advice on product use."""


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d\-/.,]*\d|\d", text))


def guard(llm_text: str, facts: list[dict], warnings: list[str]) -> tuple[bool, str | None]:
    """Reject any LLM answer containing a number or country code not present in the facts/warnings."""
    allowed = _numbers(json.dumps(facts, ensure_ascii=False, default=str) + " " + " ".join(warnings))
    for n in _numbers(llm_text):
        if n not in allowed and not re.fullmatch(r"\d{1,2}", n):  # small counts (e.g. '3 countries') are tolerated
            return False, f"unsupported number '{n}' in model text"
    ccs = set(re.findall(r"\b([A-Z]{2})\b", llm_text)) & set(Q.COUNTRY_SOURCES) | set(re.findall(r"\b(DE|BE|MX|UY|ES|IT|NL|GB|PL)\b", llm_text))
    fact_ccs = {f.get("country") for f in facts if f.get("country")} | set(re.findall(r"\(([A-Z]{2})\)", " ".join(warnings)))
    for cc in ccs - fact_ccs:
        if cc in Q.COUNTRY_WORDS if hasattr(Q, "COUNTRY_WORDS") else cc in COUNTRY_WORDS:
            return False, f"country {cc} not in facts"
    return True, None


def ask(session: Session, question: str, language: str = "fr", context: dict | None = None, history: list[dict] | None = None) -> dict:
    pl = plan(session, question, context)
    facts, evidence, warnings, tools = run_tools(session, pl)
    structured = build_structured(pl, facts, warnings, language)
    text = structured.to_text(language)
    model = None
    if settings.ai_enabled and facts:
        try:
            client = get_client()
            conv = "".join(f"- {h.get('role')}: {str(h.get('content') or '')[:300]}\n" for h in (history or [])[-6:] if isinstance(h, dict))
            user = ((f"CONVERSATION (earlier turns, wording only):\n{conv}\n" if conv else "")
                    + f"QUESTION ({language}): {question}\n\nFACTS (JSON rows):\n{json.dumps(facts[:60], ensure_ascii=False, default=str)}\n\n"
                    f"WARNINGS:\n- " + "\n- ".join(warnings[:12]) + f"\n\nDRAFT (same shape; improve selection and wording, never content):\n{structured.model_dump_json()}")
            data = client.chat_json(SYSTEM, user, schema=ANSWER_SCHEMA, max_tokens=1200)
            cand = StructuredAnswer.model_validate(data)
            cand.items = cand.items[:12]
            cand.caveats = cand.caveats[:4]
            ok, why = guard(cand.to_text(language), facts, warnings)
            if ok and cand.headline.strip():
                structured, text, model = cand, cand.to_text(language), client.model
            else:
                warnings.append(f"AI phrasing rejected by the grounding guard ({why}); deterministic answer shown instead.")
        except (LLMUnavailable, ValueError) as e:
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
    lang = (language or "fr").lower()[:2]
    return {"answer": text, "evidence": ev[:50], "warnings": list(dict.fromkeys(warnings)), "disclaimer": DISCLAIMER,
            "facts": facts[:200], "intent": pl.intent, "toolsUsed": list(dict.fromkeys(tools)), "model": model,
            "structured": structured.model_dump(), "warningsLocalized": [localize_warning(w, lang) for w in dict.fromkeys(warnings)],
            "context": {"productIds": pl.product_ids, "countries": pl.countries, "species": pl.species, "crop": pl.crop, "intent": pl.intent}}
