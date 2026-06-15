from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
SOURCE_PATH = ROOT / "carrier_performance_sources.json"
MIRROR_PATH = ROOT / "carrier_performance_feishu.json"
MARKET_CACHE_PATH = ROOT / "carrier_market_cache.json"
VERIFIED_FIELDS_PATH = ROOT / "carrier_performance_verified_fields.json"
SPREADSHEET_TOKEN = "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
SHEET_TITLE = "运营商业绩摘要补充"
LARK_CLI = shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"
HEADERS = [
    "范围",
    "主体",
    "最新披露",
    "披露日期",
    "股票代码",
    "派息",
    "资本开支",
    "战略升级",
    "券商观点",
    "市场反应",
    "来源链接",
    "主体说明",
    "更新时间",
]
FIELD_COLUMNS = {
    "dividend": "派息",
    "capex": "资本开支",
    "strategy": "战略升级",
    "broker": "券商观点",
    "market": "市场反应",
}
FORBIDDEN_PLACEHOLDERS = ("待补充", "将按", "抓取失败", "飞书镜像验证")
FORBIDDEN_RAW_FRAGMENTS = (
    "Skip to main content",
    "Log In Sign Up",
    "Full Chart Watchlist",
    "Income Statement",
    "Annual Results Presentation",
    "Investor Relations Department",
    "Corporate Governance Report",
    "SOURCE:",
    "| --- |",
)


