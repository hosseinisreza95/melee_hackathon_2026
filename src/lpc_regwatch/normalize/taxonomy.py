"""Active-entity (micro-organism) canonicalisation: species synonyms + strain, from the starter
active_entity_mapping.csv plus synonyms stated by the official sources themselves.

Rule N5: matching is on species AND strain; species alone never asserts identity.
Taxonomic synonyms are applied only from an explicit, evidenced list:
- starter kit AE-004: Gliocladium catenulatum J1446 -> Clonostachys rosea J1446 (validated internally)
- starter kit AE-007/AE-008: Metarhizium anisopliae (var. anisopliae) F52 -> Metarhizium brunneum F52
  (to_verify in the kit; the EPA record itself says "formerly known as Metarhizium anisopliae").
  Applied to strain F52 only: other M. anisopliae strains (e.g. Brazilian IBCB 425) are NOT renamed.
"""
from __future__ import annotations

import re

STRAIN_RE = re.compile(r"(?:strain|souche|cepa|isolado|isolate|stamm)\s*:?\s*([A-Za-z0-9][^(),;|]*)", re.I)
STOP = {"strain", "souche", "cepa", "isolado", "isolate", "produto", "biológico", "microbiológico", "formerly", "known",
        "var", "subsp", "sp", "spp", "technical", "nematóides", "vivos", "product", "microbiological"}
SPECIES_SYNONYMS: dict[str, tuple[str, str, set[str] | None]] = {
    # lowercase synonym -> (canonical species, evidence, strains for which the synonym applies or None=all)
    "gliocladium catenulatum": ("Clonostachys rosea", "starter AE-004 former_taxonomic_name (validated)", None),
    "metarhizium anisopliae": ("Metarhizium brunneum", "starter AE-007/AE-008 + EPA record 'formerly known as Metarhizium anisopliae'", {"F52", "MA 43", "MA43"}),
}


def strain_of(active: str | None) -> str | None:
    m = STRAIN_RE.search(active or "")
    if not m:
        return None
    s = re.sub(r"\s+", " ", m.group(1)).strip(" *.:")
    # cut the strain before any concentration wording: '5.3% w/w', '1x10^9 UFC/g', '32%', '900000000 UFC/g', '(...)'
    s = re.split(r"\s+(?=\d+(?:[.,]\d+)?\s*(?:%|x\s*10|×|UFC|CFU|g\b|g/|mg\b|ml\b|l\b|w/w|w/v))|\s+\(|\s+\d{6,}|\s+UFC|\s+CFU", s, flags=re.I)[0].strip(" *.:")
    return s[:40] or None


def species_of(active: str | None) -> str | None:
    """Genus + species from free text. Accepts 'Genus species', 'GENUS SPECIES' and 'Genus Species' (source typos)."""
    txt = (active or "").replace(",", " ").replace("(", " ( ")
    words = re.findall(r"[A-Za-zÀ-ÿ]+", txt)
    for i in range(len(words) - 1):
        g, s = words[i], words[i + 1]
        if len(g) < 4 or len(s) < 3 or g.lower() in STOP or s.lower() in STOP:
            continue
        if not g[0].isupper():
            continue
        if g.isupper() != s.isupper():  # 'BRUNNEUM Strain' or 'Produto MICRO' are not binomials
            continue
        return f"{g.capitalize()} {s.lower()}"
    return None


def canonical_active_entity(active: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (species_canonical, strain, normalized 'Species strain', synonym_note or None)."""
    sp = species_of(active)
    st = strain_of(active)
    note = None
    if sp:
        syn = SPECIES_SYNONYMS.get(sp.lower())
        if syn:
            canon, evidence, scope = syn
            if scope is None or (st or "").upper() in scope:
                note = f"{sp} -> {canon} ({evidence})"
                sp = canon
    norm = f"{sp} {st}" if sp and st else sp
    return sp, st, norm, note
