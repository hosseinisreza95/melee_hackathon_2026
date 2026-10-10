# Infrastructure — deployment as code

## Services (infra/docker-compose.yml)

| Service | Image | Role | Exposed |
|---|---|---|---|
| `db` | postgres:16-alpine | canonical store (9 tables, see docs/DATA_MODEL.md) | internal only |
| `api` | lpc-regwatch (infra/Dockerfile) | FastAPI, `scripts/serve_api.py` | internal :8000 → proxy `/api/` |
| `ui` | lpc-regwatch | Streamlit thin client (`API_BASE_URL=http://api:8000`) | internal :8501 → proxy `/` |
| `proxy` | caddy:2-alpine | single public port 80; `/api/*` → api, `/pitch/*` → static presentation, `/*` → ui | **:80** |
| `pipeline` | lpc-regwatch (profile `jobs`) | one-shot `scripts/pipeline.sh`: init → collect → parse → normalize → labels → export → submission | — |

Volumes: `pgdata` (database), `rawdata` (official files + `.meta.json`, ≈ 420 MB), `processed` (label-extraction cache),
`output` (submission.json), `caddy_data`.

## First deployment (Ubuntu 24.04 host with Docker ≥ 24 and compose v2)

```bash
sudo mkdir -p /opt/lpc-regwatch && sudo chown $USER /opt/lpc-regwatch
git clone https://github.com/hosseinisreza95/melee_hackathon_2026.git /opt/lpc-regwatch
cd /opt/lpc-regwatch
cp .env.example .env            # then set POSTGRES_PASSWORD, PUBLIC_BASE_URL, and (optionally) AI_API_KEY
chmod 600 .env
docker compose -f infra/docker-compose.yml --env-file .env up -d --build db api ui proxy
docker compose -f infra/docker-compose.yml --env-file .env --profile jobs run --rm pipeline
```

The pipeline takes ~10 minutes the first time (the Brazilian CSV is 392 MB). Without `AI_API_KEY` the label-extraction
step prints `SKIPPED` and everything else is identical.

## Refresh (cron on the host)

`infra/cron.d/lpc-regwatch` runs the pipeline every day at 03:30 UTC (Canada refreshes nightly, EPA every 12 h, E-Phy weekly,
Brazil irregularly) and prunes raw snapshots older than 60 days. Change detection compares each run with the previous snapshot
(`change_log` table, `GET /changes`).

```
30 3 * * * ubuntu cd /opt/lpc-regwatch && docker compose -f infra/docker-compose.yml --env-file .env --profile jobs run --rm pipeline >> /var/log/lpc-regwatch-pipeline.log 2>&1
```

## Operations

```bash
docker compose -f infra/docker-compose.yml --env-file .env ps
docker compose -f infra/docker-compose.yml --env-file .env logs -f api
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m pytest -q tests      # tests inside the container
docker compose -f infra/docker-compose.yml --env-file .env exec db pg_dump -U lpc lpc_regwatch > backup.sql
```

Schema changes: the models are the schema. `init_db()` creates missing tables and **adds missing nullable columns**
(additive migration, enough for this tool). Destructive changes would need Alembic (path to production, docs/ARCHITECTURE.md).

## Security notes

- Only port 80 is published (plus SSH on the host). HTTPS: point a domain at the host and replace `:80` by the domain in `infra/Caddyfile`; Caddy issues the certificate automatically.
- `.env` holds the only secrets (database password, optional AI key); it is git-ignored, `chmod 600`, and mounted as `env_file`, never baked into the image.
- Containers run as non-root user `lpc`. Caddy strips the `Server` header and sets `X-Content-Type-Options`.
- The API has no authentication in the tool (public read-only data). For LPC: Entra ID in front (m365/README.md §4) and `POST /review` restricted to the Reviewer role.
- Personal contact data from EPA records is redacted at ingestion; raw files contain only company names.
