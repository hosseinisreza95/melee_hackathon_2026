# PLAN — step-by-step MVP build

Principle: one vertical slice at a time, each step ends with a test and a short review of
problems + suggestions before the next step starts. Nothing beyond MVP until `docs/SPEC.md`
MUST rows are done.

## Step 0 — Scaffolding and source investigation ✅ (this step)

- Starter kit merged into repo root (structure preserved).
- `docs/SPEC.md` written: every requirement → component → test.
- `docs/SOURCES.md` written: each source visited, download method verified, fields listed.
- Database schema created (`src/lpc_regwatch/db/models.py`, `scripts/init_db.py`).
- Probe scripts kept in `scripts/probe/` as evidence of how access was verified.

Exit test: `python scripts/validate_data.py` passes; `python scripts/init_db.py` creates
`data/lpc_regwatch.sqlite`; `pytest tests/test_db.py` green.

## Step 1 — Collectors + raw evidence store (sources → raw_documents) ✅ (2026-10-09)

Live result: CA 4 files / 28.9 MB, US 44 JSON + 6 pilot label PDFs / 4.2 MB, FR zip 4.0 MB, BR CSV 392 MB.
One failed US run (snapshot 2) is kept on purpose: it shows how a structural surprise is recorded
(`status=failed`, reason in notes) instead of producing data. Fixed by distinguishing "empty record"
from "schema drift". 8 offline tests green.

- `collectors/base.py`: interface `fetch() -> list[RawDocument]`, writes file + `.meta.json`
  (url, collected_at, sha256, content_type), registers a `snapshot`.
- `collectors/ca_ppid.py`: download `product`, `ingredient`, `application` CSV extracts.
- `collectors/us_epa_ppls.py`: search by partial name / ingredient → fetch `/ppls/{regno}` JSON
  for the pilot registrations; record label PDF URLs.
- `collectors/fr_ephy.py`: resolve latest UTF-8 zip via data.gouv.fr API, download, unzip.
- `collectors/br_agrofit.py`: resolve resource URLs via CKAN `package_search`, stream the 392 MB CSV to disk.
- Schema-drift guard: expected column list per source; unexpected → `SchemaDriftError`.

Exit test: `tests/test_collectors.py` (offline, on fixtures) + one live run producing
`data/raw/<source>/<date>/...` for all four sources.

## Step 2 — Parsers (deterministic) → canonical rows

- `parsers/ca_ppid.py`: product rows → `products`, `registrations`, `uses` (site × pest, dose null).
- `parsers/us_epa_ppls.py`: JSON → `products`, `registrations`, `uses` (site × pest, dose null),
  `product_aliases` from `altbrandnames` / `inactive_brand_names`.
- `parsers/fr_ephy.py`: `produits` + `usages_des_produits_autorises` → full `uses` with dose,
  unit, PHI, max applications, BBCH stages, conditions.
- Status normalisation table `data/status_mapping.csv`.
- Only pilot products + Lallemand registrant filter for MVP (keeps DB small, demo fast).

Exit test: `tests/test_parsers.py` on fixture files; `scripts/validate_data.py` on exported CSVs;
row counts reported in `docs/SOURCES.md`.

## Step 3 — Normalisation + matching

- EPPO mapping via starter CSVs (crop, pest) with multilingual aliases; unmapped → `to_verify`.
- Product identity across countries via `product_name_mapping.csv` + `active_entity_mapping.csv`
  + observed aliases (EPA alt brand names, E-Phy "seconds noms commerciaux").
- Sister-product candidates = same species + strain, different commercial name → `to_verify`.

Exit test: `tests/test_matching.py`; the three pilot products resolve to one `product_id` each
across CA / US / FR; PRESTOP ↔ LALSTOP G46 WG is a `sister_product_candidate`.

## Step 4 — API (openapi.yaml contract)

- FastAPI implementing `/health`, `/products`, `/products/{id}/registrations`, `/compare`, `/ask`.
- `/ask`: entity resolution → tool calls (predefined SQL) → answer from rows only; returns
  `evidence[]`, `warnings[]`, `disclaimer`.
- LLM client: OpenAI-compatible, provider/model/key from env (`AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`,
  `AI_BASE_URL`). Works with OpenAI, Gemini (OpenAI-compatible endpoint) and Azure OpenAI.

Exit test: `tests/test_api.py`, `tests/test_gold.py` (T01–T05); `scripts/build_submission.py`
→ evaluator 70/70.

## Step 5 — UI (Streamlit workbench, thin client of the API)

- Comparison table (product × country × use) with per-cell status badge + source link + date.
- Detail panel: original vs normalized values, evidence excerpt, confidence.
- Prompt box → `/ask`; result updates table + warnings.
- CSV / Excel export button.

Exit test: manual run-through of T01–T05 in the UI; screenshots in `docs/demo/`.

## Step 6 — M365 interoperability

- Export `schema/openapi.yaml` (served at `/openapi.json`) → Power Platform custom connector.
- Copilot Studio agent with one action calling `/ask`; or Power Automate flow consuming `/export.csv`
  into SharePoint. Document with screenshots in `m365/README.md`.

Exit test: one question answered in Copilot Studio with the same evidence as the UI.

## Step 7 — Label PDF extraction (AI) — first "nice to have" inside MVP

- For CA and US, dose lives only in label PDFs. `extract/label_llm.py`: PDF → text (PyMuPDF) →
  LLM with strict JSON schema → `uses` rows with `extraction_method=llm`, `confidence`,
  `evidence_excerpt`, `validation_status=automatically_extracted`.
- Cache by PDF sha256. Only pilot labels (≈ 6 PDFs).

Exit test: 20 hand-checked fields vs PDF; precision reported in `docs/EVAL.md`.

## Step 8 — Packaging

- `infra/docker-compose.yml` (api, ui, postgres) for the team server.
- README quickstart verified on a clean machine. Known limitations + RA validation procedure
  + path to production written (cahier §15 deliverables).

## Bonus (only if all above are green)

Change detection (`change_log`), expiry alerts, choropleth map, competitor footprint.
