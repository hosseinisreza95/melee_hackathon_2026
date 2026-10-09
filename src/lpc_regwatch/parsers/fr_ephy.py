"""France E-Phy parser: produits + usages_des_produits_autorises (inside the weekly zip).

What the source asserts: product status AUTORISE/RETIRE with first-authorisation and withdrawal
dates, holder, active substances with content, formulation, second commercial names, and a full
use table: crop * treatment * target ('identifiant usage lib court'), dose + unit, BBCH stages,
pre-harvest interval, max applications, conditions, buffer zones (ZNT). This is the only MVP
source with structured doses -> pairing='source_paired'.
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd

from .base import BaseParser, Batch, excerpt, is_relevant, parse_date, to_float, to_int

ENCODING = "utf-8-sig"


def _col(df: pd.DataFrame, startswith: str) -> str:
    for c in df.columns:
        if c.strip().lower().startswith(startswith.lower()):
            return c
    raise KeyError(startswith)


class FrEphyParser(BaseParser):
    source_id = "FR-EPHY"
    country = "FR"
    authority = "ANSES (Agence nationale de sécurité sanitaire) – catalogue E-Phy"

    def parse(self, snap=None) -> Batch:
        snap = snap or self.latest_snapshot()
        b = self.new_batch(snap)
        doc = self.docs(snap.snapshot_id, kind="zip")[0]
        with zipfile.ZipFile(doc.local_path) as z:
            prod = pd.read_csv(io.BytesIO(z.read("produits_utf8.csv")), sep=";", dtype=str, encoding=ENCODING, low_memory=False).fillna("")
            uses = pd.read_csv(io.BytesIO(z.read("usages_des_produits_autorises_utf8.csv")), sep=";", dtype=str, encoding=ENCODING, low_memory=False).fillna("")
        prod.columns = [c.strip() for c in prod.columns]
        uses.columns = [c.strip() for c in uses.columns]
        c_etat, c_retrait, c_first = _col(prod, "Etat d"), _col(prod, "Date de retrait"), _col(prod, "Date de premi")
        c_amm_u = _col(uses, "numero AMM")

        prod = prod[prod["type produit"].str.strip() == "PPP"]
        rel = prod[prod.apply(lambda r: is_relevant(r["nom produit"], r["titulaire"], r["Substances actives"]), axis=1)]
        b.notes.append(f"{len(rel)} relevant PPP products of {len(prod)}")
        url = doc.url  # the exact dataset file we fetched; AMM number identifies the record inside it

        for _, r in rel.iterrows():
            amm = r["numero AMM"].strip()
            pid = b.add_product(r["nom produit"], r["Substances actives"])
            ev = excerpt(r.to_dict(), ["numero AMM", "nom produit", "seconds noms commerciaux", "titulaire", "type commercial",
                                       "Substances actives", "fonctions", "formulations", c_etat, c_first, c_retrait, "gamme usage"])
            rid = b.add_registration(f"R-FR-{amm}", pid, self.country, self.authority, amm, r[c_etat], url, doc.raw_document_id,
                                     "csv_parser", ev + f" | human_lookup=https://ephy.anses.fr (AMM {amm})",
                                     approval_date=parse_date(r[c_first]), expiration_date=parse_date(r[c_retrait]),
                                     holder_original=r["titulaire"] or None, formulation_original=r["formulations"] or None,
                                     active_entity_original=r["Substances actives"] or None)
            for name in [n.strip() for n in r["seconds noms commerciaux"].replace(";", "|").split("|") if n.strip()]:
                b.add_alias(pid, name, "alternate_name", "E-Phy 'seconds noms commerciaux' (same AMM)", url, "FR")

            u = uses[uses[c_amm_u].str.strip() == amm]
            for i, (_, x) in enumerate(u.iterrows(), 1):
                # Verified on the 2026-10-08 file: despite the header names, 'identifiant usage lib court'
                # holds the numeric use code (e.g. 11012217) and 'identifiant usage' holds the text
                # 'Culture*Traitement*Cible'. We key on the code and parse the text.
                use_code = x["identifiant usage lib court"].strip()
                parts = [p.strip() for p in x["identifiant usage"].split("*")]
                crop = parts[0] if parts else None
                method = parts[1] if len(parts) > 1 else None
                target = "*".join(parts[2:]) if len(parts) > 2 else None
                znt = "; ".join(f"{k}={x[k]}" for k in ("ZNT aquatique (en m)", "ZNT arthropodes non cibles (en m)", "ZNT plantes non cibles (en m)") if k in x and x[k])
                restrictions = " | ".join(s for s in (x.get("condition emploi", ""), znt, x.get("mentions autorisees", "")) if s) or None
                b.add_use(f"U-{rid}-{use_code}-{i}", rid, url, doc.raw_document_id, "csv_parser",
                          excerpt(x.to_dict(), ["identifiant usage lib court", "identifiant usage", "date decision", "etat usage",
                                                "dose retenue", "dose retenue unite", "delai avant recolte jour",
                                                "nombre max d'application", "stade cultural min (BBCH)", "stade cultural max (BBCH)",
                                                "condition emploi"]),
                          crop_name_original=crop, target_name_original=target, application_method=method,
                          dose_value=to_float(x["dose retenue"]), dose_unit_original=x["dose retenue unite"] or None,
                          max_applications=to_int(x["nombre max d'application"]), phi_days=to_float(x["delai avant recolte jour"]),
                          growth_stage_min=x["stade cultural min (BBCH)"] or None, growth_stage_max=x["stade cultural max (BBCH)"] or None,
                          restrictions_original=restrictions, use_status_original=x["etat usage"] or None)
            if u.empty:
                b.notes.append(f"AMM {amm}: no rows in usages_des_produits_autorises (withdrawn products have none)")
        return b
