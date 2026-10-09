# État d'avancement — Agent IA de veille réglementaire (défi Lallemand Plant Care)

Date : 9 octobre 2026 · Dépôt : `melee_hackathon_2026` · Branche : `main`

Ce document résume ce qui a été fait jusqu'ici, pourquoi, et ce qu'il reste à faire. Il est écrit pour
l'équipe. Les détails techniques sont dans `docs/SPEC.md`, `docs/PLAN.md`, `docs/SOURCES.md` et `docs/DATA_MODEL.md`.

---

## 1. Le défi en cinq lignes

Lallemand Plant Care (LPC) vend des produits de biocontrôle à base de micro-organismes. Les homologations de
ces produits sont dispersées dans des bases nationales (Canada, États-Unis, Brésil, France, …) aux formats,
langues et nomenclatures différents. Le défi : un **prototype d'agent IA** qui collecte ces sources officielles,
les structure dans un **référentiel unique, traçable et interrogeable en langage naturel**, et permet de
comparer produit × pays × usage (culture, cible, dose, restrictions). Durée : 30 h. Livrable : un dépôt Git
relançable depuis le README, avec une intégration Microsoft 365 démontrée ou documentée.

Seuil minimum imposé : **≥ 3 sources officielles, ≥ 2 régions**, tableau de comparaison avec source et date,
au moins une correspondance « produit sœur » présentée comme hypothèse, aucune donnée inventée, valeur
originale conservée à côté de la valeur normalisée.

## 2. Décisions de périmètre (prises le 9 octobre)

| Décision | Choix | Pourquoi |
|---|---|---|
| Sources MVP | **Canada (PPID), États-Unis (EPA PPLS), France (E-Phy), Brésil (AGROFIT)** | 4 sources, 3 régions (Amérique du Nord, Europe, Amérique latine), toutes en accès libre sans compte |
| Allemagne (BVL) | écartée | l'API répond sans clé, mais on garde le MVP petit ; documentée dans `docs/SOURCES.md` |
| Mexique, Belgique, Uruguay | hors MVP | Mexique : source non confirmée par l'organisateur ; Belgique : SFTP sur inscription ; Uruguay : HTML |
| Produits pilotes | LALSTOP CONTANS WG, LALSTOP G46 WG, LALGUARD M52 OD | imposés par la fiche défi |
| Produits concurrents | tout produit dont le micro-organisme est l'une des espèces pilotes | répond à « quels concurrents sont autorisés sur telle culture » |
| Fournisseur d'IA | n'importe quel endpoint compatible OpenAI, choisi par `.env` | exigence « fournisseur interchangeable, aucune clé personnelle » |
| Base de données | SQLite en développement, PostgreSQL sur le serveur de l'équipe | même modèle SQLAlchemy, seule `DATABASE_URL` change |

## 3. Ce qui est fait

### Étape 0 — Cadrage, spécification, modèle de données (commit `ee16946`)

