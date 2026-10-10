# Evaluation of the AI parts (label extraction and grounded answers) — 2026-10-10

## 1. Label PDF extraction (Step 7)

Scope: the three pilot label PDFs stored by the US collector (EPA PPLS), read with PyMuPDF and extracted by the
configured model with a strict JSON schema, then filtered by the grounding gate (`extract/label_llm.py`).

| Label (EPA reg. no.) | Pages | Model | Rows returned | Accepted verbatim | Accepted partial* | Rejected | Why rejected |
|---|---|---|---|---|---|---|---|
| LALSTOP CONTANS WG (64137-34) | 13 | gpt-5 | 28 | 26 | 2 | 0 | — |
| LALGUARD M52 OD (64137-33) | 19 | gpt-5 | 34 | 32 | 2 | 0 | — |
| PRESTOP WG (64137-13, related product of G46) | 34 | gpt-5 | 23 | 5 | 7 | 11 | the model wrote `...` between table cells, so the excerpt start is not a verbatim substring |
| **Total** | | | **85** | **63** | **11** | **11** | |

\* partial = the whole excerpt is not contiguous in the PDF text (table cells re-ordered), but the first 60 characters,
the crop wording and the dose as written are each found verbatim; confidence capped at 0.7 and the evidence excerpt says so.

Earlier run with gpt-4.1 (same PDFs, kept in the cache for comparison): 51 returned, 51 accepted after the three-level
gate (34 verbatim, 17 partial), 0 rejected; with the first all-or-nothing gate the PRESTOP WG label had 17/17 rejected,
which is what led to the three-level design.

### Manual spot check (20 fields read against the PDF text)

| # | Label | Field checked | Extracted | PDF says | OK |
|---|---|---|---|---|---|
| 1 | CONTANS p.7 | crop group | Brassica (Cole) Leafy Vegetables: Broccoli, Chinese broccoli… | identical wording | ✔ |
| 2 | CONTANS p.7 | target | Sclerotinia sclerotiorum and Sclerotinia minor | identical | ✔ |
| 3 | CONTANS p.7 | dose (field) | 4 lbs/A, range "1 to 4 lbs/A" | "1 to 4 lbs/A (field & chemigation applications)" | ✔ |
| 4 | CONTANS p.7 | dose (greenhouse) | 1.5 oz/1000 ft2, range "0.75 to 1.5 oz/1000 ft2" | identical | ✔ |
| 5 | CONTANS p.7 | max applications | 8 | label section on maximum applications | ✔ |
| 6 | CONTANS p.7 | REI | 4 h | "Restricted-entry interval of 4 hours" | ✔ |
| 7 | CONTANS p.8 | crop group | Fruiting Vegetables (except cucurbits): Eggplant, groundcherry… | identical | ✔ |
| 8 | CONTANS p.7 | crop group | Bulb Vegetables: Chive, fresh leaves; … | identical | ✔ |
| 9 | M52 OD p.11 | crop group | Cucurbits including: cucumber, cantaloupe, melon… | identical | ✔ |
| 10 | M52 OD p.11 | target (drench) | Thrips | identical | ✔ |
| 11 | M52 OD p.11 | dose (drench) | 80 fl. oz./100 gal., range "[40-80 fl. oz./100 gal.] [4-8 fl. oz. / 10gal]" | identical | ✔ |
| 12 | M52 OD p.11 | target (foliar) | Thrips, Whiteflies, Mites, Aphids | identical | ✔ |
| 13 | M52 OD p.11 | dose (foliar) | 64 fl.oz./acre, range "8 – 64 fl.oz. [0.5 pt.- 2 qt]/acre low volume or 8-32 fl. oz. … / 100 gal." | identical | ✔ |
| 14 | M52 OD p.13 | crop group | Tree nuts, including: almond, beech nut… | identical | ✔ |
| 15 | M52 OD p.13 | turf dose | 3 fl. oz./ 1000 ft2, range "2 to 3 fl. oz./ 1000 ft2" | identical | ✔ |
| 16 | M52 OD | REI | 4 h | label REI statement | ✔ |
| 17 | PRESTOP WG p.27 | crop | TURF APPLICATIONS (use site) | table title; the model used the section title as crop | ✔ (coarse) |
| 18 | PRESTOP WG p.27 | dose | 0.33 oz per 1000 sq. ft. | "0.33" in the turf table | ✔ |
| 19 | PRESTOP WG | ornamental rows | rejected by the gate | the dose 13.2 oz / 100 gal exists in the PDF but the excerpt was not verbatim | correct rejection (recall loss, no false fact) |
| 20 | all | evidence page | page numbers 7, 8, 11, 13, 27 | excerpt found on that page by the gate | ✔ |

Result of the spot check: 19/20 fields exact, 1 coarse (use-site title instead of a crop list), 0 wrong values. Rows that the gate
rejected are missing data, never wrong data — the trade-off the challenge asks for ("ne pas inventer").

