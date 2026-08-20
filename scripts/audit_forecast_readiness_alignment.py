#!/usr/bin/env python3
"""Audit that forecast tooling respects current CMHK data boundaries."""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import SELECTED_DATASET_IDS, forecast_quarterly_metric  # noqa: E402

AUDIT_DATE = date.today().isoformat()
OUT_ROOT = ROOT / "agent_knowledge" / "forecast_readiness_audits"

CASES = [
    {
        "case_id": "aws_revenue_strong_window",
        "subject": "AWS",
        "metric_key": "revenue",
        "horizon": 1,
        "expected_status": "success",
        "expected_samples": 40,
        "expected_grain_label": "季度",
        "must_include": ["Q1 2016 至 Q4 2025", "source_gap 不参与拟合"],
    },
    {
        "case_id": "alibaba_revenue_excludes_legacy",
        "subject": "Alibaba Cloud",
        "metric_key": "revenue",
        "horizon": 1,
        "expected_status": "success",
        "expected_samples": 16,
        "expected_grain_label": "季度",
        "must_include": ["FY2023 Q1 至 FY2026 Q4", "source_gap 不参与拟合"],
        "must_exclude": ["FY2022 Q1 至 FY2026 Q4", "20 个季度"],
    },
    {
        "case_id": "alibaba_legacy_metric_rejected",
        "subject": "Alibaba Cloud",
        "metric_key": "legacy_cloud_segment_revenue_including_dingtalk",
        "horizon": 1,
        "expected_status": "failure",
        "expected_samples": 4,
        "expected_grain_label": "季度",
        "must_include": ["少于 8 个", "不适合做趋势预测"],
    },
    {
        "case_id": "hkt_half_year_supported",
        "subject": "HKT / csl / 1O1O",
        "metric_key": "revenue",
        "horizon": 1,
        "expected_status": "success",
        "expected_samples": 20,
        "expected_grain_label": "半年度",
        "must_include": ["H1 2016 至 H2 2025", "source_gap 不参与拟合"],
    },
    {
        "case_id": "hgc_source_gap_rejected",
        "subject": "HGC",
        "metric_key": "revenue",
        "horizon": 1,
        "expected_status": "failure",
        "expected_samples": 0,
        "expected_grain_label": "季度",
        "must_include": ["可用季度样本只有 0 个", "不适合做趋势预测"],
    },
    {
        "case_id": "macro_policy_not_forecast_target",
        "subject": "Hong Kong macro environment",
        "metric_key": "retail_sales_value_index",
        "horizon": 1,
        "expected_status": "failure",
        "expected_samples": 0,
        "expected_grain_label": "季度",
        "must_include": ["可用季度样本只有 0 个", "不适合做趋势预测"],
        "must_exclude": ["cmhk_macro_policy_2026-06-19"],
    },
    {
        "case_id": "selected_latest_quarterly_package_allowed",
        "subject": "AWS",
        "metric_key": "revenue",
        "horizon": 1,
        "selected_dataset_ids": ["quarterly_competitor_metrics_2026-06-18"],
        "expected_status": "success",
        "expected_samples": 40,
        "expected_grain_label": "季度",
        "must_include": ["quarterly_competitor_metrics_2026-06-18", "Q1 2016 至 Q4 2025"],
        "must_exclude": ["quarterly_competitor_metrics_2026-06-17"],
    },
    {
        "case_id": "selected_superseded_quarterly_package_rejected",
        "subject": "AWS",
        "metric_key": "revenue",
        "horizon": 1,
        "selected_dataset_ids": ["quarterly_competitor_metrics_2026-06-17"],
        "expected_status": "failure",
        "expected_samples": None,
        "expected_grain_label": "",
        "must_include": ["当前未选择可用的 quarterly_competitor_metrics 数据库"],
        "must_exclude": ["历史样本", "quarterly_competitor_metrics_2026-06-17/quarterly_metrics.csv"],
    },
]


def call_forecast(case: dict[str, Any]) -> str:
    spec = {
        "subject": case["subject"],
        "metric_key": case["metric_key"],
        "horizon": case.get("horizon", 1),
    }
    selected_dataset_ids = case.get("selected_dataset_ids")
    if selected_dataset_ids is None:
        return str(forecast_quarterly_metric.invoke(json.dumps(spec, ensure_ascii=False)))
    token = SELECTED_DATASET_IDS.set(set(selected_dataset_ids))
    try:
        return str(forecast_quarterly_metric.invoke(json.dumps(spec, ensure_ascii=False)))
    finally:
        SELECTED_DATASET_IDS.reset(token)


def parse_sample_count(text: str) -> int | None:
    match = re.search(r"历史样本：(\d+)\s*个", text)
    if match:
        return int(match.group(1))
    match = re.search(r"样本只有\s*(\d+)\s*个", text)
    if match:
        return int(match.group(1))
    return None


