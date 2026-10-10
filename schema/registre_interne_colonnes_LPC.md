# Colonnes du registre interne LPC (structure seule, transmise le 10/10/2026 — `registre_interne_colonnes_LPC.docx`)

LPC partage **uniquement la structure** de sa liste SharePoint, pas les données (informations internes). Les tests utilisent
les sources officielles et des données fictives marquées `is_synthetic=true` (`data/synthetic/lpc_internal_registry_sample.csv`).

| Colonne du registre LPC | Champ du kit | Remarque LPC | Traitement dans l'outil (`src/lpc_regwatch/registry/`) |
|---|---|---|---|
| Product_TS | product_id / produit canonique | valeur « (Unassigned Product_TS) » possible | résolu vers `product_id` par nom/alias ; « Unassigned » → aucun lien, drapeau `product_unassigned` |
| Title | product_name_mapping.name_variant | nom enregistré dans le pays | nom utilisé pour la résolution produit et pour le rapprochement |
| Trademark Name | name_variant | nom de marque déposée | second nom candidat ; conservé tel quel |
| Country | country_code | nom complet en anglais, à convertir en code ISO | table nom → ISO 3166-1 alpha-2 ; inconnu → `country_code` vide + drapeau |
| Registration Status | status_original | Registered, Pending, Not applicable… | conservé tel quel ; normalisé via `data/registry_status_mapping.csv` (Registered→active, Pending→pending, Not applicable→unknown…) |
| Registration Number | registration_number | peut contenir « No registration number » | « No registration number » → vide + drapeau `no_registration_number` ; sinon nettoyé (espaces) |
| Registration Renewal Date | expiration_date | **12/31/2999 = « sans échéance »**, pas une vraie date | 2999 → vide + drapeau `no_expiry_convention` ; autres dates → ISO |
| Renewal Submission Date | (extension) | — | conservée dans `extensions` |
| Reg Type | (extension) | National Registration, Mutual Recognition XX, Notified, Sold without registration | conservée ; « Sold without registration » → drapeau `sold_without_registration` |
| Regulatory Classification | catégorie locale d'origine | libellé dans la langue du pays | conservée (originale) |
| Product Category | catégorie normalisée | Biofungicide, Fertilizer, Soil amendment… | conservée ; « Fertilizer / Soil amendment » → drapeau `not_a_ppp` (hors périmètre PPP) |
| Registration Holder | manquant dans le kit → à ajouter `registration_holder` | — | `holder_original` (ajouté au modèle cible, voir `docs/DATAVERSE_MAPPING.md`) |
| Company Name (label) | (extension) | — | conservée |
| Declared Manufacturer | (extension) | — | conservée |
| Guaranteed Actives | active_entity_original | souche et concentration dans un seul texte libre | `active_entity_original` conservé ; `canonical_active_entity()` → espèce + souche (mêmes règles que les sources officielles) |
| Formulation Code | formulation_code | format « WP - Wettable powder » | code extrait avant le tiret → `formulation_code` ; libellé conservé |
| RegState Registered / Pending / Not Applicable | (extension) | états américains séparés par des espaces | conservés en liste (extension) |
| Organic listing | (extension) | OMRI, EcoCert… | conservée |
| Crops / Target / Application rate | **à ne pas confondre avec uses** | données marketing au niveau produit, pas des usages homologués | conservées comme texte marketing (`marketing_crops_targets_rate`), **jamais** transformées en `uses` |
| Status | **à ne pas confondre avec le statut d'homologation** | cycle commercial : In market, Cancelled, In development | `commercial_status`, séparé de `status_original` |
| Shelf life (DECLARED) / Packaging formats (DECLARED) | (extension) | — | conservées |

Rapprochement avec les sources officielles (`registry.reconcile`) : clé 1 = (pays ISO, numéro d'enregistrement normalisé) ;
clé 2 = (pays, nom ou alias du produit). Sortie par ligne : enregistrement officiel trouvé ou non, statut registre vs statut officiel,
échéance registre vs officielle, titulaire, drapeaux de qualité, preuve officielle (source, URL, date). Un écart n'est jamais corrigé
automatiquement : il est affiché pour Regulatory Affairs.
