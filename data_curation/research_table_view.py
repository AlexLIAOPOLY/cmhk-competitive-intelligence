"""Read-only, paginated views of the local formal research tables."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .research_kpi import CARRIER_PATH, CLOUD_PATH


RUN_ID_PATTERN = re.compile(r"research_\d{8}(?:_rerun_\d{6})?")
TABLES = {
    "carrier": {
        "path": CARRIER_PATH,
        "label": "运营商正式指标表（香港／内地／国际）",
        "scope": "香港、内地、国际运营商",
    },
    "cloud": {
        "path": CLOUD_PATH,
        "label": "云厂商正式指标表",
        "scope": "全球云厂商",
    },
}
PREFERRED_COLUMNS = (
    "subject", "vendor", "category", "legal_name", "ticker", "period",
    "fiscal_year", "period_end", "fiscal_year_end", "grain", "metric_zh",
    "metric_key", "value", "currency", "unit", "official_value",
    "official_unit", "verification_status", "verification_count",
    "verification_method", "official_source_label", "official_source_url",
    "primary_source_url", "official_evidence", "verification_sources",
    "verification_note", "gap_reason_code", "gap_reason", "source_ids",
    "quality_status", "disclosure_quality", "quality_note",
    "disclosure_frequency", "daily_crawl_row_ref", "daily_evidence_hash",
    "daily_research_run_id",
)
COLUMN_LABELS = {
    "subject": "公司／对象", "vendor": "云厂商", "category": "类别",
    "legal_name": "法定名称", "ticker": "股票代码", "period": "报告期",
    "fiscal_year": "财年", "period_end": "报告期末", "fiscal_year_end": "财年末",
    "grain": "数据粒度", "metric_zh": "指标", "metric_key": "指标字段",
    "value": "数值", "currency": "币种", "unit": "单位",
    "official_value": "官方值", "official_unit": "官方单位",
    "verification_status": "核验状态", "verification_count": "核验次数",
    "verification_method": "核验方法", "official_source_label": "官方来源名称",
    "official_source_url": "官方来源链接", "primary_source_url": "主要来源链接",
    "official_evidence": "官方原文依据", "verification_sources": "核验来源",
    "verification_note": "核验说明", "gap_reason_code": "缺口代码",
    "gap_reason": "缺口原因", "source_ids": "来源编号",
    "quality_status": "质量状态", "disclosure_quality": "披露质量",
    "quality_note": "质量说明", "disclosure_frequency": "披露频率",
    "daily_crawl_row_ref": "采集行引用", "daily_evidence_hash": "证据哈希",
    "daily_research_run_id": "写入批次",
}


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("正式表格式无效")
    return data


def _scalar(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _row_key(row: dict, table_id: str) -> tuple[str, str, str]:
    if table_id == "cloud":
        keys = ("vendor", "fiscal_year", "metric_key")
    else:
        keys = ("subject", "period", "metric_key")
    return tuple(str(row.get(key) or "") for key in keys)


def _run_highlights(root: Path, run_id: str, table_id: str, rows: list[dict]) -> tuple[set[tuple[str, str, str]], int]:
    run_dir = root / "curation_data" / "research_runs" / run_id
    manifest = _read_json(run_dir / "manifest.json")
    if str(manifest.get("run_id") or "") != run_id:
        raise ValueError("研究批次档案不匹配")
    check = ((manifest.get("publication") or {}).get("storage_readback") or {})
    selected_path = TABLES[table_id]["path"]
    receipts = []
    for item in check.get("items") or []:
        main = item.get("main_table") if isinstance(item.get("main_table"), dict) else {}
        if main.get("status") != "written" or main.get("path") != selected_path:
            continue
        key_data = main.get("row_key") if isinstance(main.get("row_key"), dict) else {}
        if table_id == "cloud":
            key = tuple(str(key_data.get(name) or main.get(name) or "") for name in ("vendor", "fiscal_year", "metric_key"))
        else:
            key = tuple(str(key_data.get(name) or main.get(name) or "") for name in ("subject", "period", "metric_key"))
        receipts.append((key, main))
    current = {_row_key(row, table_id): row for row in rows}
    highlighted = set()
    for key, receipt in receipts:
        row = current.get(key)
        if not row:
            continue
        expected = receipt.get("current_value", receipt.get("candidate_value"))
        if expected is not None and str(row.get("value")) != str(expected):
            continue
        if receipt.get("unit") and str(row.get("unit") or "") != str(receipt["unit"]):
            continue
        if receipt.get("currency") and str(row.get("currency") or "") != str(receipt["currency"]):
            continue
        highlighted.add(key)
    return highlighted, len(receipts)


def formal_table_view(
    root: Path,
    *,
    run_id: str,
    table_id: str,
    page: int = 1,
    page_size: int = 100,
    query: str = "",
    highlight_only: bool = False,
) -> dict:
    """Return one safe page while retaining access to every local row and column."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("研究批次编号无效")
    if table_id not in TABLES:
        raise ValueError("正式表编号无效")
    page = max(1, int(page))
    page_size = max(20, min(200, int(page_size)))
    query = str(query or "").strip()[:200]
    meta = TABLES[table_id]
    source = root / meta["path"]
    data = _read_json(source)
    rows = data.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("正式表 rows 格式无效")
    highlighted, receipt_total = _run_highlights(root, run_id, table_id, rows)
    columns_seen = {key for row in rows for key in row}
    ordered_keys = [key for key in PREFERRED_COLUMNS if key in columns_seen]
    ordered_keys.extend(sorted(columns_seen - set(ordered_keys)))
    normalized = []
    query_folded = query.casefold()
    for row in rows:
        key = _row_key(row, table_id)
        is_new = key in highlighted
        values = {column: _scalar(row.get(column)) for column in ordered_keys}
        if highlight_only and not is_new:
            continue
        if query_folded and query_folded not in " ".join("" if value is None else str(value) for value in values.values()).casefold():
            continue
        normalized.append({
            "values": values,
            "is_new": is_new,
            "highlighted_cells": [key for key in ("subject", "vendor", "period", "fiscal_year", "metric_zh", "metric_key", "value", "unit", "currency") if key in values] if is_new else [],
        })
    filtered = len(normalized)
    pages = max(1, math.ceil(filtered / page_size))
    page = min(page, pages)
    start = (page - 1) * page_size
    return {
        "ok": True,
        "run_id": run_id,
        "table": {"id": table_id, **meta, "row_count": len(rows)},
        "columns": [{"key": key, "label": COLUMN_LABELS.get(key, key)} for key in ordered_keys],
        "rows": normalized[start:start + page_size],
        "summary": {
            "total": len(rows), "filtered": filtered, "new_total": len(highlighted),
            "receipt_total": receipt_total, "highlight_mismatch": max(0, receipt_total - len(highlighted)),
            "page": page, "page_size": page_size, "pages": pages,
        },
    }
