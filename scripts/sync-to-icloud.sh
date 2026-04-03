#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ICLOUD_BACKUP_DIR="${ICLOUD_BACKUP_DIR:-}"

if [ -z "$ICLOUD_BACKUP_DIR" ]; then
  echo "ICLOUD_BACKUP_DIR is not set. Skipping backup sync."
  exit 0
fi

mkdir -p "$ICLOUD_BACKUP_DIR"

rsync -a --delete \
  --exclude '.DS_Store' \
  --exclude 'logs/launchd.out.log' \
  --exclude 'logs/launchd.err.log' \
  "$PROJECT_DIR/" \
  "$ICLOUD_BACKUP_DIR/"
