#!/usr/bin/env python3
"""Repair human-attributed review events using exact Feishu AI changesets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhk.auth.service import AuthService
from cmhk.intelligence.news_review_sheet import review_sheet_changesets


ROBOT = {
    "id": "news-auto-screening-bot",
    "name": "新闻自动初筛机器人",
    "role": "SYSTEM",
}
FIELD_COLUMNS = {
    "是否纳入滚动": 1,
    "纳入滚动": 1,
    "纳入滚动栏": 1,
    "是否纳入周报": 2,
    "纳入周报": 2,
}


def _timestamp(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _ai_cell_evidence(sheet_id: str, revisions: list[int]) -> dict[tuple[int, int], list[dict]]:
    evidence: dict[tuple[int, int], list[dict]] = {}
    for revision in sorted(set(revisions)):
        for changeset in review_sheet_changesets(revision, revision):
            if changeset.get("is_ai_edit") is not True:
                continue
            for action in changeset.get("actions") or []:
                if not isinstance(action, dict) or str(action.get("sheet_id") or "") != sheet_id:
                    continue
                if str(action.get("action") or "") not in {"setCell", "setRangeValues"}:
                    continue
                target = action.get("target") if isinstance(action.get("target"), dict) else {}
                try:
                    first_row = int(target.get("row")) + 1
                    first_column = int(target.get("col"))
                    row_count = max(1, int(target.get("row_count") or 1))
                    column_count = max(1, int(target.get("col_count") or 1))
                except (TypeError, ValueError):
                    continue
                item = {
                    "revision": int(changeset.get("revision") or revision),
                    "create_time": str(changeset.get("create_time") or ""),
                    "timestamp": _timestamp(changeset.get("create_time")),
                    "action": str(action.get("action") or ""),
                }
                for row_number in range(first_row, first_row + row_count):
                    for column_index in range(first_column, first_column + column_count):
                        evidence.setdefault((row_number, column_index), []).append(item)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--sheet-id", required=True)
    parser.add_argument("--revision", type=int, action="append", required=True)
    parser.add_argument("--max-delay-seconds", type=int, default=300)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    service = AuthService(args.runtime_root.resolve())
    audit_path = service.operation_audit_path
    raw_lines = audit_path.read_text(encoding="utf-8").splitlines()
    evidence = _ai_cell_evidence(args.sheet_id, args.revision)
    corrected: list[dict] = []
    output_lines: list[str] = []
    for raw_line in raw_lines:
        try:
            event = json.loads(raw_line)
        except (TypeError, ValueError):
            output_lines.append(raw_line)
            continue
        details = event.get("details") if isinstance(event, dict) and isinstance(event.get("details"), dict) else {}
        column_index = FIELD_COLUMNS.get(str(details.get("field") or "").strip())
        try:
            row_number = int(details.get("sheet_row") or 0)
        except (TypeError, ValueError):
            row_number = 0
        event_at = _timestamp(event.get("at") if isinstance(event, dict) else None)
        candidates = evidence.get((row_number, column_index), []) if column_index is not None else []
        match = None
        if (
            isinstance(event, dict)
            and event.get("action") == "news_review.update"
            and event.get("result") == "success"
            and str(event.get("actor_id") or "") != ROBOT["id"]
            and event_at is not None
        ):
            timed = [
                item
                for item in candidates
                if item.get("timestamp") is not None
                and 0 <= event_at - float(item["timestamp"]) <= args.max_delay_seconds
            ]
            if timed:
                match = max(timed, key=lambda item: float(item["timestamp"]))
        if match:
            event.update({
                "actor_id": ROBOT["id"],
                "actor_open_id": "",
                "actor_name": ROBOT["name"],
                "actor_avatar_url": "",
                "actor_role": ROBOT["role"],
            })
            details.update({
                "source_label": "新闻自动初筛",
                "identity_note": "飞书 changeset 已逐格标记为 AI 编辑；历史人工归因已修正",
                "identity_corrected": True,
                "feishu_changeset_revision": match["revision"],
                "feishu_changeset_at": match["create_time"],
                "feishu_changeset_action": match["action"],
                "feishu_changeset_ai_edit": True,
                "automation_event_key": "|".join((
                    "changeset-repair",
                    str(match["revision"]),
                    args.sheet_id,
                    str(row_number),
                    str(column_index),
                    str(details.get("after") or ""),
                )),
            })
            event["details"] = details
            corrected.append({
                "event_id": str(event.get("id") or ""),
                "row": row_number,
                "column": column_index,
                "revision": match["revision"],
            })
        output_lines.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))

    result = {
        "mode": "apply" if args.apply else "dry-run",
        "auditPath": str(audit_path),
        "aiCells": len(evidence),
        "correctedEvents": len(corrected),
        "byRevision": dict(Counter(str(item["revision"]) for item in corrected)),
        "sample": corrected[:10],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.apply or not corrected:
        return 0
    backup_path = audit_path.with_name(
        f"{audit_path.name}.before-changeset-attribution-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    )
    backup_path.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    os.chmod(backup_path, 0o600)
    temp_path = audit_path.with_name(f".{audit_path.name}.changeset-attribution.tmp")
    temp_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(audit_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
