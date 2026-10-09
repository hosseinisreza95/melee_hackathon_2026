# Power Automate flow — weekly comparison export to SharePoint + change alert in Teams

Trigger and actions (built-in connectors only; the custom connector of §1 is optional):

1. **Recurrence** — every week, Monday 06:00 (Europe/Paris).
2. **HTTP** — `GET http://<host>/api/export.csv?productId=P-LPC-CONTANS&countries=CA,US,FR,BR`
   - Headers: `Accept: text/csv`
   - (with Entra ID: Authentication = Active Directory OAuth, audience = API app id)
3. **Create file** (SharePoint) — site `Regulatory Affairs`, folder `/Shared Documents/RegWatch/`,
   file name `comparison_CONTANS_@{formatDateTime(utcNow(),'yyyy-MM-dd')}.csv`, content = body of step 2.
   The file keeps `source_id`, `source_record_url`, `collected_at`, `validation_status`, `pairing`, `extraction_method` per row.
4. **HTTP** — `GET http://<host>/api/changes?limit=50`
5. **Condition** — `length(body('HTTP_2')) > 0`
   - Yes → **Post message in a chat or channel** (Teams): "RegWatch: @{length(body('HTTP_2'))} change(s) detected" + an HTML table
     built with **Create HTML table** from `entityId`, `field`, `oldValue`, `newValue`, `detectedAt`.
6. **HTTP** — `GET http://<host>/api/expiring?months=6` → same pattern → Teams message "Registrations expiring within 6 months".

Why these endpoints: `/export.csv` is the flat product × country × use table (one row per use, evidence columns included);
`/changes` and `/expiring` are the two watch signals the challenge asks for (cahier §12). All three are read-only.

Validation note: the SharePoint copy is a *derived* document. The file header row and the `disclaimer` column in the
XLSX variant remind readers that Regulatory Affairs validation is required and that absence of a row is not absence of registration.