def col_to_a1(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def cli_env() -> dict[str, str]:
    return os.environ.copy()


def run_cli(args: list[str]) -> dict:
    proc = subprocess.run(
        [LARK_CLI, *args],
        cwd=str(ROOT),
        env=cli_env(),
        text=True,
        capture_output=True,
        timeout=90,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return json.loads(proc.stdout)


def source_rows() -> list[dict]:
    config = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    verified_fields = (
        json.loads(VERIFIED_FIELDS_PATH.read_text(encoding="utf-8"))
        if VERIFIED_FIELDS_PATH.exists()
        else {}
    )
    market_cache = (
        json.loads(MARKET_CACHE_PATH.read_text(encoding="utf-8"))
        if MARKET_CACHE_PATH.exists()
        else {}
    )
    now = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
    rows = []
    for group, companies in (config.get("groups") or {}).items():
        for company in companies:
            company_cfg = config["companies"][company]
            latest = company_cfg.get("latest_event") or {}
            fields = dict(company_cfg.get("fields") or {})
            fields.update(verified_fields.get(company) or {})
            market_key = f"{company_cfg.get('ticker', '')}|{company_cfg.get('market_event_date', '')}"
            market_text = (market_cache.get(market_key) or {}).get("text") or fields.get("market", "")
            rows.append(
                {
                    "范围": group,
                    "主体": company,
                    "最新披露": latest.get("label", ""),
                    "披露日期": latest.get("date", ""),
                    "股票代码": company_cfg.get("ticker", ""),
                    "派息": fields.get("dividend", ""),
                    "资本开支": fields.get("capex", ""),
                    "战略升级": fields.get("strategy", ""),
                    "券商观点": fields.get("broker", ""),
                    "市场反应": market_text,
                    "来源链接": "\n".join(
                        str(item.get("url") or "").strip()
                        for item in company_cfg.get("sources", [])
                        if str(item.get("url") or "").strip()
                    ),
                    "主体说明": latest.get("note", ""),
                    "更新时间": now,
                }
            )
    return rows


def values_from_rows(rows: list[dict]) -> list[list[str]]:
    return [HEADERS] + [[str(row.get(header, "")) for header in HEADERS] for row in rows]


def find_sheet_id(info: dict) -> str:
    data = info.get("data") or {}
    sheets = data.get("sheets") or []
    if isinstance(sheets, dict):
        sheets = sheets.get("sheets") or []
    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        if sheet.get("title") == SHEET_TITLE:
            return str(sheet.get("sheet_id") or sheet.get("sheetId") or "")
    return ""


def ensure_sheet() -> str:
    info = run_cli(["sheets", "+info", "--spreadsheet-token", SPREADSHEET_TOKEN])
    sheet_id = find_sheet_id(info)
    if sheet_id:
        return sheet_id
    created = run_cli(
        ["sheets", "+create-sheet", "--spreadsheet-token", SPREADSHEET_TOKEN, "--title", SHEET_TITLE]
    )
    data = created.get("data") or {}
    sheet_id = str(data.get("sheet_id") or data.get("sheetId") or "")
    if not sheet_id:
        raise RuntimeError(f"未能获取新建工作表 ID：{created}")
    return sheet_id


def write_rows(sheet_id: str, rows: list[dict]) -> None:
    values = values_from_rows(rows)
    target_range = f"{sheet_id}!A1:{col_to_a1(len(HEADERS))}{len(values)}"
    run_cli(
        [
            "sheets",
            "+write",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--sheet-id",
            sheet_id,
            "--range",
            target_range,
            "--values",
            json.dumps(values, ensure_ascii=False),
        ]
    )


def read_rows(sheet_id: str) -> list[dict]:
    result = run_cli(
        [
            "sheets",
            "+read",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--sheet-id",
            sheet_id,
            "--range",
            f"{sheet_id}!A1:{col_to_a1(len(HEADERS))}200",
            "--value-render-option",
            "ToString",
        ]
    )
    data = result.get("data") or {}
    value_range = data.get("value_range") or data.get("valueRange") or {}
    values = value_range.get("values") or []
    if not values:
        return []
    headers = [str(item) for item in values[0]]
    rows = []
    for value_row in values[1:]:
        padded = list(value_row) + [""] * max(0, len(headers) - len(value_row))
        row = {header: "" if value is None else str(value) for header, value in zip(headers, padded)}
        if row.get("主体"):
            rows.append(row)
    return rows


def save_mirror(sheet_id: str, rows: list[dict]) -> None:
    payload = {
        "spreadsheet_token": SPREADSHEET_TOKEN,
        "sheet_id": sheet_id,
        "sheet_title": SHEET_TITLE,
        "sheet_url": f"https://cmhk-try.feishu.cn/sheets/{SPREADSHEET_TOKEN}?sheet={sheet_id}",
        "synced_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds"),
        "rows": rows,
    }
    MIRROR_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_rows(rows: list[dict], expected_companies: list[str]) -> None:
    actual_companies = [row.get("主体", "").strip() for row in rows]
    if actual_companies != expected_companies:
        raise RuntimeError(
            "飞书回读主体不完整或顺序异常："
            f"预期 {expected_companies}，实际 {actual_companies}"
        )
    for row in rows:
        company = row.get("主体", "").strip()
        missing = [label for label in FIELD_COLUMNS.values() if not row.get(label, "").strip()]
        if missing:
            raise RuntimeError(f"飞书回读缺少字段：{company} -> {', '.join(missing)}")
        combined = " ".join(row.get(label, "") for label in FIELD_COLUMNS.values())
        placeholders = [token for token in FORBIDDEN_PLACEHOLDERS if token in combined]
        if placeholders:
            raise RuntimeError(f"飞书回读仍含占位内容：{company} -> {', '.join(placeholders)}")
        fragments = [token for token in FORBIDDEN_RAW_FRAGMENTS if token.lower() in combined.lower()]
        if fragments:
            raise RuntimeError(f"飞书回读含原始网页片段：{company} -> {', '.join(fragments)}")
    hgc = next((row for row in rows if row.get("主体") == "HGC"), None)
    if not hgc:
        raise RuntimeError("飞书回读缺少 HGC")
    for label in ("派息", "券商观点", "市场反应"):
        if "不适用" not in hgc.get(label, ""):
            raise RuntimeError(f"HGC {label} 必须明确标记为不适用")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull-only", action="store_true")
    args = parser.parse_args()
    sheet_id = ensure_sheet()
    if not args.pull_only:
        source = source_rows()
        write_rows(sheet_id, source)
    else:
        source = source_rows()
    rows = read_rows(sheet_id)
    validate_rows(rows, [row["主体"] for row in source])
    save_mirror(sheet_id, rows)
    print(json.dumps({"ok": True, "sheet_id": sheet_id, "rows": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
