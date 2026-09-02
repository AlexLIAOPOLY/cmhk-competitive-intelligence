from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from cmhk.crawl.run_registry import (
    append_crawl_run_event,
    heartbeat_crawl_run,
    load_index as load_crawl_run_index,
    load_run_history as load_crawl_run_history,
    register_crawl_run,
    resume_crawl_run,
    start_crawl_run,
)
from cmhk.intelligence.scheduled_news_bridge import capture_completed_crawl
from cmhk.integrations.feishu_runtime import resolve_lark_cli


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
STATE_PATH = ROOT / "scheduler_state.json"
PENDING_RUN_PATH = ROOT / "scheduler_pending_run.json"
HEARTBEAT_PATH = ROOT / "var" / "frequency_scheduler" / "heartbeat.json"
LIVE_SCHEDULE_CACHE_PATH = ROOT / "var" / "frequency_scheduler" / "live_schedule_cache.json"
RUN_LOG_PATH = ROOT / "run_log.json"
SPREADSHEET_TOKEN = "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
MAIN_SHEET_ID = "9c638d"
HKT = ZoneInfo("Asia/Hong_Kong")
POLL_SECONDS = max(30, int(os.environ.get("CMHK_SCHEDULER_POLL_SECONDS", "60")))
RETRY_SECONDS = max(300, int(os.environ.get("CMHK_SCHEDULER_RETRY_SECONDS", "1800")))
SCHEDULE_READ_ATTEMPTS = max(1, int(os.environ.get("CMHK_SCHEDULE_READ_ATTEMPTS", "3")))
SCHEDULE_CACHE_MAX_AGE_SECONDS = max(
    POLL_SECONDS * 2,
    int(os.environ.get("CMHK_SCHEDULE_CACHE_MAX_AGE_SECONDS", "900")),
)
LARK_CLI = resolve_lark_cli()
PYTHON = sys.executable
FREQUENCY_HEADERS = ("更新频率", "更新频次", "收集频率", "排期频率", "每隔多长时间收集一轮")
AGENT_AUDIT_TIMEOUT_SECONDS = max(600, int(os.environ.get("CMHK_AGENT_AUDIT_TIMEOUT_SECONDS", "5400")))
DEFAULT_AGENT_AUDIT_ONLINE_LIMIT = "0"
AGENT_AUDIT_CONTROL_VERSION = 15
REQUIRED_AGENT_NODES = {
    "证据接收",
    "来源分类",
    "事实抽取",
    "主体校验",
    "质量审计",
    "冲突仲裁",
    "搜索验证",
    "缺口规划",
    "公司研究 Agent",
    "编排决策",
    "发布",
}
FINANCIAL_RESULT_ROWS = frozenset({2, 5, 8, 11, 15, 17})
FINANCIAL_RESULT_DAILY_FREQUENCY = "每天 03:00"
FINANCIAL_FRONTEND_PUBLISH_SCRIPT = ROOT / "scripts" / "publish_executive_dashboard_pages.py"
_SCHEDULER_HEARTBEAT: "SchedulerHeartbeat | None" = None


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def no_proxy_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        env.pop(key, None)
    env["LARK_CLI_NO_PROXY"] = "1"
    return env


def cell_text(value: object) -> str:
    if isinstance(value, list):
        return "".join(
            str(item.get("text") or "")
            for item in value
            if isinstance(item, dict)
        )
    return "" if value is None else str(value)


def _transient_lark_failure(raw: object) -> bool:
    text = str(raw or "").strip()
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else {}
    error = error if isinstance(error, dict) else {}
    error_type = str(error.get("type") or "").lower()
    error_subtype = str(error.get("subtype") or "").lower()
    message = str(error.get("message") or text).lower()
    return bool(
        error_type in {"network", "timeout"}
        or error_subtype in {"connect", "connection", "dns", "server_error", "timeout", "tls"}
        or any(
            marker in message
            for marker in (
                "connect: operation timed out",
                "connection reset",
                "dial tcp",
                "i/o timeout",
                "rate limit",
                "temporarily unavailable",
                "timed out",
                "timeout",
            )
        )
    )


def _schedule_rows_from_values(values: list[object]) -> list[dict[str, object]]:
    if not values:
        raise RuntimeError("飞书主表为空")
    headers = [cell_text(value).strip() for value in values[0]]
    frequency_index = next(
        (headers.index(name) for name in FREQUENCY_HEADERS if name in headers),
        None,
    )
    if frequency_index is None:
        raise RuntimeError(f"找不到更新频率列，当前表头：{headers}")
    rows: list[dict[str, object]] = []
    project_index = headers.index("项目名称") if "项目名称" in headers else 0
    active_project = ""
    for row_no in range(2, len(values) + 1):
        row = values[row_no - 1] if row_no - 1 < len(values) else []
        project = cell_text(row[project_index] if project_index < len(row) else None).strip()
        if project:
            active_project = project
        if active_project != "竞争对手与行业情报监测":
            continue
        frequency = cell_text(row[frequency_index] if frequency_index < len(row) else None).strip()
        if frequency:
            rows.append({"row": row_no, "frequency": frequency})
    return rows


def _write_live_schedule_cache(rows: list[dict[str, object]]) -> None:
    LIVE_SCHEDULE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LIVE_SCHEDULE_CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "version": 1,
                "verified_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(LIVE_SCHEDULE_CACHE_PATH)


def _read_recent_live_schedule_cache() -> list[dict[str, object]]:
    try:
        payload = json.loads(LIVE_SCHEDULE_CACHE_PATH.read_text(encoding="utf-8"))
        verified_at = datetime.fromisoformat(str(payload.get("verified_at_hkt") or ""))
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=HKT)
        age_seconds = (datetime.now(HKT) - verified_at.astimezone(HKT)).total_seconds()
        rows = payload.get("rows")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []
    if age_seconds < 0 or age_seconds > SCHEDULE_CACHE_MAX_AGE_SECONDS or not isinstance(rows, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in rows:
        if not isinstance(item, dict):
            return []
        try:
            row_no = int(item.get("row") or 0)
        except (TypeError, ValueError):
            return []
        frequency = str(item.get("frequency") or "").strip()
        if row_no < 2 or not frequency:
            return []
        normalized.append({"row": row_no, "frequency": frequency})
    return normalized


def read_live_schedule() -> list[dict[str, object]]:
    last_error = ""
    for attempt in range(1, SCHEDULE_READ_ATTEMPTS + 1):
        try:
            proc = subprocess.run(
                [
                    LARK_CLI,
                    "sheets",
                    "+read",
                    "--spreadsheet-token",
                    SPREADSHEET_TOKEN,
                    "--range",
                    f"{MAIN_SHEET_ID}!A1:Z200",
                    "--value-render-option",
                    "FormattedValue",
                ],
                cwd=ROOT,
                env=no_proxy_env(),
                text=True,
                capture_output=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            last_error = f"lark-cli schedule read timed out after {exc.timeout}s"
            transient = True
        else:
            raw = proc.stderr.strip() or proc.stdout.strip()
            if proc.returncode:
                last_error = raw
                transient = _transient_lark_failure(raw)
            else:
                try:
                    values = json.loads(proc.stdout)["data"]["valueRange"]["values"]
                    rows = _schedule_rows_from_values(values)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"飞书主表返回结构无效：{exc}") from exc
                _write_live_schedule_cache(rows)
                return rows
        if not transient:
            raise RuntimeError(last_error)
        if attempt < SCHEDULE_READ_ATTEMPTS:
            logging.warning(
                "飞书排期读取瞬时失败，第 %s/%s 次，准备重试",
                attempt,
                SCHEDULE_READ_ATTEMPTS,
            )
            time.sleep(min(2.0, float(attempt)))
    cached = _read_recent_live_schedule_cache()
    if cached:
        logging.warning(
            "飞书排期连续读取失败，使用最近 %s 秒内已验证快照；下一轮继续实时回读",
            SCHEDULE_CACHE_MAX_AGE_SECONDS,
        )
        return cached
    raise RuntimeError(last_error or "飞书排期读取失败且没有可用的已验证快照")


def parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HKT)
    return parsed.astimezone(HKT)


def elapsed_ms(started_at: object) -> int:
    started = parse_datetime(started_at)
    if not started:
        return 0
    return max(0, round((datetime.now(HKT) - started).total_seconds() * 1000))


