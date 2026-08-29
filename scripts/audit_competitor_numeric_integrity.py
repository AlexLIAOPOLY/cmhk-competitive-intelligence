#!/usr/bin/env python3
"""Create a row-level integrity and search-boundary audit for competitor numbers.

The audit never treats a low source count as permission to hide a disclosed
number.  It separates value availability, evidence strength, conflicts, and
the recorded search boundary so a confirmed targeted-search gap cannot be
confused with a row for which no targeted search was documented.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "agent_knowledge"
OUTPUT = KNOWLEDGE / "knowledge_integrity_audits"
AUDIT_DATE = datetime.now().astimezone().date().isoformat()

DATASETS = (
    {
        "id": "quarterly_competitor_metrics_2026-06-18",
        "path": KNOWLEDGE
        / "quarterly_competitor_metrics_2026-06-18"
        / "quarterly_metrics.csv",
        "entity": "subject",
        "period": "period",
        "metric": "metric_key",
        "value_fields": ("official_value",),
        "unit_fields": ("official_unit", "unit"),
        "status": "verification_status",
        "key_fields": ("subject", "period", "grain", "metric_key"),
        "source_mode": "embedded",
    },
    {
        "id": "global_top5_operators_2016_2025",
        "path": KNOWLEDGE / "global_top5_operators_2016_2025" / "annual_metrics.csv",
        "registry": KNOWLEDGE / "global_top5_operators_2016_2025" / "sources.json",
        "entity": "operator",
        "period": "period",
        "metric": "metric_key",
        "value_fields": ("official_value", "value"),
        "unit_fields": ("unit",),
        "status": "verification_status",
        "key_fields": ("operator_id", "period", "grain", "metric_key"),
        "source_mode": "registry",
    },
    {
        "id": "local_hk_operator_operating_metrics_2016_2025",
        "path": KNOWLEDGE
        / "local_hk_operator_operating_metrics_2016_2025"
        / "annual_metrics.csv",
        "registry": KNOWLEDGE
        / "local_hk_operator_operating_metrics_2016_2025"
        / "sources.json",
        "entity": "operator",
        "period": "period",
        "metric": "metric_key",
        "value_fields": ("official_value", "value"),
        "unit_fields": ("unit",),
        "status": "verification_status",
        "key_fields": ("operator_id", "period", "grain", "metric_key"),
        "source_mode": "registry",
    },
    {
        "id": "competitor_product_tariffs",
        "path": KNOWLEDGE
        / "competitor_product_tariffs"
        / "product_tariffs_formal_agent_records.csv",
        "entity": "品牌",
        "period": "期间",
        "metric": "产品类别",
        "value_fields": ("月费_HKD", "平均月费_HKD", "公开价格_HKD"),
        "unit_fields": ("计价单位",),
        "status": "核验状态",
        "key_fields": ("记录键",),
        "source_mode": "tariff",
    },
    {
        "id": "requested_overview_010304_2016_2025",
        "path": KNOWLEDGE / "requested_overview_010304_2016_2025" / "annual_facts.csv",
        "entity": "entity",
        "period": "period",
        "metric": "metric",
        "value_fields": ("value",),
        "unit_fields": ("unit",),
        "status": "verification_status",
        "key_fields": ("domain", "entity", "metric", "period"),
        "source_mode": "overview",
    },
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(str(raw or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def normalized_url(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value.startswith(("http://", "https://")):
        return ""
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def first_value(row: dict[str, str], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def numeric_state(raw: str) -> tuple[str, float | None]:
    if raw.strip().lower() in {"", "n/a", "na", "none", "null", "-"}:
        return "missing", None
    try:
        value = float(raw.replace(",", "").replace("%", ""))
    except ValueError:
        return "invalid_numeric", None
    return ("numeric", value) if math.isfinite(value) else ("invalid_numeric", None)


def registry(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sources", []) if isinstance(payload, dict) else payload
    return {
        str(item.get("source_id") or item.get("id")): item
        for item in rows
        if isinstance(item, dict)
    }


def source_evidence(
    row: dict[str, str], config: dict[str, Any], sources: dict[str, dict[str, Any]]
) -> tuple[list[str], int]:
    urls = {
        url
        for field in (
            "official_source_url",
            "primary_source_url",
            "來源URL",
            "来源URL",
            "归档URL",
        )
        if (url := normalized_url(row.get(field)))
    }
    references = {f"url:{url}" for url in urls}
    mode = config["source_mode"]
    if mode == "embedded":
        for item in parse_list(row.get("verification_sources")):
            if isinstance(item, dict):
                url = normalized_url(item.get("url"))
                if url:
                    urls.add(url)
                identity = str(
                    item.get("source_document_id")
                    or item.get("source_id")
                    or url
                    or ""
                ).strip()
                if identity:
                    references.add(f"ref:{identity}")
    elif mode == "registry":
        for source_id in parse_list(row.get("verification_sources")):
            references.add(f"ref:{source_id}")
            item = sources.get(str(source_id), {})
            if url := normalized_url(item.get("url")):
                urls.add(url)
        for source_id in parse_list(row.get("candidate_sources")):
            references.add(f"candidate:{source_id}")
            item = sources.get(str(source_id), {})
            if url := normalized_url(item.get("url")):
                urls.add(url)
    elif mode == "overview":
        urls.update(
            url
            for item in parse_list(row.get("source_urls"))
            if (url := normalized_url(item))
        )
    if mode == "tariff" and row.get("来源ID", "").strip():
        references.add(f"ref:{row['来源ID'].strip()}")
    if row.get("primary_source_id", "").strip():
        references.add(f"ref:{row['primary_source_id'].strip()}")
    references.update(f"url:{url}" for url in urls)
    return sorted(urls), len(references)


def search_boundary(
    dataset_id: str, row: dict[str, str], value_state: str
) -> tuple[str, str]:
    if value_state == "numeric":
        return "not_applicable_value_present", ""
    verification_status = str(
        row.get("verification_status") or row.get("核验状态") or ""
    ).strip()
    if verification_status == "not_applicable_precommercial":
        return "not_applicable_precommercial", row.get("quality_note", "").strip()
    if dataset_id == "local_hk_operator_operating_metrics_2016_2025":
        outcome = row.get("audit_outcome", "").strip()
        scope = row.get("gap_search_scope", "").strip()
        availability = row.get("global_availability_status", "").strip()
        if outcome == "targeted_search_no_direct_value" or scope:
            return "targeted_public_search_no_direct_value", " | ".join(
                item for item in (scope, availability) if item
            )
    if dataset_id == "quarterly_competitor_metrics_2026-06-18":
        note = row.get("verification_note", "").strip()
        if verification_status == "needs_official_row_crosscheck":
            return "official_source_row_crosscheck_pending", note
        if note:
            return "documented_official_material_review_no_direct_value", note
    if dataset_id == "global_top5_operators_2016_2025":
        note = row.get("quality_note", "").strip()
        if note:
            return "documented_public_source_review_no_direct_value", note
    if dataset_id == "competitor_product_tariffs" and "no_price" in row.get(
        "来源状态", ""
    ).lower():
        return (
            "documented_public_product_source_no_price",
            row.get("证据摘录", "").strip(),
        )
    return "targeted_public_search_not_recorded", ""


def evidence_quality(status: str, verification_count: int, value_state: str) -> str:
    if value_state != "numeric":
        return "not_applicable_gap"
    lowered = status.lower()
    if "conflict" in lowered:
        return "conflict"
    if "derived" in lowered or "normalized" in lowered:
        return "derived_or_normalized"
    if verification_count >= 3 or "three_distinct" in lowered:
        return "strong_three_plus_sources"
    if (
        verification_count >= 2
        or "multi_source" in lowered
        or "two_distinct" in lowered
    ):
        return "multi_source"
    return "limited_source"


def audit_dataset(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_csv(config["path"])
    sources = registry(config.get("registry"))
    keys = [
        " | ".join(str(row.get(field) or "").strip() for field in config["key_fields"])
        for row in rows
    ]
    duplicate_counts = Counter(keys)
    output: list[dict[str, Any]] = []
    for row_number, (row, natural_key) in enumerate(zip(rows, keys, strict=True), start=2):
        raw_value = first_value(row, config["value_fields"])
        state, value = numeric_state(raw_value)
        urls, source_reference_count = source_evidence(row, config, sources)
        status = row.get(config["status"], "").strip()
        raw_verification_count = first_value(
            row, ("verification_count", "核验次数", "source_count")
        )
        try:
            verification_count = int(float(raw_verification_count or "0"))
        except ValueError:
            verification_count = 0
        search_status, search_detail = search_boundary(config["id"], row, state)
        issues: list[str] = []
        if state == "invalid_numeric":
            issues.append("invalid_numeric")
        if duplicate_counts[natural_key] > 1:
            issues.append("duplicate_natural_key")
        derived = "derived" in status.lower() or "normalized" in status.lower()
        if state == "numeric" and source_reference_count == 0 and not derived:
            issues.append("numeric_value_without_source_reference")
        conflict = "conflict" in status.lower()
        if conflict:
            issues.append("source_conflict")
        usage_policy = (
            "quarantined_conflict"
            if conflict
            else "included_with_quality_label"
            if state == "numeric" and "invalid_numeric" not in issues
            else "gap_not_used"
        )
        output.append(
            {
                "dataset_id": config["id"],
                "source_row": row_number,
                "natural_key": natural_key,
                "entity": row.get(config["entity"], ""),
                "period": row.get(config["period"], ""),
                "metric": row.get(config["metric"], ""),
                "raw_value": raw_value,
                "numeric_value": "" if value is None else value,
                "unit": first_value(row, config["unit_fields"]),
                "value_state": state,
                "verification_status": status,
                "resolved_source_url_count": len(urls),
                "resolved_source_reference_count": source_reference_count,
                "resolved_source_urls": json.dumps(urls, ensure_ascii=False),
                "reported_verification_count": verification_count,
                "evidence_quality": evidence_quality(
                    status, verification_count, state
                ),
                "usage_policy": usage_policy,
                "gap_search_status": search_status,
                "gap_search_detail": search_detail,
                "integrity_issues": ";".join(issues),
            }
        )
    summary = {
        "dataset_id": config["id"],
        "row_count": len(output),
        "numeric_rows": sum(row["value_state"] == "numeric" for row in output),
        "gap_rows": sum(row["value_state"] == "missing" for row in output),
        "invalid_numeric_rows": sum(row["value_state"] == "invalid_numeric" for row in output),
        "included_rows": sum(row["usage_policy"] == "included_with_quality_label" for row in output),
        "conflict_rows": sum(row["usage_policy"] == "quarantined_conflict" for row in output),
        "duplicate_rows": sum("duplicate_natural_key" in row["integrity_issues"] for row in output),
        "numeric_without_source_reference": sum(
            "numeric_value_without_source_reference" in row["integrity_issues"]
            for row in output
        ),
        "targeted_search_no_direct_value_rows": sum(
            row["gap_search_status"]
            in {
                "targeted_public_search_no_direct_value",
                "documented_official_material_review_no_direct_value",
                "documented_public_source_review_no_direct_value",
                "documented_public_product_source_no_price",
            }
            for row in output
        ),
        "targeted_search_not_recorded_rows": sum(
            row["gap_search_status"] == "targeted_public_search_not_recorded"
            for row in output
        ),
        "source_csv": config["path"].relative_to(ROOT).as_posix(),
    }
    return output, summary


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    audit_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for config in DATASETS:
        rows, summary = audit_dataset(config)
        audit_rows.extend(rows)
        summaries.append(summary)
    csv_path = OUTPUT / f"competitor_numeric_row_audit_{AUDIT_DATE}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)
    payload = {
        "audit_date": AUDIT_DATE,
        "policy": {
            "disclosed_numeric_values": "included_with_quality_label_unless_conflicted_or_invalid",
            "weak_source_count": "quality_advisory_not_omission_rule",
            "gap_boundary": "targeted-search-no-direct-value and search-not-recorded are distinct",
        },
        "total_rows": len(audit_rows),
        "datasets": summaries,
        "row_audit_csv": csv_path.relative_to(ROOT).as_posix(),
    }
    json_path = OUTPUT / f"competitor_numeric_row_audit_{AUDIT_DATE}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
