#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATIC_DIR = ROOT / "web" / "static"
INTELLIGENCE_SNAPSHOT_SCRIPT = ROOT / "scripts" / "build_intelligence_static_snapshot.js"
DATA_DIR = ROOT / "strategy_briefing"
STATE_PATH = DATA_DIR / "dashboard_pages_publish_state.json"
LOCK_PATH = DATA_DIR / "dashboard_pages_publish.lock"
HKT = ZoneInfo("Asia/Hong_Kong")
DEFAULT_REPOSITORY = "https://github.com/AlexLIAOPOLY/cmhk-competitive-intelligence.git"
DEFAULT_PUBLIC_URL = "https://alexliaopoly.github.io/cmhk-competitive-intelligence/"
DEFAULT_INTELLIGENCE_SOURCE_URL = "http://127.0.0.1:8765/"
PUBLIC_STATIC_FILES = (
    "app.js",
    "auth-client.js",
    "company-data.js",
    "confirm-dialog.css",
    "confirm-dialog.js",
    "leadership-board.css",
    "news-review-sheet.css",
    "news-review-sheet.js",
    "organization-admin.css",
    "organization-admin.js",
    "responsive-layout-hardening.css",
    "styles.css",
    "workspace-tabs.css",
    "workspace-tabs.js",
)

