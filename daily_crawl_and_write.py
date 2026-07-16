from __future__ import annotations

import csv
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import crawl
from crawl_log_formatter import write_and_format_crawl_log_sheet


ROOT = Path(__file__).resolve().parent
SPREADSHEET_TOKEN = crawl.SPREADSHEET_TOKEN
MAIN_SHEET_ID = crawl.MAIN_SHEET_ID
LARK_CLI = crawl.LARK_CLI
RESULT_HEADER_PREFIXES = ("数据爬取更新", "本轮爬虫日志摘要", "原始数据")
PERFORMANCE_SYNC_SCRIPT = ROOT / "sync_carrier_performance_feishu.py"
AGENT_TRACE_PATH = ROOT / "curation_data" / "agent_trace.jsonl"
CURATION_LATEST_PATH = ROOT / "curation_data" / "latest.json"
LOG_INDEX_SHEET_TITLE = "爬虫历史记录链接"
INPUT_SOURCE_HEADERS = ("待爬链接", "来源/系统", "可能来源/系统", "可能来源")
SUCCESS_SOURCE_HEADER = "本轮成功来源"
AGENT_TRACE_HEADERS = [
    "时间",
    "运行ID",
    "序号",
    "Agent节点",
    "阶段",
    "事件类型",
    "处理说明",
    "调用工具",
    "输入摘要",
    "输出/结果",
    "状态",
]
LOCAL_PROXY_CANDIDATES = (
    "http://127.0.0.1:7897",
    "http://127.0.0.1:7890",
)


def local_proxy_env(base_env: dict[str, str] | None = None) -> dict[str, str] | None:
    env = (base_env or os.environ).copy()
    configured = next(
        (
            env.get(key)
            for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
            if env.get(key)
        ),
        "",
    )
    candidates = [configured, *LOCAL_PROXY_CANDIDATES]
    for proxy_url in dict.fromkeys(value for value in candidates if value):
        match = re.match(r"^https?://([^:/]+):(\d+)$", proxy_url)
        if not match:
            continue
        try:
            with socket.create_connection((match.group(1), int(match.group(2))), timeout=0.8):
                pass
        except OSError:
            continue
        env.pop("LARK_CLI_NO_PROXY", None)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env[key] = proxy_url
        return env
    return None


def feishu_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env["LARK_CLI_NO_PROXY"] = "1"
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        env.pop(key, None)
    return env


def feishu_proxy_env_if_needed() -> dict[str, str] | None:
    env = os.environ.copy()
    try:
        resolved = socket.gethostbyname("open.feishu.cn")
    except OSError:
        resolved = ""
    # 198.18.0.0/15 is commonly a local proxy fake-IP range and is not
    # directly routable. In that case the configured proxy is the usable path.
    if not resolved or resolved.startswith(("198.18.", "198.19.")):
        return local_proxy_env(env)
    return None


def run_cmd(args: list[str], *, timeout: int = 180) -> str:
    original_env = os.environ.copy()
    direct_env = feishu_cli_env()
    proxy_env = feishu_proxy_env_if_needed() or local_proxy_env(original_env)
    environments = [proxy_env, direct_env] if proxy_env else [direct_env]
    proc = None
    for attempt in range(3):
        command_env = environments[min(attempt, len(environments) - 1)]
        proc = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=command_env,
        )
        if proc.returncode == 0:
            break
        network_error = f"{proc.stderr}\n{proc.stdout}".lower()
        if not any(
            marker in network_error
            for marker in ("no such host", "lookup open.feishu.cn", "i/o timeout", "connection refused")
        ):
            break
        refreshed_proxy_env = local_proxy_env(original_env)
        if refreshed_proxy_env:
            environments = [refreshed_proxy_env, direct_env]
        time.sleep(1.0 + attempt)
    assert proc is not None
    (ROOT / "last_daily_command.log").open("a", encoding="utf-8").write(
        f"\n$ {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n"
    )
    if proc.returncode:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr}\n{proc.stdout}")
    return proc.stdout


