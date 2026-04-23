#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_SCRIPT="$PROJECT_DIR/scripts/sync-to-icloud.sh"
DEFAULT_VENV_DIR="$PROJECT_DIR/.venv"
DEFAULT_VAULT_CURATOR_PYTHON="$DEFAULT_VENV_DIR/bin/python"
VENV_DIR="${VENV_DIR:-}"
VAULT_CURATOR_PYTHON="${VAULT_CURATOR_PYTHON:-}"
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

load_env_file() {
  setopt local_options extended_glob
  local env_file="$1"

  if [ -z "$env_file" ] || [ ! -f "$env_file" ]; then
    return 0
  fi

  local line key value ignored=0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    line="${line##[[:space:]]#}"
    line="${line%%[[:space:]]#}"

    case "$line" in
      ""|\#*) continue ;;
    esac

    if [[ "$line" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line##[[:space:]]#}"
    fi

    if [[ "$line" != *=* ]]; then
      ignored=$((ignored + 1))
      continue
    fi

    key="${line%%=*}"
    value="${line#*=}"
    key="${key##[[:space:]]#}"
    key="${key%%[[:space:]]#}"
    value="${value##[[:space:]]#}"
    value="${value%%[[:space:]]#}"

    case "$key" in
      OMLX_BASE_URL|OMLX_MODEL|OMLX_API_KEY|\
      VAULT_CURATOR_LOCAL_BASE_URL|VAULT_CURATOR_LOCAL_MODEL|VAULT_CURATOR_LOCAL_API_KEY|\
      VENV_DIR|VAULT_CURATOR_PYTHON|ICLOUD_BACKUP_DIR)
        ;;
      *)
        continue
        ;;
    esac

    case "$value" in
      \"*\") value="${value#\"}"; value="${value%\"}" ;;
      \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac

    export "$key=$value"
  done < "$env_file"

  if [ "$ignored" -gt 0 ]; then
    echo "Warning: ignored unsupported env lines in $env_file ($ignored)."
  fi

  return 0
}

if [ -z "$SHARED_AI_ENV" ]; then
  if [ -f "$PROJECT_DIR/.shared-ai.env" ]; then
    SHARED_AI_ENV="$PROJECT_DIR/.shared-ai.env"
  elif [ -f "$PROJECT_DIR/../.shared-ai.env" ]; then
    SHARED_AI_ENV="$PROJECT_DIR/../.shared-ai.env"
  fi
fi

load_env_file "$SHARED_AI_ENV"

VENV_DIR="${VENV_DIR:-$DEFAULT_VENV_DIR}"
VAULT_CURATOR_PYTHON="${VAULT_CURATOR_PYTHON:-$VENV_DIR/bin/python}"

if [ ! -x "$VAULT_CURATOR_PYTHON" ] \
  && [ "$VAULT_CURATOR_PYTHON" != "$DEFAULT_VAULT_CURATOR_PYTHON" ] \
  && [ -x "$DEFAULT_VAULT_CURATOR_PYTHON" ]; then
  echo "Configured Python executable is unavailable: $VAULT_CURATOR_PYTHON"
  echo "Falling back to uv-managed repo environment: $DEFAULT_VAULT_CURATOR_PYTHON"
  VAULT_CURATOR_PYTHON="$DEFAULT_VAULT_CURATOR_PYTHON"
fi

if [ ! -x "$VAULT_CURATOR_PYTHON" ]; then
  echo "Missing Python executable: $VAULT_CURATOR_PYTHON"
  echo "Bootstrap the repo-local environment first:"
  echo "  cd \"$PROJECT_DIR\" && uv sync"
  exit 1
fi

echo "Vault curator runtime:"
echo "  Python: $VAULT_CURATOR_PYTHON"
if [ -n "$SHARED_AI_ENV" ]; then
  echo "  Shared env: $SHARED_AI_ENV"
else
  echo "  Shared env: (none)"
fi
if [ -n "${OMLX_BASE_URL:-}" ]; then
  echo "  Endpoint override: OMLX_BASE_URL=$OMLX_BASE_URL"
elif [ -n "${VAULT_CURATOR_LOCAL_BASE_URL:-}" ]; then
  echo "  Endpoint override: VAULT_CURATOR_LOCAL_BASE_URL=$VAULT_CURATOR_LOCAL_BASE_URL"
else
  echo "  Endpoint override: (config.toml fallback)"
fi
if [ -n "${OMLX_MODEL:-}" ]; then
  echo "  Model override: OMLX_MODEL=$OMLX_MODEL"
elif [ -n "${VAULT_CURATOR_LOCAL_MODEL:-}" ]; then
  echo "  Model override: VAULT_CURATOR_LOCAL_MODEL=$VAULT_CURATOR_LOCAL_MODEL"
else
  echo "  Model override: (config.toml fallback)"
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
