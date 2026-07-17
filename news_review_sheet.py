from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "strategy_briefing"
LATEST_PATH = DATA_DIR / "news_discovery_latest.json"
FULL_DISCOVERY_PATH = DATA_DIR / "news_discovery_full.json"
PUBLISHED_PATH = DATA_DIR / "published.json"
STATE_PATH = DATA_DIR / "news_review_sheet_state.json"

HKT = ZoneInfo("Asia/Hong_Kong")
LARK_CLI = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"
SPREADSHEET_TOKEN = (
    os.environ.get("CMHK_NEWS_REVIEW_SPREADSHEET_TOKEN")
    or "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
).strip()
SHEET_TITLE = os.environ.get("CMHK_NEWS_REVIEW_SHEET_TITLE") or "滚动新闻候选池"
POLL_SECONDS = max(60, int(os.environ.get("CMHK_NEWS_REVIEW_POLL_SECONDS", "300")))
MAX_SHEET_ROWS = max(500, int(os.environ.get("CMHK_NEWS_REVIEW_MAX_ROWS", "3000")))
SHEET_SOURCE = "feishu_review_sheet"
FORMAT_VERSION = 7

HEADERS = [
    "是否纳入滚动",
    "同步状态",
    "检索日期",
    "地域",
    "分类",
    "新闻标题（AI）",
    "内容简介（AI）",
    "来源媒体",
    "发布时间",
    "原文链接",
    "命中关键词",
    "入池理由",
]

_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _group_notifications_paused() -> bool:
    return os.environ.get("CMHK_STRATEGIC_GROUP_NOTIFICATIONS", "0") != "1"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _text(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def _lark(*parts: str, timeout: int = 120) -> dict[str, Any]:
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
    environment["LARK_CLI_NO_PROXY"] = "1"
    process = subprocess.run(
        [LARK_CLI, *parts, "--as", "user"],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = process.stdout.strip()
    try:
        payload = json.loads(output) if output else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            process.stderr.strip() or output or "飞书命令未返回 JSON"
        ) from exc
    if process.returncode != 0 or payload.get("ok") is False:
        raise RuntimeError(
            str(payload.get("message") or payload.get("msg") or process.stderr.strip() or output)
        )
    return payload


def _walk_for_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _walk_for_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _walk_for_key(child, key)
            if found is not None:
                return found
    return None


def _sheet_url(sheet_id: str) -> str:
    return (
        f"https://cmhk-try.feishu.cn/sheets/{SPREADSHEET_TOKEN}"
        f"?sheet={sheet_id}"
    )


def _spreadsheet_info() -> dict[str, Any]:
    return _lark(
        "sheets",
        "+info",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
    )


def _find_sheet_id(payload: dict[str, Any]) -> str:
    sheets = _walk_for_key(payload, "sheets")
    if isinstance(sheets, dict):
        sheets = sheets.get("sheets")
    for sheet in sheets if isinstance(sheets, list) else []:
        if isinstance(sheet, dict) and str(sheet.get("title") or "") == SHEET_TITLE:
            return str(sheet.get("sheet_id") or "")
    return ""


def _sheet_row_count(payload: dict[str, Any], sheet_id: str) -> int:
    sheets = _walk_for_key(payload, "sheets")
    if isinstance(sheets, dict):
        sheets = sheets.get("sheets")
    for sheet in sheets if isinstance(sheets, list) else []:
        if not isinstance(sheet, dict) or str(sheet.get("sheet_id") or "") != sheet_id:
            continue
        properties = sheet.get("grid_properties") or {}
        return int(properties.get("row_count") or 0)
    return 0


def _best_effort(*parts: str) -> None:
    try:
        _lark(*parts)
    except Exception as exc:
        logging.warning("滚动新闻审核表格式设置失败：%s", exc)


def _format_sheet(sheet_id: str) -> None:
    header_style = {
        "font": {"bold": True, "foreColor": "#FFFFFF"},
        "backColor": "#174A78",
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
        "wrapStrategy": "WRAP",
    }
    body_style = {
        "verticalAlignment": "TOP",
        "wrapStrategy": "WRAP",
    }
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!A1:L1",
        "--style",
        json.dumps(header_style, ensure_ascii=False),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!A2:L{MAX_SHEET_ROWS}",
        "--style",
        json.dumps(body_style, ensure_ascii=False),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!A2:B{MAX_SHEET_ROWS}",
        "--style",
        json.dumps(
            {
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
            ensure_ascii=False,
        ),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!C2:C{MAX_SHEET_ROWS}",
        "--style",
        json.dumps(
            {
                "font": {"bold": True, "foreColor": "#174A78"},
                "backColor": "#EAF3FA",
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
            ensure_ascii=False,
        ),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!D2:E{MAX_SHEET_ROWS}",
        "--style",
        json.dumps(
            {
                "backColor": "#F3F7FB",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            },
            ensure_ascii=False,
        ),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!F2:F{MAX_SHEET_ROWS}",
        "--style",
        json.dumps(
            {
                "font": {"bold": True, "foreColor": "#163A5F"},
                "verticalAlignment": "TOP",
                "wrapStrategy": "WRAP",
            },
            ensure_ascii=False,
        ),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!G2:G{MAX_SHEET_ROWS}",
        "--style",
        json.dumps(
            {
                "font": {"foreColor": "#274C67"},
                "verticalAlignment": "TOP",
                "wrapStrategy": "WRAP",
            },
            ensure_ascii=False,
        ),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!H2:L{MAX_SHEET_ROWS}",
        "--style",
        json.dumps(
            {
                "font": {"foreColor": "#52687C"},
                "verticalAlignment": "TOP",
                "wrapStrategy": "WRAP",
            },
            ensure_ascii=False,
        ),
    )
    _best_effort(
        "sheets",
        "+set-dropdown",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!A2:A{MAX_SHEET_ROWS}",
        "--condition-values",
        json.dumps(["待审核", "接受", "暂缓", "不接受"], ensure_ascii=False),
        "--colors",
        json.dumps(["#8F959E", "#16A34A", "#D97706", "#DC2626"]),
        "--highlight",
    )
    _best_effort(
        "sheets",
        "+set-dropdown",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!B2:B{MAX_SHEET_ROWS}",
        "--condition-values",
        json.dumps(["未同步", "已纳入", "已移除", "同步失败"], ensure_ascii=False),
        "--colors",
        json.dumps(["#8F959E", "#2563EB", "#D97706", "#DC2626"]),
        "--highlight",
    )
    widths = [
        112,
        108,
        112,
        90,
        150,
        380,
        440,
        140,
        145,
        420,
        260,
        220,
    ]
    for index, width in enumerate(widths, start=1):
        _best_effort(
            "sheets",
            "+update-dimension",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--sheet-id",
            sheet_id,
            "--dimension",
            "COLUMNS",
            "--start-index",
            str(index),
            "--end-index",
            str(index),
            "--fixed-size",
            str(width),
            "--visible",
        )
    _best_effort(
        "sheets",
        "+update-dimension",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--dimension",
        "ROWS",
        "--start-index",
        "1",
        "--end-index",
        "1",
        "--fixed-size",
        "42",
        "--visible",
    )
    _best_effort(
        "sheets",
        "+update-dimension",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--dimension",
        "ROWS",
        "--start-index",
        "2",
        "--end-index",
        str(MAX_SHEET_ROWS),
        "--fixed-size",
        "76",
        "--visible",
    )
    _best_effort(
        "sheets",
        "+update-sheet",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--frozen-row-count",
        "1",
        "--frozen-col-count",
        "7",
    )
    _best_effort(
        "sheets",
        "+create-filter-view",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--range",
        f"{sheet_id}!A1:L{MAX_SHEET_ROWS}",
        "--filter-view-name",
        "滚动新闻审核视图",
    )


def _write(sheet_id: str, cell_range: str, values: list[list[Any]]) -> None:
    _lark(
        "sheets",
        "+write",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--range",
        cell_range,
        "--values",
        json.dumps(values, ensure_ascii=False),
    )


def _normalized_sheet_row(row: list[Any], format_version: int = FORMAT_VERSION) -> list[Any]:
    width = 10 if format_version <= 5 else 11 if format_version == 6 else len(HEADERS)
    padded = (list(row) + [""] * width)[:width]
    if format_version <= 5:
        return padded
    expected_url_index = 8 if format_version == 6 else 9
    shifted_url_index = expected_url_index + 1
    url_at_expected_column = _text(padded[expected_url_index], 1600).lower().startswith(("http://", "https://"))
    url_shifted_one_column = (
        shifted_url_index < len(padded)
        and _text(padded[shifted_url_index], 1600).lower().startswith(("http://", "https://"))
    )
    if format_version == 6 and not url_at_expected_column and url_shifted_one_column:
        return [
            *padded[:6],
            padded[7],
            padded[8],
            padded[9],
            padded[10],
            "历史候选",
        ]
    if format_version >= 7 and not url_at_expected_column and url_shifted_one_column:
        return [
            *padded[:7],
            padded[8],
            padded[9],
            padded[10],
            padded[11],
            "历史候选",
        ]
    return padded


def _read_rows(
    sheet_id: str,
    *,
    format_version: int = FORMAT_VERSION,
) -> list[list[Any]]:
    end_column = "J" if format_version <= 5 else "K" if format_version == 6 else "L"
    payload = _lark(
        "sheets",
        "+read",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--range",
        f"A2:{end_column}{MAX_SHEET_ROWS}",
        "--value-render-option",
        "ToString",
    )
    values = _walk_for_key(payload, "values")
    rows = [
        _normalized_sheet_row(
            row if isinstance(row, list) else [],
            format_version,
        )
        for row in values or []
    ]
    while rows and not any(cell not in (None, "") for cell in rows[-1]):
        rows.pop()
    return rows


def ensure_sheet() -> str:
    with _LOCK:
        state = _read_json(STATE_PATH, {})
        info = _spreadsheet_info()
        sheet_id = _find_sheet_id(info)
        created = False
        if not sheet_id:
            _lark(
                "sheets",
                "+create-sheet",
                "--spreadsheet-token",
                SPREADSHEET_TOKEN,
                "--title",
                SHEET_TITLE,
                "--index",
                "3",
            )
            sheet_id = _find_sheet_id(_spreadsheet_info())
            created = True
        if not sheet_id:
            raise RuntimeError("飞书子表创建后未能取得 sheet_id")
        info = _spreadsheet_info()
        row_count = _sheet_row_count(info, sheet_id)
        expanded = row_count < MAX_SHEET_ROWS
        if expanded:
            _lark(
                "sheets",
                "+add-dimension",
                "--spreadsheet-token",
                SPREADSHEET_TOKEN,
                "--sheet-id",
                sheet_id,
                "--dimension",
                "ROWS",
                "--length",
                str(MAX_SHEET_ROWS - row_count),
            )
        previous_version = int(state.get("format_version") or 0)
        if not created and previous_version in {5, 6}:
            legacy_rows = _read_rows(sheet_id, format_version=previous_version)
            if previous_version == 5:
                version_six_rows = []
                for row in legacy_rows:
                    legacy = (list(row[:10]) + [""] * 10)[:10]
                    version_six_rows.append(legacy[:5] + [""] + legacy[5:])
            else:
                version_six_rows = legacy_rows
            legacy_search_date = _search_date(state.get("last_source_generated_at"))
            migrated_rows = [
                list(row[:2]) + [legacy_search_date] + list(row[2:11])
                for row in version_six_rows
            ]
            for offset in range(0, len(migrated_rows), 40):
                chunk = migrated_rows[offset : offset + 40]
                start_row = 2 + offset
                end_row = start_row + len(chunk) - 1
                _write(sheet_id, f"A{start_row}:L{end_row}", chunk)
        _write(sheet_id, "A1:L1", [HEADERS])
        _write(sheet_id, "M1:P1", [[""] * 4])
        if (
            created
            or expanded
            or not state.get("formatted_at")
            or state.get("sheet_id") != sheet_id
            or int(state.get("format_version") or 0) != FORMAT_VERSION
        ):
            _format_sheet(sheet_id)
            state["formatted_at"] = _now_iso()
            state["format_version"] = FORMAT_VERSION
        state.update(
            {
                "sheet_id": sheet_id,
                "sheet_title": SHEET_TITLE,
                "sheet_url": _sheet_url(sheet_id),
                "updated_at": _now_iso(),
            }
        )
        _write_json(STATE_PATH, state)
        return sheet_id


def _keywords(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(_text(item, 80) for item in value if _text(item, 80))
    return _text(value, 500)


def _publication_date(value: Any) -> str:
    text = _text(value, 60)
    if not text:
        return ""
    normalized = text.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=HKT)
        return parsed.astimezone(HKT).strftime("%Y-%m-%d")
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=HKT)
        return parsed.astimezone(HKT).strftime("%Y-%m-%d")
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if not match:
        return ""
    try:
        return datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=HKT
        ).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _display_time(value: Any) -> str:
    return _publication_date(value)


