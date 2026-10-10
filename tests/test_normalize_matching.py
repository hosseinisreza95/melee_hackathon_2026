"""Step 3 tests: exact-only EPPO mapping, meaning-preserving unit conversion, scoped taxonomy synonyms,
official-equivalence merge, sister candidates only on species+strain, hypotheses never upgraded."""
import datetime as dt
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.db.models import (AliasRelation, AuthorizedUse, ExtractionMethod, Product, ProductAlias, RawDocument,  # noqa: E402
                                    RegStatus, Registration, Snapshot, ValidationStatus)
from lpc_regwatch.db.session import init_db  # noqa: E402
from lpc_regwatch.matching import (apply_normalization, link_official_equivalents, load_curated_relations,  # noqa: E402
                                   load_starter_candidates, propose_sister_candidates)
from lpc_regwatch.normalize import canonical_active_entity, normalize_crop, normalize_dose, normalize_target  # noqa: E402

NOW = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc)


# ----------------------------------------------------------------------------- pure functions
def test_crop_mapping_is_exact_and_flagged_to_verify():
    m = normalize_crop("TOMATOES (SOIL TREATMENT)")
    assert (m.normalized, m.eppo_code, m.status) == ("Tomato", "LYPES", "to_verify")
    assert normalize_crop("Fraisier").eppo_code == "FRAAN"           # French alias from the starter file
    u = normalize_crop("Cucurbitacées à peau comestible")             # group wording: no guess
    assert u.eppo_code is None and u.status == "unmapped" and u.normalized == "Cucurbitacées à peau comestible"
    comp = normalize_crop("Tomate - Aubergine")                        # composite: names joined, no single code
    assert comp.eppo_code is None and comp.status == "list" and "Tomato" in comp.normalized


def test_target_mapping_never_guesses_species_from_genus():
    assert normalize_target("Pourriture grise").eppo_code == "BOTRCI"
    assert normalize_target("Botrytis cinerea").eppo_code == "BOTRCI"
    assert normalize_target("Thrips").eppo_code is None                # genus/group wording -> no species code
    lst = normalize_target("WHITE MOLD (SCLEROTINIA SCLEROTIORUM); NO PEST; SCLEROTINIA SPP.")
    assert lst.eppo_code is None and lst.status == "list" and "Sclerotinia sclerotiorum" in lst.normalized and "No pest" not in lst.normalized


def test_dose_conversion_only_when_exact():
    assert normalize_dose(15, "g/m²") == (150.0, "kg/ha")
    assert normalize_dose(0.5, "kg/ha") == (0.5, "kg/ha")
    assert normalize_dose(1.25, "L/ha") == (1.25, "L/ha")
    assert normalize_dose(130, "g/kg") == (None, None)                 # per kg of seed: not an area dose
    assert normalize_dose(None, "kg/ha") == (None, None)


def test_taxonomy_synonym_is_scoped_to_documented_strain():
    sp, st, norm, note = canonical_active_entity("Metarhizium anisopliae var. anisopliae strain F52 (x) 900000000 UFC/g")
    assert (sp, st, norm) == ("Metarhizium brunneum", "F52", "Metarhizium brunneum F52") and note
    sp2, st2, norm2, note2 = canonical_active_entity("Metarhizium anisopliae, isolado IBCB 425* (Biológico) (1 x10^9 UFC/g )")
    assert sp2 == "Metarhizium anisopliae" and st2 == "IBCB 425" and note2 is None   # Brazilian strain is NOT renamed
    assert canonical_active_entity("Gliocladium catenulatum souche J1446")[2] == "Clonostachys rosea J1446"
    assert canonical_active_entity("CONIOTHYRIUM MINITANS STRAIN CON/M/91-08")[2] == "Coniothyrium minitans CON/M/91-08"


# ----------------------------------------------------------------------------- database behaviour
@pytest.fixture()
def session():
    eng = init_db("sqlite:///:memory:")
    s = sessionmaker(bind=eng)()
    snap = Snapshot(source_id="CA-PPID", collected_at=NOW, collector_version="t", status="ok")
    s.add(snap)
    s.flush()
    s.add(RawDocument(snapshot_id=snap.snapshot_id, source_id="CA-PPID", url="https://x", local_path="x", content_type="x",
                      sha256="0" * 64, bytes=1, collected_at=NOW, document_kind="extract_csv"))
    s.commit()
    yield s
    s.close()


def _reg(rid, pid, cc, number, active, holder="DANSTAR FERMENT AG", snap=1):
    return Registration(registration_id=rid, product_id=pid, country_code=cc, authority_name="A", registration_number=number,
                        status_original="Full Registration", status_normalized=RegStatus.active, holder_original=holder,
                        active_entity_original=active, source_id="CA-PPID", source_record_url="https://example.org/" + number,
                        collected_at=NOW, snapshot_id=snap, extraction_method=ExtractionMethod.csv_parser, evidence_excerpt="e")


