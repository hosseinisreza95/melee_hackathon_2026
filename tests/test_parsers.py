"""Parser tests on tiny fixture files: originals preserved, status normalised, pairing flagged,
aliases derived from official fields, traceability on every row, loader + export round-trip."""
import datetime as dt
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.collectors import ca_ppid as ca_col  # noqa: E402
from lpc_regwatch.db.models import AuthorizedUse, RawDocument, Registration, Snapshot  # noqa: E402
from lpc_regwatch.db.session import init_db  # noqa: E402
from lpc_regwatch.loader import export_csv, load_batch  # noqa: E402
from lpc_regwatch.parsers import BrAgrofitParser, CaPpidParser, FrEphyParser, UsEpaPplsParser  # noqa: E402
from lpc_regwatch.parsers.base import active_normalized, product_id_for, strain_of  # noqa: E402

NOW = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture()
def session():
    eng = init_db("sqlite:///:memory:")
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _snap(session, source_id, files: dict[str, bytes], tmp_path, kind="extract_csv"):
    snap = Snapshot(source_id=source_id, collected_at=NOW, collector_version="t", status="ok")
    session.add(snap)
    session.flush()
    for name, data in files.items():
        p = tmp_path / name
        p.write_bytes(data)
        session.add(RawDocument(snapshot_id=snap.snapshot_id, source_id=source_id, url=f"https://example.org/{name}",
                                local_path=str(p), content_type="x", sha256="0" * 64, bytes=len(data), collected_at=NOW,
                                document_kind=kind))
    session.commit()
    return snap


def test_identity_helpers():
    assert product_id_for("LALSTOP® CONTANS WG") == "P-LPC-CONTANS"
    assert product_id_for("CONTANS WG") == "P-LPC-CONTANS"          # historical name -> same pilot
    assert product_id_for("MET52 OD") == "P-LPC-M52"
    assert product_id_for("PRESTOP") == "P-PRESTOP"                  # sister candidate is NOT merged
    assert product_id_for("PRESTOP (WG)") == product_id_for("PRESTOP WG")
    assert strain_of("CONIOTHYRIUM MINITANS STRAIN CON/M/91-08") == "CON/M/91-08"
    assert strain_of("Clonostachys rosea, cepa CPQBA 040-11 DRM 07 (Produto Microbiológico) (200 g/kg)") == "CPQBA 040-11 DRM 07"
    assert active_normalized("Metarhizium brunneum (formerly known as Metarhizium anisopliae) Strain F52") == "Metarhizium brunneum F52"


def test_ca_parser(session, tmp_path):
    cols = ca_col.EXPECTED["product"] + ["Exclusive period start date"]
    row = {c: "" for c in cols}
    row.update({"Registration number": "29066", "Product name - English": "LALSTOP CONTANS WG", "Product name - French": "LALSTOP CONTANS WG",
                "Registration Status": "Full Registration", "Expiry date": "2027-12-31", "Marketing type": "COMMERCIAL",
                "Date first registered": "2009-03-11", "Active ingredients - English": "CONIOTHYRIUM MINITANS STRAIN CON/M/91-08",
                "Registrant name": "DANSTAR FERMENT AG", "Sites of Use": "LETTUCE;CARROTS", "Pests": "SCLEROTINIA MINOR;SCLEROTINIA SCLEROTIORUM",
                "Current / Historical": "Current"})
    tech = dict(row, **{"Registration number": "29065", "Product name - English": "CONIOTHYRIUM MINITANS TECH", "Marketing type": "TECHNICAL ACTIVE"})
    other = dict(row, **{"Registration number": "1", "Product name - English": "ROUNDUP", "Registrant name": "X", "Active ingredients - English": "GLYPHOSATE"})
    import csv as _csv
    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    [w.writerow(r) for r in (row, tech, other)]
    app_cols = ca_col.EXPECTED["application"]
    abuf = io.StringIO()
    aw = _csv.DictWriter(abuf, fieldnames=app_cols)
    aw.writeheader()
    aw.writerow({c: "" for c in app_cols} | {"Application number": "2007-4323", "Date received": "2007-06-11", "Purpose": "New",
                                            "Product name - English": "CONTANS WG", "Registration number": "29066", "Name of registrant": "PROPHYTA"})
    snap = _snap(session, "CA-PPID", {"ca_product.csv": buf.getvalue().encode("cp1252"), "ca_application.csv": abuf.getvalue().encode("cp1252")}, tmp_path)
    b = CaPpidParser(session).parse(snap)
    assert [r["registration_id"] for r in b.registrations] == ["R-CA-29066"]  # technical + irrelevant skipped
    r = b.registrations[0]
    assert r["status_original"] == "Full Registration" and r["status_normalized"] == "active"
    assert r["expiration_date"] == dt.datetime(2027, 12, 31) and r["product_id"] == "P-LPC-CONTANS"
    assert r["source_record_url"].startswith("https://pr-rp.hc-sc.gc.ca/") and r["collected_at"] == NOW
    assert len(b.uses) == 2 and all(u["pairing"] == "unpaired_lists" and u.get("dose_value") is None for u in b.uses)
    assert b.uses[0]["crop_name_original"] == "LETTUCE" and "SCLEROTINIA MINOR" in b.uses[0]["target_name_original"]
    assert any(a["alias_name"] == "CONTANS WG" and a["relationship_type"] == "historical_name" for a in b.aliases.values())


