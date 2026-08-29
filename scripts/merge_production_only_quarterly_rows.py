#!/usr/bin/env python3
"""Merge the seven production-only rows without overwriting common rows.

The formal runtime had seven newer natural keys than the source package.  This
one-time migration embeds those rows, validates exact keys and values, and
updates every tabular/JSON view plus the manifest.  Existing common rows are
never replaced because several runtime values used a different period/scope.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from promote_2026_interim_official_rows import DATASET, atomic_csv, atomic_json, row_key


BASE = {
    "category": "carrier",
    "period_end": "Jun '26 Jun 30, 2026",
    "quality_status": "standardized_online_source_with_official_crosscheck_required",
    "verification_status": "needs_official_row_crosscheck",
    "official_value": "",
    "official_unit": "",
    "official_source_label": "",
    "official_source_url": "",
    "official_evidence": "",
    "verification_count": "0",
    "verification_method": "",
    "verification_sources": "[]",
    "verification_note": "",
    "daily_crawl_row_ref": "",
    "daily_evidence_hash": "",
}


def standardized(subject: str, legal_name: str, ticker: str, metric_key: str, metric_zh: str, value: str, unit: str) -> dict[str, str]:
    return {
        **BASE,
        "subject": subject,
        "legal_name": legal_name,
        "ticker": ticker,
        "period": "H1 2026" if subject == "3HK / Hutchison" else "Q2 2026",
        "grain": "half_year" if subject == "3HK / Hutchison" else "quarter",
        "metric_key": metric_key,
        "metric_zh": metric_zh,
        "value": value,
        "unit": unit,
        "disclosure_frequency": "quarterly_or_standardized_quarterly",
    }


ROWS: list[dict[str, str]] = [
    standardized("3HK / Hutchison", "Hutchison Telecommunications Hong Kong Holdings Limited", "0215.HK", "capital_expenditures", "资本开支", "-169", "millions HKD"),
    standardized("3HK / Hutchison", "Hutchison Telecommunications Hong Kong Holdings Limited", "0215.HK", "free_cash_flow", "自由现金流", "589", "millions HKD"),
    standardized("3HK / Hutchison", "Hutchison Telecommunications Hong Kong Holdings Limited", "0215.HK", "total_debt", "总债务", "529", "millions HKD"),
    {
        "subject": "i-CABLE", "category": "carrier", "legal_name": "i-CABLE", "ticker": "", "period": "FY 2025", "period_end": "FY 2025", "grain": "quarter", "metric_key": "capital_expenditures", "metric_zh": "资本开支", "value": "52", "unit": "millions HKD", "disclosure_frequency": "quarterly", "quality_status": "daily_official_crawl_promoted", "verification_status": "official_only", "official_value": "52", "official_unit": "millions HKD", "official_source_label": "PDF extracted by pdftotext", "official_source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0327/2026032703354.pdf", "official_evidence": "capital expenditure on property, plant and equipment amounted to approximately HK$52 million", "verification_count": "2", "verification_method": "daily_agent_gate_plus_issuer_report_index", "verification_sources": json.dumps([{"label": "每日爬虫核验的官方披露", "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0327/2026032703354.pdf", "evidence": "capital expenditure on property, plant and equipment amounted to approximately HK$52 million"}, {"label": "发行人官方财报入口", "url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en", "evidence": "用于核对发行人、披露期间与官方文件归属。"}], ensure_ascii=False), "verification_note": "每日03:00爬虫经Agent实体、指标、数值、期间和官方来源门禁后晋升。", "daily_crawl_row_ref": "row_17", "daily_evidence_hash": "1a394bf9f12f069125d395a50be9040921947320127a460c17b20a7871628f6b",
    },
    {
        "subject": "中国移动", "category": "carrier", "legal_name": "中国移动", "ticker": "", "period": "H1 2026", "period_end": "Jun '26 Jun 30, 2026", "grain": "half_year", "metric_key": "ebitda", "metric_zh": "EBITDA", "value": "173626", "unit": "millions CNY", "disclosure_frequency": "semiannual", "quality_status": "daily_official_crawl_promoted", "verification_status": "official_only", "official_value": "173626", "official_unit": "millions CNY", "official_source_label": "每日Agent核验官方披露", "official_source_url": "https://www.chinamobileltd.com/sc/ir/reports/ir2026_ashare.pdf", "official_evidence": "片段中明确列出 'EBITDA' 为 '173,626' 百万元人民币，并标注变化为 '-6.6%'。", "verification_count": "3", "verification_method": "daily_agent_gate_plus_issuer_report_index", "verification_sources": json.dumps([{"label": "官方披露1", "url": "https://www.chinamobileltd.com/sc/ir/reports/ir2026_ashare.pdf", "evidence": "片段中明确列出 'EBITDA' 为 '173,626' 百万元人民币，并标注变化为 '-6.6%'。"}, {"label": "官方披露2", "url": "https://www.chinamobileltd.com/en/ir/reports/ir2026.pdf", "evidence": "片段中明确列出 'EBITDA' 为 '173,626' 百万元人民币，并标注变化为 '-6.6%'。"}, {"label": "官方披露3", "url": "https://www.chinamobileltd.com/en/ir/reports.php", "evidence": "片段中明确列出 'EBITDA' 为 '173,626' 百万元人民币，并标注变化为 '-6.6%'。"}], ensure_ascii=False), "verification_note": "每日03:00爬虫经Agent实体、指标、数值、期间和官方来源门禁后晋升。", "daily_crawl_row_ref": "row_49", "daily_evidence_hash": "8e5f0aa410da4c7b674a784c39ebc8f1b6aca08c08c1d05f24fc62160966e975",
    },
    standardized("中国移动", "China Mobile Limited", "0941.HK", "total_debt", "总债务", "98,828", "millions CNY"),
    standardized("中国联通", "China Unicom (Hong Kong) Limited", "0762.HK", "total_debt", "总债务", "31,347", "millions CNY"),
]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    expected = {row_key(row) for row in ROWS}
    if len(expected) != 7:
        raise RuntimeError("migration must contain exactly seven unique natural keys")

    main_path = DATASET / "quarterly_metrics.csv"
    fields, rows = read_csv(main_path)
    existing = {row_key(row) for row in rows}
    overlap = existing & expected
    if overlap and overlap != expected:
        raise RuntimeError(f"partial migration state is not accepted: {sorted(overlap)}")
    if not overlap:
        rows.extend(ROWS)
    atomic_csv(main_path, rows, fields)

    payload_path = DATASET / "quarterly_metrics.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    json_rows = payload.get("rows")
    if not isinstance(json_rows, list):
        raise RuntimeError("quarterly_metrics.json rows missing")
    json_existing = {row_key(row) for row in json_rows if isinstance(row, dict)}
    if not expected <= json_existing:
        json_rows.extend(row for row in ROWS if row_key(row) not in json_existing)
    atomic_json(payload_path, payload)

    human_path = DATASET / "quarterly_metrics_human_readable.csv"
    human_fields, human_rows = read_csv(human_path)
    human_keys = {(row.get("subject", ""), row.get("period", ""), row.get("metric_zh", "")) for row in human_rows}
    for row in ROWS:
        key = (row["subject"], row["period"], row["metric_zh"])
        if key not in human_keys:
            human_rows.append({field: row.get(field, "") for field in human_fields})
    atomic_csv(human_path, human_rows, human_fields)

    online_path = DATASET / "online_verification_2026-06-18.csv"
    online_fields, _ = read_csv(online_path)
    atomic_csv(online_path, [{"row_no": number, **row} for number, row in enumerate(rows, 1)], online_fields)

    verified_path = DATASET / "official_verified_metrics_2026-06-18.csv"
    verified_fields, verified_rows = read_csv(verified_path)
    verified_keys = {row_key(row) for row in verified_rows}
    for row in ROWS:
        if row["verification_status"] == "official_only" and row_key(row) not in verified_keys:
            verified_rows.append(row)
    atomic_csv(verified_path, [{"row_no": number, **row} for number, row in enumerate(verified_rows, 1)], verified_fields)

    manifest_path = DATASET / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["row_count"] = len(rows)
    if isinstance(manifest.get("quality"), dict):
        manifest["quality"]["row_count"] = len(rows)
    atomic_json(manifest_path, manifest)

    print(json.dumps({"merged": 0 if overlap else 7, "row_count": len(rows), "keys": sorted(expected)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
