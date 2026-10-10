"""Gold questions T01–T05 (evaluation/gold_questions.csv) through POST /ask, deterministic path.

Each test asserts the required facts are present AND the forbidden behaviour is absent.
Adversarial cases check the agent does not invent anything for unknown products or uncovered markets.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = {r["test_id"]: r for r in csv.DictReader((ROOT / "evaluation" / "gold_questions.csv").open(encoding="utf-8-sig"))}


def _ask(client, q, lang="fr"):
    r = client.post("/ask", json={"question": q, "language": lang})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["disclaimer"] and isinstance(d["warnings"], list) and isinstance(d["evidence"], list)
    for e in d["evidence"]:
        assert e["sourceId"] and e["sourceUrl"].startswith("http") and e["collectedAt"] and e["validationStatus"]
    return d


def test_T01_countries_where_pilot_is_registered(api_client):
    d = _ask(api_client, GOLD["T01"]["question_fr"].replace("le produit pilote", "LALSTOP CONTANS WG"))
    assert d["intent"] == "registration_lookup" and "compare" in d["toolsUsed"]
    regs = [f for f in d["facts"] if f["type"] == "registration"]
    assert {f["country"] for f in regs} == {"CA", "US", "FR"}
    for f in regs:  # required facts: country, status, source_url, collected_at, validation_status
        assert f["statusNormalized"] and f["sourceUrl"].startswith("http") and f["collectedAt"] and f["validationStatus"]
    # forbidden: claiming no registration from no result -> BR must be explained as 'not found in source', not 'not registered'
    br = next(f for f in d["facts"] if f["type"] == "coverage" and f["country"] == "BR")
    assert br["coverage"] == "not_found_in_source" and "Not proof of no registration" in br["note"]
    assert "non enregistré" not in d["answer"].lower() and "pas homologué" not in d["answer"].lower()
    assert len(d["evidence"]) >= 3


def test_T02_compare_uses_between_two_countries_without_mixing(api_client):
    d = _ask(api_client, "Comparer les usages de LALSTOP CONTANS WG entre la France et le Canada.")
    assert d["intent"] == "use_comparison"
    uses = [f for f in d["facts"] if f["type"] == "use"]
    assert {u["country"] for u in uses} == {"FR", "CA"}
    fr = [u for u in uses if u["country"] == "FR"]
    ca = [u for u in uses if u["country"] == "CA"]
    assert fr[0]["dose"] == 4.0 and fr[0]["doseUnit"] == "kg/ha" and fr[0]["restrictions"]
    assert all(u["dose"] is None for u in ca), "CA dose is not structured; must not borrow the FR dose"
    assert all(u["registrationNumber"] == "9900189" for u in fr) and all(u["registrationNumber"] == "29066" for u in ca)
    assert any("dose is not in the structured source" in w for w in d["warnings"])
    assert "US" not in {u["country"] for u in uses}  # only the two requested countries


def test_T03_uncertain_fields_are_listed_not_hidden(api_client):
    d = _ask(api_client, "Quels champs sont incertains ou manquants pour LALGUARD M52 OD ?")
    assert d["intent"] == "data_quality"
    dq = [f for f in d["facts"] if f["type"] == "data_quality"]
    assert {f["country"] for f in dq} == {"CA", "FR", "US"}
    us = next(f for f in dq if f["country"] == "US")
    assert "approvalDate" in us["missingOrUncertain"] and "expirationDate" in us["missingOrUncertain"] and "uses (none in source)" in us["missingOrUncertain"]
    assert all(f["validationStatus"] == "automatically_extracted" for f in dq)
    assert d["warnings"] and any("not yet validated" in w for w in d["warnings"])


def test_T04_sister_products_are_hypotheses(api_client):
    d = _ask(api_client, GOLD["T04"]["question_fr"].rstrip(" ?") + " de LALSTOP G46 WG ?")
    assert d["intent"] == "sister_product"
    al = [f for f in d["facts"] if f["type"] == "alias"]
    cands = [f for f in al if f["relationshipType"] == "sister_product_candidate"]
    assert cands and cands[0]["aliasName"] == "PRIMASTOP BIOFUNGICIDE POWDER" and cands[0]["reviewStatus"] == "to_verify" and cands[0]["evidence"]
    confirmed = [f for f in al if f["relationshipType"] == "confirmed_sister_product"]
    assert confirmed and confirmed[0]["aliasName"] == "PRESTOP" and confirmed[0]["reviewStatus"] == "validated" and "LPC answer" in confirmed[0]["evidence"]
    related = [f for f in al if f["relationshipType"] == "related_product"]
    assert {f["aliasName"] for f in related} == {"PRESTOP WG", "LALFRESH S"}  # LPC: distinct products, never merged
    assert "hypoth" in d["answer"].lower() or "à confirmer" in d["answer"].lower()
    assert "sister_product_candidate · to_verify · confiance 0.8" in d["answer"]  # hypothesis shown with its status, not as a fact
    assert d["structured"]["headline"] and len(d["structured"]["items"]) >= 3 and d["structured"]["caveats"]
    assert any("hypotheses" in w for w in d["warnings"])


def test_T05_official_source_of_each_datum(api_client):
    d = _ask(api_client, "Donne la source officielle de chaque donnée pour LALSTOP CONTANS WG.")
    regs = [f for f in d["facts"] if f["type"] == "registration"]
    assert regs and all(f["sourceId"] in ("CA-PPID", "US-EPA-PPLS", "FR-EPHY") and f["sourceUrl"].startswith("http") and f["collectedAt"] for f in regs)
    assert {e["sourceId"] for e in d["evidence"]} == {"CA-PPID", "US-EPA-PPLS", "FR-EPHY"}
    assert "CA-PPID" in d["answer"] and "2026-10-09" in d["answer"]


def test_adversarial_unknown_product_yields_no_facts(api_client):
    d = _ask(api_client, "Dans quels pays le produit FOOBARIX 3000 est-il homologué ?")
    assert not [f for f in d["facts"] if f["type"] in ("registration", "coverage", "use")] and d["evidence"] == []  # only the store scope is returned, nothing invented
    assert any("not proof of no registration" in w for w in d["warnings"])
    assert "FOOBARIX" in " ".join(d["warnings"])  # the unresolved name is echoed, nothing invented
    assert "homologu" not in d["answer"].lower() or "absence" in d["answer"].lower()


def test_adversarial_uncovered_market_is_unknown_not_absent(api_client):
    d = _ask(api_client, "LALSTOP CONTANS WG est-il homologué en Allemagne ?")
    cov = [f for f in d["facts"] if f["type"] == "coverage"]
    assert cov and cov[0]["country"] == "DE" and cov[0]["coverage"] == "source_not_collected"
    assert any("no source connected" in w for w in d["warnings"])
    assert d["evidence"] == []  # nothing to cite for DE


def test_ingredient_question_on_a_crop(api_client):
    d = _ask(api_client, "Quels produits contenant Clonostachys rosea sont homologués sur la fraise ?")
    assert d["intent"] == "ingredient_search"
    regs = [f for f in d["facts"] if f["type"] == "registration"]
    assert {(f["country"], f["registrationNumber"]) for f in regs} == {("FR", "2230771"), ("CA", "32404")}
    assert all("Clonostachys rosea" in f["activeEntityNormalized"] for f in regs)
    assert {f["product"] for f in regs} == {"LALSTOP G46 WG", "PRESTOP WG"}  # two distinct products on strawberry


def test_other_products_countries_and_crops_like_the_jury_will(api_client):
    """LPC said they will test the same intents with other products, countries and crops."""
    d = _ask(api_client, "Where is PRESTOP registered and with which status?", "en")
    regs = [f for f in d["facts"] if f["type"] == "registration"]
    assert {(f["country"], f["statusNormalized"]) for f in regs} == {("CA", "active"), ("US", "withdrawn")}
    d2 = _ask(api_client, "Which products containing Metarhizium brunneum are registered on strawberries in France?", "en")
    regs2 = [f for f in d2["facts"] if f["type"] == "registration"]
    assert [(f["country"], f["registrationNumber"]) for f in regs2] == [("FR", "2150990")]
    d3 = _ask(api_client, "Kamoi Pro est-il homologué au Brésil et au Canada ?")
    regs3 = [f for f in d3["facts"] if f["type"] == "registration"]
    assert [(f["country"], f["registrationNumber"]) for f in regs3] == [("BR", "27520")]
    assert any(f["type"] == "coverage" and f["country"] == "CA" and f["coverage"] == "not_found_in_source" for f in d3["facts"])
    d4 = _ask(api_client, "Quels produits à base de Clonostachys rosea sont autorisés sur vigne ?")
    assert [(f["country"], f["registrationNumber"]) for f in d4["facts"] if f["type"] == "registration"] == [("FR", "2230771")]


def test_expiry_question(api_client):
    d = _ask(api_client, "Quelles autorisations expirent dans les 6 prochains mois ?", "en")
    assert d["intent"] == "expiry"
    regs = [f for f in d["facts"] if f["type"] == "registration"]
    assert [f["registrationNumber"] for f in regs] == ["32404"] and regs[0]["expirationDate"] == "2026-12-31"
    assert any("US-EPA-PPLS and BR-AGROFIT do not publish" in w for w in d["warnings"])


def test_country_portfolio_question(api_client):
    """'Which (Lallemand) products are registered in <country>?' - no product named, the country is the subject."""
    d = _ask(api_client, "Quels produits Lallemand sont homologués au Canada ?")
    assert d["intent"] == "country_portfolio" and d["toolsUsed"] == ["overview"]
    regs = [f for f in d["facts"] if f["type"] == "registration"]
    assert {f["registrationNumber"] for f in regs} == {"29066", "32404", "28820", "30829"}
    assert all(f["country"] == "CA" for f in regs) and len(d["evidence"]) == 4
    assert d["structured"]["headline"].startswith("Canada : 4 enregistrement(s) de titulaire Lallemand/Danstar dans CA-PPID")
    assert len(d["structured"]["items"]) == 4
    assert any("Lallemand" in c and "DANSTAR" in c for c in d["structured"]["caveats"])  # localized caveat about the scope
    d2 = _ask(api_client, "Which products are registered in Brazil?", "en")
    assert d2["intent"] == "country_portfolio"
    assert [(f["country"], f["registrationNumber"]) for f in d2["facts"] if f["type"] == "registration"] == [("BR", "27520")]
    d3 = _ask(api_client, "Quais produtos estão registrados na Alemanha?", "pt")
    assert d3["intent"] == "country_portfolio" and d3["evidence"] == [] and [f for f in d3["facts"] if f["type"] == "registration"] == []
    assert "Alemanha" in d3["structured"]["headline"] and any("Alemanha (DE): nenhuma fonte conectada" in c for c in d3["structured"]["caveats"])
    assert any("no source connected" in w for w in d3["warnings"])  # the API warnings stay English
    d4 = _ask(api_client, "Quels produits contenant Clonostachys rosea sont homologués au Canada ?")
    assert d4["intent"] == "ingredient_search"  # a species question is still an ingredient search


def test_caveats_follow_the_question_language(api_client):
    d = _ask(api_client, "LALSTOP CONTANS WG est-il homologué au Brésil ?")
    assert any("Brésil (BR) : non trouvé dans BR-AGROFIT" in c and "preuve d'absence" in c for c in d["structured"]["caveats"])
    assert any("not found in BR-AGROFIT" in w for w in d["warnings"])  # English in the contract field
    assert any("Brésil (BR) : non trouvé" in w for w in d["warningsLocalized"])
    d_pt = _ask(api_client, "LALSTOP CONTANS WG está registrado no Brasil?", "pt")
    assert any("Brasil (BR): não encontrado em BR-AGROFIT" in c for c in d_pt["structured"]["caveats"])
    d_en = _ask(api_client, "Is LALSTOP CONTANS WG registered in Brazil?", "en")
    assert d_en["warningsLocalized"] == d_en["warnings"]


def test_follow_up_questions_inherit_the_conversation_context(api_client):
    """Chat mode: the answer returns a `context`; sent back with the next question, follow-ups keep product / countries."""
    d1 = _ask(api_client, "LALSTOP G46 WG est-il homologué au Canada ?")
    ctx = d1["context"]
    assert ctx["productIds"] == ["P-LPC-G46"] and ctx["countries"] == ["CA"]
    d2 = api_client.post("/ask", json={"question": "Et en France ?", "language": "fr", "context": ctx}).json()
    assert [(f["country"], f["registrationNumber"]) for f in d2["facts"] if f["type"] == "registration"] == [("FR", "2230771")]
    assert d2["context"]["productIds"] == ["P-LPC-G46"] and d2["context"]["countries"] == ["FR"]
    assert any(w == "Context taken from the conversation: LALSTOP G46 WG." for w in d2["warnings"])
    assert d2["structured"]["caveats"][0] == "Contexte repris de la conversation : LALSTOP G46 WG."
    d3 = api_client.post("/ask", json={"question": "Et ses usages ?", "language": "fr", "context": d2["context"]}).json()
    assert d3["intent"] == "use_comparison" and d3["context"]["countries"] == ["FR"]  # product and country inherited
    assert any(f["type"] == "use" for f in d3["facts"])
    assert any(w == "Context taken from the conversation: LALSTOP G46 WG · FR." for w in d3["warnings"])
    d4 = api_client.post("/ask", json={"question": "Dans quels pays est-il homologué ?", "language": "fr", "context": d3["context"]}).json()
    assert sorted({f["country"] for f in d4["facts"] if f["type"] in ("registration", "coverage")}) == ["BR", "CA", "FR", "US"]  # 'quels pays' = all
    d5 = api_client.post("/ask", json={"question": "Quels sont ses produits sœurs ?", "language": "fr", "context": d4["context"]}).json()
    assert d5["intent"] == "sister_product" and any(f["type"] == "alias" for f in d5["facts"])
    d6 = api_client.post("/ask", json={"question": "Et PRESTOP au Canada ?", "language": "fr", "context": d5["context"]}).json()
    assert "P-PRESTOP" in d6["context"]["productIds"] and not any("Context taken" in w for w in d6["warnings"])  # a named product resets the thread
    d7 = api_client.post("/ask", json={"question": "Which products containing Clonostachys rosea are registered on strawberries?", "language": "en"}).json()
    d8 = api_client.post("/ask", json={"question": "And in Canada?", "language": "en", "context": d7["context"]}).json()
    assert d8["intent"] == "ingredient_search" and d8["context"]["species"] == "Clonostachys rosea"
    regs8 = [f for f in d8["facts"] if f["type"] == "registration"]
    assert regs8 and all(f["country"] == "CA" for f in regs8)
    assert any(w.startswith("Context taken from the conversation: Clonostachys rosea") for w in d8["warnings"]), d8["warnings"]
