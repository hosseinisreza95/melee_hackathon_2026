# SOURCES — verified access report (2026-10-09)

Each source below was visited and tested before the collectors were written (the one-off probe scripts were
removed once `src/lpc_regwatch/collectors/` superseded them; every verified URL is recorded here and in `data/source_registry.csv`). "Pilot hit" = LALSTOP CONTANS WG, LALSTOP G46 WG / PRESTOP, LALGUARD M52 OD found.

## Summary

| Source | Region | Access | Format | Status / expiry | Crop | Pest | Dose | Label PDF | Pilot hit | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| CA — Health Canada PPID | North America | open CSV extract, no key | CSV (cp1252) | yes | yes (Sites of Use) | yes (Pests) | **no** (label only) | yes (viewer URL) | 3/3 + PRESTOP | **MVP source 1** |
| US — EPA PPLS | North America | REST JSON, no key | JSON | yes | yes (sites) | yes (pests) | **no** (label only) | yes (direct PDF URL) | 3/3 + PRESTOP | **MVP source 2** |
| FR — ANSES E-Phy open data | Europe | weekly zip, no key | CSV `;` UTF-8 | yes (+ withdrawal date) | yes | yes | **yes** (+ unit, PHI, max apps, BBCH, ZNT) | no (web only) | 3/3 + 6 more Lallemand | **MVP source 3** |
| BR — MAPA open data AGROFIT | Latin America | open CSV, no key, CC-BY | CSV `;` UTF-8 (392 MB) | active only (`SITUACAO`), no dates | yes (CULTURA) | yes (scientific + common name) | **no** (label "bula" only) | no | **0/3 pilots**; 17 other Lallemand products; competitor with Clonostachys (other strain) | **MVP source 4** |
| DE — BVL PSM API | Europe | ORDS REST JSON, no key | JSON | yes | TBD | TBD | TBD | no | CONTANS found | dropped (team decision 2026-10-09) |
| BE — Fytoweb | Europe | SFTP after registration | JSON | — | — | — | — | — | not tested | script only |
| UY — MGAP/DGSA | LATAM | HTML table | HTML | — | — | — | — | — | not tested | post-MVP |
| MX — COFEPRIS | LATAM | source not confirmed by organiser | — | — | — | — | — | — | — | blocked |

Regions covered by MVP: North America (CA, US) + Europe (FR) + Latin America (BR) → 4 sources, 3 regions,
above the "≥ 3 sources, ≥ 2 regions" bar. Germany was dropped by team decision to keep the MVP small.

Brazil is deliberately kept although none of the three pilot products is registered there: it is the
live demonstration of the rule "no result ≠ no registration" (the product is simply not on that market),
it shows Lallemand's different Brazilian portfolio, and it contains a competitor Clonostachys rosea
product with a *different strain* — the textbook case where species match but strain does not.

Important finding for the architecture: **in CA and US the structured data gives status, crops
and pests but not the dose; the dose is only in the label PDF.** France gives everything structured.
So the pipeline needs two extraction paths: deterministic parsers (all three) + LLM label
extraction (CA/US dose), exactly as the challenge's "extraction assistée par IA" expects.

---

## 1. Canada — Health Canada Pesticide Product Information Database (PPID)

- Dataset page: https://open.canada.ca/data/en/dataset/e10b0d6e-04ac-4014-a64a-666c3874bbe0
- Licence: Open Government Licence – Canada. Update frequency: **daily** (02:30–03:30 EST).
- Resource list obtained from the CKAN API (`package_show`), no clicking needed:
  - `https://pest-control.canada.ca/pesticide-registry-api/api/extract/product` (11.1 MB CSV, 21 811 rows, 16 cols)
  - `.../extract/ingredient` (1 316 rows), `.../extract/application` (62 347 rows), `.../extract/label` (index only, 4 cols), `.../extract/incident`, `.../extract/mrl`
  - append `?lang=fr` for French; append `/<registration number>` to filter one product (e.g. `/product/29066`).
  - API guide (HTML) saved to `data/raw/probe/ca_ppid_api_doc.html`.
- Encoding: `application/vnd.ms-excel;charset=WINDOWS-1252` → read with `cp1252`.
- Product columns: `Registration number, Product name - English/French, Registration Status, Expiry date,
  Marketing type, Date first registered, Exclusive period start date, Active ingredients - English/French,
  Product Type, Registrant name, Use Site Category, Sites of Use, Pests, Current / Historical`.
