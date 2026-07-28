#!/usr/bin/env bash
set -euo pipefail

PUBLIC_REMOTE="${PUBLIC_REMOTE:-origin}"
PRIVATE_REMOTE="${PRIVATE_REMOTE:-private}"
PRIVATE_MAIN="${PRIVATE_MAIN:-main}"
ROOT="$(git rev-parse --show-toplevel)"
BRANCH="${1:-$(git branch --show-current)}"
RUNTIME_ROOT="${CMHK_RUNTIME_ROOT:-/Users/liaowang/cmhk_public_crawl_app}"

if [[ -z "$BRANCH" ]]; then
  echo "Refusing to synchronize from a detached HEAD." >&2
  exit 1
fi

for remote in "$PUBLIC_REMOTE" "$PRIVATE_REMOTE"; do
  if ! git -C "$ROOT" remote get-url "$remote" >/dev/null 2>&1; then
    echo "Missing Git remote: $remote" >&2
    exit 1
  fi
done

git_net() {
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
      -u http_proxy -u https_proxy -u all_proxy \
      NO_PROXY="github.com,api.github.com" \
      git -c http.proxy= -c https.proxy= "$@"
}

echo "[1/3] Push committed branch '$BRANCH' to public repository..."
git_net -C "$ROOT" push "$PUBLIC_REMOTE" "$BRANCH:$BRANCH"

echo "[2/3] Push committed branch '$BRANCH' to private repository..."
git_net -C "$ROOT" push "$PRIVATE_REMOTE" "$BRANCH:$BRANCH"

if ! git -C "$ROOT" diff --quiet || ! git -C "$ROOT" diff --cached --quiet; then
  echo "Note: uncommitted changes will be included only in private main snapshot."
fi

echo "[3/3] Build and push sanitized complete snapshot to private main..."
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cmhk-private-sync.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

PRIVATE_URL="$(git -C "$ROOT" remote get-url "$PRIVATE_REMOTE")"
git -C "$TMP_DIR" init -q
git -C "$TMP_DIR" remote add origin "$PRIVATE_URL"
git -C "$TMP_DIR" config user.name "AlexLIAOPOLY"
git -C "$TMP_DIR" config user.email "AlexLIAOPOLY@users.noreply.github.com"
git_net -C "$TMP_DIR" fetch --depth=1 --filter=blob:none origin "$PRIVATE_MAIN"

OLD_MAIN="$(git -C "$TMP_DIR" rev-parse FETCH_HEAD)"
STAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_BRANCH="backup/main-before-sync-$STAMP"
git_net -C "$TMP_DIR" push origin "$OLD_MAIN:refs/heads/$BACKUP_BRANCH"

rsync -a --delete \
  --exclude '/.git/' \
  --exclude '/.venv*/' \
  --exclude '/venv/' \
  --exclude '/tmp/' \
  --exclude '/archives/' \
  --exclude '/audio/' \
  --exclude '/models/' \
  --exclude '/__pycache__/' \
  --exclude '*/__pycache__/' \
  --exclude '*.pyc' \
  --exclude '*.pyo' \
  --exclude '*.log' \
  --exclude '*.pid' \
  --exclude '/.crawl_process.lock' \
  --exclude '/ai_config.json' \
  --exclude '/.env' \
  --exclude '/.env.*' \
  --exclude '/curation_data/backups/' \
  --exclude '/curation_data/cache_backups/' \
  --exclude '/curation_data/checkpoints.sqlite' \
  --exclude '/PRIVATE_SNAPSHOT.md' \
  --exclude '/SNAPSHOT_FILE_MANIFEST.tsv' \
  "$ROOT/" "$TMP_DIR/"

