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


ROOT = Path(__file__).resolve().parent
SPREADSHEET_TOKEN = crawl.SPREADSHEET_TOKEN
MAIN_SHEET_ID = crawl.MAIN_SHEET_ID
LARK_CLI = crawl.LARK_CLI
RESULT_HEADER_PREFIXES = ("数据爬取更新", "本轮爬虫日志摘要", "原始数据")
PERFORMANCE_SYNC_SCRIPT = ROOT / "sync_carrier_performance_feishu.py"
AGENT_TRACE_PATH = ROOT / "curation_data" / "agent_trace.jsonl"
CURATION_LATEST_PATH = ROOT / "curation_data" / "latest.json"
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


def create_log_sheet() -> tuple[str, str]:
    title = "爬虫日志_" + datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d_%H%M%S")
    payload = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
    output = run_cmd(
        [
            LARK_CLI,
            "api",
            "POST",
            f"/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}/sheets_batch_update",
            "--data",
            json.dumps(payload, ensure_ascii=False),
        ],
        timeout=120,
    )
    data = json_from_output(output)
    sheet_id = data["data"]["replies"][0]["addSheet"]["properties"]["sheetId"]
    return sheet_id, title


def write_range(cell_range: str, values: list[list[str]]) -> None:
    run_cmd(
        [
            LARK_CLI,
            "sheets",
            "+write",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--range",
            cell_range,
            "--values",
            json.dumps(values, ensure_ascii=False),
        ],
        timeout=180,
    )