def _search_date(value: Any) -> str:
    text = _text(value, 60)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text).astimezone(HKT).strftime("%Y-%m-%d")
    except ValueError:
        match = re.search(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}", text)
        return match.group(0).replace("/", "-") if match else text[:10]


def _category_label(item: dict[str, Any]) -> str:
    text = " ".join(
        (
            _text(item.get("title"), 500),
            _text(item.get("snippet"), 1200),
        )
    ).lower()
    rules = (
        (("网络安全", "cyber", "诈骗", "fraud", "data breach"), "网络安全"),
        (("5g", "6g", "ran", "频谱", "基站", "telecom", "电信"), "电信与网络"),
        (("人工智能", " ai ", "artificial intelligence", "大模型", "算力"), "AI与科技"),
        (("数据中心", "data center", "data centre", "cloud", "云计算"), "云与数据中心"),
        (("半导体", "semiconductor", "chip", "出口管制", "entity list"), "芯片与监管"),
        (("监管", "政策", "政府", "制裁", "sanction", "地缘"), "宏观与政策"),
        (("合作", "并购", "投资", "战略"), "战略与合作"),
    )
    padded = f" {text} "
    for terms, label in rules:
        if any(term in padded for term in terms):
            return label
    return "行业动态"


def _news_item_id(url: Any, title: Any) -> str:
    canonical_url = _canonical_news_url(url)
    seed_text = canonical_url or _text(url, 1800) or _normalized_news_title(title)
    seed = seed_text.encode("utf-8")
    return "NEWS-" + hashlib.sha1(seed).hexdigest()[:14].upper()


def _candidate_row(item: dict[str, Any], generated_at: str) -> list[Any]:
    return [
        "待审核",
        "未同步",
        _search_date(
            item.get("search_date")
            or item.get("searched_at")
            or item.get("retrieved_at")
            or generated_at
        ),
        _text(item.get("region") or "国际/行业", 40),
        _text(item.get("category") or _category_label(item), 80),
        _text(item.get("ai_title"), 500),
        _text(item.get("ai_summary"), 500),
        _text(item.get("source") or item.get("source_domain"), 160),
        _display_time(item.get("source_date") or item.get("published_at")),
        _text(item.get("url"), 1600),
        _keywords(item.get("keywords")),
        _text(item.get("filter_reason") or "战略新闻候选", 300),
    ]

