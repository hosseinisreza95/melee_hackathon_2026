"""Shared fixture: a small but realistic canonical database (3 pilot products, related products, 4 countries, aliases,
uses) built from scratch in a temporary SQLite file, and a FastAPI test client bound to it.

Values mirror real official records (numbers, statuses, dates as collected on 2026-10-09) and LPC's answers of
2026-10-10 (PRESTOP WG is a distinct related product; PRESTOP a confirmed sister; LALFRESH S a related product),
so the gold tests assert the behaviour the jury will see, but nothing here depends on network access or on the live DB.
"""
import datetime as dt
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.db import session as dbsession  # noqa: E402
from lpc_regwatch.db.models import (AliasRelation, AuthorizedUse, ExtractionMethod, Product, ProductAlias, RawDocument, RegStatus,  # noqa: E402
                                    Registration, Snapshot, ValidationStatus)

T = dt.datetime(2026, 10, 9, 21, 11, tzinfo=dt.timezone.utc)
CA_URL = "https://pr-rp.hc-sc.gc.ca/ls-re/lbl_detail-eng.php?p_disp_regn='{n}'&p_regnum={n}"
US_URL = "https://ordspub.epa.gov/ords/pesticides/cswu/ppls/{n}"
FR_URL = "https://www.data.gouv.fr/fr/datasets/r/ephy-2026-10-08"
BR_URL = "https://dados.agricultura.gov.br/dataset/6c913699/resource/d30b30d7/download/agrofitprodutosformulados.csv"


def _reg(s, rid, pid, cc, n, src, url, status_o, status_n, active, holder, approval=None, expiry=None, snap=1, method=ExtractionMethod.csv_parser):
    r = Registration(registration_id=rid, product_id=pid, country_code=cc, authority_name=f"Authority {cc}", registration_number=n,
                     status_original=status_o, status_normalized=status_n, holder_original=holder, active_entity_original=active,
                     approval_date=approval, expiration_date=expiry, source_id=src, source_record_url=url, collected_at=T, snapshot_id=snap,
                     raw_document_id=snap, extraction_method=method, evidence_excerpt=f"{n} | {status_o} | {active}", confidence=1.0)
    s.add(r)
    return r


def _use(s, uid, rid, crop, target, url, dose=None, unit=None, pairing="source_paired", phi=None, maxapp=None, restr=None, method=ExtractionMethod.csv_parser,
         crop_n=None, eppo=None):
    s.add(AuthorizedUse(use_id=uid, registration_id=rid, crop_name_original=crop, crop_name_normalized=crop_n, eppo_crop_code=eppo,
                        eppo_crop_status="to_verify" if eppo else "unmapped", target_name_original=target, dose_value=dose, dose_unit_original=unit,
                        phi_days=phi, max_applications=maxapp, restrictions_original=restr, pairing=pairing, source_record_url=url, collected_at=T,
                        raw_document_id=1, extraction_method=method, evidence_excerpt=f"{crop} | {target} | {dose} {unit}",
                        confidence=1.0 if method != ExtractionMethod.llm_pdf else 0.8))


def _alias(aid, pid, name, cc, rel, conf, evidence, review, url=None):
    return ProductAlias(alias_id=aid, product_id=pid, alias_name=name, country_code=cc, relationship_type=rel, confidence=conf,
                        evidence=evidence, source_record_url=url, review_status=review)


