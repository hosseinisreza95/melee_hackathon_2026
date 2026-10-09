# Source attribution (template of `attribution_template.md` filled for each MVP source)

## CA-PPID
- Source organization: Health Canada — Pest Management Regulatory Agency (PMRA)
- Dataset/service: Pesticide Product Information Database (PPID) open-data extracts
- Official URL: https://open.canada.ca/data/en/dataset/e10b0d6e-04ac-4014-a64a-666c3874bbe0
- Record URL: `https://pr-rp.hc-sc.gc.ca/ls-re/lbl_detail-eng.php?p_disp_regn='<regno>'&p_regnum=<regno>`
- Licence/version: Open Government Licence – Canada; extracts refreshed daily
- Required attribution: "Contains information licensed under the Open Government Licence – Canada."
- Collection time UTC: per snapshot (`snapshots.collected_at`, `.meta.json` next to each file)
- Access method: HTTP download of `/api/extract/product|ingredient|application|label`
- Transformations: cp1252 decoding; status mapped via `data/status_mapping.csv`; sites/pests split on `;` (lists kept unpaired); historical names from the application extract
- Known exclusions/limits: dose not in the extract (label PDF only); technical actives and manufacturing concentrates skipped
- Validation owner/status: Regulatory Affairs; all rows `automatically_extracted`

## US-EPA-PPLS
- Source organization: United States Environmental Protection Agency (EPA)
- Dataset/service: Pesticide Product Label System (PPLS) API + label PDFs
- Official URL: https://www.epa.gov/pesticide-labels/pesticide-product-label-system-ppls-application-program-interface-api
- Record URL: `https://ordspub.epa.gov/ords/pesticides/cswu/ppls/<regno>`; labels `https://www3.epa.gov/pesticides/chem_search/ppls/<file>.pdf`
- Licence/version: US federal public data (terms not stated); refreshed every 12 h
- Required attribution: "Source: US EPA PPLS, collected <date>."
- Collection time UTC: per snapshot
- Access method: REST JSON (partial-name search, ingredient search, full record), PDF download for pilot labels only
- Transformations: contact-person fields redacted at ingestion; sites/pests kept as unpaired lists; alt/inactive brand names → aliases; label PDFs → AI-extracted uses flagged `llm_pdf`
- Known exclusions/limits: no dates in the record (status date only); quotas/SLA unknown; very granular site lists
- Validation owner/status: Regulatory Affairs; all rows `automatically_extracted`

## FR-EPHY
- Source organization: ANSES (Agence nationale de sécurité sanitaire de l'alimentation, de l'environnement et du travail)
- Dataset/service: Données ouvertes du catalogue E-Phy (data.gouv.fr)
- Official URL: https://www.data.gouv.fr/datasets/donnees-ouvertes-du-catalogue-e-phy-des-produits-phytopharmaceutiques-matieres-fertilisantes-et-supports-de-culture-adjuvants-produits-mixtes-et-melanges
- Record URL: the dated zip resource URL (changes weekly) + AMM number; human lookup https://ephy.anses.fr
- Licence/version: Licence Ouverte / Open Licence (fr-lo); weekly file (last seen 2026-10-07)
- Required attribution: "Source : ANSES, catalogue E-Phy, données ouvertes, collectées le <date>. Les décisions officielles prévalent."
- Collection time UTC: per snapshot
- Access method: data.gouv.fr dataset API → current UTF-8 CSV zip
- Transformations: `;` CSV decoding; `identifiant usage` text split on `*` into crop / treatment / target; dose, unit, DAR, BBCH, ZNT kept as written; second commercial names → aliases
- Known exclusions/limits: header names misleading (documented); withdrawn products have no use rows
- Validation owner/status: Regulatory Affairs; all rows `automatically_extracted`

## BR-AGROFIT
- Source organization: Ministério da Agricultura e Pecuária (MAPA)
- Dataset/service: Sistema de Agrotóxicos Fitossanitários — AGROFIT, open data (CKAN)
- Official URL: https://dados.agricultura.gov.br/dataset/sistema-de-agrotoxicos-fitossanitarios-agrofit
- Record URL: the resource download URL + `NR_REGISTRO`
- Licence/version: Creative Commons Attribution; dataset modified 2026-10-09
- Required attribution: "Fonte: MAPA — AGROFIT, dados abertos (CC-BY), coletados em <data>."
- Collection time UTC: per snapshot
- Access method: CKAN `package_search` → CSV download (392 MB, streamed)
- Transformations: UTF-8-BOM `;` CSV read in chunks; one use per crop × pest row; several brand names per registration split on `/` and `;`
- Known exclusions/limits: active registrations only (`SITUACAO=TRUE`), no dates, no dose; absence from the file is not a withdrawal
- Validation owner/status: Regulatory Affairs; all rows `automatically_extracted`