- Le **kit de démarrage** de LPC (schéma canonique, dictionnaire de champs, contrat OpenAPI, mappings EPPO,
  rubrique d'évaluation, évaluateur automatique) est fusionné à la racine du dépôt, structure intacte.
- `docs/SPEC.md` : chaque exigence de la fiche défi, du cahier des charges et de la rubrique est reliée à un
  composant du code et à un test. 8 critères MVP, 8 règles de gouvernance, 6 règles de sécurité, 9 fonctions,
  5 questions « gold », 5 règles de normalisation.
- `docs/PLAN.md` : 8 étapes, chacune avec un test de sortie.
- `docs/SOURCES.md` : chaque source a été **visitée et testée réellement** (téléchargement, colonnes, présence des
  produits pilotes, licence, limites). Scripts de sondage conservés dans `scripts/probe/`.
- **Modèle de données** (`src/lpc_regwatch/db/models.py`) : 9 tables. Cinq reprennent exactement les CSV du kit
  (`sources`, `products`, `product_aliases`, `registrations`, `uses`) ; quatre ajoutent la traçabilité demandée :
  `snapshots` (une par exécution de collecte), `raw_documents` (chaque fichier téléchargé avec URL, date, sha256),
  `change_log` (différences entre deux collectes, bonus), `review_log` (chaque changement de statut de validation
  par un humain). Sur `registrations` et `uses`, les colonnes source, URL, date de collecte et statut sont
  **obligatoires au niveau du schéma** — une ligne sans preuve est refusée par la base.
- `scripts/init_db.py`, `infra/docker-compose.yml` (PostgreSQL), `requirements.txt`, `.env.example`.

### Étape 1 — Collecteurs et stockage des preuves brutes (commit `46182fa`)

- `BaseCollector` : chaque fichier est écrit tel quel dans `data/raw/<source>/<horodatage UTC>/` avec un fichier
  `.meta.json` (URL, date, sha256, taille, type). Une ligne `snapshots` par exécution (`ok` / `failed`), une
  ligne `raw_documents` par fichier. **Garde contre les changements de structure** : si une colonne ou une clé
  sur laquelle on s'appuie disparaît, l'exécution est enregistrée en échec avec la raison, et aucune donnée
  fausse n'est produite. Les colonnes nouvelles sont seulement notées.
- Quatre collecteurs :
  - **Canada** : extraits CSV `product`, `ingredient`, `application` (historique des noms et titulaires), `label`.
  - **États-Unis** : découverte par nom partiel et par ingrédient, puis fiche JSON complète par numéro EPA ;
    téléchargement des PDF d'étiquette **uniquement pour les produits pilotes** (6 PDF). Les champs de contact
    nominatifs (personne, téléphone, e-mail) sont **caviardés avant écriture sur disque** (règle sécurité du cahier).
  - **France** : l'URL du zip hebdomadaire change chaque semaine ; le collecteur interroge l'API data.gouv.fr
    pour obtenir la ressource courante.
  - **Brésil** : l'URL est résolue via l'API CKAN du portail du ministère ; le CSV de 392 Mo est streamé sur disque.
- `src/lpc_regwatch/pilots.py` : les termes de recherche (10 noms commerciaux, 5 espèces) sont **lus dans les
  CSV du kit**, pas codés en dur.
- Résultat réel : CA 4 fichiers / 28,9 Mo ; US 44 JSON + 6 PDF / 4,2 Mo ; FR zip / 4,0 Mo ; BR CSV / 392 Mo.
  Une première exécution US a échoué (l'API renvoie `{"items": []}` pour un vieux numéro) : le snapshot en
  échec est **conservé volontairement** comme preuve du comportement ; la cause est corrigée (« fiche vide » ≠
  « format changé »).

### Étape 2 — Parseurs déterministes, chargement, export au contrat du kit (commit `72ac489`)

- `parsers/base.py` : chaque ligne porte source, URL, date de collecte, snapshot, document brut, méthode
  d'extraction et un **extrait de preuve** construit à partir de la ligne source. Les valeurs originales sont
  copiées telles quelles ; seul le statut est normalisé, via la table versionnée `data/status_mapping.csv`.
  L'identité des produits pilotes vient de `data/product_name_mapping.csv` (noms canoniques et historiques) ;
  tout autre produit reçoit un identifiant déterministe. **Les candidats « produit sœur » ne sont jamais fusionnés ici.**
- Quatre parseurs, chacun documentant ce que la source affirme réellement :
  - **Canada** : statut, expiration, première homologation, titulaire, matière active. `Sites of Use` et `Pests`
    sont deux listes indépendantes → une ligne d'usage par culture, liste des cibles en texte, `pairing=unpaired_lists`,
    dose absente (étiquette seulement). L'extrait `application` donne les **noms historiques** (CONTANS WG déposé
    par PROPHYTA en 2007, Met52 par NOVOZYMES en 2006).
  - **États-Unis** : statut, formulation, matières actives avec %, noms de marque alternatifs et inactifs
    (officiels), historique de transfert, listes `sites` / `pests` non appariées, dose absente.
  - **France** : la seule source MVP avec **doses structurées** (dose, unité, DAR, nombre max d'applications,
    stades BBCH, ZNT, conditions), `pairing=source_paired`. Seconds noms commerciaux → alias officiels.
  - **Brésil** : une ligne par produit × culture × cible, actifs seulement (`SITUACAO=TRUE`), pas de dates ni
    de dose ; plusieurs noms par numéro d'enregistrement → alias.
- `loader.py` : chargement idempotent ; export de `data/products.csv`, `product_aliases.csv`,
  `registrations.csv`, `uses.csv` **dans l'ordre de colonnes du kit** ; `scripts/validate_data.py` de
  l'organisateur passe sur l'export réel.

Résultat réel (snapshots du 9 octobre) :

| Source | Enregistrements | Usages | Dose structurée | Produits pilotes trouvés |
|---|---|---|---|---|
| Canada | 17 | 300 | non | 3/3 (+ PRESTOP, PRESTOP WG, M52 GR) |
| États-Unis | 29 | 5 438 | non | 3/3 (+ PRESTOP, M52 GR, K61, B33, …) |
| France | 15 | 144 | **oui** | 3/3 (+ 6 autres produits Lallemand) |
| Brésil | 171 | 454 | non | **0/3** (17 autres produits Lallemand ; concurrents même espèce) |
| **Total** | **232** | **6 336** | | 219 produits, 122 alias avec preuve |

Tests : 13 tests `pytest` verts (schéma, collecteurs hors-ligne avec transport simulé, parseurs sur fixtures,
aller-retour chargement/export). Évaluateur automatique de l'organisateur : 70/70 sur l'exemple.

## 4. Découvertes importantes

1. **Au Canada et aux États-Unis, la dose n'est pas dans les données structurées** : elle n'existe que dans le PDF
   d'étiquette. La France donne tout en structuré. C'est exactement là que l'« extraction assistée par IA » se
   justifie : lire ~6 PDF d'étiquette pilotes, pas remplacer les parseurs.
2. **Un même produit porte trois noms principaux** : France « LALSTOP G46 WG » (AMM 2230771), Canada « PRESTOP WG »
   (n° 32404), États-Unis « PRESTOP (WG) » (64137-13) dont le champ officiel `altbrandnames` dit
   « LALSTOP G46 WG ». Aujourd'hui ce sont deux identifiants produit. Règle retenue pour l'étape 3 : un nom
   alternatif officiel **sur le même enregistrement** est une équivalence (preuve), pas une hypothèse ; « PRESTOP »
   (poudre mouillable, autre formulation) reste un candidat « produit sœur » à confirmer.
3. **Synonymes taxonomiques fournis par les sources officielles** : l'EPA écrit « Metarhizium brunneum (formerly
   known as Metarhizium anisopliae) » ; E-Phy liste « Gliocladium catenulatum souche J1446 | Clonostachys rosea
   souche J1446 ». Cela validera plusieurs lignes `to_verify` du kit.
