# Single image for api, ui and pipeline jobs (the command differs per service in docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# make the package importable without pip install -e
ENV PYTHONPATH=/app/src
RUN useradd -m -u 10001 lpc && mkdir -p /app/data/raw /app/data/processed /app/output && chown -R lpc:lpc /app
USER lpc

EXPOSE 8000 8501
CMD ["python", "scripts/serve_api.py"]
