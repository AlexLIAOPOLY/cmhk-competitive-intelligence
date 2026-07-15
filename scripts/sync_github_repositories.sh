#!/usr/bin/env bash
set -euo pipefail

PUBLIC_REMOTE="${PUBLIC_REMOTE:-origin}"
PRIVATE_REMOTE="${PRIVATE_REMOTE:-private}"
PRIVATE_MAIN="${PRIVATE_MAIN:-main}"
ROOT="$(git rev-parse --show-toplevel)"
BRANCH="${1:-$(git branch --show-current)}"

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

if [[ -f "$ROOT/curation_data/checkpoints.sqlite" ]]; then
  mkdir -p "$TMP_DIR/curation_data"
  sqlite3 "$ROOT/curation_data/checkpoints.sqlite" \
    ".backup '$TMP_DIR/curation_data/checkpoints.sqlite'"
fi

cat > "$TMP_DIR/PRIVATE_SNAPSHOT.md" <<EOF
# Private complete-project snapshot

- Source directory: local CMHK project workspace
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
