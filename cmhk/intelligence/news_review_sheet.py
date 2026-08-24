from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from cmhk.integrations.feishu_sheet_rollover import (
    capacity_decision,
    record_active_part,
    timestamped_part_title,
)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "strategy_briefing"
LATEST_PATH = DATA_DIR / "news_discovery_latest.json"
FULL_DISCOVERY_PATH = DATA_DIR / "news_discovery_full.json"
PUBLISHED_PATH = DATA_DIR / "published.json"
STATE_PATH = DATA_DIR / "news_review_sheet_state.json"
GATE_METADATA_STATE_KEY = "candidate_gate_metadata"

HKT = ZoneInfo("Asia/Hong_Kong")
LARK_CLI = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"
SPREADSHEET_TOKEN = (
    os.environ.get("CMHK_NEWS_REVIEW_SPREADSHEET_TOKEN")
    or "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
).strip()
SHEET_TITLE = os.environ.get("CMHK_NEWS_REVIEW_SHEET_TITLE") or "滚动新闻候选池"
POLL_SECONDS = max(60, int(os.environ.get("CMHK_NEWS_REVIEW_POLL_SECONDS", "300")))
MAX_SHEET_ROWS = max(500, int(os.environ.get("CMHK_NEWS_REVIEW_MAX_ROWS", "3000")))
REVIEW_ROW_HEIGHT_PX = 76
SEPARATOR_ROW_HEIGHT_PX = 18
SAME_DAY_BATCH_SEPARATOR_ROWS = 1
CROSS_DAY_SEPARATOR_ROWS = 2
SEPARATOR_ROW_COLOR = "#E8EEF5"
ROLLOVER_SOFT_LIMIT_RATIO = min(
    0.95,
    max(0.50, float(os.environ.get("CMHK_NEWS_REVIEW_ROLLOVER_RATIO", "0.90"))),
)
ROLLOVER_TARGET_KEY = "news_review"
SHEET_SOURCE = "feishu_review_sheet"
FORMAT_VERSION = 9
LARK_READ_MAX_ATTEMPTS = 3
LARK_TRANSIENT_ERROR_CODES = {2200}
SUCCESSFUL_CYCLE_RESULTS_STATE_KEY = "successful_cycle_results"
PENDING_CYCLE_STATE_KEY = "pending_cycle"
MAX_SUCCESSFUL_CYCLE_RESULTS = 32

HEADERS = [
    "是否纳入滚动",
    "是否纳入周报",
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
    "信息获取流程",
]

_LOCK = threading.RLock()
PROCESS_LOCK_PATH = DATA_DIR / "cmhk.intelligence.news_review_sheet.lock"
DASHBOARD_PUBLISH_SCRIPT = ROOT / "scripts" / "publish_executive_dashboard_pages.py"
DASHBOARD_PUBLISH_LOG = DATA_DIR / "dashboard_pages_publish.log"


@contextmanager
def _review_process_lock(*, wait: bool):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_handle = None
    try:
        try:
            import fcntl

            lock_handle = PROCESS_LOCK_PATH.open("a+")
            operation = fcntl.LOCK_EX
            if not wait:
                operation |= fcntl.LOCK_NB
            fcntl.flock(lock_handle.fileno(), operation)
        except BlockingIOError:
            if lock_handle is not None:
                lock_handle.close()
                lock_handle = None
            yield False
            return
        except (ImportError, OSError):
            if lock_handle is not None:
                lock_handle.close()
                lock_handle = None
        yield True
    finally:
        if lock_handle is not None:
            try:
                import fcntl

                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            lock_handle.close()


def _now_iso() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _group_notifications_paused() -> bool:
    return os.environ.get("CMHK_STRATEGIC_GROUP_NOTIFICATIONS", "0") != "1"


ProgressCallback = Callable[[str, str], None]


def _progress(
    progress_callback: ProgressCallback | None,
    phase: str,
    detail: str,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(phase, detail)
    except Exception:
        logging.exception("战略新闻审核详细日志回调失败")


def _schedule_public_dashboard_publish() -> dict[str, Any]:
    if os.environ.get("CMHK_DASHBOARD_PAGES_AUTO_PUBLISH", "0") != "1":
        return {"status": "disabled"}
    if not DASHBOARD_PUBLISH_SCRIPT.exists():
        return {"status": "missing_script"}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    with DASHBOARD_PUBLISH_LOG.open("ab") as output:
        process = subprocess.Popen(
            [sys.executable, str(DASHBOARD_PUBLISH_SCRIPT)],
            cwd=str(ROOT),
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"status": "started", "pid": process.pid}


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


def _cell_link(value: Any, limit: int = 1800) -> str:
    entries = value if isinstance(value, list) else [value]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        link = _text(entry.get("link"), limit)
        if link:
            return link
    if isinstance(value, dict):
        return _text(value.get("text"), limit)
    if isinstance(value, list):
        return " ".join(
            _text(entry.get("text"), limit)
            for entry in value
            if isinstance(entry, dict) and _text(entry.get("text"), limit)
        )[:limit]
    return _text(value, limit)


def _lark_error_code(payload: dict[str, Any]) -> int:
    error = payload.get("error")
    if not isinstance(error, dict):
        return 0
    try:
        return int(error.get("code") or 0)
    except (TypeError, ValueError):
        return 0


def _lark_error_message(
    payload: dict[str, Any],
    *,
    stderr: str = "",
    output: str = "",
) -> str:
    return str(
        payload.get("message")
        or payload.get("msg")
        or stderr.strip()
        or output
        or "飞书命令执行失败"
    )


def _lark(
    *parts: str,
    timeout: int = 120,
    retry_transient: bool = False,
) -> dict[str, Any]:
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
    attempts = LARK_READ_MAX_ATTEMPTS if retry_transient else 1
    for attempt in range(1, attempts + 1):
        try:
            process = subprocess.run(
                [LARK_CLI, *parts, "--as", "user"],
                cwd=str(ROOT),
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if attempt >= attempts:
                raise RuntimeError(
                    f"飞书只读接口超时，已尝试 {attempt} 次"
                ) from exc
            logging.warning(
                "飞书只读接口超时，第 %s/%s 次失败，准备重试",
                attempt,
                attempts,
            )
            time.sleep(2 ** (attempt - 1))
            continue
        output = process.stdout.strip()
        try:
            payload = json.loads(output) if output else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                process.stderr.strip() or output or "飞书命令未返回 JSON"
            ) from exc
        if process.returncode == 0 and payload.get("ok") is not False:
            return payload
        error_code = _lark_error_code(payload)
        if (
            retry_transient
            and error_code in LARK_TRANSIENT_ERROR_CODES
            and attempt < attempts
        ):
            logging.warning(
                "飞书只读接口返回瞬时错误 %s，第 %s/%s 次失败，准备重试",
                error_code,
                attempt,
                attempts,
            )
            time.sleep(2 ** (attempt - 1))
            continue
        raise RuntimeError(
            _lark_error_message(
                payload,
                stderr=process.stderr,
                output=output,
            )
        )
    raise RuntimeError("飞书只读接口重试流程异常结束")


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
        retry_transient=True,
    )


def _sheet_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sheets = _walk_for_key(payload, "sheets")
    if isinstance(sheets, dict):
        sheets = sheets.get("sheets")
    return [sheet for sheet in sheets if isinstance(sheet, dict)] if isinstance(sheets, list) else []


def _sheet_title(sheet: dict[str, Any]) -> str:
    return str(sheet.get("title") or sheet.get("sheet_name") or "")


def _find_sheet_id(payload: dict[str, Any], preferred_sheet_id: str = "") -> str:
    items = _sheet_items(payload)
    if preferred_sheet_id:
        for sheet in items:
            if str(sheet.get("sheet_id") or "") == preferred_sheet_id:
                return preferred_sheet_id
    for sheet in items:
        if _sheet_title(sheet) == SHEET_TITLE:
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
        f"{sheet_id}!A1:N1",
        "--style",
        json.dumps(header_style, ensure_ascii=False),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!A2:N{MAX_SHEET_ROWS}",
        "--style",
        json.dumps(body_style, ensure_ascii=False),
    )
    _best_effort(
        "sheets",
        "+set-style",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--range",
        f"{sheet_id}!A2:C{MAX_SHEET_ROWS}",
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
        f"{sheet_id}!D2:D{MAX_SHEET_ROWS}",
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
        f"{sheet_id}!E2:F{MAX_SHEET_ROWS}",
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
        f"{sheet_id}!G2:G{MAX_SHEET_ROWS}",
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
        f"{sheet_id}!H2:H{MAX_SHEET_ROWS}",
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
        f"{sheet_id}!I2:N{MAX_SHEET_ROWS}",
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
        f"{sheet_id}!C2:C{MAX_SHEET_ROWS}",
        "--condition-values",
        json.dumps(["未同步", "已纳入", "已移除", "同步失败"], ensure_ascii=False),
        "--colors",
        json.dumps(["#8F959E", "#2563EB", "#D97706", "#DC2626"]),
        "--highlight",
    )
    widths = [
        112,
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
        260,
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
        str(REVIEW_ROW_HEIGHT_PX),
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
        "8",
    )
    _best_effort(
        "sheets",
        "+create-filter-view",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--range",
        f"{sheet_id}!A1:N{MAX_SHEET_ROWS}",
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


def _insert_rows(
    sheet_id: str,
    count: int,
    *,
    start_index: int = 1,
    separator_count: int = 0,
) -> None:
    if count <= 0:
        return
    if separator_count < 0 or separator_count > count:
        raise ValueError("separator_count must be between zero and count")
    _lark(
        "sheets",
        "+insert-dimension",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--dimension",
        "ROWS",
        "--start-index",
        str(start_index),
        "--end-index",
        str(start_index + count),
        "--inherit-style",
        "AFTER",
    )
    # Feishu row insertion inherits cell formatting but not row height. Reapply
    # the review-table height so newly inserted candidates match prior rows.
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
        str(start_index + 1),
        "--end-index",
        str(start_index + count),
        "--fixed-size",
        str(REVIEW_ROW_HEIGHT_PX),
        "--visible",
    )
    if separator_count:
        separator_start = start_index + count - separator_count + 1
        separator_end = start_index + count
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
            str(separator_start),
            "--end-index",
            str(separator_end),
            "--fixed-size",
            str(SEPARATOR_ROW_HEIGHT_PX),
            "--visible",
        )
        _best_effort(
            "sheets",
            "+set-style",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--range",
            f"{sheet_id}!A{separator_start}:N{separator_end}",
            "--style",
            json.dumps({"backColor": SEPARATOR_ROW_COLOR}, ensure_ascii=False),
        )


