"""Collector base class: fetch official files, store them untouched with provenance, register a snapshot.

Design rules (docs/SPEC.md G2, G6, G7; QUICKSTART "store evidence before normalization"):
- Every byte fetched is written to data/raw/<source_id>/<UTC timestamp>/<file> plus <file>.meta.json
  (url, collected_at, sha256, bytes, content_type). Nothing is parsed or modified here, except the
  privacy redaction a subclass may apply before writing (documented in that subclass).
- One `snapshots` row per run (status ok|failed|partial) and one `raw_documents` row per file.
- Schema drift: a subclass declares the columns/keys it relies on; if any is missing the run is
  marked failed and SchemaDriftError is raised. New columns are only reported in snapshot.notes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import RawDocument, Snapshot

log = logging.getLogger(__name__)


class SchemaDriftError(RuntimeError):
    """The source changed its structure; stop instead of producing wrong data."""


@dataclass
class Fetched:
    url: str
    local_path: str
    content_type: str | None
    sha256: str
    bytes: int
    collected_at: str  # ISO-8601 UTC
    document_kind: str  # extract_csv | api_json | label_pdf | zip | html


class BaseCollector:
    source_id: str = ""
    version: str = "0.1.0"
    timeout: float = 600.0
    retries: int = 3

    def __init__(self, session: Session, raw_dir: Path | None = None, client: httpx.Client | None = None):
        self.session = session
        self.raw_dir = Path(raw_dir or settings.raw_dir)
        self.client = client or httpx.Client(
            headers={"User-Agent": settings.http_user_agent}, timeout=self.timeout, follow_redirects=True
        )
        self.started_at = dt.datetime.now(dt.timezone.utc)
        self.snapshot_dir = self.raw_dir / self.source_id / self.started_at.strftime("%Y%m%dT%H%M%SZ")
        self.notes: list[str] = []

    # ------------------------------------------------------------------ public
    def run(self) -> Snapshot:
        snap = Snapshot(source_id=self.source_id, collected_at=self.started_at,
                        collector_version=self.version, status="running")
        self.session.add(snap)
        self.session.flush()
        try:
            fetched = list(self.collect())
            for f in fetched:
                self.session.add(RawDocument(
                    snapshot_id=snap.snapshot_id, source_id=self.source_id, url=f.url, local_path=f.local_path,
                    content_type=f.content_type, sha256=f.sha256, bytes=f.bytes,
                    collected_at=dt.datetime.fromisoformat(f.collected_at), document_kind=f.document_kind,
                ))
            snap.status = "ok"
            snap.notes = "\n".join(self.notes) or None
            self.session.commit()
            log.info("%s: snapshot %s ok, %d documents", self.source_id, snap.snapshot_id, len(fetched))
            return snap
        except Exception as e:  # noqa: BLE001 — any failure must be recorded, then re-raised
            snap.status = "failed"
            snap.notes = f"{type(e).__name__}: {e}\n" + "\n".join(self.notes)
            self.session.commit()
            log.error("%s: snapshot %s FAILED: %s", self.source_id, snap.snapshot_id, e)
            raise

    def collect(self) -> Iterable[Fetched]:  # pragma: no cover - abstract
        raise NotImplementedError

    # ------------------------------------------------------------------ helpers for subclasses
    def _get(self, url: str, **kw) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.client.get(url, **kw)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"server error {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
                if attempt < self.retries and (isinstance(e, httpx.TransportError) or e.response.status_code >= 500):
                    time.sleep(2 * attempt)
                    continue
                raise
        raise last  # type: ignore[misc]

    def download(self, url: str, filename: str, kind: str, params: dict | None = None) -> Fetched:
        """Stream a URL to disk, write provenance sidecar, return Fetched."""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_dir / filename
        collected_at = dt.datetime.now(dt.timezone.utc)
        h = hashlib.sha256()
        n = 0
        with self.client.stream("GET", url, params=params) as r:
            if r.status_code >= 400:
                raise httpx.HTTPStatusError(f"{r.status_code} for {url}", request=r.request, response=r)
            with path.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
            ct = r.headers.get("content-type")
            final_url = str(r.url)
        return self._record(final_url, path, ct, h.hexdigest(), n, collected_at, kind)

    def save_json(self, url: str, obj: Any, filename: str, kind: str = "api_json", content_type: str = "application/json") -> Fetched:
        """Persist an already-fetched JSON object (e.g. after privacy redaction) with provenance."""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_dir / filename
        data = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        path.write_bytes(data)
        return self._record(url, path, content_type, hashlib.sha256(data).hexdigest(), len(data),
                            dt.datetime.now(dt.timezone.utc), kind)

    def _record(self, url, path: Path, ct, sha, n, collected_at: dt.datetime, kind) -> Fetched:
        f = Fetched(url=url, local_path=str(path), content_type=ct, sha256=sha, bytes=n,
                    collected_at=collected_at.isoformat(), document_kind=kind)
        meta = asdict(f) | {"source_id": self.source_id, "collector_version": self.version}
        path.with_name(path.name + ".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return f

    def check_columns(self, found: Iterable[str], expected: Iterable[str], label: str) -> list[str]:
        """Raise SchemaDriftError on missing expected columns; return (and note) extra ones."""
        found_s = [c.strip() for c in found]
        missing = [c for c in expected if c not in found_s]
        if missing:
            raise SchemaDriftError(f"{self.source_id}/{label}: missing columns {missing}; found {found_s}")
        extra = [c for c in found_s if c not in set(expected)]
        if extra:
            self.notes.append(f"{label}: new columns not in contract: {extra}")
        return extra

    @staticmethod
    def read_header(path: Path, encoding: str, sep: str) -> list[str]:
        with Path(path).open("r", encoding=encoding, newline="") as fh:
            return [c.strip().strip('"') for c in fh.readline().rstrip("\r\n").split(sep)]
