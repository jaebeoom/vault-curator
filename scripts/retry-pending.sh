#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PENDING_FILE="$PROJECT_DIR/.curation-pending"

if [ ! -f "$PENDING_FILE" ]; then
  echo "No pending curation job."
  exit 0
fi

echo "Pending curation found. Retrying..."
"$PROJECT_DIR/scripts/daily-curate.sh"
