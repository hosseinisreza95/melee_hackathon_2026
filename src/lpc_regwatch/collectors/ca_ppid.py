"""Canada — Health Canada Pesticide Product Information Database (PPID) open-data extracts.

Source facts (docs/SOURCES.md §1): CSV extracts under one base URL, no key, daily refresh,
Open Government Licence – Canada, encoding Windows-1252. We fetch English extracts for
product (status, expiry, active ingredient, registrant, sites, pests), ingredient, application
(history of names/owners) and the label index. Dose is not in these files (label PDF only).
"""
from __future__ import annotations

from typing import Iterable

from .base import BaseCollector, Fetched

BASE = "https://pest-control.canada.ca/pesticide-registry-api/api/extract/"
ENCODING = "cp1252"

EXPECTED = {
    "product": ["Registration number", "Product name - English", "Product name - French", "Registration Status",
                "Expiry date", "Marketing type", "Date first registered", "Active ingredients - English",
                "Active ingredients - French", "Product Type", "Registrant name", "Use Site Category",
                "Sites of Use", "Pests", "Current / Historical"],
    "ingredient": ["Active ingredient name - English", "Active ingredient name - French", "Reevaluation status", "CAS number"],
    "application": ["Application number", "Date received", "Outcome", "Active ingredients - English", "Purpose",
                    "Product name - English", "Registration number", "Name of registrant", "Registration status",
                    "Product type", "Marketing type", "Current / Historical"],
    "label": ["Registration number", "Registrant name", "Product name", "Registration Status"],
}


class CaPpidCollector(BaseCollector):
    source_id = "CA-PPID"
    version = "0.1.0"
    extracts = ("product", "ingredient", "application", "label")

    def collect(self) -> Iterable[Fetched]:
        for name in self.extracts:
            f = self.download(BASE + name, f"ca_{name}.csv", "extract_csv")
            header = self.read_header(f.local_path, ENCODING, ",")
            self.check_columns(header, EXPECTED[name], name)
            yield f
