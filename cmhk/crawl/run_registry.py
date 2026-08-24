from __future__ import annotations

import csv
import fcntl
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import crawl


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = ROOT / "agent_knowledge" / "crawl_run_logs"
RUNS_DIR = REGISTRY_DIR / "runs"
INDEX_JSON = REGISTRY_DIR / "index.json"
LATEST_JSON = REGISTRY_DIR / "latest.json"
INDEX_MD = REGISTRY_DIR / "index.md"
MANIFEST_JSON = REGISTRY_DIR / "manifest.json"
README_MD = REGISTRY_DIR / "README.md"
LOCK_FILE = REGISTRY_DIR / ".registry.lock"
REGISTRY_LOCK = threading.RLock()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _write_text_atomic(path: Path, content: str) -> None:
    """Replace one registry file atomically so readers never observe partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _registry_write_lock():
    """Serialize registry read-modify-write cycles across scheduler/web workers."""
    with REGISTRY_LOCK:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        with LOCK_FILE.open("a+", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _safe_id(value: str) -> str:
    clean = re.sub(r"^爬虫日志[_-]?", "", value)
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", clean).strip("._-")
    return clean or datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d_%H%M%S")


def _line_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def load_final_audit_summary() -> dict[str, Any]:
    path = ROOT / "final_audit.md"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    return {
        "generated_at": _line_value(text, "Generated at"),
        "rows_crawled": _line_value(text, "Rows crawled"),
        "ok_rows": _line_value(text, "OK rows"),
        "partial_rows": _line_value(text, "Partial rows"),
        "failed_rows": _line_value(text, "Failed/no extraction rows"),
        "fulfilled": _line_value(text, "Information requirements fulfilled"),
        "live_url_success": _line_value(text, "Live URL success"),
        "live_url_failures": _line_value(text, "Live URL failures"),
        "restored_from_previous_evidence": _line_value(text, "URLs restored from previous evidence"),
    }


def load_run_log_summary() -> dict[str, Any]:
    path = ROOT / "run_log.tsv"
    if not path.exists():
        return {"rows": 0, "success_urls": 0, "failed_urls": 0, "fallback_urls": 0}
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    success_urls = 0
    fallback_urls = 0
    failed_urls = 0
    for row in rows:
        status = int(row.get("http_status") or 0)
        fallback = str(row.get("evidence_fallback_used") or "").lower() in {"1", "true", "yes"}
        if fallback:
            fallback_urls += 1
            failed_urls += 1
        elif 200 <= status < 400:
            success_urls += 1
        else:
            failed_urls += 1
    return {
        "rows": len(rows),
        "success_urls": success_urls,
        "failed_urls": failed_urls,
        "fallback_urls": fallback_urls,
    }


def load_curation_summary() -> dict[str, Any]:
    latest = _read_json(ROOT / "curation_data" / "latest.json", {})
    if not isinstance(latest, dict):
        return {}
    return {
        "agent_run_id": latest.get("run_id", ""),
        "started_at": latest.get("started_at", ""),
        "completed_at": latest.get("completed_at", ""),
        "tasks": latest.get("tasks", 0),
        "accepted": latest.get("accepted", 0),
        "rejected": latest.get("rejected", 0),
        "review": latest.get("review", 0),
        "gaps": latest.get("gaps", 0),
        "recrawl_rows": latest.get("recrawl_rows", []),
        "agent_trace": (latest.get("extra") or {}).get("agent_trace", ""),
        "search_verification": (latest.get("extra") or {}).get("search_verification", {}),
    }


def ensure_registry_docs() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": "crawl-run-logs",
        "title": "爬虫运行日志索引",
        "summary": "记录每次全量爬虫对应的本地审计文件、飞书日志页、Agent 数据整理运行 ID 和质量摘要，供小竞 AI 调度、追溯和回答运行状态问题。",
        "source_type": "internal_operational_log",
        "scope": "运行审计与调度索引；完整逐 URL 日志以飞书日志子表和 run_log.tsv 为准。",
        "updated_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).date().isoformat(),
        "tags": ["爬虫日志", "运行审计", "Agent调度", "飞书日志", "数据质量"],
        "keywords": ["爬虫日志", "运行记录", "飞书日志", "Agent trace", "覆盖率", "失败链接", "缺口", "调度"],
        "entrypoints": ["README.md", "index.md", "latest.json", "index.json"],
        "quality": "index.json/latest.json 为调度索引；飞书日志页保存完整 run_log.tsv 和 Agent trace，若本地索引与飞书不一致，以飞书日志页和 daily_validation.json 为准。",
    }
    _write_json(MANIFEST_JSON, manifest)
    README_MD.write_text(
        """# 爬虫运行日志索引

