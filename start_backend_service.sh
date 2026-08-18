#!/usr/bin/env bash
set -euo pipefail

LABEL="com.liaowang.cmhk-web-app"
DOMAIN="gui/$(id -u)"
SOURCE="/Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/cmhk_public_crawl"
cp "$SOURCE/$LABEL.plist" "$PLIST"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  # Strategic-news scans currently execute in the Web process. Reloading that
  # process mid-scan turns a healthy crawl into an interrupted retry, so an
  # already-loaded service must go through the task-aware reload gate. Runtime
  # files are synchronized only after the gate is idle as well.
  "$SOURCE/scripts/safe_reload_web_app.sh" "$SOURCE/sync_app_runtime.sh"
else
  "$SOURCE/sync_app_runtime.sh"
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
  launchctl kickstart "$DOMAIN/$LABEL"
fi

echo "CMHK APP service started: http://127.0.0.1:8765/"