PUBLIC_SNAPSHOT_BOOTSTRAP = r'''(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const root = new URL(document.baseURI.includes("/static/") ? "../" : "./", document.baseURI);
  const snapshotRoutes = new Map([
    ["/api/status", "static-data/status.json"],
    ["/api/company-metrics", "static-data/company-metrics.json"],
    ["/api/executive-intelligence", "static-data/executive-intelligence.json"],
    ["/api/strategic-briefs", "strategic-briefs.json"],
    ["/api/project-incidents", "static-data/project-incidents.json"],
    ["/api/crawl-runs", "static-data/crawl-runs.json"],
    ["/api/task-runs", "static-data/task-runs.json"],
    ["/api/scheduler-overview", "static-data/scheduler-overview.json"],
    ["/api/news-review-sheet", "static-data/news-review-sheet.json"],
    ["/api/weekly-report-preview", "static-data/weekly-report-preview.json"],
    ["/api/subscriptions", "static-data/subscriptions.json"],
    ["/api/auth/admin/users", "static-data/organization-users.json"],
    ["/api/auth/admin/audit", "static-data/organization-audit.json"],
  ]);
  const lookupRoutes = new Map([
    ["/api/crawl-run-log", ["static-data/crawl-run-details.json", "details"]],
    ["/api/task-run-log", ["static-data/task-run-details.json", "details"]],
  ]);
  const inlineRoutes = new Map([
    ["/api/auth/me", {
      ok: true,
      authenticated: true,
      user: {
        name: "公开快照",
        role: "VIEWER",
        roleLabel: "只读",
        permissions: { modules: {
          dashboard: true, monitoring: true, competitor: true, news: true,
          weekly: true, performance: true, review: true, log: true, fault: true,
          subscriptions: true, ai: true, organization: true,
        } },
      },
    }],
    ["/api/agent-datasets", { ok: true, datasets: [] }],
    ["/api/agent-memory", { ok: true, memories: [] }],
    ["/api/agent-skills", { ok: true, skills: [] }],
    ["/api/agent-trace", { ok: true, events: [] }],
    ["/api/ai-config", { ok: true, config: { provider: "", base_url: "", model: "", has_api_key: false } }],
    ["/api/ai-models", { ok: true, models: [] }],
    ["/api/chat-starters", { ok: true, starters: [] }],
    ["/api/chat-threads", { ok: true, threads: [] }],
  ]);
  const snapshotCache = new Map();

  function jsonResponse(payload, status = 200) {
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  async function lookupSnapshot(route, requestUrl) {
    const [relative, collectionKey] = lookupRoutes.get(route);
    if (!snapshotCache.has(relative)) {
      snapshotCache.set(relative, nativeFetch(new URL(relative, root), { cache: "no-store" }).then((response) => response.json()));
    }
    const payload = await snapshotCache.get(relative);
    const id = requestUrl.searchParams.get("id") || "";
    const item = payload?.[collectionKey]?.[id];
    return item
      ? jsonResponse(item)
      : jsonResponse({ ok: false, error: "该历史记录未包含在公开快照中。" }, 404);
  }

  window.CMHK_PUBLIC_SNAPSHOT = Object.freeze({ readOnly: true });
  window.fetch = function publicSnapshotFetch(input, init = {}) {
    const requestUrl = new URL(typeof input === "string" ? input : input.url, window.location.href);
    const method = String(init.method || (typeof input !== "string" && input.method) || "GET").toUpperCase();
    if (requestUrl.origin === window.location.origin && requestUrl.pathname.startsWith("/static/")) {
      const relative = requestUrl.pathname.slice("/static/".length);
      return nativeFetch(new URL(`static/${relative}${requestUrl.search}`, root), init);
    }
    if (!requestUrl.pathname.startsWith("/api/")) return nativeFetch(input, init);
    const route = requestUrl.pathname;
    if (method === "GET" && snapshotRoutes.has(route)) {
      return nativeFetch(new URL(snapshotRoutes.get(route), root), { cache: "no-store" });
    }
    if (method === "GET" && lookupRoutes.has(route)) return lookupSnapshot(route, requestUrl);
    if (inlineRoutes.has(route) && (method === "GET" || route === "/api/ai-models")) {
      return Promise.resolve(jsonResponse(inlineRoutes.get(route)));
    }
    return Promise.resolve(jsonResponse({ ok: false, error: "公开网页是只读快照，请在 CMHK 内网主页执行此操作。" }, 403));
  };

  function lockPrivateControls() {
    document.body.classList.add("public-snapshot");
    document.querySelectorAll([
      "#crawlButtonSecondary", "#generateButtonSecondary", "#generatePerformanceButton",
      "#aiSettingsButton", "#composerUploadFileButton", "#composerUploadImageButton",
      "[data-generate-report]", "[data-intelligence-insight-refresh]",
      "[data-intelligence-relation-refresh]", "[data-refresh-fault]",
    ].join(",")).forEach((item) => {
      item.hidden = true;
      item.setAttribute("aria-hidden", "true");
    });
    document.querySelectorAll(".strategy-ticker-footer a").forEach((item) => item.hidden = true);
    document.querySelectorAll("#subscriptionAdmin button, #subscriptionAdmin input, #subscriptionAdmin select").forEach((item) => {
      item.disabled = true;
      item.setAttribute("aria-disabled", "true");
    });
    document.querySelectorAll('[data-workspace-panel="competitor"] button, [data-workspace-panel="competitor"] input, [data-workspace-panel="competitor"] select').forEach((item) => {
      item.disabled = true;
      item.setAttribute("aria-disabled", "true");
    });
    document.querySelectorAll("#organizationAdmin [data-directory-open], #organizationAdmin [data-delete-user], #organizationAdmin .organization-save-bar").forEach((item) => {
      item.hidden = true;
      item.setAttribute("aria-hidden", "true");
    });
    document.querySelectorAll("#organizationAdmin [data-role], #organizationAdmin [data-status], #organizationAdmin [data-module]").forEach((item) => {
      item.disabled = true;
      item.setAttribute("aria-disabled", "true");
    });
    const competitorInsight = document.querySelector("#competitorInsight");
    const competitorInsightList = competitorInsight?.querySelector("[data-competitor-insight-list]");
    const fixedCompetitorInsights = [
      "稳定。HKBN两年均为0.907百万户，HKT由1.474升至1.488百万户，差距从约0.567扩至约0.581百万户，显示头部集中态势微幅强化。",
      "HKBN规模持平且动能停滞，HKT以约1.488百万户保持领先并延续微增，两者位置稳固，但HKBN的零增长可能反映其客户获取或留存承压。",
      "HKT的规模优势扩大或强化其网络投入与变现基础，HKBN持平则可能限制其规模竞争弹性，对客户留存策略的依赖度上升；数据锚点为2025年HKBN 0.907百万户。",
    ];
    const renderedCompetitorInsight = competitorInsightList
      ? Array.from(competitorInsightList.querySelectorAll("li span")).map((item) => item.textContent).join("")
      : "";
    if (competitorInsightList && renderedCompetitorInsight !== fixedCompetitorInsights.join("")) {
      competitorInsight.classList.remove("is-loading", "is-streaming");
      competitorInsight.classList.add("is-ai");
      competitorInsight.setAttribute("aria-busy", "false");
      const insightStatus = competitorInsight.querySelector("[data-competitor-insight-status]");
      if (insightStatus) insightStatus.hidden = true;
      const insightBadge = competitorInsight.querySelector("[data-competitor-insight-badge]");
      if (insightBadge) insightBadge.textContent = "COMPETITIVE INSIGHT";
      competitorInsightList.replaceChildren(...fixedCompetitorInsights.map((copy, index) => {
        const item = document.createElement("li");
        const label = document.createElement("b");
        const text = document.createElement("span");
        label.textContent = ["竞争格局", "公司定位", "业务含义"][index];
        text.textContent = copy;
        item.append(label, text);
        return item;
      }));
    }
    ["weekly", "performance"].forEach((kind) => {
      const reportPanel = document.querySelector(`[data-workspace-panel="${kind}"]`);
      const latestReportRow = reportPanel?.querySelector('.workspace-report-host .file-row[data-path]');
      if (latestReportRow && reportPanel.querySelector('[data-report-preview].is-placeholder') && !reportPanel.dataset.publicAutoPreviewed) {
        reportPanel.dataset.publicAutoPreviewed = "true";
        latestReportRow.click();
      }
    });
  }
  function startPrivateControlLock() {
    lockPrivateControls();
    new MutationObserver(lockPrivateControls).observe(document.documentElement, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startPrivateControlLock, { once: true });
  } else {
    startPrivateControlLock();
  }
})();
'''


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    environment_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        environment.pop(name, None)
    if environment_overrides:
        environment.update(environment_overrides)
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=environment,
        text=True,
        capture_output=True,
        check=check,
    )