这个数据集用于让小竞 AI 明确知道每次爬虫日志在哪里、如何追溯、如何调度使用。

## 保存策略

- 飞书日志子表：保存完整逐 URL 爬虫日志，并在 Agent 数据整理完成后追加 Agent 处理流程与结果。
- 本地运行索引：保存轻量摘要、飞书日志页链接、本地审计文件路径和 Agent run_id，供 Agent 快速检索。

## 主要文件

- `index.md`：最近运行的人类可读索引。
- `index.json`：最近多次运行的结构化索引。
- `latest.json`：最新一次运行摘要。
- `runs/<crawl_run_id>.json`：单次运行详情。

## Agent 使用规则

当用户询问爬虫运行、失败链接、覆盖率、飞书日志、Agent 调度或上次爬虫结果时，先读取本数据集，再按需要读取 `/references/run_log.tsv`、`/references/coverage_report.tsv`、`/references/final_audit.md` 或打开飞书日志页。
""",
        encoding="utf-8",
    )


def render_index_markdown(runs: list[dict[str, Any]]) -> str:
    lines = [
        "# 爬虫运行日志索引",
        "",
        f"- 更新时间：{datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(timespec='seconds')}",
        "- 完整逐 URL 日志在飞书日志子表；本地保留轻量索引用于 Agent 检索和调度。",
        "",
        "| 运行ID | 时间 | 覆盖率 | URL成功/失败 | 飞书日志 | Agent运行 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in runs[:20]:
        audit = item.get("final_audit") or {}
        run_log = item.get("run_log") or {}
        feishu = item.get("feishu") or {}
        curation = item.get("curation") or {}
        feishu_label = feishu.get("log_sheet_title") or feishu.get("log_sheet_id") or "未写入"
        feishu_url = feishu.get("url") or ""
        feishu_cell = f"[{feishu_label}]({feishu_url})" if feishu_url else feishu_label
        lines.append(
            "| {run_id} | {time} | {fulfilled} | {ok}/{failed} | {feishu} | {agent} |".format(
                run_id=item.get("crawl_run_id", ""),
                time=item.get("completed_at_hkt") or item.get("started_at_hkt") or "",
                fulfilled=audit.get("fulfilled") or "",
                ok=run_log.get("success_urls", 0),
                failed=run_log.get("failed_urls", 0),
                feishu=feishu_cell,
                agent=curation.get("agent_run_id") or "",
            )
        )
    return "\n".join(lines).strip() + "\n"


def load_index() -> list[dict[str, Any]]:
    data = _read_json(INDEX_JSON, [])
    if not isinstance(data, list):
        return []
    resolved: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        crawl_run_id = str(item.get("crawl_run_id") or "")
        detail = _read_json(RUNS_DIR / f"{_safe_id(crawl_run_id)}.json", {}) if crawl_run_id else {}
        # The per-run record is the authoritative state.  It is written before
        # the shared index and survives a competing writer's stale index update.
        resolved.append(detail if isinstance(detail, dict) and detail else item)
    return resolved


def load_run_history(task_kind: str = "") -> list[dict[str, Any]]:
    """Load every retained per-run record, optionally filtered by task kind.

    ``index.json`` is intentionally capped for the lightweight latest-runs view.
    Historical UI filters must scan the authoritative per-run records instead,
    otherwise busy task kinds push older dates out of the visible window.
    """
    records: dict[str, dict[str, Any]] = {}
    for item in load_index():
        crawl_run_id = str(item.get("crawl_run_id") or "")
        if crawl_run_id:
            records[crawl_run_id] = item
    for path in RUNS_DIR.glob("*.json"):
        item = _read_json(path, {})
        if not isinstance(item, dict):
            continue
        crawl_run_id = str(item.get("crawl_run_id") or path.stem)
        if crawl_run_id:
            records[crawl_run_id] = item
    runs = list(records.values())
    if task_kind:
        runs = [item for item in runs if str(item.get("task_kind") or "") == task_kind]
    return sorted(
        runs,
        key=lambda item: (
            str(item.get("started_at_hkt") or item.get("completed_at_hkt") or ""),
            str(item.get("crawl_run_id") or ""),
        ),
        reverse=True,
    )


def _save_run_record(record: dict[str, Any]) -> dict[str, Any]:
    with _registry_write_lock():
        crawl_run_id = str(record.get("crawl_run_id") or "")
        if not crawl_run_id:
            raise ValueError("crawl_run_id is required")
        current = _read_json(RUNS_DIR / f"{crawl_run_id}.json", {})
        current_terminal = isinstance(current, dict) and current.get("run_status") in {"completed", "failed"}
        incoming_running = record.get("run_status") == "running"
        if current_terminal and incoming_running and not record.get("resumed_at_hkt"):
            # A delayed heartbeat must never reopen an already finalized task.
            record = current
        _write_json(RUNS_DIR / f"{crawl_run_id}.json", record)
        runs = [item for item in load_index() if item.get("crawl_run_id") != crawl_run_id]
        runs.insert(0, record)
        runs = runs[:50]
        _write_json(INDEX_JSON, runs)
        _write_json(LATEST_JSON, record)
        _write_text_atomic(INDEX_MD, render_index_markdown(runs))
        return record


def _stream_log_stats(path: Path | None) -> dict[str, int]:
    if not path or not path.exists():
        return {"bytes": 0, "lines": 0}
    try:
        raw = path.read_bytes()
    except OSError:
        return {"bytes": 0, "lines": 0}
    return {"bytes": len(raw), "lines": len(raw.splitlines())}


def start_crawl_run(
    *,
    trigger: str,
    scope: str = "",
    task_kind: str = "crawl",
    parent_crawl_run_id: str = "",
    phase: str = "任务启动",
    progress_detail: str = "后台已接收爬虫任务，正在准备执行。",
) -> dict[str, Any]:
    """Register a run and reserve its immutable full-log file before work starts."""
    ensure_registry_docs()
    started = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    crawl_run_id = _safe_id(started.strftime("%Y%m%d_%H%M%S_%f"))
    stream_log = RUNS_DIR / f"{crawl_run_id}.jsonl"
    stream_log.write_text("", encoding="utf-8")
    record = {
        "crawl_run_id": crawl_run_id,
        "trigger": trigger,
        "scope": scope,
        "task_kind": task_kind,
        "parent_crawl_run_id": str(parent_crawl_run_id or ""),
        "run_status": "running",
        "backend_pid": os.getpid(),
        "worker_pid": 0,
        "phase": phase,
        "progress_detail": progress_detail,
        "heartbeat_at_hkt": started.isoformat(timespec="seconds"),
        "started_at_hkt": started.isoformat(timespec="seconds"),
        "completed_at_hkt": "",
        "crawl_return_code": None,
        "duration_ms": None,
        "feishu": {},
        "local_files": {
            "stream_log": str(stream_log.relative_to(ROOT)),
        },
        "stream_log": _stream_log_stats(stream_log),
        "final_audit": {},
        "run_log": {},
        "curation": {},
        "metrics_refresh": {},
        "agent_trace_feishu_sync": {},
    }
    _save_run_record(record)
    return {**record, "stream_log_path": str(stream_log)}


def finalize_operational_crawl_run(
    crawl_run_id: str,
    *,
    ok: bool,
    duration_ms: int,
    progress_detail: str,
    failure_stage: str = "",
    summary: dict[str, Any] | None = None,
    run_status_override: str = "",
) -> dict[str, Any]:
    """Finalize a crawler-shaped operational task without borrowing full-crawl metrics."""
    with REGISTRY_LOCK:
        record = _read_json(RUNS_DIR / f"{_safe_id(crawl_run_id)}.json", {})
        if not isinstance(record, dict) or not record:
            raise ValueError(f"crawl run not found: {crawl_run_id}")
        relative = str((record.get("local_files") or {}).get("stream_log") or "")
        stream_path = ROOT / relative if relative else RUNS_DIR / f"{crawl_run_id}.jsonl"
        now = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
        run_status = str(run_status_override or ("completed" if ok else "failed"))
        if run_status not in {"completed", "failed", "cutoff"}:
            raise ValueError(f"unsupported operational run status: {run_status}")
        phase = {"completed": "已完成", "failed": "失败", "cutoff": "已截止"}[run_status]
        record.update(
            {
                "run_status": run_status,
                "worker_pid": 0,
                "phase": phase,
                "progress_detail": progress_detail,
                "status_detail": progress_detail,
                "failure_stage": failure_stage,
                "heartbeat_at_hkt": now,
                "completed_at_hkt": now,
                "crawl_return_code": 0 if run_status in {"completed", "cutoff"} else 1,
                "duration_ms": max(0, int(duration_ms or 0)),
                "operational_summary": dict(summary or {}),
            }
        )
        record["stream_log"] = _stream_log_stats(stream_path)
        return _save_run_record(record)


def append_crawl_run_event(log_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def heartbeat_crawl_run(
    crawl_run_id: str,
    phase: str,
    detail: str,
    *,
    worker_pid: int = 0,
    append_log: bool = True,
) -> dict[str, Any] | None:
    """Persist crawl liveness independently from the browser SSE connection."""
    if not crawl_run_id:
        return None
    with REGISTRY_LOCK:
        record = _read_json(RUNS_DIR / f"{_safe_id(crawl_run_id)}.json", {})
        if not isinstance(record, dict) or not record or record.get("run_status") != "running":
            return record if isinstance(record, dict) else None
        relative = str((record.get("local_files") or {}).get("stream_log") or "")
        stream_path = ROOT / relative if relative else RUNS_DIR / f"{crawl_run_id}.jsonl"
        now = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
        record.update(
            {
                "backend_pid": os.getpid(),
                "worker_pid": int(worker_pid or 0),
                "phase": str(phase or record.get("phase") or "执行中"),
                "progress_detail": str(detail or record.get("progress_detail") or "任务仍在执行。"),
                "heartbeat_at_hkt": now,
            }
        )
        if append_log:
            append_crawl_run_event(
                stream_path,
                {
                    "type": "monitor",
                    "timestamp": now,
                    "phase": record["phase"],
                    "detail": record["progress_detail"],
                    "backendPid": record["backend_pid"],
                    "workerPid": record["worker_pid"],
                },
            )
        record["stream_log"] = _stream_log_stats(stream_path)
        return _save_run_record(record)


def resume_crawl_run(
    crawl_run_id: str,
    phase: str,
    detail: str,
) -> dict[str, Any]:
    """Reopen an interrupted scheduled run so its downstream stages can resume."""
    with REGISTRY_LOCK:
        record = _read_json(RUNS_DIR / f"{_safe_id(crawl_run_id)}.json", {})
        if not isinstance(record, dict) or not record:
            raise ValueError(f"crawl run not found: {crawl_run_id}")
        relative = str((record.get("local_files") or {}).get("stream_log") or "")
        stream_path = ROOT / relative if relative else RUNS_DIR / f"{crawl_run_id}.jsonl"
        now = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
        record.update(
            {
                "run_status": "running",
                "backend_pid": os.getpid(),
                "worker_pid": 0,
                "phase": str(phase or "恢复任务"),
                "progress_detail": str(detail or "正在恢复未完成的爬虫任务。"),
                "status_detail": "",
                "failure_stage": "",
                "heartbeat_at_hkt": now,
                "completed_at_hkt": "",
                "crawl_return_code": None,
                "interrupted": False,
                "resumed_at_hkt": now,
            }
        )
        append_crawl_run_event(
            stream_path,
            {
                "type": "monitor",
                "timestamp": now,
                "phase": record["phase"],
                "detail": record["progress_detail"],
                "backendPid": record["backend_pid"],
                "workerPid": 0,
                "resumed": True,
            },
        )
        record["stream_log"] = _stream_log_stats(stream_path)
        return _save_run_record(record)


def _last_stream_event_summary(path: Path) -> str:
    if not path.exists():
        return "尚未写入运行日志"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "运行日志无法读取"
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            value = line.strip()
            if value:
                return value[:240]
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "log" and event.get("text"):
            return str(event.get("text"))[:240]
        if event.get("type") == "agent_trace":
            trace = event.get("trace") if isinstance(event.get("trace"), dict) else {}
            if trace.get("message"):
                return str(trace.get("message"))[:240]
    return "已建立任务记录，但没有可识别的进度事件"


def mark_crawl_run_interrupted(
    crawl_run_id: str,
    detail: str,
    *,
    use_last_activity_time: bool = False,
) -> dict[str, Any] | None:
    """Finalize one orphaned crawl so it cannot remain permanently running."""
    record_path = RUNS_DIR / f"{_safe_id(crawl_run_id)}.json"
    record = _read_json(record_path, {})
    if not isinstance(record, dict) or not record or record.get("run_status") != "running":
        return None
    relative = str((record.get("local_files") or {}).get("stream_log") or "")
    stream_path = ROOT / relative if relative else RUNS_DIR / f"{crawl_run_id}.jsonl"
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    completed = now
    if use_last_activity_time and stream_path.exists():
        try:
            completed = datetime.fromtimestamp(stream_path.stat().st_mtime, ZoneInfo("Asia/Hong_Kong"))
        except OSError:
            completed = now
    started_text = str(record.get("started_at_hkt") or "")
    try:
        started = datetime.fromisoformat(started_text)
        if started.tzinfo is None:
            started = started.replace(tzinfo=ZoneInfo("Asia/Hong_Kong"))
        duration_ms = max(0, int((completed - started).total_seconds() * 1000))
    except (TypeError, ValueError):
        duration_ms = 0
    status_detail = str(detail or "爬虫任务意外中断").strip()
    status_detail += f"；最后活动：{completed.isoformat(timespec='seconds')}"
    status_detail += f"；最后进度：{_last_stream_event_summary(stream_path)}"
    append_crawl_run_event(stream_path, {"type": "log", "text": "[任务中断] " + status_detail})
    append_crawl_run_event(
        stream_path,
        {
            "type": "done",
            "ok": False,
            "interrupted": True,
            "durationMs": duration_ms,
            "message": status_detail,
        },
    )
    record.update(
        {
            "run_status": "failed",
            "interrupted": True,
            "status_detail": status_detail,
            "completed_at_hkt": completed.isoformat(timespec="seconds"),
            "crawl_return_code": -1,
            "duration_ms": duration_ms,
            "worker_pid": 0,
            "phase": "已中断",
            "progress_detail": status_detail,
            "heartbeat_at_hkt": completed.isoformat(timespec="seconds"),
        }
    )
    record["stream_log"] = _stream_log_stats(stream_path)
    return _save_run_record(record)


def reconcile_interrupted_crawl_runs() -> list[dict[str, Any]]:
    """Mark running records whose backend and worker processes are both gone."""
    updated: list[dict[str, Any]] = []
    for item in reversed(load_index()):
        if not isinstance(item, dict) or item.get("run_status") != "running":
            continue
        backend_pid = int(item.get("backend_pid") or 0)
        worker_pid = int(item.get("worker_pid") or 0)
        if _pid_alive(backend_pid) or _pid_alive(worker_pid):
            continue
        record = mark_crawl_run_interrupted(
            str(item.get("crawl_run_id") or ""),
            "后台服务已重新启动，原爬虫进程已不存在",
            use_last_activity_time=True,
        )
        if record:
            updated.append(record)
    return updated


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def load_crawl_run_log(crawl_run_id: str) -> dict[str, Any]:
    """Return the complete immutable event log for one historical run."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", crawl_run_id or ""):
        return {"ok": False, "error": "invalid crawl run id"}
    record = _read_json(RUNS_DIR / f"{crawl_run_id}.json", {})
    if not isinstance(record, dict) or not record:
        return {"ok": False, "error": "crawl run not found"}
    relative = str((record.get("local_files") or {}).get("stream_log") or "")
    path = (ROOT / relative).resolve() if relative else (RUNS_DIR / f"{crawl_run_id}.jsonl").resolve()
    if path.parent != RUNS_DIR.resolve() or not path.exists():
        return {
            "ok": False,
            "error": "full log was not archived for this legacy run",
            "run": record,
        }
    raw = path.read_text(encoding="utf-8", errors="replace")
    rendered: list[str] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            rendered.append(line)
            continue
        if not isinstance(event, dict):
            rendered.append(line)
            continue
        event_type = str(event.get("type") or "")
        if event_type == "run_start":
            rendered.append(
                "[{time}] {trigger} {scope}".format(
                    time=event.get("startedAt") or record.get("started_at_hkt") or "",
                    trigger=event.get("trigger") or record.get("trigger") or "",
                    scope=event.get("scope") or record.get("scope") or "",
                ).strip()
            )
        elif event_type == "log":
            rendered.append(str(event.get("text") or ""))
        elif event_type == "agent_trace":
            rendered.append("AGENT_TRACE=" + json.dumps(event.get("trace") or {}, ensure_ascii=False))
        elif event_type == "monitor":
            timestamp = str(event.get("timestamp") or "")
            clock = timestamp[11:19] if len(timestamp) >= 19 else timestamp
            rendered.append(
                f"[监控心跳 {clock}] 阶段：{event.get('phase') or '执行中'}；"
                f"状态：{event.get('detail') or '任务仍在执行。'}"
            )
        else:
            rendered.append(json.dumps(event, ensure_ascii=False))
    return {
        "ok": True,
        "run": record,
        "content": "\n".join(rendered).rstrip() + ("\n" if rendered else ""),
        "raw": raw,
        "bytes": len(raw.encode("utf-8")),
        "lines": len(raw.splitlines()),
    }