def _batch_separator_count(
    new_values: list[list[Any]],
    existing_rows: list[list[Any]],
) -> int:
    """Return the blank-row gap between a new batch and existing news."""

    if not new_values:
        return 0
    existing_first = next(
        (
            row
            for row in existing_rows
            if row and any(_text(value, 80) for value in row)
        ),
        None,
    )
    if existing_first is None:
        return 0
    new_date = _publication_date(new_values[-1][3])
    existing_date = _publication_date(existing_first[3])
    if new_date and existing_date and new_date == existing_date:
        return SAME_DAY_BATCH_SEPARATOR_ROWS
    return CROSS_DAY_SEPARATOR_ROWS


def _normalized_sheet_row(row: list[Any], format_version: int = FORMAT_VERSION) -> list[Any]:
    if format_version <= 5:
        width = 10
    elif format_version == 6:
        width = 11
    elif format_version == 7:
        width = 12
    elif format_version == 8:
        width = 13
    else:
        width = len(HEADERS)
    padded = (list(row) + [""] * width)[:width]
    if format_version <= 5:
        return padded
    expected_url_index = 8 if format_version == 6 else 9 if format_version == 7 else 10
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
    if format_version == 7 and not url_at_expected_column and url_shifted_one_column:
        return [
            *padded[:7],
            padded[8],
            padded[9],
            padded[10],
            padded[11],
            "历史候选",
        ]
    if format_version == 8 and not url_at_expected_column and url_shifted_one_column:
        corrected = [
            *padded[:8],
            padded[9],
            padded[10],
            padded[11],
            padded[12],
            "历史候选",
        ]
        return corrected
    return padded


def _read_rows(
    sheet_id: str,
    *,
    format_version: int = FORMAT_VERSION,
) -> list[list[Any]]:
    if format_version <= 5:
        end_column = "J"
    elif format_version == 6:
        end_column = "K"
    elif format_version == 7:
        end_column = "L"
    elif format_version == 8:
        end_column = "M"
    else:
        end_column = "N"
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
        retry_transient=True,
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


def _validate_sheet_rows(
    rows: list[list[Any]],
    *,
    context: str,
) -> None:
    errors: list[str] = []
    for index, row in enumerate(rows, start=2):
        if not row or not any(_text(value, 80) for value in row):
            continue
        if len(row) != len(HEADERS):
            errors.append(f"第{index}行列数为{len(row)}，应为{len(HEADERS)}")
            continue
        search_date = _publication_date(row[3])
        source_date = _publication_date(row[9])
        source_url = _cell_link(row[10], 1600)
        title = _text(row[6], 500)
        category = _text(row[5], 120)
        if not search_date:
            errors.append(f"第{index}行检索日期不在D列")
        if not source_date and _normalized_status(row[0]) != "不接受":
            errors.append(f"第{index}行发布时间不在J列")
        if not title:
            errors.append(f"第{index}行新闻标题不在G列")
        if not category:
            errors.append(f"第{index}行分类不在F列")
        if not source_url.lower().startswith(("http://", "https://")):
            errors.append(f"第{index}行原文链接不在K列")
        if len(errors) >= 12:
            break
    if errors:
        raise RuntimeError(
            f"{context}结构校验失败，已停止写入以保护飞书审核表："
            + "；".join(errors)
        )


def _comparable_sheet_row(row: list[Any]) -> list[str]:
    padded = (list(row) + [""] * len(HEADERS))[: len(HEADERS)]
    return [
        _cell_link(cell, 5000) if index == 10 else _text(cell, 5000)
        for index, cell in enumerate(padded)
    ]


def ensure_sheet() -> str:
    with _LOCK:
        state = _read_json(STATE_PATH, {})
        info = _spreadsheet_info()
        saved_sheet_id = _text(state.get("sheet_id"), 120) if isinstance(state, dict) else ""
        sheet_id = _find_sheet_id(info, saved_sheet_id)
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
        if not created and previous_version not in {0, FORMAT_VERSION}:
            raise RuntimeError(
                "检测到飞书审核表格式版本变化，自动整表迁移已禁用以保护人工审核结果："
                f"当前版本 {previous_version}，目标版本 {FORMAT_VERSION}。"
                "请先使用独立迁移脚本备份、预检并回读验证。"
            )
        _write(sheet_id, "A1:N1", [HEADERS])
        _write(sheet_id, "O1:P1", [[""] * 2])
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
                "sheet_title": next(
                    (_sheet_title(sheet) for sheet in _sheet_items(info) if str(sheet.get("sheet_id") or "") == sheet_id),
                    SHEET_TITLE,
                ),
                "sheet_url": _sheet_url(sheet_id),
                "updated_at": _now_iso(),
            }
        )
        _write_json(STATE_PATH, state)
        record_active_part(
            ROOT,
            ROLLOVER_TARGET_KEY,
            spreadsheet_token=SPREADSHEET_TOKEN,
            sheet_id=sheet_id,
            sheet_title=str(state.get("sheet_title") or SHEET_TITLE),
        )
        return sheet_id


def _rollover_review_sheet(
    *,
    current_sheet_id: str,
    current_rows_by_id: dict[str, list[Any]],
    decision: Any,
) -> tuple[str, dict[str, Any]]:
    """Create and activate a dated review-sheet part before a capacity failure."""

    state = _read_json(STATE_PATH, {})
    info = _spreadsheet_info()
    items = _sheet_items(info)
    if len(items) >= decision.soft_sheet_limit:
        raise RuntimeError(
            "主工作簿子表数已进入安全阈值，为避免再次触发 300 张上限，"
            "已停止在该工作簿内继续新建分卷。"
        )
    titles = {_sheet_title(sheet) for sheet in items}
    part_title = timestamped_part_title(SHEET_TITLE, existing_titles=titles)
    _lark(
        "sheets",
        "+create-sheet",
        "--spreadsheet-token",
        SPREADSHEET_TOKEN,
        "--title",
        part_title,
        "--index",
        str(len(items)),
    )
    refreshed = _spreadsheet_info()
    new_sheet_id = next(
        (
            str(sheet.get("sheet_id") or "")
            for sheet in _sheet_items(refreshed)
            if _sheet_title(sheet) == part_title
        ),
        "",
    )
    if not new_sheet_id:
        raise RuntimeError("新闻审核表分卷已请求创建，但回读未找到新子表")
    row_count = _sheet_row_count(refreshed, new_sheet_id)
    if row_count < MAX_SHEET_ROWS:
        _lark(
            "sheets",
            "+add-dimension",
            "--spreadsheet-token",
            SPREADSHEET_TOKEN,
            "--sheet-id",
            new_sheet_id,
            "--dimension",
            "ROWS",
            "--length",
            str(MAX_SHEET_ROWS - row_count),
        )
    _write(new_sheet_id, "A1:N1", [HEADERS])
    _format_sheet(new_sheet_id)

    archived_ids = {
        _text(value, 80)
        for value in (state.get("archived_news_ids") or [])
        if _text(value, 80)
    }
    archived_ids.update(current_rows_by_id)
    archived_parts = list(state.get("archive_parts") or [])
    previous_title = str(state.get("sheet_title") or SHEET_TITLE)
    previous = {
        "spreadsheet_token": SPREADSHEET_TOKEN,
        "sheet_id": current_sheet_id,
        "sheet_title": previous_title,
        "sheet_url": _sheet_url(current_sheet_id),
    }
    archived_parts.append(
        {
            **previous,
            "archived_at_hkt": _now_iso(),
            "candidate_count": len(current_rows_by_id),
        }
    )
    state.update(
        {
            "sheet_id": new_sheet_id,
            "sheet_title": part_title,
            "sheet_url": _sheet_url(new_sheet_id),
            "last_candidate_count": 0,
            "archive_parts": archived_parts,
            "archived_news_ids": sorted(archived_ids),
            "last_rollover_at_hkt": _now_iso(),
            "last_rollover_reason": decision.reason,
            "updated_at": _now_iso(),
        }
    )
    _write_json(STATE_PATH, state)
    record_active_part(
        ROOT,
        ROLLOVER_TARGET_KEY,
        spreadsheet_token=SPREADSHEET_TOKEN,
        sheet_id=new_sheet_id,
        sheet_title=part_title,
        decision=decision,
        previous=previous,
    )
    return new_sheet_id, state