- `Sites of Use` and `Pests` are `;`-separated lists → one `use` row per (site, pest) pair, dose null.
- Status values observed: `Full Registration, Cancelled, Temporary Product, Emergency Registration,
  Limited Term Product, Phase-Out`.
- Pilot hits (registrant `DANSTAR FERMENT AG` = Lallemand):

| Reg. no | Product | Status | Expiry | Active ingredient |
|---|---|---|---|---|
| 29066 | LALSTOP CONTANS WG | Full Registration | 2027-12-31 | Coniothyrium minitans strain CON/M/91-08 |
| 28820 | PRESTOP | Full Registration | 2028-12-31 | Clonostachys rosea strain J1446 |
| 32404 | PRESTOP WG | Full Registration | 2026-12-31 | Clonostachys rosea strain J1446 |
| 30829 | LALGUARD M52 OD | Full Registration | 2031-12-31 | Metarhizium brunneum strain F52 |
| 29147 | LALGUARD M52 GR | Full Registration | 2030-12-31 | Metarhizium brunneum strain F52 |
| 29065 / 28819 / 29146 | technical actives | Full Registration | 2028-12-31 | (same strains) |

- `application` extract gives **history**: 2007 "CONTANS WG" by PROPHYTA, 2006 "Met52 Granular" by
  NOVOZYMES, "GLIOCLADIUM CATENULATUM J1446" by VERDERA → evidence for name/owner changes.
- Label PDF: label search `https://pr-rp.hc-sc.gc.ca/ls-re/result-eng.php?p_search_label=&searchfield1=REGNU&operator1=EXACT&criteria1=29066`
  → detail page → `https://pr-rp.hc-sc.gc.ca/1_1/view_label?p_ukid=441403788` returns `application/pdf`.
  The `p_ukid` must be scraped from the result page (one request per product, acceptable for 6 products;
  the annex says "do not scrape the interface" for bulk — we only fetch the pilot labels and document it).
- Record URL for evidence: `https://pr-rp.hc-sc.gc.ca/ls-re/lbl_detail-eng.php?p_disp_regn='29066'&p_regnum=29066`
  (public detail page, shows status, expiry, active ingredient).
- Failure modes: encoding change, column rename (guard with expected column list), site maintenance window at night EST.

## 2. United States — EPA Pesticide Product Label System (PPLS) API

- Doc page: https://www.epa.gov/pesticide-labels/pesticide-product-label-system-ppls-application-program-interface-api
- No authentication described. Updated **every 12 hours** (noon and midnight EDT). Licence/quota/SLA not stated → documented as limit.
- Endpoints verified (base `https://ordspub.epa.gov/ords/pesticides/cswu`):
  - partial name: `/ProductSearch/partialprodsearch/v2/riname/{text}` → `[{eparegno, productname, product_status, product_status_date, altrntbrndnames}]`
  - ingredient: `/ProductSearch/searchWithIngName/v1/{text}` → products per active ingredient (with `pccode`)
  - full record: `/ppls/{company-product}` → `product_status, formulations, active_ingredients(pc_code, active_ing, percent),
    altbrandnames, inactive_brand_names, transfer_history, pdffiles[], sites[], pests[], types[]`
- Label PDF direct URL: `https://www3.epa.gov/pesticides/chem_search/ppls/{pdffile}` (verified 200, application/pdf).
- Pilot hits (company `DANSTAR FERMENT AG / LALLEMAND PLANT CARE`):

| EPA Reg. no | Product | Status | Alt / inactive brand names | Active ingredient |
|---|---|---|---|---|
| 64137-34 | LALSTOP® CONTANS WG | Active | transferred from 72444-1 (Bayer), 264-1174 | Coniothyrium minitans strain CON/M/91-08 (5 %) |
| 64137-13 | PRESTOP (WG) | Active | alt brand **LALSTOP G46 WG** | Clonostachys rosea strain J1446 (93 %) |
| 64137-11 | PRESTOP | Inactive (2020-12-21) | | Clonostachys rosea strain J1446 |
| 64137-33 | LALGUARD M52 OD | Active | inactive **MET52 EC**, TICK-EX EC; "formerly known as Metarhizium anisopliae" | Metarhizium brunneum Strain F52 (11 %) |
| 64137-31 | LALGUARD® M52 GR | Active | MET52 GRANULAR | Metarhizium brunneum Strain F52 |

- `sites[]` and `pests[]` are flat lists (not paired) → MVP stores them as use rows with `pairing=unknown`
  and a warning; the exact crop↔pest↔dose pairing comes from the label PDF (Step 7).
