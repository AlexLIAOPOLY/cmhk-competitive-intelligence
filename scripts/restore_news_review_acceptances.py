#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import news_review_sheet as review


DEFAULT_BACKUP = (
    ROOT
    / "curation_data"
    / "backups"
    / "news_review_sheet_before_final_duplicate_cleanup_20260727_104737.json"
)


def _load_rows(path: Path) -> list[list[Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"备份文件缺少 rows：{path}")
    return [
        (list(row) + [""] * len(review.HEADERS))[: len(review.HEADERS)]
        for row in rows
        if isinstance(row, list)
    ]


def _row_key(row: list[Any]) -> tuple[str, str]:
    padded = (list(row) + [""] * len(review.HEADERS))[: len(review.HEADERS)]
    return (
        review._canonical_news_url(review._cell_link(padded[10], 1600)),
        review._normalized_news_title(padded[6]),
    )


def _backup_live_rows(sheet_id: str, rows: list[list[Any]]) -> Path:
    backup_dir = ROOT / "curation_data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(review.HKT).strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"news_review_sheet_before_acceptance_restore_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "created_at": review._now_iso(),
                "sheet_id": sheet_id,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def build_restore_plan(
    backup_rows: list[list[Any]],
    live_rows: list[list[Any]],
) -> list[dict[str, Any]]:
    accepted_backup = {
        _row_key(row): row
        for row in backup_rows
        if review._normalized_status(row[0]) == "接受"
    }
    if len(accepted_backup) != 18:
        raise RuntimeError(
            f"基准备份应有18条接受记录，实际为 {len(accepted_backup)} 条"
        )

    live_by_key: dict[tuple[str, str], tuple[int, list[Any]]] = {}
    for row_number, row in enumerate(live_rows, start=2):
        key = _row_key(row)
        if not all(key):
            continue
        if key in live_by_key:
            raise RuntimeError(f"线上表存在重复记录，无法安全恢复：{row[6]}")
        live_by_key[key] = (row_number, row)

    plan: list[dict[str, Any]] = []
    for key, backup_row in accepted_backup.items():
        match = live_by_key.get(key)
        if not match:
            raise RuntimeError(f"线上表找不到基准记录：{backup_row[6]}")
        row_number, live_row = match
        live_status = review._normalized_status(live_row[0])
        if live_status not in {"接受", "不接受"}:
            raise RuntimeError(
                f"第{row_number}行状态不是事故造成的接受/不接受："
                f"{live_row[0]}（{live_row[6]}）"
            )
        plan.append(
            {
                "row_number": row_number,
                "title": live_row[6],
                "before": list(live_row[:3]),
                "after": list(backup_row[:3]),
            }
        )
    plan.sort(key=lambda item: item["row_number"])
    return plan


def apply_restore(
    sheet_id: str,
    live_rows: list[list[Any]],
    plan: list[dict[str, Any]],
) -> dict[str, Any]:
    backup_path = _backup_live_rows(sheet_id, live_rows)
    expected = [list(row) for row in live_rows]
    try:
        for item in plan:
            row_number = int(item["row_number"])
            review._write(
                sheet_id,
                f"A{row_number}:C{row_number}",
                [item["after"]],
            )
            expected[row_number - 2][:3] = item["after"]

        readback = review._read_rows(sheet_id)
        if [
            review._comparable_sheet_row(row) for row in readback
        ] != [
            review._comparable_sheet_row(row) for row in expected
        ]:
            raise RuntimeError("恢复后全表逐格回读不一致")
    except Exception:
        for item in plan:
            row_number = int(item["row_number"])
            review._write(
                sheet_id,
                f"A{row_number}:C{row_number}",
                [item["before"]],
            )
        rollback = review._read_rows(sheet_id)
        if [
            review._comparable_sheet_row(row) for row in rollback
        ] != [
            review._comparable_sheet_row(row) for row in live_rows
        ]:
            raise RuntimeError(
                f"恢复失败且自动回滚未能逐格验证，请使用备份：{backup_path}"
            )
        raise

    return {
        "sheet_id": sheet_id,
        "restored_count": len(plan),
        "backup_path": str(backup_path),
        "accepted_after_restore": sum(
            review._normalized_status(row[0]) == "接受" for row in expected
        ),
        "full_readback_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="恢复2026-07-28错列事故中被自动改写的18条人工接受记录"
    )
    parser.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    sheet_id = review._find_sheet_id(review._spreadsheet_info())
    if not sheet_id:
        raise RuntimeError("未找到滚动新闻候选池子表")
    live_rows = review._read_rows(sheet_id)
    review._validate_sheet_rows(live_rows, context="恢复前飞书审核表")
    plan = build_restore_plan(_load_rows(args.backup), live_rows)
    result: dict[str, Any] = {
        "sheet_id": sheet_id,
        "apply": args.apply,
        "planned_count": len(plan),
        "changes": plan,
    }
    if args.apply:
        result.update(apply_restore(sheet_id, live_rows, plan))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