def last_success(row_no: int, *, before: datetime | None = None) -> datetime | None:
    path = RESULTS_DIR / f"row_{row_no}.json"
    latest: datetime | None = None
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        latest = parse_datetime(payload.get("fetched_at_hkt") or payload.get("fetched_at"))
        if latest and (before is None or latest < before):
            return latest
    if before is None or not RUN_LOG_PATH.exists():
        return None if before and latest and latest >= before else latest
    try:
        entries = json.loads(RUN_LOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    candidates: list[datetime] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or int(entry.get("row") or 0) != row_no:
            continue
        timestamp = parse_datetime(entry.get("run_time_hkt") or entry.get("run_time"))
        if timestamp and timestamp < before:
            candidates.append(timestamp)
    return max(candidates, default=None)


def canonical_schedule(frequency: str) -> tuple[str, object] | None:
    text = re.sub(r"\s+", "", frequency or "")
    if not text or "手动不自动" in text or text in {"手动", "未设置", "不自动"}:
        return None
    absolute_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", text)
    if absolute_match:
        absolute = parse_datetime(absolute_match.group(0))
        return ("once", absolute) if absolute else None
    hour_match = re.search(r"每(\d+)小时", text)
    if hour_match:
        return "hours", int(hour_match.group(1))
    day_match = re.search(r"每(\d+)天", text)
    if day_match:
        return "days", int(day_match.group(1))
    if "每日" in text or "每天" in text:
        return "daily", 3
    if "每周一" in text:
        return "weekly", 0
    if "每周" in text or "每星期" in text:
        return "weekly", 0
    if "半月" in text:
        return "days", 15
    if "每月" in text or "月度" in text:
        return "monthly", 1
    if "每季" in text or "季度" in text:
        return "quarterly", 1
    if "每半年" in text or "半年度" in text:
        return "semiannual", 1
    if "每年" in text or "年度" in text:
        return "yearly", 1
    return None


def next_calendar_time(kind: str, anchor: datetime) -> datetime:
    anchor = anchor.astimezone(HKT)
    if kind == "daily":
        candidate = anchor.replace(hour=3, minute=0, second=0, microsecond=0)
        return candidate if candidate > anchor else candidate + timedelta(days=1)
    if kind == "weekly":
        candidate = anchor.replace(hour=3, minute=0, second=0, microsecond=0)
        candidate += timedelta(days=(7 - candidate.weekday()) % 7)
        return candidate if candidate > anchor else candidate + timedelta(days=7)
    if kind == "monthly":
        year = anchor.year + (1 if anchor.month == 12 else 0)
        month = 1 if anchor.month == 12 else anchor.month + 1
        return datetime(year, month, 1, 3, tzinfo=HKT)
    if kind == "quarterly":
        next_month = ((anchor.month - 1) // 3 + 1) * 3 + 1
        year = anchor.year
        if next_month > 12:
            next_month -= 12
            year += 1
        return datetime(year, next_month, 1, 3, tzinfo=HKT)
    if kind == "semiannual":
        if anchor.month < 7:
            return datetime(anchor.year, 7, 1, 3, tzinfo=HKT)
        return datetime(anchor.year + 1, 1, 1, 3, tzinfo=HKT)
    return datetime(anchor.year + 1, 1, 1, 3, tzinfo=HKT)


def next_run_time(frequency: str, last_run: datetime | None, now: datetime) -> datetime | None:
    schedule = canonical_schedule(frequency)
    if schedule is None:
        return None
    kind, value = schedule
    if kind == "once":
        return value if isinstance(value, datetime) else None
    if last_run is None:
        return now
    if kind == "hours":
        return last_run + timedelta(hours=int(value))
    if kind == "days":
        return last_run + timedelta(days=int(value))
    return next_calendar_time(kind, last_run)


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        state: dict[str, object] = {}
    else:
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    state.setdefault("attempts", {})
    state.setdefault("completed_once", {})
    state.setdefault("last_completed", {})
    state.setdefault("last_scheduled_for", {})
    _restore_completed_rows_from_run_archive(state)
    return state


def save_state(state: dict[str, object]) -> None:
    state["updated_at_hkt"] = datetime.now(HKT).isoformat(timespec="seconds")
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


class SchedulerHeartbeat:
    """Write liveness independently from long-running crawl subprocesses."""

    def __init__(self, interval_seconds: int = 30) -> None:
        self.interval_seconds = max(10, interval_seconds)
        self.started_at_hkt = datetime.now(HKT).isoformat(timespec="seconds")
        self._lock = threading.Lock()
        self._state: dict[str, object] = {"status": "idle", "stage": "polling", "crawl_run_id": ""}
        self._stop = threading.Event()

    def update(self, **values: object) -> None:
        with self._lock:
            self._state.update(values)
        self.write()

    def write(self) -> None:
        with self._lock:
            payload = dict(self._state)
        payload.update({
            "schema_version": 1,
            "service": "frequency-scheduler",
            "pid": os.getpid(),
            "started_at_hkt": self.started_at_hkt,
            "updated_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"),
        })
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = HEARTBEAT_PATH.with_name(HEARTBEAT_PATH.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, HEARTBEAT_PATH)

    def start(self) -> None:
        self.write()
        threading.Thread(target=self._run, name="scheduler-heartbeat", daemon=True).start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.write()
            except Exception:
                logging.exception("调度器心跳写入失败")


def _write_pending_run(payload: dict[str, object]) -> None:
    temporary = PENDING_RUN_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(PENDING_RUN_PATH)
    if _SCHEDULER_HEARTBEAT is not None:
        _SCHEDULER_HEARTBEAT.update(
            status="running",
            stage=str(payload.get("stage") or "running"),
            crawl_run_id=str(payload.get("crawl_run_id") or ""),
        )


def _load_pending_run() -> dict[str, object]:
    if not PENDING_RUN_PATH.exists():
        return {}
    try:
        payload = json.loads(PENDING_RUN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _clear_pending_run() -> None:
    PENDING_RUN_PATH.unlink(missing_ok=True)
    if _SCHEDULER_HEARTBEAT is not None:
        _SCHEDULER_HEARTBEAT.update(status="idle", stage="polling", crawl_run_id="")


def _scope_rows(scope: str) -> list[int]:
    return [
        int(value)
        for value in re.findall(r"第(\d+)行", str(scope or ""))
    ]


def _restore_completed_rows_from_run_archive(state: dict[str, object]) -> None:
    last_completed = (
        state.get("last_completed")
        if isinstance(state.get("last_completed"), dict)
        else {}
    )
    try:
        records = load_crawl_run_history()
    except Exception:
        logging.exception("无法从任务归档恢复定时爬虫完成时间")
        state["last_completed"] = last_completed
        return
    last_scheduled_for = (
        state.get("last_scheduled_for")
        if isinstance(state.get("last_scheduled_for"), dict)
        else {}
    )
    for record in records:
        if not isinstance(record, dict):
            continue
        if (
            record.get("trigger") != "定时爬虫"
            or record.get("run_status") != "completed"
        ):
            continue
        completed_at = parse_datetime(record.get("completed_at_hkt"))
        scheduled_for = parse_datetime(
            record.get("scheduled_for_hkt") or record.get("started_at_hkt")
        )
        if completed_at is None or scheduled_for is None:
            continue
        for row in _scope_rows(str(record.get("scope") or "")):
            previous = parse_datetime(last_completed.get(str(row)))
            if previous is None or completed_at > previous:
                last_completed[str(row)] = completed_at.isoformat(
                    timespec="seconds"
                )
            previous_schedule = parse_datetime(last_scheduled_for.get(str(row)))
            if previous_schedule is None or scheduled_for > previous_schedule:
                last_scheduled_for[str(row)] = scheduled_for.isoformat(
                    timespec="seconds"
                )
    state["last_completed"] = last_completed
    state["last_scheduled_for"] = last_scheduled_for


def _mark_rows_completed(
    state: dict[str, object],
    rows: list[int],
    *,
    scheduled_for_hkt: object = None,
) -> None:
    attempts = state.get("attempts") if isinstance(state.get("attempts"), dict) else {}
    last_completed = (
        state.get("last_completed")
        if isinstance(state.get("last_completed"), dict)
        else {}
    )
    last_scheduled_for = (
        state.get("last_scheduled_for")
        if isinstance(state.get("last_scheduled_for"), dict)
        else {}
    )
    completed_once = (
        state.get("completed_once")
        if isinstance(state.get("completed_once"), dict)
        else {}
    )
    completed_at = datetime.now(HKT).isoformat(timespec="seconds")
    explicit_schedule = parse_datetime(scheduled_for_hkt)
    frequencies = {
        int(item["row"]): str(item.get("frequency") or "")
        for item in read_live_schedule()
    }
    for row in rows:
        row_schedule = (
            explicit_schedule
            or parse_datetime(attempts.get(str(row)))
            or parse_datetime(completed_at)
        )
        attempts.pop(str(row), None)
        last_completed[str(row)] = completed_at
        if row_schedule:
            last_scheduled_for[str(row)] = row_schedule.isoformat(timespec="seconds")
        frequency = frequencies.get(row, "")
        schedule = canonical_schedule(frequency)
        if schedule and schedule[0] == "once":
            completed_once[str(row)] = frequency
    state["attempts"] = attempts
    state["last_completed"] = last_completed
    state["last_scheduled_for"] = last_scheduled_for
    state["completed_once"] = completed_once
    save_state(state)


def _recover_interrupted_pending_run() -> dict[str, object]:
    if PENDING_RUN_PATH.exists():
        return _load_pending_run()
    records = load_crawl_run_index()
    latest_completed = max(
        (
            parse_datetime(record.get("completed_at_hkt") or record.get("started_at_hkt"))
            for record in records
            if isinstance(record, dict)
            and record.get("trigger") == "定时爬虫"
            and record.get("run_status") == "completed"
        ),
        default=None,
    )
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("trigger") != "定时爬虫":
            continue
        if not record.get("interrupted"):
            continue
        if str(record.get("phase") or "") != "已中断":
            continue
        started_at = parse_datetime(record.get("started_at_hkt"))
        if started_at and latest_completed and latest_completed > started_at:
            continue
        rows = _scope_rows(str(record.get("scope") or ""))
        relative = str((record.get("local_files") or {}).get("stream_log") or "")
        stream_path = ROOT / relative if relative else Path()
        if not rows or not relative or not stream_path.exists():
            continue
        raw = stream_path.read_text(encoding="utf-8", errors="replace")
        if "网页抓取和飞书同步已完成" not in raw:
            continue
        sheet_matches = re.findall(r'"log_sheet_id"\s*:\s*"([^"]+)"', raw)
        if not sheet_matches:
            continue
        payload: dict[str, object] = {
            "version": 1,
            "stage": "sync_completed",
            "crawl_run_id": str(record.get("crawl_run_id") or ""),
            "rows": rows,
            "scope": str(record.get("scope") or ""),
            "started_at_hkt": str(record.get("started_at_hkt") or ""),
            "stream_log_path": str(stream_path),
            "log_sheet_id": sheet_matches[-1],
            "sync_return_code": 0,
            "recovered_from_interrupted_log": True,
            "last_attempt_at_hkt": "",
        }
        _write_pending_run(payload)
        return payload
    return {}


def _pending_run_was_interrupted(pending: dict[str, object]) -> bool:
    crawl_run_id = str(pending.get("crawl_run_id") or "")
    if not crawl_run_id:
        return False
    return any(
        str(record.get("crawl_run_id") or "") == crawl_run_id
        and bool(record.get("interrupted"))
        for record in load_crawl_run_index()
        if isinstance(record, dict)
    )


def crawl_process_running() -> bool:
    proc = subprocess.run(
        ["pgrep", "-f", str(ROOT / "crawl.py")],
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def agent_audit_process_running() -> bool:
    proc = subprocess.run(
        ["pgrep", "-f", str(ROOT / "run_data_curation.py")],
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def due_rows(now: datetime, state: dict[str, object]) -> tuple[list[int], list[dict[str, object]]]:
    attempts = state.get("attempts") if isinstance(state.get("attempts"), dict) else {}
    last_completed = (
        state.get("last_completed")
        if isinstance(state.get("last_completed"), dict)
        else {}
    )
    last_scheduled_for = (
        state.get("last_scheduled_for")
        if isinstance(state.get("last_scheduled_for"), dict)
        else {}
    )
    completed_once = state.get("completed_once") if isinstance(state.get("completed_once"), dict) else {}
    due: list[int] = []
    audit: list[dict[str, object]] = []
    for item in read_live_schedule():
        row_no = int(item["row"])
        configured_frequency = str(item.get("frequency") or "")
        frequency = (
            FINANCIAL_RESULT_DAILY_FREQUENCY
            if row_no in FINANCIAL_RESULT_ROWS
            else configured_frequency
        )
        schedule = canonical_schedule(frequency)
        last_attempt = parse_datetime(attempts.get(str(row_no)))
        result_success = (
            last_success(row_no, before=last_attempt)
            if last_attempt
            else last_success(row_no)
        )
        ledger_schedule = parse_datetime(last_scheduled_for.get(str(row_no)))
        legacy_completed = parse_datetime(last_completed.get(str(row_no)))
        # Scheduled occurrences are authoritative once available. Fetch and
        # completion times may cross midnight and must not consume tomorrow's slot.
        last_run = ledger_schedule or max(
            (value for value in (result_success, legacy_completed) if value),
            default=None,
        )
        next_run = next_run_time(frequency, last_run, now)
        status = "disabled" if schedule is None else "waiting"
        if schedule and schedule[0] == "once" and completed_once.get(str(row_no)) == frequency:
            status = "completed_once"
        elif next_run is not None and now >= next_run:
            if last_attempt and (now - last_attempt).total_seconds() < RETRY_SECONDS:
                status = "retry_backoff"
            else:
                status = "due"
                due.append(row_no)
        audit.append(
            {
                "row": row_no,
                "frequency": frequency,
                "configured_frequency": configured_frequency,
                "schedule_policy": (
                    "financial_results_next_day_sla"
                    if row_no in FINANCIAL_RESULT_ROWS
                    else "feishu_schedule"
                ),
                "last_success_hkt": last_run.isoformat(timespec="seconds") if last_run else None,
                "next_run_hkt": next_run.isoformat(timespec="seconds") if next_run else None,
                "status": status,
            }
        )
    return due, audit


def _append_process_output(path: Path, stdout: str = "", stderr: str = "") -> None:
    with path.open("a", encoding="utf-8") as fh:
        if stdout:
            fh.write(stdout)
            if not stdout.endswith("\n"):
                fh.write("\n")
        if stderr:
            fh.write(stderr)
            if not stderr.endswith("\n"):
                fh.write("\n")


def _agent_run_ids(output: str) -> list[str]:
    run_ids: list[str] = []
    for line in output.splitlines():
        if not line.startswith("AGENT_TRACE="):
            continue
        try:
            event = json.loads(line.removeprefix("AGENT_TRACE="))
        except (json.JSONDecodeError, TypeError):
            continue
        run_id = str(event.get("run_id") or "").strip()
        if run_id and run_id not in run_ids:
            run_ids.append(run_id)
    return run_ids


def _scheduled_agent_run_id(crawl_run_id: str) -> str:
    return f"scheduled_{crawl_run_id}"


def _infer_agent_audit_run_id(
    pending: dict[str, object],
    stream_log_path: Path,
) -> str:
    recorded = str(pending.get("agent_audit_run_id") or "").strip()
    if recorded:
        return recorded
    try:
        run_ids = _agent_run_ids(
            stream_log_path.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        run_ids = []
    if run_ids:
        return run_ids[-1]
    return _scheduled_agent_run_id(str(pending.get("crawl_run_id") or ""))


def _json_object_from_output(output: str) -> dict[str, object]:
    decoder = json.JSONDecoder()
    objects: list[tuple[int, int, dict[str, object]]] = []
    for match in re.finditer(r"\{", output):
        try:
            value, end = decoder.raw_decode(output, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append((end, -match.start(), value))
    return max(objects, key=lambda item: (item[0], item[1]))[2] if objects else {}


def _validated_curation_summary(run_id: str) -> tuple[dict[str, object], list[str]]:
    summary_path = ROOT / "curation_data" / "runs" / f"{run_id}.json"
    trace_path = ROOT / "curation_data" / "runs" / f"{run_id}_agent_trace.jsonl"
    problems: list[str] = []
    try:
        latest = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        return {}, [f"无法读取本轮 Agent 摘要：{exc}"]
    if str(latest.get("run_id") or "") != run_id:
        problems.append("Agent 摘要 run_id 与本轮进程输出不一致")
    if not str(latest.get("completed_at") or "").strip():
        problems.append("Agent 摘要缺少 completed_at")

    nodes: set[str] = set()
    event_count = 0
    try:
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if str(event.get("run_id") or "") != run_id:
                continue
            event_count += 1
            node = str(event.get("node") or "").strip()
            if node:
                nodes.add(node)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        problems.append(f"无法读取本轮 Agent trace：{exc}")
    if event_count == 0:
        problems.append("本轮 Agent trace 为空")
    missing_nodes = sorted(REQUIRED_AGENT_NODES - nodes)
    if missing_nodes:
        problems.append("Agent 审核节点未完整执行：" + "、".join(missing_nodes))

    extra = latest.get("extra") if isinstance(latest.get("extra"), dict) else {}
    summary: dict[str, object] = {
        "agent_run_id": run_id,
        "started_at": latest.get("started_at", ""),
        "completed_at": latest.get("completed_at", ""),
        "tasks": latest.get("tasks", 0),
        "accepted": latest.get("accepted", 0),
        "rejected": latest.get("rejected", 0),
        "review": latest.get("review", 0),
        "gaps": latest.get("gaps", 0),
        "recrawl_rows": latest.get("recrawl_rows", []),
        "agent_trace": str(trace_path.relative_to(ROOT)),
        "trace_events": event_count,
        "search_verification": extra.get("search_verification", {}),
        "company_agent_summary": extra.get("company_agent_summary", {}),
        "overall_status": extra.get("overall_status", ""),
    }
    search_verification = summary["search_verification"]
    if not isinstance(search_verification, dict) or not search_verification.get("online_search"):
        problems.append("最终合并 Agent 未启用联网补充搜索")
    elif not search_verification.get("online_coverage_complete"):
        problems.append(
            "最终合并 Agent 未完成全部主体×指标联网搜索："
            f"{search_verification.get('online_checked', 0)}/"
            f"{search_verification.get('online_required', latest.get('tasks', 0))}"
        )
    company_agent_summary = summary["company_agent_summary"]
    if not isinstance(company_agent_summary, dict) or not company_agent_summary.get("required"):
        problems.append("最终合并 Agent 未启用 41 公司 Multi-Agent 研究")
    elif not company_agent_summary.get("coverage_complete"):
        problems.append(
            "公司 Agent 报告未收齐："
            f"{company_agent_summary.get('completed', 0)}/"
            f"{company_agent_summary.get('expected', 41)}"
        )
    else:
        if not company_agent_summary.get("metric_coverage_complete"):
            problems.append(
                "公司 Agent 尚有未解决指标："
                f"{company_agent_summary.get('completed_metrics', 0)}/"
                f"{company_agent_summary.get('expected_metrics', 0)}"
            )
        if not company_agent_summary.get("publish_ready"):
            unresolved = company_agent_summary.get("unresolved_companies") or []
            problems.append(
                "公司 Agent 尚有未解决主体："
                + "、".join(str(company) for company in unresolved)
            )
    if summary["overall_status"] != "complete":
        problems.append(f"Agent 审核总体状态未完成：{summary['overall_status'] or '缺失'}")
    return summary, problems


def _run_scheduled_agent_audit(
    crawl_run_id: str,
    stream_log_path: Path,
    *,
    log_sheet_id: str = "",
    agent_run_id: str = "",
) -> tuple[bool, int, dict[str, object], dict[str, object], str]:
    expected_agent_run_id = str(agent_run_id or "").strip()
    command = [
        PYTHON,
        "-u",
        str(ROOT / "run_data_curation.py"),
        "--recrawl-gaps",
        "--max-recrawl-rows",
        "14",
        "--max-recrawl-rounds",
        "1",
        "--ai-workers",
        os.environ.get("CMHK_AI_WORKERS", "1"),
        "--search-verify-workers",
        os.environ.get("CMHK_SEARCH_VERIFY_WORKERS", "4"),
    ]
    if expected_agent_run_id:
        command.extend(["--run-id", expected_agent_run_id, "--resume"])
    if os.environ.get("CMHK_SEARCH_VERIFY_ONLINE", "1").lower() not in {"0", "false", "no", "off"}:
        command.extend(
            [
                "--search-verify-online",
                "--search-verify-online-limit",
                os.environ.get(
                    "CMHK_SEARCH_VERIFY_ONLINE_LIMIT",
                    DEFAULT_AGENT_AUDIT_ONLINE_LIMIT,
                ),
            ]
        )
    audit_env = os.environ.copy()
    for key in ("CMHK_ROWS", "CMHK_CRAWL_TRIGGER", "CMHK_CRAWL_SCOPE"):
        audit_env.pop(key, None)
    audit_env["PYTHONUNBUFFERED"] = "1"

    heartbeat_crawl_run(
        crawl_run_id,
        "Agent审核",
        "网页抓取和飞书同步已完成，正在执行完整 Agent 审核流程。",
        append_log=True,
    )
    stop_heartbeat = threading.Event()

    def keep_heartbeat() -> None:
        while not stop_heartbeat.wait(20):
            try:
                heartbeat_crawl_run(
                    crawl_run_id,
                    "Agent审核",
                    "Agent 正在执行事实抽取、质量审计、搜索验证和发布流程。",
                    append_log=False,
                )
            except Exception as exc:
                logging.warning("Agent 审核心跳更新失败：%s", exc)

    heartbeat_thread = threading.Thread(target=keep_heartbeat, name="scheduled-agent-audit-heartbeat", daemon=True)
    heartbeat_thread.start()
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            env=audit_env,
            text=True,
            capture_output=True,
            timeout=AGENT_AUDIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        _append_process_output(stream_log_path, stdout, stderr)
        curation = (
            {"agent_run_id": expected_agent_run_id, "checkpointed": True}
            if expected_agent_run_id
            else {}
        )
        return False, 124, curation, {}, f"Agent 审核超过 {AGENT_AUDIT_TIMEOUT_SECONDS} 秒"
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)

    _append_process_output(stream_log_path, proc.stdout or "", proc.stderr or "")
    run_ids = _agent_run_ids(proc.stdout or "")
    if proc.returncode:
        curation = {"agent_run_id": expected_agent_run_id} if expected_agent_run_id else {}
        return False, proc.returncode, curation, {}, f"Agent 审核进程失败，返回码 {proc.returncode}"
    if expected_agent_run_id and any(run_id != expected_agent_run_id for run_id in run_ids):
        return False, 1, {}, {}, f"Agent run_id 与预设检查点不一致：{run_ids}"
    if not expected_agent_run_id and len(run_ids) != 1:
        return False, 1, {}, {}, f"无法唯一确定本轮 Agent run_id：{run_ids or '未产生'}"

    agent_run_id = expected_agent_run_id or run_ids[0]
    curation, problems = _validated_curation_summary(agent_run_id)
    if problems:
        return False, 1, curation, {}, "；".join(problems)

    if not log_sheet_id:
        return True, 0, curation, {
            "ok": False,
            "skipped": True,
            "reason": "本次飞书同步未产生可用日志页 ID，Agent 已完成但 trace 未归档到飞书。",
            "agent_run_id": agent_run_id,
        }, ""

    heartbeat_crawl_run(
        crawl_run_id,
        "审核归档",
        "Agent 审核节点已全部完成，正在把本轮 trace 写入飞书日志。",
        append_log=True,
    )
    try:
        trace_proc = subprocess.run(
            [
                PYTHON,
                str(ROOT / "daily_crawl_and_write.py"),
                "--append-agent-trace",
                log_sheet_id,
                agent_run_id,
            ],
            cwd=ROOT,
            env=audit_env,
            text=True,
            capture_output=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        _append_process_output(stream_log_path, stdout, stderr)
        return False, 124, curation, {}, "Agent trace 写入飞书超时"
    _append_process_output(stream_log_path, trace_proc.stdout or "", trace_proc.stderr or "")
    trace_sync: dict[str, object] = {
        "ok": trace_proc.returncode == 0,
        "returnCode": trace_proc.returncode,
        "agent_run_id": agent_run_id,
        "log_sheet_id": log_sheet_id,
        "stdout": (trace_proc.stdout or "").strip(),
        "stderr": (trace_proc.stderr or "").strip(),
    }
    if trace_proc.returncode:
        return False, trace_proc.returncode, curation, trace_sync, "Agent trace 写入飞书失败"
    return True, 0, curation, trace_sync, ""


def _launch_executive_intelligence_refresh(
    crawl_run_id: str,
    stream_log_path: Path,
    curation: dict[str, object],
) -> dict[str, object]:
    """Launch the linked four-domain refresh and record its complete coverage contract."""
    domains = ["local", "international", "mainland", "cloud"]
    stages = [
        "database_refresh",
        "quality_gate",
        "official_source_recrawl",
        "19_insight_analysis_15_focuses_4_discoveries",
        "homepage_ui_refresh",
        "public_frontend_publish",
    ]
    if (
        ROOT != Path(__file__).resolve().parent
        or (
            any(name.rsplit(".", 1)[-1].startswith("test_") for name in sys.modules)
            and os.environ.get("CMHK_FORCE_INTELLIGENCE_REFRESH_FOR_TESTS") != "1"
        )
    ):
        return {
            "ok": True,
            "launched": False,
            "skipped": True,
            "reason": "non_production_root",
            "domains": domains,
            "stages": stages,
        }
    agent_run_id = str(curation.get("agent_run_id") or "").strip()
    if not agent_run_id:
        result: dict[str, object] = {
            "ok": False,
            "launched": False,
            "error": "Agent 审核摘要缺少 run_id，未启动四库刷新。",
        }
    else:
        try:
            from executive_intelligence_pipeline import launch_pipeline_async

            result = launch_pipeline_async(
                agent_run_id=agent_run_id,
                curation_summary=curation,
                parent_crawl_run_id=crawl_run_id,
            )
        except Exception as exc:
            result = {"ok": False, "launched": False, "error": str(exc)}
    append_crawl_run_event(
        stream_log_path,
        {
            "type": "executive_intelligence_refresh",
            "ok": bool(result.get("ok")),
            "launched": bool(result.get("launched")),
            "pid": result.get("pid"),
            "taskRunId": result.get("task_run_id"),
            "taskId": result.get("task_id"),
            "agentRunId": agent_run_id,
            "domains": domains,
            "stages": stages,
            "completionContract": "current_ui_four_domains_database_quality_source_recrawl_15_focus_4_discovery_homepage_public_frontend",
            "error": result.get("error", ""),
        },
    )
    result = {**result, "domains": domains, "stages": stages}
    if result.get("ok"):
        logging.info("当前UI四域数据库、质量门禁、官方来源复查、15项分域洞察、4条顶部跨库研判、主页与公开前端刷新已启动：%s", result)
    else:
        logging.warning("四域数据库与前端刷新未启动；守护进程将依据本轮爬虫日志补跑：%s", result)
    return result


def _publish_financial_frontend(stream_log_path: Path) -> dict[str, object]:
    if (
        any(name.startswith("test_") for name in sys.modules)
        and os.environ.get("CMHK_FORCE_FINANCIAL_FRONTEND_PUBLISH_FOR_TESTS") != "1"
    ):
        return {"ok": True, "skipped": True, "reason": "test_runtime"}
    environment = os.environ.copy()
    environment.setdefault("CMHK_INTELLIGENCE_SOURCE_URL", "http://127.0.0.1:8765/")
    completed = subprocess.run(
        [PYTHON, str(FINANCIAL_FRONTEND_PUBLISH_SCRIPT), "--force"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=900,
    )
    _append_process_output(stream_log_path, completed.stdout or "", completed.stderr or "")
    result = _json_object_from_output(completed.stdout or "") if completed.returncode == 0 else {}
    status = str(result.get("status") or "")
    ok = (
        completed.returncode == 0
        and status in {"published", "verified", "unchanged"}
        and str(result.get("site_version") or "")
        and str(result.get("public_url") or "").startswith("https://")
    )
    return {
        "ok": bool(ok),
        "returnCode": completed.returncode,
        "status": status or "failed",
        "site_version": str(result.get("site_version") or ""),
        "public_url": str(result.get("public_url") or ""),
        "commit": str(result.get("commit") or ""),
        "error": "" if ok else (completed.stderr or completed.stdout or "财报前端发布未返回有效结果")[-1200:],
    }


def _missing_financial_report_rows(financial_refresh: dict[str, object]) -> list[int]:
    return sorted(
        {
            int(item.get("row"))
            for item in financial_refresh.get("last_check") or []
            if isinstance(item, dict)
            and str(item.get("row") or "").isdigit()
            and item.get("status") == "no_official_report_discovered"
        }
    )


def _recrawl_missing_financial_reports(
    rows: list[int],
    stream_log_path: Path,
) -> dict[str, object]:
    targeted_rows = sorted(set(rows) & FINANCIAL_RESULT_ROWS)
    if not targeted_rows:
        return {"ok": False, "rows": [], "returnCode": 0, "error": "没有可补抓的财报行"}
    environment = os.environ.copy()
    environment["CMHK_ROWS"] = ",".join(str(row) for row in targeted_rows)
    environment["CMHK_CRAWL_MAX_SECONDS"] = "600"
    try:
        completed = subprocess.run(
            [PYTHON, str(ROOT / "crawl.py")],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=720,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        _append_process_output(stream_log_path, stdout, stderr)
        return {
            "ok": False,
            "rows": targeted_rows,
            "returnCode": 124,
            "error": "定向财报补抓超过 720 秒",
        }
    _append_process_output(stream_log_path, completed.stdout or "", completed.stderr or "")
    return {
        "ok": completed.returncode == 0,
        "rows": targeted_rows,
        "returnCode": completed.returncode,
        "error": "" if completed.returncode == 0 else (completed.stderr or completed.stdout or "定向财报补抓失败")[-1200:],
    }


def _monitor_executive_intelligence_refresh(now: datetime) -> dict[str, object]:
    if (
        any(name.startswith("test_") for name in sys.modules)
        and os.environ.get("CMHK_FORCE_INTELLIGENCE_WATCHDOG_FOR_TESTS") != "1"
    ):
        return {"ok": True, "skipped": True, "reason": "test_runtime"}
    try:
        from executive_intelligence_pipeline import monitor_scheduled_refresh_health

        return monitor_scheduled_refresh_health(now)
    except Exception as exc:
        logging.exception("四库刷新守护检查失败")
        return {"ok": False, "status": "watchdog_failed", "error": str(exc)}


def run_due_rows(rows: list[int], state: dict[str, object]) -> bool:
    started_monotonic = time.time()
    now = datetime.now(HKT)
    attempts = state.setdefault("attempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
        state["attempts"] = attempts
    for row in rows:
        attempts[str(row)] = now.isoformat(timespec="seconds")
    save_state(state)

    env = os.environ.copy()
    env["CMHK_ROWS"] = ",".join(str(row) for row in rows)
    env["CMHK_CRAWL_TRIGGER"] = "定时爬虫"
    env["CMHK_CRAWL_SCOPE"] = "定时指定行（" + "、".join(f"第{row}行" for row in rows) + "）"
    started_record = start_crawl_run(trigger="定时爬虫", scope=env["CMHK_CRAWL_SCOPE"])
    crawl_run_id = str(started_record["crawl_run_id"])
    stream_log_path = Path(started_record["stream_log_path"])
    agent_audit_run_id = _scheduled_agent_run_id(crawl_run_id)
    pending_run: dict[str, object] = {
        "version": 1,
        "stage": "crawl_running",
        "crawl_run_id": crawl_run_id,
        "rows": list(rows),
        "scope": env["CMHK_CRAWL_SCOPE"],
        "started_at_hkt": now.isoformat(timespec="seconds"),
        "scheduled_for_hkt": now.isoformat(timespec="seconds"),
        "stream_log_path": str(stream_log_path),
        "agent_audit_run_id": agent_audit_run_id,
        "agent_audit_control_version": AGENT_AUDIT_CONTROL_VERSION,
        "agent_audit_attempt_count": 0,
        "last_attempt_at_hkt": now.isoformat(timespec="seconds"),
    }
    _write_pending_run(pending_run)
    append_crawl_run_event(
        stream_log_path,
        {
            "type": "run_start",
            "crawlRunId": crawl_run_id,
            "startedAt": now.isoformat(timespec="seconds"),
            "trigger": "定时爬虫",
            "scope": env["CMHK_CRAWL_SCOPE"],
        },
    )
    logging.info("到期行开始爬取：%s", env["CMHK_ROWS"])
    crawl = subprocess.run(
        [PYTHON, "-u", str(ROOT / "crawl.py")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=1800,
    )
    with stream_log_path.open("a", encoding="utf-8") as fh:
        fh.write(crawl.stdout or "")
        fh.write(crawl.stderr or "")
    if crawl.returncode:
        logging.error("到期行爬取失败，退出码 %s", crawl.returncode)
        append_crawl_run_event(stream_log_path, {"type": "done", "ok": False, "stage": "crawl", "returnCode": crawl.returncode})
        register_crawl_run(
            crawl_return_code=crawl.returncode,
            duration_ms=round((time.time() - started_monotonic) * 1000),
            trigger="定时爬虫",
            scope=env["CMHK_CRAWL_SCOPE"],
            crawl_run_id=crawl_run_id,
            started_at_hkt=now.isoformat(timespec="seconds"),
            stream_log_path=stream_log_path,
            curation_summary={},
            failure_stage="crawl",
            progress_detail=f"网页抓取失败，返回码 {crawl.returncode}；Agent 审核未启动。",
        )
        _clear_pending_run()
        return False
    pending_run["stage"] = "crawl_completed"
    _write_pending_run(pending_run)
    sync = subprocess.run(
        [PYTHON, str(ROOT / "daily_crawl_and_write.py"), "--sync-only"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=1800,
    )
    with stream_log_path.open("a", encoding="utf-8") as fh:
        fh.write(sync.stdout or "")
        fh.write(sync.stderr or "")
    sync_result = _json_object_from_output(sync.stdout or "") if sync.returncode == 0 else {}
    log_sheet_id = str(sync_result.get("log_sheet_id") or "").strip()
    pending_run.update(
        {
            "stage": "sync_completed",
            "log_sheet_id": log_sheet_id,
            "sync_return_code": sync.returncode,
        }
    )
    _write_pending_run(pending_run)
    if sync.returncode:
        logging.error("到期行飞书同步失败，退出码 %s；继续执行 Agent 审核", sync.returncode)
        heartbeat_crawl_run(
            crawl_run_id,
            "Agent审核",
            f"飞书同步失败（返回码 {sync.returncode}），不阻断 Agent 审核；审核完成后任务仍会保留失败状态等待重试。",
            append_log=True,
        )

    audit_ok, audit_code, curation, trace_sync, audit_error = _run_scheduled_agent_audit(
        crawl_run_id,
        stream_log_path,
        log_sheet_id=log_sheet_id,
        agent_run_id=agent_audit_run_id,
    )
    if not audit_ok:
        pending_run.update(
            {
                "last_attempt_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"),
                "agent_audit_attempt_count": int(pending_run.get("agent_audit_attempt_count") or 0) + 1,
                "agent_audit_last_error": audit_error,
            }
        )
        _write_pending_run(pending_run)
        logging.error("定时爬虫 Agent 审核失败：%s", audit_error)
        append_crawl_run_event(
            stream_log_path,
            {"type": "done", "ok": False, "stage": "agent_review", "returnCode": audit_code, "error": audit_error},
        )
        register_crawl_run(
            crawl_return_code=audit_code or 1,
            duration_ms=round((time.time() - started_monotonic) * 1000),
            trace_sync=trace_sync,
            trigger="定时爬虫",
            scope=env["CMHK_CRAWL_SCOPE"],
            crawl_run_id=crawl_run_id,
            started_at_hkt=now.isoformat(timespec="seconds"),
            stream_log_path=stream_log_path,
            curation_summary=curation,
            failure_stage="agent_review",
            progress_detail=(
                f"飞书同步返回码 {sync.returncode}；" if sync.returncode else "网页抓取和飞书同步已完成；"
            ) + f"本轮 Agent 审核未通过完整性校验：{audit_error}",
        )
        return False
    pending_run.update(
        {
            "stage": "audit_completed",
            "curation": curation,
            "trace_sync": trace_sync,
        }
    )
    _write_pending_run(pending_run)

    if sync.returncode:
        append_crawl_run_event(
            stream_log_path,
            {
                "type": "done",
                "ok": False,
                "stage": "feishu_sync",
                "returnCode": sync.returncode,
                "agentReviewCompleted": True,
                "agentRunId": curation.get("agent_run_id", ""),
            },
        )
        register_crawl_run(
            crawl_return_code=sync.returncode,
            duration_ms=round((time.time() - started_monotonic) * 1000),
            trace_sync=trace_sync,
            trigger="定时爬虫",
            scope=env["CMHK_CRAWL_SCOPE"],
            crawl_run_id=crawl_run_id,
            started_at_hkt=now.isoformat(timespec="seconds"),
            stream_log_path=stream_log_path,
            curation_summary=curation,
            failure_stage="feishu_sync",
            progress_detail=(
                f"Agent 审核已完整执行（{curation.get('agent_run_id') or 'run_id 未记录'}），"
                f"但飞书同步失败，返回码 {sync.returncode}；任务将按退避策略重试。"
            ),
        )
        pending_run["stage"] = "crawl_completed"
        pending_run["last_attempt_at_hkt"] = datetime.now(HKT).isoformat(
            timespec="seconds"
        )
        pending_run.pop("curation", None)
        pending_run.pop("trace_sync", None)
        _write_pending_run(pending_run)
        return False

    financial_rows = sorted(set(rows) & FINANCIAL_RESULT_ROWS)
    if financial_rows:
        from cmhk.data.local_financial_results import rebuild_local_financial_database

        financial_refresh = rebuild_local_financial_database(rows=financial_rows)
        financial_quality = financial_refresh.get("quality") or {}
        curation = {**curation, "local_financial_results": financial_refresh}
        financial_checks = []
        for item in financial_refresh.get("last_check") or []:
            metrics = item.get("metrics") or []
            financial_checks.append(
                {
                    "row": item.get("row"),
                    "company": item.get("company"),
                    "status": item.get("status") or item.get("verification_status"),
                    "period": item.get("period", ""),
                    "publicationDate": item.get("publication_date", ""),
                    "nextDayDeadlineHkt": item.get("due_at_hkt", ""),
                    "sourceUrl": item.get("source_url", ""),
                    "coreMetricCount": item.get("core_metric_count", 0),
                    "metrics": [
                        {
                            "key": metric.get("metric_key", ""),
                            "label": metric.get("metric", ""),
                            "value": metric.get("value", ""),
                        }
                        for metric in metrics
                    ],
                }
            )
        append_crawl_run_event(
            stream_log_path,
            {
                "type": "local_financial_results",
                "ok": bool(financial_quality.get("ok")),
                "checkedRows": financial_rows,
                "checkedCompanies": financial_checks,
                "databasePath": financial_refresh.get("database_path", ""),
                "databaseUpdated": bool(financial_refresh.get("database_updated")),
                "databaseChanged": bool(financial_refresh.get("database_changed")),
                "generatedAtHkt": financial_refresh.get("generated_at_hkt", ""),
                "schedulePolicy": financial_refresh.get("schedule_policy", ""),
                "failures": financial_quality.get("failures") or [],
            },
        )
        logging.info(
            "本地竞对财报检查完成：rows=%s companies=%s database_updated=%s database_changed=%s failures=%s",
            financial_rows,
            [
                f"{item.get('company')}:{item.get('period') or item.get('status')}:{item.get('coreMetricCount')}项核心指标"
                for item in financial_checks
            ],
            bool(financial_refresh.get("database_updated")),
            bool(financial_refresh.get("database_changed")),
            financial_quality.get("failures") or [],
        )
        if not financial_quality.get("ok"):
            failures = "；".join(str(item) for item in financial_quality.get("failures") or [])
            register_crawl_run(
                crawl_return_code=1,
                duration_ms=round((time.time() - started_monotonic) * 1000),
                trace_sync=trace_sync,
                trigger="定时爬虫",
                scope=env["CMHK_CRAWL_SCOPE"],
                crawl_run_id=crawl_run_id,
                started_at_hkt=now.isoformat(timespec="seconds"),
                stream_log_path=stream_log_path,
                curation_summary=curation,
                failure_stage="local_financial_results",
                progress_detail=f"官方财报已检查，但结构化门禁失败：{failures}；不会把旧数据发布为成功。",
            )
            pending_run["last_attempt_at_hkt"] = datetime.now(HKT).isoformat(timespec="seconds")
            _write_pending_run(pending_run)
            return False

        financial_frontend_publish = _publish_financial_frontend(stream_log_path)
        curation = {**curation, "financial_frontend_publish": financial_frontend_publish}
        append_crawl_run_event(
            stream_log_path,
            {
                "type": "financial_frontend_publish",
                "ok": bool(financial_frontend_publish.get("ok")),
                "status": financial_frontend_publish.get("status", ""),
                "siteVersion": financial_frontend_publish.get("site_version", ""),
                "publicUrl": financial_frontend_publish.get("public_url", ""),
                "commit": financial_frontend_publish.get("commit", ""),
                "error": financial_frontend_publish.get("error", ""),
            },
        )
        if not financial_frontend_publish.get("ok"):
            publish_error = str(financial_frontend_publish.get("error") or "未返回有效发布结果")
            register_crawl_run(
                crawl_return_code=1,
                duration_ms=round((time.time() - started_monotonic) * 1000),
                trace_sync=trace_sync,
                trigger="定时爬虫",
                scope=env["CMHK_CRAWL_SCOPE"],
                crawl_run_id=crawl_run_id,
                started_at_hkt=now.isoformat(timespec="seconds"),
                stream_log_path=stream_log_path,
                curation_summary=curation,
                failure_stage="financial_frontend_publish",
                progress_detail=f"财报数据库已更新，但前端发布验证失败：{publish_error}；任务保留等待重试。",
            )
            pending_run["last_attempt_at_hkt"] = datetime.now(HKT).isoformat(timespec="seconds")
            _write_pending_run(pending_run)
            return False

    try:
        news_bridge = capture_completed_crawl(
            crawl_run_id,
            rows,
            captured_at=datetime.now(HKT),
        )
    except Exception as exc:
        bridge_error = f"定时爬虫新闻线索桥接失败：{exc}"
        logging.exception(bridge_error)
        append_crawl_run_event(
            stream_log_path,
            {
                "type": "done",
                "ok": False,
                "stage": "news_bridge",
                "error": bridge_error,
            },
        )
        register_crawl_run(
            crawl_return_code=1,
            duration_ms=round((time.time() - started_monotonic) * 1000),
            trace_sync=trace_sync,
            trigger="定时爬虫",
            scope=env["CMHK_CRAWL_SCOPE"],
            crawl_run_id=crawl_run_id,
            started_at_hkt=now.isoformat(timespec="seconds"),
            stream_log_path=stream_log_path,
            curation_summary=curation,
            failure_stage="news_bridge",
            progress_detail=(
                "网页抓取、飞书同步和 Agent 审核已完成；"
                f"{bridge_error}，任务将按退避策略重试。"
            ),
        )
        return False

    curation = {
        **curation,
        "news_bridge": news_bridge,
    }
    append_crawl_run_event(
        stream_log_path,
        {
            "type": "news_bridge",
            "ok": True,
            "bootstrap": bool(news_bridge.get("bootstrap")),
            "pageCount": int(news_bridge.get("page_count") or 0),
            "signalCount": int(news_bridge.get("signal_count") or 0),
        },
    )

    _mark_rows_completed(state, rows, scheduled_for_hkt=now)
    append_crawl_run_event(stream_log_path, {"type": "done", "ok": True, "returnCode": 0})
    register_crawl_run(
        crawl_return_code=0,
        duration_ms=round((time.time() - started_monotonic) * 1000),
        trigger="定时爬虫",
        scope=env["CMHK_CRAWL_SCOPE"],
        crawl_run_id=crawl_run_id,
        started_at_hkt=now.isoformat(timespec="seconds"),
        stream_log_path=stream_log_path,
        curation_summary=curation,
        trace_sync=trace_sync,
    )
    intelligence_refresh = _launch_executive_intelligence_refresh(
        crawl_run_id,
        stream_log_path,
        curation,
    )
    curation = {
        **curation,
        "executive_intelligence_refresh": intelligence_refresh,
    }
    register_crawl_run(
        crawl_return_code=0,
        duration_ms=round((time.time() - started_monotonic) * 1000),
        trigger="定时爬虫",
        scope=env["CMHK_CRAWL_SCOPE"],
        crawl_run_id=crawl_run_id,
        started_at_hkt=now.isoformat(timespec="seconds"),
        stream_log_path=stream_log_path,
        curation_summary=curation,
        trace_sync=trace_sync,
    )
    _clear_pending_run()
    logging.info("到期行爬取、Agent 审核与飞书归档完成：%s", rows)
    return True


def resume_pending_run(
    pending: dict[str, object],
    state: dict[str, object],
) -> bool:
    rows = [
        int(value)
        for value in pending.get("rows", [])
        if str(value).isdigit()
    ]
    crawl_run_id = str(pending.get("crawl_run_id") or "")
    stream_log_path = Path(str(pending.get("stream_log_path") or ""))
    scope = str(pending.get("scope") or "")
    started_at_hkt = str(pending.get("started_at_hkt") or "")
    if not rows or not crawl_run_id or not stream_log_path.exists():
        _clear_pending_run()
        return False

    resumed_at = datetime.now(HKT)
    pending["last_attempt_at_hkt"] = resumed_at.isoformat(timespec="seconds")
    _write_pending_run(pending)
    resume_crawl_run(
        crawl_run_id,
        "恢复未完成任务",
        "检测到服务重启前的已完成抓取结果，正在从下游阶段继续，不重复抓取网页。",
    )
    append_crawl_run_event(
        stream_log_path,
        {
            "type": "log",
            "text": "[任务续跑] 已复用本轮网页抓取结果，从飞书同步/Agent 审核阶段继续。",
        },
    )

    stage = str(pending.get("stage") or "")
    sync_return_code = int(pending.get("sync_return_code") or 0)
    log_sheet_id = str(pending.get("log_sheet_id") or "")
    if stage == "crawl_completed":
        heartbeat_crawl_run(
            crawl_run_id,
            "恢复飞书同步",
            "网页抓取已完成，正在重新执行飞书同步。",
            append_log=True,
        )
        env = os.environ.copy()
        env["CMHK_ROWS"] = ",".join(str(row) for row in rows)
        sync = subprocess.run(
            [PYTHON, str(ROOT / "daily_crawl_and_write.py"), "--sync-only"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=1800,
        )
        _append_process_output(stream_log_path, sync.stdout or "", sync.stderr or "")
        sync_result = _json_object_from_output(sync.stdout or "") if sync.returncode == 0 else {}
        sync_return_code = sync.returncode
        log_sheet_id = str(sync_result.get("log_sheet_id") or "").strip()
        if sync.returncode:
            register_crawl_run(
                crawl_return_code=sync.returncode,
                duration_ms=elapsed_ms(started_at_hkt),
                trigger="定时爬虫",
                scope=scope,
                crawl_run_id=crawl_run_id,
                started_at_hkt=started_at_hkt,
                stream_log_path=stream_log_path,
                curation_summary={},
                failure_stage="feishu_sync",
                progress_detail=f"续跑飞书同步失败，返回码 {sync.returncode}；保留抓取结果等待重试。",
            )
            return False
        pending.update(
            {
                "stage": "sync_completed",
                "log_sheet_id": log_sheet_id,
                "sync_return_code": 0,
            }
        )
        _write_pending_run(pending)
        stage = "sync_completed"

    if stage == "sync_completed":
        agent_audit_run_id = _infer_agent_audit_run_id(pending, stream_log_path)
        pending["agent_audit_run_id"] = agent_audit_run_id
        pending["agent_audit_control_version"] = AGENT_AUDIT_CONTROL_VERSION
        _write_pending_run(pending)
        audit_ok, audit_code, curation, trace_sync, audit_error = _run_scheduled_agent_audit(
            crawl_run_id,
            stream_log_path,
            log_sheet_id=log_sheet_id,
            agent_run_id=agent_audit_run_id,
        )
        if not audit_ok:
            pending.update(
                {
                    "last_attempt_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"),
                    "agent_audit_attempt_count": int(pending.get("agent_audit_attempt_count") or 0) + 1,
                    "agent_audit_last_error": audit_error,
                }
            )
            _write_pending_run(pending)
            register_crawl_run(
                crawl_return_code=audit_code or 1,
                duration_ms=elapsed_ms(started_at_hkt),
                trace_sync=trace_sync,
                trigger="定时爬虫",
                scope=scope,
                crawl_run_id=crawl_run_id,
                started_at_hkt=started_at_hkt,
                stream_log_path=stream_log_path,
                curation_summary=curation,
                failure_stage="agent_review",
                progress_detail=f"续跑 Agent 审核未通过：{audit_error}",
            )
            return False
        pending.update(
            {
                "stage": "audit_completed",
                "curation": curation,
                "trace_sync": trace_sync,
            }
        )
        _write_pending_run(pending)
        stage = "audit_completed"
    else:
        curation = (
            pending.get("curation")
            if isinstance(pending.get("curation"), dict)
            else {}
        )
        trace_sync = (
            pending.get("trace_sync")
            if isinstance(pending.get("trace_sync"), dict)
            else {}
        )

    if stage == "audit_completed":
        financial_rows = sorted(set(rows) & FINANCIAL_RESULT_ROWS)
        if financial_rows:
            from cmhk.data.local_financial_results import rebuild_local_financial_database

            financial_refresh = rebuild_local_financial_database(rows=financial_rows)
            financial_quality = financial_refresh.get("quality") or {}
            missing_financial_rows = _missing_financial_report_rows(financial_refresh)
            if not financial_quality.get("ok") and missing_financial_rows:
                financial_recrawl = _recrawl_missing_financial_reports(
                    missing_financial_rows,
                    stream_log_path,
                )
                append_crawl_run_event(
                    stream_log_path,
                    {
                        "type": "financial_recovery_recrawl",
                        "ok": bool(financial_recrawl.get("ok")),
                        "rows": financial_recrawl.get("rows") or [],
                        "returnCode": financial_recrawl.get("returnCode"),
                        "error": financial_recrawl.get("error", ""),
                        "resumed": True,
                    },
                )
                if financial_recrawl.get("ok"):
                    financial_refresh = rebuild_local_financial_database(rows=financial_rows)
                    financial_quality = financial_refresh.get("quality") or {}
            curation = {**curation, "local_financial_results": financial_refresh}
            financial_checks = []
            for item in financial_refresh.get("last_check") or []:
                metrics = item.get("metrics") or []
                financial_checks.append(
                    {
                        "row": item.get("row"),
                        "company": item.get("company"),
                        "status": item.get("status") or item.get("verification_status"),
                        "period": item.get("period", ""),
                        "publicationDate": item.get("publication_date", ""),
                        "nextDayDeadlineHkt": item.get("due_at_hkt", ""),
                        "sourceUrl": item.get("source_url", ""),
                        "coreMetricCount": item.get("core_metric_count", 0),
                        "metrics": [
                            {
                                "key": metric.get("metric_key", ""),
                                "label": metric.get("metric", ""),
                                "value": metric.get("value", ""),
                            }
                            for metric in metrics
                        ],
                    }
                )
            append_crawl_run_event(
                stream_log_path,
                {
                    "type": "local_financial_results",
                    "ok": bool(financial_quality.get("ok")),
                    "checkedRows": financial_rows,
                    "checkedCompanies": financial_checks,
                    "databasePath": financial_refresh.get("database_path", ""),
                    "databaseUpdated": bool(financial_refresh.get("database_updated")),
                    "databaseChanged": bool(financial_refresh.get("database_changed")),
                    "generatedAtHkt": financial_refresh.get("generated_at_hkt", ""),
                    "schedulePolicy": financial_refresh.get("schedule_policy", ""),
                    "failures": financial_quality.get("failures") or [],
                    "resumed": True,
                },
            )
            if not financial_quality.get("ok"):
                failures = "；".join(str(item) for item in financial_quality.get("failures") or [])
                pending.update({"curation": curation, "trace_sync": trace_sync})
                _write_pending_run(pending)
                register_crawl_run(
                    crawl_return_code=1,
                    duration_ms=elapsed_ms(started_at_hkt),
                    trace_sync=trace_sync,
                    trigger="定时爬虫",
                    scope=scope,
                    crawl_run_id=crawl_run_id,
                    started_at_hkt=started_at_hkt,
                    stream_log_path=stream_log_path,
                    curation_summary=curation,
                    failure_stage="local_financial_results",
                    progress_detail=f"续跑财报结构化门禁失败：{failures}；保留旧数据等待重试。",
                )
                return False

            financial_frontend_publish = _publish_financial_frontend(stream_log_path)
            curation = {**curation, "financial_frontend_publish": financial_frontend_publish}
            append_crawl_run_event(
                stream_log_path,
                {
                    "type": "financial_frontend_publish",
                    "ok": bool(financial_frontend_publish.get("ok")),
                    "status": financial_frontend_publish.get("status", ""),
                    "siteVersion": financial_frontend_publish.get("site_version", ""),
                    "publicUrl": financial_frontend_publish.get("public_url", ""),
                    "commit": financial_frontend_publish.get("commit", ""),
                    "error": financial_frontend_publish.get("error", ""),
                    "resumed": True,
                },
            )
            if not financial_frontend_publish.get("ok"):
                publish_error = str(financial_frontend_publish.get("error") or "未返回有效发布结果")
                pending.update({"curation": curation, "trace_sync": trace_sync})
                _write_pending_run(pending)
                register_crawl_run(
                    crawl_return_code=1,
                    duration_ms=elapsed_ms(started_at_hkt),
                    trace_sync=trace_sync,
                    trigger="定时爬虫",
                    scope=scope,
                    crawl_run_id=crawl_run_id,
                    started_at_hkt=started_at_hkt,
                    stream_log_path=stream_log_path,
                    curation_summary=curation,
                    failure_stage="financial_frontend_publish",
                    progress_detail=f"续跑财报数据库已更新，但前端发布验证失败：{publish_error}。",
                )
                return False
        pending.update(
            {
                "stage": "financial_completed",
                "curation": curation,
                "trace_sync": trace_sync,
            }
        )
        _write_pending_run(pending)
        stage = "financial_completed"

    if sync_return_code:
        pending["stage"] = "crawl_completed"
        _write_pending_run(pending)
        return False
    try:
        news_bridge = capture_completed_crawl(
            crawl_run_id,
            rows,
            captured_at=datetime.now(HKT),
        )
    except Exception as exc:
        register_crawl_run(
            crawl_return_code=1,
            duration_ms=elapsed_ms(started_at_hkt),
            trace_sync=trace_sync,
            trigger="定时爬虫",
            scope=scope,
            crawl_run_id=crawl_run_id,
            started_at_hkt=started_at_hkt,
            stream_log_path=stream_log_path,
            curation_summary=curation,
            failure_stage="news_bridge",
            progress_detail=f"续跑 Agent 审核已完成，但新闻线索桥接失败：{exc}",
        )
        return False

    curation = {
        **curation,
        "news_bridge": news_bridge,
    }
    append_crawl_run_event(
        stream_log_path,
        {
            "type": "news_bridge",
            "ok": True,
            "bootstrap": bool(news_bridge.get("bootstrap")),
            "pageCount": int(news_bridge.get("page_count") or 0),
            "signalCount": int(news_bridge.get("signal_count") or 0),
            "resumed": True,
        },
    )
    _mark_rows_completed(
        state,
        rows,
        scheduled_for_hkt=pending.get("scheduled_for_hkt") or started_at_hkt,
    )
    append_crawl_run_event(
        stream_log_path,
        {"type": "done", "ok": True, "returnCode": 0, "resumed": True},
    )
    register_crawl_run(
        crawl_return_code=0,
        duration_ms=elapsed_ms(started_at_hkt),
        trigger="定时爬虫",
        scope=scope,
        crawl_run_id=crawl_run_id,
        started_at_hkt=started_at_hkt,
        stream_log_path=stream_log_path,
        curation_summary=curation,
        trace_sync=trace_sync,
        progress_detail="服务重启后已复用抓取结果，Agent 审核、飞书归档和新闻线索桥接均已完成。",
    )
    intelligence_refresh = _launch_executive_intelligence_refresh(
        crawl_run_id,
        stream_log_path,
        curation,
    )
    curation = {
        **curation,
        "executive_intelligence_refresh": intelligence_refresh,
    }
    register_crawl_run(
        crawl_return_code=0,
        duration_ms=elapsed_ms(started_at_hkt),
        trigger="定时爬虫",
        scope=scope,
        crawl_run_id=crawl_run_id,
        started_at_hkt=started_at_hkt,
        stream_log_path=stream_log_path,
        curation_summary=curation,
        trace_sync=trace_sync,
        progress_detail="服务重启后已复用抓取结果，Agent 审核、飞书归档和新闻线索桥接均已完成。",
    )
    _clear_pending_run()
    return True


def dispatch_subscription_queue(*, dry_run: bool = False) -> dict[str, object]:
    """Dispatch due subscriber messages without coupling failures to crawler scheduling."""
    try:
        from cmhk.services.subscriptions import SubscriptionService

        service = SubscriptionService(runtime_root=ROOT)
        if dry_run:
            return {"ok": True, "dry_run": True, "due_count": service.due_count()}
        return {"ok": True, **service.flush_due()}
    except Exception as exc:
        logging.exception("订阅频率派发失败")
        return {"ok": False, "error": str(exc)[:900]}


def dispatch_scheduled_weekly_report(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, object]:
    """Generate and deliver the weekly report when the saved monthly slot is due."""
    try:
        from cmhk.services.subscriptions import SubscriptionService

        service = SubscriptionService(runtime_root=ROOT)
        return service.run_due_weekly_report(now=now or datetime.now(HKT), dry_run=dry_run)
    except Exception as exc:
        logging.exception("定时周报生成与推送失败")
        return {"ok": False, "error": str(exc)[:1200]}


def dispatch_scheduled_performance_report(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, object]:
    """Deliver the selected performance summary when its saved monthly slot is due."""
    try:
        from cmhk.services.subscriptions import SubscriptionService

        service = SubscriptionService(runtime_root=ROOT)
        return service.run_due_performance_report(now=now or datetime.now(HKT), dry_run=dry_run)
    except Exception as exc:
        logging.exception("定时业绩摘要推送失败")
        return {"ok": False, "error": str(exc)[:1200]}


def run_due_four_database_source_discovery(
    now: datetime,
    state: dict[str, object],
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    """Run the independent 01:00 search-agent handoff once per HKT day."""
    today = now.astimezone(HKT).date().isoformat()
    due = now.hour >= 1 and str(state.get("four_database_source_discovery_date") or "") != today
    if not due:
        return {"ok": True, "due": False, "scheduled_for": f"{today}T01:00:00+08:00"}
    if dry_run:
        return {"ok": True, "due": True, "dry_run": True, "scheduled_for": f"{today}T01:00:00+08:00"}
    if crawl_process_running() or agent_audit_process_running():
        return {"ok": True, "due": True, "skipped": "crawler_or_agent_audit_running"}
    from four_database_source_discovery import run_discovery

    result = run_discovery(now)
    if result.get("ok"):
        state["four_database_source_discovery_date"] = today
        state["four_database_source_discovery_run_id"] = result.get("run_id")
        save_state(state)
    return {"due": True, **result}


def run_cycle(*, dry_run: bool = False) -> dict[str, object]:
    now = datetime.now(HKT)
    state = load_state()
    resume_state = dict(state)
    source_discovery = run_due_four_database_source_discovery(now, state, dry_run=dry_run)
    subscription_dispatch = dispatch_subscription_queue(dry_run=dry_run)
    weekly_report_dispatch = dispatch_scheduled_weekly_report(dry_run=True, now=now)
    performance_report_dispatch = dispatch_scheduled_performance_report(dry_run=True, now=now)
    watchdog = (
        {"ok": True, "skipped": True, "reason": "dry_run"}
        if dry_run
        else _monitor_executive_intelligence_refresh(now)
    )
    pending = _load_pending_run()
    if not dry_run and not pending:
        pending = _recover_interrupted_pending_run()
    if pending:
        result: dict[str, object] = {
            "checked_at_hkt": now.isoformat(timespec="seconds"),
            "timezone": "Asia/Hong_Kong",
            "executive_intelligence_watchdog": watchdog,
            "subscription_dispatch": subscription_dispatch,
            "weekly_report_dispatch": weekly_report_dispatch,
            "performance_report_dispatch": performance_report_dispatch,
            "four_database_source_discovery": source_discovery,
            "pending_run_id": pending.get("crawl_run_id"),
            "pending_stage": pending.get("stage"),
        }
        if dry_run:
            result["resume_due"] = True
            return result
        last_resume = parse_datetime(pending.get("last_attempt_at_hkt"))
        interrupted_resume = _pending_run_was_interrupted(pending)
        control_upgrade_due = (
            str(pending.get("stage") or "") == "sync_completed"
            and int(pending.get("agent_audit_control_version") or 0)
            < AGENT_AUDIT_CONTROL_VERSION
        )
        if (
            last_resume
            and not interrupted_resume
            and not control_upgrade_due
            and (now - last_resume).total_seconds() < RETRY_SECONDS
        ):
            result["resume_skipped"] = "retry_backoff"
            return result
        if str(pending.get("stage") or "") == "crawl_running":
            _clear_pending_run()
        elif crawl_process_running():
            result["resume_skipped"] = "crawl_already_running"
            return result
        elif agent_audit_process_running():
            result["resume_skipped"] = "agent_audit_already_running"
            return result
        else:
            # The independent 01:00 handoff may update scheduler bookkeeping in
            # this same cycle. A pending 03:00 crawl resumes against the state
            # snapshot it originally loaded, so unrelated discovery metadata
            # cannot alter its recovery contract.
            result["resumed"] = resume_pending_run(pending, resume_state)
            return result
    due, audit = due_rows(now, state)
    result: dict[str, object] = {
        "checked_at_hkt": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Hong_Kong",
        "executive_intelligence_watchdog": watchdog,
        "subscription_dispatch": subscription_dispatch,
        "weekly_report_dispatch": weekly_report_dispatch,
        "performance_report_dispatch": performance_report_dispatch,
        "four_database_source_discovery": source_discovery,
        "due_rows": due,
        "rows": audit,
    }
    if dry_run:
        return result
    if not due:
        if crawl_process_running() or agent_audit_process_running():
            result["weekly_report_dispatch"] = {
                **weekly_report_dispatch,
                "skipped": "crawler_or_agent_audit_running",
            }
            result["performance_report_dispatch"] = {
                **performance_report_dispatch,
                "skipped": "crawler_or_agent_audit_running",
            }
            logging.info("爬虫或 Agent 审核正在运行，本轮暂缓定时报告推送")
            return result
        result["weekly_report_dispatch"] = dispatch_scheduled_weekly_report(now=now)
        result["performance_report_dispatch"] = dispatch_scheduled_performance_report(now=now)
        logging.info("本轮无到期行")
        return result
    if crawl_process_running():
        logging.info("已有爬虫运行，本轮跳过，到期行：%s", due)
        result["skipped"] = "crawl_already_running"
        return result
    result["success"] = run_due_rows(due, state)
    return result


def main() -> None:
    global _SCHEDULER_HEARTBEAT
    parser = argparse.ArgumentParser(description="CMHK 飞书频率调度器")
    parser.add_argument("--once", action="store_true", help="只检查一次")
    parser.add_argument("--dry-run", action="store_true", help="只输出到期判断，不执行爬虫")
    args = parser.parse_args()
    if args.once or args.dry_run:
        print(json.dumps(run_cycle(dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return
    _SCHEDULER_HEARTBEAT = SchedulerHeartbeat()
    _SCHEDULER_HEARTBEAT.start()
    logging.info("飞书频率调度器启动，时区 Asia/Hong_Kong，每 %s 秒检查一次", POLL_SECONDS)
    while True:
        try:
            run_cycle()
        except Exception:
            logging.exception("调度周期失败")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
