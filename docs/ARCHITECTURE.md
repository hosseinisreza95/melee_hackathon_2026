# Architecture

```
 official sources                 evidence store                 canonical store                 consumers
 ─────────────────                ──────────────                 ───────────────                 ─────────
 CA  PPID CSV extracts  ─┐        data/raw/<src>/<ts>/           PostgreSQL / SQLite             Streamlit UI (thin client)
 US  EPA PPLS JSON+PDF  ─┼─ collectors ─► file + .meta.json ─► parsers ─► products, aliases,  ─► FastAPI ─► Power Platform connector
 FR  E-Phy weekly zip   ─┤   (snapshot,    (url, sha256,          (originals   registrations, uses   (/compare  Copilot Studio action
 BR  AGROFIT CSV 392 MB ─┘    drift guard)  collected_at)          verbatim)   + snapshots, raw_docs,  /ask      Power Automate → SharePoint
                                                                   │           change_log, review_log  /export)  submission.json → evaluator
                                   label PDFs (CA/US dose) ─► LLM extraction with verbatim-excerpt gate ─► uses (llm_pdf, to verify)
                                                                   ▼
                                                     normalize + matching (EPPO exact-only, units, taxonomy, official equivalences,
                                                     sister hypotheses) — originals never modified
```

## Layers and the rule each one enforces

| Layer | Module | Rule it enforces |
|---|---|---|
| Collectors | `collectors/` | store before transforming; provenance sidecar per file; failed run recorded with reason; schema drift stops the run (G2, G6, G7) |
| Parsers | `parsers/` | deterministic; `*_original` verbatim; evidence excerpt from the source row; status normalised only via a versioned table (M3, N3) |
| Normalisation | `normalize/`, `matching.py` | exact-only EPPO candidates flagged `to_verify`; unit conversion only when meaning-preserving; taxonomy synonyms only with evidence; species+strain identity (N1, N2, N4, N5) |
| Store | `db/models.py` | source, URL, timestamp, snapshot, validation status NOT NULL on regulatory rows; `is_synthetic` everywhere; `review_log` for human decisions (G2, G8, F6) |
| AI extraction | `extract/label_llm.py` | strict JSON schema; every row must quote a verbatim excerpt found in the PDF or is rejected; rows flagged `llm_pdf` / `llm_paired` / `automatically_extracted` (F3, ai criterion) |
| API | `api/` | contract of `schema/openapi.yaml`; `evidence`, `warnings`, `disclaimer` on every answer; 404 text says it is not proof of absence (M2, M4, G1, G4) |
| Agent | `api/ask.py` | deterministic planner + predefined read-only tools; LLM only rephrases; grounding guard rejects numbers/countries outside the facts; works without any key (G3, §16) |
| UI | `ui/app.py` | thin client of the API; original and normalised side by side; badges for status, pairing, extraction, validation (ux) |
| M365 | `m365/` | Swagger 2.0 connector generated from the live schema; flows and Copilot action documented (M6) |
| Infra | `infra/` | compose stack, single public port, non-root containers, secrets only in `.env`, cron refresh, additive migrations (M7, S3, S4) |

## External services

| Service | Used for | Data sent | Configurable |
|---|---|---|---|
| Health Canada PPID, US EPA PPLS, data.gouv.fr (ANSES), dados.agricultura.gov.br (MAPA) | official data | nothing but public GET requests with a descriptive User-Agent | `HTTP_USER_AGENT` |
| OpenAI-compatible LLM endpoint (OpenAI / Azure OpenAI / Gemini / local) | label extraction, answer phrasing | label text of public PDFs; database facts; the user's question. Never personal data. | `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`, `AI_BASE_URL` |

No other external call exists. The UI talks only to the API; the API talks only to the database and the LLM endpoint.

## Data storage

- Development: SQLite file `data/lpc_regwatch.sqlite` (git-ignored).
- Server: PostgreSQL 16 in Docker volume `pgdata`; raw evidence in volume `rawdata`; nothing leaves the LPC-controlled host.
- Exports (`data/*.csv`, `/export.csv`, `/export.xlsx`) are derived documents and say so.

## Path to production (what would change)

1. Entra ID in front of the API (App roles Reader / Reviewer), API Management or Caddy OAuth2 proxy; HTTPS by domain.
2. Alembic migrations instead of additive `ALTER TABLE`; PostgreSQL backups to Azure Blob.
3. Collectors as scheduled jobs (Azure Container Apps Jobs or the host cron shipped here); alerting on `status=failed` snapshots.
4. More sources with the same base class (BVL Germany already probed; Belgium Fytoweb SFTP; Uruguay HTML) and organiser frozen extracts as a fallback source type.
5. EPPO Data Services client to turn `to_verify` codes into `validated` ones under RA control.
6. LLM provider = Azure OpenAI in the LPC tenant (same code, 4 env lines).
