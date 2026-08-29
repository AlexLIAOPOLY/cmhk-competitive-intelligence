#!/usr/bin/env python3
"""Promote attached official evidence over media/mirror primary URLs.

This is deliberately a migration of the current non-degraded quarterly package,
not a rebuild from older source inputs.  Verification-source arrays are retained
unchanged so mirrors remain available as secondary audit evidence.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"
NON_ISSUER_HOSTS = (
    "businesswire.com",
    "money.finance.sina.com.cn",
    "vip.stock.finance.sina.com.cn",
)


def _is_non_issuer(url: Any) -> bool:
    lowered = str(url or "").lower()
    return any(host in lowered for host in NON_ISSUER_HOSTS)


def _sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("verification_sources") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def normalize_row(row: dict[str, Any]) -> bool:
    if not _is_non_issuer(row.get("official_source_url")):
        return False
    preferred = next(
        (
            source
            for source in _sources(row)
            if source.get("url") and not _is_non_issuer(source.get("url"))
        ),
        None,
    )
    if preferred is None:
        raise RuntimeError(
            "non-issuer primary source has no attached official alternative: "
            f"{row.get('subject')} {row.get('period')} {row.get('metric_key')}"
        )
    row["official_source_url"] = str(preferred["url"])
    if preferred.get("label"):
        row["official_source_label"] = str(preferred["label"])
    if preferred.get("evidence"):
        row["official_evidence"] = str(preferred["evidence"])
    return True


def _atomic_text(path: Path, text: str) -> None:
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_csv(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    changed = sum(normalize_row(row) for row in rows)
    if not changed:
        return 0
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8-sig", newline="", delete=False, dir=path.parent
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return changed


def sync_csv_projection(
    path: Path,
    source_rows: list[dict[str, str]],
    *,
    target_key_fields: tuple[str, str, str],
    source_key_fields: tuple[str, str, str],
) -> int:
    index = {
        tuple(str(row.get(field) or "") for field in source_key_fields): row
        for row in source_rows
    }
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    changed = 0
    for row in rows:
        source = index.get(
            tuple(str(row.get(field) or "") for field in target_key_fields)
        )
        if source is None:
            continue
        for field in ("official_source_url", "official_source_label"):
            if field in row and row.get(field) != source.get(field):
                row[field] = source.get(field, "")
                changed += 1
    if not changed:
        return 0
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8-sig", newline="", delete=False, dir=path.parent
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return changed


def normalize_json(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"expected rows array: {path}")
    changed = sum(normalize_row(row) for row in rows if isinstance(row, dict))
    if changed:
        _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return changed


def main() -> int:
    main_csv = DATASET / "quarterly_metrics.csv"
    changes = {
        "quarterly_metrics.csv": normalize_csv(main_csv),
        "quarterly_metrics.json": normalize_json(DATASET / "quarterly_metrics.json"),
        "official_verified_metrics_2026-06-18.csv": normalize_csv(
            DATASET / "official_verified_metrics_2026-06-18.csv"
        ),
        "online_verification_2026-06-18.csv": normalize_csv(
            DATASET / "online_verification_2026-06-18.csv"
        ),
    }
    with main_csv.open(encoding="utf-8-sig", newline="") as handle:
        current_rows = list(csv.DictReader(handle))
    changes["quarterly_metrics_human_readable.csv"] = sync_csv_projection(
        DATASET / "quarterly_metrics_human_readable.csv",
        current_rows,
        target_key_fields=("subject", "period", "metric_zh"),
        source_key_fields=("subject", "period", "metric_zh"),
    )
    changes["cloud_source_gap_integrity_2026-06-18.csv"] = sync_csv_projection(
        DATASET / "cloud_source_gap_integrity_2026-06-18.csv",
        current_rows,
        target_key_fields=("subject", "target_period", "metric_key"),
        source_key_fields=("subject", "period", "metric_key"),
    )
    print(json.dumps(changes, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
