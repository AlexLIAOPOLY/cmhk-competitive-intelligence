#!/usr/bin/env bash
set -euo pipefail

LABEL="com.liaowang.cmhk-web-app"
DOMAIN="gui/$(id -u)"
SOURCE="/Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/cmhk_public_crawl"
"$SOURCE/sync_app_runtime.sh"
cp "$SOURCE/$LABEL.plist" "$PLIST"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl enable "$DOMAIN/$LABEL"
for attempt in {1..10}; do
  if bootstrap_output="$(launchctl bootstrap "$DOMAIN" "$PLIST" 2>&1)"; then
    break
  fi
  if [[ "$attempt" == "10" ]]; then
    echo "$bootstrap_output" >&2
    echo "Unable to bootstrap $LABEL after $attempt attempts." >&2
    exit 1
  fi
  sleep 1
done
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "CMHK APP service started: http://127.0.0.1:8765/"
