from __future__ import annotations

import hashlib
import json
import re
import textwrap
from pathlib import Path
from typing import Any, Callable


HUMAN_COLUMNS: list[tuple[str, str]] = [
    ("run_time_hkt", "抓取时间（香港）"),
    ("row", "主表行号"),
    ("row_status", "抓取状态"),
    ("title", "页面标题"),
    ("result_overview", "结果概览"),
    ("content_excerpt", "抓取内容摘要（原文摘录）"),
    ("full_content", "完整原文"),
    ("extracted_fields", "命中字段"),
    ("missing_fields", "缺失字段"),
    ("entity_hits", "监测对象"),
    ("url", "原始链接"),
    ("final_url", "最终链接"),
    ("http_status", "HTTP状态"),
    ("method", "抓取方式"),
    ("elapsed_seconds", "耗时（秒）"),
    ("bytes", "数据量（字节）"),
    ("source_type", "来源类型"),
    ("source_policy", "来源政策"),
    ("jurisdiction", "司法辖区"),
    ("robots_status", "robots状态"),
    ("robots_allowed", "robots允许"),
    ("tos_status", "TOS状态"),
    ("live_fetch_status", "实时抓取状态"),
    ("cache_hit", "缓存命中"),
    ("evidence_fallback_used", "历史证据回退"),
    ("error_detail", "错误/跳过原因"),
    ("content_hash", "内容哈希"),
    ("run_time", "抓取时间（UTC）"),
]

HEADER_TO_KEY = {label: key for key, label in HUMAN_COLUMNS}
HEADER_TO_KEY.update({key: key for key, _ in HUMAN_COLUMNS})
HEADER_TO_KEY.update(
    {
        "抓取内容摘要": "content_excerpt",
        "error": "error",
        "skip_reason": "skip_reason",
        "fallback_reason": "fallback_reason",
    }
)

FULL_TEXT_SAFE_CHARS = 38000
FULL_TEXT_SHEET_TITLE = "完整原文"


def _rich_text_value(value: Any) -> str | None:
    if isinstance(value, dict) and "text" in value:
        return str(value.get("text") or "")
    if isinstance(value, list) and value and all(isinstance(item, dict) and "text" in item for item in value):
        return "".join(str(item.get("text") or "") for item in value)
    return None


def _cell_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    rich_text = _rich_text_value(value)
    if rich_text is not None:
        return rich_text.strip()
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).strip()


def _source_records(source_rows: list[Any]) -> list[dict[str, str]]:
    if not source_rows:
        return []
    if isinstance(source_rows[0], dict):
        return [{str(key): _cell_text(value) for key, value in row.items()} for row in source_rows]
    headers = [_cell_text(value) for value in source_rows[0]]
    records: list[dict[str, str]] = []
    for values in source_rows[1:]:
        if not isinstance(values, list) or not any(_cell_text(value) for value in values):
            continue
        record: dict[str, str] = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            key = HEADER_TO_KEY.get(header, header)
            record[key] = _cell_text(values[index] if index < len(values) else "")
        records.append(record)
    return records


def _load_snapshot_index(root: Path) -> tuple[dict[str, dict[str, Any]], dict[int, str]]:
    by_hash: dict[str, dict[str, Any]] = {}
    row_entities: dict[int, str] = {}
    results_dir = root / "results"
    for path in sorted(results_dir.glob("row_*.json")):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        try:
            row_no = int(result.get("row") or 0)
        except (TypeError, ValueError):
            row_no = 0
        entities = [str(value).strip() for value in result.get("entities", []) if str(value).strip()]
        if row_no and entities:
            row_entities[row_no] = "、".join(dict.fromkeys(entities))
        for record in result.get("raw_records", []):
            if not isinstance(record, dict):
                continue
            content_hash = str(record.get("content_hash") or "").strip()
            if content_hash:
                by_hash[content_hash] = record
    return by_hash, row_entities


def _clean_excerpt(text: str, limit: int = 540) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    if len(clean) > limit:
        clean = clean[: limit - 1].rstrip() + "…"
    return "\n".join(
        textwrap.wrap(
            clean,
            width=90,
            break_long_words=True,
            break_on_hyphens=False,
        )[:6]
    )


