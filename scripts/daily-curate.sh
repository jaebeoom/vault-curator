#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_SCRIPT="$PROJECT_DIR/scripts/sync-to-icloud.sh"
CONDA_BIN="/Users/nathan/miniforge3/condabin/conda"
SHARED_AI_ENV="/Users/nathan/Atelier/Projects/.shared-ai.env"
PENDING_FILE="$PROJECT_DIR/.curation-pending"

cd "$PROJECT_DIR"

if [ -f "$SHARED_AI_ENV" ]; then
  set -a
  source "$SHARED_AI_ENV"
  set +a
fi

if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

if [ -z "${OMLX_API_KEY:-}" ] && [ -z "${VAULT_CURATOR_LOCAL_API_KEY:-}" ]; then
  echo "OMLX_API_KEY is not set. Add it to /Users/nathan/Atelier/Projects/.shared-ai.env."
  exit 1
fi

mkdir -p "$PROJECT_DIR/logs"

tmp_log="$(mktemp)"

if "$CONDA_BIN" run -n vault-curator env PYTHONPATH=src \
  python -m vault_curator.cli local-run \
  --timeout-seconds 900 >"$tmp_log" 2>&1; then
  cat "$tmp_log"
  rm -f "$tmp_log"
  rm -f "$PENDING_FILE"
else
  cat "$tmp_log"
  if grep -q "HTTP 507" "$tmp_log"; then
    date +"%Y-%m-%d %H:%M:%S" >"$PENDING_FILE"
    echo "Memory pressure detected (HTTP 507). Marked pending for overnight retry."
  fi
  rm -f "$tmp_log"
  exit 1
fi

if [ -x "$BACKUP_SCRIPT" ]; then
  "$BACKUP_SCRIPT"
fi