4. **Brésil : aucun produit pilote n'y est enregistré.** C'est la démonstration vivante de la règle « absence de
   résultat ≠ absence d'homologation ». Le fichier ne liste que les produits actifs : un produit absent ne peut pas
   être marqué « retiré ». Un concurrent (Kamoi Pro, Agrivalle) a la même espèce que G46 (*Clonostachys rosea*)
   mais une **autre souche** — cas d'école pour montrer que la souche compte.
5. **Piège d'en-tête E-Phy** : la colonne `identifiant usage lib court` contient le **code numérique** et la colonne
   `identifiant usage` contient le **texte** `Culture*Traitement*Cible`. Le test unitaire, écrit d'après les noms,
   passait ; l'erreur n'est apparue qu'en vérifiant les données réelles. Corrigé et documenté. Leçon : vérifier
   chaque étape sur les vraies données, pas seulement sur les fixtures.
6. **Vie privée** : la fiche EPA contient nom, téléphone et e-mail d'une personne de contact. Ces champs sont
   remplacés par `[redacted]` avant stockage ; le nom de l'entreprise est conservé (fait réglementaire).

## 5. Où sont les données

| Couche | Emplacement | Dans Git ? | Reconstruction |
|---|---|---|---|
| Preuves brutes (fichiers officiels + `.meta.json`) | `data/raw/<source>/<horodatage>/` (≈ 420 Mo) | non | `python scripts/collect.py --source all` |
| Base canonique | `data/lpc_regwatch.sqlite` (7 Mo, 9 tables) | non | `python scripts/init_db.py` puis `parse.py` |
| Export au contrat du kit | `data/products.csv`, `product_aliases.csv`, `registrations.csv`, `uses.csv` | **oui** | `python scripts/parse.py --source all` |

## 6. Relancer depuis une machine propre

```bash
uv pip install -r requirements.txt      # ou pip install -r requirements.txt
cp .env.example .env                     # aucune clé nécessaire pour collecter/parser
python scripts/init_db.py
python scripts/collect.py --source all   # ~10 min, 420 Mo (le Brésil fait 392 Mo)
python scripts/parse.py --source all     # charge la base, exporte les CSV, lance validate_data.py
pytest
```