def register_crawl_run(
    *,
    crawl_return_code: int | None = None,
    duration_ms: int | None = None,
    sync_result: dict[str, Any] | None = None,
    metrics_refresh: dict[str, Any] | None = None,
    trace_sync: dict[str, Any] | None = None,
    trigger: str = "web",
    scope: str = "",
    crawl_run_id: str = "",
    started_at_hkt: str = "",
    stream_log_path: str | Path = "",
    curation_summary: dict[str, Any] | None = None,
    failure_stage: str = "",
    progress_detail: str = "",
) -> dict[str, Any]:
    ensure_registry_docs()
    validation = _read_json(ROOT / "daily_validation.json", {})
    curation = load_curation_summary() if curation_summary is None else dict(curation_summary)
    log_sheet_id = str((sync_result or {}).get("log_sheet_id") or validation.get("log_sheet_id") or "")
    log_sheet_title = str((sync_result or {}).get("log_sheet_title") or validation.get("log_sheet_title") or "")
    crawl_run_id = _safe_id(crawl_run_id or log_sheet_title or curation.get("agent_run_id") or datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat())
    existing = _read_json(RUNS_DIR / f"{crawl_run_id}.json", {})
    if not isinstance(existing, dict):
        existing = {}
    now = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
    completed = crawl_return_code == 0 and not failure_stage
    feishu_url = (
        f"https://cmhk-try.feishu.cn/sheets/{crawl.SPREADSHEET_TOKEN}?sheet={log_sheet_id}"
        if log_sheet_id
        else ""
    )
    record = {
        "crawl_run_id": crawl_run_id,
        "trigger": trigger,
        "scope": scope or existing.get("scope", ""),
        "run_status": "completed" if completed else "failed",
        "backend_pid": int(existing.get("backend_pid") or os.getpid()),
        "worker_pid": 0,
        "phase": "已完成" if completed else "失败",
        "progress_detail": progress_detail or (
            "爬虫、审核与结果归档已全部完成。"
            if completed
            else f"任务在 {failure_stage or '执行阶段'} 失败，返回码 {crawl_return_code}，请查看运行日志。"
        ),
        "failure_stage": failure_stage,
        "heartbeat_at_hkt": now,
        "started_at_hkt": started_at_hkt or existing.get("started_at_hkt") or validation.get("checked_at_hkt", ""),
        "completed_at_hkt": now,
        "crawl_return_code": crawl_return_code,
        "duration_ms": duration_ms,
        "feishu": {
            "spreadsheet_token": crawl.SPREADSHEET_TOKEN,
            "main_sheet_id": crawl.MAIN_SHEET_ID,
            "log_sheet_id": log_sheet_id,
            "log_sheet_title": log_sheet_title,
            "url": feishu_url,
            "sync_ok": bool(validation.get("ok")) if validation else bool(log_sheet_id),
            "result_columns": validation.get("result_columns") if isinstance(validation, dict) else {},
            "compliance_gaps": validation.get("compliance_gaps", []) if isinstance(validation, dict) else [],
        },
        "local_files": {
            **(existing.get("local_files") or {}),
            "final_audit": "final_audit.md",
            "coverage_report": "coverage_report.tsv",
            "run_log_tsv": "run_log.tsv",
            "run_log_json": "run_log.json",
            "daily_validation": "daily_validation.json",
            "curation_latest": "curation_data/latest.json",
            "agent_trace": curation.get("agent_trace", ""),
        },
        "final_audit": load_final_audit_summary(),
        "run_log": load_run_log_summary(),
        "curation": curation,
        "metrics_refresh": metrics_refresh or {},
        "agent_trace_feishu_sync": trace_sync or {},
    }
    if stream_log_path:
        stream_path = Path(stream_log_path)
        record["local_files"]["stream_log"] = str(stream_path.relative_to(ROOT))
    else:
        relative_stream = str(record["local_files"].get("stream_log") or "")
        stream_path = ROOT / relative_stream if relative_stream else None
    record["stream_log"] = _stream_log_stats(stream_path)
    return _save_run_record(record)


def latest_crawl_run_summary(limit: int = 5) -> str:
    ensure_registry_docs()
    runs = load_index()[:limit]
    if not runs:
        return "当前还没有记录到爬虫运行索引。"
    lines = ["最近爬虫运行索引："]
    for item in runs:
        audit = item.get("final_audit") or {}
        run_log = item.get("run_log") or {}
        feishu = item.get("feishu") or {}
        curation = item.get("curation") or {}
        lines.append(
            "\n".join(
                [
                    f"- 运行ID：{item.get('crawl_run_id')}",
                    f"  时间：{item.get('completed_at_hkt')}",
                    f"  覆盖率：{audit.get('fulfilled') or '未记录'}",
                    f"  URL：成功 {run_log.get('success_urls', 0)}，失败/兜底 {run_log.get('failed_urls', 0)}",
                    f"  飞书日志：{feishu.get('log_sheet_title') or feishu.get('log_sheet_id') or '未写入'} {feishu.get('url') or ''}",
                    f"  Agent运行：{curation.get('agent_run_id') or '未记录'}，发布 {curation.get('accepted', 0)}，缺口 {curation.get('gaps', 0)}",
                ]
            )
        )
    return "\n".join(lines)
