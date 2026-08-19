#!/usr/bin/env bash
set -euo pipefail

WEB_LABEL="com.liaowang.cmhk-web-app"
QUEUE_LABEL="com.liaowang.cmhk-queued-web-reload"
DOMAIN="gui/$(id -u)"
TASKS_URL="${CMHK_TASK_RUNS_URL:-http://127.0.0.1:8765/api/task-runs?limit=100}"
CHECK_INTERVAL_SECONDS="${CMHK_RELOAD_CHECK_INTERVAL_SECONDS:-5}"
STATE_DIR="$HOME/Library/Application Support/CMHK"
REQUEST_FILE="$STATE_DIR/web-reload-requested"
INTERRUPT_FILE="$STATE_DIR/web-reload-interrupt-strategic"
STAGE_ROOT="$STATE_DIR/web-reload-releases"
RUNTIME="/Users/liaowang/cmhk_public_crawl_app"
WEB_PLIST="$HOME/Library/LaunchAgents/$WEB_LABEL.plist"
LOG_FILE="$HOME/Library/Logs/cmhk_public_crawl/queued-web-reload.log"

mkdir -p "$STATE_DIR" "$(dirname "$LOG_FILE")"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

running_strategic_tasks() {
  /usr/bin/curl -fsS --max-time 3 "$TASKS_URL" | /usr/bin/python3 -c '
import json
import sys

payload = json.load(sys.stdin)
tasks = payload.get("tasks") or []
print(sum(
    1
    for task in tasks
    if task.get("kind") == "strategic-news"
    and task.get("run_status") == "running"
))
'
}

next_midnight_epoch() {
  TZ=Asia/Hong_Kong /usr/bin/python3 -c '
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

zone = ZoneInfo("Asia/Hong_Kong")
now = datetime.now(zone)
deadline = datetime.combine(now.date() + timedelta(days=1), time(0, 0), zone)
print(int(deadline.timestamp()))
'
}

interrupt_requested() {
  local requested_token="$1"
  [[ -f "$INTERRUPT_FILE" ]] && [[ "$(cat "$INTERRUPT_FILE" 2>/dev/null || true)" == "$requested_token" ]]
}

wait_until_idle_or_midnight() {
  local requested_token="$1" deadline_epoch first_count second_count
  deadline_epoch="$(next_midnight_epoch)"
  while true; do
    if interrupt_requested "$requested_token"; then
      log "Explicit strategic-task restart requested for $requested_token; activating the queued release now."
      return 0
    fi
    if (( $(date +%s) >= deadline_epoch )); then
      log "Daily midnight cutoff reached; queued release may interrupt the remaining strategic task."
      return 0
    fi
    if ! first_count="$(running_strategic_tasks)"; then
      log "Task API unavailable; preserving the current Web process."
      sleep "$CHECK_INTERVAL_SECONDS"
      continue
    fi
    if (( first_count > 0 )); then
      sleep "$CHECK_INTERVAL_SECONDS"
      continue
    fi
    sleep "$CHECK_INTERVAL_SECONDS"
    if ! second_count="$(running_strategic_tasks)"; then
      continue
    fi
    if (( second_count == 0 )); then
      return 0
    fi
  done
}

log "Queued Web reload worker started."
while [[ -f "$REQUEST_FILE" ]]; do
  requested_token="$(cat "$REQUEST_FILE" 2>/dev/null || true)"
  [[ -n "$requested_token" ]] || break
  wait_until_idle_or_midnight "$requested_token"
  requested_token="$(cat "$REQUEST_FILE" 2>/dev/null || true)"
  [[ -n "$requested_token" ]] || break
  if [[ ! "$requested_token" =~ ^[0-9]{8}T[0-9]{6}-[0-9]+-[0-9]+$ ]]; then
    log "Invalid request token; refusing to resolve a release path."
    exit 1
  fi
  release_dir="$STAGE_ROOT/$requested_token"
  if [[ ! -d "$release_dir" ]]; then
    log "Release directory missing for $requested_token; leaving request queued."
    sleep "$CHECK_INTERVAL_SECONDS"
    continue
  fi

  log "Activating coalesced request $requested_token."
  /usr/bin/rsync -a "$release_dir/" "$RUNTIME/" >> "$LOG_FILE" 2>&1
  if [[ -f "$release_dir/$WEB_LABEL.plist" ]]; then
    /usr/bin/plutil -lint "$release_dir/$WEB_LABEL.plist" >> "$LOG_FILE" 2>&1
    /bin/cp "$release_dir/$WEB_LABEL.plist" "$WEB_PLIST"
    /bin/chmod 600 "$WEB_PLIST"
    /bin/launchctl bootout "$DOMAIN/$WEB_LABEL" >> "$LOG_FILE" 2>&1 || true
    /bin/launchctl bootstrap "$DOMAIN" "$WEB_PLIST" >> "$LOG_FILE" 2>&1
  else
    /bin/launchctl kickstart -k "$DOMAIN/$WEB_LABEL"
  fi

  for _attempt in {1..30}; do
    if /usr/bin/curl -fsS --max-time 3 http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  current_token="$(cat "$REQUEST_FILE" 2>/dev/null || true)"
  if [[ "$current_token" == "$requested_token" ]]; then
    rm -f "$REQUEST_FILE"
    if interrupt_requested "$requested_token"; then
      rm -f "$INTERRUPT_FILE"
    fi
    rm -rf "$release_dir"
    log "Request $requested_token activated; queue is empty."
  else
    log "A newer request is queued; worker will coalesce and activate it next."
  fi
done

log "Queued Web reload worker exiting."
# `launchctl submit` jobs otherwise remain scheduled after a clean exit and
# relaunch every ThrottleInterval. Removing this one-shot worker keeps the
# queue dormant until a caller records the next request.
/bin/launchctl remove "$QUEUE_LABEL" >/dev/null 2>&1 || true
