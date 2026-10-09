"""Brazil AGROFIT parser: formulated-products CSV (product x crop x pest rows).

What the source asserts: active registrations only (SITUACAO=TRUE), registrant, formulation,
active ingredient text (species, strain, concentration), class, and crop↔pest pairs (no dose,
no dates). Several commercial names may share one registration ('ANT-03 EC/BioTitan EC',
'Kamoi Pro; BioRoof;') -> first name is the product, others become alternate_name aliases.
The 392 MB file is read in chunks and filtered before anything is kept in memory.
"""
from __future__ import annotations

import re

import pandas as pd

from .base import BaseParser, Batch, excerpt, is_relevant

ENCODING = "utf-8-sig"
COLS = ["NR_REGISTRO", "MARCA_COMERCIAL", "FORMULACAO", "INGREDIENTE_ATIVO", "TITULAR_DE_REGISTRO", "CLASSE",
        "MODO_DE_ACAO", "CULTURA", "PRAGA_NOME_CIENTIFICO", "PRAGA_NOME_COMUM", "CLASSE_TOXICOLOGICA",
        "CLASSE_AMBIENTAL", "ORGANICOS", "SITUACAO"]


class BrAgrofitParser(BaseParser):
    source_id = "BR-AGROFIT"
    country = "BR"
    authority = "Ministério da Agricultura e Pecuária (MAPA) – AGROFIT"

    def parse(self, snap=None) -> Batch:
        snap = snap or self.latest_snapshot()
        b = self.new_batch(snap)
        doc = self.docs(snap.snapshot_id, name_suffix="agrofit_produtos_formulados.csv")[0]
        keep = []
        total = 0
        for chunk in pd.read_csv(doc.local_path, sep=";", dtype=str, encoding=ENCODING, usecols=COLS, chunksize=100_000, low_memory=False):
            chunk = chunk.fillna("")
            total += len(chunk)
            m = chunk.apply(lambda r: is_relevant(r["MARCA_COMERCIAL"], r["TITULAR_DE_REGISTRO"], r["INGREDIENTE_ATIVO"]), axis=1)
            keep.append(chunk[m])
        df = pd.concat(keep) if keep else pd.DataFrame(columns=COLS)
        b.notes.append(f"{len(df)} relevant rows of {total}; {df['NR_REGISTRO'].nunique()} registrations")
        url = doc.url

        for regno, g in df.groupby("NR_REGISTRO", sort=True):
            r = g.iloc[0]
            names = [n.strip() for n in re.split(r"[/;]", r["MARCA_COMERCIAL"]) if n.strip()]
            name = names[0] if names else r["MARCA_COMERCIAL"].strip()
            pid = b.add_product(name, r["INGREDIENTE_ATIVO"])
            ev = excerpt(r.to_dict(), ["NR_REGISTRO", "MARCA_COMERCIAL", "FORMULACAO", "INGREDIENTE_ATIVO", "TITULAR_DE_REGISTRO",
                                       "CLASSE", "CLASSE_TOXICOLOGICA", "CLASSE_AMBIENTAL", "ORGANICOS", "SITUACAO"])
            rid = b.add_registration(f"R-BR-{regno.strip()}", pid, self.country, self.authority, regno.strip(), r["SITUACAO"], url,
                                     doc.raw_document_id, "csv_parser", ev + " | note=open file lists active registrations only; no dates",
                                     approval_date=None, expiration_date=None, holder_original=r["TITULAR_DE_REGISTRO"].strip() or None,
                                     formulation_original=r["FORMULACAO"] or None, active_entity_original=r["INGREDIENTE_ATIVO"] or None)
            for other in names[1:]:
                b.add_alias(pid, other, "alternate_name", "AGROFIT MARCA_COMERCIAL lists several names for one registration", url, "BR")
            for i, (_, x) in enumerate(g.iterrows(), 1):
                b.add_use(f"U-{rid}-{i}", rid, url, doc.raw_document_id, "csv_parser",
                          excerpt(x.to_dict(), ["CULTURA", "PRAGA_NOME_CIENTIFICO", "PRAGA_NOME_COMUM", "MODO_DE_ACAO"]),
                          crop_name_original=x["CULTURA"] or None, target_name_original=x["PRAGA_NOME_CIENTIFICO"] or None,
                          application_method=x["MODO_DE_ACAO"] or None, pairing="source_paired",
                          use_status_original=x["SITUACAO"] or None)
        return b
