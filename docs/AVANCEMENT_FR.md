# Rapport d'avancement — Agent IA de veille réglementaire (défi Lallemand Plant Care)

Date : 10 octobre 2026 · Dépôt : `melee_hackathon_2026` · Branche : `main` · Démo : http://37.187.176.97/ (UI) · http://37.187.176.97/api/docs (API) · http://37.187.176.97/pitch/ (pitch)

Ce document est écrit pour l'équipe : ce qui a été fait, les problèmes rencontrés, les solutions retenues et **pourquoi**.
Les détails techniques sont dans `docs/SPEC.md` (exigence → composant → test), `docs/ARCHITECTURE.md`, `docs/SOURCES.md`,
`docs/NORMALIZATION.md`, `docs/EVAL.md`, `docs/LIMITATIONS.md`, `docs/RA_VALIDATION_PROCEDURE.md`, `docs/LPC_QA.md`.

---

## 1. Le défi en cinq lignes

Lallemand Plant Care (LPC) vend des produits de biocontrôle à base de micro-organismes. Leurs homologations sont dispersées dans
des bases nationales aux formats, langues et nomenclatures différents. Le défi : un **prototype d'agent IA** qui collecte ces sources
officielles, les structure dans un **référentiel unique, traçable, interrogeable en langage naturel**, et compare produit × pays × usage
(culture, cible, dose, restrictions). Seuil : ≥ 3 sources officielles, ≥ 2 régions, tableau de comparaison avec source et date, au moins une
correspondance « produit sœur » présentée comme hypothèse, intégration Microsoft 365 démontrée ou documentée, dépôt relançable depuis le
README sans clé personnelle, aucune donnée inventée, valeur originale conservée à côté de la valeur normalisée.

## 2. État final : tout est livré et déployé