- Privacy: `companyinfo` contains a named contact person, phone and email → **dropped at ingestion** (cahier §13 Sécurité).
- Failure modes: ORDS pagination (`hasMore`), name search needs exact spelling for some endpoints, status
  of distributor products vs. section-3 products — keep `product_status` only from `/ppls/{regno}`.

## 3. France — ANSES E-Phy open data (data.gouv.fr)

- Dataset: https://www.data.gouv.fr/datasets/donnees-ouvertes-du-catalogue-e-phy-des-produits-phytopharmaceutiques-matieres-fertilisantes-et-supports-de-culture-adjuvants-produits-mixtes-et-melanges
- Licence: Licence Ouverte (fr-lo). Frequency: **weekly**. Last update seen: 2026-10-07.
- Resources resolved via `https://www.data.gouv.fr/api/1/datasets/{slug}/` (no clicking): three zips
  (CSV cp1252, **CSV UTF-8 4.0 MB**, XML 8.6 MB). URL contains the date → the collector must read the API each run.
- Zip members (UTF-8): `produits_utf8.csv` (3.1 MB), `usages_des_produits_autorises_utf8.csv` (8.1 MB),
  `produits_usages_utf8.csv`, `produits_condition_emploi_utf8.csv`, `substance_active_utf8.csv`,
  `produits_phrases_de_risque`, `produits_classe_et_mention_danger`, `mfsc_*`, `permis_de_commerce_parallele`.
- Separator `;`, trailing empty column (`Unnamed: N`) to drop. Dates `dd/mm/yyyy`.
- `produits` columns: `type produit, numero AMM, nom produit, seconds noms commerciaux, titulaire, type commercial,
  gamme usage, mentions autorisees, restrictions usage, Substances actives, fonctions, formulations,
  Etat d'autorisation (AUTORISE | RETIRE), Date de retrait du produit, Date de première autorisation, ...`
- `usages_des_produits_autorises` columns: `identifiant usage lib court` (= crop * treatment * target, e.g.
  `Fraisier*Trt Part.Aer.*Pourriture grise et sclérotinioses`), `identifiant usage`, `date decision`,
  `stade cultural min/max (BBCH)`, `etat usage`, `dose retenue`, `dose retenue unite`, `delai avant recolte jour`,
  `nombre max d'application`, `date fin distribution/utilisation`, `condition emploi`, `ZNT aquatique / arthropodes / plantes (m)`.
  → this is the richest structured use table of the three sources.
- Pilot hits (titulaire `DANSTAR FERMENT AG`), 142 use rows:

| AMM | Product | Second name | Active substance (as written) | First auth. |
|---|---|---|---|---|
| 9900189 | LALSTOP CONTANS WG | | Coniothyrium minitans Souche CON/M/91-08 | 2001-04-06 |
| 2230771 | LALSTOP G46 WG | | Clonostachys rosea souche J1446 | 2024-01-16 |
| 2120177 | PRESTOP | | Clonostachys rosea souche J1446 | 2012-11-05 |
| 2150847 | PRESTOP 4B | | Clonostachys rosea souche J1446 | 2023-01-09 |
| 2230264 | LALFRESH S | | Clonostachys rosea souche J1446 | 2023-05-15 |
| 2150990 | LALGUARD M52 OD | | Metarhizium anisopliae var. anisopliae strain F52 | 2016-08-22 |
| 2110055 | LALGUARD M52 GR | MITAXION G | Metarhizium anisopliae var. anisopliae strain F52 | 2011-04-01 |
| 2140208 / 2260171 | MYCOSTOP / LALSTOP K61 WS | LALSTOP K61 WP | Streptomyces K61 | |

- `substance_active` lists variants: `Gliocladium catenulatum souche J1446 | Clonostachys rosea souche J1446`,
  `Metarhizium brunneum souche Ma 43 | Metarhizium anisopliae var. anisopliae` → official synonym evidence
  that validates several starter-kit `to_verify` rows.
- Record URL for evidence: `https://ephy.anses.fr/ppp/<slug>` is not stable from the CSV; we cite the dataset
  resource URL + AMM number, and the E-Phy search URL `https://ephy.anses.fr/resultats_recherche/<AMM>` as human link.
- Failure modes: weekly file name changes (resolve via API), header typos exist (`tade cultural max`), cp1252 vs UTF-8.
- **Header trap (verified on the 2026-10-08 file):** column `identifiant usage lib court` contains the numeric use code
  (e.g. `11012217`) and column `identifiant usage` contains the text `Culture*Traitement*Cible`. The parser keys on the
  code and parses the text; do not trust the header names.