def _keywords(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(_text(item, 80) for item in value if _text(item, 80))
    return _text(value, 500)


def _historical_information_flow(value: Any) -> str:
    keywords = _keywords(value)
    detail = f"；命中：{keywords}" if keywords else ""
    return f"历史新闻搜索（搜索引擎未留存{detail}）"


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


def _timestamp_hkt(value: Any) -> datetime | None:
    text = _text(value, 80)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HKT)
    return parsed.astimezone(HKT)


def _gate_metadata(item: dict[str, Any]) -> dict[str, str]:
    metadata = {
        "published_at": _text(
            item.get("published_at")
            or item.get("source_date")
            or item.get("publication_date"),
            80,
        ),
        "search_window_start": _text(item.get("search_window_start"), 80),
        "search_window_end": _text(item.get("search_window_end"), 80),
        "search_origin": _text(item.get("search_origin"), 100),
    }
    return {key: value for key, value in metadata.items() if value}


def _gate_metadata_key(value: Any) -> str:
    return _canonical_news_url(value)


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


def _flow_keywords(item: dict[str, Any]) -> str:
    value = (
        item.get("ai_keywords")
        or item.get("matched_keywords")
        or item.get("keywords")
    )
    if isinstance(value, list):
        terms = [_text(term, 60) for term in value if _text(term, 60)]
    else:
        terms = [
            _text(term, 60)
            for term in re.split(r"[、,，|]+", _text(value, 300))
            if _text(term, 60)
        ]
    return "、".join(dict.fromkeys(terms[:5]))


def _flow_context(item: dict[str, Any], *, include_competitor: bool = False) -> str:
    details: list[str] = []
    if include_competitor:
        competitor = _text(item.get("canonical_competitor"), 80)
        if competitor:
            details.append(competitor)
    module = _text(item.get("module") or item.get("category"), 80)
    if module and (not include_competitor or not details):
        details.append(f"模块：{module}")
    keywords = _flow_keywords(item)
    if keywords:
        details.append(f"命中：{keywords}")
    return "；".join(details)


def _information_flow(item: dict[str, Any], *, historical: bool = False) -> str:
    explicit = _text(
        item.get("information_flow") or item.get("acquisition_flow"),
        300,
    )
    if explicit:
        return explicit
    origin = _text(item.get("search_origin"), 100)
    provider = {
        "bing": "Bing News",
        "google": "Google News",
    }.get(_text(item.get("search_provider"), 40).lower(), "")
    search_step = f"{provider}搜索" if provider else "新闻搜索"
    if origin == "scheduled_crawl_reference" or item.get(
        "scheduled_crawl_signal_id"
    ):
        crawl_details: list[str] = []
        config_row = _text(item.get("scheduled_crawl_config_row"), 20)
        if config_row:
            crawl_details.append(f"配置第{config_row}行")
        parent_url = _text(
            item.get("scheduled_crawl_parent_url")
            or item.get("scheduled_crawl_target_url"),
            1600,
        )
        parent_domain = (
            urlparse(parent_url).hostname or ""
        ).lower().removeprefix("www.")
        if parent_domain:
            crawl_details.append(parent_domain)
        keywords = _flow_keywords(item)
        if keywords:
            crawl_details.append(f"命中：{keywords}")
        detail_text = f"（{'；'.join(crawl_details)}）" if crawl_details else ""
        return f"定时页面爬虫{detail_text}发现 → {search_step}核验"
    if origin == "mandatory_local_competitor":
        context = _flow_context(item, include_competitor=True)
        return f"后台固定竞对词库{f'（{context}）' if context else ''} → {search_step}"
    if origin == "background_fixed_keywords":
        context = _flow_context(item)
        return f"后台固定战略词库{f'（{context}）' if context else ''} → {search_step}"
    if origin == "monitoring_sheet_keyword_search":
        context = _flow_context(item)
        return f"飞书监测表关键词{f'（{context}）' if context else ''} → {search_step}"
    if origin in {"agentic_expansion", "agentic_followup"}:
        context = _flow_context(item)
        round_label = "覆盖补搜" if origin == "agentic_expansion" else "缺口复查"
        return (
            f"Agentic Search {round_label}"
            f"{f'（{context}）' if context else ''} → {search_step}"
        )
    if item.get("crawl_run_id") and not item.get("query"):
        return "定时页面爬虫"
    if historical:
        return "新闻搜索爬虫（历史候选）"
    return "新闻搜索爬虫"


def _candidate_row(item: dict[str, Any], generated_at: str) -> list[Any]:
    return [
        "待审核",
        "待审核",
        "未同步",
        _search_date(
            item.get("search_date")
            or item.get("searched_at")
            or item.get("retrieved_at")
            or generated_at
        ),
        _text(item.get("ai_region") or item.get("region") or "国际/行业", 40),
        _text(item.get("ai_category") or item.get("category") or _category_label(item), 80),
        _text(item.get("ai_title"), 500),
        _text(item.get("ai_summary"), 500),
        _text(item.get("source") or item.get("source_domain"), 160),
        _display_time(item.get("source_date") or item.get("published_at")),
        _text(item.get("url"), 1600),
        _text(item.get("ai_keywords") or _keywords(item.get("keywords")), 500),
        _text(item.get("ai_inclusion_reason") or item.get("filter_reason") or "战略新闻候选", 300),
        _information_flow(item),
    ]