def _git(*parts: str) -> list[str]:
    return ["git", "-c", "http.proxy=", "-c", "https.proxy=", *parts]


def _read_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


def _now_iso() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _public_news_payload() -> dict[str, Any]:
    from strategic_briefing import public_snapshot

    snapshot = public_snapshot()
    published_path = DATA_DIR / "published.json"
    try:
        published_payload = json.loads(published_path.read_text(encoding="utf-8"))
        generated_at = str(published_payload.get("updated_at") or "")
    except (OSError, json.JSONDecodeError, AttributeError):
        generated_at = ""
    items: list[dict[str, Any]] = []
    for item in (snapshot.get("items") or [])[:8]:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                key: item.get(key)
                for key in (
                    "id",
                    "title",
                    "summary",
                    "category",
                    "source_url",
                    "published_at",
                )
            }
        )
    return {"ok": True, "generated_at": generated_at, "items": items}


def _build_fresh_intelligence_snapshot(destination: Path) -> dict[str, str]:
    if not INTELLIGENCE_SNAPSHOT_SCRIPT.is_file():
        raise RuntimeError(f"missing intelligence snapshot builder: {INTELLIGENCE_SNAPSHOT_SCRIPT}")
    source_url = os.environ.get(
        "CMHK_INTELLIGENCE_SOURCE_URL",
        DEFAULT_INTELLIGENCE_SOURCE_URL,
    ).strip()
    if not source_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("intelligence snapshot source must be a local runtime URL")
    result = _run(
        ["node", str(INTELLIGENCE_SNAPSHOT_SCRIPT)],
        cwd=ROOT,
        environment_overrides={
            "CMHK_INTELLIGENCE_SOURCE_URL": source_url,
            "CMHK_INTELLIGENCE_SNAPSHOT_DIR": str(destination),
        },
    )
    required = (destination / "index.html", destination / "intelligence.js")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"intelligence snapshot builder omitted required files: {missing}")
    return {
        "source_url": source_url,
        "output_dir": str(destination),
        "builder_output": (result.stdout or "").strip()[-1000:],
    }


def _local_source_url() -> str:
    source_url = os.environ.get(
        "CMHK_INTELLIGENCE_SOURCE_URL",
        DEFAULT_INTELLIGENCE_SOURCE_URL,
    ).strip()
    if not source_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("public snapshot source must be a local runtime URL")
    return source_url.rstrip("/") + "/"


def _fetch_local_json(
    source_url: str,
    endpoint: str,
    *,
    cookie_jar: Path | None = None,
) -> dict[str, Any]:
    command = [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--max-time",
        "30",
    ]
    if cookie_jar is not None:
        command.extend(["--cookie", str(cookie_jar)])
    command.append(source_url.rstrip("/") + endpoint)
    response = _run(command)
    payload = json.loads(response.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"snapshot endpoint did not return an object: {endpoint}")
    return payload


def _open_local_snapshot_session(source_url: str, cookie_jar: Path) -> None:
    """Authenticate the unattended loopback publisher when runtime login is enabled."""
    config = _fetch_local_json(source_url, "/api/auth/config")
    if not config.get("requireLogin"):
        return
    accounts = [item for item in config.get("devAccounts") or [] if isinstance(item, dict)]
    admin = next(
        (
            item
            for item in accounts
            if item.get("role") == "ADMIN" and item.get("status") == "active"
        ),
        None,
    )
    account = str((admin or {}).get("account") or "").strip()
    if not account:
        raise RuntimeError(
            "local snapshot publisher requires an active loopback ADMIN development account"
        )
    response = _run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "30",
            "--cookie-jar",
            str(cookie_jar),
            "--header",
            "Content-Type: application/json; charset=utf-8",
            "--data",
            json.dumps({"account": account}, ensure_ascii=False),
            source_url.rstrip("/") + "/api/auth/dev-login",
        ]
    )
    payload = json.loads(response.stdout)
    if not isinstance(payload, dict) or not payload.get("ok") or not cookie_jar.is_file():
        raise RuntimeError("local snapshot publisher could not establish its runtime session")


