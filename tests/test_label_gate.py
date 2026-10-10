"""Grounding gate of the label extractor: verbatim excerpt accepted, re-ordered table cells accepted only when the
excerpt start, the crop and the dose as written all exist in the PDF text, anything else rejected. No LLM involved."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.extract.label_llm import grounding_check  # noqa: E402

PAGES = ["LALSTOP CONTANS WG\nDIRECTIONS FOR USE\n",
         "Brassica (Cole) Leafy Vegetables: Broccoli, cabbage, cauliflower  Sclerotinia sclerotiorum and S. minor  1 to 4 lbs/A  "
         "Apply to soil before planting.\nCucurbit Vegetables:  Chayote (fruit), Chinese waxgourd, citron melon, cucumber  1 to 4 lbs/A\n"]


def test_verbatim_excerpt_is_accepted_with_page():
    row = {"crop": "Brassica (Cole) Leafy Vegetables", "dose_value": 4, "dose_text": "1 to 4 lbs/A",
           "evidence_excerpt": "Brassica (Cole) Leafy Vegetables: Broccoli, cabbage, cauliflower  Sclerotinia sclerotiorum and S. minor  1 to 4 lbs/A"}
    assert grounding_check(row, PAGES) == ("verbatim", 2, None)


def test_reordered_cells_accepted_only_when_start_crop_and_dose_exist():
    row = {"crop": "Cucurbit Vegetables", "dose_value": 4, "dose_text": "1 to 4 lbs/A",
           "evidence_excerpt": "Cucurbit Vegetables:  Chayote (fruit), Chinese waxgourd, citron melon, cucumber Sclerotinia 1 to 4 lbs/A soil drench"}
    mode, page, why = grounding_check(row, PAGES)
    assert mode == "partial" and page == 2 and why is None


def test_invented_dose_or_crop_is_rejected():
    bad_dose = {"crop": "Cucurbit Vegetables", "dose_value": 9, "dose_text": "9 lbs/A",
                "evidence_excerpt": "Cucurbit Vegetables:  Chayote (fruit), Chinese waxgourd, citron melon, cucumber Sclerotinia 9 lbs/A drench"}
    mode, _, why = grounding_check(bad_dose, PAGES)
    assert mode is None and "dose" in why
    bad_crop = {"crop": "Tomato", "dose_value": 4, "dose_text": "1 to 4 lbs/A",
                "evidence_excerpt": "Tomato field grown  Sclerotinia  1 to 4 lbs/A apply at planting and again at thinning for best"}
    assert grounding_check(bad_crop, PAGES)[0] is None
    short = {"crop": "Cucurbit Vegetables", "dose_value": 4, "evidence_excerpt": "Cucurbit"}
    assert grounding_check(short, PAGES)[0] is None
