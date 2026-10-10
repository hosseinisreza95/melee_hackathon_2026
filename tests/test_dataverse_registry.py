"""Dataverse target structure (schema/dataverse_tables.xlsx) and LPC internal-registry reconciliation, on the fixture DB."""
import io
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.dataverse import build_tables, load_workbook_model, validate_against_workbook  # noqa: E402
from lpc_regwatch.db import session as dbsession  # noqa: E402
from lpc_regwatch.registry import normalize_registry_rows, read_registry_file, reconcile, sample_rows  # noqa: E402


@pytest.fixture()
def session(fixture_db_url):
    s = sessionmaker(bind=dbsession.get_engine(fixture_db_url), expire_on_commit=False)()
    yield s
    s.close()


def test_export_matches_workbook_columns_requirements_and_choices(session):
    tables = build_tables(session)
    model = load_workbook_model()
    assert set(model["columns"]) <= set(tables)
    for table, cols in model["columns"].items():
        if tables[table]:
            assert [c["name"] for c in cols] == [k for k in tables[table][0] if not k.endswith("_ext")], table  # target columns first, in order
    rep = validate_against_workbook(tables)
    assert rep["ok"], rep["errors"]
    reg = tables["lpc_registration"][0]
    for k in ("lpc_sourceid", "lpc_sourcerecordurl", "lpc_collectedat", "lpc_validationstatus", "lpc_issynthetic"):
        assert reg[k] != ""  # traceability never dropped
    names = {r["lpc_namevariant"]: r for r in tables["lpc_productname"] if r["lpc_productid"] == "P-LPC-G46"}
    assert names["PRESTOP"]["lpc_relationshiptype"] == "confirmed_sister_product" and names["PRESTOP"]["lpc_reviewstatus"] == "validated"
    assert names["PRESTOP WG"]["lpc_relationshiptype"] == "related_formulation" and names["PRESTOP WG"]["lpc_relationshipdetail_ext"] == "related_product"
    owners = {r["lpc_productcode"]: r["lpc_owner"] for r in tables["lpc_product"]}
    assert owners["P-LPC-CONTANS"] == "lpc" and owners["P-KAMOI-PRO"] == "competitor"


def test_dataverse_endpoints(api_client):
    z = api_client.get("/export/dataverse.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert {"lpc_product.csv", "lpc_registration.csv", "lpc_authorizeduse.csv", "lpc_productname.csv", "lpc_source.csv", "lpc_eppocode.csv"} <= set(names)
    t = api_client.get("/export/dataverse/lpc_registration", params={"limit": 5}).json()
    assert t["total"] >= 10 and t["items"][0]["lpc_registrationcode"].startswith("R-")
    assert api_client.get("/export/dataverse/nope").status_code == 404
    assert api_client.get("/export/dataverse-validation").json()["ok"] is True


def test_registry_normalisation_keeps_originals_and_flags_conventions():
    rows = normalize_registry_rows(sample_rows())
    by = {(r["title"], r["country_original"]): r for r in rows}
    us = by[("LALSTOP CONTANS WG", "United States")]
    assert us["country_code"] == "US" and us["expiration_date"] is None and "no_expiry_convention" in us["flags"]
    assert us["expiration_date_original"] == "12/31/2999" and us["status_normalized"] == "active" and us["status_original"] == "Registered"
    assert us["formulation_code"] == "WG" and us["formulation_original"].startswith("WG - ")
    assert us["active_entity_normalized"] == "Coniothyrium minitans CON/M/91-08" and us["us_states"] == ["CA", "OR", "WA", "ID", "AZ", "FL"]
    br = by[("LALGUARD M52 OD", "Brazil")]
    assert br["registration_number"] is None and "no_registration_number" in br["flags"] and br["status_normalized"] == "pending"
    mx = by[("LALSTOP K61 WS", "Mexico")]
    assert "product_unassigned" in mx["flags"] and "sold_without_registration" in mx["flags"] and "not_a_ppp" in mx["flags"]
    assert mx["commercial_status"] == "In market" and mx["status_normalized"] == "unknown"
    assert all(r["is_synthetic"] for r in rows)


def test_registry_reconciliation_against_official_sources(session):
    rep = reconcile(session, normalize_registry_rows(sample_rows()))
    rows = {(r["title"], r["country_original"]): r for r in rep["rows"]}
    ca = rows[("LALSTOP CONTANS WG", "Canada")]
    assert ca["match"] == "registration_number" and ca["official"]["registrationNumber"] == "29066"
    verdict = {c["field"]: c["verdict"] for c in ca["comparison"]}
    assert verdict["status"] == "agree" and verdict["expiration_date"] == "agree" and verdict["active_entity"] == "agree"
    pw = rows[("PRESTOP WG", "Canada")]  # registry links it to G46; official source: distinct product PRESTOP WG
    assert pw["match"] == "registration_number" and pw["official"]["productName"] == "PRESTOP WG"
    assert any(c["field"] == "product_identity" and c["verdict"] == "discrepancy" for c in pw["comparison"])
    br = rows[("LALGUARD M52 OD", "Brazil")]
    assert br["match"] == "not_found_in_source" and "not proof" in br["comparison"][0]["note"]
    de = rows[("LALSTOP CONTANS WG", "Germany")]
    assert de["match"] == "source_not_collected"
    mx = rows[("LALSTOP K61 WS", "Mexico")]
    assert mx["match"] == "source_not_collected"
    us_m52 = rows[("MET52 EC", "United States")]  # historical name resolves to the pilot through its alias, number confirms
    assert us_m52["match"] == "registration_number" and us_m52["official"]["productId"] == "P-LPC-M52"
    assert rep["counts"]["discrepancies"] >= 1 and all(r["evidence"] for r in rep["rows"] if r["official"])


def test_registry_upload_endpoint(api_client):
    csv_bytes = (Path(__file__).resolve().parents[1] / "data" / "synthetic" / "lpc_internal_registry_sample.csv").read_bytes()
    r = api_client.post("/registry/reconcile", files={"file": ("registre.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200 and r.json()["total"] == 11 and r.json()["disclaimer"]
    bad = api_client.post("/registry/reconcile", files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")})
    assert bad.status_code == 422
    xlsx_rows = read_registry_file(csv_bytes, "registre.csv")
    assert xlsx_rows[0]["Country"] == "Canada"
