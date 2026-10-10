# Dataverse target model (schema/dataverse_tables.xlsx) — how the prototype produces it

LPC: "C'est le modèle qui fait foi. Vous n'êtes pas obligés d'utiliser Dataverse, mais votre solution doit pouvoir produire ou
exposer cette structure, sans retirer les champs de traçabilité ni les statuts de validation."

The prototype exposes the eight tables with the workbook's logical names (`lpc_*`), choice CSV values and alternate keys:

| How | Where |
|---|---|
| Zip of CSV files, one per table | `GET /export/dataverse.zip` · `python scripts/export_dataverse.py` → `output/dataverse/` |
| One Excel workbook, one sheet per table | `GET /export/dataverse.xlsx` |
| JSON rows per table (paged) for Power Automate / Dataflows | `GET /export/dataverse/{table}` |
| Self-check against the workbook (columns, business-required filled, choice values legal, text lengths) | `GET /export/dataverse-validation` · `tests/test_dataverse_registry.py` |

Columns of the workbook come **first and in its order**; our additional fields follow with the suffix `_ext` (an import can map or ignore them).
Nothing of the traceability set (source, record URL, collected-at, validation status, is_synthetic) is ever dropped.

## Table by table

| Dataverse table | Rows from | Notes and additive extensions |
|---|---|---|
| `lpc_product` (6 cols) | `products` | `lpc_owner` = `lpc` when a registration holder matches Danstar/Lallemand or the id is `P-LPC-*`, else `competitor`. Ext: `lpc_activeentitynormalized_ext`, `lpc_strain_ext`. |
| `lpc_productname` (10 cols) | one `canonical_name` row per product + every `product_aliases` row | `lpc_relationshiptype` uses the workbook choice set; our `related_product` (LPC: PRESTOP WG, LALFRESH S) is emitted as `related_formulation` with the exact value in `lpc_relationshipdetail_ext` — **proposal: add `related_product` to `lpc_namerelationship`**. `lpc_confidencestatus` derived (LPC statement → `confirmed_internal`; official field → `confirmed_related`; ≥ 0.8 → `strong_candidate`; else `candidate`). `lpc_mappingcode` = alias id, or a stable hash code when longer than 50 (full id in `lpc_aliasid_ext`). |
| `lpc_activeentity` (12 cols) | one row per distinct active-entity wording per product | `taxonomic_synonym` rows carry `former_taxonomic_name` and `to_verify` when a documented synonym was applied (Gliocladium → Clonostachys; M. anisopliae F52 → M. brunneum). |
| `lpc_source` (9 cols) | `sources` | `lpc_accessmethod` multi-value separated by `;` (workbook: multi-select allowed). |
| `lpc_registration` (14 cols) | `registrations` | Ext: `lpc_registrationholder_ext` (**LPC asked to add `registration_holder` to the model**), active entity and formulation as written, extraction method, evidence excerpt, snapshot id, is_current. |
| `lpc_authorizeduse` (19 cols) | `uses` | Ext: normalised dose value, EPPO mapping statuses, `pairing` (source_paired / unpaired_lists / llm_paired), extraction method, confidence, evidence excerpt, record URL, collected-at. |
| `lpc_eppocode` (9 cols) | starter crop/pest CSVs + observed aliases | observed wordings appended to `lpc_multilingualaliases` as `lang:alias (seen in SOURCE)`; new concepts (alfalfa, bean…) as `to_verify` rows. Key = concept + type. |
| `lpc_changelog` (7 cols) | `change_log` | `lpc_changecode` = `CHG-{id:06d}` (workbook: autonumber on import). Empty until the second collection of a source. |

## Validation result (deployed data, 2026-10-10)

`GET /export/dataverse-validation` → `ok: true` for all eight tables (219 products, 354 names, 232 active-entity rows, 9 sources,
232 registrations, 6 387 uses, 63 EPPO concepts, 0 changes yet).

## Import path (Power Platform)

1. Create the tables from the workbook (or import the solution LPC builds from it); keep alternate keys of the `Keys` sheet.
2. Dataflow or Power Automate: `GET /export/dataverse/lpc_product` … `lpc_authorizeduse` in dependency order (product → source → registration → use),
   upsert on the alternate key; `*_ext` columns map to custom columns or are ignored.
3. Or import the zip CSVs with the Dataverse "Import data" wizard (one CSV per table).

## Two model gaps reported to LPC

- `registration_holder` is missing from `lpc_registration` (the internal registry has it; we export it as `lpc_registrationholder_ext`).
- `related_product` is missing from the name-relationship choice set (LPC's own distinction between a sister product and a related product).
