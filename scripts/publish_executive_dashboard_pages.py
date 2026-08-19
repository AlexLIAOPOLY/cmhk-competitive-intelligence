#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    "company-data.js",
    "leadership-board.css",
    "news-review-sheet.css",
    "news-review-sheet.js",
    "responsive-layout-hardening.css",
    "styles.css",
    "workspace-tabs.css",
    "workspace-tabs.js",
)

PUBLIC_SNAPSHOT_BOOTSTRAP = r'''(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const root = new URL("./", document.baseURI);
  const snapshotRoutes = new Map([
    ["/api/status", "static-data/status.json"],
    ["/api/company-metrics", "static-data/company-metrics.json"],
    ["/api/executive-intelligence", "static-data/executive-intelligence.json"],
    ["/api/strategic-briefs", "strategic-briefs.json"],
    ["/api/project-incidents", "static-data/project-incidents.json"],
    ["/api/crawl-runs", "static-data/crawl-runs.json"],
    ["/api/task-runs", "static-data/task-runs.json"],
  ]);
  const inlineRoutes = new Map([
    ["/api/agent-datasets", { ok: true, datasets: [] }],
    ["/api/agent-memory", { ok: true, memories: [] }],
    ["/api/agent-skills", { ok: true, skills: [] }],
    ["/api/agent-trace", { ok: true, events: [] }],
    ["/api/ai-config", { ok: true, config: { provider: "", base_url: "", model: "", has_api_key: false } }],
    ["/api/ai-models", { ok: true, models: [] }],
    ["/api/chat-starters", { ok: true, starters: [] }],
    ["/api/chat-threads", { ok: true, threads: [] }],
    ["/api/news-review-sheet", { ok: true, records: [], columns: [], feishu_url: "" }],
  ]);

  function jsonResponse(payload, status = 200) {
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
    });
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
  }
  document.addEventListener("DOMContentLoaded", lockPrivateControls);
  new MutationObserver(lockPrivateControls).observe(document.documentElement, { childList: true, subtree: true });
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


def _fetch_local_json(source_url: str, endpoint: str) -> dict[str, Any]:
    response = _run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "30",
            source_url.rstrip("/") + endpoint,
        ]
    )
    payload = json.loads(response.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"snapshot endpoint did not return an object: {endpoint}")
    return payload


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


def _build_public_runtime_snapshots(source_url: str) -> dict[str, dict[str, Any]]:
    live_status = _fetch_local_json(source_url, "/api/status").get("status") or {}
    live_briefs = _fetch_local_json(source_url, "/api/strategic-briefs")
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
            "outputs": [],
        },
    }
    return {
        "status.json": public_status,
        "company-metrics.json": _scrub_public_value(
            _fetch_local_json(source_url, "/api/company-metrics")
        ),
        "executive-intelligence.json": _scrub_public_value(
            _fetch_local_json(source_url, "/api/executive-intelligence")
        ),
        "project-incidents.json": {"ok": True, "incidents": [], "total": 0},
        "crawl-runs.json": {"ok": True, "runs": [], "total": 0, "truncated": False},
        "task-runs.json": {"ok": True, "tasks": []},
        "strategic-briefs.json": public_briefs,
    }


def _rewrite_static_css(source: str) -> str:
    return source.replace('url("/static/assets/', 'url("./assets/').replace(
        "url('/static/assets/", "url('./assets/"
    )


def _rewrite_root_javascript(source: str) -> str:
    return source.replace('"/static/', '"./static/').replace("'/static/", "'./static/")


def _readonly_module_html() -> str:
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#06131e;color:#c8eaf4;font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.card{width:min(560px,calc(100% - 48px));padding:32px;border:1px solid rgba(84,205,232,.28);background:rgba(8,31,44,.82);box-shadow:0 18px 60px rgba(0,0,0,.24)}h1{margin:0 0 12px;font-size:22px}p{margin:0;color:#83a8b5}</style></head>
<body><section class="card"><h1>公开网页为只读快照</h1><p>此模块包含内部订阅、人员或操作功能，不在 GitHub Pages 公开。请在 CMHK 内网主页使用完整功能。</p></section></body></html>"""


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
        'src="./static/subscription-admin.html?v=11"',
        'src="./static/public-readonly.html?module=subscriptions"',
    )
    html = re.sub(
        r'<a href="https://cmhk-try\.feishu\.cn/sheets/[^\"]+"[^>]*>\s*监测规则\s*</a>',
        '<span class="public-snapshot-label">公开快照</span>',
        html,
    )
    html = html.replace(
        '    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
        '    <script src="./static/public-snapshot-bootstrap.js"></script>\n'
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
        (static_destination / name).write_text(content, encoding="utf-8")
    (static_destination / "public-snapshot-bootstrap.js").write_text(
        PUBLIC_SNAPSHOT_BOOTSTRAP,
        encoding="utf-8",
    )
    (static_destination / "public-readonly.html").write_text(
        _readonly_module_html(),
        encoding="utf-8",
    )
    shutil.copy2(
        STATIC_DIR / "competitor-workbench-data.json",
        static_destination / "competitor-workbench-data.json",
    )
    (static_destination / "news-run-items.json").write_text("{}\n", encoding="utf-8")

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
        if name == "strategic-briefs.json":
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