## 4. Brazil — MAPA open data portal, AGROFIT dataset (official ministry source)

- Dataset: https://dados.agricultura.gov.br/dataset/sistema-de-agrotoxicos-fitossanitarios-agrofit
  (Ministério da Agricultura e Pecuária). Licence: **Creative Commons Attribution**. Modified 2026-10-09.
- Resolved via CKAN API `package_search?q=agrofit` → two resources:
  - `Produto Formulado` → `.../download/agrofitprodutosformulados.csv` (392 MB, 280 058 rows, 15 cols)
  - `Produto Técnico` → `.../download/agrofitprodutostecnicos.csv`
- Columns: `NR_REGISTRO, MARCA_COMERCIAL, FORMULACAO, INGREDIENTE_ATIVO, TITULAR_DE_REGISTRO, CLASSE, MODO_DE_ACAO,
  CULTURA, PRAGA_NOME_CIENTIFICO, PRAGA_NOME_COMUM, EMPRESA_PAIS_TIPO, CLASSE_TOXICOLOGICA, CLASSE_AMBIENTAL, ORGANICOS, SITUACAO`.
  One row per product × crop × pest → already a use table (no dose). `INGREDIENTE_ATIVO` embeds strain and
  concentration in free text, e.g. `Clonostachys rosea, cepa CPQBA 040-11 DRM 07 (Produto Microbiológico) (200 g/kg)`.
- `SITUACAO` is `TRUE` for every row → the file lists **active registrations only**; withdrawn products are absent,
  not flagged. Consequence: a product missing from this file gets `not_found`, never `withdrawn`.
- No dates (approval / expiry) in the open file → `approval_date = null`, warning "not in structured source".
- Embrapa AgroAPI (https://www.portal.agroapi.cnptia.embrapa.br/api-docs/agrofit/v1, base `https://api.cnptia.embrapa.br/agrofit/v1`)
  is a *derived* service: its FAQ states the data comes from this same open-data portal. Free plan: 100 000
  requests/month after creating an application. **Not needed** — the ministry CSV is the primary official source.
- Pilot hits: none of LALSTOP CONTANS WG / LALSTOP G46 WG / LALGUARD M52 OD. Lallemand Brazil
  (`Lallemand Solucoes Biologicas Ltda - Piracicaba/SP`) has 17 products (e.g. Lalstop K61 WS, Lalstop Organic DS,
  Lalguard C99 WP, Opala with *Metarhizium anisopliae* IBCB 425, ANT-03/BioTitan). Competitor example:
  `Kamoi Pro; BioRoof` (Agrivalle) with *Clonostachys rosea* strain CPQBA 040-11 — same species as G46, different strain.
- Failure modes: file size (392 MB) → stream to disk, parse with `usecols`; encoding UTF-8 with BOM; `;` separator;
  trailing spaces in names; CKAN resource ids may change → always resolve via `package_search`.

## 4b. Germany — BVL PSM API (dropped, kept for reference)

- Swagger UI at https://psm-api.bvl.bund.de/ ; ORDS REST at `https://psm-api.bvl.bund.de/ords/psm/api-v1/`.
- Verified: `GET /ords/psm/api-v1/mittel/?q={"mittelname":{"$like":"%CONTANS%"}}` → `LALSTOP CONTANS WG`,
  `kennr 034346-00`, `zul_erstmalig_am 2019-07-31`, `zul_ende 2033-07-30`, `formulierung_art WG`.
- Licence: Datenlizenz Deutschland Namensnennung 2.0 (attribution). Quotas not documented.
- Uses (`awg`, `awg_kultur`, `awg_schadorg`, `awg_aufwand`) exist in this API family → to explore if time permits.

## 5. Sources needing the user's help

- **Brazil**: resolved — ministry open data needs no account (see §4). Embrapa API free plan exists but is unnecessary.
- **Belgium — Fytoweb Data**: SFTP after registration, foreign IP must be whitelisted. Same rule. Low priority.
- **Mexico — COFEPRIS**: organiser says "URL to be validated by local Regulatory" → blocked, documented as such.

## 6. Failure modes handled generically

| Situation | Behaviour |
|---|---|
| Source unreachable | collector records `snapshot.status=failed`; API answers from last good snapshot and adds warning `source_unavailable` |
| Column added/renamed | `SchemaDriftError`, run stops for that source, raw file kept for re-parse |
| Record disappears between snapshots | previous row marked `obsolete`, `change_log` entry |
| Value changes | `change_log` entry (old, new, from/to snapshot) |
| Restricted data | script delivered, no raw data committed |
