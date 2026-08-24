from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import crawl
import daily_crawl_and_write as daily
from cmhk.crawl.log_formatter import write_and_format_crawl_log_sheet


TOKEN_PATTERN = re.compile(r"/sheets/([A-Za-z0-9]+)")


def spreadsheet_info(token: str) -> dict[str, Any]:
    output = daily.run_cmd(
        [daily.LARK_CLI, "sheets", "+info", "--spreadsheet-token", token],
        timeout=120,
    )
    payload = daily.json_from_output(output)
    return payload.get("data") if isinstance(payload.get("data"), dict) else {}


def sheet_items(info: dict[str, Any]) -> list[dict[str, Any]]:
    container = info.get("sheets") if isinstance(info.get("sheets"), dict) else {}
    items = container.get("sheets") if isinstance(container.get("sheets"), list) else []
    return [item for item in items if isinstance(item, dict)]


def add_token(tokens: set[str], value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    match = TOKEN_PATTERN.search(text)
    token = match.group(1) if match else text
    if re.fullmatch(r"[A-Za-z0-9]+", token) and token != crawl.SPREADSHEET_TOKEN:
        tokens.add(token)


def discover_log_tokens() -> list[str]:
    tokens: set[str] = set()
    validation_path = ROOT / "daily_validation.json"
    if validation_path.exists():
        try:
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            add_token(tokens, validation.get("log_spreadsheet_token"))
            add_token(tokens, validation.get("log_spreadsheet_url"))
        except (OSError, ValueError, TypeError):
            pass
    registry_path = ROOT / "agent_knowledge" / "crawl_run_logs" / "index.json"
    if registry_path.exists():
        try:
            records = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            records = []
        for record in records if isinstance(records, list) else []:
            feishu = record.get("feishu") if isinstance(record, dict) and isinstance(record.get("feishu"), dict) else {}
            add_token(tokens, feishu.get("spreadsheet_token"))
            add_token(tokens, feishu.get("url"))

    main_info = spreadsheet_info(crawl.SPREADSHEET_TOKEN)
    history_sheet = next(
        (item for item in sheet_items(main_info) if str(item.get("title") or "") == daily.LOG_INDEX_SHEET_TITLE),
        None,
    )
    if history_sheet:
        rows = daily.read_range(
            f"{history_sheet['sheet_id']}!A1:F500",
            spreadsheet_token=crawl.SPREADSHEET_TOKEN,
        )
        for row in rows:
            for value in row:
                match = TOKEN_PATTERN.search(str(value or ""))
                if match:
                    add_token(tokens, match.group(1))
    return sorted(tokens)


def crawl_section(rows: list[list[Any]]) -> list[list[Any]]:
    output: list[list[Any]] = []
    for index, row in enumerate(rows):
        values = [str(value or "").strip() for value in row]
        first = values[0] if values else ""
        if first == "AGENT处理流程与结果":
            break
        if index > 0 and not any(values):
            break
        output.append(row)
    return output


def format_token(token: str) -> list[dict[str, Any]]:
    info = spreadsheet_info(token)
    candidates = [item for item in sheet_items(info) if str(item.get("title") or "").startswith("爬虫日志")]
    if not candidates:
        return []
    results: list[dict[str, Any]] = []
    for sheet in candidates:
        sheet_id = str(sheet.get("sheet_id") or "")
        rows = daily.read_range(f"{sheet_id}!A1:AD1000", spreadsheet_token=token)
        source_rows = crawl_section(rows)
        if not source_rows:
            continue
        header = {str(value or "").strip() for value in source_rows[0]}
        if not ({"run_time", "抓取时间（香港）"} & header):
            continue
        result = write_and_format_crawl_log_sheet(
            root=ROOT,
            sheet_id=sheet_id,
            spreadsheet_token=token,
            source_rows=source_rows,
            write_range=daily.write_range,
            read_range=daily.read_range,
            set_style=daily.set_style,
            run_cmd=daily.run_cmd,
            lark_cli=daily.LARK_CLI,
        )
        result["sheet_title"] = str(sheet.get("title") or "")
        results.append(result)
    return results


def main() -> int:
    tokens = discover_log_tokens()
    if not tokens:
        raise RuntimeError("没有从爬虫历史记录链接或本地运行索引发现独立日志表")
    formatted: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, token in enumerate(tokens, start=1):
        print(f"[{index}/{len(tokens)}] 整理日志表 {token}", flush=True)
        try:
            formatted.extend(format_token(token))
        except Exception as exc:
            failures.append({"spreadsheet_token": token, "error": f"{type(exc).__name__}: {exc}"})
    result = {
        "ok": not failures,
        "discovered_spreadsheets": len(tokens),
        "formatted_sheets": len(formatted),
        "formatted": formatted,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if not failures and formatted else 1


if __name__ == "__main__":
    sys.exit(main())
