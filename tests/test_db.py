"""Schema smoke tests: tables exist, traceability columns are mandatory, sources seeded."""
import datetime as dt
import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.db.models import (  # noqa: E402
    ExtractionMethod,
    Product,
    Registration,
    Snapshot,
    Source,
)
from lpc_regwatch.db.session import get_session, init_db  # noqa: E402

URL = "sqlite:///:memory:"


@pytest.fixture()
def session():
    eng = init_db(URL)
    from sqlalchemy.orm import sessionmaker

    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_all_tables_created(session):
    names = set(inspect(session.get_bind()).get_table_names())
    assert {"sources", "snapshots", "raw_documents", "products", "product_aliases",
            "registrations", "uses", "change_log", "review_log"} <= names


def test_sources_seeded_from_registry(session):
    ids = {s.source_id for s in session.query(Source).all()}
    assert {"CA-PPID", "US-EPA-PPLS", "FR-EPHY"} <= ids


def test_registration_requires_traceability(session):
    """G2: a regulatory row without source/url/date must be rejected by the schema."""
    session.add(Product(product_id="P-T", commercial_name="TEST"))
    session.add(Snapshot(snapshot_id=1, source_id="CA-PPID", collector_version="t"))
    session.flush()
    bad = Registration(registration_id="R-T", product_id="P-T", country_code="CA",
                       authority_name="PMRA", extraction_method=ExtractionMethod.csv_parser,
                       source_id="CA-PPID", snapshot_id=1,
                       source_record_url=None, collected_at=None)  # missing evidence
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_registration_with_traceability_ok(session):
    session.add(Product(product_id="P-T", commercial_name="TEST"))
    session.add(Snapshot(snapshot_id=1, source_id="CA-PPID", collector_version="t"))
    session.flush()
    session.add(Registration(registration_id="R-T", product_id="P-T", country_code="CA",
                             authority_name="PMRA", extraction_method=ExtractionMethod.csv_parser,
                             source_id="CA-PPID", snapshot_id=1,
                             source_record_url="https://example.org/r", collected_at=dt.datetime.now(dt.timezone.utc)))
    session.flush()
    r = session.get(Registration, "R-T")
    assert r.validation_status.value == "automatically_extracted"
    assert r.status_normalized.value == "unknown"


def test_string_columns_fit_observed_values():
    """PostgreSQL enforces VARCHAR lengths (SQLite does not): the longest ids/names seen in the sources must fit."""
    from lpc_regwatch.db.models import AuthorizedUse, Product, ProductAlias, Registration

    assert Product.__table__.c.product_id.type.length >= 160
    assert ProductAlias.__table__.c.alias_id.type.length >= 400 and ProductAlias.__table__.c.alias_name.type.length >= 400
    assert AuthorizedUse.__table__.c.use_id.type.length >= 160 and Registration.__table__.c.holder_original.type.length >= 400
    longest = "A-P-METARHIZIUM-BRUNNEUM-STRAIN-F52-TECHNICAL-MET52-TECHNICAL-US"
    assert len(longest) <= ProductAlias.__table__.c.alias_id.type.length