def _scrub_public_value(value: Any, *, key: str = "") -> Any:
    blocked_key_fragments = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "email",
        "local_path",
        "open_id",
        "password",
        "phone",
        "secret",
        "token",
        "trace",
        "user_id",
    )
    lowered_key = key.lower()
    if any(fragment in lowered_key for fragment in blocked_key_fragments):
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child_value in value.items():
            cleaned = _scrub_public_value(child_value, key=str(child_key))
            if cleaned is not None:
                result[str(child_key)] = cleaned
        return result
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _scrub_public_value(item, key=key)) is not None
        ]
    if isinstance(value, str):
        lowered = value.lower()
        if any(
            marker in lowered
            for marker in (
                "/users/",
                "127.0.0.1",
                "localhost",
                "192.168.",
                "0.0.0.0",
                "feishu.cn/sheets/",
            )
        ):
            return ""
    return value


def _fetch_optional_public_snapshot(fetch: Any, endpoint: str) -> dict[str, Any]:
    """Return an empty safe snapshot when a non-core live preview is busy."""
    try:
        return fetch(endpoint)
    except Exception:
        return {}


def _build_public_runtime_snapshots(source_url: str) -> dict[str, dict[str, Any]]:
    cookie_dir = tempfile.TemporaryDirectory(prefix="cmhk-public-snapshot-session-")
    cookie_jar = Path(cookie_dir.name) / "cookies.txt"
    _open_local_snapshot_session(source_url, cookie_jar)
    fetch = lambda endpoint: _fetch_local_json(
        source_url,
        endpoint,
        cookie_jar=cookie_jar,
    )
    live_status = fetch("/api/health").get("status") or {}
    live_briefs = fetch("/api/strategic-briefs")
    public_briefs = dict(_public_news_payload())
    monitor = live_briefs.get("monitor") if isinstance(live_briefs, dict) else {}
    if isinstance(monitor, dict):
        public_briefs["monitor"] = {
            "status": "snapshot",
            "scan_times": list(monitor.get("scan_times") or [])[:4],
            "last_error": "",
        }
    public_status = {
        "ok": True,
        "status": {
            "results": _scrub_public_value(live_status.get("results") or {}),
            "visuals": _scrub_public_value(live_status.get("visuals") or {}),
            "settings": _scrub_public_value(live_status.get("settings") or {}),
            "tasks": {"runningCount": 0, "hasRunning": False},
            "latestOutputText": str(live_status.get("latestOutputText") or ""),
            "outputs": [
                _public_report_output(item)
                for item in (live_status.get("outputs") or [])
                if isinstance(item, dict)
            ],
        },
    }
    all_crawl_runs_payload = fetch("/api/crawl-runs?limit=500")
    public_crawl_runs = [
        _public_crawl_run(item)
        for item in (all_crawl_runs_payload.get("runs") or [])
        if isinstance(item, dict)
    ]
    strategic_runs = [item for item in public_crawl_runs if item.get("task_kind") == "strategic-news"]
    detail_limit = max(1, min(int(os.environ.get("CMHK_PUBLIC_NEWS_RUN_DETAIL_LIMIT", "64")), 120))
    crawl_run_details: dict[str, Any] = {}
    news_run_items: dict[str, Any] = {}
    for run in strategic_runs[:detail_limit]:
        run_id = str(run.get("crawl_run_id") or "")
        if not run_id:
            continue
        try:
            detail = fetch(f"/api/crawl-run-log?id={run_id}")
        except Exception:
            continue
        public_detail = _public_crawl_run_detail(detail)
        crawl_run_details[run_id] = public_detail
        if public_detail.get("newsItems"):
            news_run_items[run_id] = public_detail["newsItems"]

    task_runs_payload = fetch("/api/task-runs?limit=80")
    public_task_runs = [
        _public_task_run(item)
        for item in (task_runs_payload.get("tasks") or [])
        if isinstance(item, dict)
    ]
    task_run_details = {
        str(item.get("task_id") or item.get("task_run_id")): {
            "ok": True,
            "run": item,
            "content": "公开快照仅保留任务摘要；内部运行日志未公开。",
        }
        for item in public_task_runs
        if item.get("task_id") or item.get("task_run_id")
    }
    # These previews may be temporarily locked while strategic-news writes to
    # Feishu. They must not block unrelated performance snapshot publication.
    review_sheet_payload = _fetch_optional_public_snapshot(
        fetch,
        "/api/news-review-sheet",
    )
    review_sheet = _public_news_review_sheet(review_sheet_payload)
    # Keep the public module entry without exporting recipient, invitation,
    # delivery or schedule records from the internal runtime.
    subscriptions = _public_subscriptions({})
    incidents_payload = fetch("/api/project-incidents?limit=500")
    public_incidents = [
        _public_incident(item)
        for item in (incidents_payload.get("incidents") or [])
        if isinstance(item, dict)
    ]
    organization_users, organization_audit = _public_organization_snapshots(
        _fetch_optional_public_snapshot(fetch, "/api/auth/admin/users"),
        _fetch_optional_public_snapshot(fetch, "/api/auth/admin/audit?limit=200"),
        incidents_payload,
    )

    return {
        "status.json": public_status,
        "company-metrics.json": _scrub_public_value(
            fetch("/api/company-metrics")
        ),
        "executive-intelligence.json": _scrub_public_value(
            fetch("/api/executive-intelligence")
        ),
        "project-incidents.json": {"ok": True, "incidents": public_incidents, "total": len(public_incidents)},
        "crawl-runs.json": {"ok": True, "runs": public_crawl_runs, "total": len(public_crawl_runs), "truncated": False},
        "crawl-run-details.json": {"ok": True, "details": crawl_run_details},
        "task-runs.json": {"ok": True, "tasks": public_task_runs},
        "task-run-details.json": {"ok": True, "details": task_run_details},
        "scheduler-overview.json": _scrub_public_value(
            fetch("/api/scheduler-overview")
        ),
        "news-review-sheet.json": review_sheet,
        "weekly-report-preview.json": _scrub_public_value(
            _fetch_optional_public_snapshot(fetch, "/api/weekly-report-preview")
        ),
        "subscriptions.json": subscriptions,
        "organization-users.json": organization_users,
        "organization-audit.json": organization_audit,
        "news-run-items.json": news_run_items,
        "strategic-briefs.json": public_briefs,
    }


