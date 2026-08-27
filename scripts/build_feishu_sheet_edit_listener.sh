#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GO_BIN="${CMHK_GO_BIN:-$(command -v go || true)}"
OUTPUT="${CMHK_FEISHU_SHEET_EDIT_LISTENER_BIN:-$ROOT/var/bin/lark-cli-drive}"
LARK_CLI_COMMIT="c8f06cd167fe352bf75a02f04a304875b9a68a2d"
SOURCE_DIR="${CMHK_LARK_CLI_SOURCE_DIR:-}"
cleanup_dir=""
tmp=""

cleanup() {
  [[ -z "$tmp" ]] || rm -f "$tmp"
  if [[ -n "$cleanup_dir" && -d "$cleanup_dir" ]]; then
    find "$cleanup_dir" -depth -delete
  fi
}
trap cleanup EXIT

if [[ -z "$GO_BIN" || ! -x "$GO_BIN" ]]; then
  echo "Go compiler not found; set CMHK_GO_BIN to an executable Go toolchain" >&2
  exit 1
fi

if [[ -z "$SOURCE_DIR" ]]; then
  cleanup_dir="$(mktemp -d "${TMPDIR:-/tmp}/cmhk-lark-cli.XXXXXX")"
  SOURCE_DIR="$cleanup_dir/source"
  git clone --quiet --filter=blob:none https://github.com/larksuite/cli.git "$SOURCE_DIR"
  git -C "$SOURCE_DIR" checkout --quiet "$LARK_CLI_COMMIT"
fi

git -C "$SOURCE_DIR" apply --check "$ROOT/patches/lark-cli-drive-file-edit.patch"
git -C "$SOURCE_DIR" apply "$ROOT/patches/lark-cli-drive-file-edit.patch"

mkdir -p "$(dirname "$OUTPUT")"
tmp="$OUTPUT.tmp.$$"
(
  cd "$SOURCE_DIR"
  "$GO_BIN" build -trimpath -o "$tmp" .
)
chmod 700 "$tmp"
mv -f "$tmp" "$OUTPUT"
tmp=""
echo "$OUTPUT"
