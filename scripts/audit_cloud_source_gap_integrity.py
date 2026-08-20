#!/usr/bin/env python3
"""Audit cloud vendor quarterly coverage and documented disclosure gaps.

The prediction-history coverage audit intentionally counts only comparable
quarterly value rows. This companion audit keeps the same 40-quarter cloud
target, but classifies every target period by evidence state so remaining gaps
are explicit and reviewable.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"
DEFAULT_INPUT = DEFAULT_DATASET / "quarterly_metrics.csv"
AUDIT_DATE = date.today().isoformat()

CLOUD_SUBJECTS = [
    "AWS",
    "Microsoft Azure / Intelligent Cloud",
    "Google Cloud",
    "Alibaba Cloud",
    "Tencent Cloud / Tencent FBS proxy",
    "Oracle Cloud",
]

FORECAST_VALUE_METRICS = {
    "AWS": {"revenue", "operating_income"},
    "Microsoft Azure / Intelligent Cloud": {
        "revenue",
        "operating_income",
        "azure_and_other_cloud_services_growth_yoy",
    },
    "Google Cloud": {"revenue", "operating_income", "revenue_growth_yoy"},
    "Alibaba Cloud": {"revenue", "adjusted_ebita", "revenue_growth_yoy", "adjusted_ebita_growth_yoy"},
    "Tencent Cloud / Tencent FBS proxy": {
        "fintech_business_services_revenue",
        "fintech_business_services_revenue_growth_yoy",
    },
    "Oracle Cloud": {
        "cloud_revenue",
        "iaas_revenue_growth_yoy",
        "saas_revenue_growth_yoy",
        "cloud_revenue_growth_yoy_cc",
    },
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def has_value(row: dict[str, str]) -> bool:
    text = str(row.get("official_value") or row.get("value") or "").strip()
    return bool(text and text.lower() not in {"nan", "n/a", "na", "none", "-"})


def period_sort_key(period: str) -> tuple[int, int] | None:
    match = re.match(r"Q([1-4])\s+(\d{4})$", period or "")
    if match:
        quarter, year = match.groups()
        return int(year), int(quarter)
    match = re.match(r"FY(\d{4})\s+Q([1-4])$", period or "")
    if match:
        year, quarter = match.groups()
        return int(year), int(quarter)
    return None


def period_label(year: int, quarter: int, fiscal: bool) -> str:
    return f"FY{year} Q{quarter}" if fiscal else f"Q{quarter} {year}"


def target_periods_for_subject(subject: str, rows: list[dict[str, str]]) -> list[str]:
    keys = [
        key
        for row in rows
        if row.get("subject") == subject and row.get("grain") == "quarter"
        for key in [period_sort_key(row.get("period", ""))]
        if key
    ]
    if not keys:
        return []
    last_year, last_quarter = max(keys)
    last_index = last_year * 4 + last_quarter
    start_index = last_index - 40 + 1
    fiscal = any(
        row.get("subject") == subject
        and row.get("grain") == "quarter"
        and (row.get("period") or "").startswith("FY")
        for row in rows
    )
    labels: list[str] = []
    for idx in range(start_index, last_index + 1):
        year = (idx - 1) // 4
        quarter = idx - year * 4
        labels.append(period_label(year, quarter, fiscal))
    return labels


def best_source_gap_row(rows: list[dict[str, str]]) -> dict[str, str] | None:
    source_gap_rows = [row for row in rows if row.get("verification_status") == "source_gap_confirmed"]
    if not source_gap_rows:
        return None
    return sorted(
        source_gap_rows,
        key=lambda row: (
            row.get("metric_key") != "cloud_quarterly_disclosure_status",
            -int(row.get("verification_count") or 0),
            row.get("metric_key", ""),
        ),
    )[0]


def classify_period(subject: str, period: str, rows: list[dict[str, str]]) -> dict[str, str]:
    target_metrics = FORECAST_VALUE_METRICS.get(subject, set())
    forecast_rows = [
        row
        for row in rows
        if row.get("grain") == "quarter"
        and row.get("metric_key") in target_metrics
        and has_value(row)
        and row.get("verification_status") != "source_gap_confirmed"
    ]
    annual_only_rows = [
        row
        for row in rows
        if row.get("grain") == "period"
        and has_value(row)
        and row.get("verification_status") != "source_gap_confirmed"
    ]
    non_forecast_value_rows = [
        row
        for row in rows
        if row.get("grain") == "quarter"
        and row.get("metric_key") not in target_metrics
        and has_value(row)
        and row.get("verification_status") != "source_gap_confirmed"
    ]
    gap_row = best_source_gap_row(rows)

    if forecast_rows:
        status = "forecast_value_available"
        evidence_row = sorted(forecast_rows, key=lambda row: row.get("metric_key", ""))[0]
        note = "Comparable official/public quarterly value exists for the retained cloud series."
    elif non_forecast_value_rows:
        status = "non_forecast_legacy_value_recorded"
        evidence_row = sorted(non_forecast_value_rows, key=lambda row: row.get("metric_key", ""))[0]
        note = "Official/public quarterly value exists, but it is outside the retained forecasting series and does not count as prediction-ready coverage."
    elif annual_only_rows:
        status = "annual_only_recorded"
        evidence_row = sorted(annual_only_rows, key=lambda row: row.get("metric_key", ""))[0]
        note = "Only annual/non-quarterly official value evidence is recorded; do not split into quarters."
    elif gap_row:
        status = "documented_source_gap"
        evidence_row = gap_row
        note = "Official/public sources were checked and the comparable quarterly cloud series is not disclosed."
    else:
        status = "missing_boundary_record"
        evidence_row = {}
        note = "No value row or documented source-gap row found for this target period."

    source_label = evidence_row.get("official_source_label", "")
    source_url = evidence_row.get("official_source_url", "")
    evidence = evidence_row.get("official_evidence", "")
    return {
        "subject": subject,
        "target_period": period,
        "status": status,
        "metric_key": evidence_row.get("metric_key", ""),
        "grain": evidence_row.get("grain", ""),
        "verification_status": evidence_row.get("verification_status", ""),
        "verification_count": evidence_row.get("verification_count", ""),
        "official_source_label": source_label,
        "official_source_url": source_url,
        "evidence_note": evidence[:500],
        "audit_note": note,
    }


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, str]], path: Path, input_path: Path) -> None:
    by_subject: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_subject[row["subject"]].append(row)

    lines = [
        f"# Cloud Source-Gap Integrity Audit ({AUDIT_DATE})",
        "",
        f"- Source package: `{input_path.relative_to(ROOT)}`",
        "- Scope: 40 target quarters per cloud vendor, ending at the latest quarter observed for that vendor.",
        "- `forecast_value_available` counts only comparable quarterly rows with official/public values for the retained forecasting series.",
        "- `non_forecast_legacy_value_recorded`, `annual_only_recorded`, and `documented_source_gap` are evidence records; they do not count as prediction-ready quarterly coverage.",
        "",
        "## Summary",
        "",
        "| Subject | Forecast quarters | Non-forecast legacy quarters | Annual-only periods | Documented source gaps | Missing boundary records |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for subject in CLOUD_SUBJECTS:
        subject_rows = by_subject.get(subject, [])
        counts = defaultdict(int)
        for row in subject_rows:
            counts[row["status"]] += 1
        lines.append(
            f"| {subject} | {counts['forecast_value_available']} | {counts['non_forecast_legacy_value_recorded']} | {counts['annual_only_recorded']} | {counts['documented_source_gap']} | {counts['missing_boundary_record']} |"
        )

    lines.extend(["", "## Non-Forecast Evidence Periods", ""])
    for subject in CLOUD_SUBJECTS:
        subject_rows = [
            row
            for row in by_subject.get(subject, [])
            if row["status"] in {
                "non_forecast_legacy_value_recorded",
                "annual_only_recorded",
                "documented_source_gap",
                "missing_boundary_record",
            }
        ]
        if not subject_rows:
            continue
        lines.append(f"### {subject}")
        for row in subject_rows:
            source = row["official_source_label"] or "no source"
            lines.append(
                f"- {row['target_period']}: {row['status']} / {row['metric_key'] or '-'} / verification_count={row['verification_count'] or '0'} / {source}"
            )
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    rows = read_rows(DEFAULT_INPUT)
    by_subject_period: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        subject = row.get("subject", "")
        if subject not in CLOUD_SUBJECTS:
            continue
        by_subject_period[(subject, row.get("period", ""))].append(row)

    audit_rows: list[dict[str, str]] = []
    for subject in CLOUD_SUBJECTS:
        for period in target_periods_for_subject(subject, rows):
            audit_rows.append(classify_period(subject, period, by_subject_period.get((subject, period), [])))

    out_csv = DEFAULT_DATASET / f"cloud_source_gap_integrity_{AUDIT_DATE}.csv"
    out_md = DEFAULT_DATASET / f"cloud_source_gap_integrity_{AUDIT_DATE}.md"
    write_csv(audit_rows, out_csv)
    write_markdown(audit_rows, out_md, DEFAULT_INPUT)
    print(f"Wrote {out_csv.relative_to(ROOT)}")
    print(f"Wrote {out_md.relative_to(ROOT)}")
    print(f"Rows: {len(audit_rows)}")


if __name__ == "__main__":
    main()
