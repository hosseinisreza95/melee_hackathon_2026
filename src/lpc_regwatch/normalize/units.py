"""Dose unit harmonisation. Only exact, meaning-preserving conversions (cahier §8.3 N2).

Target units: kg/ha for mass per area, L/ha for volume per area. Everything else (g/kg of seed,
g/L of substrate, g/plant, g/hive, g/m3) keeps its original unit and gets no normalized value.
"""
from __future__ import annotations

import re

_TO_KG_HA = {"kg/ha": 1.0, "g/ha": 0.001, "g/m²": 10.0, "g/m2": 10.0, "kg/m²": 10000.0, "kg/m2": 10000.0, "t/ha": 1000.0,
             "lb/acre": 1.1208511, "lb/a": 1.1208511, "lbs/acre": 1.1208511, "oz/acre": 0.0700532, "kg/acre": 2.4710538}
_TO_L_HA = {"l/ha": 1.0, "ml/ha": 0.001, "ml/m²": 10.0, "ml/m2": 10.0, "l/m²": 10000.0, "l/m2": 10000.0,
            "qt/acre": 2.3385, "pt/acre": 1.16925, "gal/acre": 9.35396, "floz/acre": 0.0730778, "fl.oz/acre": 0.0730778}


def _key(u: str) -> str:
    u = u.strip().lower().replace("litre", "l").replace("liter", "l").replace("hectare", "ha")
    u = u.replace("fl. oz", "floz").replace("fl oz", "floz").replace("fluid ounces", "floz").replace("ounces", "oz").replace("pounds", "lb")
    return re.sub(r"\s+", "", u)


def normalize_dose(value: float | None, unit: str | None) -> tuple[float | None, str | None]:
    """Return (value_normalized, unit_normalized) or (None, None) when no exact conversion exists."""
    if value is None or not unit:
        return None, None
    k = _key(unit)
    if k in _TO_KG_HA:
        return round(value * _TO_KG_HA[k], 6), "kg/ha"
    if k in _TO_L_HA:
        return round(value * _TO_L_HA[k], 6), "L/ha"
    return None, None