def test_us_parser_and_loader_export(session, tmp_path):
    rec = {"eparegno": "64137-13", "productname": "PRESTOP (WG)", "product_status": "Active", "product_status_date": "September 8, 2016",
           "registereddate": None, "cancel_flag": "No", "formulations": [{"formulation": "Soluble Concentrate"}],
           "active_ingredients": [{"active_ing": "Clonostachys rosea strain J1446", "active_ing_percent": 93}],
           "companyinfo": [{"name": "DANSTAR FERMENT AG / LALLEMAND PLANT CARE"}], "altbrandnames": [{"altbrandname": "LALSTOP G46 WG"}],
           "inactive_brand_names": [{"inactive_brand_name": "NA"}], "pdffiles": [{"pdffile": "x.pdf"}],
           "sites": [{"site": "POINSETTIA (SOIL TREATMENT)"}], "pests": [{"pest": "BOTRYTIS"}, {"pest": "PYTHIUM"}], "transfer_history": []}
    snap = _snap(session, "US-EPA-PPLS", {"ppls_64137-13.json": json.dumps(rec).encode(), "ppls_64296-10.json": b'{"items": []}'}, tmp_path, kind="api_json")
    b = UsEpaPplsParser(session).parse(snap)
    # LPC (2026-10-10): PRESTOP WG is a distinct product from LALSTOP G46 WG -> its own id, never the pilot id
    assert len(b.registrations) == 1 and b.registrations[0]["product_id"] == "P-PRESTOP-WG"
    pid = b.registrations[0]["product_id"]
    assert b.registrations[0]["status_normalized"] == "active" and b.registrations[0]["approval_date"] is None
    assert b.uses[0]["target_name_original"] == "BOTRYTIS; PYTHIUM" and b.uses[0]["pairing"] == "unpaired_lists"
    aliases = list(b.aliases.values())
    if pid == "P-PRESTOP-WG":
        assert len(aliases) == 1 and aliases[0]["alias_name"] == "LALSTOP G46 WG" and aliases[0]["relationship_type"] == "alternate_name"
    else:  # pilot id: the source wording becomes an official alias, the pilot's own name is not duplicated
        assert {a["alias_name"] for a in aliases} == {"PRESTOP (WG)"} and aliases[0]["relationship_type"] == "alternate_name"

    counts = load_batch(session, b)
    assert (counts["products_new"], counts["registrations"], counts["uses"]) == (1, 1, 1)
    counts2 = load_batch(session, b)  # idempotent re-load
    assert counts2["products_new"] == 0 and session.query(AuthorizedUse).count() == 1
    out = export_csv(session, tmp_path / "out")
    assert out["registrations"] == 1
    txt = (tmp_path / "out" / "registrations.csv").read_text(encoding="utf-8")
    assert txt.splitlines()[0].startswith("registration_id,product_id,country_code,authority_name,registration_number,status_original,status_normalized")
    assert "2026-10-09T12:00:00Z" in txt and ",true," not in txt.splitlines()[1]  # is_synthetic false


