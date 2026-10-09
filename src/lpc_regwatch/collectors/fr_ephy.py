"""France — ANSES E-Phy open data on data.gouv.fr.

Source facts (docs/SOURCES.md §3): weekly zip whose URL changes every week, so the collector
asks the data.gouv.fr dataset API for the current UTF-8 CSV resource, downloads it and verifies
the zip members and the columns it depends on (produits, usages_des_produits_autorises,
substance_active). Licence Ouverte.
"""
from __future__ import annotations

import io
import zipfile
from typing import Iterable

from .base import BaseCollector, Fetched, SchemaDriftError

DATASET_SLUG = ("donnees-ouvertes-du-catalogue-e-phy-des-produits-phytopharmaceutiques-matieres-fertilisantes-"
                "et-supports-de-culture-adjuvants-produits-mixtes-et-melanges")
API = f"https://www.data.gouv.fr/api/1/datasets/{DATASET_SLUG}/"
ENCODING = "utf-8-sig"
SEP = ";"

EXPECTED = {
    "produits_utf8.csv": ["type produit", "numero AMM", "nom produit", "seconds noms commerciaux", "titulaire",
                          "type commercial", "gamme usage", "mentions autorisees", "Substances actives", "fonctions",
                          "formulations", "Etat d’autorisation", "Date de retrait du produit", "Date de première autorisation"],
    "usages_des_produits_autorises_utf8.csv": ["numero AMM", "nom produit", "identifiant usage lib court", "identifiant usage",
                                               "date decision", "stade cultural min (BBCH)", "stade cultural max (BBCH)",
                                               "etat usage", "dose retenue", "dose retenue unite", "delai avant recolte jour",
                                               "nombre max d'application", "condition emploi", "ZNT aquatique (en m)"],
    "substance_active_utf8.csv": ["Nom substance active", "Numero CAS", "Etat d’autorisation", "Variant"],
}


class FrEphyCollector(BaseCollector):
    source_id = "FR-EPHY"
    version = "0.1.0"

    def collect(self) -> Iterable[Fetched]:
        meta = self._get(API).json()
        yield self.save_json(API, meta, "datagouv_dataset.json", kind="api_json")
        res = [r for r in meta.get("resources", []) if "csv" in (r.get("title") or "").lower() and "utf8" in (r.get("title") or "").lower()]
        if not res:
            raise SchemaDriftError(f"{self.source_id}: no UTF-8 CSV zip resource in dataset API response")
        r = sorted(res, key=lambda x: x.get("last_modified") or "", reverse=True)[0]
        self.notes.append(f"resource: {r.get('title')} last_modified={r.get('last_modified')} filesize={r.get('filesize')}")
        f = self.download(r["url"], "ephy_csv_utf8.zip", "zip")
        with zipfile.ZipFile(f.local_path) as z:
            names = set(z.namelist())
            for member, cols in EXPECTED.items():
                if member not in names:
                    raise SchemaDriftError(f"{self.source_id}: zip member {member} missing; members={sorted(names)}")
                header = io.TextIOWrapper(z.open(member), encoding=ENCODING, newline="").readline()
                found = [c.strip().strip('"') for c in header.rstrip("\r\n").split(SEP)]
                self.check_columns(found, cols, member)
        yield f