def _recent_semantic_history(
    history_items: list[dict[str, Any]],
    *,
    generated_at: str = "",
    candidate_items: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Return the current Hong Kong search day plus the preceding two days."""
    search_day = _search_date(generated_at or _now_iso())
    candidate_days = {
        _search_date(
            item.get("search_date")
            or item.get("searched_at")
            or item.get("retrieved_at")
            or generated_at
        )
        for item in (candidate_items or [])
    }
    candidate_days.discard("")
    if len(candidate_days) == 1:
        search_day = next(iter(candidate_days))
    try:
        anchor_day = datetime.fromisoformat(search_day).date()
    except ValueError:
        anchor_day = datetime.now(HKT).date()
        search_day = anchor_day.isoformat()
    included_days = {
        (anchor_day - timedelta(days=offset)).isoformat()
        for offset in range(3)
    }
    return search_day, [
        item
        for item in history_items
        if _search_date(item.get("search_date")) in included_days
    ]


# Compatibility alias for callers outside this module. Its behavior now follows
# the required three-day search window.
_same_day_semantic_history = _recent_semantic_history


HUMAN_DECISION_COLUMNS = (0, 1, 2)
STATUS_PRIORITY = {"接受": 4, "不接受": 3, "暂缓": 2, "待审核": 1}


def _index_review_rows(rows: list[list[Any]]) -> dict[str, list[Any]]:
    rows_by_id: dict[str, list[Any]] = {}
    for index, row in enumerate(rows, start=2):
        if not row or not any(_text(value, 80) for value in row):
            continue
        padded = (list(row) + [""] * len(HEADERS))[: len(HEADERS)]
        news_id = _row_dict(padded, index)["news_id"]
        if not news_id:
            continue
        previous = rows_by_id.get(news_id)
        if previous is not None and STATUS_PRIORITY.get(
            _normalized_status(padded[0]), 0
        ) <= STATUS_PRIORITY.get(_normalized_status(previous[0]), 0):
            continue
        rows_by_id[news_id] = padded
    return rows_by_id


def _refresh_live_review_sheet(
    sheet_id: str,
    existing_rows_by_id: dict[str, list[Any]],
    existing_status: dict[str, tuple[str, str]],
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Re-read the live sheet before mutating it.

    Existing rows are never rewritten. This refresh only decides which new
    rows are truly absent, and records concurrent human edits for monitoring.
    """

    rescued: list[dict[str, str]] = []
    try:
        latest_rows = _read_rows(sheet_id)
    except Exception:
        logging.exception("写回前重新读取审核表失败，本轮只追加新行、不改已有行")
        _progress(
            progress_callback,
            "人工审核状态保护",
            "写回前重新读取审核表失败，已改为只追加新行，不覆盖已有审核结果。",
        )
        return {
            "rescued": rescued,
            "rows": list(existing_rows_by_id.values()),
            "rows_by_id": dict(existing_rows_by_id),
            "physical_count": len(existing_rows_by_id),
            "row_span": len(existing_rows_by_id),
        }

    latest_by_id = _index_review_rows(latest_rows)
    physical_count = sum(
        1
        for row in latest_rows
        if row and any(_text(value, 80) for value in row)
    )
    for news_id, stored_row in existing_rows_by_id.items():
        latest = latest_by_id.get(news_id)
        if latest is None:
            continue
        before = tuple(
            _text(stored_row[column], 40) for column in HUMAN_DECISION_COLUMNS
        )
        after = tuple(
            _text(latest[column], 40) for column in HUMAN_DECISION_COLUMNS
        )
        if before == after:
            continue
        existing_status[news_id] = (
            _normalized_status(after[0]),
            after[2] or "未同步",
        )
        rescued.append(
            {
                "news_id": news_id,
                "title": _text(latest[6], 240),
                "before": " / ".join(before),
                "after": " / ".join(after),
            }
        )

    if rescued:
        logging.warning(
            "写回前发现 %s 条候选的人工审核状态在本轮运行期间被修改，已有行不会被覆盖：%s",
            len(rescued),
            "；".join(
                f"{entry['title'][:40]}（{entry['before']} → {entry['after']}）"
                for entry in rescued[:3]
            ),
        )
    _progress(
        progress_callback,
        "人工审核状态保护",
        (
            f"写回前重新读取 {physical_count} 行，"
            f"本轮运行期间有 {len(rescued)} 条人工决策变化；已有行将保持不动。"
        ),
    )
    return {
        "rescued": rescued,
        "rows": latest_rows,
        "rows_by_id": latest_by_id,
        "physical_count": physical_count,
        "row_span": len(latest_rows),
    }


def sync_candidates(
    items: list[dict[str, Any]],
    *,
    generated_at: str = "",
    slot_label: str = "",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    with _LOCK:
        _progress(
            progress_callback,
            "飞书审核表准备",
            f"正在解析目标工作表并读取全量历史；本轮传入 {len(items)} 条。",
        )
        sheet_id = ensure_sheet()
        rows = _read_rows(sheet_id)
        _validate_sheet_rows(rows, context="现有飞书审核表")
        existing_status: dict[str, tuple[str, str]] = {}
        existing_rows_by_id: dict[str, list[Any]] = {}
        existing_history_items: list[dict[str, Any]] = []
        existing_row_count = 0
        status_priority = STATUS_PRIORITY
        for index, row in enumerate(rows, start=2):
            if not row or not any(_text(value, 80) for value in row):
                continue
            existing_row_count += 1
            parsed = _row_dict(row, index)
            normalized_row = (list(row) + [""] * len(HEADERS))[: len(HEADERS)]
            previous_row = existing_rows_by_id.get(parsed["news_id"])
            if previous_row is not None:
                previous_status = _normalized_status(previous_row[0])
                if status_priority.get(parsed["status"], 0) > status_priority.get(previous_status, 0):
                    existing_rows_by_id[parsed["news_id"]] = normalized_row
                    existing_status[parsed["news_id"]] = (
                        parsed["status"],
                        parsed["sync_status"] or "未同步",
                    )
                continue
            existing_status[parsed["news_id"]] = (
                parsed["status"],
                parsed["sync_status"] or "未同步",
            )
            existing_rows_by_id[parsed["news_id"]] = normalized_row
            existing_history_items.append(parsed)
        _progress(
            progress_callback,
            "飞书历史读取",
            (
                f"已读取 {len(rows)} 行，有效历史 {existing_row_count} 条，"
                f"唯一新闻ID {len(existing_rows_by_id)} 个。"
            ),
        )
        state = _read_json(STATE_PATH, {})
        archived_news_ids = {
            _text(value, 80)
            for value in (state.get("archived_news_ids") or [])
            if _text(value, 80)
        }
        try:
            previous_candidate_count = int(state.get("last_candidate_count") or 0)
        except (TypeError, ValueError):
            previous_candidate_count = 0
        if existing_row_count < previous_candidate_count:
            raise RuntimeError(
                "审核表现有候选数少于上次同步记录，已停止追加以防止历史数据被覆盖："
                f"当前 {existing_row_count} 条，上次 {previous_candidate_count} 条"
            )
        curated_items, gate_reasons = curate_news_items(list(items))
        gate_reason_text = "、".join(
            f"{name} {count}"
            for name, count in sorted(
                gate_reasons.items(), key=lambda entry: (-entry[1], entry[0])
            )[:8]
        ) or "无"
        _progress(
            progress_callback,
            "候选确定性门禁",
            (
                f"输入 {len(items)} 条，通过 {len(curated_items)} 条，"
                f"过滤 {len(items) - len(curated_items)} 条；主要原因：{gate_reason_text}。"
            ),
        )
        candidate_gate_metadata = (
            dict(state.get(GATE_METADATA_STATE_KEY) or {})
            if isinstance(state.get(GATE_METADATA_STATE_KEY), dict)
            else {}
        )
        for item in curated_items:
            metadata_key = _gate_metadata_key(item.get("url"))
            metadata = _gate_metadata(item)
            if metadata_key and metadata:
                candidate_gate_metadata[metadata_key] = metadata
        from strategic_briefing import (
            acknowledge_deferred_ai_candidates,
            agent_semantic_deduplicate_candidates,
            load_latest_ai_review_audit,
            polish_candidates_before_review,
            unpublishable_copy_reason,
        )

        _progress(
            progress_callback,
            "AI逐条审核",
            f"开始审核 {len(curated_items)} 条门禁通过候选。",
        )
        prepared_items = (
            polish_candidates_before_review(
                curated_items,
                progress_callback=progress_callback,
            )
            if progress_callback is not None
            else polish_candidates_before_review(curated_items)
        )
        ai_review_audit = load_latest_ai_review_audit()
        ai_review_items = (
            ai_review_audit.get("review_items")
            if isinstance(ai_review_audit.get("review_items"), list)
            else []
        )
        ai_deferred_count = sum(
            1
            for review_item in ai_review_items
            if isinstance(review_item, dict)
            and review_item.get("status") == "deferred"
        )
        ai_included_count = len(prepared_items)
        semantic_search_day, semantic_history_items = _recent_semantic_history(
            existing_history_items,
            generated_at=generated_at,
            candidate_items=curated_items,
        )
        _progress(
            progress_callback,
            "AI逐条审核",
            (
                f"AI审核结束，保留 {len(prepared_items)}/{len(curated_items)} 条；"
                f"即将对 {semantic_search_day} 及前两日历史 "
                f"{len(semantic_history_items)} 条去重。"
            ),
        )
        semantic_input_items = list(prepared_items)
        semantic_result = (
            agent_semantic_deduplicate_candidates(
                prepared_items,
                semantic_history_items,
                progress_callback=progress_callback,
            )
            if progress_callback is not None
            else agent_semantic_deduplicate_candidates(
                prepared_items,
                semantic_history_items,
            )
        )
        prepared_items = semantic_result["kept"]
        semantic_decisions = {
            _text(entry.get("id"), 80): entry
            for entry in semantic_result.get("decisions") or []
            if isinstance(entry, dict) and _text(entry.get("id"), 80)
        }
        semantic_review_items: list[dict[str, Any]] = []
        ordered_semantic_decisions = [
            entry
            for entry in semantic_result.get("decisions") or []
            if isinstance(entry, dict)
        ]
        for item_index, item in enumerate(semantic_input_items):
            news_id = _text(item.get("news_id"), 80)
            decision = semantic_decisions.get(news_id) or (
                ordered_semantic_decisions[item_index]
                if item_index < len(ordered_semantic_decisions)
                else {}
            )
            is_duplicate = decision.get("is_duplicate") is True
            is_deferred = decision.get("is_deferred") is True
            semantic_review_items.append(
                {
                    "news_id": news_id,
                    "title": _text(item.get("ai_title") or item.get("title"), 500),
                    "summary": _text(
                        item.get("ai_summary") or item.get("summary") or item.get("snippet"),
                        1200,
                    ),
                    "source": _text(item.get("source") or item.get("source_domain"), 160),
                    "url": _text(item.get("url") or item.get("source_url"), 1600),
                    "published_at": _text(
                        item.get("published_at") or item.get("source_date"), 80
                    ),
                    "status": (
                        "deferred"
                        if is_deferred
                        else "duplicate" if is_duplicate else "kept"
                    ),
                    "duplicate_of": _text(decision.get("duplicate_of"), 80),
                    "reason": _text(
                        decision.get("reason")
                        or "本轮去重归档未保存逐条理由。",
                        1000,
                    ),
                    "errors": [
                        _text(error, 300) for error in decision.get("errors") or []
                    ],
                }
            )
        # Final gate before human-facing rows. The AI layer already recovers or
        # rejects leaked prompt text and programme listings, so anything caught
        # here is an unseen model failure: block it and let monitoring alert
        # instead of writing it into the sheet people review.
        blocked_dirty_copy: list[dict[str, str]] = []
        publishable_items: list[dict[str, Any]] = []
        for item in prepared_items:
            dirty_reason = unpublishable_copy_reason(
                item.get("ai_title") or item.get("title"),
                item.get("ai_summary") or item.get("summary"),
            )
            if dirty_reason:
                blocked_dirty_copy.append(
                    {
                        "news_id": _text(item.get("news_id"), 80),
                        "title": _text(item.get("ai_title") or item.get("title"), 240),
                        "reason": dirty_reason,
                    }
                )
                continue
            publishable_items.append(item)
        prepared_items = publishable_items
        if blocked_dirty_copy:
            logging.error(
                "审核表写入前拦截 %s 条不可发布文案：%s",
                len(blocked_dirty_copy),
                "；".join(
                    f"{entry['reason']}（{entry['title'][:40]}）"
                    for entry in blocked_dirty_copy[:3]
                ),
            )
        finalized_ai_items = [
            *prepared_items,
            *[
                entry["item"]
                for entry in semantic_result["duplicates"]
                if isinstance(entry, dict) and isinstance(entry.get("item"), dict)
            ],
            *[
                entry["item"]
                for entry in semantic_result["deferred"]
                if isinstance(entry, dict) and isinstance(entry.get("item"), dict)
            ],
        ]
        _progress(
            progress_callback,
            "新增候选组装",
            (
                f"去重后保留 {len(prepared_items)} 条；重复 "
                f"{len(semantic_result['duplicates'])} 条，延期 "
                f"{len(semantic_result['deferred'])} 条。"
            ),
        )
        archived_count = len(existing_rows_by_id)
        new_values: list[list[Any]] = []
        new_count = 0
        new_category_counts: Counter[str] = Counter()
        new_region_counts: Counter[str] = Counter()
        new_sources: set[str] = set()
        new_items: list[dict[str, Any]] = []
        for item in prepared_items:
            news_id = _text(item.get("news_id"), 80)
            if not news_id:
                news_id = _news_item_id(
                    item.get("url") or item.get("source_url"),
                    item.get("ai_title") or item.get("title"),
                )
            if news_id in existing_rows_by_id or news_id in archived_news_ids:
                continue
            value = _candidate_row(item, generated_at)
            new_count += 1
            new_category_counts[_text(item.get("category") or "未分类", 80)] += 1
            new_region_counts[_text(item.get("region") or "未分类", 80)] += 1
            source = _text(item.get("source") or item.get("source_domain"), 160)
            if source:
                new_sources.add(source)
            new_items.append(
                {
                    "news_id": news_id,
                    "title": _text(item.get("ai_title") or item.get("title"), 500),
                    "summary": _text(
                        item.get("ai_summary")
                        or item.get("summary")
                        or item.get("snippet"),
                        1000,
                    ),
                    "category": _text(item.get("category") or "未分类", 80),
                    "region": _text(item.get("region") or "未分类", 80),
                    "source": source,
                    "published_at": _text(
                        item.get("published_at")
                        or item.get("source_date")
                        or item.get("publication_date"),
                        80,
                    ),
                    "url": _text(
                        item.get("url") or item.get("source_url"),
                        1600,
                    ),
                    "inclusion_reason": _text(
                        item.get("ai_inclusion_reason")
                        or item.get("inclusion_reason")
                        or item.get("why"),
                        1000,
                    ),
                    "business_impact": _text(
                        item.get("ai_business_impact")
                        or item.get("business_impact"),
                        120,
                    ),
                }
            )
            new_values.append(value)
            existing_status[news_id] = (value[0], value[2])
        new_values.sort(key=lambda row: str(row[3] or ""), reverse=True)
        live_sheet = _refresh_live_review_sheet(
            sheet_id,
            existing_rows_by_id,
            existing_status,
            progress_callback=progress_callback,
        )
        rescued_decisions = live_sheet["rescued"]
        live_ids = set(live_sheet["rows_by_id"])
        committed_new_values: list[list[Any]] = []
        committed_new_items: list[dict[str, Any]] = []
        for value, item in zip(new_values, new_items):
            news_id = _text(item.get("news_id"), 80) or _row_dict(value, 2)["news_id"]
            if not news_id or news_id in live_ids:
                continue
            committed_new_values.append(value)
            committed_new_items.append(item)
            live_ids.add(news_id)
        dropped_already_present = len(new_values) - len(committed_new_values)
        new_values = committed_new_values
        new_items = committed_new_items
        new_count = len(new_values)
        if dropped_already_present:
            logging.warning(
                "增量写入前跳过 %s 条已在审核表中的候选，避免覆盖人工审核",
                dropped_already_present,
            )
        candidate_count = live_sheet["physical_count"] + new_count
        separator_count = _batch_separator_count(new_values, live_sheet["rows"])
        incoming_row_span = new_count + separator_count
        workbook_info = _spreadsheet_info()
        decision = capacity_decision(
            used_rows=live_sheet["row_span"] + 1,
            incoming_rows=incoming_row_span,
            column_count=len(HEADERS),
            sheet_count=len(_sheet_items(workbook_info)),
            operational_max_rows=MAX_SHEET_ROWS,
            soft_limit_ratio=ROLLOVER_SOFT_LIMIT_RATIO,
        )
        if decision.should_rollover:
            sheet_id, state = _rollover_review_sheet(
                current_sheet_id=sheet_id,
                current_rows_by_id=live_sheet["rows_by_id"],
                decision=decision,
            )
            archived_news_ids.update(live_sheet["rows_by_id"])
            live_sheet = {
                "rescued": rescued_decisions,
                "rows": [],
                "rows_by_id": {},
                "physical_count": 0,
                "row_span": 0,
            }
            candidate_count = new_count
            separator_count = 0
            incoming_row_span = new_count
            _progress(
                progress_callback,
                "飞书容量分卷",
                f"旧候选池已达安全阈值，已切换到时间分卷 {state.get('sheet_title')}。",
            )
        if incoming_row_span > MAX_SHEET_ROWS - 1:
            raise RuntimeError(
                f"新分卷单批连同分隔行即超过 {MAX_SHEET_ROWS - 1} 行上限"
            )
        _validate_sheet_rows(new_values, context="待追加飞书审核表")
        if new_values:
            if live_sheet["physical_count"] > 0:
                _progress(
                    progress_callback,
                    "飞书分批写入",
                    (
                        f"在表头下插入 {len(new_values)} 条新闻和 "
                        f"{separator_count} 行分隔，不改动已有 "
                        f"{live_sheet['physical_count']} 条新闻。"
                    ),
                )
                _insert_rows(
                    sheet_id,
                    incoming_row_span,
                    start_index=1,
                    separator_count=separator_count,
                )
            total_chunks = (len(new_values) + 39) // 40
            for offset in range(0, len(new_values), 40):
                chunk = new_values[offset : offset + 40]
                start_row = 2 + offset
                chunk_end = start_row + len(chunk) - 1
                _progress(
                    progress_callback,
                    "飞书分批写入",
                    (
                        f"写入第 {offset // 40 + 1}/{total_chunks} 批新增，"
                        f"范围 A{start_row}:N{chunk_end}，共 {len(chunk)} 行。"
                    ),
                )
                _write(sheet_id, f"A{start_row}:N{chunk_end}", chunk)
        else:
            _progress(
                progress_callback,
                "飞书分批写入",
                "本轮无新增候选，跳过写表以保护已有人工审核结果。",
            )
        expected_new_rows = [_comparable_sheet_row(row) for row in new_values]
        actual_new_rows: list[list[str]] = []
        written_rows: list[list[Any]] = []
        for readback_attempt in range(1, 5):
            _progress(
                progress_callback,
                "飞书逐格回读",
                (
                    f"第 {readback_attempt}/4 次回读，校验新增 "
                    f"{len(new_values)} 行，并确认已有候选仍在表中。"
                ),
            )
            written_rows = _read_rows(sheet_id)
            actual_new_rows = [
                _comparable_sheet_row(row)
                for row in written_rows[: len(new_values)]
            ]
            written_ids = {
                _row_dict(row, index)["news_id"]
                for index, row in enumerate(written_rows, start=2)
                if row and any(_text(value, 80) for value in row)
            }
            existing_still_present = live_sheet["rows_by_id"].keys() <= written_ids
            if actual_new_rows == expected_new_rows and existing_still_present:
                _progress(
                    progress_callback,
                    "飞书逐格回读",
                    (
                        f"第 {readback_attempt} 次回读通过：新增 {len(new_values)} 行一致，"
                        f"已有 {len(live_sheet['rows_by_id'])} 条候选仍在表中。"
                    ),
                )
                break
            if readback_attempt < 4:
                time.sleep(readback_attempt)
        written_ids = {
            _row_dict(row, index)["news_id"]
            for index, row in enumerate(written_rows, start=2)
            if row and any(_text(value, 80) for value in row)
        }
        if actual_new_rows != expected_new_rows:
            first_difference = "新增行数不一致"
            for row_index, (expected, actual) in enumerate(
                zip(expected_new_rows, actual_new_rows),
                start=2,
            ):
                if expected == actual:
                    continue
                for column_index, (expected_cell, actual_cell) in enumerate(
                    zip(expected, actual)
                ):
                    if expected_cell != actual_cell:
                        first_difference = (
                            f"第{row_index}行第{column_index + 1}列，"
                            f"期望“{_text(expected_cell, 80)}”，"
                            f"实际“{_text(actual_cell, 80)}”"
                        )
                        break
                break
            raise RuntimeError(
                "飞书审核表新增行回读不一致，已停止后续处理并保留错误现场："
                + first_difference
            )
        missing_existing = [
            news_id
            for news_id in live_sheet["rows_by_id"]
            if news_id not in written_ids
        ]
        if missing_existing:
            raise RuntimeError(
                "飞书审核表增量写入后丢失已有候选，已停止后续处理并保留错误现场："
                f"缺失 {len(missing_existing)} 条"
            )
        candidate_count = sum(
            1
            for row in written_rows
            if row and any(_text(value, 80) for value in row)
        )
        active_metadata_keys = {
            _gate_metadata_key(row[10])
            for row in written_rows
            if row and _gate_metadata_key(row[10])
        }
        candidate_gate_metadata = {
            key: metadata
            for key, metadata in candidate_gate_metadata.items()
            if key in active_metadata_keys and isinstance(metadata, dict)
        }
        state.update(
            {
                "sheet_id": sheet_id,
                "sheet_url": _sheet_url(sheet_id),
                "last_source_generated_at": generated_at,
                "last_slot_label": slot_label,
                "last_candidate_count": candidate_count,
                "last_batch_count": len(items),
                "last_archived_count": archived_count,
                "last_gate_filtered_count": len(items) - len(curated_items),
                "last_gate_filtered_reasons": dict(gate_reasons),
                "last_dirty_copy_blocked_count": len(blocked_dirty_copy),
                "last_dirty_copy_blocked": blocked_dirty_copy[:10],
                "last_rescued_decision_count": len(rescued_decisions),
                "last_rescued_decisions": rescued_decisions[:10],
                "last_existing_rows_untouched": True,
                "last_new_count": new_count,
                "last_new_category_counts": dict(new_category_counts),
                "last_new_region_counts": dict(new_region_counts),
                "last_new_source_count": len(new_sources),
                "last_ai_included_count": ai_included_count,
                "last_ai_deferred_count": ai_deferred_count,
                "last_ai_processed_count": len(prepared_items),
                "last_semantic_duplicate_count": len(semantic_result["duplicates"]),
                "last_semantic_deferred_count": len(semantic_result["deferred"]),
                "last_semantic_history_count": semantic_result["history_count"],
                "last_semantic_history_shards": semantic_result["history_shards"],
                "last_semantic_history_scope": "hkt_search_day_and_previous_2_days",
                "last_semantic_search_day": semantic_search_day,
                GATE_METADATA_STATE_KEY: candidate_gate_metadata,
                "last_sync_at": _now_iso(),
                "group_notifications_paused": _group_notifications_paused(),
            }
        )
        _write_json(STATE_PATH, state)
        deferred_ack = acknowledge_deferred_ai_candidates(finalized_ai_items)
        return {
            "sheet_id": sheet_id,
            "sheet_url": _sheet_url(sheet_id),
            "readback_verified": True,
            "candidate_count": candidate_count,
            "batch_count": len(items),
            "ai_included_count": ai_included_count,
            "ai_deferred_count": ai_deferred_count,
            "ai_review_items": ai_review_items,
            "archived_count": archived_count,
            "gate_filtered_count": len(items) - len(curated_items),
            "gate_filtered_reasons": dict(gate_reasons),
            "dirty_copy_blocked_count": len(blocked_dirty_copy),
            "dirty_copy_blocked": blocked_dirty_copy[:10],
            "rescued_decision_count": len(rescued_decisions),
            "rescued_decisions": rescued_decisions[:10],
            "existing_rows_untouched": True,
            "new_count": new_count,
            "new_category_counts": dict(new_category_counts),
            "new_region_counts": dict(new_region_counts),
            "new_source_count": len(new_sources),
            "new_items": new_items,
            "existing_count": len(existing_status),
            "semantic_duplicate_count": len(semantic_result["duplicates"]),
            "semantic_review_items": semantic_review_items,
            "semantic_deferred_count": len(semantic_result["deferred"]),
            "deferred_count": (
                ai_deferred_count + len(semantic_result["deferred"])
            ),
            "semantic_history_count": semantic_result["history_count"],
            "semantic_history_shards": semantic_result["history_shards"],
            "semantic_history_scope": "hkt_search_day_and_previous_2_days",
            "semantic_search_day": semantic_search_day,
            "semantic_audit_id": semantic_result.get("audit_id", ""),
            "deferred_delivery_ack": deferred_ack,
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
    source_url = _cell_link(padded[10], 1600)
    news_id = _news_item_id(source_url, padded[6])
    return {
        "row_number": row_number,
        "status": _normalized_status(padded[0]),
        "weekly_status": _normalized_status(padded[1]),
        "sync_status": _text(padded[2], 40),
        "search_date": _text(padded[3], 20),
        "region": _text(padded[4], 80),
        "category": _text(padded[5], 120),
        "title": _text(padded[6], 500),
        "summary": _text(padded[7], 500),
        "source": _text(padded[8], 240),
        "source_date": _text(padded[9], 40),
        "source_url": source_url,
        "keywords": _text(padded[11], 1800),
        "note": _text(padded[12], 500),
        "information_flow": _text(padded[13], 300),
        "news_id": news_id,
    }


REVIEW_SHEET_EDITABLE_COLUMNS = tuple(index for index in range(len(HEADERS)) if index != 2)
REVIEW_SHEET_STATUS_OPTIONS = ("待审核", "接受", "不接受", "暂缓")


def _resolved_review_sheet_id(sheet_id: str | None = None) -> str:
    if sheet_id:
        return sheet_id
    state = _read_json(STATE_PATH, {})
    saved_sheet_id = _text(state.get("sheet_id"), 120) if isinstance(state, dict) else ""
    return saved_sheet_id or ensure_sheet()


def review_sheet_snapshot(*, sheet_id: str | None = None) -> dict[str, Any]:
    """Return a live, browser-safe view of the Feishu review worksheet."""
    lock_acquired = _LOCK.acquire(timeout=1.0)
    if not lock_acquired:
        raise RuntimeError("后台战略新闻任务正在更新飞书审核表，请稍后刷新")
    try:
        resolved_sheet_id = _resolved_review_sheet_id(sheet_id)
        rows = _read_rows(resolved_sheet_id)
        state = _read_json(STATE_PATH, {})
        return {
            "sheetId": resolved_sheet_id,
            "sheetTitle": _text(state.get("sheet_title"), 100) or SHEET_TITLE,
            "sheetUrl": _sheet_url(resolved_sheet_id),
            "headers": list(HEADERS),
            "editableColumns": list(REVIEW_SHEET_EDITABLE_COLUMNS),
            "statusOptions": list(REVIEW_SHEET_STATUS_OPTIONS),
            "updatedAt": _now_iso(),
            "rows": [
                {
                    "rowNumber": row_number,
                    "values": _comparable_sheet_row(row),
                }
                for row_number, row in enumerate(rows, start=2)
                if row and any(_text(value, 80) for value in row)
            ],
        }
    finally:
        _LOCK.release()


def _column_name(index: int) -> str:
    if index < 0 or index >= 26:
        raise ValueError("列编号超出支持范围")
    return chr(ord("A") + index)


def update_review_sheet_cells(
    changes: list[dict[str, Any]],
    *,
    sheet_id: str | None = None,
) -> dict[str, Any]:
    """Write reviewed cells to Feishu, apply decisions, and prove them by readback."""
    if not isinstance(changes, list) or not changes:
        raise ValueError("没有需要保存的单元格")
    if len(changes) > 200:
        raise ValueError("单次最多保存 200 个单元格")

    with _LOCK, _review_process_lock(wait=False) as process_lock_acquired:
        if not process_lock_acquired:
            raise RuntimeError("审核表正在同步，请稍后重试")
        resolved_sheet_id = _resolved_review_sheet_id(sheet_id)
        current_rows = _read_rows(resolved_sheet_id)
        normalized: dict[tuple[int, int], dict[str, Any]] = {}
        for raw_change in changes:
            if not isinstance(raw_change, dict):
                raise ValueError("单元格更新格式无效")
            row_number = int(raw_change.get("rowNumber") or 0)
            column_index = int(raw_change.get("columnIndex", -1))
            if row_number < 2 or row_number > MAX_SHEET_ROWS:
                raise ValueError(f"第 {row_number} 行超出审核表范围")
            if column_index not in REVIEW_SHEET_EDITABLE_COLUMNS:
                raise ValueError("同步状态列由系统维护，不能手工修改")
            row_offset = row_number - 2
            if row_offset >= len(current_rows):
                raise ValueError(f"第 {row_number} 行不存在，已停止写入")
            current = _comparable_sheet_row(current_rows[row_offset])[column_index]
            expected = raw_change.get("before")
            if expected is not None and _text(expected, 5000) != current:
                raise RuntimeError(
                    f"第 {row_number} 行“{HEADERS[column_index]}”已被其他用户修改，请刷新后重试"
                )
            value = _text(raw_change.get("value"), 5000)
            if column_index in {0, 1}:
                value = _normalized_status(value)
                if value not in REVIEW_SHEET_STATUS_OPTIONS:
                    raise ValueError(f"无效审核状态：{value}")
            if column_index == 10 and value and not value.lower().startswith(("http://", "https://")):
                raise ValueError("原文链接必须以 http:// 或 https:// 开头")
            normalized[(row_number, column_index)] = {
                "rowNumber": row_number,
                "columnIndex": column_index,
                "before": current,
                "value": value,
            }

        changed = [item for item in normalized.values() if item["value"] != item["before"]]
        if not changed:
            snapshot = review_sheet_snapshot(sheet_id=resolved_sheet_id)
            return {"changedCount": 0, "review": {}, **snapshot}

        # Coalesce adjacent cells on the same row so rectangular Excel pastes do
        # not produce one network request per cell.
        by_row: dict[int, list[dict[str, Any]]] = {}
        for item in changed:
            by_row.setdefault(item["rowNumber"], []).append(item)
        for row_number, row_changes in sorted(by_row.items()):
            row_changes.sort(key=lambda item: item["columnIndex"])
            segment: list[dict[str, Any]] = []
            segments: list[list[dict[str, Any]]] = []
            for item in row_changes:
                if segment and item["columnIndex"] != segment[-1]["columnIndex"] + 1:
                    segments.append(segment)
                    segment = []
                segment.append(item)
            if segment:
                segments.append(segment)
            for items in segments:
                start_column = _column_name(items[0]["columnIndex"])
                end_column = _column_name(items[-1]["columnIndex"])
                _write(
                    resolved_sheet_id,
                    f"{start_column}{row_number}:{end_column}{row_number}",
                    [[item["value"] for item in items]],
                )

        review_result = apply_reviews(resolved_sheet_id)
        snapshot = review_sheet_snapshot(sheet_id=resolved_sheet_id)
        readback = {
            (row["rowNumber"], column_index): row["values"][column_index]
            for row in snapshot["rows"]
            for column_index in range(len(HEADERS))
        }
        mismatches = [
            item
            for item in changed
            if readback.get((item["rowNumber"], item["columnIndex"])) != item["value"]
        ]
        if mismatches:
            first = mismatches[0]
            raise RuntimeError(
                f"第 {first['rowNumber']} 行“{HEADERS[first['columnIndex']]}”回读不一致，未确认保存成功"
            )
        return {
            "changedCount": len(changed),
            "readbackVerified": True,
            "review": review_result,
            **snapshot,
        }


def load_weekly_report_candidates(
    window_start: str,
    window_end: str,
    *,
    sheet_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load only manually approved weekly-report rows inside one report window."""
    start = _publication_date(window_start)
    end = _publication_date(window_end)
    if not start or not end or start > end:
        raise ValueError("双周报时间窗口必须提供有效的开始和结束日期")
    resolved_sheet_id = sheet_id or ensure_sheet()
    rows = [
        _row_dict(row, index)
        for index, row in enumerate(_read_rows(resolved_sheet_id), start=2)
        if row and any(_text(value, 80) for value in row)
    ]
    accepted = [row for row in rows if row["weekly_status"] == "接受"]
    included: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    invalid_rows: list[str] = []
    seen: set[str] = set()
    for row in accepted:
        publication_date = _publication_date(row["source_date"])
        if not publication_date:
            reasons["date_missing"] += 1
            continue
        if publication_date < start or publication_date > end:
            reasons["out_of_window"] += 1
            continue
        missing = [
            label
            for label, value in (
                ("新闻标题", row["title"]),
                ("内容简介", row["summary"]),
                ("来源媒体", row["source"]),
                ("原文链接", row["source_url"]),
            )
            if not _text(value, 1600)
        ]
        if missing or not row["source_url"].lower().startswith(("http://", "https://")):
            if not row["source_url"].lower().startswith(("http://", "https://")):
                missing.append("有效原文链接")
            invalid_rows.append(
                f"第{row['row_number']}行缺少{'、'.join(dict.fromkeys(missing))}"
            )
            reasons["invalid"] += 1
            continue
        identity = row["news_id"]
        if identity in seen:
            reasons["duplicate"] += 1
            continue
        seen.add(identity)
        item = dict(row)
        item["publication_date"] = publication_date
        included.append(item)
        reasons["included"] += 1
    if invalid_rows:
        raise ValueError("已选择纳入周报的行不完整：" + "；".join(invalid_rows))
    included.sort(
        key=lambda row: (row["publication_date"], row["row_number"]),
        reverse=True,
    )
    return included, {
        "selectionSource": SHEET_SOURCE,
        "sheetId": resolved_sheet_id,
        "sheetUrl": _sheet_url(resolved_sheet_id),
        "windowStart": start,
        "windowEnd": end,
        "sheetRows": len(rows),
        "acceptedRows": len(accepted),
        "includedRows": len(included),
        "excludedRows": len(accepted) - len(included),
        "reasons": dict(reasons),
    }


def apply_reviews(sheet_id: str | None = None) -> dict[str, Any]:
    with _LOCK:
        sheet_id = sheet_id or ensure_sheet()
        state = _read_json(STATE_PATH, {})
        candidate_gate_metadata = (
            state.get(GATE_METADATA_STATE_KEY)
            if isinstance(state, dict)
            and isinstance(state.get(GATE_METADATA_STATE_KEY), dict)
            else {}
        )
        rows = [
            _row_dict(row, index)
            for index, row in enumerate(_read_rows(sheet_id), start=2)
            if row and any(_text(value, 80) for value in row[:2])
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
            metadata = candidate_gate_metadata.get(
                _gate_metadata_key(row["source_url"]),
                {},
            )
            if not isinstance(metadata, dict):
                metadata = {}
            gate_item = {
                "title": row["title"],
                "snippet": f"{row['summary']} {row['keywords']} {row['note']}",
                "source": row["source"],
                "url": row["source_url"],
                "keywords": row["keywords"],
                "source_date": row["source_date"],
                "published_at": metadata.get("published_at") or row["source_date"],
                "search_date": row["search_date"],
                "search_window_start": metadata.get("search_window_start"),
                "search_window_end": metadata.get("search_window_end"),
                "search_origin": metadata.get("search_origin"),
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
                    "information_flow": row["information_flow"],
                    "published_at": metadata.get("published_at") or row["source_date"],
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
        blocked_reviews: list[dict[str, Any]] = []
        for row in rows:
            blocked_reason = blocked_rows.get(row["row_number"])
            if blocked_reason:
                blocked_reviews.append(
                    {
                        "row_number": row["row_number"],
                        "news_id": row["news_id"],
                        "title": row["title"],
                        "reason": blocked_reason,
                    }
                )
                if row["sync_status"] != "同步失败":
                    _write(
                        sheet_id,
                        f"C{row['row_number']}:C{row['row_number']}",
                        [["同步失败"]],
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
                    f"C{row['row_number']}:C{row['row_number']}",
                    [[desired_sync]],
                )
                changed_rows += 1
        return {
            "accepted_count": len(accepted_items),
            "requested_accept_count": len(accepted_rows),
            "blocked_accept_count": len(blocked_rows),
            "blocked_reviews": blocked_reviews,
            "pending_count": sum(row["status"] == "待审核" for row in rows),
            "deferred_count": sum(row["status"] == "暂缓" for row in rows),
            "rejected_count": sum(row["status"] == "不接受" for row in rows),
            "weekly_accepted_count": sum(
                row["weekly_status"] == "接受" for row in rows
            ),
            "weekly_pending_count": sum(
                row["weekly_status"] == "待审核" for row in rows
            ),
            "published_count": len(combined),
            "changed_rows": changed_rows,
        }

def _crawl_item_id(*parts: Any) -> str:
    import hashlib

    raw = "\n".join(str(part or "") for part in parts)
    return "CRAWL-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _latest_crawl_results() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    roots = [
        Path(__file__).resolve().parents[2] / "curation_data" / "backups",
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

def _canonical_news_url(value: Any) -> str:
    text = _text(value, 1800)
    try:
        parsed = urlparse(text)
    except ValueError:
        return text
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"fbclid", "gclid", "oc"}
        ),
        doseq=True,
    )
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            query,
            "",
        )
    )


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


def _review_news_candidate(item: dict[str, Any]) -> tuple[bool, str]:
    title = _text(item.get("title"), 500)
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
        published_at = _timestamp_hkt(
            item.get("published_at") or item.get("source_date")
        )
        window_start = _timestamp_hkt(item.get("search_window_start"))
        window_end = _timestamp_hkt(item.get("search_window_end"))
        search_origin = _text(item.get("search_origin"), 100)
        is_news_search = (
            search_origin.startswith("agentic_")
            or search_origin
            in {
                "background_fixed_keywords",
                "mandatory_local_competitor",
                "monitoring_sheet_keyword_search",
            }
        )
        if (
            is_news_search
            and window_start
            and window_end
            and (
                window_end < window_start
                or (window_end - window_start).total_seconds() > 36 * 3600
            )
        ):
            return False, "新闻搜索入库窗口异常"
        if not (
            published_at
            and window_start
            and window_end
            and window_start <= published_at <= window_end
        ):
            return False, "不在明确检索时间窗口"
    title_years = {int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", title)}
    if title_years and int(search_date[:4]) not in title_years and max(title_years) < int(search_date[:4]):
        return False, "标题显示旧年份"
    url_date_hint = _url_publication_hint(url)
    if url_date_hint and not source_date.startswith(url_date_hint):
        return False, "原文路径日期与发布时间不符"
    item["source_date"] = source_date
    item["search_date"] = search_date
    return True, "待AI审核"


def curate_news_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    kept: dict[str, dict[str, Any]] = {}
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
        if not url_key or not title_key or url_key in kept:
            reasons["重复新闻"] += 1
            continue
        if _text(item.get("ai_region"), 20) in {"香港本地", "国际/行业"}:
            item["region"] = _text(item.get("ai_region"), 20)
        else:
            item.pop("region", None)
        item["category"] = _text(
            item.get("ai_category")
            or item.get("category")
            or item.get("module")
            or "待AI审核",
            80,
        )
        item["filter_reason"] = reason
        item["news_id"] = _news_item_id(item.get("url"), item.get("title"))
        kept[url_key] = item
    result = list(kept.values())
    result.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            str(item.get("source_date") or ""),
            str(item.get("title") or ""),
        )
    )
    return result, reasons


def _load_curated_latest(
    *,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = _news_source_paths()
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
    curated, reasons = curate_news_items(combined) if combined else ([], Counter())
    current_urls = {
        _canonical_news_url(item.get("url"))
        for item in curated
        if _canonical_news_url(item.get("url"))
    }
    current_result_count = sum(
        1
        for item in curated
        if _canonical_news_url(item.get("url")) in current_urls
    )
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
        "filtered_count": max(0, len(combined) - current_result_count),
        "filtered_reasons": dict(reasons),
        "category_counts": dict(category_counts),
        "region_counts": dict(region_counts),
        "source_count": len(sources),
        "source_path": ", ".join(source_paths),
        "group_notifications_paused": _group_notifications_paused(),
    }


def _news_source_paths() -> list[Path]:
    return [
        LATEST_PATH,
        Path("/Users/liaowang/cmhk_public_crawl_app/strategy_briefing/news_discovery_latest.json"),
        STATE_PATH.parent / "news_discovery_full.json",
        Path("/Users/liaowang/cmhk_public_crawl_app/strategy_briefing/news_discovery_full.json"),
    ]


def _current_source_generated_at() -> str:
    seen_paths: set[str] = set()
    for path in _news_source_paths():
        path_key = str(path)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        payload = _read_json(path, {})
        items = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(items, list) or not items:
            continue
        return _text(payload.get("generated_at"), 60)
    return ""

def run_cycle(
    *,
    force: bool = False,
    schedule_dashboard_publish: bool = True,
    idempotency_key: str = "",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    lock_started = time.monotonic()
    _progress(
        progress_callback,
        "审核进程锁",
        f"正在等待审核进程锁；force={force}，幂等键={_text(idempotency_key, 120) or '无'}。",
    )
    with _LOCK, _review_process_lock(wait=force) as process_lock_acquired:
        if not process_lock_acquired:
            return {
                "status": "busy",
                "reason": "another_review_process_is_running",
            }
        _progress(
            progress_callback,
            "审核进程锁",
            f"已取得锁，等待 {time.monotonic() - lock_started:.2f} 秒。",
        )
        state = _read_json(STATE_PATH, {})
        now_epoch = time.time()
        if not force and now_epoch - float(state.get("last_poll_epoch") or 0) < POLL_SECONDS:
            return {"status": "throttled", "sheet_url": state.get("sheet_url") or ""}
        cycle_key = _text(idempotency_key, 120)
        successful_cycles = state.get(SUCCESSFUL_CYCLE_RESULTS_STATE_KEY)
        if not isinstance(successful_cycles, dict):
            successful_cycles = {}
        cached_cycle = successful_cycles.get(cycle_key) if cycle_key else None
        if (
            isinstance(cached_cycle, dict)
            and cached_cycle.get("status") == "ok"
            and cached_cycle.get("readback_verified") is True
        ):
            _progress(
                progress_callback,
                "幂等结果复用",
                "已找到同一时段且逐格回读成功的结果，直接复用，不重复审核和写表。",
            )
            return {
                **cached_cycle,
                "status": "ok",
                "source_unchanged": True,
                "reused_verified_result": True,
                "dashboard_publish": {
                    "status": "deferred_reused_verified_result"
                },
            }
        source_generated_at = _current_source_generated_at()
        pending_cycle = state.get(PENDING_CYCLE_STATE_KEY)
        if not isinstance(pending_cycle, dict):
            pending_cycle = {}
        if cycle_key:
            pending_cycle = {
                "key": cycle_key,
                "source_generated_at": source_generated_at,
                "recorded_at": _now_iso(),
            }
            state[PENDING_CYCLE_STATE_KEY] = pending_cycle
            _write_json(STATE_PATH, state)
        elif (
            _text(pending_cycle.get("key"), 120)
            and source_generated_at
            and source_generated_at
            == _text(pending_cycle.get("source_generated_at"), 60)
        ):
            cycle_key = _text(pending_cycle.get("key"), 120)
        from strategic_briefing import has_pending_ai_candidates

        source_unchanged = (
            not force
            and not has_pending_ai_candidates()
            and bool(source_generated_at)
            and source_generated_at
            == _text(state.get("last_source_generated_at"), 60)
            and bool(_text(state.get("sheet_id"), 80))
        )
        try:
            if source_unchanged:
                latest = (
                    state.get("last_source_summary")
                    if isinstance(state.get("last_source_summary"), dict)
                    else {}
                )
                sync_result = {
                    "sheet_id": _text(state.get("sheet_id"), 80),
                    "sheet_url": _text(state.get("sheet_url"), 1600),
                    "candidate_count": int(state.get("last_candidate_count") or 0),
                    "new_count": 0,
                    "new_items": [],
                    "semantic_duplicate_count": 0,
                    "semantic_deferred_count": 0,
                }
            else:
                _progress(
                    progress_callback,
                    "候选源汇总",
                    "正在读取新闻发现池、运行时候选和延期记录并做入口门禁。",
                )
                items, latest = (
                    _load_curated_latest(progress_callback=progress_callback)
                    if progress_callback is not None
                    else _load_curated_latest()
                )
                _progress(
                    progress_callback,
                    "候选源汇总",
                    (
                        f"原始汇总 {int(latest.get('input_count') or 0)} 条，"
                        f"入口后 {len(items)} 条，来自 "
                        f"{int(latest.get('source_count') or 0)} 个来源。"
                    ),
                )
                sync_result = sync_candidates(
                    items,
                    generated_at=_text(latest.get("generated_at"), 40),
                    slot_label=_text(latest.get("slot_label"), 80),
                    progress_callback=progress_callback,
                )
            _progress(
                progress_callback,
                "人工审核状态同步",
                "正在读取飞书中的接受、不接受、暂缓状态，更新APP发布池及同步标记。",
            )
            review_result = apply_reviews(sync_result["sheet_id"])
            _progress(
                progress_callback,
                "人工审核状态同步",
                (
                    f"已同步：请求接受 {int(review_result.get('requested_accept_count') or 0)} 条，"
                    f"实际纳入 {int(review_result.get('accepted_count') or 0)} 条，"
                    f"阻断 {int(review_result.get('blocked_accept_count') or 0)} 条，"
                    f"待审 {int(review_result.get('pending_count') or 0)} 条，"
                    f"更新同步状态 {int(review_result.get('changed_rows') or 0)} 行。"
                ),
            )
        except Exception as exc:
            state["last_poll_error"] = _text(exc, 600)
            state["last_poll_error_at"] = _now_iso()
            state["last_poll_status"] = "failed"
            _write_json(STATE_PATH, state)
            raise
        state = _read_json(STATE_PATH, {})
        state.update(
            {
                "last_poll_epoch": now_epoch,
                "last_poll_at": _now_iso(),
                "last_poll_result": review_result,
                "last_poll_error": "",
                "last_poll_status": "ok",
                "last_source_summary": latest,
                "group_notifications_paused": _group_notifications_paused(),
            }
        )
        _write_json(STATE_PATH, state)
        dashboard_publish = (
            _schedule_public_dashboard_publish()
            if schedule_dashboard_publish
            else {"status": "deferred_until_periodic_cycle"}
        )
        cycle_result = {
            "status": "ok",
            "source_unchanged": source_unchanged,
            "dashboard_publish": dashboard_publish,
            **latest,
            **sync_result,
            **review_result,
            "source_candidate_count": int(latest.get("candidate_count") or 0),
            "sheet_candidate_count": int(sync_result.get("candidate_count") or 0),
        }
        if cycle_key and cycle_result.get("readback_verified") is True:
            state = _read_json(STATE_PATH, {})
            successful_cycles = state.get(SUCCESSFUL_CYCLE_RESULTS_STATE_KEY)
            if not isinstance(successful_cycles, dict):
                successful_cycles = {}
            successful_cycles[cycle_key] = {
                **cycle_result,
                "dashboard_publish": {
                    "status": "deferred_cached_result"
                },
                "verified_at": _now_iso(),
            }
            state[SUCCESSFUL_CYCLE_RESULTS_STATE_KEY] = dict(
                list(successful_cycles.items())[-MAX_SUCCESSFUL_CYCLE_RESULTS:]
            )
            pending_cycle = state.get(PENDING_CYCLE_STATE_KEY)
            if (
                isinstance(pending_cycle, dict)
                and _text(pending_cycle.get("key"), 120) == cycle_key
            ):
                state.pop(PENDING_CYCLE_STATE_KEY, None)
            _write_json(STATE_PATH, state)
        _progress(
            progress_callback,
            "审核周期完成",
            (
                f"状态 ok；源候选 {cycle_result['source_candidate_count']} 条，"
                f"写表新增 {int(cycle_result.get('new_count') or 0)} 条，"
                f"历史重复 {int(cycle_result.get('semantic_duplicate_count') or 0)} 条，"
                f"逐格回读={'通过' if cycle_result.get('readback_verified') is True else '未通过'}。"
            ),
        )
        return cycle_result


def build_notice_cards(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    del args, kwargs
    # The Agentic discovery callback only suppresses its legacy per-item cards.
    # The owning 09:00/14:00 scan invokes run_cycle(force=True) exactly once
    # after discovery completes, so syncing here would write the same batch
    # twice and make the final group summary incorrectly report zero new rows.
    return []
