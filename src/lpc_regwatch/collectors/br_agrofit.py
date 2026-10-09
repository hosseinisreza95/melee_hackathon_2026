"""Brazil — Ministério da Agricultura e Pecuária open-data portal, AGROFIT dataset.

Source facts (docs/SOURCES.md §4): CKAN portal, Creative Commons Attribution, no account.
The formulated-products CSV (≈ 392 MB) is one row per product × crop × pest with status
SITUACAO (active only), registrant, class and active ingredient (strain + concentration in text).
Resource URLs are resolved through the CKAN API on every run because resource ids can change.
"""
from __future__ import annotations

from typing import Iterable

from .base import BaseCollector, Fetched, SchemaDriftError

CKAN = "https://dados.agricultura.gov.br/api/3/action/package_search"
DATASET = "sistema-de-agrotoxicos-fitossanitarios-agrofit"
ENCODING = "utf-8-sig"
SEP = ";"
EXPECTED = ["NR_REGISTRO", "MARCA_COMERCIAL", "FORMULACAO", "INGREDIENTE_ATIVO", "TITULAR_DE_REGISTRO", "CLASSE",
            "MODO_DE_ACAO", "CULTURA", "PRAGA_NOME_CIENTIFICO", "PRAGA_NOME_COMUM", "EMPRESA_PAIS_TIPO",
            "CLASSE_TOXICOLOGICA", "CLASSE_AMBIENTAL", "ORGANICOS", "SITUACAO"]


class BrAgrofitCollector(BaseCollector):
    source_id = "BR-AGROFIT"
    version = "0.1.0"
    resources = ("Produto Formulado",)  # technical products not needed for the MVP

    def collect(self) -> Iterable[Fetched]:
        meta = self._get(CKAN, params={"q": "agrofit", "rows": 5}).json()
        yield self.save_json(CKAN + "?q=agrofit", meta, "ckan_package_search.json")
        pkgs = [p for p in meta.get("result", {}).get("results", []) if p.get("name") == DATASET]
        if not pkgs:
            raise SchemaDriftError(f"{self.source_id}: dataset {DATASET} not found in CKAN search")
        pkg = pkgs[0]
        self.notes.append(f"dataset modified={pkg.get('metadata_modified')} license={pkg.get('license_title')}")
        for want in self.resources:
            res = [r for r in pkg.get("resources", []) if (r.get("name") or "").strip().lower() == want.lower()]
            if not res:
                raise SchemaDriftError(f"{self.source_id}: resource '{want}' not found; have {[r.get('name') for r in pkg.get('resources', [])]}")
            f = self.download(res[0]["url"], "agrofit_produtos_formulados.csv", "extract_csv")
            self.check_columns(self.read_header(f.local_path, ENCODING, SEP), EXPECTED, want)
            yield f
