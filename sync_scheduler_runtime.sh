#!/usr/bin/env bash
set -euo pipefail

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="/Users/liaowang/cmhk_public_crawl_automation"

mkdir -p "$RUNTIME" "$RUNTIME/results" "$RUNTIME/raw" "$RUNTIME/curation_data"
rsync -a --include='*.py' --include='*.json' --include='*.tsv' --exclude='*' "$SOURCE/" "$RUNTIME/"
rsync -a --delete "$SOURCE/results/" "$RUNTIME/results/"
if [[ -d "$SOURCE/curation_data" ]]; then
  rsync -a --delete \
    --exclude='checkpoints.sqlite*' \
    --exclude='backups/' \
    --exclude='cache_backups/' \
    "$SOURCE/curation_data/" "$RUNTIME/curation_data/"
fi

echo "Scheduler runtime synchronized to $RUNTIME"
