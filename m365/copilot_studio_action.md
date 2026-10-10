# Copilot Studio — "Regulatory watch" agent with one grounded action

Goal: a Regulatory Affairs user asks in Teams "Dans quels pays LALSTOP CONTANS WG est-il homologué ?" and gets the
same answer, evidence and warnings as the web UI — nothing more.

## Setup

1. Create the custom connector from `m365/apiDefinition.swagger.json` (see README §1).
2. Copilot Studio → *Create agent* → name `LPC Regulatory Watch`.
3. **Settings → Generative AI → "Use information from the web": OFF** (cahier §16: no uncontrolled web search).
4. **Actions → Add an action → Connector** → choose the connector → operation **askRegulatoryQuestion** (`POST /ask`).
   - Inputs: `question` ← the user's utterance (`System.Activity.Text`), `language` ← `fr`.
   - Outputs used: `answer`, `evidence`, `warnings`, `disclaimer`, `intent`, `model`.
5. Topic `Regulatory question` (trigger phrases: homologué, enregistré, usages, dose, produit sœur, source, expire…):
   - Call the action.
   - **Message**: `{answer}`
   - **Message** (adaptive card, repeated over `evidence`): `sourceId · sourceUrl (link) · collectedAt · validationStatus`
   - **Condition** `CountRows(warnings) > 0` → **Message**: "⚠️ Points d'attention :" + bullet list of `warnings`.
   - **Message**: `{disclaimer}` (always, last).
6. Fallback topic: "Je ne réponds qu'à partir des sources officielles collectées (CA, US, FR, BR). Aucun résultat ≠ absence d'homologation."

## Why this is safe

- The LLM inside the API only rephrases facts returned by predefined queries; a guard rejects any number or country not
  present in the facts (`src/lpc_regwatch/api/ask.py`). Copilot Studio adds no second generation step.
- Every card line is an official source URL with a collection timestamp and a validation status.
- The `disclaimer` is a mandatory field of the contract and is printed on every turn.

## Example conversation (expected)

> **User:** Comparer les usages de LALSTOP CONTANS WG entre la France et le Canada.
>
> **Agent:** LALSTOP CONTANS WG — France (FR) : n° 9900189, statut active (« AUTORISE »), 1 usage, source FR-EPHY collectée le 2026-10-09 … Canada (CA) : n° 29066, statut active (« Full Registration »), 17 usages … Usages (extrait) : FR 9900189 : Traitements généraux → Champignons (autres que pythiacées) | 4.0 kg/ha | max 1 appl. ; CA 29066 : LETTUCE → SCLEROTINIA MINOR; SCLEROTINIA SCLEROTIORUM | dose non structurée | unpaired_lists …
>
> *Preuves:* FR-EPHY · data.gouv.fr/… · 2026-10-09 21:11 UTC · automatically_extracted ; CA-PPID · pr-rp.hc-sc.gc.ca/… · 2026-10-09 21:11 UTC · automatically_extracted
>
> ⚠️ CA 29066: dose is not in the structured source; only the official label PDF states it. · CA 29066: the source lists crops and targets as two independent lists…
>
> *This tool is not an official regulatory source. Regulatory Affairs validation is required…*
