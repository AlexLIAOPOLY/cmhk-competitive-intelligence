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

from crawl_run_registry import (
    append_crawl_run_event,
    heartbeat_crawl_run,
    register_crawl_run,
    start_crawl_run,
)


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
STATE_PATH = ROOT / "scheduler_state.json"
SPREADSHEET_TOKEN = "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
MAIN_SHEET_ID = "9c638d"
HKT = ZoneInfo("Asia/Hong_Kong")
POLL_SECONDS = max(30, int(os.environ.get("CMHK_SCHEDULER_POLL_SECONDS", "60")))
RETRY_SECONDS = max(300, int(os.environ.get("CMHK_SCHEDULER_RETRY_SECONDS", "1800")))
LARK_CLI = shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"
PYTHON = sys.executable
FREQUENCY_HEADERS = ("更新频率", "更新频次", "收集频率", "排期频率", "每隔多长时间收集一轮")
AGENT_AUDIT_TIMEOUT_SECONDS = max(600, int(os.environ.get("CMHK_AGENT_AUDIT_TIMEOUT_SECONDS", "3600")))
REQUIRED_AGENT_NODES = {
    "证据接收",
    "来源分类",
    "事实抽取",
    "主体校验",
    "质量审计",
    "冲突仲裁",
    "搜索验证",
    "缺口规划",
    "编排决策",
    "发布",
}


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


def read_live_schedule() -> list[dict[str, object]]:
    proc = subprocess.run(
        [
            LARK_CLI,
            "sheets",
            "+read",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--range",
            f"{MAIN_SHEET_ID}!A1:Z34",
            "--value-render-option",
            "FormattedValue",
        ],
        cwd=ROOT,
        env=no_proxy_env(),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    values = json.loads(proc.stdout)["data"]["valueRange"]["values"]
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
    for row_no in range(2, 35):
        row = values[row_no - 1] if row_no - 1 < len(values) else []
        frequency = cell_text(row[frequency_index] if frequency_index < len(row) else None).strip()
        rows.append({"row": row_no, "frequency": frequency})
    return rows


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


def last_success(row_no: int) -> datetime | None:
    path = RESULTS_DIR / f"row_{row_no}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parse_datetime(payload.get("fetched_at_hkt") or payload.get("fetched_at"))


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
        return {"attempts": {}, "completed_once": {}}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"attempts": {}, "completed_once": {}}
    state.setdefault("attempts", {})
    state.setdefault("completed_once", {})
    return state


def save_state(state: dict[str, object]) -> None:
    state["updated_at_hkt"] = datetime.now(HKT).isoformat(timespec="seconds")
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def crawl_process_running() -> bool:
    proc = subprocess.run(
        ["pgrep", "-f", str(ROOT / "crawl.py")],
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def due_rows(now: datetime, state: dict[str, object]) -> tuple[list[int], list[dict[str, object]]]:
    attempts = state.get("attempts") if isinstance(state.get("attempts"), dict) else {}
    completed_once = state.get("completed_once") if isinstance(state.get("completed_once"), dict) else {}
    due: list[int] = []
    audit: list[dict[str, object]] = []
    for item in read_live_schedule():
        row_no = int(item["row"])
        frequency = str(item.get("frequency") or "")
        schedule = canonical_schedule(frequency)
        last_run = last_success(row_no)
        next_run = next_run_time(frequency, last_run, now)
        status = "disabled" if schedule is None else "waiting"
        if schedule and schedule[0] == "once" and completed_once.get(str(row_no)) == frequency:
            status = "completed_once"
        elif next_run is not None and now >= next_run:
            last_attempt = parse_datetime(attempts.get(str(row_no)))
            if last_attempt and (now - last_attempt).total_seconds() < RETRY_SECONDS:
                status = "retry_backoff"
            else:
                status = "due"
                due.append(row_no)
        audit.append(
            {
                "row": row_no,
                "frequency": frequency,
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


def _json_object_from_output(output: str) -> dict[str, object]:
    match = re.search(r"\{.*\}\s*$", output, re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


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
    }
    return summary, problems


def _run_scheduled_agent_audit(
    crawl_run_id: str,
    stream_log_path: Path,
    *,
    log_sheet_id: str = "",
) -> tuple[bool, int, dict[str, object], dict[str, object], str]:
    command = [
        PYTHON,
        "-u",
        str(ROOT / "run_data_curation.py"),
        "--recrawl-gaps",
        "--max-recrawl-rows",
        "6",
        "--max-recrawl-rounds",
        "1",
        "--ai-workers",
        os.environ.get("CMHK_AI_WORKERS", "3"),
        "--search-verify-workers",
        os.environ.get("CMHK_SEARCH_VERIFY_WORKERS", "4"),
    ]
    if os.environ.get("CMHK_SEARCH_VERIFY_ONLINE", "1").lower() not in {"0", "false", "no", "off"}:
        command.extend(
            [
                "--search-verify-online",
                "--search-verify-online-limit",
                os.environ.get("CMHK_SEARCH_VERIFY_ONLINE_LIMIT", "0"),
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
        return False, 124, {}, {}, f"Agent 审核超过 {AGENT_AUDIT_TIMEOUT_SECONDS} 秒"
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)

    _append_process_output(stream_log_path, proc.stdout or "", proc.stderr or "")
    run_ids = _agent_run_ids(proc.stdout or "")
    if proc.returncode:
        return False, proc.returncode, {}, {}, f"Agent 审核进程失败，返回码 {proc.returncode}"
    if len(run_ids) != 1:
        return False, 1, {}, {}, f"无法唯一确定本轮 Agent run_id：{run_ids or '未产生'}"

    agent_run_id = run_ids[0]
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
        return False
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
    )
    if not audit_ok:
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
        return False

    completed_once = state.setdefault("completed_once", {})
    if not isinstance(completed_once, dict):
        completed_once = {}
        state["completed_once"] = completed_once
    frequencies = {int(item["row"]): str(item.get("frequency") or "") for item in read_live_schedule()}
    for row in rows:
        attempts.pop(str(row), None)
        schedule = canonical_schedule(frequencies.get(row, ""))
        if schedule and schedule[0] == "once":
            completed_once[str(row)] = frequencies[row]
    save_state(state)
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
    logging.info("到期行爬取、Agent 审核与飞书归档完成：%s", rows)
    return True


def run_cycle(*, dry_run: bool = False) -> dict[str, object]:
    now = datetime.now(HKT)
    state = load_state()
    due, audit = due_rows(now, state)
    result: dict[str, object] = {
        "checked_at_hkt": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Hong_Kong",
        "due_rows": due,
        "rows": audit,
    }
    if dry_run:
        return result
    if not due:
        logging.info("本轮无到期行")
        return result
    if crawl_process_running():
        logging.info("已有爬虫运行，本轮跳过，到期行：%s", due)
        result["skipped"] = "crawl_already_running"
        return result
    result["success"] = run_due_rows(due, state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="CMHK 飞书频率调度器")
    parser.add_argument("--once", action="store_true", help="只检查一次")
    parser.add_argument("--dry-run", action="store_true", help="只输出到期判断，不执行爬虫")
    args = parser.parse_args()
    if args.once or args.dry_run:
        print(json.dumps(run_cycle(dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return
    logging.info("飞书频率调度器启动，时区 Asia/Hong_Kong，每 %s 秒检查一次", POLL_SECONDS)
    while True:
        try:
            run_cycle()
        except Exception:
            logging.exception("调度周期失败")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
