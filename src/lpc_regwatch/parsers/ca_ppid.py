"""Canada PPID parser: product extract -> registrations + uses; application extract -> historical names.

What the source asserts and what we therefore store:
- status, expiry, first-registration date, registrant, active ingredient: structured -> registration row;
- 'Sites of Use' and 'Pests' are two independent ';' lists for the product, not crop↔pest pairs ->
  one use row per site, with the full pest list as target text and pairing='unpaired_lists';
  dose is not in the extract (label only) -> dose_value=null;
- technical-grade actives and manufacturing concentrates are skipped (not commercial products).
"""
from __future__ import annotations

import pandas as pd

from .base import BaseParser, Batch, excerpt, is_relevant, norm_name, parse_date

ENCODING = "cp1252"
RECORD_URL = "https://pr-rp.hc-sc.gc.ca/ls-re/lbl_detail-eng.php?p_disp_regn='{regno}'&p_regnum={regno}"
APPLICATION_URL = "https://pest-control.canada.ca/pesticide-registry-api/api/extract/application/{appnum}"
SKIP_MARKETING = {"TECHNICAL ACTIVE", "MANUFACTURING CONCENTRATE", "COMMERCIAL+MANUFACTURING CONCENTRATE"}


class CaPpidParser(BaseParser):
    source_id = "CA-PPID"
    country = "CA"
    authority = "Health Canada – Pest Management Regulatory Agency (PMRA)"

    def parse(self, snap=None) -> Batch:
        snap = snap or self.latest_snapshot()
        b = self.new_batch(snap)
        prod_doc = self.docs(snap.snapshot_id, name_suffix="ca_product.csv")[0]
        app_docs = self.docs(snap.snapshot_id, name_suffix="ca_application.csv")
        df = pd.read_csv(prod_doc.local_path, encoding=ENCODING, dtype=str, low_memory=False).fillna("")
        rel = df[df.apply(lambda r: is_relevant(r["Product name - English"], r["Registrant name"], r["Active ingredients - English"]), axis=1)]
        skipped = rel[rel["Marketing type"].isin(SKIP_MARKETING)]
        rel = rel[~rel["Marketing type"].isin(SKIP_MARKETING)]
        b.notes.append(f"{len(rel)} relevant commercial products; {len(skipped)} technical/manufacturing rows skipped")

        for _, r in rel.iterrows():
            regno = r["Registration number"].strip()
            url = RECORD_URL.format(regno=regno)
            pid = b.add_product(r["Product name - English"], r["Active ingredients - English"])
            rid = b.add_registration(
                f"R-CA-{regno}", pid, self.country, self.authority, regno, r["Registration Status"], url,
                prod_doc.raw_document_id, "csv_parser",
                excerpt(r.to_dict(), ["Registration number", "Product name - English", "Registration Status", "Expiry date",
                                      "Marketing type", "Date first registered", "Active ingredients - English",
                                      "Registrant name", "Current / Historical"]),
                approval_date=parse_date(r["Date first registered"]), expiration_date=parse_date(r["Expiry date"]),
                holder_original=r["Registrant name"] or None, formulation_original=None,
                active_entity_original=r["Active ingredients - English"] or None,
            )
            if r["Product name - French"] and norm_name(r["Product name - French"]) != norm_name(r["Product name - English"]):
                b.add_alias(pid, r["Product name - French"], "alternate_name", "PPID 'Product name - French'", url, "CA")
            sites = [s.strip() for s in r["Sites of Use"].split(";") if s.strip()]
            pests = "; ".join(p.strip() for p in r["Pests"].split(";") if p.strip()) or None
            ev = excerpt(r.to_dict(), ["Sites of Use", "Pests", "Use Site Category"])
            for i, site in enumerate(sites, 1):
                b.add_use(f"U-{rid}-{i}", rid, url, prod_doc.raw_document_id, "csv_parser", ev,
                          crop_name_original=site, target_name_original=pests, pairing="unpaired_lists",
                          use_status_original=r["Registration Status"])
            if not sites:
                b.notes.append(f"{regno}: no 'Sites of Use' in extract")

        if app_docs:
            self._historical_names(b, app_docs[0], set(rel["Registration number"].str.strip()))
        return b

    def _historical_names(self, b: Batch, doc, regnos: set[str]) -> None:
        df = pd.read_csv(doc.local_path, encoding=ENCODING, dtype=str, low_memory=False).fillna("")
        df = df[df["Registration number"].str.strip().isin(regnos)]
        by_reg = {r["registration_number"]: r["product_id"] for r in b.registrations}
        n = 0
        for _, a in df.iterrows():
            regno = a["Registration number"].strip()
            pid = by_reg.get(regno)
            name = a["Product name - English"].strip()
            if not pid or not name:
                continue
            if norm_name(name) != norm_name(b.products[pid]["commercial_name"]):
                b.add_alias(pid, name, "historical_name",
                            f"PPID application {a['Application number']} received {a['Date received']} ({a['Purpose']}; registrant {a['Name of registrant']})",
                            APPLICATION_URL.format(appnum=a["Application number"]), "CA")
                n += 1
        b.notes.append(f"{n} historical name rows from application extract")
