from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
QUARTERLY_METRICS_PATH = (
    ROOT
    / "agent_knowledge"
    / "quarterly_competitor_metrics_2026-06-18"
    / "quarterly_metrics.json"
)

COMPANIES = (
    {"id": "cmhk", "label": "CMHK", "subject": ""},
    {"id": "hkt", "label": "HKT", "subject": "HKT / csl / 1O1O"},
    {"id": "three", "label": "3香港", "subject": "3HK / Hutchison"},
    {"id": "smartone", "label": "SmarTone", "subject": "SmarTone"},
    {"id": "hkbn", "label": "HKBN", "subject": "HKBN"},
)

METRICS = {
    "revenue": {"label": "营运收入", "unit": "亿港元", "source_key": "revenue", "scale": 0.01},
    "ebitda": {"label": "EBITDA", "unit": "亿港元", "source_key": "ebitda", "scale": 0.01},
    "net_profit": {"label": "净利润", "unit": "亿港元", "source_key": "net_income", "scale": 0.01},
    "capital_expenditure": {"label": "资本支出", "unit": "亿港元", "source_key": "capital_expenditures", "scale": 0.01, "absolute": True},
    "cash": {"label": "现金及现金等值", "unit": "亿港元", "source_key": "cash_and_equivalents", "scale": 0.01},
    "free_cash_flow": {"label": "自由现金流", "unit": "亿港元", "source_key": "free_cash_flow", "scale": 0.01},
    "ebitda_margin": {"label": "EBITDA率", "unit": "%", "derived": "ebitda_margin"},
    "net_margin": {"label": "净利润率", "unit": "%", "derived": "net_margin"},
}

CMHK_CURRENT = {
    "revenue": {"value": 96.8, "period": "驾驶舱当前口径"},
    "ebitda": {"value": 34.8, "period": "驾驶舱当前口径"},
    "net_profit": {"value": 12.4, "period": "驾驶舱当前口径"},
    "capital_expenditure": {"value": 18.9, "period": "驾驶舱当前口径"},
    "cash": {"value": 42.8, "period": "驾驶舱当前口径"},
    "free_cash_flow": {"value": 16.2, "period": "驾驶舱当前口径"},
    "ebitda_margin": {"value": 35.9, "period": "驾驶舱当前口径"},
    "net_margin": {"value": 12.8, "period": "驾驶舱当前口径"},
}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _official_value(row: dict[str, Any]) -> float | None:
    official = _number(row.get("official_value"))
    if official is not None and row.get("verification_status") in {
        "official_match",
        "official_only",
        "official_conflict",
    }:
        return official
    return None


def _latest_by_metric(rows: list[dict[str, Any]], subject: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("subject") != subject or not row.get("metric_key"):
            continue
        if _official_value(row) is None:
            continue
        latest[str(row["metric_key"])] = row
    return latest


def _record(row: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any] | None:
    value = _official_value(row)
    if value is None:
        return None
    if metric.get("absolute"):
        value = abs(value)
    value *= float(metric.get("scale") or 1)
    return {
        "value": round(value, 2),
        "period": str(row.get("period") or ""),
        "period_end": str(row.get("period_end") or ""),
        "source_label": str(row.get("official_source_label") or ""),
        "source_url": str(row.get("official_source_url") or ""),
        "verification_status": str(row.get("verification_status") or ""),
    }


def _derived_margin(
    latest: dict[str, dict[str, Any]],
    numerator_key: str,
) -> dict[str, Any] | None:
    numerator = latest.get(numerator_key)
    revenue = latest.get("revenue")
    if not numerator or not revenue or numerator.get("period") != revenue.get("period"):
        return None
    numerator_value = _official_value(numerator)
    revenue_value = _official_value(revenue)
    if numerator_value is None or revenue_value in (None, 0):
        return None
    return {
        "value": round(numerator_value / revenue_value * 100, 1),
        "period": str(revenue.get("period") or ""),
        "period_end": str(revenue.get("period_end") or ""),
        "source_label": str(revenue.get("official_source_label") or ""),
        "source_url": str(revenue.get("official_source_url") or ""),
        "verification_status": "derived_from_verified_values",
    }


def build_company_benchmarks() -> dict[str, Any]:
    payload = json.loads(QUARTERLY_METRICS_PATH.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    values: dict[str, dict[str, Any]] = {"cmhk": dict(CMHK_CURRENT)}

    for company in COMPANIES[1:]:
        latest = _latest_by_metric(rows, str(company["subject"]))
        company_values: dict[str, Any] = {}
        for metric_id, metric in METRICS.items():
            if metric.get("source_key"):
                row = latest.get(str(metric["source_key"]))
                record = _record(row, metric) if row else None
            elif metric.get("derived") == "ebitda_margin":
                record = _derived_margin(latest, "ebitda")
            elif metric.get("derived") == "net_margin":
                record = _derived_margin(latest, "net_income")
            else:
                record = None
            if record:
                company_values[metric_id] = record
        values[str(company["id"])] = company_values

    return {
        "ok": True,
        "generated_at": str(payload.get("generated_at") or ""),
        "comparison_basis": "各公司最新可核验半年度披露；期间不同，不用于直接合计。",
        "companies": [{"id": item["id"], "label": item["label"]} for item in COMPANIES],
        "metrics": {
            metric_id: {"label": metric["label"], "unit": metric["unit"]}
            for metric_id, metric in METRICS.items()
        },
        "values": values,
    }


if __name__ == "__main__":
    print(json.dumps(build_company_benchmarks(), ensure_ascii=False, indent=2))
