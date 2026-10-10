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
    assert "sister_product_candidate, confiance 0.8, statut to_verify" in d["answer"]  # hypothesis shown with its status, not as a fact
    assert any("hypotheses" in w for w in d["warnings"])


def test_T05_official_source_of_each_datum(api_client):
    d = _ask(api_client, "Donne la source officielle de chaque donnée pour LALSTOP CONTANS WG.")
    regs = [f for f in d["facts"] if f["type"] == "registration"]
    assert regs and all(f["sourceId"] in ("CA-PPID", "US-EPA-PPLS", "FR-EPHY") and f["sourceUrl"].startswith("http") and f["collectedAt"] for f in regs)
    assert {e["sourceId"] for e in d["evidence"]} == {"CA-PPID", "US-EPA-PPLS", "FR-EPHY"}
    assert "CA-PPID" in d["answer"] and "2026-10-09" in d["answer"]


def test_adversarial_unknown_product_yields_no_facts(api_client):
    d = _ask(api_client, "Dans quels pays le produit FOOBARIX 3000 est-il homologué ?")
    assert d["facts"] == [] and d["evidence"] == []
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
