from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


HKT = ZoneInfo("Asia/Hong_Kong")

# Feishu Help Center limits, checked 2026-08-21:
# - 5,000,000 cells per worksheet
# - 13,000 columns per worksheet
# - 300 grid worksheets per spreadsheet
FEISHU_MAX_CELLS_PER_SHEET = 5_000_000
FEISHU_MAX_COLUMNS_PER_SHEET = 13_000
FEISHU_MAX_SHEETS_PER_WORKBOOK = 300
DEFAULT_SOFT_LIMIT_RATIO = 0.90


@dataclass(frozen=True)
class CapacityDecision:
    should_rollover: bool
    reason: str
    used_rows: int
    incoming_rows: int
    column_count: int
    projected_rows: int
    projected_cells: int
    soft_row_limit: int
    hard_row_limit: int
    sheet_count: int
    soft_sheet_limit: int


def capacity_decision(
    *,
    used_rows: int,
    column_count: int,
    incoming_rows: int = 0,
    sheet_count: int = 0,
    operational_max_rows: int | None = None,
    soft_limit_ratio: float = DEFAULT_SOFT_LIMIT_RATIO,
) -> CapacityDecision:
    """Return a conservative pre-write capacity decision.

    Feishu has no standalone row limit for a grid worksheet. The effective row
    ceiling is the 5M-cell limit divided by the actual column width. A target
    may additionally impose a smaller operational row ceiling so reads and
    browser rendering stay bounded.
    """

    rows = max(0, int(used_rows))
    columns = max(1, int(column_count))
    incoming = max(0, int(incoming_rows))
    ratio = min(0.99, max(0.50, float(soft_limit_ratio)))
    hard_row_limit = FEISHU_MAX_CELLS_PER_SHEET // columns
    if operational_max_rows is not None:
        hard_row_limit = min(hard_row_limit, max(1, int(operational_max_rows)))
    soft_row_limit = max(1, math.floor(hard_row_limit * ratio))
    projected_rows = rows + incoming
    projected_cells = projected_rows * columns
    soft_sheet_limit = max(1, math.floor(FEISHU_MAX_SHEETS_PER_WORKBOOK * ratio))

    reason = "within_capacity"
    if columns >= math.floor(FEISHU_MAX_COLUMNS_PER_SHEET * ratio):
        reason = "column_limit_near"
    elif projected_rows >= soft_row_limit:
        reason = "row_or_cell_limit_near"
    elif sheet_count >= soft_sheet_limit:
        reason = "workbook_sheet_limit_near"
    return CapacityDecision(
        should_rollover=reason != "within_capacity",
        reason=reason,
        used_rows=rows,
        incoming_rows=incoming,
        column_count=columns,
        projected_rows=projected_rows,
        projected_cells=projected_cells,
        soft_row_limit=soft_row_limit,
        hard_row_limit=hard_row_limit,
        sheet_count=max(0, int(sheet_count)),
        soft_sheet_limit=soft_sheet_limit,
    )


def timestamped_part_title(
    base_title: str,
    *,
    now: datetime | None = None,
    existing_titles: set[str] | None = None,
) -> str:
    timestamp = (now or datetime.now(HKT)).astimezone(HKT).strftime("%Y%m%d_%H%M")
    safe_base = re.sub(r"[/\\?*\[\]:]", "_", str(base_title).strip())[:84] or "分卷"
    candidate = f"{safe_base}_{timestamp}"[:100]
    titles = existing_titles or set()
    if candidate not in titles:
        return candidate
    for sequence in range(2, 100):
        suffix = f"_{sequence}"
        alternative = f"{candidate[:100 - len(suffix)]}{suffix}"
        if alternative not in titles:
            return alternative
    raise RuntimeError("无法生成唯一的飞书分卷子表名")


def sheet_url(spreadsheet_token: str, sheet_id: str) -> str:
    return f"https://cmhk-try.feishu.cn/sheets/{spreadsheet_token}?sheet={sheet_id}"


def runtime_registry_path(root: Path) -> Path:
    configured = os.environ.get("CMHK_FEISHU_ROLLOVER_REGISTRY", "").strip()
    return Path(configured) if configured else root / "var" / "feishu_sheet_rollovers.json"


def read_registry(root: Path) -> dict[str, Any]:
    path = runtime_registry_path(root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"version": 1, "targets": {}}
    if not isinstance(value, dict):
        return {"version": 1, "targets": {}}
    if not isinstance(value.get("targets"), dict):
        value["targets"] = {}
    value.setdefault("version", 1)
    return value


def record_active_part(
    root: Path,
    target: str,
    *,
    spreadsheet_token: str,
    sheet_id: str,
    sheet_title: str,
    decision: CapacityDecision | None = None,
    previous: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    path = runtime_registry_path(root)
    registry = read_registry(root)
    timestamp = (now or datetime.now(HKT)).astimezone(HKT).isoformat(timespec="seconds")
    existing = registry["targets"].get(target)
    same_part = (
        isinstance(existing, dict)
        and str(existing.get("spreadsheet_token") or "") == spreadsheet_token
        and str(existing.get("sheet_id") or "") == sheet_id
    )
    entry: dict[str, Any] = {
        "spreadsheet_token": spreadsheet_token,
        "sheet_id": sheet_id,
        "sheet_title": sheet_title,
        "sheet_url": sheet_url(spreadsheet_token, sheet_id),
        "activated_at_hkt": (
            str(existing.get("activated_at_hkt") or timestamp) if same_part else timestamp
        ),
        "updated_at_hkt": timestamp,
    }
    if decision is not None:
        entry["capacity_at_activation"] = asdict(decision)
    if previous:
        entry["previous_part"] = {
            key: previous.get(key)
            for key in ("spreadsheet_token", "sheet_id", "sheet_title", "sheet_url")
            if previous.get(key)
        }
    elif same_part and existing.get("previous_part"):
        entry["previous_part"] = existing["previous_part"]
    registry["targets"][target] = entry
    registry["updated_at_hkt"] = timestamp
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return entry


def active_part(root: Path, target: str) -> dict[str, Any]:
    targets = read_registry(root).get("targets") or {}
    value = targets.get(target) if isinstance(targets, dict) else None
    return dict(value) if isinstance(value, dict) else {}