def test_fr_parser(session, tmp_path):
    prod_cols = ["type produit", "numero AMM", "nom produit", "seconds noms commerciaux", "titulaire", "type commercial", "gamme usage",
                 "mentions autorisees", "restrictions usage", "restrictions usage libelle", "Substances actives", "fonctions", "formulations",
                 "Etat d’autorisation", "Date de retrait du produit", "Date de première autorisation", "Numéro AMM du produit de référence",
                 "Nom du produit de référence", ""]
    prod = ";".join(prod_cols) + "\n" + ";".join(["PPP", "2110055", "LALGUARD M52 GR", "MITAXION G", "DANSTAR FERMENT AG", "Produit de référence", "Professionnel",
                                                   "", "", "", "Metarhizium anisopliae var. anisopliae strain F52 900000000 UFC/g", "Insecticide", "Granulé",
                                                   "AUTORISE", "", "01/04/2011", "", "", ""]) + "\n"
    use_cols = ["type produit", "numero AMM", "nom produit", "seconds noms commerciaux", "titulaire", "type commercial", "gamme usage", "mentions autorisees",
                "Substances actives", "fonctions", "formulations", "identifiant usage lib court", "identifiant usage", "date decision",
                "stade cultural min (BBCH)", "stade cultural max (BBCH)", "etat usage", "dose retenue", "dose retenue unite", "delai avant recolte jour",
                "delai avant recolte bbch", "nombre max d'application", "date fin distribution", "date fin utilisation", "condition emploi",
                "ZNT aquatique (en m)", "ZNT arthropodes non cibles (en m)", "ZNT plantes non cibles (en m)", "mentions autorisees", ""]
    use = ";".join(use_cols) + "\n" + ";".join(["PPP", "2110055", "LALGUARD M52 GR", "", "", "", "", "", "", "", "",
                                                 "16553201", "Fraisier*Trt Sol*Otiorhynques", "26/01/2023", "00", "89", "Autorisé", "0,5", "kg/ha", "3", "", "2", "", "",
                                                 "Également autorisé sous abri.", "5", "", "", "", ""]) + "\n"
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("produits_utf8.csv", "﻿" + prod)
        z.writestr("usages_des_produits_autorises_utf8.csv", "﻿" + use)
    snap = _snap(session, "FR-EPHY", {"ephy_csv_utf8.zip": zbuf.getvalue()}, tmp_path, kind="zip")
    b = FrEphyParser(session).parse(snap)
    r = b.registrations[0]
    assert r["registration_id"] == "R-FR-2110055" and r["status_normalized"] == "active" and r["approval_date"] == dt.datetime(2011, 4, 1)
    u = b.uses[0]
    assert (u["crop_name_original"], u["application_method"], u["target_name_original"]) == ("Fraisier", "Trt Sol", "Otiorhynques")
    assert u["dose_value"] == 0.5 and u["dose_unit_original"] == "kg/ha" and u["phi_days"] == 3 and u["max_applications"] == 2
    assert u["pairing"] == "source_paired" and "ZNT aquatique (en m)=5" in u["restrictions_original"]
    assert [a["alias_name"] for a in b.aliases.values()] == ["MITAXION G"]


