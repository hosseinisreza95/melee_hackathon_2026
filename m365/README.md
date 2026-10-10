# Microsoft 365 interoperability

Status: **documented and connector files generated; not demonstrated in a live tenant** (the team has no Power
Platform tenant during the hackathon). Everything needed to import the API in a tenant is in this folder.

The prototype exposes one REST API (FastAPI, `schema/openapi.yaml` + extensions) at `http://<host>/api`.
Microsoft 365 reaches it in three documented ways, from the simplest to the most integrated.

| Path | What it gives Regulatory Affairs | Files |
|---|---|---|
| 1. Power Platform **custom connector** | `/compare`, `/products`, `/ask`, `/export.csv` as actions in Power Automate, Power Apps and Copilot Studio | `apiDefinition.swagger.json`, `apiProperties.json` |
| 2. **Power Automate** flow → SharePoint / Excel | Weekly refresh of the comparison table into a SharePoint list or an Excel file in Teams; alert on `/changes` and `/expiring` | `power_automate_flow.md` |
| 3. **Copilot Studio** agent action | Ask the question in Teams; the action calls `POST /ask`; the agent shows answer + evidence + warnings + disclaimer | `copilot_studio_action.md` |
| 4. **Dataverse** target model | The eight `lpc_*` tables of `schema/dataverse_tables.xlsx` exported as CSV zip / Excel / JSON rows, validated against the workbook; LPC's SharePoint registry reconciled with official sources | `docs/DATAVERSE_MAPPING.md`, `GET /export/dataverse.zip`, `POST /registry/reconcile` |

## 1. Custom connector (Power Platform)

Power Platform imports **OpenAPI 2.0 (Swagger)** files. `scripts/export_m365_connector.py` converts the live
FastAPI schema into `m365/apiDefinition.swagger.json` (10 operations, 15 definitions) and writes `apiProperties.json`.

Import steps (Power Automate → Data → Custom connectors → *New custom connector* → *Import an OpenAPI file*):

1. Upload `m365/apiDefinition.swagger.json`. Host and base path are pre-filled (`37.187.176.97`, `/api`); change them to the production host.
2. Security: the prototype is open (no key). For LPC the connector should use **OAuth 2.0 / Entra ID** (see §4); the Swagger file
   declares an `X-API-Key` header placeholder so the connector can be created without code changes.
3. Definition: operations `compareProductUses`, `searchProducts`, `askRegulatoryQuestion` are marked `x-ms-visibility: important`.
4. Test tab: `GET /compare?productId=P-LPC-CONTANS&countries=CA,US,FR,BR` → JSON with `registrations[]`, `coverage[]`, `warnings[]`, `disclaimer`.

Regenerate after any API change:

```bash
python scripts/export_m365_connector.py --host <host> --base-path /api --scheme https
```

## 2. Power Automate flow (CSV → SharePoint)

See `power_automate_flow.md` for the step list. Summary: *Recurrence (weekly, Monday 06:00)* → *HTTP GET
`/export.csv?productId=P-LPC-CONTANS&countries=CA,US,FR,BR`* → *Create file* in the SharePoint library
`Regulatory/Comparisons/` → *HTTP GET `/changes?limit=50`* → if non-empty, *Post a message in Teams* with the
changed registrations and their source URLs. Every CSV row carries `source_id`, `source_record_url`, `collected_at`,
`validation_status`, so the SharePoint copy keeps the traceability.

## 3. Copilot Studio action

See `copilot_studio_action.md`. The agent has one action (connector operation `askRegulatoryQuestion`) with inputs
`question`, `language`. The agent's response template prints `answer`, then the `evidence[]` list (source, URL, collected_at,
validation_status), then `warnings[]`, then `disclaimer`. The generative-answers feature is **disabled** for this topic so
the agent cannot answer from the web (cahier §16: no uncontrolled web search).

## 4. Security design (Entra ID) — documented, not built

- API behind **Azure API Management** (or Caddy + OAuth2 proxy) requiring an Entra ID bearer token; app registration
  `lpc-regwatch-api` with two app roles: `RegWatch.Reader` (GET endpoints) and `RegWatch.Reviewer` (POST `/review`).
- The custom connector uses the Entra ID OAuth 2.0 security definition; users log in with their LPC account, no shared key.
- The LLM key stays server-side in the API container's environment; it is never visible to Power Platform.
- Data residency: database and raw evidence on the LPC server (PostgreSQL volume); nothing is stored in the connector.

## 5. What the prototype demonstrates today

- `GET /openapi.json` and `/docs` served live; the Swagger 2.0 export validated by import-time checks of Power Platform
  (unique operationIds, `in: body` parameter, 2.0 types, `x-ms-*` metadata).
- `GET /export.csv` and `/export.xlsx` tested (BOM UTF-8 CSV opens correctly in Excel; XLSX has `comparison`, `sources`,
  `disclaimer` sheets).
- `/ask` returns the `Answer` object of the contract (answer, evidence, warnings, disclaimer) that Copilot Studio renders.

## 6. Evidence to add after a tenant test (todo for the team)

Screenshots: connector test tab, Power Automate run history, Copilot Studio conversation showing evidence and disclaimer.