def sync_candidates(
    items: list[dict[str, Any]],
    *,
    generated_at: str = "",
    slot_label: str = "",
) -> dict[str, Any]:
    with _LOCK:
        sheet_id = ensure_sheet()
        rows = _read_rows(sheet_id)
        existing_status: dict[str, tuple[str, str]] = {}
        existing_search_dates: dict[str, str] = {}
        archived_items: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows, start=2):
            if not row or not _text(row[0], 40):
                continue
            parsed = _row_dict(row, index)
            still_relevant, _ = _review_news_candidate(
                {
                    "title": parsed["title"],
                    "snippet": f"{parsed['summary']} {parsed['keywords']} {parsed['note']}",
                    "source": parsed["source"],
                    "url": parsed["source_url"],
                    "keywords": parsed["keywords"],
                    "source_date": parsed["source_date"],
                    "search_date": parsed["search_date"],
                }
            )
            if not still_relevant:
                continue
            existing_status[parsed["news_id"]] = (
                parsed["status"],
                parsed["sync_status"] or "未同步",
            )
            existing_search_dates[parsed["news_id"]] = parsed["search_date"]
            archived_items[parsed["news_id"]] = {
                "news_id": parsed["news_id"],
                "search_date": parsed["search_date"],
                "title": parsed["title"],
                "source_title": parsed["title"],
                "snippet": parsed["summary"] or parsed["note"],
                "ai_title": parsed["title"],
                "ai_summary": parsed["summary"],
                "region": parsed["region"],
                "category": parsed["category"],
                "source": parsed["source"],
                "source_date": parsed["source_date"],
                "url": parsed["source_url"],
                "keywords": parsed["keywords"],
                "filter_reason": parsed["note"],
            }
        current_ids = {_text(item.get("news_id"), 80) for item in items}
        combined_items = list(items) + [
            item for news_id, item in archived_items.items() if news_id not in current_ids
        ]
        curated_items, gate_reasons = curate_news_items(combined_items)
        from strategic_briefing import polish_candidates_before_review

        prepared_items = polish_candidates_before_review(curated_items)
        archived_count = sum(
            _text(item.get("news_id"), 80) not in current_ids for item in prepared_items
        )
        values: list[list[Any]] = []
        new_count = 0
        new_category_counts: Counter[str] = Counter()
        new_region_counts: Counter[str] = Counter()
        new_sources: set[str] = set()
        for item in prepared_items:
            news_id = _text(item.get("news_id"), 80)
            value = _candidate_row(item, generated_at)
            if news_id in existing_status:
                value[0], value[1] = existing_status[news_id]
                value[2] = existing_search_dates.get(news_id) or value[2]
            else:
                new_count += 1
                new_category_counts[_text(item.get("category") or "未分类", 80)] += 1
                new_region_counts[_text(item.get("region") or "未分类", 80)] += 1
                source = _text(item.get("source") or item.get("source_domain"), 160)
                if source:
                    new_sources.add(source)
            values.append(value)
        values.sort(key=lambda row: str(row[2] or ""), reverse=True)
        if len(values) > MAX_SHEET_ROWS - 1:
            raise RuntimeError(f"审核表超过 {MAX_SHEET_ROWS - 1} 条候选上限")
        clear_count = max(len(rows), len(values))
        for offset in range(0, clear_count, 40):
            count = min(40, clear_count - offset)
            start_row = 2 + offset
            end_row = start_row + count - 1
            _write(sheet_id, f"A{start_row}:P{end_row}", [[""] * 16 for _ in range(count)])
        for offset in range(0, len(values), 40):
            chunk = values[offset : offset + 40]
            start_row = 2 + offset
            end_row = start_row + len(chunk) - 1
            _write(sheet_id, f"A{start_row}:L{end_row}", chunk)
        state = _read_json(STATE_PATH, {})
        state.update(
            {
                "sheet_id": sheet_id,
                "sheet_url": _sheet_url(sheet_id),
                "last_source_generated_at": generated_at,
                "last_slot_label": slot_label,
                "last_candidate_count": len(values),
                "last_batch_count": len(items),
                "last_archived_count": archived_count,
                "last_gate_filtered_count": len(combined_items) - len(curated_items),
                "last_gate_filtered_reasons": dict(gate_reasons),
                "last_new_count": new_count,
                "last_new_category_counts": dict(new_category_counts),
                "last_new_region_counts": dict(new_region_counts),
                "last_new_source_count": len(new_sources),
                "last_ai_processed_count": len(prepared_items),
                "last_sync_at": _now_iso(),
                "group_notifications_paused": _group_notifications_paused(),
            }
        )
        _write_json(STATE_PATH, state)
        return {
            "sheet_id": sheet_id,
            "sheet_url": _sheet_url(sheet_id),
            "candidate_count": len(values),
            "batch_count": len(items),
            "archived_count": archived_count,
            "gate_filtered_count": len(combined_items) - len(curated_items),
            "gate_filtered_reasons": dict(gate_reasons),
            "new_count": new_count,
            "new_category_counts": dict(new_category_counts),
            "new_region_counts": dict(new_region_counts),
            "new_source_count": len(new_sources),
            "existing_count": len(existing_status),
        }

def _normalized_status(value: Any) -> str:
    text = _text(value, 30).replace(" ", "")
    aliases = {
        "采纳": "接受",
        "已接受": "接受",
        "纳入": "接受",
        "纳入滚动": "接受",
        "拒绝": "不接受",
        "不采纳": "不接受",
        "稍后": "暂缓",
    }
    return aliases.get(text, text or "待审核")


def _row_dict(row: list[Any], row_number: int) -> dict[str, Any]:
    padded = list(row) + [""] * max(0, len(HEADERS) - len(row))
    news_id = _news_item_id(padded[9], padded[5])
    return {
        "row_number": row_number,
        "status": _normalized_status(padded[0]),
        "sync_status": _text(padded[1], 40),
        "search_date": _text(padded[2], 20),
        "region": _text(padded[3], 80),
        "category": _text(padded[4], 120),
        "title": _text(padded[5], 500),
        "summary": _text(padded[6], 500),
        "source": _text(padded[7], 240),
        "source_date": _text(padded[8], 40),
        "source_url": _text(padded[9], 1600),
        "keywords": _text(padded[10], 1800),
        "note": _text(padded[11], 500),
        "news_id": news_id,
    }

