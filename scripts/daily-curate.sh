#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_SCRIPT="$PROJECT_DIR/scripts/sync-to-icloud.sh"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
VAULT_CURATOR_PYTHON="${VAULT_CURATOR_PYTHON:-$VENV_DIR/bin/python}"
SHARED_AI_ENV="${SHARED_AI_ENV:-}"
PENDING_FILE="$PROJECT_DIR/.curation-pending"
LOCK_DIR="$PROJECT_DIR/.curation.lock"

cd "$PROJECT_DIR"

cleanup_lock() {
  rm -rf "$LOCK_DIR"
}

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_DIR/pid"
    return 0
  fi

  if [ -f "$LOCK_DIR/pid" ]; then
    local lock_pid
    lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
      echo "Curation already running (pid $lock_pid)."
      return 1
    fi
  fi

  echo "Removing stale curation lock."
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
  echo "$$" > "$LOCK_DIR/pid"
  return 0
}

if ! acquire_lock; then
  exit 0
fi

trap cleanup_lock EXIT INT TERM

source_env_file() {
  local env_file="$1"

  if [ -z "$env_file" ] || [ ! -f "$env_file" ]; then
    return 0
  fi

  set +e
  set -a
  source "$env_file"
  local source_rc=$?
  set +a
  set -e

  if [ $source_rc -ne 0 ]; then
    echo "Warning: could not load env file: $env_file"
  fi

  return 0
}

if [ -z "$SHARED_AI_ENV" ] && [ -f "$PROJECT_DIR/.shared-ai.env" ]; then
  SHARED_AI_ENV="$PROJECT_DIR/.shared-ai.env"
fi

source_env_file "$SHARED_AI_ENV"

if [ -f "$PROJECT_DIR/.env" ]; then
  source_env_file "$PROJECT_DIR/.env"
fi

if [ ! -x "$VAULT_CURATOR_PYTHON" ]; then
  echo "Missing Python executable: $VAULT_CURATOR_PYTHON"
  echo "Bootstrap the repo-local environment first:"
  echo "  cd \"$PROJECT_DIR\" && uv sync"
  exit 1
fi

mkdir -p "$PROJECT_DIR/logs"

tmp_log="$(mktemp)"

if PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
  VAULT_CURATOR_SKIP_CLI_LOCK=1 \
  "$VAULT_CURATOR_PYTHON" -m vault_curator.cli local-run \
  --timeout-seconds 900 >"$tmp_log" 2>&1; then
  cat "$tmp_log"
  rm -f "$tmp_log"
  rm -f "$PENDING_FILE"
else
  cat "$tmp_log"
  date +"%Y-%m-%d %H:%M:%S" >"$PENDING_FILE"
  if grep -q "HTTP 507" "$tmp_log"; then
    echo "Memory pressure detected (HTTP 507). Marked pending for overnight retry."
  else
    echo "Curation failed. Marked pending for retry."
  fi
  rm -f "$tmp_log"
  exit 1
fi

if [ -x "$BACKUP_SCRIPT" ]; then
  "$BACKUP_SCRIPT"
fi
