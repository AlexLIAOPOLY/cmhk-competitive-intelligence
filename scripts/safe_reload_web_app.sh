#!/usr/bin/env bash
set -euo pipefail

LABEL="${CMHK_WEB_APP_LABEL:-com.liaowang.cmhk-web-app}"
DOMAIN="gui/$(id -u)"
TASKS_URL="${CMHK_TASK_RUNS_URL:-http://127.0.0.1:8765/api/task-runs?limit=100}"
CHECK_INTERVAL_SECONDS="${CMHK_RELOAD_CHECK_INTERVAL_SECONDS:-5}"

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

echo "Waiting for strategic-news tasks to become idle before reloading $LABEL."
while true; do
  if ! first_count="$(running_strategic_tasks)"; then
    echo "Task API unavailable; preserving the current service and checking again."
    sleep "$CHECK_INTERVAL_SECONDS"
    continue
  fi
  if (( first_count > 0 )); then
    echo "Strategic-news tasks running: $first_count; reload remains queued."
    sleep "$CHECK_INTERVAL_SECONDS"
    continue
  fi

  sleep "$CHECK_INTERVAL_SECONDS"
  if ! second_count="$(running_strategic_tasks)"; then
    echo "Task API unavailable during confirmation; reload remains queued."
    continue
  fi
  if (( second_count > 0 )); then
    echo "A strategic-news task started during confirmation; reload remains queued."
    continue
  fi

  if (( $# > 0 )); then
    echo "Running the queued pre-reload preparation command."
    "$@"
  fi
  echo "No strategic-news task is running; reloading $LABEL."
  /bin/launchctl kickstart -k "$DOMAIN/$LABEL"
  exit 0
done