def apply_reviews(sheet_id: str | None = None) -> dict[str, Any]:
    with _LOCK:
        sheet_id = sheet_id or ensure_sheet()
        rows = [
            _row_dict(row, index)
            for index, row in enumerate(_read_rows(sheet_id), start=2)
            if row and _text(row[0], 80)
        ]
        payload = _read_json(PUBLISHED_PATH, {"items": []})
        published = payload.get("items") if isinstance(payload, dict) else []
        published = [item for item in published or [] if isinstance(item, dict)]
        existing_sheet = {
            _text(item.get("id"), 80): item
            for item in published
            if item.get("approval_source") == SHEET_SOURCE
        }
        retained = [
            item for item in published if item.get("approval_source") != SHEET_SOURCE
        ]
        retained_ids = {_text(item.get("id"), 80) for item in retained}
        accepted_rows = [row for row in rows if row["status"] == "接受"]
        now_text = _now_iso()
        accepted_items: list[dict[str, Any]] = []
        blocked_rows: dict[int, str] = {}
        seen_urls = {
            _canonical_news_url(item.get("source_url"))
            for item in retained
            if _canonical_news_url(item.get("source_url"))
        }
        seen_titles = [
            _normalized_news_title(item.get("title"))
            for item in retained
            if _normalized_news_title(item.get("title"))
        ]
        for row in accepted_rows:
            if row["news_id"] in retained_ids:
                blocked_rows[row["row_number"]] = "重复新闻"
                continue
            gate_item = {
                "title": row["title"],
                "snippet": f"{row['summary']} {row['keywords']} {row['note']}",
                "source": row["source"],
                "url": row["source_url"],
                "keywords": row["keywords"],
                "source_date": row["source_date"],
                "search_date": row["search_date"],
            }
            allowed, reason = _review_news_candidate(gate_item)
            if not allowed:
                blocked_rows[row["row_number"]] = reason
                continue
            url_key = _canonical_news_url(row["source_url"])
            title_key = _normalized_news_title(row["title"])
            if (
                not url_key
                or not title_key
                or url_key in seen_urls
                or any(_event_titles_duplicate(title_key, existing) for existing in seen_titles)
            ):
                blocked_rows[row["row_number"]] = "重复新闻"
                continue
            previous = existing_sheet.get(row["news_id"], {})
            accepted_items.append(
                {
                    "id": row["news_id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "category": row["category"] or "战略动态",
                    "source_url": row["source_url"],
                    "source": row["source"],
                    "source_date": row["source_date"],
                    "region": row["region"],
                    "keywords": row["keywords"],
                    "published_at": row["source_date"],
                    "approved_at": previous.get("approved_at") or now_text,
                    "approved_by": "飞书表格人工审核",
                    "approval_source": SHEET_SOURCE,
                }
            )
            seen_urls.add(url_key)
            seen_titles.append(title_key)
        combined = retained + accepted_items
        combined.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
        new_payload = {"updated_at": now_text, "items": combined[:100]}
        old_comparable = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        new_comparable = json.dumps(new_payload, ensure_ascii=False, sort_keys=True)
        if old_comparable != new_comparable:
            _write_json(PUBLISHED_PATH, new_payload)

        changed_rows = 0
        for row in rows:
            blocked_reason = blocked_rows.get(row["row_number"])
            if blocked_reason:
                if row["status"] != "不接受" or row["sync_status"] != "已移除":
                    _write(
                        sheet_id,
                        f"A{row['row_number']}:B{row['row_number']}",
                        [["不接受", "已移除"]],
                    )
                    changed_rows += 1
                gate_note = f"门控拒绝：{blocked_reason}"
                if row["note"] != gate_note:
                    _write(
                        sheet_id,
                        f"L{row['row_number']}:L{row['row_number']}",
                        [[gate_note]],
                    )
                    changed_rows += 1
                continue
            desired_sync = "未同步"
            if row["status"] == "接受":
                desired_sync = "已纳入"
            elif row["status"] == "不接受":
                desired_sync = "已移除"
            elif row["news_id"] in existing_sheet:
                desired_sync = "已移除"
            if desired_sync != row["sync_status"]:
                _write(
                    sheet_id,
                    f"B{row['row_number']}:B{row['row_number']}",
                    [[desired_sync]],
                )
                changed_rows += 1
        return {
            "accepted_count": len(accepted_items),
            "requested_accept_count": len(accepted_rows),
            "blocked_accept_count": len(blocked_rows),
            "pending_count": sum(row["status"] == "待审核" for row in rows),
            "deferred_count": sum(row["status"] == "暂缓" for row in rows),
            "rejected_count": sum(row["status"] == "不接受" for row in rows),
            "published_count": len(combined),
            "changed_rows": changed_rows,
        }

def _crawl_item_id(*parts: Any) -> str:
    import hashlib

    raw = "\n".join(str(part or "") for part in parts)
    return "CRAWL-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _review_candidate_reason(
    record: dict[str, Any], source: dict[str, Any]
) -> tuple[bool, str]:
    from urllib.parse import urlparse

    url = _text(record.get("final_url") or record.get("url"), 1600)
    lower_url = url.lower()
    title = _text(record.get("title"), 500)
    lower_title = title.lower()
    path = urlparse(url).path.lower()
    source_type = _text(record.get("source_type"), 120)
    local_competitor = _text(source.get("block"), 120) == "香港本地竞对"

    if source_type in {
        "commercial_data", "public_api", "government_statistics",
        "government_api_docs", "government_open_data",
    }:
        return False, "数据、行情或统计接口"
    if any(domain in lower_url for domain in (
        "stockanalysis.com", "aastocks.com", "financialfilings.com"
    )):
        return False, "股票或财报聚合页"
    if any(marker in path for marker in (
        "/plans/", "/mobile_and_price_plans/", "/handsets/offer/"
    )):
        return False, "套餐或产品广告页"
    if lower_title == "pdf extracted by pdftotext":
        return False, "缺少可读标题的PDF"
    if any(marker in lower_url for marker in (
        "2024", "2025", "?prid=%2fpress%2fp25", "20250626"
    )):
        return False, "明显过期内容"
    if "consumer price indices" in lower_title:
        return False, "非竞对宏观数据"
    if path.endswith("/gia/general/today.htm"):
        return False, "新闻栏目首页"
    if "ezone.hk/article/20073735" in lower_url:
        return False, "与竞对官网同一事件重复"
    if not local_competitor and any(marker in lower_title for marker in (
        "net profit", "financial results", "reports aed"
    )):
        return False, "非香港竞对财务行情"
    if not local_competitor and "/quarterly-earnings/" in lower_url:
        return False, "非香港竞对财务行情"

    individual_markers = (
        "/news-updates/", "/en-newsroom/", "/insight/", "/article/",
        "press.php?prid=", "/news/detail/", "/media-centre/news-releases/",
        "/corp/news/press/", "/about/news/", "/gia/general/",
        "/wwwcms/upload/web/", "/info/media_center/pr/",
        "/newsroom/technology/", "newsroom.kddi.com/", "newsroom.bt.com/",
        "news.sktelecom.com/en/", "/communication-room/press-room/",
        "/news/press/sbkk/", "prnewswire.com/news-releases/", "/news/",
    )
    listing_suffixes = (
        "/press-releases", "/press-room", "/media-releases", "/news",
        "/press-release", "/press-archive",
    )
    if path.rstrip("/").endswith(listing_suffixes):
        return False, "新闻或公告栏目首页"
    if not any(marker in lower_url for marker in individual_markers):
        return False, "静态栏目或资料页"
    return True, "独立新闻或公告"


