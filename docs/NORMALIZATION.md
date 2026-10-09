# Normalisation rules (cahier §8.3) — what is harmonised, how, and what is deliberately left alone

| Field | Original kept in | Normalised value | Rule | Status flag |
|---|---|---|---|---|
| Registration status | `status_original` | `status_normalized` ∈ active / expired / withdrawn / pending / unknown | exact lookup in `data/status_mapping.csv` (versioned); anything else → `unknown` + warning | — |
| Crop | `crop_name_original` | `crop_name_normalized`, `eppo_crop_code` | exact match of the cleaned wording against starter names, multilingual aliases and `data/eppo_observed_aliases.csv`; English plural stripped; EPA parenthetical context ("(SOIL TREATMENT)") ignored; composites split on `;`, ` - `, `*` | `eppo_crop_status`: `to_verify` (code from starter candidate), `list` (several concepts, no single code), `unmapped` (wording kept, no code) |
| Target | `target_name_original` | `target_name_normalized`, `eppo_target_code` | same, **no plural stripping and no genus → species guess** ("Thrips", "Pythium" never get a species code); scientific name inside parentheses is used ("WHITE MOLD (SCLEROTINIA SCLEROTIORUM)") | `eppo_target_status` |
| Dose | `dose_value`, `dose_unit_original` | `dose_value_normalized`, `dose_unit_normalized` | only exact conversions to kg/ha or L/ha (g/m², g/ha, ml/ha, lb/acre, oz/acre, qt/acre…); g/kg of seed, g/L of substrate, g/plant, g/hive stay unconverted | null when no exact conversion |
| Active entity | `active_entity_original` (per registration and product) | `active_entity_normalized` = "Species strain", `strain` | genus + species parsed from text; strain after strain/souche/cepa/isolado; synonyms applied only from the documented list (Gliocladium catenulatum → Clonostachys rosea; Metarhizium anisopliae **F52 only** → M. brunneum) | synonym note in the normalisation report |
| Product identity | `commercial_name` + `product_aliases` | one `product_id` per pilot across markets | kit canonical/historical names; official equivalences (same registration carries two names) persisted in `data/product_equivalences_observed.csv`; everything else is an alias or a hypothesis | `relationship_type`, `review_status` |
| Dates | source strings | `approval_date`, `expiration_date` (YYYY-MM-DD) | parsed only from unambiguous formats (ISO, dd/mm/yyyy, "Month d, yyyy"); otherwise null | — |

Not normalised on purpose: `restrictions_original`, `application_method` (source vocabularies differ too much to merge without RA review),
holder names (legal entities), formulation wording (kept as written; `formulation_code` only when the name ends with a known code).

Coverage on the 2026-10-09 data: crop code on ~23 % of use rows (CA/FR good, US site wording very granular), target code on rows with a
scientific name (BR, part of CA/US), dose conversion on all FR area doses (41 rows), 2 taxonomy synonyms applied, 1 official equivalence merged.
