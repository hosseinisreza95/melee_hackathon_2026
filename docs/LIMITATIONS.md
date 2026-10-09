# Known limitations (honest list, as of 2026-10-10)

1. **Not an official source.** Every answer carries the disclaimer; RA validation is required before any use.
2. **Four sources.** CA-PPID, US-EPA-PPLS, FR-EPHY, BR-AGROFIT. Germany (BVL) was probed and dropped to keep the MVP small;
   Belgium (SFTP registration), Uruguay (HTML) and Mexico (source to be confirmed by the organiser) are not collected.
   A product absent from these four is *not found in source*, never *not registered*.
3. **Dose in Canada and the United States** is not in the structured data. It comes only from label PDFs, read by an LLM
   (rows flagged `extraction_method=llm_pdf`, `pairing=llm_paired`, `validation_status=automatically_extracted`, with a
   verbatim excerpt verified in the PDF). Without an AI key those rows do not exist and the comparison says so.
4. **Crop ↔ target pairing in CA/US** structured data is not asserted by the source (two independent lists); rows are flagged
   `unpaired_lists`. Only France (and the AI label rows) give asserted pairs.
5. **Brazil** open file lists active registrations only and has no dates: no expiry alert and no "withdrawn" status can come from it.
6. **EPPO codes** are starter candidates (`to_verify`), extended with wordings observed in the sources; genus-level or group wordings
   ("Thrips", "Cucurbitacées à peau comestible") get no code on purpose. Coverage: ~23 % of use rows have a crop code.
7. **Taxonomic synonyms** are applied only where documented (Gliocladium catenulatum → Clonostachys rosea; Metarhizium anisopliae
   strain F52 → M. brunneum, as stated by the EPA record). Other M. anisopliae strains (Brazil) are not renamed.
8. **Sister products** are hypotheses with machine confidence (0.3 technical grade, 0.6 other registrant, 0.8 Lallemand group,
   or the LPC kit's own score) until a reviewer validates them.
9. **Change detection** needs two collections of the same source; the first run has no baseline (the demo DB shows the
   product-merge changes only).
10. **Natural-language answers** are phrased by the LLM only when a key is configured; otherwise a deterministic template
    with the same facts is returned. The guard may reject a correct phrasing that mentions a count not present in the facts.
11. **No authentication** on the prototype API (public read-only data); the Entra ID design is documented, not built.
12. **EPA site lists are very granular** (685 sites for CONTANS): the comparison table is long; filters exist in the UI.
13. **Microsoft 365 path is documented with generated connector files, not demonstrated in a tenant** (no tenant available during the hackathon).
14. **Label extraction quality** was checked by the verbatim-excerpt gate and a manual spot check documented in docs/EVAL.md, not by a full RA review.
