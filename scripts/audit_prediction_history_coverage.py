#!/usr/bin/env python3
"""Audit whether the quarterly competitor package is prediction-ready.

This does not certify data values. It reports the current historical window
against the active collection goal: cloud vendors require a hard 10-year
quarterly window; missing public segment/proxy disclosure must be documented as
source gaps and does not count toward the coverage window. Non-cloud quarterly
issuers require at least 7 years and preferably 10 years; semiannual-only
issuers require 10 years.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18"
DEFAULT_INPUT = DEFAULT_DATASET / "quarterly_metrics.csv"
AUDIT_DATE = date.today().isoformat()


QUARTERLY_TARGET_SUBJECTS = {
    "中国移动",
    "中国电信",
    "中国联通",
    "中国铁塔",
}

CLOUD_QUARTERLY_TARGET_SUBJECTS = {
    "AWS",
    "Microsoft Azure / Intelligent Cloud",
    "Google Cloud",
    "Alibaba Cloud",
    "Tencent Cloud / Tencent FBS proxy",
    "Oracle Cloud",
}

CLOUD_FORECAST_COVERAGE_METRICS = {
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
        "cloud_revenue_growth_yoy",
        "cloud_application_revenue",
        "cloud_application_revenue_growth_yoy",
        "cloud_infrastructure_revenue",
        "cloud_infrastructure_revenue_growth_yoy",
    },
}

SEMIANNUAL_TARGET_SUBJECTS = {
    "HKT / csl / 1O1O",
    "3HK / Hutchison",
    "SmarTone",
    "HKBN",
    "i-CABLE",
}

SOURCE_GAP_SUBJECTS = {
    "HGC",
    "Huawei Cloud / Cloud Computing",
}


@dataclass(frozen=True)
class PeriodKey:
    year: int
    slot: int
    label: str


def period_key(label: str, grain: str) -> PeriodKey | None:
    label = (label or "").strip()
    match = re.match(r"Q([1-4])\s+(\d{4})$", label)
    if match:
        quarter, year = match.groups()
        return PeriodKey(int(year), int(quarter), label)

    match = re.match(r"H([1-2])\s+(\d{4})$", label)
    if match:
        half, year = match.groups()
        return PeriodKey(int(year), int(half), label)

    match = re.match(r"FY(\d{4})\s+Q([1-4])$", label)
    if match:
        year, quarter = match.groups()
        return PeriodKey(int(year), int(quarter), label)

    if grain == "source_gap":
        return None
    return None


def has_period_value(row: dict[str, str]) -> bool:
    if row.get("verification_status") == "source_gap_confirmed":
        return False
    text = str(row.get("official_value") or row.get("value") or "").strip()
    if not text or text.lower() in {"nan", "n/a", "na", "none", "-"}:
        return False
    return True


def is_coverage_metric(subject: str, row: dict[str, str]) -> bool:
    """Return whether this value row belongs to the retained prediction series."""
    if subject not in CLOUD_QUARTERLY_TARGET_SUBJECTS:
        return True
    allowed = CLOUD_FORECAST_COVERAGE_METRICS.get(subject)
    return bool(allowed and row.get("metric_key") in allowed)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def target_profile(subject: str, observed_grains: Counter[str]) -> tuple[str, int, int, str]:
    if subject in SOURCE_GAP_SUBJECTS or observed_grains.get("source_gap"):
        return "source_gap", 0, 0, "Keep as source-gap unless public periodic data is found; do not estimate."
    if subject in SEMIANNUAL_TARGET_SUBJECTS or (
        observed_grains.get("half_year") and not observed_grains.get("quarter")
    ):
        return "half_year", 20, 20, "Target 10 years of semiannual H1/H2 records."
    if subject in CLOUD_QUARTERLY_TARGET_SUBJECTS:
        return "quarter", 40, 40, "Cloud vendor quarterly history target is a hard 10 years / 40 quarters; source-gap records document non-disclosure but do not count as coverage."
    if subject in QUARTERLY_TARGET_SUBJECTS or observed_grains.get("quarter"):
        return "quarter", 28, 40, "Target at least 7 years of quarters; prefer 10 years if official/public data exists."
    return "periodic", 0, 0, "Classify disclosure grain before expanding."


def period_to_index(key: tuple[int, int], grain: str) -> int:
    year, slot = key
    periods_per_year = 4 if grain == "quarter" else 2
    return year * periods_per_year + slot


def index_to_label(index: int, grain: str, fiscal_prefix: bool) -> str:
    periods_per_year = 4 if grain == "quarter" else 2
    year = (index - 1) // periods_per_year
    slot = index - year * periods_per_year
    if grain == "quarter":
        return f"FY{year} Q{slot}" if fiscal_prefix else f"Q{slot} {year}"
    return f"H{slot} {year}"


def missing_period_labels(
    distinct_periods: list[tuple[int, int]],
    target_grain: str,
    target_periods: int,
    labels: dict[tuple[int, int], str],
) -> list[str]:
    if not distinct_periods or target_grain not in {"quarter", "half_year"} or not target_periods:
        return []
    existing = {period_to_index(key, target_grain) for key in distinct_periods}
    last_index = max(existing)
    start_index = last_index - target_periods + 1
    fiscal_prefix = any(label.startswith("FY") for label in labels.values())
    return [
        index_to_label(idx, target_grain, fiscal_prefix)
        for idx in range(start_index, last_index + 1)
        if idx not in existing
    ]


def documented_boundary_periods(
    subject: str,
    rows: list[dict[str, str]],
    target_grain: str,
) -> set[str]:
    """Return target-period labels with documented non-value evidence."""
    labels: set[str] = set()
    if target_grain not in {"quarter", "half_year"}:
        return labels
    for row in rows:
        period = row.get("period", "")
        if row.get("verification_status") == "source_gap_confirmed":
            labels.add(period)
            continue
        if subject in CLOUD_QUARTERLY_TARGET_SUBJECTS:
            if row.get("grain") != target_grain:
                continue
            if is_coverage_metric(subject, row):
                continue
            if has_period_value(row):
                labels.add(period)
    return labels


def summarize_subject(subject: str, rows: list[dict[str, str]]) -> dict[str, str]:
    category = next((row.get("category", "") for row in rows if row.get("category")), "")
    grains = Counter(row.get("grain", "") for row in rows)
    statuses = Counter(row.get("verification_status", "") for row in rows)
    metrics = sorted({row.get("metric_key", "") for row in rows if row.get("metric_key")})
    verified_multi = sum(1 for row in rows if int(row.get("verification_count") or 0) >= 2)
    target_grain, min_periods, preferred_periods, target_note = target_profile(subject, grains)

    period_keys = []
    period_labels = {}
    for row in rows:
        grain = row.get("grain", "")
        if target_grain in {"quarter", "half_year"} and grain != target_grain:
            continue
        if not is_coverage_metric(subject, row):
            continue
        if not has_period_value(row):
            continue
        key = period_key(row.get("period", ""), grain)
        if key:
            period_keys.append(key)
            period_labels[(key.year, key.slot)] = key.label

    distinct_periods = sorted(set((key.year, key.slot) for key in period_keys))
    period_count = len(distinct_periods)
    first = period_labels.get(distinct_periods[0], "") if distinct_periods else ""
    last = period_labels.get(distinct_periods[-1], "") if distinct_periods else ""

    if target_grain == "quarter":
        current_years = period_count / 4
    elif target_grain == "half_year":
        current_years = period_count / 2
    else:
        current_years = 0

    missing_min = max(0, min_periods - period_count)
    missing_preferred = max(0, preferred_periods - period_count)
    missing_min_labels = missing_period_labels(distinct_periods, target_grain, min_periods, period_labels)
    missing_preferred_labels = missing_period_labels(
        distinct_periods,
        target_grain,
        preferred_periods,
        period_labels,
    )
    boundary_periods = documented_boundary_periods(subject, rows, target_grain)
    missing_preferred_documented = [
        label for label in missing_preferred_labels if label in boundary_periods
    ]
    missing_preferred_undocumented = [
        label for label in missing_preferred_labels if label not in boundary_periods
    ]
    if target_grain == "source_gap":
        expansion_status = "not_applicable_source_gap"
    elif missing_min == 0 and missing_preferred == 0:
        expansion_status = "meets_preferred_window"
    elif missing_min == 0:
        expansion_status = "meets_minimum_needs_10y_extension"
    elif missing_min and missing_preferred_labels and not missing_preferred_undocumented:
        expansion_status = "below_minimum_with_documented_boundaries"
    else:
        expansion_status = "below_minimum_needs_extension"

    return {
        "subject": subject,
        "category": category,
        "target_grain": target_grain,
        "row_count": str(len(rows)),
        "metric_count": str(len(metrics)),
        "distinct_period_count": str(period_count),
        "current_years_equivalent": f"{current_years:.1f}" if current_years else "",
        "first_period": first,
        "last_period": last,
        "minimum_target_periods": str(min_periods) if min_periods else "",
        "preferred_target_periods": str(preferred_periods) if preferred_periods else "",
        "missing_periods_to_7y_or_10y_minimum": str(missing_min) if min_periods else "",
        "missing_minimum_period_labels": "; ".join(missing_min_labels),
        "missing_periods_to_10y_preferred": str(missing_preferred) if preferred_periods else "",
        "missing_preferred_period_labels": "; ".join(missing_preferred_labels),
        "missing_preferred_documented_boundary_labels": "; ".join(missing_preferred_documented),
        "missing_preferred_undocumented_labels": "; ".join(missing_preferred_undocumented),
        "expansion_status": expansion_status,
        "verification_status_counts": "; ".join(f"{key}:{value}" for key, value in sorted(statuses.items())),
        "rows_with_verification_count_ge_2": str(verified_multi),
        "grain_counts": "; ".join(f"{key}:{value}" for key, value in sorted(grains.items())),
        "target_note": target_note,
    }


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, str]], path: Path, input_path: Path) -> None:
    status_counts = Counter(row["expansion_status"] for row in rows)
    lines = [
        f"# Prediction History Coverage Audit ({AUDIT_DATE})",
        "",
        f"- Source package: `{input_path.relative_to(ROOT)}`",
        "- Purpose: identify the historical-period gaps before collecting prediction-ready history; cloud vendors are hard 10-year / 40-quarter targets.",
        "- This audit is coverage control only; value correctness still depends on row-level official/public source verification.",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(
        [
            "",
            "## Subject Coverage",
            "",
            "| Subject | Grain target | Current span | Periods | Missing minimum | Missing preferred | Status |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        span = f"{row['first_period']} to {row['last_period']}".strip(" to")
        lines.append(
            "| {subject} | {target_grain} | {span} | {distinct_period_count} | {missing_periods_to_7y_or_10y_minimum} | {missing_periods_to_10y_preferred} | {expansion_status} |".format(
                span=span or "-",
                **row,
            )
        )
    lines.extend(
        [
            "",
            "## Missing Periods",
            "",
        ]
    )
    for row in rows:
        if not row["missing_preferred_period_labels"]:
            continue
        lines.extend(
            [
                f"### {row['subject']}",
                "",
                f"- Missing minimum window: {row['missing_minimum_period_labels'] or '-'}",
                f"- Missing 10-year preferred window: {row['missing_preferred_period_labels']}",
                f"- Documented boundary periods: {row.get('missing_preferred_documented_boundary_labels') or '-'}",
                f"- Undocumented missing periods: {row.get('missing_preferred_undocumented_labels') or '-'}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## Immediate Implications",
            "",
            "- The existing standardized carrier snapshot only proves the current 5-year window; older periods must be added from official reports, filings, or other directly verified public sources.",
            "- Cloud vendors are the largest gap and are now treated as hard 10-year / 40-quarter targets; source-gap records document non-disclosure but do not count as coverage.",
            "- HGC and Huawei Cloud remain source-gap records unless periodic public cloud/financial segment data is found; do not estimate missing values.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    input_path = DEFAULT_INPUT
    rows = read_rows(input_path)
    by_subject: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_subject[row["subject"]].append(row)

    audit_rows = [summarize_subject(subject, by_subject[subject]) for subject in sorted(by_subject)]
    out_csv = input_path.parent / f"prediction_history_coverage_{AUDIT_DATE}.csv"
    out_md = input_path.parent / f"prediction_history_coverage_{AUDIT_DATE}.md"
    write_csv(audit_rows, out_csv)
    write_markdown(audit_rows, out_md, input_path)
    print(f"Wrote {out_csv.relative_to(ROOT)}")
    print(f"Wrote {out_md.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
