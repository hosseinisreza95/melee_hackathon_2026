"""Offline collector tests using httpx.MockTransport (no network).

They verify the behaviours the challenge grades: provenance sidecars, snapshot registration,
schema-drift detection, and privacy redaction of EPA contact fields.
"""
import json
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.collectors import CaPpidCollector, SchemaDriftError, UsEpaPplsCollector  # noqa: E402
from lpc_regwatch.collectors import ca_ppid  # noqa: E402
from lpc_regwatch.db.models import RawDocument, Snapshot  # noqa: E402
from lpc_regwatch.db.session import init_db  # noqa: E402


@pytest.fixture()
def session():
    eng = init_db("sqlite:///:memory:")
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


CA_PRODUCT_HEADER = ",".join(ca_ppid.EXPECTED["product"])


def test_ca_collector_writes_provenance_and_registers_snapshot(session, tmp_path):
    def handler(req: httpx.Request):
        name = req.url.path.rsplit("/", 1)[-1]
        header = ",".join(ca_ppid.EXPECTED[name])
        body = (header + "\r\n29066,LALSTOP CONTANS WG,x,Full Registration,2027-12-31\r\n").encode("cp1252")
        return httpx.Response(200, content=body, headers={"content-type": "application/vnd.ms-excel;charset=WINDOWS-1252"})

    snap = CaPpidCollector(session, raw_dir=tmp_path, client=_client(handler)).run()
    assert snap.status == "ok"
    docs = session.query(RawDocument).filter_by(snapshot_id=snap.snapshot_id).all()
    assert {d.document_kind for d in docs} == {"extract_csv"} and len(docs) == 4
    for d in docs:
        p = Path(d.local_path)
        assert p.exists() and p.with_name(p.name + ".meta.json").exists()
        meta = json.loads(p.with_name(p.name + ".meta.json").read_text())
        assert meta["sha256"] == d.sha256 and meta["url"] == d.url and meta["collected_at"]


def test_schema_drift_marks_snapshot_failed(session, tmp_path):
    def handler(req: httpx.Request):
        return httpx.Response(200, content=b"Registration number,Something else\r\n1,2\r\n")

    with pytest.raises(SchemaDriftError):
        CaPpidCollector(session, raw_dir=tmp_path, client=_client(handler)).run()
    snap = session.query(Snapshot).one()
    assert snap.status == "failed" and "missing columns" in (snap.notes or "")


def test_epa_collector_redacts_contact_info_and_fetches_label(session, tmp_path):
    record = {
        "eparegno": "64137-34", "productname": "LALSTOP CONTANS WG", "product_status": "Active",
        "product_status_date": "March 16, 2001", "formulations": [], "altbrandnames": [],
        "active_ingredients": [{"active_ing": "Coniothyrium minitans strain CON/M/91-08"}],
        "pdffiles": [{"pdffile": "064137-00034-20230922.pdf", "pdffile_accepted_date": "September 22, 2023"}],
        "sites": [{"site": "LETTUCE"}], "pests": [{"pest": "SCLEROTINIA"}],
        "companyinfo": [{"name": "DANSTAR FERMENT AG / LALLEMAND PLANT CARE", "contact_person": "A Person",
                         "phone": "123", "email": "a@b.c"}],
    }

    def handler(req: httpx.Request):
        path = req.url.path
        if "partialprodsearch" in path:
            return httpx.Response(200, json={"items": [{"eparegno": "64137-34"}]})
        if "searchWithIngName" in path:
            return httpx.Response(200, json={"items": [{"eparegnumber": "64137-34"}]})
        if path.endswith("/ppls/64137-34"):
            return httpx.Response(200, json=record)
        if path.endswith(".pdf"):
            return httpx.Response(200, content=b"%PDF-1.4 fake", headers={"content-type": "application/pdf"})
        return httpx.Response(404)

    c = UsEpaPplsCollector(session, raw_dir=tmp_path, client=_client(handler),
                           name_terms=["CONTANS"], ingredient_terms=["Coniothyrium minitans"])
    snap = c.run()
    docs = session.query(RawDocument).filter_by(snapshot_id=snap.snapshot_id).all()
    kinds = sorted(d.document_kind for d in docs)
    assert kinds == ["api_json", "api_json", "api_json", "label_pdf"]
    saved = json.loads(next(Path(d.local_path) for d in docs if d.local_path.endswith("ppls_64137-34.json")).read_text(encoding="utf-8"))
    assert saved["companyinfo"][0]["contact_person"] == "[redacted]"
    assert saved["companyinfo"][0]["email"] == "[redacted]"
    assert saved["companyinfo"][0]["name"].startswith("DANSTAR")  # company name is a regulatory fact, kept
    assert "redacted" in (snap.notes or "")


def test_search_terms_come_only_from_the_kit_and_have_no_generic_tokens():
    """Regression: exported product_aliases.csv must never feed EPA search terms (STRAIN/TECHNICAL pulled thousands of records)."""
    from lpc_regwatch import pilots

    toks = set(pilots.short_name_tokens())
    assert {"CONTANS", "PRESTOP", "LALSTOP", "LALGUARD", "MET52"} <= toks
    assert not toks & {"STRAIN", "TECHNICAL", "POWDER", "BIOFUNGICIDE", "BIOINSECTICIDE", "BRUNNEUM", "METARHIZIUM", "PRIMASTOP"}
    assert len(pilots.name_variants()) <= 12