def test_official_alias_links_product_as_related_without_merging(session):
    pilot = Product(product_id="P-LPC-G46", commercial_name="LALSTOP G46 WG", active_entity_original="Clonostachys rosea strain J1446")
    other = Product(product_id="P-PRESTOP-WG", commercial_name="PRESTOP WG", active_entity_original="CLONOSTACHYS ROSEA STRAIN J1446")
    session.add_all([pilot, other])
    session.flush()
    session.add(_reg("R-CA-32404", "P-PRESTOP-WG", "CA", "32404", "CLONOSTACHYS ROSEA STRAIN J1446"))
    session.add(ProductAlias(alias_id="A1", product_id="P-PRESTOP-WG", alias_name="LALSTOP G46 WG", country_code="CA",
                             relationship_type=AliasRelation.historical_name, confidence=1.0, evidence="PPID application 2020-1232",
                             review_status=ValidationStatus.automatically_extracted))
    session.commit()
    out = link_official_equivalents(session)
    assert out and session.get(Product, "P-PRESTOP-WG") is not None  # never merged (LPC 2026-10-10)
    assert session.get(Registration, "R-CA-32404").product_id == "P-PRESTOP-WG"
    names = {a.alias_name: a for a in session.get(Product, "P-LPC-G46").aliases}
    assert names["PRESTOP WG"].relationship_type == AliasRelation.related_product and names["PRESTOP WG"].review_status == ValidationStatus.to_verify
    assert "carries the name 'LALSTOP G46 WG'" in names["PRESTOP WG"].evidence
    # LPC's own statement then upgrades the same alias to validated, still as a related product
    assert load_curated_relations(session) >= 3
    names = {a.alias_name: a for a in session.get(Product, "P-LPC-G46").aliases}
    assert names["PRESTOP WG"].review_status == ValidationStatus.validated and names["PRESTOP WG"].relationship_type == AliasRelation.related_product
    assert names["PRESTOP"].relationship_type == AliasRelation.confirmed_sister_product and names["LALFRESH S"].relationship_type == AliasRelation.related_product
    assert len([a for a in session.get(Product, "P-LPC-G46").aliases if a.alias_name == "PRESTOP WG"]) == 1  # no duplicate


def test_sister_candidate_requires_species_and_strain_and_stays_hypothesis(session):
    pilot = Product(product_id="P-LPC-G46", commercial_name="LALSTOP G46 WG", active_entity_original="Clonostachys rosea strain J1446")
    same = Product(product_id="P-X", commercial_name="PRIMASTOP", active_entity_original="Clonostachys rosea strain J1446")
    other_strain = Product(product_id="P-Y", commercial_name="KAMOI PRO", active_entity_original="Clonostachys rosea, cepa CPQBA 040-11")
    session.add_all([pilot, same, other_strain])
    session.flush()
    session.add_all([_reg("R-1", "P-LPC-G46", "FR", "1", "Clonostachys rosea strain J1446"),
                     _reg("R-2", "P-X", "US", "2", "Clonostachys rosea strain J1446", holder="DANSTAR FERMENT AG / LALLEMAND"),
                     _reg("R-3", "P-Y", "BR", "3", "Clonostachys rosea, cepa CPQBA 040-11", holder="Agrivalle")])
    session.commit()
    apply_normalization(session)
    out = propose_sister_candidates(session)
    aliases = {a.alias_name: a for a in session.get(Product, "P-LPC-G46").aliases}
    assert "PRIMASTOP" in aliases and aliases["PRIMASTOP"].relationship_type == AliasRelation.sister_product_candidate
    assert aliases["PRIMASTOP"].review_status == ValidationStatus.to_verify and aliases["PRIMASTOP"].confidence == 0.8
    assert "KAMOI PRO" not in aliases, "same species but different strain must never become a sister candidate"
    assert len(out) == 1


def test_starter_hypotheses_keep_kit_review_status(session):
    for pid, name in [("P-LPC-CONTANS", "LALSTOP CONTANS WG"), ("P-LPC-G46", "LALSTOP G46 WG"), ("P-LPC-M52", "LALGUARD M52 OD")]:
        session.add(Product(product_id=pid, commercial_name=name))
    session.commit()
    n = load_starter_candidates(session)
    assert n >= 5
    g46 = {a.alias_name: a for a in session.get(Product, "P-LPC-G46").aliases}
    assert g46["PRESTOP"].relationship_type == AliasRelation.sister_product_candidate
    assert g46["PRESTOP"].review_status == ValidationStatus.to_verify and g46["PRESTOP"].confidence == 0.85
    assert "LPC starter kit PNM-004" in g46["PRESTOP"].evidence
    m52 = {a.alias_name: a for a in session.get(Product, "P-LPC-M52").aliases}
    assert m52["LALGUARD M52 GR"].relationship_type == AliasRelation.related_formulation and m52["LALGUARD M52 GR"].review_status == ValidationStatus.validated
    assert load_starter_candidates(session) == 0  # idempotent


def test_apply_normalization_fills_normalized_columns_and_keeps_originals(session):
    p = Product(product_id="P-LPC-CONTANS", commercial_name="LALSTOP CONTANS WG")
    session.add(p)
    session.flush()
    session.add(_reg("R-FR-1", "P-LPC-CONTANS", "FR", "1", "Coniothyrium minitans Souche CON/M/91-08 (x) 1000000000000 UFC/kg"))
    session.add(AuthorizedUse(use_id="U1", registration_id="R-FR-1", crop_name_original="Fraisier", target_name_original="Pourriture grise",
                              dose_value=15, dose_unit_original="g/m²", source_record_url="https://x", collected_at=NOW,
                              extraction_method=ExtractionMethod.csv_parser))
    session.commit()
    stats = apply_normalization(session)
    u = session.get(AuthorizedUse, "U1")
    assert (u.crop_name_original, u.crop_name_normalized, u.eppo_crop_code, u.eppo_crop_status) == ("Fraisier", "Strawberry", "FRAAN", "to_verify")
    assert (u.target_name_normalized, u.eppo_target_code) == ("Botrytis cinerea", "BOTRCI")
    assert (u.dose_value, u.dose_unit_original, u.dose_value_normalized, u.dose_unit_normalized) == (15, "g/m²", 150.0, "kg/ha")
    assert session.get(Product, "P-LPC-CONTANS").active_entity_normalized == "Coniothyrium minitans CON/M/91-08"
    assert stats["crop_mapped"] == 1
