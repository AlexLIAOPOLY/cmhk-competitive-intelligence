#!/usr/bin/env bash
set -euo pipefail

SOURCE="/Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521"
RUNTIME="/Users/liaowang/cmhk_public_crawl_app"

mkdir -p "$RUNTIME"
rsync -a \
  --exclude='.git/' \
  --exclude='Codex/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  "$SOURCE/" "$RUNTIME/"

mkdir -p "$RUNTIME/Codex/agent/skills"
rsync -a --delete \
  "$SOURCE/Codex/agent/skills/" \
  "$RUNTIME/Codex/agent/skills/"

if [[ -f "/Users/liaowang/Downloads/模板.docx" ]]; then
  cp "/Users/liaowang/Downloads/模板.docx" "$RUNTIME/weekly_report_template.docx"
fi

echo "APP runtime synchronized to $RUNTIME"
