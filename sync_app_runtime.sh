#!/usr/bin/env bash
set -euo pipefail

SOURCE="/Users/liaowang/Desktop/揭榜挂帅需求/cmhk_public_crawl_20260521"
RUNTIME="/Users/liaowang/cmhk_public_crawl_app"

mkdir -p "$RUNTIME"
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
  "$SOURCE/" "$RUNTIME/"

mkdir -p "$RUNTIME/Codex/agent/skills"
rsync -a --delete \
  "$SOURCE/Codex/agent/skills/" \
  "$RUNTIME/Codex/agent/skills/"

if [[ -f "/Users/liaowang/Downloads/模板.docx" ]]; then
  cp "/Users/liaowang/Downloads/模板.docx" "$RUNTIME/weekly_report_template.docx"
fi

echo "APP runtime synchronized to $RUNTIME"
