from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18/annual_operating_metrics_2016_2025.csv",
    ROOT / "agent_knowledge/local_hk_operator_operating_metrics_2016_2025/annual_metrics.csv",
)
OUTPUT = ROOT / "web/static/competitor-workbench-data.json"
BLOCKED_STATUSES = {"source_gap_confirmed", "needs_official_row_crosscheck", "not_applicable_precommercial"}


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
                raw = text(row, "official_value") or text(row, "value")
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
                    "group": "香港运营商" if source == SOURCES[1] else "内地运营商",
                })
                metric_meta.setdefault(metric, {
                    "key": metric,
                    "label": text(row, "metric_zh") or metric,
                    "unit": unit,
                })
                availability[(company, metric)].add(year)
                cells.append({
                    "company": company,
                    "metric": metric,
                    "year": year,
                    "value": value,
                    "unit": unit,
                    "status": status,
                    "source": text(row, "primary_source_url"),
                    "note": text(row, "quality_note"),
                })
    viable = {key for key, years in availability.items() if len(years) >= 2}
    cells = [cell for cell in cells if (cell["company"], cell["metric"]) in viable]
    active_companies = {cell["company"] for cell in cells}
    active_metrics = {cell["metric"] for cell in cells}
    payload = {
        "generatedAt": max(source.stat().st_mtime for source in SOURCES),
        "companies": [value for key, value in sorted(company_meta.items()) if key in active_companies],
        "metrics": [value for key, value in sorted(metric_meta.items(), key=lambda item: item[1]["label"]) if key in active_metrics],
        "cells": cells,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUTPUT} companies={len(payload['companies'])} metrics={len(payload['metrics'])} cells={len(cells)}")


if __name__ == "__main__":
    main()