def _snapshot_excerpt(root: Path, record: dict[str, str], by_hash: dict[str, dict[str, Any]]) -> str:
    existing = _cell_text(record.get("content_excerpt"))
    if existing and "历史记录未保存正文快照" not in existing:
        return existing
    content_hash = _cell_text(record.get("content_hash"))
    snapshot = by_hash.get(content_hash) if content_hash else None
    if snapshot:
        excerpt = _clean_excerpt(str(snapshot.get("text_sample") or ""))
        if excerpt:
            return excerpt
    if re.fullmatch(r"[0-9a-fA-F]{32,128}", content_hash):
        evidence_path = root / "evidence_cache" / f"{content_hash}.txt"
        try:
            with evidence_path.open("r", encoding="utf-8", errors="replace") as handle:
                excerpt = _clean_excerpt(handle.read(4000))
        except OSError:
            excerpt = ""
        if excerpt:
            return excerpt
    reason = "；".join(
        value
        for value in (
            _cell_text(record.get("error")),
            _cell_text(record.get("skip_reason")),
            _cell_text(record.get("fallback_reason")),
            _cell_text(record.get("error_detail")),
        )
        if value
    )
    if reason:
        return "未取得正文：" + reason
    return "历史记录未保存正文快照；已保留页面标题、命中字段和内容哈希，无法准确还原原文。"


def _full_snapshot_text(root: Path, record: dict[str, str], by_hash: dict[str, dict[str, Any]]) -> str:
    existing = _cell_text(record.get("full_content"))
    if existing and not existing.startswith(("超长原文", "历史记录未保存", "未取得正文")):
        return existing
    content_hash = _cell_text(record.get("content_hash"))
    snapshot = by_hash.get(content_hash) if content_hash else None
    evidence_path = ""
    if snapshot:
        evidence_path = str(snapshot.get("evidence_path") or "")
    candidates: list[Path] = []
    if evidence_path:
        candidates.append(root / evidence_path)
    if re.fullmatch(r"[0-9a-fA-F]{32,128}", content_hash):
        candidates.append(root / "evidence_cache" / f"{content_hash}.txt")
    for path in dict.fromkeys(candidates):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            return text
    reason = _error_detail(record)
    if reason:
        return "未取得正文：" + reason
    return "历史记录未保存完整正文快照；无法准确还原原文。"


def _full_text_entries(root: Path, source_rows: list[Any]) -> dict[str, dict[str, str]]:
    records = _source_records(source_rows)
    by_hash, _ = _load_snapshot_index(root)
    entries: dict[str, dict[str, str]] = {}
    for record in records:
        content_hash = _cell_text(record.get("content_hash"))
        if not content_hash:
            continue
        full_text = _full_snapshot_text(root, record, by_hash)
        if len(full_text) <= FULL_TEXT_SAFE_CHARS or full_text.startswith(("历史记录未保存", "未取得正文")):
            continue
        entries.setdefault(
            content_hash,
            {
                "content_hash": content_hash,
                "title": _cell_text(record.get("title")),
                "url": _cell_text(record.get("url")),
                "text": full_text,
            },
        )
    return entries


def _status_label(value: str) -> str:
    status = str(value or "").strip().lower()
    if status in {"ok", "success", "successful", "成功"}:
        return "成功"
    if status in {"partial", "warning", "部分成功"}:
        return "部分成功"
    if status in {"failed", "failure", "error", "失败"}:
        return "失败"
    return value or "待检查"


def _bool_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "是"}:
        return "是"
    if normalized in {"false", "0", "no", "否"}:
        return "否"
    return value


def _error_detail(record: dict[str, str]) -> str:
    values = [
        _cell_text(record.get("error_detail")),
        _cell_text(record.get("error")),
        _cell_text(record.get("skip_reason")),
        _cell_text(record.get("fallback_reason")),
    ]
    return "；".join(dict.fromkeys(value for value in values if value))