def _public_crawl_run(item: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "crawl_run_id", "trigger", "scope", "task_kind", "run_status", "phase",
        "progress_detail", "status_detail", "failure_stage", "heartbeat_at_hkt",
        "started_at_hkt", "completed_at_hkt", "crawl_return_code", "duration_ms",
        "final_audit", "curation", "operational_summary",
    )
    return _scrub_public_value({key: item.get(key) for key in allowed})


def _public_report_output(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or "未命名报告"),
        "path_str": str(item.get("name") or "未命名报告"),
        "note": str(item.get("note") or ""),
        "reportType": str(item.get("reportType") or ""),
        "size": int(item.get("size") or 0),
        "mtime": item.get("mtime"),
        "mtimeText": str(item.get("mtimeText") or ""),
        "url": "",
        "audio": None,
    }


def _copy_public_report_preview(report_name: str, static_destination: Path) -> Path | None:
    report_base = re.sub(r"\.docx$", "", report_name, flags=re.I)
    preview_key = base64.urlsafe_b64encode(report_base.encode("utf-8")).decode("ascii").rstrip("=")
    source = STATIC_DIR / "report-previews" / f"{preview_key}.pdf"
    if not source.is_file() or source.stat().st_size <= 0:
        return None
    destination_dir = static_destination / "report-previews"
    destination_dir.mkdir(exist_ok=True)
    destination = destination_dir / source.name
    shutil.copy2(source, destination)
    if destination.stat().st_size <= 0:
        raise RuntimeError(f"public report preview is empty after copy: {report_name}")
    return destination


def _public_crawl_run_detail(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(payload.get("ok", True)),
        "run": _public_crawl_run(payload.get("run") or {}),
        "lines": int(payload.get("lines") or 0),
        "newsItems": _scrub_public_value(payload.get("newsItems") or []),
        "discoveryItems": _scrub_public_value(payload.get("discoveryItems") or []),
        "aiReviewItems": _scrub_public_value(payload.get("aiReviewItems") or []),
        "dedupeItems": _scrub_public_value(payload.get("dedupeItems") or []),
    }


def _public_task_run(item: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "task_id", "task_run_id", "title", "kind", "kind_label", "scope",
        "run_status", "phase", "progress_detail", "status_detail", "started_at_hkt",
        "heartbeat_at_hkt", "completed_at_hkt", "duration_ms", "retry_count",
        "retry_index", "auto_recovered",
    )
    return _scrub_public_value({key: item.get(key) for key in allowed})


def _public_incident(item: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "incident_id", "task_id", "title", "kind", "kind_label", "scope",
        "incident_status", "run_status", "phase", "severity", "severity_label",
        "summary", "impact", "suggestions", "occurred_at_hkt", "started_at_hkt",
        "heartbeat_at_hkt", "completed_at_hkt", "handled_at_hkt",
    )
    return _scrub_public_value({key: item.get(key) for key in allowed})