def test_br_parser(session, tmp_path):
    cols = ["NR_REGISTRO", "MARCA_COMERCIAL", "FORMULACAO", "INGREDIENTE_ATIVO", "TITULAR_DE_REGISTRO", "CLASSE", "MODO_DE_ACAO", "CULTURA",
            "PRAGA_NOME_CIENTIFICO", "PRAGA_NOME_COMUM", "EMPRESA_PAIS_TIPO", "CLASSE_TOXICOLOGICA", "CLASSE_AMBIENTAL", "ORGANICOS", "SITUACAO"]
    rows = [["27520", "Kamoi Pro; BioRoof;", "WP", "Clonostachys rosea, cepa CPQBA 040-11 DRM 07 (Produto Microbiológico) (200 g/kg)", "Agrivalle",
             "Fungicida microbiológico", "", "Todas as culturas", "Botrytis cinerea", "Mofo cinzento", "", "", "", "NAO", "TRUE"],
            ["1", "Roundup", "SL", "Glifosato (480 g/L)", "Bayer", "Herbicida", "", "Soja", "Brachiaria", "", "", "", "", "NAO", "TRUE"]]
    import csv as _csv
    buf = io.StringIO()
    w = _csv.writer(buf, delimiter=";", quoting=_csv.QUOTE_MINIMAL, lineterminator="\n")  # the real file quotes names containing ';'
    w.writerow(cols)
    [w.writerow(r) for r in rows]
    snap = _snap(session, "BR-AGROFIT", {"agrofit_produtos_formulados.csv": ("﻿" + buf.getvalue()).encode("utf-8")}, tmp_path)
    b = BrAgrofitParser(session).parse(snap)
    assert len(b.registrations) == 1 and b.registrations[0]["registration_id"] == "R-BR-27520"
    assert b.registrations[0]["status_normalized"] == "active" and b.registrations[0]["approval_date"] is None
    assert b.products["P-KAMOI-PRO"]["strain"] == "CPQBA 040-11 DRM 07"
    assert [a["alias_name"] for a in b.aliases.values()] == ["BioRoof"]
    assert b.uses[0]["crop_name_original"] == "Todas as culturas" and b.uses[0]["target_name_original"] == "Botrytis cinerea"
    load_batch(session, b)
    assert session.get(Registration, "R-BR-27520").holder_original == "Agrivalle"


def test_reparse_keeps_ai_label_rows_and_logs_no_false_change(session, tmp_path):
    """Re-loading the same structured snapshot must neither delete llm_pdf rows nor log a uses_count change."""
    from lpc_regwatch.db.models import AuthorizedUse, ChangeLog, ExtractionMethod

    rec = {"eparegno": "64137-34", "productname": "LALSTOP CONTANS WG", "product_status": "Active", "product_status_date": "x", "registereddate": None,
           "cancel_flag": "No", "formulations": [], "active_ingredients": [{"active_ing": "Coniothyrium minitans strain CON/M/91-08", "active_ing_percent": 5}],
           "companyinfo": [{"name": "DANSTAR FERMENT AG"}], "altbrandnames": [], "inactive_brand_names": [], "pdffiles": [], "sites": [{"site": "LETTUCE"}],
           "pests": [{"pest": "WHITE MOLD"}], "transfer_history": []}
    snap = _snap(session, "US-EPA-PPLS", {"ppls_64137-34.json": json.dumps(rec).encode()}, tmp_path, kind="api_json")
    b = UsEpaPplsParser(session).parse(snap)
    load_batch(session, b)
    session.add(AuthorizedUse(use_id="U-R-US-64137-34-LBL1", registration_id="R-US-64137-34", crop_name_original="Lettuce", dose_value=2.0, dose_unit_original="lb/acre",
                              pairing="llm_paired", source_record_url="https://x.pdf", collected_at=NOW, extraction_method=ExtractionMethod.llm_pdf, confidence=0.9))
    session.commit()
    counts = load_batch(session, UsEpaPplsParser(session).parse(snap))
    assert counts["changes"] == 0
    kinds = {u.extraction_method for u in session.query(AuthorizedUse).filter_by(registration_id="R-US-64137-34")}
    assert kinds == {ExtractionMethod.json_parser, ExtractionMethod.llm_pdf}
    assert session.query(ChangeLog).filter_by(field="uses_count").count() == 0
