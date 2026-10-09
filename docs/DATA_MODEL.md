# DATA MODEL — canonical store

The store mirrors the starter-kit canonical CSVs (`data/*.csv`, `schema/canonical.schema.json`,
`data/field_dictionary.csv`) one-to-one, plus four traceability tables the challenge asks for
(snapshots, raw documents, change log, review log). Exporting `products`, `product_aliases`,
`registrations`, `uses`, `sources` back to CSV must pass `scripts/validate_data.py` unchanged.

Engine: SQLite by default (`DATABASE_URL=sqlite:///data/lpc_regwatch.sqlite`), PostgreSQL on the
team server (`DATABASE_URL=postgresql+psycopg://...`). Same SQLAlchemy models for both.

## Why these tables

| Table | Why it exists (requirement) |
|---|---|
| `sources` | starter `source_registry.csv`; every row must point to an official source (G2) |
| `snapshots` | one per collector run; `collected_at` and `collector_version` give temporal traceability (G6) and allow change detection (A1) |
| `raw_documents` | the file/JSON/PDF actually fetched: url, sha256, local path, content type → "store evidence before normalization" (QUICKSTART) |
| `products` | starter `products.csv` |
| `product_aliases` | starter `product_aliases.csv`; sister-product candidates stay hypotheses (M5) |
| `registrations` | starter `registrations.csv` + `snapshot_id`, `raw_document_id`, `evidence_excerpt`, `confidence`, `extraction_method` |
| `uses` | starter `uses.csv` + same evidence columns + `pairing` flag (CA/US give sites and pests as separate lists) |
| `change_log` | field-level diff between snapshots (bonus A1, cahier §12) |
| `review_log` | every change of `validation_status` with who/when/why → "mécanisme de validation humaine" and RA procedure |

## Column conventions

- `*_original`: exact source wording, never modified (README "Data rules").
- `*_normalized`: harmonised value; may be null when no exact mapping exists.
- `validation_status` ∈ {automatically_extracted, to_verify, validated, rejected, obsolete, source_unavailable}
  (field_dictionary). Default on ingestion: `automatically_extracted`.
- `confidence` ∈ [0,1]: machine confidence, **not** regulatory validity (MAPPING_README).
- `extraction_method` ∈ {csv_parser, json_parser, llm_pdf, manual}.
- `is_synthetic`: boolean, visible in every table (G8).
- `collected_at`: UTC ISO-8601 from the snapshot.
- `source_record_url`: the most specific public URL we can cite for that row.

## ER overview

```
sources 1──n snapshots 1──n raw_documents
products 1──n product_aliases
products 1──n registrations 1──n uses
registrations n──1 sources ; registrations n──1 snapshots ; registrations n──1 raw_documents
uses n──1 raw_documents
change_log (entity_type, entity_id, field, old, new, from_snapshot, to_snapshot)
review_log (entity_type, entity_id, old_status, new_status, reviewer, note, at)
```

## Identifiers

- `product_id`: `P-LPC-<SHORT>` for pilot products (from starter), `P-<COUNTRY>-<regno>` for others.
- `registration_id`: `R-<CC>-<official number>` e.g. `R-CA-29066`, `R-US-64137-34`, `R-FR-9900189`.
- `use_id`: `U-<registration_id>-<n>`.
- `source_id`: starter ids `CA-PPID`, `US-EPA-PPLS`, `FR-EPHY`, `DE-BVL`, ...

## Status normalisation (data/status_mapping.csv)

| source_id | status_original | status_normalized |
|---|---|---|
| CA-PPID | Full Registration / Temporary Product / Limited Term Product / Emergency Registration | active |
| CA-PPID | Phase-Out | expired |
| CA-PPID | Cancelled | withdrawn |
| US-EPA-PPLS | Active | active |
| US-EPA-PPLS | Inactive / Cancelled | withdrawn |
| US-EPA-PPLS | Pending | pending |
| FR-EPHY | AUTORISE | active |
| FR-EPHY | RETIRE | withdrawn |
| * | anything else | unknown (+ warning) |
