"""Crop and target normalisation against the starter EPPO candidate lists.

Rules (cahier §8.3 N1, MAPPING_README):
- a mapping is produced only when the cleaned source wording equals a known name or alias
  (starter multilingual aliases + data/eppo_observed_aliases.csv, which records wordings actually
  seen in the sources). No fuzzy matching: a wrong EPPO code is worse than none;
- every produced code carries status `to_verify` (starter candidates are not EPPO-verified);
- unmapped wording -> normalized name = cleaned wording, code null, status `unmapped`;
- lists ("A; B") and composites ("Tomate - Aubergine") are mapped token by token; a code is set only
  when exactly one concept results, otherwise the names are joined and the code stays null.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache

from ..config import ROOT

DATA = ROOT / "data"
PAREN = re.compile(r"\s*\([^)]*\)")
NOISE = {"no pest", "no pests", "none"}


@dataclass(frozen=True)
class Concept:
    concept_id: str
    name_normalized: str
    scientific_name: str | None
    eppo_code: str | None
    mapping_status: str  # to_verify | validated


@dataclass(frozen=True)
class Mapping:
    normalized: str | None
    eppo_code: str | None
    status: str  # to_verify | validated | unmapped | list
    concept_ids: tuple[str, ...] = ()


def _clean(s: str) -> str:
    s = s.replace("’", "'").strip().lower()
    return re.sub(r"\s+", " ", s)


@lru_cache
def _index(kind: str) -> tuple[dict[str, Concept], dict[str, str]]:
    """Return (concepts by id, alias -> concept_id) for 'crop' or 'pest'."""
    concepts: dict[str, Concept] = {}
    alias: dict[str, str] = {}
    fn = "eppo_crop_mapping.csv" if kind == "crop" else "eppo_pest_mapping.csv"
    with (DATA / fn).open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c = Concept(r["concept_id"], r["name_normalized"], r.get("scientific_name") or None,
                        r.get("eppo_code") or None, r.get("mapping_status") or "to_verify")
            concepts[c.concept_id] = c
            for a in [r["name_original"], r["name_normalized"], r.get("scientific_name") or ""]:
                if a:
                    alias[_clean(a)] = c.concept_id
            for tok in (r.get("multilingual_aliases") or "").split("|"):
                tok = tok.split(":", 1)[-1]
                if tok.strip():
                    alias[_clean(tok)] = c.concept_id
    # observed wordings (seen in the sources) and extra multilingual aliases (diseases, pests, Spanish/Portuguese crops) for
    # the assistant: same exact-match rule, codes are candidates (to_verify) until checked on gd.eppo.int
    for fn in ("eppo_observed_aliases.csv", "eppo_extra_aliases.csv"):
        p = DATA / fn
        if not p.exists():
            continue
        with p.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r["kind"] != kind:
                    continue
                cid = r["concept_id"]
                if cid not in concepts:  # concept added from observations: code is a candidate, status to_verify
                    sci = r.get("scientific_name") or None
                    concepts[cid] = Concept(cid, sci or cid.replace("_", " ").capitalize(), sci, r.get("eppo_code_candidate") or None, "to_verify")
                alias[_clean(r["alias"])] = cid
    return concepts, alias


def _map_token(tok: str, kind: str) -> tuple[str | None, Concept | None]:
    concepts, alias = _index(kind)
    t = _clean(tok)
    if not t or t in NOISE:
        return None, None
    cid = alias.get(t)
    if not cid:
        # EPA style "WHITE MOLD (SCLEROTINIA SCLEROTIORUM)" or "TOMATOES (SOIL TREATMENT)": inside parentheses, then outside
        inner = re.findall(r"\(([^)]*)\)", t)
        for cand in inner + [PAREN.sub("", t).strip()]:
            cid = alias.get(_clean(cand))
            if cid:
                break
    if not cid and kind == "crop":  # English plurals (TOMATOES); never for pests, where -s changes meaning
        base = PAREN.sub("", t).strip()
        if base.endswith("s") and alias.get(base[:-1]):
            cid = alias[base[:-1]]
    if cid:
        return tok.strip(), concepts[cid]
    return tok.strip(), None


def _display(raw: str) -> str:
    s = PAREN.sub("", raw).strip()
    return s.capitalize() if s.isupper() else s


def _normalize(original: str | None, kind: str, splitter: str) -> Mapping:
    if not original or not original.strip():
        return Mapping(None, None, "unmapped")
    tokens = [x for x in re.split(splitter, original) if x and x.strip()]
    names: list[str] = []
    cids: list[str] = []
    code: str | None = None
    any_known = False
    for tok in tokens:
        kept, c = _map_token(tok, kind)
        if kept is None:
            continue
        if c:
            any_known = True
            cids.append(c.concept_id)
            names.append(c.name_normalized)
            code = c.eppo_code
        else:
            names.append(_display(kept))
    uniq = list(dict.fromkeys(cids))
    names = list(dict.fromkeys(n for n in names if n))
    if len(tokens) > 1 or len(uniq) > 1:
        single = len(uniq) == 1 and len(names) == 1
        return Mapping("; ".join(names) or None, code if single else None, "list" if any_known else "unmapped", tuple(uniq))
    if uniq:
        c = _index(kind)[0][uniq[0]]
        return Mapping(c.name_normalized, c.eppo_code, c.mapping_status if c.eppo_code else "to_verify", (c.concept_id,))
    return Mapping(names[0] if names else None, None, "unmapped")


def normalize_crop(original: str | None) -> Mapping:
    return _normalize(original, "crop", r";|\s-\s|\*")


def normalize_target(original: str | None) -> Mapping:
    return _normalize(original, "pest", r";|\s-\s|\set\s|\sand\s")