if [[ -d "$RUNTIME_ROOT" && "$RUNTIME_ROOT" != "$ROOT" ]]; then
  echo "Overlaying current operational data from runtime: $RUNTIME_ROOT"

  for runtime_dir in \
    results \
    curation_data \
    strategy_briefing \
    agent_chat_threads \
    agent_runs \
    agent_knowledge \
    task_runs
  do
    if [[ ! -d "$RUNTIME_ROOT/$runtime_dir" ]]; then
      continue
    fi
    mkdir -p "$TMP_DIR/$runtime_dir"
    rsync -a --delete \
      --exclude '__pycache__/' \
      --exclude '*.pyc' \
      --exclude '*.pyo' \
      --exclude '*.log' \
      --exclude '*.pid' \
      --exclude '*.lock' \
      --exclude 'backups/' \
      --exclude 'cache_backups/' \
      --exclude 'checkpoints.sqlite' \
      --exclude 'checkpoints.sqlite-shm' \
      --exclude 'checkpoints.sqlite-wal' \
      "$RUNTIME_ROOT/$runtime_dir/" "$TMP_DIR/$runtime_dir/"
  done

  # The web report library reads root-level Word files. The persistent runtime,
  # not the development checkout, is authoritative for this generated state.
  find "$TMP_DIR" -maxdepth 1 -type f -name '*.docx' -delete
  rsync -a \
    --include='/*.docx' \
    --exclude='/*' \
    "$RUNTIME_ROOT/" "$TMP_DIR/"

  # Overlay root-level generated indexes and audits without allowing an older
  # runtime copy to replace application source code.
  rsync -a \
    --include='/carrier_performance_*.json' \
    --include='/company_metrics*.json' \
    --include='/coverage_report.tsv' \
    --include='/final_audit.md' \
    --include='/feishu_latest_*.json' \
    --include='/report_file_metadata.json' \
    --include='/run_log*.json' \
    --include='/run_log*.tsv' \
    --include='/scheduler_state.json' \
    --include='/weekly_report*.json' \
    --include='/weekly_report*.md' \
    --include='/weekly_report*.html' \
    --exclude='/*' \
    "$RUNTIME_ROOT/" "$TMP_DIR/"
fi

CHECKPOINT_SOURCE="$ROOT/curation_data/checkpoints.sqlite"
if [[ -f "$RUNTIME_ROOT/curation_data/checkpoints.sqlite" ]]; then
  CHECKPOINT_SOURCE="$RUNTIME_ROOT/curation_data/checkpoints.sqlite"
fi
if [[ -f "$CHECKPOINT_SOURCE" ]]; then
  mkdir -p "$TMP_DIR/curation_data"
  sqlite3 "$CHECKPOINT_SOURCE" \
    ".backup '$TMP_DIR/curation_data/checkpoints.sqlite'"
  CHECKPOINT_BYTES="$(wc -c < "$TMP_DIR/curation_data/checkpoints.sqlite" | tr -d ' ')"
  if (( CHECKPOINT_BYTES > 95000000 )); then
    echo "Compressing large SQLite snapshot (${CHECKPOINT_BYTES} bytes) for GitHub..."
    gzip -9 -f "$TMP_DIR/curation_data/checkpoints.sqlite"
    COMPRESSED_CHECKPOINT_BYTES="$(wc -c < "$TMP_DIR/curation_data/checkpoints.sqlite.gz" | tr -d ' ')"
    if (( COMPRESSED_CHECKPOINT_BYTES > 95000000 )); then
      echo "Compressed checkpoint is still large (${COMPRESSED_CHECKPOINT_BYTES} bytes); splitting it into GitHub-safe parts..."
      split -b 85000000 -d -a 3 \
        "$TMP_DIR/curation_data/checkpoints.sqlite.gz" \
        "$TMP_DIR/curation_data/checkpoints.sqlite.gz.part-"
      rm "$TMP_DIR/curation_data/checkpoints.sqlite.gz"
      cat > "$TMP_DIR/curation_data/checkpoints.sqlite.RESTORE.md" <<'EOF'
# Restore the split curation checkpoint

