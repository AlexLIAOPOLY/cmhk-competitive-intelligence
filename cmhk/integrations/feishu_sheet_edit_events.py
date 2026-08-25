from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


TARGET_SPREADSHEET_TOKEN = (
    os.environ.get("CMHK_NEWS_REVIEW_SPREADSHEET_TOKEN")
    or "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
).strip()
DEFAULT_EVENT_PATH = Path(
    os.environ.get(
        "CMHK_FEISHU_SHEET_EDIT_EVENT_PATH",
        str(Path.cwd() / "var" / "auth" / "feishu-sheet-edit-events.jsonl"),
    )
)

_LOCK = threading.RLock()


def _value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _identifier(item: Any) -> dict[str, str]:
    return {
        "open_id": str(_value(item, "open_id") or "").strip(),
        "union_id": str(_value(item, "union_id") or "").strip(),
        "user_id": str(_value(item, "user_id") or "").strip(),
    }


def capture_drive_file_edit_event(
    data: Any,
    *,
    path: Path = DEFAULT_EVENT_PATH,
) -> dict[str, Any] | None:
    """Persist operator IDs from the official drive.file.edit_v1 event."""
    event = _value(data, "event", data)
    file_token = str(_value(event, "file_token") or "").strip()
    file_type = str(_value(event, "file_type") or "").strip()
    if file_token != TARGET_SPREADSHEET_TOKEN or file_type != "sheet":
        return None

    header = _value(data, "header", {})
    operators = [
        identifier
        for identifier in (
            _identifier(item)
            for item in (_value(event, "operator_id_list", []) or [])
        )
        if any(identifier.values())
    ]
    if not operators:
        return None

    record = {
        "event_id": str(_value(header, "event_id") or "").strip(),
        "event_type": str(_value(header, "event_type") or "drive.file.edit_v1").strip(),
        "create_time": str(_value(header, "create_time") or "").strip(),
        "file_token": file_token,
        "file_type": file_type,
        "operators": operators,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def sheet_edit_events(
    *,
    path: Path = DEFAULT_EVENT_PATH,
    after_ms: int = 0,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    seen: set[str] = set()
    for line in lines:
        try:
            item = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(item, dict) or item.get("file_token") != TARGET_SPREADSHEET_TOKEN:
            continue
        try:
            created_ms = int(item.get("create_time") or 0)
        except (TypeError, ValueError):
            created_ms = 0
        if created_ms <= after_ms:
            continue
        event_id = str(item.get("event_id") or "")
        dedupe_key = event_id or json.dumps(item, ensure_ascii=False, sort_keys=True)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        item["create_time_ms"] = created_ms
        records.append(item)
    records.sort(key=lambda item: int(item.get("create_time_ms") or 0))
    return records