| Livrable | État | Où |
|---|---|---|
| 4 sources officielles, 3 régions (CA, US, FR, BR) | ✅ collectées, parsées, normalisées | `src/lpc_regwatch/collectors`, `parsers`, `docs/SOURCES.md` |
| Base canonique avec preuve sur chaque ligne | ✅ 232 enregistrements, 6 410 usages, 140 noms/relations, 9 tables | PostgreSQL (serveur), SQLite (dev) |
| Normalisation (statut, EPPO, unités, taxonomie, identité produit) | ✅ exacte seulement, tout est flaggé | `src/lpc_regwatch/normalize`, `matching.py`, `docs/NORMALIZATION.md` |
| API conforme au contrat du kit + extensions | ✅ `/health /products /registrations /compare /ask` + liés, qualité, échéances, changements, revue, export | `src/lpc_regwatch/api`, `/api/docs` |
| Agent `/ask` ancré, sans clé et avec clé | ✅ planificateur déterministe + outils ; réponse **structurée Pydantic** (titre, lignes utiles, points d'attention) ; LLM optionnel + garde-fou ; FR / EN / PT | `api/ask.py`, `api/answer_model.py` |
| Extraction IA des étiquettes (dose CA/US) | ✅ 74 lignes acceptées / 11 rejetées, extrait vérifié mot pour mot | `extract/label_llm.py`, `docs/EVAL.md` |
| Interface (vue d'ensemble cartographique, comparaison, carte, question, revue, veille, registre interne, sources) | ✅ client léger de l'API, identité visuelle Lallemand Plant Care (logo, ardoise, rouge), carte interactive (clic pays / pastilles), **trois langues (FR, EN, PT)** testées page par page en mode headless | `src/lpc_regwatch/ui/app.py`, `ui/i18n.py`, `.streamlit/config.toml` |
| Microsoft 365 | ✅ connecteur Swagger 2.0 généré + flux Power Automate + action Copilot Studio + design Entra ID (documenté, pas de tenant) | `m365/` |
| Modèle cible Dataverse (« qui fait foi ») | ✅ 8 tables `lpc_*` exportées (zip CSV, Excel, JSON), validées automatiquement contre `dataverse_tables.xlsx` | `src/lpc_regwatch/dataverse.py`, `docs/DATAVERSE_MAPPING.md` |
| Registre interne LPC (liste SharePoint) | ✅ structure reçue, normalisation + rapprochement avec les sources officielles, échantillon fictif, page UI et API d'upload | `src/lpc_regwatch/registry/`, `schema/registre_interne_colonnes_LPC.md` |
| Déploiement production | ✅ Docker Compose (PostgreSQL, API, UI, Caddy), cron quotidien, pare-feu, secrets hors Git | `infra/`, serveur 37.187.176.97 |
| Tests | ✅ 66 tests verts en local **et** dans le conteneur de production (PostgreSQL + fichiers officiels réels) | `tests/` |
| Évaluation de chaque étape | ✅ `scripts/evaluate_pipeline.py` : collecte, parseurs (0 violation de traçabilité), normalisation, correspondances, étiquettes IA, `/ask` avec et sans LLM (13/13), évaluateur 70/70 | `docs/EVAL.md`, `output/evaluation_report.json` |
| Évaluateur de l'organisateur | ✅ 70 / 70 (local et pipeline serveur) | `scripts/build_submission.py` |
| Pitch | ✅ 10 diapositives HTML animées, autonomes, en français | `presentation/index.html`, `/pitch/` |

## 3. Ce que nous avons appris de LPC en cours de route (et appliqué)

Nous avons envoyé six questions à LPC ; leurs réponses du 10 octobre ont changé trois choses (détail dans `docs/LPC_QA.md`) :

1. **Tout doit marcher sans clé** et ils testeront **d'autres produits, pays et cultures** avec les mêmes intentions → mode sans clé
   complet et planificateur rendu générique (cultures via l'index EPPO multilingue, espèces lues dans la base, produits par tous les noms et
   alias). Test `test_other_products_countries_and_crops_like_the_jury_will`.
2. **PRESTOP WG (Canada 32404) n'est pas LALSTOP G46 WG** ; LALFRESH S non plus (AMM distincte, post-récolte) ; PRESTOP est bien un produit
   sœur ; MITAXION G est confirmé comme second nom de M52 GR en France. Nous avions fusionné PRESTOP WG sous G46 parce que l'enregistrement
   canadien et le dossier EPA portent littéralement le nom « LALSTOP G46 WG ». **Nous avons défait la fusion** : la relation devient
   `related_product`, le produit reste distinct, ses enregistrements s'affichent **à côté** de G46 avec la preuve. Les réponses de LPC sont
   stockées comme **données** (`data/lpc_curated_relations.csv`), appliquées en dernier, visibles dans l'API avec leur preuve.
3. Un connecteur prêt à importer avec sa documentation suffit pour M365 ; le kit ne contient aucun piège ; `12522-00001-F-1-WG` est un code d'essai.
4. **Deux fichiers ajoutés au kit le 10/10** : la structure du registre interne (liste SharePoint, 22 colonnes « avec leurs imperfections ») et
   `dataverse_tables.xlsx`, le modèle cible qui fait foi. Nous exportons la base dans ce modèle (8 tables, validées colonne par colonne contre le
   classeur) et nous rapprochons un export du registre avec les sources officielles : pays en toutes lettres → ISO, « 12/31/2999 » → sans échéance,
   « No registration number » → vide + drapeau, statut commercial séparé du statut réglementaire, actifs en texte libre → espèce + souche,
   « Crops / Target / Application rate » gardé comme marketing et jamais transformé en usages. Chaque ligne sort avec l'enregistrement officiel
   trouvé (par numéro, sinon par nom), les accords, les écarts et la preuve. Deux manques du modèle cible signalés à LPC : `registration_holder`
   et la relation `related_product`.

## 4. Chronologie des étapes

| Étape | Contenu | Commit |
|---|---|---|
| 0 | Kit fusionné, SPEC (exigence → composant → test), sources vérifiées, modèle de données 9 tables | `ee16946` |
| 1 | Collecteurs + preuves brutes (`.meta.json`, sha256), snapshots, garde anti-dérive de schéma | `46baf93` |
| 2 | Parseurs déterministes, loader, export au contrat du kit (validateur OK) | `72ac489` |
| 3–4 | Normalisation, correspondances, détection de changements, API, `/ask` ancré, extraction d'étiquettes | `65acb93` |
| 5–6–8 | UI Streamlit, connecteur M365, docs infra, tests aveugles sur données réelles | `ec1d6ca` |
| Déploiement | Dockerfile, compose, Caddy, cron, serveur nettoyé et reconstruit | `030f05d` → `257a147` |
| Réponses LPC | produits liés au lieu de fusions, relations curées, questions génériques, gpt-5 | `66a3f02` |
| Final | EVAL, rapport, pitch, chiffres finaux | dernier commit de `main` |

## 5. Problèmes rencontrés, solutions, et pourquoi

| # | Problème | Solution | Pourquoi ce choix |
|---|---|---|---|
| 1 | **Dose absente des données structurées** au Canada et aux États-Unis (seulement dans le PDF d'étiquette). | Deux chemins : parseurs déterministes pour tout ; LLM uniquement pour les PDF, avec un **garde-fou à trois niveaux** (extrait verbatim / début d'extrait + culture + dose vérifiés / rejet). Lignes marquées `llm_pdf`, `llm_paired`, confiance plafonnée à 0,7 si vérification partielle. | Le cahier interdit d'inventer : une ligne IA n'entre que si le PDF contient littéralement ce qu'elle cite. Perdre 11 lignes vaut mieux qu'en fausser une. |
| 2 | **Premier garde-fou trop strict** : l'étiquette PRESTOP WG (34 pages, tableaux) avait 17/17 lignes rejetées car le modèle réordonnait les cellules. | Niveau « partiel » ajouté ; sortie brute du modèle mise en cache par sha256 pour re-jouer le garde-fou sans repayer l'extraction. | Séparer « ce que le modèle a dit » de « ce que nous acceptons » rend le filtre auditable et améliorable à coût nul. |
| 3 | **Un même produit sous trois noms** (G46 / PRESTOP WG / PRESTOP (WG)) : nous avions fusionné sur la foi des noms alternatifs officiels. LPC : ce sont des produits distincts. | Fusion supprimée ; relation `related_product` ; décisions LPC en CSV versionné ; `/compare` et la carte montrent « produit absent mais produit lié présent ». | L'autorité produit prime sur l'inférence ; mais l'information officielle (le nom figure sur l'enregistrement) reste visible comme preuve, pas comme identité. |
| 4 | **Collecteur US emballé sur le serveur** : les termes de recherche étaient dérivés du fichier d'alias exporté, qui contenait « STRAIN », « TECHNICAL », « POWDER » → des milliers de dossiers EPA. | Termes limités aux noms curés du kit + liste de mots génériques exclus ; test de régression. | Une sortie du pipeline ne doit jamais être une entrée du pipeline : boucle de rétroaction incontrôlée. |
| 5 | **PostgreSQL refuse ce que SQLite acceptait** : `VARCHAR(60)` dépassé par des identifiants d'alias longs. | Colonnes élargies aux longueurs observées ; test sur les longueurs ; base recréée. | Tester en dev sur SQLite ne suffit pas ; la suite complète tourne désormais dans le conteneur de production. |
| 6 | **En-têtes trompeurs dans E-Phy** : la colonne « identifiant usage lib court » contient le code numérique, « identifiant usage » le texte. Le test unitaire passait, la donnée réelle non. | Correction + documentation dans le parseur et `docs/SOURCES.md` ; tests « aveugles » qui relisent les fichiers officiels sans nos parseurs. | Vérifier chaque étape sur les vraies données, pas seulement sur des fixtures. |
| 7 | **Clé OpenAI locale invalide (401)** ; une clé valide existait dans l'ancien déploiement du serveur. | Copiée côté serveur uniquement (jamais affichée), `.env` en `chmod 600`, jamais dans Git ; tout le travail IA s'exécute sur le serveur. | La clé ne doit pas être exposée ; le dépôt reste utilisable sans clé. |
| 8 | **Modèles gpt-5 / gpt-5-mini** (demande de l'équipe) : API différente (`max_completion_tokens`, température fixe). | Client adapté par préfixe de modèle ; gpt-5-mini pour `/ask`, gpt-5 pour les étiquettes (meilleure extraction : 28/28 et 34/34 verbatim ou partiel). | Fournisseur et modèle restent du `.env`. |
| 9 | **Échéances erronées** : les retraits français de 2006 apparaissaient comme « expirant ». | `/expiring` ne retient que les enregistrements actifs dont l'échéance est future. | Une date de retrait passée n'est pas une échéance. |
| 10 | **Dérive de source** possible à tout moment (colonnes renommées, API vide). | Garde de schéma : colonnes attendues par source ; une run échouée est **enregistrée** avec sa raison (snapshot `failed`) ; un dossier EPA vide est une preuve « la source n'a rien dit », pas un changement de format. | Le cahier demande d'expliquer ce qui se passe quand une source change : nous le montrons dans la base. |
| 11 | **Confidentialité** : les dossiers EPA contiennent nom, téléphone, e-mail d'une personne. | Caviardage avant écriture sur disque ; test ; seul le nom de l'entreprise reste. | Donnée personnelle inutile au besoin. |
| 12 | **Un coéquipier a supprimé** `.gitignore`, `requirements.txt`, `.env.example` depuis une base ancienne (commit « remove »). | Fusion en restaurant ces fichiers ; `.gitattributes` pour les fins de ligne (scripts shell du serveur). | Sans `.gitignore`, le `.env` aurait pu partir dans Git. |
| 13 | **Serveur de l'équipe** : anciens conteneurs de test (n8n, bot Telegram, etc.). | Tout supprimé à la demande ; `.env` anciens sauvegardés dans `/home/ubuntu/old-deploy-backup-20261009/` ; pare-feu (22/80/443), swap 2 Go, Docker Compose v5, cron. | Production propre, reproductible depuis `infra/README.md`. |
| 14 | **Codes EPPO** : le kit en fournit 50 ; les sources utilisent des libellés groupés (« Cucurbitacées à peau comestible », « Thrips »). | Correspondance **exacte uniquement** (noms, alias multilingues, libellés observés) ; jamais de code espèce depuis un genre ; tout reste `to_verify`. ~23 % des usages codés. | Un code faux est pire qu'aucun code. |
| 16 | **Réponses `/ask` trop verbeuses** (lignes entières recopiées). | Modèle Pydantic `StructuredAnswer` imposé au LLM (schéma JSON) et au chemin déterministe : titre, lignes strictement utiles, 4 points d'attention max ; garde-fou inchangé. | Une réponse réglementaire doit se lire en dix secondes et rester traçable ; la structure force le modèle à choisir, pas à paraphraser des tables. |
| 17 | **Clic sur la carte sans effet** dans le navigateur. | La sélection Plotly arrivait bien à Streamlit, mais le composant « pastilles » la réécrivait avec sa valeur par défaut ; l'état est maintenant synchronisé avant le rendu (test avec un vrai événement Plotly). | Un composant à état doit être piloté par `session_state`, pas par `default`. |
| 15 | **Registre interne LPC « avec ses imperfections »** : un numéro officiel peut appartenir à un autre produit que celui du registre (PRESTOP WG lié à G46 dans l'échantillon), dates conventionnelles, statuts mélangés. | Rapprochement en deux clés (numéro puis nom) ; chaque écart typé (`product_identity`, `status`, `expiration_date`, `active_entity`, `holder`) avec la preuve officielle ; rien n'est corrigé automatiquement. | Le registre est la vérité commerciale de LPC, la source officielle est la vérité réglementaire : on montre les deux côte à côte. |

## 6. Comment c'est construit (une page)

```
sources officielles → collecteurs (fichier brut + sha256 + date, snapshot) → parseurs (originaux verbatim, extrait de preuve)
→ normalisation (statut, EPPO exact, unités, synonymes documentés, souche+espèce) → base canonique (source/URL/date/statut NOT NULL)
→ API (contrat du kit, evidence[] + warnings[] + disclaimer partout) → UI légère · connecteur Power Platform · Copilot · export CSV/XLSX
PDF d'étiquette → LLM (schéma JSON strict) → garde-fou verbatim → usages llm_pdf (à vérifier)
question → planificateur déterministe → outils en lecture seule → faits = preuves → (LLM reformule) → garde-fou chiffres/pays → réponse
```

Règles que la base rend impossibles à contourner : pas de ligne réglementaire sans source, URL, date, statut ; `*_original` jamais modifié ;
trois états distincts « trouvé / non trouvé dans la source (date) / source non connectée » ; hypothèse jamais affichée comme équivalence ;
toute décision humaine journalisée (`POST /review`, `review_log`).

## 7. Les chiffres du 10 octobre (serveur)

| Indicateur | Valeur |
|---|---|
| Sources / régions | 4 / 3 |
| Enregistrements · usages · noms et relations | 232 · 6 410 · 140 |
| Produits pilotes retrouvés | 3, chacun sous un identifiant unique ; CONTANS et M52 OD dans CA/US/FR ; G46 en FR + produits liés PRESTOP WG (CA/US), PRESTOP (CA/US/FR), LALFRESH S (FR) |
| Lignes d'étiquette IA | 74 acceptées (63 verbatim, 11 partielles), 11 rejetées, 0 valeur fausse sur 20 champs vérifiés à la main |
| Tests | 59 verts (local + conteneur de production) |
| Évaluateur | 70 / 70 |
| Temps du pipeline complet sur le serveur | ≈ 8 min (dont 392 Mo de téléchargement brésilien et ≈ 4 min d'extraction gpt-5) |

## 8. Relancer

Machine propre : voir `README.md` (10 commandes). Serveur : `infra/README.md`. Cron : `/etc/cron.d/lpc-regwatch` (03:30 UTC) ;
log `/var/log/lpc-regwatch-pipeline.log`. Mettre à jour : `ssh ubuntu@37.187.176.97 'cd /opt/lpc-regwatch && git pull && docker compose -f infra/docker-compose.yml --env-file .env up -d --build'`.

## 9. Ce qu'il reste à faire (après le hackathon)

1. Brancher le flux Power Automate sur les colonnes réelles de la liste SharePoint de LPC (attendues).
2. Démonstration dans un tenant M365 (captures : connecteur, flux, conversation Copilot).
3. Entra ID devant l'API (rôles Reader / Reviewer) ; HTTPS par nom de domaine (Caddy le fait seul).
4. Client EPPO Data Services pour passer les codes en `validated` sous contrôle RA.
5. Sources supplémentaires avec la même classe de collecteur (Allemagne BVL déjà sondée, Belgique, Uruguay).

## 10. Règles de travail dans le dépôt

- Une branche par fonctionnalité ; `main` reste exécutable ; `pytest -q` avant tout push.
- Jamais de secret dans Git (`.env` ignoré, `chmod 600` sur le serveur). Aucune clé n'est nécessaire pour relancer.
- Après tout changement de parseur ou de normalisation : `python scripts/parse.py --source all` puis `python scripts/normalize.py` doivent finir par `VALIDATION PASSED`.
- Toute nouvelle source : une ligne dans `data/source_registry.csv`, une section dans `docs/SOURCES.md`, une entrée dans `sources/ATTRIBUTION.md`.
- Ne jamais modifier une valeur `*_original` ; ne jamais passer un statut à `validated` sans revue humaine tracée (sauf les réponses écrites de LPC, versionnées dans `data/lpc_curated_relations.csv`).