def set_style(cell_range: str, style: dict) -> None:
    run_cmd(
        [
            LARK_CLI,
            "sheets",
            "+set-style",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
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


def read_range(cell_range: str) -> list[list[object]]:
    output = run_cmd(
        [
            LARK_CLI,
            "sheets",
            "+read",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
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
    """Return 0-based column insertion index immediately after the latest crawl result triplet."""
    last_group_start: int | None = None
    for i in range(0, len(headers) - 2):
        triple = headers[i : i + 3]
        if all(triple[j].startswith(RESULT_HEADER_PREFIXES[j]) for j in range(3)):
            last_group_start = i
    if last_group_start is not None:
        return last_group_start + 3
    # Fallback for a fresh sheet: insert after the last existing column
    return len(headers)


def prepare_result_columns(run_label: str) -> dict:
    headers = current_headers()
    insert_index = find_result_insert_index(headers)

    expected_headers = [f"数据爬取更新{run_label}", f"本轮爬虫日志摘要{run_label}", f"原始数据{run_label}"]

    # Check if the previous group matches the run_label
    if insert_index >= 3 and headers[insert_index - 3:insert_index] == expected_headers:
        # Reuse existing columns
        start_col = col_to_a1(insert_index - 2)
        mid_col = col_to_a1(insert_index - 1)
        end_col = col_to_a1(insert_index)
        is_new = False
        target_index = insert_index - 3
    else:
        # Insert 3 new columns
        insert_columns(insert_index, 3)
        start_col = col_to_a1(insert_index + 1)
        mid_col = col_to_a1(insert_index + 2)
        end_col = col_to_a1(insert_index + 3)
        is_new = True
        target_index = insert_index

    if is_new:
        write_range(f"{MAIN_SHEET_ID}!{start_col}1:{end_col}1", [expected_headers])
        set_style(
            f"{MAIN_SHEET_ID}!{start_col}1:{end_col}34",
            {"backColor": "#F3F8FF", "borderType": "FULL_BORDER", "borderColor": "#2F54EB"},
        )
        set_style(
            f"{MAIN_SHEET_ID}!{start_col}1:{end_col}1",
            {"backColor": "#DCEBFF", "font": {"bold": True}, "borderType": "FULL_BORDER", "borderColor": "#1D4ED8"},
        )

    return {
        "run_label": run_label,
        "start_col": start_col,
        "mid_col": mid_col,
        "end_col": end_col,
        "insert_index": target_index,
        "data_range": f"{MAIN_SHEET_ID}!{start_col}2:{end_col}34",
        "header_range": f"{MAIN_SHEET_ID}!{start_col}1:{end_col}1",
    }


def write_log_sheet(sheet_id: str) -> None:
    with (ROOT / "run_log.tsv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows:
        raise RuntimeError("run_log.tsv is empty")
    end_row = len(rows)
    end_col = chr(ord("A") + len(rows[0]) - 1)
    write_range(f"{sheet_id}!A1:{end_col}{end_row}", rows)


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


def append_agent_trace_to_log_sheet(sheet_id: str, run_id: str = "") -> dict:
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
        write_range(f"{sheet_id}!A{batch_start}:{end_col}{batch_end}", batch)
    set_style(
        f"{sheet_id}!A{start_row}:{end_col}{start_row}",
        {
            "backColor": "#0B5CAD",
            "font": {"bold": True, "foreColor": "#FFFFFF"},
            "borderType": "FULL_BORDER",
            "borderColor": "#0B5CAD",
        },
    )
    set_style(
        f"{sheet_id}!A{header_row}:{end_col}{header_row}",
        {
            "backColor": "#DCEBFF",
            "font": {"bold": True},
            "borderType": "FULL_BORDER",
            "borderColor": "#8DBBE8",
        },
    )
    set_style(
        f"{sheet_id}!A{data_start_row}:{end_col}{data_end_row}",
        {
            "backColor": "#F7FBFF",
            "borderType": "FULL_BORDER",
            "borderColor": "#D7E6F5",
        },
    )

    readback = read_range(f"{sheet_id}!A{start_row}:{end_col}{data_end_row}")
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
        "run_id": run_id,
        "trace_rows": len(trace_rows),
        "range": f"{sheet_id}!A{start_row}:{end_col}{data_end_row}",
        "problems": problems,
    }
    if problems:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))
    return result


def regenerate_payload_with_log_title(log_sheet_title: str) -> None:
    results = []
    for row in range(2, 35):
        result = json.loads((ROOT / "results" / f"row_{row}.json").read_text(encoding="utf-8"))
        result["log_sheet_title"] = log_sheet_title
        results.append(result)
    crawl.write_outputs(results)


def get_sources_column(headers: list[str]) -> str:
    for name in ["可能来源/系统", "可能来源"]:
        try:
            return col_to_a1(headers.index(name) + 1)
        except ValueError:
            pass
    return "F"


def validate_payload_and_readback(result_columns: dict, sources_col: str, payload: dict) -> dict:
    rows = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    entity_rows = {int(row["row"]): row.get("entities", []) for row in rows if len(row.get("entities", [])) > 1}
    problems: list[str] = []
    compliance_gaps: list[str] = []

    f_payload = payload.get("sources_payload") or payload.get("F2:F34")
    ij_payload = payload.get("results_payload") or payload.get("I2:K34")

    if len(f_payload) != 33 or len(ij_payload) != 33:
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
        i_cell, log_cell, raw_cell = ij_payload[idx]
        for entity in entities:
            if f"【{entity}】" not in f_cell:
                problems.append(f"row {row_no} entity {entity} missing labeled block in F payload")
            if f"【{entity}】" not in i_cell:
                problems.append(f"row {row_no} entity {entity} missing labeled block in I payload")
            for label, cell in [("J", log_cell), ("K", raw_cell)]:
                if entity not in cell:
                    problems.append(f"row {row_no} entity {entity} missing in {label} payload")
    readback_f = read_range(f"{MAIN_SHEET_ID}!{sources_col}2:{sources_col}34")
    readback_results = read_range(result_columns["data_range"])
    readback_headers = read_range(result_columns["header_range"])
    header_text = [cell_text(value) for value in readback_headers[0]] if readback_headers else []
    expected_headers = [
        f"数据爬取更新{result_columns['run_label']}",
        f"本轮爬虫日志摘要{result_columns['run_label']}",
        f"原始数据{result_columns['run_label']}",
    ]
    if header_text != expected_headers:
        problems.append(f"result headers mismatch: {header_text} != {expected_headers}")
    readback = []
    for idx in range(33):
        f_row = readback_f[idx] if idx < len(readback_f) else []
        r_row = readback_results[idx] if idx < len(readback_results) else []
        readback.append([(f_row[0] if f_row else ""), *r_row])
    if len(readback) != 33:
        problems.append(f"readback row count is {len(readback)}, expected 33")
    for idx, row in enumerate(readback, start=2):
        f_cell = cell_text(row[0]) if len(row) > 0 else ""
        i_cell = cell_text(row[1]) if len(row) > 1 else ""
        j_cell = cell_text(row[2]) if len(row) > 2 else ""
        k_cell = cell_text(row[3]) if len(row) > 3 else ""
        if not all([f_cell, i_cell, j_cell, k_cell]):
            problems.append(f"row {idx} readback has empty F/I/J/K")
        for entity in entity_rows.get(idx, []):
            if f"【{entity}】" not in f_cell:
                problems.append(f"row {idx} entity {entity} missing labeled block in readback F")
            if f"【{entity}】" not in i_cell:
                problems.append(f"row {idx} entity {entity} missing labeled block in readback I")
            for label, cell in [("J", j_cell), ("K", k_cell)]:
                if entity not in cell:
                    problems.append(f"row {idx} entity {entity} missing in readback {label}")
    return {
        "ok": not problems,
        "problems": problems,
        "compliance_gaps": compliance_gaps,
        "checked_at_hkt": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "result_columns": result_columns,
    }


def sync_to_feishu() -> None:
    run_label = f"({datetime.now(ZoneInfo('Asia/Hong_Kong')).strftime('%m-%d')})"
    log_sheet_id, log_sheet_title = create_log_sheet()
    regenerate_payload_with_log_title(log_sheet_title)

    headers = current_headers()
    sources_col = get_sources_column(headers)

    payload = json.loads((ROOT / "write_payload.json").read_text(encoding="utf-8"))
    f_payload = payload.get("sources_payload") or payload.get("F2:F34")
    ij_payload = payload.get("results_payload") or payload.get("I2:K34")

    result_columns = prepare_result_columns(run_label)
    write_range(f"{MAIN_SHEET_ID}!{sources_col}2:{sources_col}34", f_payload)
    write_range(result_columns["data_range"], ij_payload)
    write_log_sheet(log_sheet_id)
    validation = validate_payload_and_readback(result_columns, sources_col, payload)
    validation["log_sheet_id"] = log_sheet_id
    validation["log_sheet_title"] = log_sheet_title
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