def json_from_output(output: str) -> dict:
    match = re.search(r"\{.*\}\s*$", output, re.S)
    if not match:
        raise ValueError(f"no JSON object found in output: {output[:500]}")
    return json.loads(match.group(0))


def refresh_sheet_snapshot() -> None:
    output = run_cmd(
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
        timeout=120,
    )
    data = json_from_output(output)
    (ROOT / "feishu_latest_AJ.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_log_spreadsheet() -> dict[str, str]:
    timestamp = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d_%H%M%S")
    sheet_title = os.environ.get("CMHK_LOG_SHEET_TITLE") or f"爬虫日志_{timestamp}"
    spreadsheet_title = os.environ.get("CMHK_LOG_SPREADSHEET_TITLE") or f"CMHK爬虫日志_{timestamp}"
    spreadsheet_token = os.environ.get("CMHK_LOG_SPREADSHEET_TOKEN", "").strip()

    if not spreadsheet_token:
        output = run_cmd(
            [LARK_CLI, "sheets", "+create", "--title", spreadsheet_title],
            timeout=120,
        )
        created = json_from_output(output)["data"]
        spreadsheet_token = str(created["spreadsheet_token"])

    info_output = run_cmd(
        [LARK_CLI, "sheets", "+info", "--spreadsheet-token", spreadsheet_token],
        timeout=120,
    )
    info = json_from_output(info_output)["data"]
    spreadsheet = info["spreadsheet"]["spreadsheet"]
    sheet = info["sheets"]["sheets"][0]
    sheet_id = str(sheet["sheet_id"])
    spreadsheet_url = str(spreadsheet["url"])

    if str(sheet.get("title") or "") != sheet_title:
        run_cmd(
            [
                LARK_CLI,
                "sheets",
                "+update-sheet",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--title",
                sheet_title,
            ],
            timeout=120,
        )

    grid = sheet.get("grid_properties") or {}
    row_count = int(grid.get("row_count") or 0)
    column_count = int(grid.get("column_count") or 0)
    for dimension, missing in (
        ("ROWS", max(0, 1000 - row_count)),
        ("COLUMNS", max(0, 30 - column_count)),
    ):
        if not missing:
            continue
        run_cmd(
            [
                LARK_CLI,
                "sheets",
                "+add-dimension",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--dimension",
                dimension,
                "--length",
                str(missing),
            ],
            timeout=120,
        )

    return {
        "spreadsheet_token": spreadsheet_token,
        "spreadsheet_title": str(spreadsheet.get("title") or spreadsheet_title),
        "spreadsheet_url": spreadsheet_url,
        "sheet_id": sheet_id,
        "sheet_title": sheet_title,
    }


def write_range(
    cell_range: str,
    values: list[list[str]],
    *,
    spreadsheet_token: str = SPREADSHEET_TOKEN,
) -> None:
    run_cmd(
        [
            LARK_CLI,
            "sheets",
            "+write",
            "--spreadsheet-token",
            spreadsheet_token,
            "--range",
            cell_range,
            "--values",
            json.dumps(values, ensure_ascii=False),
        ],
        timeout=180,
    )


def set_style(
    cell_range: str,
    style: dict,
    *,
    spreadsheet_token: str = SPREADSHEET_TOKEN,
) -> None:
    run_cmd(
        [
            LARK_CLI,
            "sheets",
            "+set-style",
            "--spreadsheet-token",
            spreadsheet_token,
            "--range",
            cell_range,
            "--style",
            json.dumps(style, ensure_ascii=False),
        ],
        timeout=120,
    )


def insert_columns(start_index: int, count: int = 3) -> None:
    run_cmd(
        [
            LARK_CLI,
            "sheets",
            "+insert-dimension",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--sheet-id",
            MAIN_SHEET_ID,
            "--dimension",
            "COLUMNS",
            "--start-index",
            str(start_index),
            "--end-index",
            str(start_index + count),
            "--inherit-style",
            "BEFORE",
        ],
        timeout=120,
    )


def read_range(
    cell_range: str,
    *,
    spreadsheet_token: str = SPREADSHEET_TOKEN,
) -> list[list[object]]:
    output = run_cmd(
        [
            LARK_CLI,
            "sheets",
            "+read",
            "--spreadsheet-token",
            spreadsheet_token,
            "--range",
            cell_range,
            "--value-render-option",
            "FormattedValue",
        ],
        timeout=120,
    )
    data = json_from_output(output)["data"]
    value_range = data.get("valueRange") or data.get("value_range") or {}
    return value_range.get("values") or []


def cell_text(value: object) -> str:
    if isinstance(value, list):
        return "".join((item.get("text") or item.get("link") or "") if isinstance(item, dict) else str(item) for item in value)
    return "" if value is None else str(value)


def col_to_a1(index_1_based: int) -> str:
    result = ""
    n = index_1_based
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def current_headers() -> list[str]:
    rows = read_range(f"{MAIN_SHEET_ID}!A1:ZZ1")
    if not rows:
        raise RuntimeError("Sheet1 header row is empty")
    return [cell_text(value).strip() for value in rows[0]]


def find_result_insert_index(headers: list[str]) -> int:
    """Return the 0-based insertion index after the latest crawl result column."""
    last_result_end: int | None = None
    for i in range(0, len(headers) - 2):
        triple = headers[i : i + 3]
        if all(triple[j].startswith(RESULT_HEADER_PREFIXES[j]) for j in range(3)):
            last_result_end = i + 3
    for i, header in enumerate(headers):
        if header.startswith("爬虫日志("):
            last_result_end = max(last_result_end or 0, i + 1)
    if last_result_end is not None:
        return last_result_end
    # Fallback for a fresh sheet: insert after the last existing column
    return len(headers)


def prepare_result_columns(run_label: str) -> dict:
    headers = current_headers()
    insert_index = find_result_insert_index(headers)
    expected_header = f"爬虫日志{run_label}"

    if insert_index >= 1 and headers[insert_index - 1] == expected_header:
        log_col = col_to_a1(insert_index)
        is_new = False
        target_index = insert_index - 1
    else:
        insert_columns(insert_index, 1)
        log_col = col_to_a1(insert_index + 1)
        is_new = True
        target_index = insert_index

    if is_new:
        write_range(f"{MAIN_SHEET_ID}!{log_col}1:{log_col}1", [[expected_header]])
        set_style(
            f"{MAIN_SHEET_ID}!{log_col}1:{log_col}34",
            {"backColor": "#F3F8FF", "borderType": "FULL_BORDER", "borderColor": "#2F54EB"},
        )
        set_style(
            f"{MAIN_SHEET_ID}!{log_col}1:{log_col}1",
            {"backColor": "#DCEBFF", "font": {"bold": True}, "borderType": "FULL_BORDER", "borderColor": "#1D4ED8"},
        )

    return {
        "run_label": run_label,
        "log_col": log_col,
        "insert_index": target_index,
        "data_range": f"{MAIN_SHEET_ID}!{log_col}2:{log_col}34",
        "header_range": f"{MAIN_SHEET_ID}!{log_col}1:{log_col}1",
    }


def write_log_sheet(sheet_id: str, spreadsheet_token: str) -> None:
    with (ROOT / "run_log.tsv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    if not rows:
        raise RuntimeError("run_log.tsv is empty")
    result = write_and_format_crawl_log_sheet(
        root=ROOT,
        sheet_id=sheet_id,
        spreadsheet_token=spreadsheet_token,
        source_rows=rows,
        write_range=write_range,
        read_range=read_range,
        set_style=set_style,
        run_cmd=run_cmd,
        lark_cli=LARK_CLI,
    )
    print(json.dumps({"crawl_log_format": result}, ensure_ascii=False))


def compact_json_cell(value: object, limit: int = 12000) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load_agent_trace_rows(run_id: str = "") -> tuple[str, list[list[str]]]:
    if not run_id and CURATION_LATEST_PATH.exists():
        latest = json.loads(CURATION_LATEST_PATH.read_text(encoding="utf-8"))
        run_id = str(latest.get("run_id") or "")
    if not run_id:
        raise RuntimeError("无法确定要写入飞书的 Agent 运行 ID")
    if not AGENT_TRACE_PATH.exists():
        raise RuntimeError(f"Agent trace 不存在：{AGENT_TRACE_PATH}")

    events: list[dict] = []
    for line in AGENT_TRACE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(event.get("run_id") or "") == run_id:
            events.append(event)
    if not events:
        run_trace = ROOT / "curation_data" / "runs" / f"{run_id}_agent_trace.jsonl"
        if run_trace.exists():
            events = [
                json.loads(line)
                for line in run_trace.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
    if not events:
        raise RuntimeError(f"未找到运行 {run_id} 的 Agent trace")

    phase_labels = {
        "observe": "观察/读取",
        "thinking": "Agent判断",
        "decision": "执行决定",
        "answer": "处理结果",
        "tool_call": "工具调用",
        "tool_result": "工具结果",
    }
    rows: list[list[str]] = []
    for sequence, event in enumerate(events, start=1):
        phase = str(event.get("phase") or "")
        output = event.get("result") if phase == "tool_result" else event.get("output")
        status = "成功"
        if phase == "tool_result":
            result = event.get("result")
            if isinstance(result, dict) and (
                result.get("ok") is False
                or result.get("returnCode") not in (None, 0)
                or result.get("status") in {"error", "failed"}
            ):
                status = "失败"
        elif phase == "tool_call":
            status = "调用"
        elif phase == "observe":
            status = "处理中"
        elif phase == "thinking":
            status = "判断中"
        elif phase == "decision":
            status = "已决定"
            output = {
                "decision": event.get("decision"),
                "output": event.get("output"),
            }
        rows.append(
            [
                compact_json_cell(event.get("ts")),
                run_id,
                str(sequence),
                compact_json_cell(event.get("node")),
                phase_labels.get(phase, phase),
                compact_json_cell(event.get("event_type")),
                compact_json_cell(event.get("message")),
                compact_json_cell(event.get("tool")),
                compact_json_cell(event.get("input")),
                compact_json_cell(output),
                status,
            ]
        )
    return run_id, rows


def append_agent_trace_to_log_sheet(
    sheet_id: str,
    run_id: str = "",
    spreadsheet_token: str = "",
) -> dict:
    if not spreadsheet_token and (ROOT / "daily_validation.json").exists():
        validation = json.loads((ROOT / "daily_validation.json").read_text(encoding="utf-8"))
        if str(validation.get("log_sheet_id") or "") == sheet_id:
            spreadsheet_token = str(validation.get("log_spreadsheet_token") or "")
    spreadsheet_token = spreadsheet_token or SPREADSHEET_TOKEN
    run_id, trace_rows = load_agent_trace_rows(run_id)
    with (ROOT / "run_log.tsv").open(encoding="utf-8", newline="") as fh:
        crawl_rows = list(csv.reader(fh, delimiter="\t"))
    start_row = len(crawl_rows) + 3
    header_row = start_row + 1
    data_start_row = header_row + 1
    data_end_row = data_start_row + len(trace_rows) - 1
    end_col = col_to_a1(len(AGENT_TRACE_HEADERS))

    all_rows = [
        ["AGENT处理流程与结果", "", "", "", "", "", "", "", "", "", ""],
        AGENT_TRACE_HEADERS,
        *trace_rows,
    ]
    for offset in range(0, len(all_rows), 8):
        batch = all_rows[offset : offset + 8]
        batch_start = start_row + offset
        batch_end = batch_start + len(batch) - 1
        write_range(
            f"{sheet_id}!A{batch_start}:{end_col}{batch_end}",
            batch,
            spreadsheet_token=spreadsheet_token,
        )
    set_style(
        f"{sheet_id}!A{start_row}:{end_col}{start_row}",
        {
            "backColor": "#0B5CAD",
            "font": {"bold": True, "foreColor": "#FFFFFF"},
            "borderType": "FULL_BORDER",
            "borderColor": "#0B5CAD",
        },
        spreadsheet_token=spreadsheet_token,
    )
    set_style(
        f"{sheet_id}!A{header_row}:{end_col}{header_row}",
        {
            "backColor": "#DCEBFF",
            "font": {"bold": True},
            "borderType": "FULL_BORDER",
            "borderColor": "#8DBBE8",
        },
        spreadsheet_token=spreadsheet_token,
    )
    set_style(
        f"{sheet_id}!A{data_start_row}:{end_col}{data_end_row}",
        {
            "backColor": "#F7FBFF",
            "borderType": "FULL_BORDER",
            "borderColor": "#D7E6F5",
        },
        spreadsheet_token=spreadsheet_token,
    )

    readback = read_range(
        f"{sheet_id}!A{start_row}:{end_col}{data_end_row}",
        spreadsheet_token=spreadsheet_token,
    )
    readback_run_ids = {
        cell_text(row[1]).strip()
        for row in readback[2:]
        if len(row) > 1 and cell_text(row[1]).strip()
    }
    problems = []
    if len(readback) != len(trace_rows) + 2:
        problems.append(f"回读行数 {len(readback)}，预期 {len(trace_rows) + 2}")
    if readback_run_ids != {run_id}:
        problems.append(f"回读运行 ID 不一致：{sorted(readback_run_ids)}")
    result = {
        "ok": not problems,
        "sheet_id": sheet_id,
        "spreadsheet_token": spreadsheet_token,
        "run_id": run_id,
        "trace_rows": len(trace_rows),
        "range": f"{sheet_id}!A{start_row}:{end_col}{data_end_row}",
        "problems": problems,
    }
    if problems:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))
    return result


def regenerate_payload_with_log_title(log_sheet_title: str, log_spreadsheet_url: str) -> None:
    results = []
    for row in range(2, 35):
        result = json.loads((ROOT / "results" / f"row_{row}.json").read_text(encoding="utf-8"))
        result["log_sheet_title"] = log_sheet_title
        result["log_spreadsheet_url"] = log_spreadsheet_url
        results.append(result)
    crawl.write_outputs(results)


def build_log_link_payload(log_spreadsheet_url: str) -> list[list[str]]:
    values: list[list[str]] = []
    for row_no in range(2, 35):
        result = json.loads((ROOT / "results" / f"row_{row_no}.json").read_text(encoding="utf-8"))
        status = "成功" if result.get("status") == "ok" else str(result.get("status") or "待检查")
        attempted = len(result.get("raw_records") or [])
        succeeded = int(result.get("live_fetch_success_count") or len(result.get("source_urls") or []))
        values.append([f"{status}｜URL {succeeded}/{attempted}\n{log_spreadsheet_url}"])
    return values


def current_crawl_scope() -> str:
    explicit_scope = os.environ.get("CMHK_CRAWL_SCOPE", "").strip()
    if explicit_scope:
        return explicit_scope
    rows = sorted(
        {
            int(value)
            for value in re.findall(r"\d+", os.environ.get("CMHK_ROWS", ""))
            if 2 <= int(value) <= 34
        }
    )
    if not rows:
        return "全量（第2-34行）"
    return "指定行（" + "、".join(f"第{row}行" for row in rows) + "）"


def current_crawl_trigger() -> str:
    explicit_trigger = os.environ.get("CMHK_CRAWL_TRIGGER", "").strip()
    if explicit_trigger:
        return explicit_trigger
    return "定时爬虫" if os.environ.get("CMHK_ROWS", "").strip() else "手动全量"


def append_log_index(log_target: dict[str, str]) -> dict:
    info = json_from_output(
        run_cmd(
            [LARK_CLI, "sheets", "+info", "--spreadsheet-token", SPREADSHEET_TOKEN],
            timeout=120,
        )
    )["data"]
    sheets = info.get("sheets", {}).get("sheets", [])
    index_sheet = next((sheet for sheet in sheets if sheet.get("title") == LOG_INDEX_SHEET_TITLE), None)
    if not index_sheet:
        created = json_from_output(
            run_cmd(
                [
                    LARK_CLI,
                    "sheets",
                    "+create-sheet",
                    "--spreadsheet-token",
                    SPREADSHEET_TOKEN,
                    "--title",
                    LOG_INDEX_SHEET_TITLE,
                ],
                timeout=120,
            )
        )["data"]
        index_sheet = {"sheet_id": created["sheet_id"]}
        write_range(
            f"{created['sheet_id']}!A1:F1",
            [["执行时间（香港）", "触发方式", "日志名称", "存储位置", "打开日志", "爬取范围"]],
        )

    sheet_id = str(index_sheet["sheet_id"])
    rows = read_range(f"{sheet_id}!A1:F1000")
    if not rows or len(rows[0]) < 6 or cell_text(rows[0][5]) != "爬取范围":
        write_range(
            f"{sheet_id}!A1:F1",
            [["执行时间（香港）", "触发方式", "日志名称", "存储位置", "打开日志", "爬取范围"]],
        )
    log_url = log_target["spreadsheet_url"]
    if any(log_url in cell_text(cell) for row in rows for cell in row):
        return {"ok": True, "sheet_id": sheet_id, "url": log_url, "inserted": False}

    run_cmd(
        [
            LARK_CLI,
            "sheets",
            "+insert-dimension",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--sheet-id",
            sheet_id,
            "--dimension",
            "ROWS",
            "--start-index",
            "1",
            "--end-index",
            "2",
            "--inherit-style",
            "AFTER",
        ],
        timeout=120,
    )
    timestamp_match = re.search(r"([0-9]{8})_([0-9]{6})", log_target["sheet_title"])
    if timestamp_match:
        timestamp = datetime.strptime("".join(timestamp_match.groups()), "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    else:
        timestamp = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M:%S")
    write_range(
        f"{sheet_id}!A2:F2",
        [[timestamp, current_crawl_trigger(), log_target["spreadsheet_title"], "独立日志", log_url, current_crawl_scope()]],
    )
    return {"ok": True, "sheet_id": sheet_id, "url": log_url, "inserted": True}


def get_input_sources_column(headers: list[str]) -> str:
    for name in INPUT_SOURCE_HEADERS:
        try:
            return col_to_a1(headers.index(name) + 1)
        except ValueError:
            pass
    return "F"


def get_success_sources_column(headers: list[str]) -> str:
    try:
        return col_to_a1(headers.index(SUCCESS_SOURCE_HEADER) + 1)
    except ValueError:
        pass

    insert_index = len(headers)
    for name in INPUT_SOURCE_HEADERS:
        if name in headers:
            insert_index = headers.index(name) + 1
            break
    insert_columns(insert_index, 1)
    success_col = col_to_a1(insert_index + 1)
    write_range(f"{MAIN_SHEET_ID}!{success_col}1:{success_col}1", [[SUCCESS_SOURCE_HEADER]])
    set_style(
        f"{MAIN_SHEET_ID}!{success_col}1:{success_col}34",
        {"backColor": "#F6FFED", "borderType": "FULL_BORDER", "borderColor": "#52C41A"},
    )
    set_style(
        f"{MAIN_SHEET_ID}!{success_col}1:{success_col}1",
        {"backColor": "#D9F7BE", "font": {"bold": True}, "borderType": "FULL_BORDER", "borderColor": "#389E0D"},
    )
    return success_col


def validate_payload(payload: dict) -> dict:
    rows = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    entity_rows = {int(row["row"]): row.get("entities", []) for row in rows if len(row.get("entities", [])) > 1}
    problems: list[str] = []
    compliance_gaps: list[str] = []

    f_payload = payload.get("successful_sources_payload") or payload.get("sources_payload") or payload.get("F2:F34")
    if len(f_payload) != 33:
        problems.append("payload row count is not 33")
    for row_no in range(2, 35):
        result = json.loads((ROOT / "results" / f"row_{row_no}.json").read_text(encoding="utf-8"))
        if result.get("missing_fields") or result.get("entity_missing"):
            compliance_gaps.append(f"row {row_no} missing fields: {result.get('missing_fields')} {result.get('entity_missing')}")
        skipped = [rec for rec in result.get("raw_records", []) if rec.get("method") == "skipped"]
        if skipped:
            compliance_gaps.append(
                f"row {row_no} compliance skipped URLs: "
                + "; ".join(f"{rec.get('url')} ({rec.get('skip_reason')})" for rec in skipped[:8])
            )
        for entity_result in result.get("entity_results", []):
            if entity_result.get("status") != "ok":
                compliance_gaps.append(f"row {row_no} entity {entity_result.get('entity')} status {entity_result.get('status')}")
            if not entity_result.get("source_urls"):
                compliance_gaps.append(f"row {row_no} entity {entity_result.get('entity')} has no source url")
    for row_no, entities in entity_rows.items():
        idx = row_no - 2
        f_cell = f_payload[idx][0]
        for entity in entities:
            if f"【{entity}】" not in f_cell:
                problems.append(f"row {row_no} entity {entity} missing labeled block in F payload")
    return {
        "ok": not problems,
        "problems": problems,
        "compliance_gaps": compliance_gaps,
        "checked_at_hkt": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(),
    }


def sync_to_feishu() -> None:
    log_target = create_log_spreadsheet()
    log_sheet_id = log_target["sheet_id"]
    log_sheet_title = log_target["sheet_title"]
    regenerate_payload_with_log_title(log_sheet_title, log_target["spreadsheet_url"])

    headers = current_headers()
    input_sources_col = get_input_sources_column(headers)

    payload = json.loads((ROOT / "write_payload.json").read_text(encoding="utf-8"))

    write_log_sheet(log_sheet_id, log_target["spreadsheet_token"])
    log_index = append_log_index(log_target)
    validation = validate_payload(payload)
    validation["input_sources_range"] = f"{MAIN_SHEET_ID}!{input_sources_col}2:{input_sources_col}34"
    validation["log_sheet_id"] = log_sheet_id
    validation["log_sheet_title"] = log_sheet_title
    validation["log_spreadsheet_token"] = log_target["spreadsheet_token"]
    validation["log_spreadsheet_title"] = log_target["spreadsheet_title"]
    validation["log_spreadsheet_url"] = log_target["spreadsheet_url"]
    validation["log_index"] = log_index
    (ROOT / "daily_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    if not validation["ok"]:
        raise SystemExit(json.dumps(validation, ensure_ascii=False, indent=2))
    print(json.dumps(validation, ensure_ascii=False, indent=2))


def sync_carrier_performance() -> dict:
    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, str(PERFORMANCE_SYNC_SCRIPT)],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )
    result = {
        "ok": proc.returncode == 0,
        "returnCode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }
    validation_path = ROOT / "daily_validation.json"
    validation = (
        json.loads(validation_path.read_text(encoding="utf-8"))
        if validation_path.exists()
        else {}
    )
    validation["carrier_performance"] = result
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"运营商业绩摘要补充页同步失败：{proc.stderr or proc.stdout}")
    return result


def main() -> None:
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--sync-only":
        sync_to_feishu()
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--append-agent-trace":
        append_agent_trace_to_log_sheet(
            sys.argv[2],
            sys.argv[3] if len(sys.argv) > 3 else "",
            sys.argv[4] if len(sys.argv) > 4 else "",
        )
        return

    (ROOT / "last_daily_command.log").write_text("", encoding="utf-8")
    refresh_sheet_snapshot()
    os.environ.setdefault("CMHK_CRAWL_MAX_SECONDS", "1200")
    crawl.main()
    sync_to_feishu()
    sync_carrier_performance()


if __name__ == "__main__":
    main()