def audit_case(case: dict[str, Any]) -> dict[str, Any]:
    response = call_forecast(case)
    expected_status = case["expected_status"]
    actual_status = "failure" if response.startswith("预测失败") else "success"
    sample_count = parse_sample_count(response)
    issues: list[str] = []
    if actual_status != expected_status:
        issues.append("status_mismatch")
    if case.get("expected_samples") is not None and sample_count != case.get("expected_samples"):
        issues.append("sample_count_mismatch")
    if case.get("expected_grain_label") and case["expected_grain_label"] not in response:
        issues.append("grain_label_missing")
    for needle in case.get("must_include", []):
        if needle not in response:
            issues.append(f"missing_text:{needle}")
    for needle in case.get("must_exclude", []):
        if needle in response:
            issues.append(f"forbidden_text:{needle}")
    return {
        "case_id": case["case_id"],
        "subject": case["subject"],
        "metric_key": case["metric_key"],
        "expected_status": expected_status,
        "actual_status": actual_status,
        "expected_samples": case.get("expected_samples"),
        "actual_samples": sample_count,
        "status": "pass" if not issues else "fail",
        "issues": ";".join(issues),
        "response_excerpt": response[:800].replace("\n", " "),
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "case_id",
        "subject",
        "metric_key",
        "expected_status",
        "actual_status",
        "expected_samples",
        "actual_samples",
        "status",
        "issues",
        "response_excerpt",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    lines = [
        f"# Forecast Readiness Alignment Audit ({AUDIT_DATE})",
        "",
        f"- Cases checked: {len(rows)}",
        f"- Passed: {passed}",
        f"- Failed: {len(rows) - passed}",
        "",
        "## Cases",
        "",
        "| Case | Subject | Metric | Expected | Actual | Samples | Status | Issues |",
        "| --- | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {case_id} | {subject} | {metric_key} | {expected_status} | {actual_status} | {actual_samples} | {status} | {issues} |".format(
                **{key: row.get(key, "") for key in [
                    "case_id",
                    "subject",
                    "metric_key",
                    "expected_status",
                    "actual_status",
                    "actual_samples",
                    "status",
                    "issues",
                ]}
            )
        )
    lines.extend(
        [
            "",
            "## Boundary Assertions",
            "",
            "- AWS revenue remains a 40-quarter strong-window forecast series.",
            "- Alibaba Cloud revenue uses only the post-restatement Cloud Intelligence Group revenue series; FY2022 legacy Cloud segment rows are rejected as too short/non-forecast evidence.",
            "- HKT revenue is forecast as a half-year series, not mislabeled as quarterly.",
            "- HGC source-gap and macro policy rows are rejected as direct numeric forecast targets.",
            "- This audit checks tool behavior; value correctness remains covered by row-level official/source integrity audits.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(rows: list[dict[str, Any]], path: Path, csv_path: Path, md_path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    failed = len(rows) - passed
    manifest = {
        "id": "forecast_readiness_audits",
        "title": "小竞AI预测工具边界审计",
        "summary": "检查 forecast_quarterly_metric 是否按当前季度/半年度数据边界排除 source-gap、legacy 非预测口径和宏观政策事件。",
        "source_type": "local_audit",
        "scope": "小竞AI趋势预测、半年度预测、source-gap 拒绝和宏观政策解释边界。",
        "updated_at": AUDIT_DATE,
        "tags": ["audit", "forecast", "trend", "source-gap", "legacy-boundary"],
        "keywords": [
            "forecast_readiness_audits",
            "forecast_quarterly_metric",
            "source_gap_confirmed",
            "legacy_cloud_segment_revenue_including_dingtalk",
            "cmhk_macro_policy",
        ],
        "entrypoints": [md_path.name, csv_path.name],
        "quality": {
            "status": "pass" if failed == 0 else "fail",
            "row_count": len(rows),
            "cases_checked": len(rows),
            "passed": passed,
            "failed": failed,
            "notes": [
                "审计调用真实 forecast_quarterly_metric 工具输出，而不是只检查 CSV。",
                "source-gap、legacy 非预测口径和宏观政策事件不得作为公司季度数值预测目标。",
                "半年度主体必须以半年度样本和半年度预测标签输出。",
            ],
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = [audit_case(case) for case in CASES]
    csv_path = OUT_ROOT / f"forecast_readiness_alignment_{AUDIT_DATE}.csv"
    md_path = OUT_ROOT / f"forecast_readiness_alignment_{AUDIT_DATE}.md"
    manifest_path = OUT_ROOT / "manifest.json"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path)
    write_manifest(rows, manifest_path, csv_path, md_path)
    print(f"wrote {csv_path.relative_to(ROOT)}")
    print(f"wrote {md_path.relative_to(ROOT)}")
    print(f"wrote {manifest_path.relative_to(ROOT)}")
    failed = [row for row in rows if row["status"] != "pass"]
    if failed:
        for row in failed:
            print(f"failed {row['case_id']}: {row['issues']}")
        raise SystemExit(1)
    print("all forecast alignment cases passed")


if __name__ == "__main__":
    main()