The private snapshot split the compressed SQLite checkpoint only to stay below
GitHub's per-file size limit. Reassemble it without modifying the part files:

```bash
cat checkpoints.sqlite.gz.part-* > checkpoints.sqlite.gz
gzip -dk checkpoints.sqlite.gz
```
EOF
      while IFS= read -r -d '' checkpoint_part; do
        PART_BYTES="$(wc -c < "$checkpoint_part" | tr -d ' ')"
        if (( PART_BYTES > 95000000 )); then
          echo "Refusing to push: checkpoint part is still too large (${PART_BYTES} bytes)." >&2
          exit 1
        fi
      done < <(find "$TMP_DIR/curation_data" -maxdepth 1 -type f -name 'checkpoints.sqlite.gz.part-*' -print0)
    fi
  fi
fi

cat > "$TMP_DIR/PRIVATE_SNAPSHOT.md" <<EOF
# Private complete-project snapshot

- Source directory: local CMHK project workspace
- Runtime data overlay: $RUNTIME_ROOT
- Generated at: $(date '+%Y-%m-%d %H:%M:%S %z')
- Public development repository: AlexLIAOPOLY/cmhk-competitive-intelligence
- Private snapshot repository: AlexLIAOPOLY/cmhk-public-crawl-private
- Previous private main: $OLD_MAIN
- Rollback branch: $BACKUP_BRANCH

This snapshot includes project source, documents, current structured data, evidence cache, Agent knowledge and operational records. It excludes credentials, local runtimes, models, audio/cache output, temporary files, logs and historical backup directories.

SNAPSHOT_FILE_MANIFEST.tsv records the copied source bytes before Git line-ending normalization.
EOF

MANIFEST="$TMP_DIR/SNAPSHOT_FILE_MANIFEST.tsv"
printf 'path\tbytes\tsha256\n' > "$MANIFEST"
while IFS= read -r -d '' file; do
  relative="${file#"$TMP_DIR/"}"
  bytes="$(wc -c < "$file" | tr -d ' ')"
  digest="$(shasum -a 256 "$file" | awk '{print $1}')"
  printf '%s\t%s\t%s\n' "$relative" "$bytes" "$digest" >> "$MANIFEST"
done < <(find "$TMP_DIR" -type f ! -path "$TMP_DIR/.git/*" ! -path "$MANIFEST" -print0 | sort -z)

if [[ -f "$ROOT/ai_config.json" ]]; then
  INTERNAL_KEY="$(jq -er '[.. | objects | .apiKey? // empty] | map(select(type == "string" and length > 0)) | first // empty' "$ROOT/ai_config.json" 2>/dev/null || true)"
  if [[ -n "$INTERNAL_KEY" ]] && rg -F --quiet --hidden --glob '!.git/**' "$INTERNAL_KEY" "$TMP_DIR"; then
    echo "Refusing to push: the internal API key was found in snapshot content." >&2
    exit 1
  fi
  unset INTERNAL_KEY
fi

git -C "$TMP_DIR" add -f -A
TREE="$(git -C "$TMP_DIR" write-tree)"
NEW_COMMIT="$(printf 'Sync complete local project snapshot\n' | git -C "$TMP_DIR" commit-tree "$TREE" -p "$OLD_MAIN")"

REMOTE_MAIN="$(git_net ls-remote "$PRIVATE_URL" "refs/heads/$PRIVATE_MAIN" | awk '{print $1}')"
if [[ "$REMOTE_MAIN" != "$OLD_MAIN" ]]; then
  echo "Private main changed during synchronization; refusing to overwrite it." >&2
  exit 1
fi

git_net -C "$TMP_DIR" push origin "$NEW_COMMIT:refs/heads/$PRIVATE_MAIN"

echo "Synchronization complete."
echo "Public/private code branch: $BRANCH"
echo "Private main snapshot: $NEW_COMMIT"
echo "Rollback branch: $BACKUP_BRANCH"
