#!/usr/bin/env bash
set -euo pipefail

SOURCE="/Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521"
LABEL="com.liaowang.cmhk-queued-web-reload"
DOMAIN="gui/$(id -u)"
STATE_DIR="$HOME/Library/Application Support/CMHK"
REQUEST_FILE="$STATE_DIR/web-reload-requested"
INTERRUPT_FILE="$STATE_DIR/web-reload-interrupt-strategic"
STAGE_ROOT="$STATE_DIR/web-reload-releases"
QUEUE_LOCK_DIR="$STATE_DIR/web-reload-queue.lock"
WORKER_COPY="$STATE_DIR/queued_web_app_reload_worker.sh"
LOG_FILE="$HOME/Library/Logs/cmhk_public_crawl/queued-web-reload.log"

mkdir -p "$STATE_DIR" "$STAGE_ROOT" "$(dirname "$LOG_FILE")"
chmod 700 "$STATE_DIR" "$STAGE_ROOT"

interrupt_strategic=0
overlay_files=()
overlay_commit=""
while (( $# > 0 )); do
  case "$1" in
    --interrupt-strategic)
      interrupt_strategic=1
      shift
      ;;
    --overlay-file)
      shift
      if (( $# == 0 )); then
        echo "--overlay-file requires a workspace-relative file path." >&2
        exit 2
      fi
      overlay_file="$1"
      if [[ "$overlay_file" == /* || "$overlay_file" == *".."* || ! -f "$SOURCE/$overlay_file" ]]; then
        echo "Invalid overlay file: $overlay_file" >&2
        exit 2
      fi
      overlay_files+=("$overlay_file")
      shift
      ;;
    --overlay-commit)
      shift
      if (( $# == 0 )); then
        echo "--overlay-commit requires a Git commit or ref." >&2
        exit 2
      fi
      overlay_commit="$(git -C "$SOURCE" rev-parse --verify "$1^{commit}")"
      if [[ ! "$overlay_commit" =~ ^[0-9a-f]{40,64}$ ]]; then
        echo "Invalid overlay commit: $1" >&2
        exit 2
      fi
      shift
      ;;
    *)
      echo "Usage: $0 [--interrupt-strategic] [--overlay-commit REF] [--overlay-file RELATIVE_FILE ...]" >&2
      exit 2
      ;;
  esac
done

if [[ -n "$overlay_commit" ]] && (( ${#overlay_files[@]} == 0 )); then
  echo "--overlay-commit requires at least one --overlay-file." >&2
  exit 2
fi

queue_lock_acquired=0
request_published=0
release_dir=""

valid_release_token() {
  [[ "$1" =~ ^[0-9]{8}T[0-9]{6}-[0-9]+-[0-9]+$ ]]
}

delete_release_dir() {
  local candidate="$1" token
  token="${candidate##*/}"
  valid_release_token "$token" || return 1
  [[ "$candidate" == "$STAGE_ROOT/$token" ]] || return 1
  [[ -d "$candidate" && ! -L "$candidate" ]] || return 0
  find "$candidate" -depth -delete
}

release_queue_lock() {
  if (( queue_lock_acquired == 1 )); then
    rm -f "$QUEUE_LOCK_DIR/pid"
    rmdir "$QUEUE_LOCK_DIR" 2>/dev/null || true
    queue_lock_acquired=0
  fi
}

cleanup_queue_exit() {
  local exit_status=$?
  trap - EXIT
  if (( request_published == 0 )) && [[ -n "$release_dir" ]]; then
    delete_release_dir "$release_dir" || true
  fi
  release_queue_lock
  exit "$exit_status"
}

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
  echo "Timed out waiting for the Web reload queue lock." >&2
  return 1
}

prune_superseded_releases() {
  local previous_token="$1" current_token="$2" candidate token
  while IFS= read -r -d '' candidate; do
    token="${candidate##*/}"
    if [[ "$token" == "$previous_token" || "$token" == "$current_token" ]]; then
      continue
    fi
    delete_release_dir "$candidate"
  done < <(find "$STAGE_ROOT" -mindepth 1 -maxdepth 1 -type d -print0)
}

trap cleanup_queue_exit EXIT
acquire_queue_lock

request_token="$(date '+%Y%m%dT%H%M%S')-$$-${RANDOM}"
release_dir="$STAGE_ROOT/$request_token"
mkdir -p "$release_dir"

# Build an immutable release while the caller still has Desktop access. The
# background LaunchAgent only reads this private staging directory, never the
# live workspace, and the running Web process never sees a half-copied release.
if (( ${#overlay_files[@]} > 0 )); then
  for overlay_file in "${overlay_files[@]}"; do
    mkdir -p "$release_dir/$(dirname "$overlay_file")"
    if [[ -n "$overlay_commit" ]]; then
      if ! git -C "$SOURCE" cat-file -e "$overlay_commit:$overlay_file"; then
        echo "Overlay file is not present in commit $overlay_commit: $overlay_file" >&2
        exit 2
      fi
      git -C "$SOURCE" show "$overlay_commit:$overlay_file" > "$release_dir/$overlay_file"
    else
      rsync -a "$SOURCE/$overlay_file" "$release_dir/$overlay_file"
    fi
  done
else
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
  --exclude='agent_knowledge/requested_overview_010304_2016_2025/' \
  --exclude='results/' \
  --exclude='curation_data/' \
  --exclude='crawl_runs/' \
  --exclude='task_runs/' \
  --exclude='agent_runs/' \
  --exclude='artifacts/generated/' \
  --exclude='runtime/local/' \
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
fi

cp "$SOURCE/scripts/queued_web_app_reload_worker.sh" "$WORKER_COPY"
chmod 700 "$WORKER_COPY"
xattr -c "$WORKER_COPY" 2>/dev/null || true

temporary_request="$REQUEST_FILE.tmp.$$"
previous_token="$(cat "$REQUEST_FILE" 2>/dev/null || true)"
printf '%s\n' "$request_token" > "$temporary_request"
mv -f "$temporary_request" "$REQUEST_FILE"
request_published=1
if (( interrupt_strategic == 1 )); then
  temporary_interrupt="$INTERRUPT_FILE.tmp.$$"
  printf '%s\n' "$request_token" > "$temporary_interrupt"
  mv -f "$temporary_interrupt" "$INTERRUPT_FILE"
elif [[ -f "$INTERRUPT_FILE" ]] \
  && [[ "$(cat "$INTERRUPT_FILE" 2>/dev/null || true)" != "$request_token" ]]; then
  rm -f "$INTERRUPT_FILE"
fi

# The worker may already be activating the previously requested release, so
# preserve that token and the new token. Every other immutable staging copy is
# superseded and can be reclaimed immediately.
prune_superseded_releases "$previous_token" "$request_token"
release_queue_lock

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
