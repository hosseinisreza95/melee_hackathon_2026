# LPC Regulatory Watch — AI agent for global plant-protection registrations

Prototype built in 30 h for the Lallemand Plant Care challenge (Hackathon IA for Impact 2026, Mêlée Numérique Toulouse).
It collects **official** registration data for plant protection products, stores it with full provenance, normalises
it without ever overwriting the original wording, and answers product × country × use questions with evidence.

> **Regulatory disclaimer:** this repository and any prototype built from it are not official regulatory sources.
> Extracted information requires Regulatory Affairs validation before official, commercial or operational use.
> **No result must not be interpreted as no registration.**

| | |
|---|---|
| Live demo (team server) | UI `http://37.187.176.97/` · API docs `http://37.187.176.97/api/docs` · pitch `http://37.187.176.97/pitch/` |
| Sources (4, 3 regions) | Health Canada PPID (CA) · US EPA PPLS (US) · ANSES E-Phy (FR) · MAPA AGROFIT (BR) |
| Pilot products | LALSTOP CONTANS WG · LALSTOP G46 WG · LALGUARD M52 OD |
| Team report (FR) | [docs/AVANCEMENT_FR.md](docs/AVANCEMENT_FR.md) — what was done, challenges, solutions, why · LPC answers: [docs/LPC_QA.md](docs/LPC_QA.md) |
| Requirement matrix | [docs/SPEC.md](docs/SPEC.md) · plan [docs/PLAN.md](docs/PLAN.md) · sources [docs/SOURCES.md](docs/SOURCES.md) · limits [docs/LIMITATIONS.md](docs/LIMITATIONS.md) |

## Minimum success criteria → where

1. ≥ 3 official sources, ≥ 2 regions → 4 sources, 3 regions, `src/lpc_regwatch/collectors/`, verified in `docs/SOURCES.md`.
2. Product × country × use comparison → `GET /compare`, UI *Comparaison* and *Carte*, `GET /export.csv|xlsx`.
3. Original values alongside normalised → every `*_original` / `*_normalized` pair in `uses`, `registrations`, `products`.
4. Source + timestamp on every assertion → `evidence{sourceId, sourceUrl, collectedAt, validationStatus}` on every row; `raw_documents` with sha256.
5. Uncertainty visible → `warnings[]`, `validation_status`, `pairing`, `eppo_*_status`, `confidence`; UI badges.
6. Microsoft 365 → `m365/` (Power Platform connector files generated from the live API, Power Automate flow, Copilot Studio action, Entra ID design).
7. Restartable without personal keys → this README; AI provider is 4 env lines; everything except AI label extraction and AI phrasing works with **no key at all**.

## Run it (clean machine, 10 minutes + download time)

```bash
git clone https://github.com/hosseinisreza95/melee_hackathon_2026.git && cd melee_hackathon_2026
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                                 # no value is required
python scripts/init_db.py                            # SQLite in data/
python scripts/collect.py --source all               # ≈ 420 MB of official files into data/raw/<source>/<timestamp>/
python scripts/parse.py --source all                 # canonical rows + data/*.csv export + organiser validator
python scripts/normalize.py                          # EPPO / units / taxonomy / equivalences / sister hypotheses
python scripts/extract_labels.py                     # optional: needs AI_API_KEY; reads the 6 pilot label PDFs
python scripts/build_submission.py                   # output/submission.json → evaluator 70/70
python scripts/serve_api.py                          # http://localhost:8000/docs
streamlit run src/lpc_regwatch/ui/app.py             # http://localhost:8501
pytest -q                                            # 59 tests: schema, collectors (offline), parsers, normalisation, label gate, API, gold T01–T05 + jury-style questions, blind real-data checks
```

Docker (production-style stack: PostgreSQL + API + UI + Caddy, one public port): see [infra/README.md](infra/README.md).

## How a question is answered (and why it cannot invent)

```
question ─► deterministic planner (intent, product, countries, species, crop)
         ─► predefined read-only queries on the canonical store  ──► FACTS + EVIDENCE + WARNINGS
         ─► (optional) LLM rephrases FACTS only  ─► grounding guard: any number/country not in FACTS ⇒ rejected
         ─► Answer { answer, evidence[], warnings[], disclaimer }
```

Try: `POST /ask {"question": "Dans quels pays LALSTOP CONTANS WG est-il homologué ?"}`.

## Repository map

```
src/lpc_regwatch/   collectors/ parsers/ normalize/ matching.py loader.py extract/ api/ ui/ llm/ db/ config.py pilots.py
scripts/            init_db.py collect.py parse.py normalize.py extract_labels.py build_submission.py serve_api.py
                    export_m365_connector.py pipeline.sh validate_data.py evaluate_submission.py
data/               starter mappings (EPPO, names, active entities) + observed aliases + exported canonical CSVs
docs/               SPEC, PLAN, SOURCES, DATA_MODEL, ARCHITECTURE, RA_VALIDATION_PROCEDURE, LIMITATIONS, EVAL, AVANCEMENT_FR
m365/               apiDefinition.swagger.json, apiProperties.json, README, Power Automate flow, Copilot Studio action
infra/              Dockerfile, docker-compose.yml, Caddyfile, cron.d/, README
presentation/       pitch deck (self-contained HTML, animated)
tests/              59 tests incl. gold questions, jury-style questions and blind checks against the raw official files
schema/ evaluation/ business/ sources/ examples/   organiser starter kit (unchanged)
```

## Data rules kept

- `*_original` is never modified; normalisation lives in `*_normalized` with a status (`to_verify`, `list`, `unmapped`).
- Regulatory rows carry `source_id`, `source_record_url`, `collected_at`, `validation_status` (NOT NULL in the schema).
- `unknown` / `not_found_in_source` / `source_not_collected` instead of invented values.
- Sister-product matches are hypotheses until a reviewer validates them (`POST /review`, logged).
- `is_synthetic` exists on every table and is `false` everywhere in this repository.
- Personal contact data (EPA company contacts) is redacted at ingestion.

## Licence

Starter kit and this prototype: see `LICENSE.md`. Source data: Open Government Licence – Canada, US federal public data,
Licence Ouverte (ANSES / data.gouv.fr), Creative Commons Attribution (MAPA). Attribution lines are printed by `GET /sources`.
