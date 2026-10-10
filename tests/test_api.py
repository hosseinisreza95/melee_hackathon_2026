"""API contract + governance tests (SPEC M2, M4, G1, G4, F1, F2): every regulatory row carries evidence,
missing data is flagged not denied, disclaimer always present, review changes are logged."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and "disclaimer" in r.json()


def test_search_by_name_alias_and_active_entity(api_client):
    assert api_client.get("/products", params={"q": "contans"}).json()["items"][0]["productId"] == "P-LPC-CONTANS"
    by_alias = api_client.get("/products", params={"q": "PRESTOP WG"}).json()["items"]
    ids = [p["productId"] for p in by_alias]
    assert ids[0] == "P-PRESTOP-WG" and "P-LPC-G46" in ids  # distinct product first, pilot reachable through its alias
    by_hist = api_client.get("/products", params={"q": "MET52"}).json()["items"]
    assert any(p["productId"] == "P-LPC-M52" for p in by_hist)
    by_ae = api_client.get("/products", params={"q": "Clonostachys rosea"}).json()["items"]
    assert {p["productId"] for p in by_ae} >= {"P-LPC-G46", "P-PRESTOP", "P-PRESTOP-WG", "P-KAMOI-PRO"}
    empty = api_client.get("/products", params={"q": "FOOBARIX 3000"}).json()
    assert empty["items"] == [] and "not proof of no registration" in empty["warnings"][0].lower()


def test_openapi_contract_paths_are_served(api_client):
    contract = yaml.safe_load((ROOT / "schema" / "openapi.yaml").read_text(encoding="utf-8"))
    served = api_client.get("/openapi.json").json()
    for path, ops in contract["paths"].items():
        assert path in served["paths"], path
        for method, op in ops.items():
            assert served["paths"][path][method]["operationId"] == op["operationId"]


def test_compare_every_row_has_evidence_and_coverage_explains_absence(api_client):
    r = api_client.get("/compare", params={"productId": "P-LPC-CONTANS", "countries": "CA,US,FR,BR,DE"})
    assert r.status_code == 200
    d = r.json()
    assert d["disclaimer"] and d["countries"] == ["CA", "US", "FR", "BR", "DE"]
    assert {x["countryCode"] for x in d["registrations"]} == {"CA", "US", "FR"}
    for reg in d["registrations"]:
        ev = reg["evidence"]
        assert ev["sourceId"] and ev["sourceUrl"].startswith("http") and ev["collectedAt"] and ev["validationStatus"]
        for u in reg["uses"]:
            assert u["evidence"]["sourceUrl"].startswith("http") and u["evidence"]["collectedAt"]
    cov = {c["countryCode"]: c for c in d["coverage"]}
    assert cov["BR"]["coverage"] == "not_found_in_source" and cov["BR"]["sourceId"] == "BR-AGROFIT"
    assert cov["DE"]["coverage"] == "source_not_collected"
    assert any("BR" in w and "not proof" in w for w in d["warnings"])
    assert any("dose is not in the structured source" in w for w in d["warnings"])  # CA has no dose
    assert any("two independent lists" in w for w in d["warnings"])  # pairing flagged
    assert any("AI model" in w for w in d["warnings"])  # llm_pdf use flagged


def test_compare_keeps_original_and_normalized_side_by_side(api_client):
    d = api_client.get("/compare", params={"productId": "P-LPC-G46", "countries": "FR"}).json()
    use = next(u for u in d["registrations"][0]["uses"] if u["cropOriginal"] == "Fraisier")
    assert use["cropNormalized"] == "Strawberry" and use["eppoCropCode"] == "FRAAN" and use["eppoCropStatus"] == "to_verify"
    assert use["doseValue"] == 0.25 and use["doseUnitOriginal"] == "kg/ha" and use["phiDays"] == 1
    reg = d["registrations"][0]
    assert reg["statusOriginal"] == "AUTORISE" and reg["statusNormalized"] == "active"


def test_unknown_product_is_404_with_disclaimer_not_a_denial(api_client):
    r = api_client.get("/products/P-DOES-NOT-EXIST/registrations")
    assert r.status_code == 404
    body = r.json()
    assert "not proof of no registration" in body["message"] and body["disclaimer"]


def test_registrations_by_name_and_country_filter(api_client):
    r = api_client.get("/products/LALSTOP CONTANS WG/registrations", params={"country": "BR"}).json()
    assert r["items"] == [] and any("not proof of no registration" in w for w in r["warnings"])
    r2 = api_client.get("/products/P-LPC-CONTANS/registrations", params={"country": "ca"}).json()
    assert len(r2["items"]) == 1 and r2["items"][0]["registrationNumber"] == "29066" and r2["items"][0]["expirationDate"] == "2027-12-31"


def test_aliases_sister_candidates_are_hypotheses(api_client):
    al = api_client.get("/products/P-LPC-G46/aliases").json()
    cand = [a for a in al if a["relationshipType"] == "sister_product_candidate"]
    assert cand and all(a["reviewStatus"] in ("to_verify", "automatically_extracted") for a in cand)
    assert all(a["evidence"] for a in al)
    confirmed = [a for a in al if a["relationshipType"] == "confirmed_sister_product"]
    assert confirmed and confirmed[0]["aliasName"] == "PRESTOP" and "LPC answer" in confirmed[0]["evidence"]


def test_related_products_are_listed_not_merged(api_client):
    d = api_client.get("/compare", params={"productId": "P-LPC-G46", "countries": "CA,US,FR"}).json()
    assert {r["countryCode"] for r in d["registrations"]} == {"FR"}  # LPC: PRESTOP WG (CA/US) is a distinct product
    rel = {r["commercialName"]: r for r in d["relatedProducts"]}
    assert rel["PRESTOP WG"]["relationship"] == "related_product" and {x["countryCode"] for x in rel["PRESTOP WG"]["registrations"]} == {"CA", "US"}
    assert rel["PRESTOP"]["relationship"] == "confirmed_sister_product" and rel["PRESTOP"]["reviewStatus"] == "validated"
    assert rel["PRIMASTOP BIOFUNGICIDE POWDER"]["relationship"] == "sister_product_candidate"
    assert any("related product 'PRESTOP WG'" in w and "distinct product" in w for w in d["warnings"])
    r2 = api_client.get("/products/LALSTOP G46 WG/related", params={"countries": "CA"}).json()
    assert {x["commercialName"] for x in r2["items"] if x["registrations"]} == {"PRESTOP WG", "PRESTOP"}  # both have a CA registration


def test_expiring_and_sources_and_export(api_client):
    exp = api_client.get("/expiring", params={"months": 6}).json()
    assert [x["registrationNumber"] for x in exp["items"]] == ["32404"]  # expires 2026-12-31
    src = api_client.get("/sources").json()["items"]
    assert {s["sourceId"] for s in src} >= {"CA-PPID", "US-EPA-PPLS", "FR-EPHY", "BR-AGROFIT"}
    csv_ = api_client.get("/export.csv", params={"productId": "P-LPC-CONTANS"})
    assert csv_.status_code == 200 and csv_.headers["content-type"].startswith("text/csv")
    lines = csv_.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("product_id,commercial_name,country_code,registration_number,status_original,status_normalized")
    assert len(lines) == 1 + 2 + 2 + 1  # CA 2 uses, US 2 uses, FR 1 use
    xlsx = api_client.get("/export.xlsx", params={"productId": "P-LPC-M52"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_review_changes_status_and_is_logged(api_client):
    before = api_client.get("/products/P-LPC-G46/aliases").json()
    target = next(a for a in before if a["aliasName"] == "PRIMASTOP BIOFUNGICIDE POWDER")
    r = api_client.post("/review", json={"entityType": "alias", "entityId": target["aliasId"], "newStatus": "rejected", "reviewer": "RA tester", "note": "different formulation"})
    assert r.status_code == 200 and r.json()["oldStatus"] == "to_verify"
    after = next(a for a in api_client.get("/products/P-LPC-G46/aliases").json() if a["aliasName"] == "PRIMASTOP BIOFUNGICIDE POWDER")
    assert after["reviewStatus"] == "rejected"
    log = api_client.get("/review/log").json()
    assert log[0]["entityId"] == target["aliasId"] and log[0]["reviewer"] == "RA tester"
    # restore for other tests
    api_client.post("/review", json={"entityType": "alias", "entityId": target["aliasId"], "newStatus": "to_verify", "reviewer": "RA tester"})


def test_active_entity_endpoint_distinguishes_strains(api_client):
    d = api_client.get("/active-entities/Clonostachys rosea/registrations").json()
    strains = {x["activeEntityNormalized"] for x in d["items"]}
    assert "Clonostachys rosea J1446" in strains and "Clonostachys rosea CPQBA 040-11 DRM 07" in strains
    on_tomato = api_client.get("/active-entities/Coniothyrium minitans/registrations", params={"crop": "tomato"}).json()
    assert [x["countryCode"] for x in on_tomato["items"]] == ["CA"]


def test_overview_is_map_ready_and_distinguishes_coverage(api_client):
    d = api_client.get("/overview", params={"scope": "pilots"}).json()
    by = {c["countryCode"]: c for c in d["countries"]}
    assert by["FR"]["coverage"] == "found" and by["FR"]["active"] >= 3 and by["FR"]["registrations"][0]["sourceUrl"].startswith("http")
    assert by["BR"]["coverage"] == "not_found_in_source" and by["BR"]["sourceId"] == "BR-AGROFIT" and by["BR"]["collectedAt"]
    assert by["DE"]["coverage"] == "source_not_collected" and by["DE"]["sourceId"] is None
    assert d["totals"]["sourcesConnected"] == 4 and d["disclaimer"]
    p = api_client.get("/overview", params={"scope": "product", "productId": "PRESTOP"}).json()
    assert {c["countryCode"] for c in p["countries"] if c["coverage"] == "found"} == {"CA", "US"}
    assert api_client.get("/overview", params={"scope": "product", "productId": "NOPE"}).status_code == 404


def test_integration_guide_is_served(api_client):
    r = api_client.get("/guide")
    assert r.status_code == 200 and "Power Automate" in r.text and "/api/compare" in r.text and "<table" in r.text
