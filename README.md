# LPC Global Regulatory AI Starter Kit

Starter repository for the Lallemand Plant Care challenge at Hackathon IA for Impact 2026.

> **Team working notes (hackathon build):** the step-by-step plan is in [`docs/PLAN.md`](docs/PLAN.md),
> the requirement → component → test matrix in [`docs/SPEC.md`](docs/SPEC.md), the verified source access
> report in [`docs/SOURCES.md`](docs/SOURCES.md) and the database design in [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md).
> MVP sources: Canada PPID, US EPA PPLS, France E-Phy (2 regions). Dev setup:
> `uv pip install -r requirements.txt` (or `pip install -r requirements.txt`), `cp .env.example .env`,
> `python scripts/init_db.py`, `pytest`.

## Mission
Build a functional proof of concept that collects, structures, normalizes and compares official plant protection product registration information across markets. Any technology may be used, but the result must expose a credible Microsoft 365 integration path.

## Minimum success criteria
1. Integrate at least **3 official sources** from at least **2 regions**.
2. Produce a product x country x use comparison.
3. Preserve original values alongside normalized values.
4. Cite the official source and collection timestamp for every regulatory assertion.
5. Make uncertainty, missing fields and validation status visible.
6. Demonstrate or document Microsoft 365 interoperability.
7. Deliver a repository restartable from this README without personal API keys.

> **Regulatory disclaimer:** This repository and any prototype built from it are not official regulatory sources. Extracted information requires Regulatory Affairs validation before official, commercial or operational use. No result must not be interpreted automatically as no registration.

## Repository map
```text
.
├── README.md / QUICKSTART.md / LICENSE.md / CONTRIBUTING.md
├── data/          # CSV templates and starter records
├── schema/        # Canonical model, JSON Schema and OpenAPI
├── evaluation/    # Rubric, gold questions and output contract
├── scripts/       # Data validation and scoring
├── business/      # Questions and glossary
├── sources/       # Source-use and attribution guidance
├── examples/      # Sample API and submission payloads
└── tests/         # Smoke test
```

## Start
```bash
git clone <repository-url>
cd lpc-global-regulatory-ai-starter
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
cp .env.example .env
python scripts/validate_data.py
python scripts/evaluate_submission.py examples/sample_submission.json
```
No third-party Python package is required for the starter scripts.

## Before development
- Select the 3 official sources and 2 regions.
- Select pilot products or active entities.
- Document the normalization and human-review workflow.
- Choose the Microsoft 365 integration mechanism.
- Test every access and prepare a frozen fallback extract.

## Data rules
- Never modify `*_original` values.
- Put transformations in `*_normalized` fields.
- Regulatory assertions require `source_id`, `source_record_url`, `collected_at` and `validation_status`.
- Use `unknown` or `not_found` rather than inventing information.
- Sister-product matches are hypotheses until reviewed.
- Synthetic data must use `is_synthetic=true`.

## Canonical contract
- Field definitions: `data/field_dictionary.csv`
- Data model: `schema/canonical_data_model.md`
- JSON Schema: `schema/canonical.schema.json`
- Minimal API: `schema/openapi.yaml`

Teams may extend the contract but must not silently remove traceability fields.

## EPPO mappings
The included mapping files are deliberately small. Candidate codes are marked `to_verify`; teams must verify them against EPPO before changing the status to `validated`.

## Microsoft 365 interoperability
Demonstrate or document at least one: REST API importable as a custom connector, Dataverse export, SharePoint/Power Automate JSON or CSV flow, Copilot Studio action, Azure/Entra ID design, or Teams/SharePoint interface.

## Final checklist
- [ ] Solution starts from a clean machine using the README.
- [ ] No personal secret is required.
- [ ] Sources, licences and limits are documented.
- [ ] Official, derived and synthetic data are distinguishable.
- [ ] API or export follows the documented contract.
- [ ] Evaluation script runs.
- [ ] Known limitations and regulatory disclaimer are visible.
- [ ] Microsoft 365 integration is demonstrated or documented.