def _overview(record: dict[str, str], status: str) -> str:
    fields = [
        value.strip()
        for value in re.split(r"[,，;；]", _cell_text(record.get("extracted_fields")))
        if value.strip()
    ]
    pieces = [status]
    http_status = _cell_text(record.get("http_status"))
    if http_status:
        pieces.append("HTTP " + http_status)
    if fields:
        pieces.append(f"命中 {len(fields)} 个字段")
    size = _cell_text(record.get("bytes"))
    if size:
        try:
            pieces.append(f"{int(float(size)):,} B")
        except ValueError:
            pieces.append(size + " B")
    return " | ".join(pieces)


def build_human_log_table(
    root: Path,
    source_rows: list[Any],
    full_content_links: dict[str, str] | None = None,
) -> list[list[str]]:
    records = _source_records(source_rows)
    if not records:
        raise RuntimeError("爬虫日志没有可整理的数据行")
    by_hash, row_entities = _load_snapshot_index(root)
    output: list[list[str]] = [[label for _, label in HUMAN_COLUMNS]]
    for source in records:
        record = dict(source)
        status = _status_label(_cell_text(record.get("row_status")))
        record["row_status"] = status
        record["result_overview"] = _cell_text(record.get("result_overview")) or _overview(record, status)
        record["content_excerpt"] = _snapshot_excerpt(root, record, by_hash)
        full_text = _full_snapshot_text(root, record, by_hash)
        content_hash = _cell_text(record.get("content_hash"))
        if len(full_text) > FULL_TEXT_SAFE_CHARS and content_hash in (full_content_links or {}):
            record["full_content"] = (
                f"超长原文，共 {len(full_text):,} 个字符；已在同一文件的“{FULL_TEXT_SHEET_TITLE}”子表无损分段。\n"
                + str((full_content_links or {})[content_hash])
            )
        else:
            record["full_content"] = full_text
        try:
            row_no = int(float(_cell_text(record.get("row")) or 0))
        except ValueError:
            row_no = 0
        snapshot = by_hash.get(_cell_text(record.get("content_hash")))
        entity_hits = _cell_text(record.get("entity_hits"))
        if not entity_hits and snapshot:
            entity_hits = "、".join(
                dict.fromkeys(str(value).strip() for value in snapshot.get("entity_hits", []) if str(value).strip())
            )
        record["entity_hits"] = entity_hits or row_entities.get(row_no, "")
        record["error_detail"] = _error_detail(record)
        for key in ("robots_allowed", "cache_hit", "evidence_fallback_used"):
            record[key] = _bool_label(_cell_text(record.get(key)))
        output.append([_cell_text(record.get(key)) for key, _ in HUMAN_COLUMNS])
    return output


def _status_ranges(table: list[list[str]], label: str, sheet_id: str) -> list[str]:
    return [f"{sheet_id}!C{index}" for index, row in enumerate(table[1:], start=2) if len(row) > 2 and row[2] == label]


def _json_from_command(output: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}\s*$", output, re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _sheet_items(info: dict[str, Any]) -> list[dict[str, Any]]:
    data = info.get("data") if isinstance(info.get("data"), dict) else info
    container = data.get("sheets") if isinstance(data.get("sheets"), dict) else {}
    items = container.get("sheets") if isinstance(container.get("sheets"), list) else []
    return [item for item in items if isinstance(item, dict)]


def _ensure_full_text_sheet(
    spreadsheet_token: str,
    run_cmd: Callable[..., str],
    lark_cli: str,
) -> dict[str, Any]:
    def load_info() -> dict[str, Any]:
        return _json_from_command(
            run_cmd(
                [lark_cli, "sheets", "+info", "--spreadsheet-token", spreadsheet_token],
                timeout=120,
            )
        )

    info = load_info()
    sheet = next((item for item in _sheet_items(info) if str(item.get("title") or "") == FULL_TEXT_SHEET_TITLE), None)
    if sheet:
        return sheet
    run_cmd(
        [
            lark_cli,
            "sheets",
            "+create-sheet",
            "--spreadsheet-token",
            spreadsheet_token,
            "--title",
            FULL_TEXT_SHEET_TITLE,
        ],
        timeout=120,
    )
    info = load_info()
    sheet = next((item for item in _sheet_items(info) if str(item.get("title") or "") == FULL_TEXT_SHEET_TITLE), None)
    if not sheet:
        raise RuntimeError("创建完整原文子表后未能回读到该子表")
    return sheet