def _public_news_review_sheet(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    return {
        "ok": True,
        "sheetTitle": str(payload.get("sheetTitle") or "新闻人工筛选快照"),
        "headers": [str(item) for item in (payload.get("headers") or [])],
        "editableColumns": [],
        "statusOptions": [str(item) for item in (payload.get("statusOptions") or [])],
        "updatedAt": str(payload.get("updatedAt") or ""),
        "rows": _scrub_public_value([item for item in rows[:500] if isinstance(item, dict)]),
        "readOnly": True,
    }


def _public_organization_snapshots(
    users_payload: dict[str, Any],
    audit_payload: dict[str, Any],
    incidents_payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    users = [item for item in (users_payload.get("users") or []) if isinstance(item, dict)]
    public_users: list[dict[str, Any]] = []
    member_ids: dict[str, str] = {}
    member_names: dict[str, str] = {}
    for index, user in enumerate(users, start=1):
        public_id = f"member-{index:03d}"
        original_id = str(user.get("id") or "")
        name = str(user.get("name") or user.get("account") or "未命名成员")
        if original_id:
            member_ids[original_id] = public_id
        member_names[name] = public_id
        modules = {
            str(key): bool(value)
            for key, value in (user.get("modules") or {}).items()
        }
        public_users.append(
            {
                "id": public_id,
                "name": name,
                "account": "",
                "email": "",
                "department": str(user.get("department") or ""),
                "title": str(user.get("title") or ""),
                "role": str(user.get("role") or ""),
                "roleLabel": str(user.get("roleLabel") or ""),
                "status": "disabled" if user.get("status") == "disabled" else "active",
                "authProvider": "feishu",
                "current": False,
                "developmentAccount": False,
                "modules": modules,
                "permissions": {"modules": modules},
            }
        )

    public_events: list[dict[str, Any]] = []
    incident_titles = {
        str(item.get("incident_id") or ""): str(item.get("title") or item.get("summary") or "")
        for item in ((incidents_payload or {}).get("incidents") or [])
        if isinstance(item, dict) and item.get("incident_id")
    }
    for index, event in enumerate(
        (item for item in (audit_payload.get("events") or []) if isinstance(item, dict)),
        start=1,
    ):
        actor_name = str(event.get("actor_name") or "未知用户")
        original_actor_id = str(event.get("actor_id") or "")
        original_target = str(event.get("target") or "")
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        target_name = str(details.get("name") or details.get("member_name") or "").strip()
        if event.get("action") == "organization.user_import":
            target_type = "member"
            target_label = target_name or "组织成员"
            target_member_id = member_names.get(target_label) or ""
        elif event.get("action") == "fault.mark_handled":
            target_type = "fault"
            target_label = incident_titles.get(original_target) or "故障记录"
            target_member_id = ""
        else:
            target_type = "record"
            target_label = target_name or "操作记录"
            target_member_id = ""
        public_events.append(
            {
                "id": f"event-{index:03d}",
                "at": str(event.get("at") or ""),
                "actor_id": member_ids.get(original_actor_id) or member_names.get(actor_name) or "",
                "actor_name": actor_name,
                "actor_role": str(event.get("actor_role") or ""),
                "action": str(event.get("action") or ""),
                "target": original_target,
                "target_type": target_type,
                "target_label": target_label,
                "target_member_id": target_member_id,
                "result": "failure" if event.get("result") == "failure" else "success",
                "details": {},
            }
        )

    public_users_payload = {
        "ok": True,
        "users": public_users,
        "departments": sorted({item["department"] for item in public_users if item["department"]}),
        "roles": _scrub_public_value(users_payload.get("roles") or {}),
        "modules": _scrub_public_value(users_payload.get("modules") or {}),
        "roleModules": _scrub_public_value(users_payload.get("roleModules") or {}),
        "readOnly": True,
    }
    return public_users_payload, {"ok": True, "events": public_events, "readOnly": True}


def _public_subscriptions(payload: dict[str, Any]) -> dict[str, Any]:
    _ = payload
    return {
        "ok": True,
        "readOnly": True,
        "subscribers": [],
        "candidates": [],
        "deliveries": [],
        "invitations": [],
    }


def _rewrite_static_css(source: str) -> str:
    return source.replace('url("/static/assets/', 'url("./assets/').replace(
        "url('/static/assets/", "url('./assets/"
    )


def _rewrite_root_javascript(source: str) -> str:
    return (
        source.replace('"/static/', '"./static/')
        .replace("'/static/", "'./static/")
        .replace("`/static/", "`./static/")
    )


def _readonly_module_html(title: str, message: str) -> str:
    safe_title = __import__("html").escape(title)
    safe_message = __import__("html").escape(message)
    template = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#06131e;color:#c8eaf4;font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.card{width:min(560px,calc(100% - 48px));padding:32px;border:1px solid rgba(84,205,232,.28);background:rgba(8,31,44,.82);box-shadow:0 18px 60px rgba(0,0,0,.24)}.eyebrow{margin:0 0 8px;color:#58c8df;font-size:12px;letter-spacing:.14em}h1{margin:0 0 12px;font-size:22px}p{margin:0;color:#83a8b5}</style></head>
<body><section class="card"><p class="eyebrow">PUBLIC READ-ONLY</p><h1>__TITLE__</h1><p>__MESSAGE__</p></section></body></html>"""
    return template.replace("__TITLE__", safe_title).replace("__MESSAGE__", safe_message)


def _build_site(
    destination: Path,
    *,
    intelligence_static_dir: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    source_url = _local_source_url()
    snapshots = _build_public_runtime_snapshots(source_url)

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/static/', 'href="./static/')
    html = html.replace('src="/static/', 'src="./static/')
    html = html.replace('href="/executive-dashboard-demo.html', 'href="./executive-dashboard-demo.html')
    html = html.replace('src="/executive-dashboard-demo.html', 'src="./executive-dashboard-demo.html')
    html = html.replace('class="brand-mark" href="/"', 'class="brand-mark" href="./"')
    html = html.replace(
        'data-src="./static/subscription-admin.html?v=12"',
        'data-src="./static/public-subscriptions.html"',
    )
    html = re.sub(
        r'src="\./static/workspace-tabs\.js\?v=[^"]+"',
        'src="./static/workspace-tabs.js?v=public-5"',
        html,
    )
    html = re.sub(
        r'<a href="https://cmhk-try\.feishu\.cn/sheets/[^\"]+"[^>]*>\s*监测规则\s*</a>',
        '<span class="public-snapshot-label">公开快照</span>',
        html,
    )
    html = html.replace(
        '    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
        '    <script src="./static/public-snapshot-bootstrap.js?v=5"></script>\n'
        '    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
    )
    html = html.replace(
        "<head>",
        '<head>\n    <meta name="cmhk-public-mode" content="read-only-snapshot" />',
        1,
    )
    (destination / "index.html").write_text(html, encoding="utf-8")

    static_destination = destination / "static"
    static_destination.mkdir()
    shutil.copytree(STATIC_DIR / "assets", static_destination / "assets")
    for name in PUBLIC_STATIC_FILES:
        source_path = STATIC_DIR / name
        content = source_path.read_text(encoding="utf-8")
        if source_path.suffix == ".css":
            content = _rewrite_static_css(content)
        elif source_path.suffix == ".js":
            content = _rewrite_root_javascript(content)
        if name == "workspace-tabs.js":
            content = content.replace(
                'competitorSelection: { companies: [], metric: "", years: 5 }',
                'competitorSelection: { companies: ["HKBN", "HKT"], metric: "consumer_broadband_customers", years: 5 }',
                1,
            )
            content = content.replace(
                'panel.innerHTML = `<div class="workspace-embedded-host" id="workspaceAiHost"></div>`;',
                'panel.innerHTML = `<iframe src="./static/public-ai.html" title="AI智能助手" style="display:block;width:100%;height:100%;border:0" loading="eager"></iframe>`;',
                1,
            )
        (static_destination / name).write_text(content, encoding="utf-8")
    (static_destination / "public-snapshot-bootstrap.js").write_text(
        PUBLIC_SNAPSHOT_BOOTSTRAP,
        encoding="utf-8",
    )
    (static_destination / "public-subscriptions.html").write_text(
        _readonly_module_html(
            "订阅与推送管理",
            "GitHub Pages 保留模块入口；收件人、推送记录及编辑操作不在公开快照展示。请在 CMHK 内网主页管理。",
        ),
        encoding="utf-8",
    )
    (static_destination / "public-ai.html").write_text(
        _readonly_module_html(
            "AI智能助手",
            "GitHub Pages 保留模块入口；对话、知识库及模型配置不在公开快照开放。请在 CMHK 内网主页使用。",
        ),
        encoding="utf-8",
    )

    report_outputs = ((snapshots.get("status.json") or {}).get("status") or {}).get("outputs", [])
    latest_reports = [
        next(
            (
                item for item in report_outputs
                if isinstance(item, dict) and item.get("reportType") == report_type
            ),
            None,
        )
        for report_type in ("weekly", "carrier-performance")
    ]
    for latest_report in (item for item in latest_reports if item):
        _copy_public_report_preview(
            str(latest_report.get("name") or ""),
            static_destination,
        )
    shutil.copy2(
        STATIC_DIR / "competitor-workbench-data.json",
        static_destination / "competitor-workbench-data.json",
    )
    (static_destination / "news-run-items.json").write_text(
        json.dumps(snapshots.get("news-run-items.json") or {}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    monitoring_html = (STATIC_DIR / "executive-dashboard-demo.html").read_text(encoding="utf-8")
    monitoring_html = monitoring_html.replace('href="/static/', 'href="./static/')
    monitoring_html = monitoring_html.replace('src="/static/', 'src="./static/')
    monitoring_html = monitoring_html.replace('class="brand" href="/"', 'class="brand" href="./"')
    (destination / "executive-dashboard-demo.html").write_text(
        monitoring_html,
        encoding="utf-8",
    )
    for name in (
        "executive-dashboard-demo.css",
        "executive-responsive-hardening.css",
        "executive-dashboard-demo.js",
    ):
        shutil.copy2(STATIC_DIR / name, static_destination / name)

    data_destination = destination / "static-data"
    data_destination.mkdir()
    for name, payload in snapshots.items():
        if name in {"strategic-briefs.json", "news-run-items.json"}:
            continue
        (data_destination / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (destination / ".nojekyll").touch()

    payload = dict(snapshots["strategic-briefs.json"])
    digest = hashlib.sha256()
    for path in sorted(item for item in destination.rglob("*") if item.is_file()):
        if path.name == ".DS_Store":
            continue
        digest.update(str(path.relative_to(destination)).encode("utf-8"))
        digest.update(path.read_bytes())
    site_version = digest.hexdigest()
    payload["site_version"] = site_version
    (destination / "strategic-briefs.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return site_version, payload


def _verify(public_url: str, site_version: str) -> None:
    target = public_url.rstrip("/") + "/strategic-briefs.json"
    last_error = ""
    for _ in range(24):
        try:
            response = _run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "20",
                    "--header",
                    "User-Agent: CMHK dashboard publisher",
                    target,
                ]
            )
            payload = json.loads(response.stdout)
            if payload.get("site_version") == site_version:
                return
            last_error = "deployed snapshot has not reached the expected version"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(5)
    raise RuntimeError(last_error or "public verification timed out")


def publish(*, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    repository = os.environ.get(
        "CMHK_DASHBOARD_PAGES_REPOSITORY",
        DEFAULT_REPOSITORY,
    ).strip()
    branch = os.environ.get("CMHK_DASHBOARD_PAGES_BRANCH", "gh-pages").strip()
    public_url = os.environ.get(
        "CMHK_DASHBOARD_PAGES_PUBLIC_URL",
        DEFAULT_PUBLIC_URL,
    ).strip()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "busy"}

        state = _read_state()
        state["last_started_at"] = _now_iso()
        _write_state(state)
        try:
            with tempfile.TemporaryDirectory(prefix="cmhk-dashboard-pages-") as temp:
                temp_root = Path(temp)
                generated = temp_root / "generated"
                site_version, payload = _build_site(generated)
                if not force and site_version == state.get("last_site_version"):
                    return {
                        "status": "unchanged",
                        "site_version": site_version,
                        "item_count": len(payload["items"]),
                        "public_url": public_url,
                        "snapshot_source_url": _local_source_url(),
                    }
                if dry_run:
                    return {
                        "status": "dry_run",
                        "site_version": site_version,
                        "item_count": len(payload["items"]),
                        "public_url": public_url,
                        "snapshot_source_url": _local_source_url(),
                    }

                checkout = temp_root / "checkout"
                _run(
                    _git(
                        "clone",
                        "--depth",
                        "1",
                        "--branch",
                        branch,
                        repository,
                        str(checkout),
                    )
                )
                for child in checkout.iterdir():
                    if child.name == ".git":
                        continue
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                for child in generated.iterdir():
                    target = checkout / child.name
                    if child.is_dir():
                        shutil.copytree(child, target)
                    else:
                        shutil.copy2(child, target)

                _run(_git("add", "-A"), cwd=checkout)
                changed = bool(
                    _run(_git("status", "--porcelain"), cwd=checkout).stdout.strip()
                )
                if changed:
                    _run(
                        _git("config", "user.name", "CMHK Dashboard Publisher"),
                        cwd=checkout,
                    )
                    _run(
                        _git(
                            "config",
                            "user.email",
                            "cmhk-dashboard@users.noreply.github.com",
                        ),
                        cwd=checkout,
                    )
                    _run(
                        _git("commit", "-m", "Update public dashboard snapshot"),
                        cwd=checkout,
                    )
                    _run(_git("push", "origin", branch), cwd=checkout)
                commit = _run(_git("rev-parse", "HEAD"), cwd=checkout).stdout.strip()
                _verify(public_url, site_version)
                result = {
                    "status": "published" if changed else "verified",
                    "site_version": site_version,
                    "item_count": len(payload["items"]),
                    "public_url": public_url,
                    "commit": commit,
                    "snapshot_source_url": _local_source_url(),
                }
                _write_state(
                    {
                        **state,
                        "last_site_version": site_version,
                        "last_published_at": _now_iso(),
                        "last_result": result,
                        "last_error": "",
                    }
                )
                return result
        except Exception as exc:
            _write_state(
                {
                    **state,
                    "last_error_at": _now_iso(),
                    "last_error": str(exc)[:1000],
                }
            )
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            publish(force=args.force, dry_run=args.dry_run),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
