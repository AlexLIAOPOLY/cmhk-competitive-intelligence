from __future__ import annotations
import base64
import csv
import ipaddress
import json
import logging
import mimetypes
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
import crawl
from cmhk.crawl.run_registry import (
    heartbeat_crawl_run,
    latest_crawl_run_summary,
    load_crawl_run_log,
    load_index as load_crawl_run_index,
    load_run_history as load_crawl_run_history,
    mark_crawl_run_interrupted,
    reconcile_interrupted_crawl_runs,
    register_crawl_run,
    start_crawl_run,
)
from cmhk.ai.ai_config import INTERNAL_AI_BASE_URL, is_internal_ai_base_url, load_ai_config, save_ai_config
from contextvars import copy_context
from cmhk.ai.ai_dispatch import AIQueueBusy, AIRequestCancelled, WAIT_CALLBACK, capacity_status, request_context
from cmhk.ai.ai_key_rotation import open_llm_request
from cmhk.ai.ai_rate_limit import reset_internal_ai_priority, set_internal_ai_priority, wait_for_internal_ai_slot
from cmhk.data.company_metrics import build_company_metrics_payload
from cmhk.data_releases import default_release_root, resolve_release_request
from cmhk.intranet import intranet_access_urls
from executive_company_benchmarks import build_company_benchmarks
from cmhk.crawl.extractors import row_fields
from cmhk.agent.rag import ask_llm_with_rag, estimate_tokens, list_knowledge_datasets, stream_llm_with_rag
from agent import available_agent_skills, stream_agent
from cmhk.agent.memory import delete_memory, load_memories
from cmhk.agent.production import dataset_lineage, list_agent_runs
from cmhk.reporting.charts import generated_chart_path
from cmhk.reporting.docx_editor import load_docx_for_editor, save_editor_document, sha256_file
from cmhk.reporting.report_naming import report_display_name
from tts_service import (
    AUDIO_DIR,
    audio_info_for_report,
    audio_paths_for_report,
    delete_audio_for_report,
    rename_audio_for_report,
    synthesize_report_audio,
)
from cmhk.services.subscriptions import (
    FREQUENCY_LABELS,
    NEWS_CATEGORY_LABELS,
    REPORT_CADENCE_LABEL,
    REPORT_MODE_LABELS,
    SubscriptionService,
    encode_strategic_news_digest,
    filter_news_by_categories,
    news_category_summary,
)
from cmhk.auth.service import AuthService
from cmhk.integrations.feishu_sheet_edit_events import (
    TARGET_SPREADSHEET_TOKEN,
    sheet_edit_events,
)
from cmhk.integrations.feishu_runtime import lark_cli_env, resolve_lark_cli
from project_monitor_card_actions import CardActionHandler
from cmhk.reporting.operational_pdf import generate_operational_report_pdf, report_filename
ROOT = Path(__file__).resolve().parent
AUTH = AuthService(ROOT)
QUARTERLY_RELEASE_ROOT = default_release_root(ROOT)
NEWS_REVIEW_AUDIT_STATE_PATH = AUTH.state_dir / "news-review-sheet-audit-state.json"
NEWS_REVIEW_ACTOR_OVERRIDES_PATH = AUTH.state_dir / "news-review-actor-overrides.json"
NEWS_REVIEW_MENTION_IDENTITIES_PATH = (
    AUTH.state_dir / "news-review-mention-identities.json"
)
NEWS_REVIEW_SHEET_EDIT_EVENT_PATH = AUTH.state_dir / "feishu-sheet-edit-events.jsonl"
NEWS_SELECTION_DECISIONS_PATH = ROOT / "agent_knowledge" / "news_selection_agent" / "decisions.jsonl"
NEWS_AUTO_SCREENING_ACTOR = {
    "id": "news-auto-screening-bot",
    "name": "新闻自动初筛机器人",
    "avatarUrl": "",
    "role": "SYSTEM",
}
NEWS_REVIEW_SCREENER_COLUMN = 0
NEWS_REVIEW_APP_STATUS_COLUMN = 1
NEWS_REVIEW_WEEKLY_STATUS_COLUMN = 2
NEWS_REVIEW_SYNC_STATUS_COLUMN = 3
NEWS_REVIEW_TITLE_COLUMN = 7
NEWS_REVIEW_DECISION_COLUMNS = (
    NEWS_REVIEW_APP_STATUS_COLUMN,
    NEWS_REVIEW_WEEKLY_STATUS_COLUMN,
)
NEWS_REVIEW_EVENT_SETTLE_SECONDS = max(
    0,
    int(os.environ.get("CMHK_NEWS_REVIEW_EVENT_SETTLE_SECONDS", "90")),
)
NEWS_REVIEW_CHANGESET_MAX_REVISIONS = max(
    20,
    int(os.environ.get("CMHK_NEWS_REVIEW_CHANGESET_MAX_REVISIONS", "200")),
)
NEWS_REVIEW_AUDIT_LOCK = threading.RLock()
NEWS_REVIEW_MENTION_IDENTITY_LOCK = threading.RLock()
NEWS_REVIEW_ACTOR_BACKFILL_LOCK = threading.Lock()
NEWS_REVIEW_ACTOR_BACKFILL_LAST_ATTEMPT = 0.0
NEWS_REVIEW_SCREENER_MONITOR_LOCK = threading.Lock()
NEWS_REVIEW_SCREENER_MONITOR_STARTED = False
CRAWL_PIPELINE_LOCK = threading.Lock()
CRAWL_PIPELINE_STATE: dict[str, object] = {}
INTELLIGENCE_INSIGHT_REFRESH_LOCK = threading.Lock()
SCHEDULER_OVERVIEW_LOCK = threading.Lock()
SCHEDULER_OVERVIEW_CACHE: dict[str, object] = {}
SCHEDULER_OVERVIEW_CACHE_SECONDS = 90
SUBSCRIPTION_PUSH_JOBS_PATH = ROOT / "var" / "subscriptions" / "manual_push_jobs.json"
SUBSCRIPTION_PUSH_JOBS_LOCK = threading.Lock()
TASK_HEARTBEAT_INTERVAL_SECONDS = 10
STATIC_DIR = ROOT / "web" / "static"
COMPETITOR_WORKBENCH_DATA_PATH = STATIC_DIR / "competitor-workbench-data.json"
RESULTS_DIR = ROOT / "results"
CURATION_LATEST_PATH = ROOT / "curation_data" / "latest.json"
CURATION_CANDIDATE_FACTS_PATH = ROOT / "curation_data" / "candidate_facts.jsonl"
CURATION_AGENT_TRACE_PATH = ROOT / "curation_data" / "agent_trace.jsonl"
STRATEGIC_BRIEFING_DIR = ROOT / "strategy_briefing"
STRATEGIC_BRIEFING_RUNS_DIR = STRATEGIC_BRIEFING_DIR / "runs"
LOCAL_TEMPLATE_PATH = Path("/Users/liaowang/Downloads/模板.docx")
REPO_TEMPLATE_PATH = ROOT / "weekly_report_template.docx"
TEMPLATE_PATH = LOCAL_TEMPLATE_PATH if LOCAL_TEMPLATE_PATH.exists() else REPO_TEMPLATE_PATH
REPORT_FILE_RE = re.compile(
    r"^\d{1,2}月\d{1,2}日周报(?:（(?:草稿，)?截至\d{1,2}月\d{1,2}日）)?(?: \(\d+\))?\.docx$"
)
REPORT_METADATA_PATH = ROOT / "data/reporting/report_file_metadata.json"
REPORT_EDITOR_LOCK = threading.RLock()
EXCLUDED_REPORT_NAMES = {
    "test_out.docx",
    "weekly_report.docx",
    "weekly_report_from_word_template.docx",
    "weekly_report_template.docx",
    "carrier_performance_template.docx",
    "模板.docx",
}
REFERENCE_FILES = {"weekly_report.md", "weekly_report.html", "final_audit.md", "coverage_report.tsv", "run_log.tsv"}
UPLOAD_DATASET_PREFIX = "user-upload"
UPLOAD_ALLOWED_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".json", ".docx", ".pdf"}
UPLOAD_MAX_BYTES = 8 * 1024 * 1024
CHAT_IMAGE_MAX_BYTES = 8 * 1024 * 1024
CHAT_AUDIO_MAX_BYTES = 20 * 1024 * 1024
CHAT_STT_MODEL = (os.environ.get("CMHK_STT_MODEL") or "Qwen3ASR").strip()
CHAT_AUDIO_MIME_EXTENSIONS = {
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/mpga": "mpga",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}
CHAT_THREADS_DIR = ROOT / "agent_chat_threads"
CHAT_THREADS_PATH = CHAT_THREADS_DIR / "threads.json"
CHAT_THREADS_LOCK = threading.Lock()
CHAT_TITLE_TASK_LOCK = threading.Lock()
CHAT_TITLE_PENDING: dict[str, str] = {}
CHAT_TITLE_ACTIVE: set[str] = set()
CHAT_APPROVAL_LOCK = threading.Lock()
CHAT_STREAM_SESSION_LOCK = threading.RLock()
CHAT_STREAM_SESSIONS: dict[str, "ChatStreamSession"] = {}
CHAT_STREAM_SESSION_TTL_SECONDS = 30 * 60
CHAT_STREAM_HEARTBEAT_SECONDS = 10

class ChatStreamSession:
    """Keep one Agent turn alive while browsers disconnect and reconnect."""

    def __init__(self, request_id: str, fingerprint: str, producer_factory) -> None:
        self.request_id = request_id
        self.fingerprint = fingerprint
        self.session_id = uuid.uuid4().hex
        self.events: list[dict[str, object]] = []
        self.condition = threading.Condition()
        self.complete = False
        self.last_touched = time.monotonic()
        self.producer_factory = producer_factory

    def start(self) -> None:
        threading.Thread(
            target=copy_context().run,
            args=(self._run,),
            name=f"chat-stream-{self.request_id[:32]}",
            daemon=True,
        ).start()

    def _append(self, event: dict[str, object]) -> None:
        with self.condition:
            sequenced = dict(event)
            sequenced["seq"] = len(self.events) + 1
            self.events.append(sequenced)
            self.last_touched = time.monotonic()
            if sequenced.get("type") == "done":
                self.complete = True
            self.condition.notify_all()

    def _run(self) -> None:
        saw_done = False
        wait_token = WAIT_CALLBACK.set(lambda remaining: self._append({
            "type": "status", "text": "AI 请求较多，仍在排队，请稍候。",
        }))
        try:
            for event in self.producer_factory():
                normalized = dict(event or {})
                self._append(normalized)
                if normalized.get("type") == "done":
                    saw_done = True
                    break
        except Exception as exc:
            logging.exception("chat stream producer failed for %s", self.request_id)
            self._append({"type": "error", "text": str(exc)})
        finally:
            WAIT_CALLBACK.reset(wait_token)
            if not saw_done:
                self._append({"type": "done"})

    def events_after(self, sequence: int):
        cursor = max(0, sequence)
        while True:
            heartbeat = False
            with self.condition:
                self.last_touched = time.monotonic()
                while cursor >= len(self.events) and not self.complete:
                    notified = self.condition.wait(timeout=CHAT_STREAM_HEARTBEAT_SECONDS)
                    self.last_touched = time.monotonic()
                    if not notified and cursor >= len(self.events) and not self.complete:
                        heartbeat = True
                        break
                pending = self.events[cursor:]
                finished = self.complete and cursor + len(pending) >= len(self.events)
            if heartbeat:
                # Ephemeral keepalive: it is not buffered and therefore does
                # not consume a sequence number or duplicate on reconnect.
                yield {"type": "heartbeat", "seq": cursor}
                continue
            for event in pending:
                cursor = int(event.get("seq") or cursor + 1)
                yield event
            if finished:
                return


def _chat_stream_fingerprint(payload: dict) -> str:
    stable = {key: value for key, value in payload.items() if key != "resumeAfter"}
    return json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def get_or_create_chat_stream_session(
    request_id: str,
    payload: dict,
    producer_factory,
) -> ChatStreamSession:
    fingerprint = _chat_stream_fingerprint(payload)
    now = time.monotonic()
    with CHAT_STREAM_SESSION_LOCK:
        expired = [
            key
            for key, session in CHAT_STREAM_SESSIONS.items()
            if session.complete and now - session.last_touched > CHAT_STREAM_SESSION_TTL_SECONDS
        ]
        for key in expired:
            CHAT_STREAM_SESSIONS.pop(key, None)
        existing = CHAT_STREAM_SESSIONS.get(request_id)
        if existing:
            if existing.fingerprint != fingerprint:
                raise ValueError("同一请求标识不能用于不同对话内容")
            return existing
        session = ChatStreamSession(request_id, fingerprint, producer_factory)
        CHAT_STREAM_SESSIONS[request_id] = session
        session.start()
        return session

CHAT_APPROVAL_WAITERS: dict[tuple[str, str], dict[str, object]] = {}
CHAT_STARTER_POOL = (
    {
        "icon": "performance",
        "tone": "blue",
        "title": "查询香港资费数据",
        "detail": "例：csl、3HK、SmarTone 5G 月费",
        "prompt": "请查询并对比香港 csl、1O1O、3HK 和 SmarTone 当前 5G 套餐的月费、本地数据量、合约期和促销优惠，用表格展示并标明来源。",
    },
    {
        "icon": "performance",
        "tone": "violet",
        "title": "分析香港电信趋势",
        "detail": "例：移动用户、数据用量与宽频接入",
        "prompt": "请基于香港官方与已核验数据，分析近十年移动用户数、移动数据用量、宽频接入线和 5G 发展趋势，说明增速、拐点及其对香港电信市场的影响，并用图表展示。",
    },
    {
        "icon": "cloud",
        "tone": "teal",
        "title": "预测香港市场走势",
        "detail": "例：移动数据用量、5G 与宽频趋势",
        "prompt": "请基于已核验的香港历史数据，预测未来四个季度的移动数据用量、移动用户数、5G 发展和宽频接入趋势，给出基准、乐观和谨慎情景，并说明预测依据、不确定性和风险。",
    },
    {
        "icon": "policy",
        "tone": "orange",
        "title": "解读香港政策影响",
        "detail": "例：频谱分配、SIM 实名制与消费者保护",
        "prompt": "请梳理香港近期频谱分配、5G、SIM 实名制、电信监管和消费者保护政策的变化，分析对 CMHK 产品、网络、营销和运营的影响，并提出应对建议。",
    },
)
SUBSCRIPTION_OPERATION_ACTIONS = {
    "publish": "subscription.card_send",
    "update": "subscription.settings_update",
    "resetSubscriber": "subscription.settings_reset",
    "updateReportSchedule": "subscription.report_schedule_update",
    "updatePerformanceSchedule": "subscription.performance_schedule_update",
    "updateNewsSchedule": "subscription.news_schedule_update",
    "setWeeklyReportPreference": "subscription.weekly_report_preference_update",
    "setPerformanceReportPreference": "subscription.performance_report_preference_update",
    "refreshDirectory": "subscription.directory_refresh",
    "addCandidates": "subscription.candidate_add",
    "invite": "subscription.invite_send",
    "inviteTarget": "subscription.invite_send",
    "pushLatest": "subscription.content_send",
    "pushLatestAsync": "subscription.content_send",
    "push": "subscription.content_send",
}

class ReportEditConflict(RuntimeError):
    """The report changed after the editor loaded its source revision."""

TASK_RUNS_DIR = ROOT / "task_runs"
TASK_RUNS_LOG_DIR = TASK_RUNS_DIR / "logs"
TASK_RUNS_INDEX_PATH = TASK_RUNS_DIR / "index.json"
PROJECT_MONITOR_STATE_PATH = ROOT / "var" / "project_monitor" / "state.json"
PROJECT_MONITOR_ACTIONS_PATH = ROOT / "var" / "project_monitor" / "card_actions.json"
PROJECT_MONITOR_WEB_ACTIONS_PATH = ROOT / "var" / "project_monitor" / "web_actions.jsonl"
UI_RUNTIME_INCIDENTS_PATH = ROOT / "var" / "ui_runtime_incidents.json"
TASK_RUNS_LOCK = threading.Lock()
UI_RUNTIME_INCIDENTS_LOCK = threading.Lock()
GENERAL_TASK_MAX_AUTO_RETRIES = max(1, int(os.environ.get("CMHK_TASK_AUTO_RETRY_MAX", "3")))
GENERAL_TASK_RETRY_DELAY_SECONDS = max(
    1.0, float(os.environ.get("CMHK_TASK_AUTO_RETRY_DELAY_SECONDS", "5"))
)

class AppHTTPServer(ThreadingHTTPServer):
    # The stdlib's small connection backlog drops bursts before AI can queue.
    request_queue_size = 128



# Bind implementations to this module, including when launched as __main__.
from cmhk.web import subscriptions as _subscriptions
_subscriptions.bind(sys.modules[__name__])
from cmhk.web import chat_history as _chat_history
_chat_history.bind(sys.modules[__name__])
from cmhk.web import chat_media as _chat_media
_chat_media.bind(sys.modules[__name__])
from cmhk.web import reports as _reports
_reports.bind(sys.modules[__name__])
from cmhk.web import datasets as _datasets
_datasets.bind(sys.modules[__name__])
from cmhk.web import transport as _transport
_transport.bind(sys.modules[__name__])
from cmhk.web import chat_approvals as _chat_approvals
_chat_approvals.bind(sys.modules[__name__])
from cmhk.web import overview as _overview
_overview.bind(sys.modules[__name__])
from cmhk.web import news_status as _news_status
_news_status.bind(sys.modules[__name__])
from cmhk.web import pipelines as _pipelines
_pipelines.bind(sys.modules[__name__])
from cmhk.web import subscription_jobs as _subscription_jobs
_subscription_jobs.bind(sys.modules[__name__])
from cmhk.web import task_runs as _task_runs
_task_runs.bind(sys.modules[__name__])
from cmhk.web import review_actors as _review_actors
_review_actors.bind(sys.modules[__name__])
from cmhk.web import review_audit as _review_audit
_review_audit.bind(sys.modules[__name__])
from cmhk.web import task_monitor as _task_monitor
_task_monitor.bind(sys.modules[__name__])

_ORIGINAL_WRITE_SSE = write_sse
_ORIGINAL_STREAM_REPORT_GENERATION = stream_report_generation
from cmhk.web import lifecycle as _lifecycle
_lifecycle.bind(sys.modules[__name__])
from cmhk.web import http_read as _http_read
_http_read.bind(sys.modules[__name__])
from cmhk.web import http_write as _http_write
_http_write.bind(sys.modules[__name__])
from cmhk.web import http_resources as _http_resources
_http_resources.bind(sys.modules[__name__])


class AppHandler(ReadRoutes, WriteRoutes, ResourceResponses, BaseHTTPRequestHandler):
    server_version = "WeeklyReportUI/1.0"


def main() -> None:
    corrected_footprints = repair_news_auto_screening_audit()
    if corrected_footprints:
        print(f"已校正 {corrected_footprints} 条新闻自动初筛机器人身份足迹", flush=True)
    backfilled_footprints = backfill_news_auto_screening_audit()
    if backfilled_footprints:
        print(f"已补录 {backfilled_footprints} 条新闻自动初筛操作足迹", flush=True)
    interrupted = reconcile_interrupted_crawl_runs()
    if interrupted:
        print(f"Reconciled {len(interrupted)} interrupted crawl run(s)", flush=True)
    interrupted_tasks = reconcile_interrupted_general_tasks()
    if interrupted_tasks:
        print(f"Reconciled {len(interrupted_tasks)} interrupted report task(s)", flush=True)
    recovery_candidates = pending_interrupted_general_task_retries()
    if recovery_candidates:
        scheduled_retries = schedule_interrupted_general_task_retries(recovery_candidates)
        print(f"Scheduled {len(scheduled_retries)} interrupted task retry/retries", flush=True)
    corrected_tasks = reconcile_misclassified_general_tasks()
    if corrected_tasks:
        print(f"Corrected {len(corrected_tasks)} misclassified report task(s)", flush=True)
    start_scheduler_with_backend()
    try:
        import news_vote_service

        news_vote_service.ensure_started()
    except Exception as exc:
        print(f"Feishu event listener failed to start: {exc}", flush=True)
    start_news_review_screener_monitor()
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = AppHTTPServer((host, port), AppHandler)
    print(f"Weekly report UI: http://{host}:{port}", flush=True)
    access_urls = intranet_access_urls(port, host=host)
    if access_urls:
        print("公司内网访问地址（可发给同事）：", flush=True)
        for access_url in access_urls:
            print(f"  {access_url}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
