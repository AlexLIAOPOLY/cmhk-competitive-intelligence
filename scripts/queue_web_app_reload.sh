#!/usr/bin/env bash
set -euo pipefail

SOURCE="/Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521"
LABEL="com.liaowang.cmhk-queued-web-reload"
DOMAIN="gui/$(id -u)"
STATE_DIR="$HOME/Library/Application Support/CMHK"
REQUEST_FILE="$STATE_DIR/web-reload-requested"
STAGE_ROOT="$STATE_DIR/web-reload-releases"
WORKER_COPY="$STATE_DIR/queued_web_app_reload_worker.sh"
LOG_FILE="$HOME/Library/Logs/cmhk_public_crawl/queued-web-reload.log"

mkdir -p "$STATE_DIR" "$STAGE_ROOT" "$(dirname "$LOG_FILE")"
chmod 700 "$STATE_DIR" "$STAGE_ROOT"
request_token="$(date '+%Y%m%dT%H%M%S')-$$-${RANDOM}"
release_dir="$STAGE_ROOT/$request_token"
mkdir -p "$release_dir"

# Build an immutable release while the caller still has Desktop access. The
# background LaunchAgent only reads this private staging directory, never the
# live workspace, and the running Web process never sees a half-copied release.
rsync -a \
  --exclude='.git/' \
  --exclude='Codex/' \
  --exclude='agent_chat_threads/' \
  --exclude='strategy_briefing/' \
  --exclude='agent_knowledge/crawl_run_logs/' \
  --exclude='agent_knowledge/hk_competitor_product_tariffs/' \
  --exclude='agent_knowledge/quarterly_competitor_metrics_2026-06-18/' \
  --exclude='agent_knowledge/cloud_vendor_metrics_2026-06-17/' \
  --exclude='agent_knowledge/cmhk_macro_policy_2026-06-19/' \
  --exclude='agent_knowledge/executive_intelligence_refresh/' \
  --exclude='results/' \
  --exclude='curation_data/' \
  --exclude='crawl_runs/' \
  --exclude='task_runs/' \
  --exclude='agent_runs/' \
  --exclude='var/' \
  --exclude='run_log.json' \
  --exclude='run_log.tsv' \
  --exclude='final_audit.md' \
  --exclude='coverage_report.tsv' \
  --exclude='daily_validation.json' \
  --exclude='scheduler_state.json' \
  --exclude='scheduler_pending_run.json' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  "$SOURCE/" "$release_dir/"

mkdir -p "$release_dir/Codex/agent/skills"
rsync -a --delete \
  "$SOURCE/Codex/agent/skills/" \
  "$release_dir/Codex/agent/skills/"
if [[ -f "/Users/liaowang/Downloads/模板.docx" ]]; then
  cp "/Users/liaowang/Downloads/模板.docx" "$release_dir/weekly_report_template.docx"
fi

cp "$SOURCE/scripts/queued_web_app_reload_worker.sh" "$WORKER_COPY"
chmod 700 "$WORKER_COPY"
xattr -c "$WORKER_COPY" 2>/dev/null || true

temporary_request="$REQUEST_FILE.tmp.$$"
printf '%s\n' "$request_token" > "$temporary_request"
mv -f "$temporary_request" "$REQUEST_FILE"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Web reload request coalesced into the active background worker: $request_token"
  exit 0
fi

if ! launchctl submit -l "$LABEL" -- \
  /bin/bash "$WORKER_COPY"; then
  # Another caller may have submitted the same singleton between the print and
  # submit calls. Treat an observed running worker as a successful coalescing.
  if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "Unable to start queued Web reload worker; request remains at $REQUEST_FILE" >&2
    exit 1
  fi
fi

echo "Web reload queued in background: $request_token"
echo "Worker log: $LOG_FILE"
