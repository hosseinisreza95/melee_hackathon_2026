# Guide d'intégration — utiliser les données de Regulatory Watch ailleurs

Ce guide explique comment réutiliser les données de l'outil (homologations, usages autorisés, produits liés, échéances, changements)
dans d'autres applications : Microsoft 365 (Power Automate, Power Apps, Copilot Studio), Dataverse / SharePoint, Excel, ou tout
programme capable d'appeler une API HTTP. Toutes les données viennent des sources officielles collectées et portent leur preuve
(source, URL, date de collecte, statut de validation).

> L'outil n'est pas une source réglementaire officielle : une validation Regulatory Affairs reste nécessaire avant tout usage
> officiel, commercial ou opérationnel. « Non trouvé dans la source » ne signifie jamais « non homologué ».

## 1. Où sont les données

| Élément | Adresse |
|---|---|
| API (JSON) | `http://<serveur>/api` — par exemple `http://37.187.176.97/api` |
| Référence technique (Swagger / OpenAPI) | `/api/docs` et `/api/openapi.json` |
| Ce guide | `/api/guide` |
| Interface | `http://<serveur>/` |

Mise à jour : collecte → analyse → normalisation chaque nuit (03:30 UTC, `/api/health` indique la dernière et la prochaine exécution).
Couverture actuelle : France = tous les produits autorisés (E-Phy) ; Canada et États-Unis = produits Lallemand Plant Care et produits
liés ; Brésil = produits microbiens de l'extrait AGROFIT. `GET /api/sources` donne, pour chaque source, la licence, la date de
collecte et le nombre d'enregistrements.

## 2. Les appels les plus utiles

| Besoin | Appel | Exemple |
|---|---|---|
| Chercher un produit (nom, alias, matière active) | `GET /api/products?q=` | `/api/products?q=lalstop` |
| Comparer un produit entre pays (statut, usages, preuves) | `GET /api/compare?productId=&countries=` | `/api/compare?productId=P-LPC-CONTANS&countries=CA,US,FR,BR` |
| Enregistrements d'un produit | `GET /api/products/{id}/registrations` | `/api/products/P-LPC-G46/registrations?country=FR` |
| Noms alternatifs, produits sœurs et liés (avec statut de revue) | `GET /api/products/{id}/aliases` | `/api/products/P-LPC-G46/aliases` |
| Produits contenant un micro-organisme (option : culture, pays) | `GET /api/active-entities/{species}/registrations` | `/api/active-entities/Clonostachys rosea/registrations?crop=strawberry` |
| Autorisations qui expirent | `GET /api/expiring?months=12` | |
| Changements détectés entre deux collectes | `GET /api/changes` | |
| Champs manquants ou incertains d'un produit | `GET /api/products/{id}/quality` | |
| Vue d'ensemble par pays (carte) | `GET /api/overview?scope=pilots|lallemand|all|product` | |
| Poser une question en langage naturel | `POST /api/ask` `{"question": "...", "language": "fr"}` | réponse structurée + preuves ; `context` à renvoyer pour une question de suite |
| Export tableur | `GET /api/export.csv`, `GET /api/export.xlsx` (filtres `productId`, `countries`) | |
| Export au modèle Dataverse LPC (8 tables) | `GET /api/export/dataverse.zip`, `/api/export/dataverse.xlsx`, `/api/export/dataverse-validation` | |
| Rapprocher le registre interne (liste SharePoint) | `POST /api/registry/reconcile` (fichier CSV / XLSX) | `GET /api/registry/reconcile/sample` pour l'exemple |
| Décision de revue (valider / rejeter une hypothèse) | `POST /api/review` | journal : `GET /api/review/log` |

Chaque ligne renvoyée contient `evidence` : `sourceId`, `sourceUrl`, `collectedAt`, `validationStatus`, et pour les usages extraits
d'une étiquette, l'extrait et la confiance. Les valeurs originales des sources ne sont jamais modifiées ; les valeurs normalisées
(statut, codes EPPO, unités) sont ajoutées à côté.

## 3. Microsoft 365

1. **Connecteur personnalisé Power Platform** : importer `m365/apiDefinition.swagger.json` (Swagger 2.0 généré depuis l'API) et
   `m365/apiProperties.json` dans Power Automate / Power Apps (« Connecteurs personnalisés » → « Importer un fichier OpenAPI »).
   Les opérations `searchProducts`, `compareProductUses`, `askRegulatoryQuestion` sont marquées importantes.
2. **Power Automate** : flux d'exemple dans `m365/power_automate_flow.md` — chaque matin, `GET /api/expiring?months=6` puis
   `GET /api/changes`, et publication Teams / e-mail avec les preuves.
3. **Copilot Studio** : action sur `askRegulatoryQuestion` (`m365/copilot_studio_action.md`) pour interroger en langage naturel
   depuis Teams ; l'agent ne cite que les faits renvoyés.
4. **Dataverse / SharePoint** : `GET /api/export/dataverse.zip` produit les huit tables `lpc_*` au format du classeur cible LPC
   (`schema/dataverse_tables.xlsx`), validées par `/api/export/dataverse-validation` ; import par dataflow ou Power Query.
   Le rapprochement du registre interne (liste SharePoint) se fait par `POST /api/registry/reconcile`.
5. **Sécurité** : l'API est ouverte en lecture pour la démonstration ; pour LPC, placer Entra ID / API Management devant
   (`m365/README.md`, §4) et réserver `POST /review` au rôle Relecteur.

## 4. Excel, Python, autres outils

- Excel / Power Query : « Données → À partir du Web » avec l'URL JSON (`/api/compare?...`) ou l'export `/api/export.xlsx`.
- Python : `requests.get("http://<serveur>/api/compare", params={"productId": "P-LPC-M52", "countries": "CA,FR"}).json()`.
- Toute réponse comporte `disclaimer` et `warnings` : les relayer dans l'application cible.

## 5. Modèle de données en deux lignes

`products` (identité du produit, entité active normalisée) → `registrations` (une par pays et numéro officiel, statut original +
normalisé, dates, titulaire, preuve) → `uses` (culture, cible, dose, DAR, restrictions ; codes EPPO candidats) ; `product_aliases`
(noms alternatifs, produits sœurs et liés, avec statut de revue) ; `change_log` ; `review_log` ; `snapshots` et `raw_documents`
(traçabilité des fichiers officiels téléchargés). Détail : `docs/DATA_MODEL.md`, `docs/DATAVERSE_MAPPING.md`.
