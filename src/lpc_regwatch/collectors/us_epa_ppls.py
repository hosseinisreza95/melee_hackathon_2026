"""United States — EPA Pesticide Product Label System (PPLS) REST API.

Source facts (docs/SOURCES.md §2): JSON, no key, refreshed every 12 h. Discovery by partial
product name and by active-ingredient name, then one full record per EPA registration number
(status, formulation, active ingredients, alternate/inactive brand names, transfer history,
label PDF list, sites, pests). Label PDFs are fetched for Lallemand products only.

Privacy (docs/SPEC.md S1): the full record contains a named contact person with phone and
e-mail. These fields are replaced by "[redacted]" BEFORE the JSON is written to disk, and the
redaction is recorded in the sidecar notes. Company names are kept (they are regulatory facts).
"""
from __future__ import annotations

import re
from typing import Iterable

from ..pilots import short_name_tokens, species_terms
from .base import BaseCollector, Fetched, SchemaDriftError

BASE = "https://ordspub.epa.gov/ords/pesticides/cswu"
PDF_BASE = "https://www3.epa.gov/pesticides/chem_search/ppls/"
EXPECTED_KEYS = ["eparegno", "productname", "product_status", "product_status_date", "active_ingredients",
                 "pdffiles", "sites", "pests", "altbrandnames", "formulations", "companyinfo"]
REDACT_FIELDS = ("contact_person", "phone", "fax", "email", "street", "po_box", "zip_code")
LALLEMAND = re.compile(r"DANSTAR|LALLEMAND", re.I)


def _items(obj):
    return obj.get("items", obj) if isinstance(obj, dict) else obj


class UsEpaPplsCollector(BaseCollector):
    source_id = "US-EPA-PPLS"
    version = "0.1.0"

    def __init__(self, *a, name_terms: list[str] | None = None, ingredient_terms: list[str] | None = None,
                 fetch_labels: bool = True, **kw):
        super().__init__(*a, **kw)
        self.name_terms = name_terms if name_terms is not None else short_name_tokens()
        self.ingredient_terms = ingredient_terms if ingredient_terms is not None else species_terms()
        self.fetch_labels = fetch_labels

    def collect(self) -> Iterable[Fetched]:
        regnos: dict[str, str] = {}  # eparegno -> how it was found
        for term in self.name_terms:
            url = f"{BASE}/ProductSearch/partialprodsearch/v2/riname/{term}"
            data = self._get(url).json()
            yield self.save_json(url, data, f"search_name_{self._slug(term)}.json")
            for it in _items(data) or []:
                regnos.setdefault(it["eparegno"], f"name:{term}")
        for term in self.ingredient_terms:
            url = f"{BASE}/ProductSearch/searchWithIngName/v1/{term}"
            data = self._get(url).json()
            yield self.save_json(url, data, f"search_ingredient_{self._slug(term)}.json")
            for it in _items(data) or []:
                regnos.setdefault(it["eparegnumber"], f"ingredient:{term}")
        self.notes.append(f"{len(regnos)} registrations discovered: " + ", ".join(sorted(regnos)))

        for regno in sorted(regnos):
            url = f"{BASE}/ppls/{regno}"
            data = self._get(url).json()
            items = _items(data) if isinstance(data, dict) and "items" in data else [data]
            if not items:
                # The API answers {"items": []} for some old/cancelled numbers: that is "no record",
                # not a format change. Keep the empty answer as evidence (source said nothing).
                self.notes.append(f"ppls {regno}: empty record returned by the API (discovered via {regnos[regno]})")
                yield self.save_json(url, data, f"ppls_{regno}.json")
                continue
            rec = items[0]
            missing = [k for k in EXPECTED_KEYS if k not in rec]
            if missing:
                raise SchemaDriftError(f"{self.source_id}/ppls/{regno}: missing keys {missing}")
            self._redact(rec)
            yield self.save_json(url, rec, f"ppls_{regno}.json")
            if self.fetch_labels and rec.get("pdffiles") and self._is_pilot(rec):
                latest = rec["pdffiles"][0]  # list is newest-first in the API (verified 2026-10-09)
                pdf_url = PDF_BASE + latest["pdffile"]
                yield self.download(pdf_url, latest["pdffile"], "label_pdf")

    # ------------------------------------------------------------------
    def _is_pilot(self, rec: dict) -> bool:
        """Label PDFs only for pilot products: Lallemand registrant AND (pilot name or pilot species)."""
        if not any(LALLEMAND.search(c.get("name") or "") for c in rec.get("companyinfo") or []):
            return False
        name = (rec.get("productname") or "").replace("®", "").upper()
        if any(t in name for t in self.name_terms):
            species = " ".join((a.get("active_ing") or "") for a in rec.get("active_ingredients") or []).lower()
            return any(sp.lower() in species for sp in self.ingredient_terms)
        return False

    def _redact(self, rec: dict) -> None:
        n = 0
        for key in ("companyinfo", "companyagentinfo"):
            for c in rec.get(key) or []:
                for f in REDACT_FIELDS:
                    if c.get(f):
                        c[f] = "[redacted]"
                        n += 1
        if n:
            self.notes.append(f"ppls {rec.get('eparegno')}: {n} personal-contact fields redacted before storage")

    @staticmethod
    def _slug(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
