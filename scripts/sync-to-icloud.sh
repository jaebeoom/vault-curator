#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ICLOUD_BACKUP_DIR="/Users/nathan/Library/Mobile Documents/com~apple~CloudDocs/Atelier/Projects/vault-curator"

mkdir -p "$ICLOUD_BACKUP_DIR"

rsync -a --delete \
  --exclude '.DS_Store' \
  --exclude 'logs/launchd.out.log' \
  --exclude 'logs/launchd.err.log' \
  "$PROJECT_DIR/" \
  "$ICLOUD_BACKUP_DIR/"