What the AI rows look like downstream: `pairing=llm_paired`, `extraction_method=llm_pdf`, `validation_status=automatically_extracted`,
`confidence` from the model (≤ 0.7 for partial grounding), `evidence_excerpt` = page + verbatim quote + grounding mode, `source_record_url`
= the official PDF URL. `/compare` warns about them; the UI shows them with a distinct badge; RA can validate or reject them row by row.

## 2. Grounded answers (`POST /ask`)

Answer shape (since 2026-10-10 evening): a Pydantic `StructuredAnswer` — `headline` (one or two sentences that answer the question),
`items` (only the rows that support it, only the fields that matter: country, number, status, expiry, a short detail such as
"Fraisier → pourriture grise, 0.25 kg/ha") and up to four `caveats`. The deterministic builder produces it from the facts; when a
key is configured the model receives the same facts plus the JSON schema and may only re-select and re-phrase; the grounding guard
runs on the flattened text. The UI renders headline, a compact table and the caveats; evidence and raw facts stay in expanders.
Languages: French, English, Portuguese (planner words, labels and the model's output language).

- Deterministic path (no key): 100 % of the facts come from predefined queries; tests `tests/test_gold.py` (T01–T05 + adversarial +
  other products/countries/crops) pass offline.
- LLM phrasing (gpt-5-mini on the server): the model receives only the facts and a deterministic draft. The grounding guard rejects any
  number or country code absent from the facts. On the five gold questions of the deployed run, all five LLM answers passed the guard
  (`output/submission.json` on the server: `"model": "gpt-5-mini"`, no "rejected by the grounding guard" warning).
- Known weakness: the guard tolerates 1–2 digit numbers (counts such as "3 pays"), so a wrong small count could pass; everything else
  (registration numbers, dates, doses, years) must exist in the facts.

## 3. Organiser evaluator

`python scripts/evaluate_submission.py output/submission.json` → **70 / 70** automatic points (structure, traceability, disclaimer, warnings,
M365 documentation, known limitations), locally and in the server pipeline. Qualitative criteria remain with the jury.

## 4. Step-by-step evaluation run (`scripts/evaluate_pipeline.py`, 2026-10-10, key configured)

The script re-measures every step on the current database and writes `output/evaluation_report.json`. Two runs: the laptop
(SQLite, gpt-5 / gpt-5-mini) and the server container (PostgreSQL, same models).

| Step | Measure | Laptop | Server |
|---|---|---|---|
| 1 Collectors | snapshots failed | 0 / 4 | 0 / 8 (two nights) |
| 2 Parsers | registrations · uses | 232 · 6 407 | 232 · 6 410 |
| 2 Parsers | traceability violations (URL, excerpt, date, originals, synthetic) | 0 | 0 |
| 3 Normalisation | use rows with an EPPO crop code | 15 % (label rows added many crop groups) | 15 % |
| 3 Normalisation | doses converted to kg/ha or L/ha | 41 / 215 (all FR area doses) | 41 / 218 |
| 3 Normalisation | registrations with status `unknown` · genus-only codes | 0 · none | 0 · none |
| 4 Matching | pilots per country | CONTANS CA/US/FR · G46 FR (+5 related) · M52 CA/US/FR (+7 related) | same |
| 4 Matching | hypotheses validated without review log | 0 | 0 |
| 5 Labels (gpt-5) | rows accepted (verbatim / partial) | 71 (66 / 5) | 74 (63 / 11) |
| 5 Labels | label crops matching an EPA site token | CONTANS 100 %, PRESTOP WG 100 %, M52 OD 59 % (label crop groups are broader than EPA sites) | 100 % / 100 % / 47 % |
| 6 /ask deterministic | 13 questions (gold + jury-style + adversarial), required facts present, no forbidden claim, coverage explained | 13 / 13 | 13 / 13 |
| 6 /ask with gpt-5-mini | same checks on the final answer | 13 / 13 · 9 phrased by the model, 3 rejected by the guard, 1 without facts | 13 / 13 · 10 phrased, 2 rejected |
| 7 Submission | organiser evaluator | 70 / 70 | 70 / 70 |

Reading the guard rejections: in T04 (sister products), J05 (expiry) and J07 (M52 on grapevine) the model's text contained a number
absent from the facts (a day count or a dose rewritten); the deterministic draft was served instead and the warning says so.
A re-run of the same questions later passed the guard — gpt-5-mini is not deterministic, which is exactly why the deterministic
path, not the model, is the contract.

Run-to-run variability of gpt-5 on labels: the same three PDFs produced 85 rows on the server run and 71 on the laptop run
(CONTANS 28 vs 19, M52 OD 34 vs 29, PRESTOP WG 12 vs 23). Every stored row still passes the grounding gate; what varies is
recall, never the presence of invented values. The cache by sha256 freezes one run until a PDF changes, and RA validates row by row.