def _latest_crawl_results() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    roots = [
        Path(__file__).resolve().parent / "curation_data" / "backups",
        Path("/Users/liaowang/cmhk_public_crawl_app/curation_data/backups"),
    ]
    run_dirs: list[Path] = []
    for root in roots:
        if root.exists():
            run_dirs.extend(item for item in root.iterdir() if item.is_dir())
    run_dirs = sorted(
        {item.resolve() for item in run_dirs},
        key=lambda item: item.name,
        reverse=True,
    )
    for run_dir in run_dirs:
        run_log_path = run_dir / "run_log.json"
        sources_path = run_dir / "sources.json"
        if not run_log_path.exists() or not sources_path.exists():
            continue
        records = _read_json(run_log_path, [])
        sources = _read_json(sources_path, [])
        if not isinstance(records, list) or not records:
            continue
        source_map: dict[str, dict[str, Any]] = {}
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict):
                continue
            row_key = str(source.get("row") or "").strip()
            if row_key:
                source_map[row_key] = source
        try:
            batch_dt = datetime.strptime(
                "_".join(run_dir.name.split("_")[:2]), "%Y%m%d_%H%M%S"
            ).replace(tzinfo=HKT)
            batch_time = batch_dt.isoformat(timespec="seconds")
        except Exception:
            batch_time = _now_iso()
        items: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        raw_success_count = 0
        filtered_reasons: Counter[str] = Counter()
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                http_status = int(float(record.get("http_status") or 0))
            except (TypeError, ValueError):
                http_status = 0
            if not 200 <= http_status < 400 or _text(record.get("error"), 400):
                continue
            raw_success_count += 1
            row_key = str(record.get("row") or "").strip()
            source = source_map.get(row_key, {})
            url = _text(record.get("url"), 1600)
            final_url = _text(record.get("final_url") or url, 1600)
            canonical_url = final_url.rstrip("/") or final_url
            if canonical_url in seen_urls:
                filtered_reasons["跨配置行重复链接"] += 1
                continue
            seen_urls.add(canonical_url)
            keep, reason = _review_candidate_reason(record, source)
            if not keep:
                filtered_reasons[reason] += 1
                continue
            title = _text(record.get("title") or url, 500)
            item = {
                "config_row": row_key,
                "monitor_object": _text(source.get("object") or "未标注", 240),
                "monitor_category": _text(source.get("package") or "其他", 240),
                "title": title,
                "source_type": _text(record.get("source_type") or "unknown", 120),
                "jurisdiction": _text(record.get("jurisdiction") or "", 80),
                "crawl_time": batch_time,
                "http_status": http_status,
                "url": url,
                "final_url": final_url,
                "method": _text(record.get("method") or "", 120),
                "elapsed_seconds": record.get("elapsed_seconds") or 0,
                "bytes": record.get("bytes") or 0,
                "extracted_fields": _text(record.get("extracted_fields") or "", 1800),
            }
            item["news_id"] = _crawl_item_id(
                batch_time, row_key, url, final_url, title
            )
            items.append(item)
        return items, {
            "generated_at": batch_time,
            "slot_label": "凌晨3点定时爬虫",
            "run_id": run_dir.name,
            "input_count": len(records),
            "success_count": raw_success_count,
            "candidate_count": len(items),
            "filtered_count": raw_success_count - len(items),
            "failed_count": len(records) - raw_success_count,
            "filtered_reasons": dict(filtered_reasons),
            "group_notifications_paused": _group_notifications_paused(),
        }
    return [], {
        "generated_at": _now_iso(),
        "slot_label": "凌晨3点定时爬虫",
        "input_count": 0,
        "success_count": 0,
        "candidate_count": 0,
        "filtered_count": 0,
        "failed_count": 0,
        "filtered_reasons": {},
        "group_notifications_paused": _group_notifications_paused(),
    }

