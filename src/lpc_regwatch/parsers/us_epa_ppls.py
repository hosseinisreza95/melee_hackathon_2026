"""US EPA PPLS parser: one ppls_<regno>.json -> registration, uses, aliases.

What the source asserts: product status (Active/Inactive/Pending), formulation, active ingredients
with percentage, alternate and inactive brand names, transfer history, label PDF list, and two
independent lists `sites` and `pests` (no pairing, no dose) -> use rows with pairing='unpaired_lists'.
`product_status_date` is the date of the current status, not the first registration date, so
approval_date stays null and the status date goes into the evidence excerpt.
"""
from __future__ import annotations

import json

from .base import BaseParser, Batch, is_relevant, parse_date

API_URL = "https://ordspub.epa.gov/ords/pesticides/cswu/ppls/{regno}"


class UsEpaPplsParser(BaseParser):
    source_id = "US-EPA-PPLS"
    country = "US"
    authority = "US Environmental Protection Agency (EPA)"

    def parse(self, snap=None) -> Batch:
        snap = snap or self.latest_snapshot()
        b = self.new_batch(snap)
        docs = [d for d in self.docs(snap.snapshot_id, kind="api_json") if "/ppls_" in d.local_path.replace("\\", "/")]
        empty = skipped = 0
        for d in docs:
            rec = json.loads(open(d.local_path, encoding="utf-8").read())
            if not isinstance(rec, dict) or "eparegno" not in rec:
                empty += 1
                continue
            holder = (rec.get("companyinfo") or [{}])[0].get("name")
            actives = rec.get("active_ingredients") or []
            active_txt = "; ".join(f"{a.get('active_ing')} ({a.get('active_ing_percent')}%)" if a.get("active_ing_percent") is not None
                                   else str(a.get("active_ing")) for a in actives) or None
            if not is_relevant(rec.get("productname"), holder, active_txt):
                skipped += 1
                continue
            regno = rec["eparegno"]
            url = API_URL.format(regno=regno)
            formulation = ", ".join(f.get("formulation") for f in rec.get("formulations") or [] if f.get("formulation")) or None
            pid = b.add_product(rec["productname"], active_txt, url=url, country=self.country)
            ev = (f"eparegno={regno} | productname={rec.get('productname')} | product_status={rec.get('product_status')} "
                  f"| product_status_date={rec.get('product_status_date')} | cancel_flag={rec.get('cancel_flag')} "
                  f"| company={holder} | formulation={formulation} | active_ingredients={active_txt} "
                  f"| latest_label={(rec.get('pdffiles') or [{}])[0].get('pdffile')} | transfers={len(rec.get('transfer_history') or [])}")
            rid = b.add_registration(f"R-US-{regno}", pid, self.country, self.authority, regno, rec.get("product_status"),
                                     url, d.raw_document_id, "json_parser", ev,
                                     approval_date=parse_date(rec.get("registereddate")), expiration_date=None,
                                     holder_original=holder, formulation_original=formulation, active_entity_original=active_txt)
            for a in rec.get("altbrandnames") or []:
                b.add_alias(pid, a.get("altbrandname") or "", "alternate_name", "PPLS altbrandnames", url, "US")
            for a in rec.get("inactive_brand_names") or []:
                name = (a.get("inactive_brand_name") or "").strip()
                if name and name.upper() != "NA":
                    b.add_alias(pid, name, "historical_name", "PPLS inactive_brand_names", url, "US")
            sites = [s.get("site") for s in rec.get("sites") or [] if s.get("site")]
            pests = "; ".join(p.get("pest") for p in rec.get("pests") or [] if p.get("pest")) or None
            use_ev = f"sites={len(sites)} | pests={pests}"
            for i, site in enumerate(sites, 1):
                b.add_use(f"U-{rid}-{i}", rid, url, d.raw_document_id, "json_parser", use_ev,
                          crop_name_original=site, target_name_original=pests, pairing="unpaired_lists",
                          use_status_original=rec.get("product_status"))
        b.notes.append(f"{len(docs)} records read; {empty} empty; {skipped} not relevant; {len(b.registrations)} registrations")
        return b