## 7. Structure du dépôt (ce qui est à nous)

```
docs/            SPEC.md (exigences→composants→tests), PLAN.md, SOURCES.md, DATA_MODEL.md, AVANCEMENT_FR.md
src/lpc_regwatch/
  config.py      lecture de .env (DATABASE_URL, AI_PROVIDER, AI_MODEL, AI_API_KEY, AI_BASE_URL)
  pilots.py      termes de recherche dérivés des CSV du kit
  db/            models.py (9 tables), session.py (SQLite/PostgreSQL)
  collectors/    base.py + ca_ppid, us_epa_ppls, fr_ephy, br_agrofit
  parsers/       base.py + ca_ppid, us_epa_ppls, fr_ephy, br_agrofit
  loader.py      chargement idempotent + export CSV
scripts/         init_db.py, collect.py, parse.py, probe/ (sondages), + scripts du kit
tests/           test_db.py, test_collectors.py, test_parsers.py (+ test du kit)
infra/           docker-compose.yml (PostgreSQL)
data/            CSV du kit (mappings, dictionnaire) + export réel + status_mapping.csv
```

## 8. Prochaines étapes (voir `docs/PLAN.md`)

| Étape | Contenu | Point d'attention |
|---|---|---|
| 3 — Normalisation et correspondances | codes EPPO culture/cible via les CSV du kit (multilingue), unités converties seulement si exactes, fusion des produits avec nom alternatif officiel sur le même enregistrement, candidats « sœurs » = même espèce + même souche | les noms de culture US ont un contexte entre parenthèses, les noms FR sont des groupes de cultures ; ce qui n'est pas mappé reste `to_verify`, honnêtement |
| 4 — API | FastAPI selon `schema/openapi.yaml` : `/products`, `/compare`, `/ask` (résolution d'entités → outils SQL prédéfinis → réponse construite uniquement à partir des lignes, avec `evidence[]`, `warnings[]`, `disclaimer`) | pas de recherche web libre ; tests des 5 questions « gold » ; `submission.json` → évaluateur |
| 5 — Interface | Streamlit, **client léger de l'API** : tableau produit × pays × usage avec badge de statut, lien source et date par cellule ; panneau détail original/normalisé ; zone de question ; export CSV/Excel | l'UX ne vaut que 5 % de la note ; pas de KPI décoratifs |
| 6 — Microsoft 365 | OpenAPI → connecteur personnalisé Power Platform + action Copilot Studio ; ou flux Power Automate sur l'export CSV | 15 % de la note ; à démontrer avec captures |
| 7 — Extraction IA des étiquettes | PDF (PyMuPDF) → LLM avec schéma JSON strict → lignes d'usage avec dose, `extraction_method=llm_pdf`, confiance, extrait de preuve ; cache par sha256 | ~6 PDF pilotes seulement ; 20 champs vérifiés à la main |
| 8 — Packaging | docker-compose (api, ui, db) sur le serveur de l'équipe ; README vérifié sur machine propre ; limites connues, procédure de validation Regulatory Affairs, chemin vers la production | |

Bonus si tout est vert : détection des changements entre snapshots, alertes d'expiration, carte, empreinte concurrent.

## 9. Décisions ouvertes pour l'équipe

1. Garder les ~150 concurrents brésiliens à base de *Metarhizium anisopliae* ? Proposition : oui, filtrés par
   défaut dans l'interface.
2. Committer le fichier SQLite (7 Mo) pour que le jury puisse lancer la démo sans télécharger 420 Mo ?
3. Répartition des rôles pour les étapes 3 à 6 (données / IA / API / interface / M365 / présentation).

## 10. Règles de travail dans le dépôt

- Une branche par fonctionnalité, commits clairs ; `main` reste exécutable.
- Jamais de secret dans Git (`.env` est ignoré). Aucune clé n'est nécessaire avant l'étape 4.
- Après tout changement de parseur : `python scripts/parse.py --source all` doit se terminer par `VALIDATION PASSED`.
- Toute nouvelle source : une ligne dans `data/source_registry.csv` et une section dans `docs/SOURCES.md`.
- Ne jamais modifier une valeur `*_original` ; ne jamais passer un statut à `validated` sans revue humaine tracée.