_LOCAL_COMPETITOR_RE = re.compile(
    r"(?:\bhkt\b|\bpccw\b|\bcsl\b|\b1o1o\b|\b1010\b|\bhkbn\b|"
    r"\bsmartone\b|\bhgc\b|\b3hk\b|\bctexcel\b|\bcuniq\b|"
    r"香港电讯|香港電訊|电讯盈科|電訊盈科|香港宽频|香港寬頻|数码通|數碼通|"
    r"和记电讯|和記電訊|3香港|有线宽频|有線寬頻|环球全域电讯|環球全域電訊|"
    r"中国移动香港|中國移動香港|中国电信香港|中國電信香港)",
    re.I,
)
_DIRECT_COMPETITOR_RE = re.compile(
    r"(?:\bhkt\b|\bpccw\b|\bcsl\b|\b1o1o\b|\b1010\b|\bhkbn\b|"
    r"\bsmartone\b|\bhgc\b|\b3\s*(?:hong kong|hk)\b|\bi[- ]?cable\b|"
    r"\bctexcel\b|\bcuniq\b|hgc global communications|"
    r"香港电讯|香港電訊|电讯盈科|電訊盈科|香港宽频|香港寬頻|数码通|數碼通|"
    r"和记电讯|和記電訊|3香港|有线宽频|有線寬頻|环球全域电讯|環球全域電訊|"
    r"中国电信香港|中國電信香港|中国联通香港|中國聯通香港)",
    re.I,
)
_BENCHMARK_OPERATOR_RE = re.compile(
    r"(?:china telecom|china unicom|ctexcel|cuniq|vodafone(?:three)?|bt group|"
    r"deutsche telekom|telefonica|at&t|verizon|t-mobile|sk telecom|singtel|"
    r"ntt docomo|\bdocomo\b|\bkddi\b|telstra|airtel|softbank|swisscom|"
    r"\btelia\b|\btele2\b|\bkpn\b|proximus|ooredoo|\bzain\b|\bstc\b|"
    r"etisalat|e&|orange group|ck hutchison|中国电信|中國電信|中国联通|中國聯通|"
    r"英国电信|英國電信|德国电信|德國電信|西班牙电信|西班牙電信|"
    r"沃达丰|沃達豐|新加坡电信|新加坡電信|软银|軟銀|韩国电信|韓國電信)",
    re.I,
)
_OPERATOR_ACTION_RE = re.compile(
    r"(?:launch|unveil|deploy|rollout|trial|pilot|partner|partnership|agreement|contract|"
    r"acquir|merger|capex|network|spectrum|\b5g(?:-a)?\b|\b6g\b|"
    r"open ran|\bran\b|broadband|fibre|fiber|tariff|pricing|price plan|enterprise|"
    r"data cent(?:er|re)|cloud|edge|cyber|fraud|subscriber|customer|strategy|"
    r"restructur|department|appoint|management|regulat|licen[cs]e|service outage|"
    r"发布|發佈|推出|部署|试点|試點|"
    r"合作|协议|協議|合同|收购|收購|并购|併購|投资|投資|资本开支|資本開支|"
    r"网络|網絡|频谱|頻譜|基站|宽带|寬頻|资费|資費|套餐|企业业务|企業業務|"
    r"数据中心|數據中心|云|雲|网络安全|網絡安全|诈骗|詐騙|用户|用戶|"
    r"战略|戰略|重组|重組|部门|部門|任命|监管|監管|牌照)",
    re.I,
)
_BENCHMARK_TOPIC_RE = re.compile(
    r"(?:telecom|telecommunications|mobile operator|carrier|mobile network|spectrum|"
    r"\b5g(?:-a)?\b|\b6g\b|open ran|\bran\b|broadband|fibre|fiber|roaming|esim|mvno|"
    r"tariff|pricing|subscriber|enterprise connectivity|data cent(?:er|re)|cloud service|"
    r"edge computing|cybersecurity|satellite|submarine cable|电讯|電訊|电信|電信|"
    r"运营商|運營商|流动网络|流動網絡|移动网络|移動網絡|频谱|頻譜|基站|"
    r"宽带|寬頻|漫游|漫遊|资费|資費|套餐|用户|用戶|企业连接|企業連接|"
    r"数据中心|數據中心|云服务|雲服務|网络安全|網絡安全|卫星|衛星|海底电缆|海底電纜)",
    re.I,
)
_CORPORATE_CHANGE_RE = re.compile(
    r"(?:acquir|merger|joint venture|spin[- ]?off|stake sale|restructur|new department|"
    r"appoint(?:s|ed|ment)?|chief executive|ceo succession|organization(?:al)? change|"
    r"收购|收購|并购|併購|合资|合資|出售股权|出售股權|重组|重組|架构调整|架構調整|"
    r"组织调整|組織調整|成立.{0,12}部门|成立.{0,12}部門|任命|换帅|換帥)",
    re.I,
)
_NON_TELECOM_CORPORATE_RE = re.compile(
    r"(?:automotive|automaker|motor group|boston dynamics|humanoid robot|robotics company|"
    r"现代汽车|現代汽車|汽车集团|汽車集團|波士顿动力|波士頓動力|人形机器人|人形機器人)",
    re.I,
)
_HK_TELECOM_MARKET_RE = re.compile(
    r"(?:ofca|communications authority|telecom|telecommunications|mobile operator|carrier|"
    r"mobile network|broadband|spectrum|\b5g(?:-a)?\b|\b6g\b|电讯|電訊|电信|電信|"
    r"流动通讯|流動通訊|移动通讯|移動通訊|运营商|運營商|频谱|頻譜|宽频|寬頻|"
    r"宽带|寬帶|网络服务|網絡服務|通讯事务管理局|通訊事務管理局)",
    re.I,
)
_HONG_KONG_RE = re.compile(
    r"(?:hong kong|\bhk\b|香港|ofca|itib|cyberport|science park|数码港|數碼港|科学园|科學園)",
    re.I,
)
_STRATEGIC_RE = re.compile(
    r"(?:telecom|telecommunications|mobile operator|carrier|\b5g(?:-a)?\b|\b6g\b|"
    r"open ran|\bran\b|broadband|fibre|fiber|spectrum|mvno|esim|roaming|submarine cable|"
    r"satellite|data cent(?:er|re)|cloud|edge computing|artificial intelligence|"
    r"(?<![a-z])ai(?![a-z])|large language model|\bllm\b|ai agent|compute|semiconductor|"
    r"chip|export control|entity list|cybersecurity|data privacy|cross-border data|"
    r"digital infrastructure|smart city|sanction|strait of hormuz|iran|geopolit|"
    r"电信|電信|运营商|運營商|网络|網絡|频谱|頻譜|基站|宽带|寬頻|数据中心|數據中心|"
    r"云计算|雲計算|人工智能|大模型|算力|半导体|半導體|芯片|出口管制|实体清单|實體清單|"
    r"网络安全|網絡安全|数据跨境|數據跨境|数字基建|數字基建|监管|監管|制裁|霍尔木兹)",
    re.I,
)
_POLICY_RE = re.compile(
    r"(?:government|policy|regulat|regulator|law|legislation|bill|licen[cs]e|competition authority|"
    r"antitrust|data governance|privacy law|export control|entity list|sanction|subsidy|spectrum auction|"
    r"ofca|communications authority|政府|政策|监管|監管|规管|規管|法规|法規|法案|立法|"
    r"牌照|许可证|許可證|反垄断|反壟斷|竞争委员会|競爭事務委員會|数据治理|數據治理|"
    r"隐私|私隱|出口管制|实体清单|實體清單|制裁|补贴|補貼|频谱拍卖|頻譜拍賣|"
    r"national security|国家安全|國家安全|国安|國安)",
    re.I,
)
_ECONOMY_RE = re.compile(
    r"(?:\bgdp\b|\bcpi\b|\bppi\b|\bpmi\b|inflation|deflation|interest rate|rate cut|rate hike|"
    r"economic growth|recession|unemployment|retail sales|consumer spending|foreign exchange|"
    r"trade surplus|trade deficit|tariff|capital expenditure|capex|宏观经济|宏觀經濟|经济增长|"
    r"經濟增長|通胀|通脹|通缩|通縮|利率|降息|减息|加息|失业率|失業率|零售销售|零售銷售|"
    r"消费|消費|汇率|匯率|贸易顺差|貿易順差|贸易逆差|貿易逆差|关税|關稅|资本开支|資本開支)",
    re.I,
)
_FINANCE_RE = re.compile(
    r"(?:stock price|share price|target price|analyst rating|earnings forecast|financial results|"
    r"net profit|eps\b|\bstock\b|\binvestor\b|should i buy|buy up|stock-picking|"
    r"shares? (?:rise|fall)|\d+% rally|revenue growth|"
    r"股价|股價|目标价|目標價|评级|評級|净利润|淨利潤|盈利预测|盈利預測|"
    r"业绩预告|業績預告|中期业绩|中期業績|港股通|持股解析|融资融券|融資融券|基金|"
    r"台股|受惠股|概念股|个股|個股|\d+档受惠|\d+檔受惠|chartwatch|asx扫描|asx掃描|券商预测|券商預測)",
    re.I,
)
_PRODUCT_AD_RE = re.compile(
    r"(?:iphone\s*18|huawei\s*pura|smartphone review|handset review|phone card|prepaid sim|"
    r"mobile plan|price plan|buy now|\brealme\b|\bredmi\b|\bnarzo\b|geekbench|"
    r"price,? specifications|battery launched|expected price|新品发布|新品發表|产品发布|產品發表|蓝图流出|藍圖流出|"
    r"手机评测|手機評測|手机优惠|手機優惠|套餐优惠|套餐優惠|促销折扣|促銷折扣|"
    r"联想问天|聯想問天|wa5685|破解推理成本困局|asus experthub|"
    r"智能电磁炉|智能電磁爐|家电产品|家電產品|商场.*速度实测|商場.*速度實測|"
    r"展会展示.*产品|展會展示.*產品|营销解决方案|營銷解決方案|"
    r"让营销|讓行銷|成交率.*成|完整ai解方)",
    re.I,
)
_NOISE_RE = re.compile(
    r"(?:autism|spectrum disorder|自闭|自閉|driving licen[cs]e|restaurant licen[cs]e|"
    r"state funeral|football|world cup|messi|pet dog|puppy|recipe|fashion|celebrity|"
    r"weather|rainstorm|yellow rain|暴雨|天文台|三伏天|每日楼市|每日樓市|property market|"
    r"range rover|astronaut|submarine implosion|prison sentence|clinical trial|cancer treatment|"
    r"biotech|scooter|craft beer|horoscope|旅游攻略|旅遊攻略|体育赛事|體育賽事|"
    r"羽球|羽毛球|公開賽|公开赛|ai搞錢|ai搞钱|智慧台中論壇|智慧台中论坛|"
    r"高級文憑|高级文凭|物管專才|物管专才|ai眼鏡.*作弊|ai眼镜.*作弊|"
    r"神級正妹|神级正妹|老人健保|廚餘|厨余|美食導入ai|美食导入ai|"
    r"防災系統|防灾系统|如何讓20美元|如何让20美元|六配速法|限時優惠|限时优惠|"
    r"photography contest|摄影展|攝影展|linkedin|履历|履歷|人才高峰会|人才高峰會|"
    r"生活照|ai修图|ai修圖|女球友|smartphone|screen warranty|智慧车|智慧車|"
    r"登錄興櫃|登录兴柜|ai写自介|ai寫自介|cryptocurrency|crypto token|"
    r"\busdc\b|24小時成交量|24小时成交量|幣速報|币速报|\bnrl\b|broncos|"
    r"trophy|semi-finals|semifinals|rugby|cricket|fighter jet|missile|航空母舰|航空母艦|"
    r"航母|导弹|導彈|food safety|eateries|餐厅卫生|餐廳衛生|"
    r"child|toddler|infant|missing person|homicide|murder|shooting|car crash|court case|"
    r"baseball|basketball|soccer|sports team|player transfer|\bnba\b|\bnfl\b|\bmlb\b|"
    r"男童|女童|幼儿|幼兒|婴儿|嬰兒|儿童|兒童|上吊|尸体|屍體|身亡|死亡|失踪|失蹤|"
    r"谋杀|謀殺|凶杀|兇殺|枪击|槍擊|车祸|車禍|沉船|救援|警方|法院|判刑|"
    r"球队|球隊|球员|球員|赛季|賽季|比赛|比賽|联赛|聯賽|国家队|國家隊|投手|"
    r"av女優|av女优|成人影片|porn|entertainment|movie|film premiere|地震|明星八卦)",
    re.I,
)
_STATIC_PATH_MARKERS = (
    "/solutions/", "/products/", "/product/", "/postpaid/", "/prepaid/",
    "/plans/", "/tariff", "/contact-us", "/1010home/", "/tc/home",
    "/globalbusiness-", "/ctc_login", "/wiki/", "/blob/", "/resources/",
    "/project-links", "/four-zones", "/committees-and-task-force", "/downloads/",
    "/assets/files/", "/legislative_council_business/", "/ad/article/",
    "/perspectives/advisories/", "/about-nm/", "/trending-in-nm",
    "/publications/", ".pdf",
)
_STATIC_TITLE_RE = re.compile(
    r"(?:主页|主頁|首页|首頁|项目链接|項目連結|四大区域|四大區域|"
    r"网站简介|網站簡介|执行摘要|執行摘要|草案全文|政策文件全文|報告全文|报告全文)",
    re.I,
)
_NEWS_PATH_MARKERS = (
    "/news/", "/article/", "/articles/", "/press/", "/media/", "/story/",
    "/stories/", "/newsroom/", "/news-release", "/press-release", "/2026/",
)
_MEDIA_RE = re.compile(
    r"(?:reuters|bloomberg|bbc|cnbc|scmp|rthk|hket|tvb|now\s*财经|now\s*財經|"
    r"singtao|bastillepost|light reading|lightreading|total telecom|totaltele|"
    r"mobile world live|mobileworldlive|capacity media|telecompaper|datacenterdynamics|"
    r"the register|pr newswire|prnewswire|yahoo|caixin|wenweipo|香港文匯|香港文汇|"
    r"mydrivers|快科技|yicai|第一财经|第一財經|shangbao|商报|商報|info\.gov\.hk|gov\.hk)",
    re.I,
)


