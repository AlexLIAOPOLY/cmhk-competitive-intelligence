#!/usr/bin/env bash
set -euo pipefail

WEB_LABEL="com.liaowang.cmhk-web-app"
SCHEDULER_LABEL="com.liaowang.cmhk-frequency-scheduler"
QUEUE_LABEL="com.liaowang.cmhk-queued-web-reload"
DOMAIN="gui/$(id -u)"
TASKS_URL="${CMHK_TASK_RUNS_URL:-http://127.0.0.1:8765/api/task-runs?limit=100}"
CHECK_INTERVAL_SECONDS="${CMHK_RELOAD_CHECK_INTERVAL_SECONDS:-5}"
STATE_DIR="$HOME/Library/Application Support/CMHK"
REQUEST_FILE="$STATE_DIR/web-reload-requested"
INTERRUPT_FILE="$STATE_DIR/web-reload-interrupt-strategic"
STAGE_ROOT="$STATE_DIR/web-reload-releases"
QUEUE_LOCK_DIR="$STATE_DIR/web-reload-queue.lock"
RUNTIME="${CMHK_WEB_RUNTIME:-/Users/liaowang/cmhk_public_crawl_app}"
WEB_PLIST="$HOME/Library/LaunchAgents/$WEB_LABEL.plist"
SCHEDULER_PLIST="$HOME/Library/LaunchAgents/$SCHEDULER_LABEL.plist"
LOG_FILE="$HOME/Library/Logs/cmhk_public_crawl/queued-web-reload.log"

mkdir -p "$STATE_DIR" "$(dirname "$LOG_FILE")"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

queue_lock_acquired=0

acquire_queue_lock() {
  local existing_pid="" _attempt
  for _attempt in {1..120}; do
    if mkdir "$QUEUE_LOCK_DIR" 2>/dev/null; then
      printf '%s\n' "$$" > "$QUEUE_LOCK_DIR/pid"
      queue_lock_acquired=1
      return 0
    fi
    existing_pid="$(cat "$QUEUE_LOCK_DIR/pid" 2>/dev/null || true)"
    if [[ "$existing_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$existing_pid" 2>/dev/null; then
      rm -f "$QUEUE_LOCK_DIR/pid"
      rmdir "$QUEUE_LOCK_DIR" 2>/dev/null || true
      continue
    fi
    sleep 1
  done
  log "Timed out waiting for the Web reload queue lock."
  return 1
}

release_queue_lock() {
  if (( queue_lock_acquired == 1 )); then
    rm -f "$QUEUE_LOCK_DIR/pid"
    rmdir "$QUEUE_LOCK_DIR" 2>/dev/null || true
    queue_lock_acquired=0
  fi
}

delete_release_dir() {
  local candidate="$1" token
  token="${candidate##*/}"
  [[ "$token" =~ ^[0-9]{8}T[0-9]{6}-[0-9]+-[0-9]+$ ]] || return 1
  [[ "$candidate" == "$STAGE_ROOT/$token" ]] || return 1
  [[ -d "$candidate" && ! -L "$candidate" ]] || return 0
  find "$candidate" -depth -delete
}

running_strategic_tasks() {
  local payload
  if [[ "${CMHK_RELOAD_FORCE_INDEX_FALLBACK:-0}" != "1" ]] \
    && payload="$(/usr/bin/curl -fsS --max-time 3 "$TASKS_URL" 2>/dev/null)"; then
    printf '%s' "$payload" | /usr/bin/python3 -c '
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
    return
  fi
  # Once login is required, the local queue worker cannot anonymously call the
  # task API. Strategic crawls live in the crawl-run registry, not the general
  # task index. A missing or malformed registry returns non-zero so the caller
  # fails closed and preserves the current Web process.
  /usr/bin/python3 - "$RUNTIME/agent_knowledge/crawl_run_logs/index.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if isinstance(payload, dict):
    tasks = payload.get("tasks") or []
elif isinstance(payload, list):
    tasks = payload
else:
    raise TypeError("crawl-run registry must be a list or object")
print(sum(
    1
    for task in tasks
    if (task.get("task_kind") or task.get("kind")) == "strategic-news"
    and task.get("run_status") == "running"
))
PY
}

running_frequency_pipeline_tasks() {
  if /usr/bin/pgrep -f "$RUNTIME/crawl.py" >/dev/null 2>&1 \
    || /usr/bin/pgrep -f "$RUNTIME/run_data_curation.py" >/dev/null 2>&1; then
    printf '1\n'
  else
    printf '0\n'
  fi
}

if [[ "${1:-}" == "--count-running-strategic" ]]; then
  running_strategic_tasks
  exit
fi

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
  local requested_token="$1" deadline_epoch first_count second_count frequency_count
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
    frequency_count="$(running_frequency_pipeline_tasks)"
    if (( frequency_count > 0 )); then
      sleep "$CHECK_INTERVAL_SECONDS"
      continue
    fi
    sleep "$CHECK_INTERVAL_SECONDS"
    if ! second_count="$(running_strategic_tasks)"; then
      continue
    fi
    if (( second_count == 0 )); then
      frequency_count="$(running_frequency_pipeline_tasks)"
      if (( frequency_count == 0 )); then
        return 0
      fi
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
    bootstrap_ok=0
    for _bootstrap_attempt in {1..5}; do
      if /bin/launchctl bootstrap "$DOMAIN" "$WEB_PLIST" >> "$LOG_FILE" 2>&1; then
        bootstrap_ok=1
        break
      fi
      sleep 1
    done
    if (( bootstrap_ok == 0 )); then
      log "Unable to bootstrap $WEB_LABEL after five attempts; request remains queued."
      exit 1
    fi
  else
    /bin/launchctl kickstart -k "$DOMAIN/$WEB_LABEL"
  fi

  for _attempt in {1..30}; do
    if /usr/bin/curl -fsS --max-time 3 http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  # scheduler.py is a long-lived process, so copying a new file is not enough.
  # Restart it only after all production crawl/audit workers are idle.
  if /bin/launchctl print "$DOMAIN/$SCHEDULER_LABEL" >/dev/null 2>&1; then
    /bin/launchctl kickstart -k "$DOMAIN/$SCHEDULER_LABEL" >> "$LOG_FILE" 2>&1
  elif [[ -f "$SCHEDULER_PLIST" ]]; then
    /bin/launchctl bootstrap "$DOMAIN" "$SCHEDULER_PLIST" >> "$LOG_FILE" 2>&1
  else
    log "Frequency scheduler plist is missing; request remains queued."
    exit 1
  fi

  # Serialize request publication and completion so an arriving request cannot
  # be removed by the worker after it compared the previous token.
  acquire_queue_lock
  current_token="$(cat "$REQUEST_FILE" 2>/dev/null || true)"
  if [[ "$current_token" == "$requested_token" ]]; then
    rm -f "$REQUEST_FILE"
    if interrupt_requested "$requested_token"; then
      rm -f "$INTERRUPT_FILE"
    fi
    delete_release_dir "$release_dir"
    log "Request $requested_token activated; queue is empty."
  else
    delete_release_dir "$release_dir"
    log "A newer request is queued; worker will coalesce and activate it next."
  fi
  release_queue_lock
done

log "Queued Web reload worker exiting."
# `launchctl submit` jobs otherwise remain scheduled after a clean exit and
# relaunch every ThrottleInterval. Removing this one-shot worker keeps the
# queue dormant until a caller records the next request.
/bin/launchctl remove "$QUEUE_LABEL" >/dev/null 2>&1 || true