def build_fixture_db(path: Path) -> str:
    url = f"sqlite:///{path.as_posix()}"
    eng = dbsession.init_db(url)
    s = sessionmaker(bind=eng)()
    for i, src in enumerate(["CA-PPID", "US-EPA-PPLS", "FR-EPHY", "BR-AGROFIT"], 1):
        s.add(Snapshot(snapshot_id=i, source_id=src, collected_at=T, collector_version="t", status="ok"))
        s.flush()
        s.add(RawDocument(raw_document_id=i, snapshot_id=i, source_id=src, url="https://example.org/" + src, local_path="x", content_type="x",
                          sha256=str(i) * 64, bytes=1, collected_at=T, document_kind="extract_csv"))
    s.add_all([
        Product(product_id="P-LPC-CONTANS", commercial_name="LALSTOP CONTANS WG", active_entity_original="CONIOTHYRIUM MINITANS STRAIN CON/M/91-08",
                active_entity_normalized="Coniothyrium minitans CON/M/91-08", strain="CON/M/91-08", formulation_code="WG"),
        Product(product_id="P-LPC-G46", commercial_name="LALSTOP G46 WG", active_entity_original="Clonostachys rosea souche J1446",
                active_entity_normalized="Clonostachys rosea J1446", strain="J1446", formulation_code="WG"),
        Product(product_id="P-LPC-M52", commercial_name="LALGUARD M52 OD", active_entity_original="METARHIZIUM BRUNNEUM STRAIN F52",
                active_entity_normalized="Metarhizium brunneum F52", strain="F52", formulation_code="OD"),
        Product(product_id="P-PRESTOP", commercial_name="PRESTOP", active_entity_original="CLONOSTACHYS ROSEA STRAIN J1446",
                active_entity_normalized="Clonostachys rosea J1446", strain="J1446"),
        Product(product_id="P-PRESTOP-WG", commercial_name="PRESTOP WG", active_entity_original="CLONOSTACHYS ROSEA STRAIN J1446",
                active_entity_normalized="Clonostachys rosea J1446", strain="J1446", formulation_code="WG"),
        Product(product_id="P-PRIMASTOP-BIOFUNGICIDE-POWDER", commercial_name="PRIMASTOP BIOFUNGICIDE POWDER", active_entity_original="Clonostachys rosea strain J1446 (32%)",
                active_entity_normalized="Clonostachys rosea J1446", strain="J1446"),
        Product(product_id="P-KAMOI-PRO", commercial_name="Kamoi Pro", active_entity_original="Clonostachys rosea, cepa CPQBA 040-11 DRM 07 (200 g/kg)",
                active_entity_normalized="Clonostachys rosea CPQBA 040-11 DRM 07", strain="CPQBA 040-11 DRM 07"),
    ])
    s.flush()
    # CONTANS: CA + US + FR, nothing in BR
    _reg(s, "R-CA-29066", "P-LPC-CONTANS", "CA", "29066", "CA-PPID", CA_URL.format(n=29066), "Full Registration", RegStatus.active,
         "CONIOTHYRIUM MINITANS STRAIN CON/M/91-08", "DANSTAR FERMENT AG", dt.datetime(2009, 3, 11), dt.datetime(2027, 12, 31), 1)
    _use(s, "U-R-CA-29066-1", "R-CA-29066", "LETTUCE", "SCLEROTINIA MINOR; SCLEROTINIA SCLEROTIORUM", CA_URL.format(n=29066), pairing="unpaired_lists", crop_n="Lettuce", eppo="LACSA")
    _use(s, "U-R-CA-29066-2", "R-CA-29066", "TOMATO", "SCLEROTINIA MINOR; SCLEROTINIA SCLEROTIORUM", CA_URL.format(n=29066), pairing="unpaired_lists", crop_n="Tomato", eppo="LYPES")
    _reg(s, "R-US-64137-34", "P-LPC-CONTANS", "US", "64137-34", "US-EPA-PPLS", US_URL.format(n="64137-34"), "Active", RegStatus.active,
         "Coniothyrium minitans strain CON/M/91-08 (5%)", "DANSTAR FERMENT AG / LALLEMAND PLANT CARE", None, None, 2, ExtractionMethod.json_parser)
    _use(s, "U-R-US-64137-34-1", "R-US-64137-34", "LETTUCE (SOIL TREATMENT)", "WHITE MOLD (SCLEROTINIA SCLEROTIORUM); SCLEROTINIA SPP.", US_URL.format(n="64137-34"),
         pairing="unpaired_lists", method=ExtractionMethod.json_parser, crop_n="Lettuce", eppo="LACSA")
    _use(s, "U-R-US-64137-34-L1", "R-US-64137-34", "Lettuce", "Sclerotinia minor", "https://www3.epa.gov/pesticides/chem_search/ppls/064137-00034-20230922.pdf",
         dose=2.0, unit="lb/acre", pairing="llm_paired", method=ExtractionMethod.llm_pdf, crop_n="Lettuce", eppo="LACSA")
    _reg(s, "R-FR-9900189", "P-LPC-CONTANS", "FR", "9900189", "FR-EPHY", FR_URL, "AUTORISE", RegStatus.active,
         "Coniothyrium minitans Souche CON/M/91-08 1000000000000 UFC/kg", "DANSTAR FERMENT AG", dt.datetime(2001, 4, 6), None, 3)
    _use(s, "U-R-FR-9900189-1", "R-FR-9900189", "Traitements généraux", "Champignons (autres que pythiacées)", FR_URL, dose=4.0, unit="kg/ha", maxapp=1,
         restr="Également autorisé sous abri. Efficacité montrée sur Sclerotinia sclerotiorum.", crop_n="All crops")
    # G46: FR only; PRESTOP WG (CA + US) is a distinct related product; PRESTOP a confirmed sister; PRIMASTOP a data hypothesis
    _reg(s, "R-FR-2230771", "P-LPC-G46", "FR", "2230771", "FR-EPHY", FR_URL, "AUTORISE", RegStatus.active, "Clonostachys rosea souche J1446 1000000000 UFC/g",
         "DANSTAR FERMENT AG", dt.datetime(2023, 1, 26), None, 3)
    _use(s, "U-R-FR-2230771-1", "R-FR-2230771", "Fraisier", "Pourriture grise et sclérotinioses", FR_URL, dose=0.25, unit="kg/ha", phi=1, maxapp=4, crop_n="Strawberry", eppo="FRAAN")
    _use(s, "U-R-FR-2230771-2", "R-FR-2230771", "Vigne", "Pourriture grise", FR_URL, dose=0.5, unit="kg/ha", phi=1, maxapp=4, crop_n="Grapevine", eppo="VITVI")
    _reg(s, "R-CA-32404", "P-PRESTOP-WG", "CA", "32404", "CA-PPID", CA_URL.format(n=32404), "Full Registration", RegStatus.active,
         "CLONOSTACHYS ROSEA STRAIN J1446", "DANSTAR FERMENT AG", dt.datetime(2015, 9, 1), dt.datetime(2026, 12, 31), 1)
    _use(s, "U-R-CA-32404-1", "R-CA-32404", "STRAWBERRY", "BOTRYTIS CINEREA", CA_URL.format(n=32404), pairing="unpaired_lists", crop_n="Strawberry", eppo="FRAAN")
    _reg(s, "R-US-64137-13", "P-PRESTOP-WG", "US", "64137-13", "US-EPA-PPLS", US_URL.format(n="64137-13"), "Active", RegStatus.active,
         "Clonostachys rosea strain J1446 (93%)", "DANSTAR FERMENT AG / LALLEMAND PLANT CARE", None, None, 2, ExtractionMethod.json_parser)
    _reg(s, "R-CA-28820", "P-PRESTOP", "CA", "28820", "CA-PPID", CA_URL.format(n=28820), "Full Registration", RegStatus.active,
         "CLONOSTACHYS ROSEA STRAIN J1446", "DANSTAR FERMENT AG", dt.datetime(2008, 1, 1), dt.datetime(2028, 12, 31), 1)
    _reg(s, "R-US-64137-11", "P-PRESTOP", "US", "64137-11", "US-EPA-PPLS", US_URL.format(n="64137-11"), "Inactive", RegStatus.withdrawn,
         "Clonostachys rosea strain J1446 (32%)", "DANSTAR FERMENT AG / LALLEMAND PLANT CARE", None, None, 2, ExtractionMethod.json_parser)
    _reg(s, "R-US-64137-8", "P-PRIMASTOP-BIOFUNGICIDE-POWDER", "US", "64137-8", "US-EPA-PPLS", US_URL.format(n="64137-8"), "Inactive", RegStatus.withdrawn,
         "Clonostachys rosea strain J1446 (32%)", "DANSTAR FERMENT AG / LALLEMAND PLANT CARE", None, None, 2, ExtractionMethod.json_parser)
    _reg(s, "R-BR-27520", "P-KAMOI-PRO", "BR", "27520", "BR-AGROFIT", BR_URL, "TRUE", RegStatus.active,
         "Clonostachys rosea, cepa CPQBA 040-11 DRM 07 (Produto Microbiológico) (200 g/kg)", "Agrivalle Brasil", None, None, 4)
    _use(s, "U-R-BR-27520-1", "R-BR-27520", "Todas as culturas", "Botrytis cinerea", BR_URL, crop_n="All crops")
    # M52: CA + FR + US
    _reg(s, "R-CA-30829", "P-LPC-M52", "CA", "30829", "CA-PPID", CA_URL.format(n=30829), "Full Registration", RegStatus.active,
         "METARHIZIUM BRUNNEUM STRAIN F52", "DANSTAR FERMENT AG", dt.datetime(2011, 12, 23), dt.datetime(2031, 12, 31), 1)
    _reg(s, "R-FR-2150990", "P-LPC-M52", "FR", "2150990", "FR-EPHY", FR_URL, "AUTORISE", RegStatus.active,
         "Metarhizium anisopliae var. anisopliae strain F52 2000000000000 UFC/L", "DANSTAR FERMENT AG", dt.datetime(2016, 5, 1), None, 3)
    _use(s, "U-R-FR-2150990-1", "R-FR-2150990", "Fraisier", "Thrips", FR_URL, dose=1.25, unit="L/ha", phi=3, maxapp=10, crop_n="Strawberry", eppo="FRAAN")
    _reg(s, "R-US-64137-33", "P-LPC-M52", "US", "64137-33", "US-EPA-PPLS", US_URL.format(n="64137-33"), "Active", RegStatus.active,
         "Metarhizium brunneum (formerly known as Metarhizium anisopliae) Strain F52 (11%)", "DANSTAR FERMENT AG / LALLEMAND PLANT CARE", None, None, 2, ExtractionMethod.json_parser)
    s.add_all([
        _alias("A-G46-PRESTOP-WG-CA", "P-LPC-G46", "PRESTOP WG", "CA", AliasRelation.related_product, 1.0,
               "LPC answer (2026-10-10): PRESTOP WG (CA 32404) is not the same product as LALSTOP G46 WG; related product. Its registration carries 'LALSTOP G46 WG' as alternate name.",
               ValidationStatus.validated, CA_URL.format(n=32404)),
        _alias("A-G46-PRESTOP-LPC", "P-LPC-G46", "PRESTOP", "FR", AliasRelation.confirmed_sister_product, 1.0,
               "LPC answer (2026-10-10): sister product (AMM 2120177), same strain, different formulation and content; kit PNM-004", ValidationStatus.validated),
        _alias("A-G46-LALFRESH-LPC", "P-LPC-G46", "LALFRESH S", "FR", AliasRelation.related_product, 1.0,
               "LPC answer (2026-10-10): not a second brand; distinct AMM 2230264, post-harvest positioning", ValidationStatus.validated),
        _alias("A-G46-PRIMASTOP-US", "P-LPC-G46", "PRIMASTOP BIOFUNGICIDE POWDER", "US", AliasRelation.sister_product_candidate, 0.8,
               "Same active entity 'Clonostachys rosea J1446' (species + strain) in US [US 64137-8]; different commercial name and registration -> hypothesis",
               ValidationStatus.to_verify, US_URL.format(n="64137-8")),
        _alias("A-PRESTOPWG-G46-US", "P-PRESTOP-WG", "LALSTOP G46 WG", "US", AliasRelation.alternate_name, 1.0, "PPLS altbrandnames",
               ValidationStatus.automatically_extracted, US_URL.format(n="64137-13")),
        _alias("A-CONTANS-HIST", "P-LPC-CONTANS", "CONTANS WG", "CA", AliasRelation.historical_name, 1.0, "PPID application 2007-4323 (registrant PROPHYTA)",
               ValidationStatus.automatically_extracted, CA_URL.format(n=29066)),
        _alias("A-M52-MET52", "P-LPC-M52", "MET52 EC", "US", AliasRelation.historical_name, 1.0, "PPLS inactive_brand_names",
               ValidationStatus.automatically_extracted, US_URL.format(n="64137-33")),
    ])
    s.commit()
    s.close()
    return url


@pytest.fixture(scope="session")
def fixture_db_url(tmp_path_factory) -> str:
    return build_fixture_db(tmp_path_factory.mktemp("db") / "fixture.sqlite")


@pytest.fixture()
def api_client(fixture_db_url, monkeypatch):
    """TestClient whose DB dependency points at the fixture database (never the developer's real DB)."""
    from fastapi.testclient import TestClient

    import lpc_regwatch.api.app as appmod
    import lpc_regwatch.api.ask as askmod
    from lpc_regwatch.config import Settings

    eng = dbsession.get_engine(fixture_db_url)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(appmod, "get_session", lambda: Session())
    monkeypatch.setattr(askmod, "settings", Settings(ai_api_key=""))  # deterministic path in tests (frozen dataclass -> replace)
    with TestClient(appmod.app) as c:
        yield c