def _canonical_news_url(value: Any) -> str:
    text = _text(value, 1800)
    try:
        parsed = urlparse(text)
    except ValueError:
        return text
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def _url_publication_hint(value: Any) -> str:
    text = _text(value, 1800)
    full_match = re.search(
        r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", text
    )
    if full_match:
        try:
            return datetime(
                int(full_match.group(1)),
                int(full_match.group(2)),
                int(full_match.group(3)),
                tzinfo=HKT,
            ).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    compact_match = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", text)
    if compact_match:
        try:
            return datetime(
                int(compact_match.group(1)),
                int(compact_match.group(2)),
                int(compact_match.group(3)),
                tzinfo=HKT,
            ).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    month_match = re.search(r"(?<!\d)(20\d{2})[-/](\d{1,2})(?!\d)", text)
    if month_match:
        month = int(month_match.group(2))
        if 1 <= month <= 12:
            return f"{month_match.group(1)}-{month:02d}"
    return ""


def _normalized_news_title(value: Any) -> str:
    text = _text(value, 500).lower()
    text = re.sub(r"^\s*[【\[].{1,24}?[】\]]\s*", "", text)
    text = re.sub(r"\s*[|｜]\s*[^|｜]{1,36}$", "", text)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


_EVENT_TITLE_STOP_RE = re.compile(
    r"(?:集团|集團|公司|宣布|宣佈|将|將|获得|獲得|实现|實現|完全|全资|全資|"
    r"控股|控制|收购|收購|购买|購買|持有|所持|股份|股权|股權|正式|完成|拟|擬|"
    r"计划|計劃|旗下|关联|關聯|加速|战略|戰略|group|company|announces?|acquires?|"
    r"acquisition|purchase|buy|stake|shares?|fully?|takes?control|completes?|plans?)",
    re.I,
)


def _event_title_key(value: Any) -> str:
    title = re.sub(r"project\s*tango", "探戈", _text(value, 500), flags=re.I)
    return _normalized_news_title(_EVENT_TITLE_STOP_RE.sub("", title))


def _event_titles_duplicate(left: Any, right: Any) -> bool:
    left_key = _event_title_key(left)
    right_key = _event_title_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if min(len(left_key), len(right_key)) >= 8 and (
        left_key in right_key or right_key in left_key
    ):
        return True
    if min(len(left_key), len(right_key)) < 10:
        return False
    if SequenceMatcher(None, left_key, right_key).ratio() >= 0.60:
        return True
    left_pairs = {left_key[index : index + 2] for index in range(len(left_key) - 1)}
    right_pairs = {right_key[index : index + 2] for index in range(len(right_key) - 1)}
    return len(left_pairs & right_pairs) / max(1, min(len(left_pairs), len(right_pairs))) >= 0.62


def _news_like(item: dict[str, Any], lower_url: str, text: str) -> bool:
    source = " ".join((_text(item.get("source"), 200), _text(item.get("source_domain"), 200)))
    if _MEDIA_RE.search(source):
        return True
    path = urlparse(lower_url).path.lower()
    if any(marker in path for marker in _NEWS_PATH_MARKERS):
        return True
    if re.search(r"/20\d{2}[/-]\d{1,2}(?:[/-]\d{1,2})?", path):
        return True
    return bool(_LOCAL_COMPETITOR_RE.search(text) and ("press" in path or "news" in path))


def _competitor_relevance(item: dict[str, Any]) -> tuple[bool, str]:
    text = " ".join(
        (
            _text(item.get("title"), 500),
            _text(item.get("snippet"), 1800),
            _text(item.get("source"), 240),
            _text(item.get("url"), 1800),
            _text(item.get("keywords"), 800),
        )
    )
    if _DIRECT_COMPETITOR_RE.search(text):
        return True, "香港直接竞对新闻"
    if _BENCHMARK_OPERATOR_RE.search(text):
        if (
            _CORPORATE_CHANGE_RE.search(text)
            and _BENCHMARK_TOPIC_RE.search(text)
            and not _NON_TELECOM_CORPORATE_RE.search(text)
        ):
            return True, "国际运营商组织或资本动作"
        if _OPERATOR_ACTION_RE.search(text) and _BENCHMARK_TOPIC_RE.search(text):
            return True, "国际运营商业务对标新闻"
    if _HONG_KONG_RE.search(text) and _HK_TELECOM_MARKET_RE.search(text):
        return True, "香港电信市场或监管新闻"
    return False, "未直接关联竞对或香港电信市场"


