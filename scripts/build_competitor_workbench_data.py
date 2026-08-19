from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_OPERATOR_SOURCE = (
    ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.csv"
)
LOCAL_HK_SOURCE = (
    ROOT / "agent_knowledge/local_hk_operator_operating_metrics_2016_2025/annual_metrics.csv"
)
SOURCES = (
    GLOBAL_OPERATOR_SOURCE,
    LOCAL_HK_SOURCE,
)
OUTPUT = ROOT / "web/static/competitor-workbench-data.json"
BLOCKED_STATUSES = {"source_gap_confirmed", "needs_official_row_crosscheck", "not_applicable_precommercial"}
COMPANY_GROUPS = {
    "中国移动": "内地运营商",
    "中国电信": "内地运营商",
    "中国联通": "内地运营商",
    "中国广电": "内地运营商",
    "Bharti Airtel": "印度运营商",
    "Reliance Jio": "印度运营商",
}
UNIT_LABELS = {
    "percent": "%",
    "million_subscribers": "百万户",
    "million_customers": "百万户",
    "million_base_stations": "百万座",
    "base_stations": "座",
    "HKD_per_user_month": "港元/户/月",
    "CNY_per_user_month": "元/户/月",
    "GB_per_user_month": "GB/户/月",
    "million_households": "百万户",
    "INR_per_user_month": "印度卢比/户/月",
    "INR_million": "百万印度卢比",
    "INR_crore": "千万印度卢比",
    "billion_GB": "十亿GB",
}


def text(row: dict, key: str) -> str:
    return str(row.get(key) or row.get("\ufeff" + key) or "").strip()


def main() -> None:
    cells: list[dict] = []
    company_meta: dict[str, dict] = {}
    metric_meta: dict[str, dict] = {}
    availability: dict[tuple[str, str], set[int]] = defaultdict(set)
    for source in SOURCES:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                status = text(row, "verification_status")
                raw = text(row, "official_value")
                company = text(row, "operator")
                metric = text(row, "metric_key")
                try:
                    year = int(text(row, "year"))
                    value = float(raw.replace(",", ""))
                except (TypeError, ValueError):
                    continue
                if not company or not metric or status in BLOCKED_STATUSES:
                    continue
                unit = text(row, "unit")
                company_meta.setdefault(company, {
                    "id": company,
                    "label": company,
                    "group": "香港运营商" if source == LOCAL_HK_SOURCE else COMPANY_GROUPS.get(company, "国际运营商"),
                })
                meta = metric_meta.setdefault(metric, {
                    "key": metric,
                    "label": text(row, "metric_zh") or metric,
                    "unit": unit,
                    "unitLabel": UNIT_LABELS.get(unit, unit),
                    "units": [],
                    "unitLabels": {},
                })
                if unit not in meta["units"]:
                    meta["units"].append(unit)
                meta["unitLabels"][unit] = UNIT_LABELS.get(unit, unit)
                availability[(company, metric)].add(year)
                cells.append({
                    "company": company,
                    "metric": metric,
                    "year": year,
                    "value": value,
                    "unit": unit,
                    "comparator": text(row, "comparator") or "=",
                    "period": text(row, "period"),
                    "periodEnd": text(row, "period_end"),
                    "scope": text(row, "scope"),
                    "basis": text(row, "basis"),
                    "status": status,
                    "source": text(row, "primary_source_url"),
                    "note": text(row, "quality_note"),
                })
    viable = {key for key, years in availability.items() if len(years) >= 2}
    cells = [cell for cell in cells if (cell["company"], cell["metric"]) in viable]
    active_companies = {cell["company"] for cell in cells}
    active_metrics = {cell["metric"] for cell in cells}
    digest = hashlib.sha256()
    for source in SOURCES:
        digest.update(source.name.encode("utf-8"))
        digest.update(source.read_bytes())
    payload = {
        "generatedAt": datetime.fromtimestamp(max(source.stat().st_mtime for source in SOURCES), tz=timezone.utc).isoformat(),
        "evidenceVersion": digest.hexdigest(),
        "sourceDatasets": [source.parent.name for source in SOURCES],
        "companies": [value for key, value in sorted(company_meta.items()) if key in active_companies],
        "metrics": [value for key, value in sorted(metric_meta.items(), key=lambda item: item[1]["label"]) if key in active_metrics],
        "cells": cells,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUTPUT} companies={len(payload['companies'])} metrics={len(payload['metrics'])} cells={len(cells)}")


if __name__ == "__main__":
    main()
