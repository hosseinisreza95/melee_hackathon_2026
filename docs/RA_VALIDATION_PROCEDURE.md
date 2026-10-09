# Regulatory Affairs validation procedure (human in the loop)

The prototype never asserts regulatory validity. Every row is born `automatically_extracted` and can only be
promoted by a named reviewer. This page is the procedure the RA team follows; the mechanism is `POST /review`
(UI: *Produits sœurs & revue*) and the `review_log` table.

## Statuses (field_dictionary)

| validation_status / review_status | Meaning | Who sets it |
|---|---|---|
| `automatically_extracted` | parsed or AI-extracted, untouched by a human | pipeline |
| `to_verify` | flagged for review (sister hypotheses, EPPO candidates, AI rows) | pipeline or reviewer |
| `validated` | checked against the official record by RA | reviewer only |
| `rejected` | wrong or not applicable (e.g. a sister hypothesis that is a different formulation) | reviewer only |
| `obsolete` | superseded by a newer official record | reviewer or change detection |
| `source_unavailable` | the source could not be collected at the last run | pipeline |

## Weekly routine (30 minutes)

1. Open *Veille*: read `/changes` (field-level differences since the previous collection) and `/expiring?months=12`.
   For each change: open the official URL in the evidence, confirm, then mark the registration `validated` or `obsolete`.
2. Open *Produits sœurs & revue* for each pilot product: decide on `sister_product_candidate` rows.
   - Same registration carries both names (`alternate_name`, evidence "Official equivalence") → nothing to do, it is a fact.
   - Same species + strain, other name/registration → `validated` only with an internal document proving identity; otherwise `rejected` with a note.
3. Open *Sources & qualité* for the product: fields listed as missing/uncertain must either be completed from the label
   (then the AI-extracted `llm_pdf` rows are checked against the PDF excerpt quoted in `evidence_excerpt`) or left as is.
4. EPPO codes: codes marked `to_verify` are confirmed in EPPO Global Database; confirmed concepts are moved to `validated`
   in `data/eppo_*_mapping.csv` (the mapping table is versioned in git, the change is reviewed in a pull request).

## Rules that cannot be bypassed

- A `*_original` value is never edited; if the source is wrong, the row is `rejected` and the authority is contacted.
- A sister-product hypothesis is never shown as an equivalent before `validated`; the API and UI label it as a hypothesis.
- A product absent from a source is "not found in source as of <date>", never "not registered".
- Every status change is logged with reviewer, timestamp and note (`GET /review/log`) — this is the audit trail.
- AI confidence is machine confidence, not regulatory validity (MAPPING_README).
