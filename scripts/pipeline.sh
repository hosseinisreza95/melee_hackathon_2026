#!/usr/bin/env bash
# Full data pipeline, idempotent: init schema -> collect official files -> parse -> normalise/match
# -> AI label extraction (skipped without key) -> export CSVs -> submission + evaluator.
# Used by the `pipeline` compose service and by cron on the server (infra/README.md).
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUTF8=1
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

log "init_db";        python scripts/init_db.py
log "collect";        python scripts/collect.py --source ${SOURCES:-all}
log "parse";          python scripts/parse.py --source ${SOURCES:-all}
log "normalize";      python scripts/normalize.py
log "extract_labels"; python scripts/extract_labels.py ${LABEL_ARGS:-} || log "label extraction failed (non-blocking)"
log "normalize(2)";   python scripts/normalize.py          # re-map crops/targets of AI-extracted rows and re-export
log "submission";     python scripts/build_submission.py
log "done"
