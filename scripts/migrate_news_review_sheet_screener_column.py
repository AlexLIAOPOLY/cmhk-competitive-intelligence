#!/usr/bin/env python3
"""Safely insert the v10 screener column into every news-review sheet part.

The migration is deliberately separate from normal synchronization. It backs up
the v9 values and structural evidence, refuses merged/formula-bearing ranges,
inserts one physical column before A, and only publishes format_version=10 after
every targeted part passes exact B:O readback plus dropdown/freeze checks.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cmhk.intelligence.news_review_sheet as review  # noqa: E402


MIGRATION_ID = "news-review-v9-to-v10-screener-20260830"
OLD_FORMAT_VERSION = 9
NEW_FORMAT_VERSION = 10
OLD_HEADERS = review.HEADERS[1:]
NEW_HEADERS = review.HEADERS


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@contextmanager
def _runtime_review_lock(runtime_root: Path):
    """Exclude the formal scheduler/reviewer while the physical schema moves."""

    lock_path = (
        runtime_root
        / "strategy_briefing"
        / "cmhk.intelligence.news_review_sheet.lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "正式战略新闻审核进程正在运行，未取得运行态排他锁；本次没有迁移"
            ) from exc
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        handle.close()


def _walk(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = _walk(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _walk(value, key)
            if found is not None:
                return found
    return None


def _lark(
    *parts: str,
    identity: str = "",
    profile: str = "",
    retry_transient: bool = True,
) -> dict[str, Any]:
    return review._lark(
        *parts,
        retry_transient=retry_transient,
        identity_override=identity,
        profile_override=profile,
    )


def _values_from_payload(payload: dict[str, Any]) -> list[list[Any]]:
    values = _walk(payload, "values")
    return [list(row) if isinstance(row, list) else [] for row in values or []]


def _read_values(
    sheet_id: str,
    cell_range: str,
    *,
    identity: str = "",
    profile: str = "",
) -> list[list[Any]]:
    payload = _lark(
        "sheets",
        "+read",
        "--spreadsheet-token",
        review.SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--range",
        cell_range,
        "--value-render-option",
        "ToString",
        identity=identity,
        profile=profile,
    )
    return _values_from_payload(payload)


def _normalized_rows(rows: list[list[Any]], width: int) -> list[list[Any]]:
    normalized = [(list(row) + [""] * width)[:width] for row in rows]
    while normalized and not any(str(value or "").strip() for value in normalized[-1]):
        normalized.pop()
    return normalized


def _schema_kind(header_row: list[Any]) -> str:
    values = (list(header_row) + [""] * len(NEW_HEADERS))[: len(NEW_HEADERS)]
    if [str(value or "") for value in values] == NEW_HEADERS:
        return "v10"
    if [str(value or "") for value in values[: len(OLD_HEADERS)]] == OLD_HEADERS:
        if not str(values[len(OLD_HEADERS)] or "").strip():
            return "v9"
    raise RuntimeError(
        "审核表表头既不是 v9 A:N，也不是 v10 A:O；已停止结构写入"
    )


def _grid_rows_by_sheet() -> dict[str, int]:
    info = review._spreadsheet_info()
    result: dict[str, int] = {}
    for sheet in review._sheet_items(info):
        sheet_id = str(sheet.get("sheet_id") or "")
        properties = sheet.get("grid_properties") if isinstance(
            sheet.get("grid_properties"), dict
        ) else {}
        if sheet_id:
            result[sheet_id] = int(properties.get("row_count") or review.MAX_SHEET_ROWS)
    return result


def _sheet_parts(state: dict[str, Any]) -> list[dict[str, str]]:
    active_sheet_id = str(state.get("sheet_id") or "").strip()
    parts = review._review_sheet_parts(state, active_sheet_id)
    if not parts:
        raise RuntimeError("运行态未记录战略新闻审核表 sheet_id")
    return parts


def _cell_audit(
    sheet_id: str,
    end_row: int,
    end_column: str,
    *,
    identity: str = "",
    profile: str = "",
) -> dict[str, Any]:
    return _lark(
        "sheets",
        "+cells-get",
        "--spreadsheet-token",
        review.SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--range",
        f"A1:{end_column}{max(1, end_row)}",
        "--include",
        "value,formula,data_validation",
        "--max-chars",
        "20000000",
        identity=identity,
        profile=profile,
    )


def _sheet_info(
    sheet_id: str,
    end_row: int,
    end_column: str,
    *,
    identity: str = "",
    profile: str = "",
) -> dict[str, Any]:
    return _lark(
        "sheets",
        "+sheet-info",
        "--spreadsheet-token",
        review.SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--range",
        f"A1:{end_column}{max(1, end_row)}",
        "--include",
        "merges,frozen,col_widths",
        identity=identity,
        profile=profile,
    )


def _cell_objects(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ranges = _walk(payload, "ranges")
    output: list[dict[str, Any]] = []
    for range_item in ranges if isinstance(ranges, list) else []:
        if not isinstance(range_item, dict):
            continue
        if range_item.get("truncated") is True:
            raise RuntimeError("cells-get 返回截断结果，已停止迁移")
        for row in range_item.get("cells") or []:
            for cell in row if isinstance(row, list) else []:
                if isinstance(cell, dict):
                    output.append(cell)
    return output


def inspect_sheet(
    part: dict[str, str],
    row_count: int,
    *,
    identity: str = "",
    profile: str = "",
) -> dict[str, Any]:
    sheet_id = part["sheet_id"]
    header_rows = _read_values(
        sheet_id,
        "A1:O1",
        identity=identity,
        profile=profile,
    )
    header = header_rows[0] if header_rows else []
    schema = _schema_kind(header)
    source_column = "N" if schema == "v9" else "O"
    values = _normalized_rows(
        _read_values(
            sheet_id,
            f"A1:{source_column}{row_count}",
            identity=identity,
            profile=profile,
        ),
        14 if schema == "v9" else 15,
    )
    used_rows = max(1, len(values))
    structure = _sheet_info(
        sheet_id,
        used_rows,
        source_column,
        identity=identity,
        profile=profile,
    )
    cell_audit = _cell_audit(
        sheet_id,
        used_rows,
        source_column,
        identity=identity,
        profile=profile,
    )
    data = structure.get("data") if isinstance(structure.get("data"), dict) else {}
    merges = data.get("merged_cells") if isinstance(data, dict) else []
    if merges:
        raise RuntimeError(f"审核表 {sheet_id} 含合并单元格，已停止自动插列")
    formulas = [cell.get("formula") for cell in _cell_objects(cell_audit) if cell.get("formula")]
    if formulas:
        raise RuntimeError(f"审核表 {sheet_id} 含 {len(formulas)} 个公式，已停止自动插列")
    return {
        "sheetId": sheet_id,
        "sheetTitle": part.get("sheet_title") or "",
        "role": part.get("role") or "",
        "schema": schema,
        "rowCount": row_count,
        "usedRows": used_rows,
        "values": values,
        "structure": structure,
        "cellAudit": cell_audit,
    }


def _write_backup(runtime_root: Path, inspections: list[dict[str, Any]]) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    path = (
        runtime_root
        / "curation_data"
        / "backups"
        / f"news_review_sheet_before_screener_column_{timestamp}.json"
    )
    _atomic_write_json(
        path,
        {
            "migrationId": MIGRATION_ID,
            "createdAt": _now_iso(),
            "spreadsheetToken": review.SPREADSHEET_TOKEN,
            "sheets": inspections,
        },
    )
    return path


def _insert_screener_column(
    sheet_id: str,
    *,
    identity: str = "",
    profile: str = "",
) -> None:
    _lark(
        "sheets",
        "+dim-insert",
        "--spreadsheet-token",
        review.SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--position",
        "A",
        "--count",
        "1",
        "--inherit-style",
        "after",
        identity=identity,
        profile=profile,
        retry_transient=False,
    )


def _configure_new_column(
    sheet_id: str,
    row_count: int,
    *,
    identity: str = "",
    profile: str = "",
) -> None:
    review._write(
        sheet_id,
        "A1:O1",
        [NEW_HEADERS],
        identity=identity,
        profile=profile,
    )
    if row_count >= 2:
        validation_cells = [[{"data_validation": None}] for _ in range(row_count - 1)]
        _lark(
            "sheets",
            "+cells-set",
            "--spreadsheet-token",
            review.SPREADSHEET_TOKEN,
            "--sheet-id",
            sheet_id,
            "--range",
            f"A2:A{row_count}",
            "--cells",
            json.dumps(validation_cells, ensure_ascii=False),
            identity=identity,
            profile=profile,
            retry_transient=False,
        )
    _lark(
        "sheets",
        "+update-dimension",
        "--spreadsheet-token",
        review.SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--dimension",
        "COLUMNS",
        "--start-index",
        "1",
        "--end-index",
        "1",
        "--fixed-size",
        "150",
        "--visible",
        identity=identity,
        profile=profile,
        retry_transient=False,
    )
    _lark(
        "sheets",
        "+update-sheet",
        "--spreadsheet-token",
        review.SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        "--frozen-row-count",
        "1",
        "--frozen-col-count",
        "9",
        identity=identity,
        profile=profile,
        retry_transient=False,
    )
    filter_payload = _lark(
        "sheets",
        "+filter-view-list",
        "--spreadsheet-token",
        review.SPREADSHEET_TOKEN,
        "--sheet-id",
        sheet_id,
        identity=identity,
        profile=profile,
    )
    sheets = _walk(filter_payload, "sheets")
    views: list[dict[str, Any]] = []
    for item in sheets if isinstance(sheets, list) else []:
        if isinstance(item, dict) and str(item.get("sheet_id") or "") == sheet_id:
            views = [view for view in item.get("views") or [] if isinstance(view, dict)]
            break
    for view in views:
        view_id = str(view.get("view_id") or "")
        if not view_id:
            continue
        details = view.get("details") if isinstance(view.get("details"), dict) else {}
        _lark(
            "sheets",
            "+filter-view-update",
            "--spreadsheet-token",
            review.SPREADSHEET_TOKEN,
            "--sheet-id",
            sheet_id,
            "--view-id",
            view_id,
            "--range",
            f"A1:O{row_count}",
            "--properties",
            json.dumps(
                {
                    "rules": details.get("rules") or [],
                    "filtered_columns": details.get("filtered_columns") or [],
                },
                ensure_ascii=False,
            ),
            identity=identity,
            profile=profile,
            retry_transient=False,
        )


def verify_sheet(
    inspection: dict[str, Any],
    *,
    identity: str = "",
    profile: str = "",
) -> dict[str, Any]:
    sheet_id = str(inspection["sheetId"])
    used_rows = max(1, int(inspection.get("usedRows") or 1))
    post_values = _normalized_rows(
        _read_values(
            sheet_id,
            f"A1:O{max(used_rows, 2)}",
            identity=identity,
            profile=profile,
        ),
        15,
    )
    if not post_values or [str(value or "") for value in post_values[0]] != NEW_HEADERS:
        raise RuntimeError(f"审核表 {sheet_id} v10 表头回读不一致")
    expected_v9_values = inspection.get("expectedV9Values")
    if inspection.get("schema") == "v9" or isinstance(expected_v9_values, list):
        expected_old = _normalized_rows(
            expected_v9_values
            if isinstance(expected_v9_values, list)
            else inspection.get("values") or [],
            14,
        )
        shifted = [row[1:15] for row in post_values[: len(expected_old)]]
        if shifted != expected_old:
            raise RuntimeError(f"审核表 {sheet_id} 插列后 B:O 未与原 A:N 逐格一致")

    structure = _sheet_info(
        sheet_id,
        min(max(2, used_rows), int(inspection.get("rowCount") or used_rows)),
        "O",
        identity=identity,
        profile=profile,
    )
    data = structure.get("data") if isinstance(structure.get("data"), dict) else {}
    if int(data.get("frozen_rows") or 0) != 1 or int(data.get("frozen_columns") or 0) != 9:
        raise RuntimeError(f"审核表 {sheet_id} 冻结行列回读不一致")
    widths = data.get("column_widths") if isinstance(data.get("column_widths"), list) else []
    if not any(
        isinstance(item, dict)
        and str(item.get("cols") or "") in {"A", "A:A"}
        and int(item.get("width") or 0) == 150
        for item in widths
    ):
        raise RuntimeError(f"审核表 {sheet_id} 筛选人列宽回读不一致")

    audit = _cell_audit(
        sheet_id,
        min(max(2, used_rows), int(inspection.get("rowCount") or used_rows)),
        "D",
        identity=identity,
        profile=profile,
    )
    cell_ranges = _walk(audit, "ranges")
    cells = (
        cell_ranges[0].get("cells")
        if isinstance(cell_ranges, list)
        and cell_ranges
        and isinstance(cell_ranges[0], dict)
        else []
    )
    body = cells[1] if isinstance(cells, list) and len(cells) > 1 else []
    if len(body) < 4:
        raise RuntimeError(f"审核表 {sheet_id} 下拉验证回读缺少 B/C/D")
    if body[0].get("data_validation"):
        raise RuntimeError(f"审核表 {sheet_id} 筛选人 A 列仍残留审核状态下拉")
    expected_options = [
        ["待审核", "接受", "暂缓", "不接受"],
        ["待审核", "接受", "暂缓", "不接受"],
        ["未同步", "已纳入", "已移除", "同步失败"],
    ]
    for offset, options in enumerate(expected_options, start=1):
        validation = body[offset].get("data_validation") if isinstance(body[offset], dict) else {}
        if not isinstance(validation, dict) or validation.get("items") != options:
            raise RuntimeError(
                f"审核表 {sheet_id} {chr(ord('A') + offset)} 列下拉验证回读不一致"
            )
    return {
        "sheetId": sheet_id,
        "schema": "v10",
        "usedRows": len(post_values),
        "shiftedReadbackVerified": True,
        "dropdownReadbackVerified": True,
        "layoutReadbackVerified": True,
    }


def _migrate_unlocked(
    runtime_root: Path,
    *,
    apply: bool,
    identity: str = "",
    profile: str = "",
) -> dict[str, Any]:
    state_path = runtime_root / "strategy_briefing" / "news_review_sheet_state.json"
    journal_path = runtime_root / "strategy_briefing" / "news_review_screener_migration_state.json"
    state = _read_json(state_path, {})
    if not isinstance(state, dict) or not state:
        raise RuntimeError(f"未找到运行态审核表状态：{state_path}")
    format_version = int(state.get("format_version") or 0)
    if format_version not in {OLD_FORMAT_VERSION, NEW_FORMAT_VERSION}:
        raise RuntimeError(
            f"仅支持 v{OLD_FORMAT_VERSION} → v{NEW_FORMAT_VERSION}，当前为 v{format_version}"
        )
    parts = _sheet_parts(state)
    grid_rows = _grid_rows_by_sheet()
    inspections = [
        inspect_sheet(
            part,
            grid_rows.get(part["sheet_id"], review.MAX_SHEET_ROWS),
            identity=identity,
            profile=profile,
        )
        for part in parts
    ]
    prior_journal = _read_json(journal_path, {})
    prior_backup_path = Path(
        str(prior_journal.get("backupPath") or "")
    ) if isinstance(prior_journal, dict) else Path()
    prior_backup = (
        _read_json(prior_backup_path, {})
        if str(prior_backup_path) and prior_backup_path.is_file()
        else {}
    )
    prior_sheets = {
        str(item.get("sheetId") or ""): item
        for item in prior_backup.get("sheets") or []
        if isinstance(item, dict) and item.get("sheetId")
    } if isinstance(prior_backup, dict) else {}
    if format_version == OLD_FORMAT_VERSION:
        for inspection in inspections:
            if inspection.get("schema") != "v10":
                continue
            baseline = prior_sheets.get(str(inspection.get("sheetId") or ""))
            if (
                not isinstance(baseline, dict)
                or baseline.get("schema") != "v9"
                or not isinstance(baseline.get("values"), list)
            ):
                raise RuntimeError(
                    f"审核表 {inspection.get('sheetId')} 已是 v10，但运行态仍是 v9，"
                    "且找不到首次插列前备份；为避免重复插列或误确认，已停止迁移"
                )
            inspection["expectedV9Values"] = baseline["values"]
    preflight = {
        "migrationId": MIGRATION_ID,
        "status": "ready" if any(item["schema"] == "v9" for item in inspections) else "already_migrated",
        "apply": apply,
        "statePath": str(state_path),
        "formatVersionBefore": format_version,
        "sheets": [
            {
                key: item[key]
                for key in ("sheetId", "sheetTitle", "role", "schema", "rowCount", "usedRows")
            }
            for item in inspections
        ],
        "preflightVerified": True,
    }
    if not apply:
        return preflight

    backup_path = _write_backup(runtime_root, inspections)
    journal: dict[str, Any] = {
        **preflight,
        "status": "running",
        "startedAt": _now_iso(),
        "backupPath": str(backup_path),
        "sheets": {},
    }
    _atomic_write_json(journal_path, journal)
    verifications: list[dict[str, Any]] = []
    try:
        for inspection in inspections:
            sheet_id = str(inspection["sheetId"])
            if inspection["schema"] == "v9":
                _insert_screener_column(
                    sheet_id,
                    identity=identity,
                    profile=profile,
                )
            _configure_new_column(
                sheet_id,
                int(inspection["rowCount"]),
                identity=identity,
                profile=profile,
            )
            verification = verify_sheet(
                inspection,
                identity=identity,
                profile=profile,
            )
            verifications.append(verification)
            journal["sheets"][sheet_id] = {
                "status": "verified",
                "verifiedAt": _now_iso(),
                **verification,
            }
            _atomic_write_json(journal_path, journal)
    except Exception as exc:
        journal["status"] = "failed"
        journal["failedAt"] = _now_iso()
        journal["error"] = str(exc)[:1000]
        _atomic_write_json(journal_path, journal)
        raise

    next_state = dict(state)
    next_state["format_version"] = NEW_FORMAT_VERSION
    next_state["formatted_at"] = _now_iso()
    next_state["updated_at"] = _now_iso()
    next_state["screener_column_migration"] = {
        "migration_id": MIGRATION_ID,
        "completed_at": _now_iso(),
        "backup_path": str(backup_path),
        "verified_sheet_ids": [item["sheetId"] for item in verifications],
    }
    _atomic_write_json(state_path, next_state)
    journal["status"] = "completed"
    journal["completedAt"] = _now_iso()
    journal["formatVersionAfter"] = NEW_FORMAT_VERSION
    _atomic_write_json(journal_path, journal)
    return {
        **preflight,
        "status": "completed",
        "formatVersionAfter": NEW_FORMAT_VERSION,
        "backupPath": str(backup_path),
        "journalPath": str(journal_path),
        "verifications": verifications,
    }


def migrate(
    runtime_root: Path,
    *,
    apply: bool,
    identity: str = "",
    profile: str = "",
) -> dict[str, Any]:
    if not apply:
        return _migrate_unlocked(
            runtime_root,
            apply=False,
            identity=identity,
            profile=profile,
        )
    with _runtime_review_lock(runtime_root):
        return _migrate_unlocked(
            runtime_root,
            apply=True,
            identity=identity,
            profile=profile,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(os.environ.get("CMHK_RUNTIME_ROOT") or ROOT),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="execute the insertion; omission performs a read-only preflight",
    )
    parser.add_argument("--identity", default="")
    parser.add_argument("--profile", default="")
    args = parser.parse_args()
    result = migrate(
        args.runtime_root.resolve(),
        apply=args.apply,
        identity=args.identity,
        profile=args.profile,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
