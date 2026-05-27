from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "crawl_settings.json"


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {"version": 1, "rows": {}}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "rows": {}}
    if not isinstance(data, dict):
        return {"version": 1, "rows": {}}
    data.setdefault("version", 1)
    data.setdefault("rows", {})
    if not isinstance(data["rows"], dict):
        data["rows"] = {}
    return data


def save_settings(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "version": 1,
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
    }
    SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def selected_row_config(row: int | str) -> dict[str, Any]:
    settings = load_settings()
    cfg = settings.get("rows", {}).get(str(row), {})
    return cfg if isinstance(cfg, dict) else {}


def enabled_rows() -> set[int] | None:
    settings = load_settings()
    row_settings = settings.get("rows", {})
    if not row_settings:
        return None
    enabled: set[int] = set()
    for row, cfg in row_settings.items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("enabled", True):
            try:
                enabled.add(int(row))
            except ValueError:
                continue
    return enabled


def apply_selected_fields(
    extracted: dict[str, Any], missing: Iterable[str], selected_fields: Iterable[str] | None
) -> tuple[dict[str, Any], list[str]]:
    fields = [field for field in selected_fields or [] if field]
    if not fields:
        return extracted, list(missing)
    allowed = set(fields)
    return {key: value for key, value in extracted.items() if key in allowed}, [
        field for field in missing if field in allowed
    ]
