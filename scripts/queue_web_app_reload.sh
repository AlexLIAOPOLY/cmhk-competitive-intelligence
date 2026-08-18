#!/usr/bin/env bash
set -euo pipefail

SOURCE="/Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521"
LABEL="com.liaowang.cmhk-queued-web-reload"
DOMAIN="gui/$(id -u)"
STATE_DIR="$HOME/Library/Application Support/CMHK"
REQUEST_FILE="$STATE_DIR/web-reload-requested"
LOG_FILE="$HOME/Library/Logs/cmhk_public_crawl/queued-web-reload.log"

mkdir -p "$STATE_DIR" "$(dirname "$LOG_FILE")"
request_token="$(date '+%Y%m%dT%H%M%S')-$$-${RANDOM}"
temporary_request="$REQUEST_FILE.tmp.$$"
printf '%s\n' "$request_token" > "$temporary_request"
mv -f "$temporary_request" "$REQUEST_FILE"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Web reload request coalesced into the active background worker: $request_token"
  exit 0
fi

if ! launchctl submit -l "$LABEL" -- \
  /bin/bash "$SOURCE/scripts/queued_web_app_reload_worker.sh"; then
  # Another caller may have submitted the same singleton between the print and
  # submit calls. Treat an observed running worker as a successful coalescing.
  if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "Unable to start queued Web reload worker; request remains at $REQUEST_FILE" >&2
    exit 1
  fi
fi

echo "Web reload queued in background: $request_token"
echo "Worker log: $LOG_FILE"