def _review_news_candidate(item: dict[str, Any]) -> tuple[bool, str]:
    title = _text(item.get("title"), 500)
    snippet = _text(item.get("snippet"), 1800)
    url = _text(item.get("url"), 1800)
    if not title or not url:
        return False, "缺少标题或原文"
    source_date = _publication_date(item.get("source_date") or item.get("published_at"))
    search_date = _search_date(
        item.get("search_date") or item.get("searched_at") or item.get("retrieved_at")
    )
    if not source_date:
        return False, "缺少可验证发布日期"
    if not search_date:
        return False, "缺少检索日期"
    if source_date != search_date:
        return False, "非检索当日发布"
    title_years = {int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", title)}
    if title_years and int(search_date[:4]) not in title_years and max(title_years) < int(search_date[:4]):
        return False, "标题显示旧年份"
    url_date_hint = _url_publication_hint(url)
    if url_date_hint and not source_date.startswith(url_date_hint):
        return False, "原文路径日期与发布时间不符"
    item["source_date"] = source_date
    item["search_date"] = search_date
    lower_url = url.lower()
    text = f"{title} {snippet}"
    lower_text = text.lower()
    path = urlparse(lower_url).path.lower()
    if "bing.com/aclick" in lower_url or "googleadservices" in lower_url:
        return False, "广告跳转"
    source_text = f"{_text(item.get('source'), 200)} {lower_url}".lower()
    if "fund.eastmoney.com" in source_text or "天天基金" in source_text:
        return False, "基金或行情页面"
    if any(marker in path for marker in _STATIC_PATH_MARKERS):
        return False, "官网产品或资料页"
    if "nm.gov.hk" in source_text and not url_date_hint:
        return False, "北部都会区静态页面"
    if "chinaelections.org" in source_text or _STATIC_TITLE_RE.search(title):
        return False, "静态文件或资料页"
    if _NOISE_RE.search(f"{lower_text} {source_text}"):
        return False, "生活、体育或误命中新闻"
    if re.search(r"(?:codex\s*micro|实体键盘|實體鍵盤|限量版键盘|限量版鍵盤)", lower_text, re.I):
        return False, "消费型AI硬件新品"
    if _PRODUCT_AD_RE.search(lower_text):
        return False, "消费产品或套餐广告"
    if (
        _BENCHMARK_OPERATOR_RE.search(text)
        and _CORPORATE_CHANGE_RE.search(text)
        and _NON_TELECOM_CORPORATE_RE.search(text)
    ):
        return False, "非电信资产或业务事件"
    direct_competitor = bool(_DIRECT_COMPETITOR_RE.search(text))
    if _FINANCE_RE.search(lower_text) and not direct_competitor:
        return False, "非香港竞对股市或业绩稿"
    competitor_relevant, relevance_reason = _competitor_relevance(item)
    if not competitor_relevant:
        if _POLICY_RE.search(text) and (
            _STRATEGIC_RE.search(text)
            or _ECONOMY_RE.search(text)
            or re.search(r"national security|国家安全|國家安全|国安|國安", text, re.I)
        ):
            relevance_reason = "政策监管"
        elif _ECONOMY_RE.search(text):
            relevance_reason = "宏观经济"
        elif _STRATEGIC_RE.search(text):
            relevance_reason = "战略产业新闻"
        else:
            return False, "未达到战略相关门槛"
    generic_titles = {
        "hkt", "pccw", "ctexcel", "documentctexcel", "1010home", "wwwbisgov",
        "香港電訊商及流動數據服務csl", "香港电讯商及流动数据服务csl",
    }
    if _normalized_news_title(title) in generic_titles:
        return False, "官网首页或栏目页"
    if not _news_like(item, lower_url, text):
        return False, "不像独立新闻文章"
    return True, relevance_reason


def curate_news_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    kept: dict[str, dict[str, Any]] = {}
    title_keys: list[str] = []
    reasons: Counter[str] = Counter()
    for source_item in items:
        if not isinstance(source_item, dict):
            continue
        item = dict(source_item)
        keep, reason = _review_news_candidate(item)
        if not keep:
            reasons[reason] += 1
            continue
        url_key = _canonical_news_url(item.get("url"))
        title_key = _normalized_news_title(item.get("title"))
        if (
            not url_key
            or not title_key
            or url_key in kept
            or any(_event_titles_duplicate(title_key, existing) for existing in title_keys)
        ):
            reasons["重复新闻"] += 1
            continue
        text = f"{_text(item.get('title'), 500)} {_text(item.get('snippet'), 1800)}"
        item["region"] = "香港本地" if _HONG_KONG_RE.search(text) or _LOCAL_COMPETITOR_RE.search(text) else "国际/行业"
        if "竞对" in reason or "运营商" in reason:
            item["category"] = "竞对动态"
        elif reason == "政策监管":
            item["category"] = "政策监管"
        elif reason == "宏观经济":
            item["category"] = "宏观经济"
        elif reason == "其他待筛":
            item["category"] = "其他待筛"
        else:
            item["category"] = _category_label(item)
        item["filter_reason"] = reason
        item["news_id"] = _news_item_id(item.get("url"), item.get("title"))
        kept[url_key] = item
        title_keys.append(title_key)
    result = list(kept.values())
    category_priority = {"竞对动态": 0, "政策监管": 1, "宏观经济": 2, "其他待筛": 9}
    result.sort(
        key=lambda item: (
            category_priority.get(str(item.get("category") or ""), 3),
            item.get("region") != "香港本地",
            -int(item.get("score") or 0),
            str(item.get("source_date") or ""),
            str(item.get("title") or ""),
        )
    )
    return result[:100], reasons


def _load_curated_latest() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = [
        LATEST_PATH,
        Path("/Users/liaowang/cmhk_public_crawl_app/strategy_briefing/news_discovery_latest.json"),
        STATE_PATH.parent / "news_discovery_full.json",
        Path("/Users/liaowang/cmhk_public_crawl_app/strategy_briefing/news_discovery_full.json"),
    ]
    combined: list[dict[str, Any]] = []
    generated_at = ""
    source_paths: list[str] = []
    seen_paths: set[str] = set()
    for path in paths:
        path_key = str(path)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        payload = _read_json(path, {})
        items = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(items, list) or not items:
            continue
        combined.extend(item for item in items if isinstance(item, dict))
        source_paths.append(path_key)
        if not generated_at:
            generated_at = _text(payload.get("generated_at"), 60)
    if combined:
        curated, reasons = curate_news_items(combined)
        category_counts = Counter(
            _text(item.get("category") or "未分类", 80) for item in curated
        )
        region_counts = Counter(
            _text(item.get("region") or "未分类", 80) for item in curated
        )
        sources = {
            _text(item.get("source") or item.get("source_domain"), 160)
            for item in curated
            if _text(item.get("source") or item.get("source_domain"), 160)
        }
        return curated, {
            "generated_at": generated_at or _now_iso(),
            "slot_label": "战略新闻搜索池",
            "input_count": len(combined),
            "candidate_count": len(curated),
            "filtered_count": len(combined) - len(curated),
            "filtered_reasons": dict(reasons),
            "category_counts": dict(category_counts),
            "region_counts": dict(region_counts),
            "source_count": len(sources),
            "source_path": ", ".join(source_paths),
            "group_notifications_paused": _group_notifications_paused(),
        }
    return [], {
        "generated_at": _now_iso(),
        "slot_label": "战略新闻搜索池",
        "input_count": 0,
        "candidate_count": 0,
        "filtered_count": 0,
        "filtered_reasons": {},
        "category_counts": {},
        "region_counts": {},
        "source_count": 0,
        "group_notifications_paused": _group_notifications_paused(),
    }

def run_cycle(*, force: bool = False) -> dict[str, Any]:
    with _LOCK:
        state = _read_json(STATE_PATH, {})
        now_epoch = time.time()
        if not force and now_epoch - float(state.get("last_poll_epoch") or 0) < POLL_SECONDS:
            return {"status": "throttled", "sheet_url": state.get("sheet_url") or ""}
        items, latest = _load_curated_latest()
        sync_result = sync_candidates(
            items,
            generated_at=_text(latest.get("generated_at"), 40),
            slot_label=_text(latest.get("slot_label"), 80),
        )
        review_result = apply_reviews(sync_result["sheet_id"])
        state = _read_json(STATE_PATH, {})
        state.update(
            {
                "last_poll_epoch": now_epoch,
                "last_poll_at": _now_iso(),
                "last_poll_result": review_result,
                "last_source_summary": latest,
            }
        )
        _write_json(STATE_PATH, state)
        return {
            "status": "ok",
            **latest,
            **sync_result,
            **review_result,
            "source_candidate_count": int(latest.get("candidate_count") or 0),
            "sheet_candidate_count": int(sync_result.get("candidate_count") or 0),
        }


def build_notice_cards(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    del args, kwargs
    items, latest = _load_curated_latest()
    result = sync_candidates(
        items,
        generated_at=_text(latest.get("generated_at"), 40),
        slot_label=_text(latest.get("slot_label"), 80),
    )
    apply_reviews(result["sheet_id"])
    state = _read_json(STATE_PATH, {})
    paused = _group_notifications_paused()
    state["group_notifications_paused"] = paused
    if paused:
        state["group_notifications_paused_at"] = _now_iso()
    else:
        state.pop("group_notifications_paused_at", None)
        state["group_notifications_resumed_at"] = _now_iso()
    _write_json(STATE_PATH, state)
    return []