def _write_full_text_sheet(
    *,
    spreadsheet_token: str,
    entries: dict[str, dict[str, str]],
    write_range: Callable[..., None],
    read_range: Callable[..., list[list[Any]]],
    set_style: Callable[..., None],
    run_cmd: Callable[..., str],
    lark_cli: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    if not entries:
        return {}, {"sheet_id": "", "rows": 0, "documents": 0}
    sheet = _ensure_full_text_sheet(spreadsheet_token, run_cmd, lark_cli)
    sheet_id = str(sheet.get("sheet_id") or "")
    rows: list[list[str]] = [["内容哈希", "页面标题", "原始链接", "总字符数", "分段", "完整原文"]]
    first_rows: dict[str, int] = {}
    expected_texts: dict[str, str] = {}
    for content_hash, entry in entries.items():
        text = str(entry.get("text") or "")
        chunks = [text[index : index + FULL_TEXT_SAFE_CHARS] for index in range(0, len(text), FULL_TEXT_SAFE_CHARS)]
        if not chunks:
            chunks = [""]
        first_rows[content_hash] = len(rows) + 1
        expected_texts[content_hash] = text
        for sequence, chunk in enumerate(chunks, start=1):
            rows.append(
                [
                    content_hash,
                    str(entry.get("title") or ""),
                    str(entry.get("url") or ""),
                    str(len(text)),
                    f"{sequence}/{len(chunks)}",
                    chunk,
                ]
            )
    grid = sheet.get("grid_properties") if isinstance(sheet.get("grid_properties"), dict) else {}
    row_count = int(grid.get("row_count") or 0)
    if len(rows) > row_count:
        run_cmd(
            [
                lark_cli,
                "sheets",
                "+add-dimension",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--dimension",
                "ROWS",
                "--length",
                str(len(rows) - row_count),
            ],
            timeout=120,
        )
    for offset in range(0, len(rows), 8):
        batch = rows[offset : offset + 8]
        start = offset + 1
        end = start + len(batch) - 1
        write_range(f"{sheet_id}!A{start}:F{end}", batch, spreadsheet_token=spreadsheet_token)
    set_style(
        f"{sheet_id}!A1:F1",
        {
            "backColor": "#123B5D",
            "font": {"bold": True, "foreColor": "#FFFFFF"},
            "borderType": "FULL_BORDER",
            "borderColor": "#123B5D",
        },
        spreadsheet_token=spreadsheet_token,
    )
    set_style(
        f"{sheet_id}!A2:E{len(rows)}",
        {"backColor": "#F3F8FC", "borderType": "FULL_BORDER", "borderColor": "#D7E1EA"},
        spreadsheet_token=spreadsheet_token,
    )
    set_style(
        f"{sheet_id}!F2:F{len(rows)}",
        {"backColor": "#FFFDF3", "borderType": "FULL_BORDER", "borderColor": "#E8DDA8"},
        spreadsheet_token=spreadsheet_token,
    )
    for start, end, size in ((1, 1, 180), (2, 2, 240), (3, 3, 320), (4, 5, 105), (6, 6, 620)):
        run_cmd(
            [
                lark_cli,
                "sheets",
                "+update-dimension",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--dimension",
                "COLUMNS",
                "--start-index",
                str(start),
                "--end-index",
                str(end),
                "--fixed-size",
                str(size),
            ],
            timeout=120,
        )
    run_cmd(
        [
            lark_cli,
            "sheets",
            "+update-dimension",
            "--spreadsheet-token",
            spreadsheet_token,
            "--sheet-id",
            sheet_id,
            "--dimension",
            "ROWS",
            "--start-index",
            "2",
            "--end-index",
            str(len(rows)),
            "--fixed-size",
            "160",
        ],
        timeout=120,
    )
    run_cmd(
        [
            lark_cli,
            "sheets",
            "+update-sheet",
            "--spreadsheet-token",
            spreadsheet_token,
            "--sheet-id",
            sheet_id,
            "--frozen-row-count",
            "1",
            "--frozen-col-count",
            "2",
        ],
        timeout=120,
    )
    readback = read_range(f"{sheet_id}!A1:F{len(rows)}", spreadsheet_token=spreadsheet_token)
    reconstructed: dict[str, list[str]] = {}
    for row in readback[1:]:
        content_hash = _cell_text(row[0] if row else "")
        if not content_hash:
            continue
        value = row[5] if len(row) > 5 else ""
        rich_text = _rich_text_value(value)
        reconstructed.setdefault(content_hash, []).append(rich_text if rich_text is not None else str(value))
    mismatches = [
        content_hash
        for content_hash, expected in expected_texts.items()
        if "".join(reconstructed.get(content_hash, [])) != expected
    ]
    if mismatches:
        raise RuntimeError(f"完整原文分段回读不一致：{mismatches[:5]}")
    links = {
        content_hash: (
            f"https://cmhk-try.feishu.cn/sheets/{spreadsheet_token}?sheet={sheet_id}&range=F{row_no}"
        )
        for content_hash, row_no in first_rows.items()
    }
    return links, {
        "sheet_id": sheet_id,
        "rows": len(rows) - 1,
        "documents": len(entries),
        "verified_documents": len(expected_texts) - len(mismatches),
    }


def write_and_format_crawl_log_sheet(
    *,
    root: Path,
    sheet_id: str,
    spreadsheet_token: str,
    source_rows: list[Any],
    write_range: Callable[..., None],
    read_range: Callable[..., list[list[Any]]],
    set_style: Callable[..., None],
    run_cmd: Callable[..., str],
    lark_cli: str,
) -> dict[str, Any]:
    full_text_entries = _full_text_entries(root, source_rows)
    full_content_links, full_text_result = _write_full_text_sheet(
        spreadsheet_token=spreadsheet_token,
        entries=full_text_entries,
        write_range=write_range,
        read_range=read_range,
        set_style=set_style,
        run_cmd=run_cmd,
        lark_cli=lark_cli,
    )
    table = build_human_log_table(root, source_rows, full_content_links)
    end_row = len(table)
    end_col = "AB"
    target_range = f"{sheet_id}!A1:{end_col}{end_row}"
    for offset in range(0, len(table), 8):
        batch = table[offset : offset + 8]
        start = offset + 1
        end = start + len(batch) - 1
        write_range(f"{sheet_id}!A{start}:{end_col}{end}", batch, spreadsheet_token=spreadsheet_token)

    base_styles = [
        {
            "ranges": [target_range],
            "style": {"borderType": "FULL_BORDER", "borderColor": "#D7E1EA"},
        },
        {
            "ranges": [f"{sheet_id}!A1:{end_col}1"],
            "style": {
                "backColor": "#123B5D",
                "font": {"bold": True, "foreColor": "#FFFFFF"},
                "borderType": "FULL_BORDER",
                "borderColor": "#123B5D",
            },
        },
        {"ranges": [f"{sheet_id}!A2:D{end_row}"], "style": {"backColor": "#F3F8FC"}},
        {
            "ranges": [f"{sheet_id}!E2:F{end_row}"],
            "style": {"backColor": "#FFF6D8", "borderType": "FULL_BORDER", "borderColor": "#E8C968"},
        },
        {"ranges": [f"{sheet_id}!G2:G{end_row}"], "style": {"backColor": "#FFFDF3"}},
        {"ranges": [f"{sheet_id}!H2:J{end_row}"], "style": {"backColor": "#F1F9F4"}},
        {
            "ranges": [f"{sheet_id}!C2:C{end_row}"],
            "style": {"font": {"bold": True}, "backColor": "#E8F5ED"},
        },
    ]
    status_styles = [
        (_status_ranges(table, "成功", sheet_id), "#DFF3E7", "#176B43"),
        (_status_ranges(table, "部分成功", sheet_id), "#FFF0CC", "#8A5A00"),
        (_status_ranges(table, "失败", sheet_id), "#FCE4E2", "#A33830"),
    ]
    for ranges, background, foreground in status_styles:
        if ranges:
            base_styles.append(
                {
                    "ranges": ranges,
                    "style": {"backColor": background, "font": {"bold": True, "foreColor": foreground}},
                }
            )
    try:
        run_cmd(
            [
                lark_cli,
                "sheets",
                "+batch-set-style",
                "--spreadsheet-token",
                spreadsheet_token,
                "--data",
                json.dumps(base_styles, ensure_ascii=False, separators=(",", ":")),
            ],
            timeout=180,
        )
    except Exception:
        for item in base_styles:
            for range_ref in item["ranges"]:
                set_style(range_ref, item["style"], spreadsheet_token=spreadsheet_token)

    width_specs = [
        (1, 1, 175),
        (2, 3, 88),
        (4, 4, 240),
        (5, 5, 270),
        (6, 6, 420),
        (7, 7, 520),
        (8, 9, 235),
        (10, 10, 130),
        (11, 12, 310),
        (13, 16, 105),
        (17, 22, 125),
        (23, 25, 110),
        (26, 26, 250),
        (27, 28, 180),
    ]
    for start, end, size in width_specs:
        run_cmd(
            [
                lark_cli,
                "sheets",
                "+update-dimension",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--dimension",
                "COLUMNS",
                "--start-index",
                str(start),
                "--end-index",
                str(end),
                "--fixed-size",
                str(size),
            ],
            timeout=120,
        )
    for start, end, size in ((1, 1, 42), (2, end_row, 112)):
        run_cmd(
            [
                lark_cli,
                "sheets",
                "+update-dimension",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--dimension",
                "ROWS",
                "--start-index",
                str(start),
                "--end-index",
                str(end),
                "--fixed-size",
                str(size),
            ],
            timeout=120,
        )
    run_cmd(
        [
            lark_cli,
            "sheets",
            "+update-sheet",
            "--spreadsheet-token",
            spreadsheet_token,
            "--sheet-id",
            sheet_id,
            "--frozen-row-count",
            "1",
            "--frozen-col-count",
            "3",
        ],
        timeout=120,
    )
    filter_id = ("LOG" + hashlib.sha1(f"{spreadsheet_token}:{sheet_id}".encode()).hexdigest()[:7]).upper()
    try:
        run_cmd(
            [
                lark_cli,
                "sheets",
                "+create-filter-view",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--range",
                target_range,
                "--filter-view-id",
                filter_id,
                "--filter-view-name",
                "日志筛选",
            ],
            timeout=120,
        )
    except Exception:
        pass

    readback = read_range(target_range, spreadsheet_token=spreadsheet_token)
    readback_header = [_cell_text(value) for value in (readback[0] if readback else [])]
    expected_header = [label for _, label in HUMAN_COLUMNS]
    if readback_header[: len(expected_header)] != expected_header:
        raise RuntimeError("日志表头回读不一致")
    if len(readback) != end_row:
        raise RuntimeError(f"日志回读行数 {len(readback)}，预期 {end_row}")
    excerpt_count = sum(1 for row in readback[1:] if len(row) > 5 and _cell_text(row[5]))
    if excerpt_count != end_row - 1:
        raise RuntimeError(f"抓取内容摘要回读 {excerpt_count} 行，预期 {end_row - 1}")
    full_content_count = sum(1 for row in readback[1:] if len(row) > 6 and _cell_text(row[6]))
    if full_content_count != end_row - 1:
        raise RuntimeError(f"完整原文回读 {full_content_count} 行，预期 {end_row - 1}")
    return {
        "ok": True,
        "sheet_id": sheet_id,
        "spreadsheet_token": spreadsheet_token,
        "range": target_range,
        "data_rows": end_row - 1,
        "excerpt_rows": excerpt_count,
        "full_content_rows": full_content_count,
        "full_text_sheet": full_text_result,
    }
