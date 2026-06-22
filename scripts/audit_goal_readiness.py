#!/usr/bin/env python3
"""Audit current evidence against the active CMHK knowledge-base goal."""

from __future__ import annotations

import csv
import json
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DATE = date.today().isoformat()
OUT_ROOT = ROOT / "agent_knowledge" / "goal_readiness_audits"

MAIN_DATASETS = [
    {
        "id": "cmhk_macro_policy_2026-06-19",
        "folder": ROOT / "agent_knowledge" / "cmhk_macro_policy_2026-06-19",
        "primary_csv": "macro_policy_metrics.csv",
    },
    {
        "id": "quarterly_competitor_metrics_2026-06-18",
        "folder": ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18",
        "primary_csv": "quarterly_metrics.csv",
    },
    {
        "id": "cloud_vendor_metrics_2026-06-17",
        "folder": ROOT / "agent_knowledge" / "cloud_vendor_metrics_2026-06-17",
        "primary_csv": "cloud_vendor_metrics_2023_2025.csv",
    },
]

REQUIRED_ROW_FIELDS = {
    "official_value",
    "official_unit",
    "verification_status",
    "verification_count",
    "verification_sources",
}
OFFICIAL_VALUE_STATUSES = {
    "official_match",
    "official_only",
    "official_conflict",
    "official_derived_from_verified_rows",
    "verified_against_official_source",
    "derived_from_verified_rows",
}
SOURCE_GAP_STATUSES = {"source_gap_confirmed"}
HARD_URL_FAILURES = {"http_error", "timeout", "network_error"}


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def blank(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or text.lower() in {"nan", "n/a", "na", "none", "-"}


def as_int(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except Exception:
        return None


def latest_csv(folder: str, prefix: str) -> Path | None:
    root = ROOT / "agent_knowledge" / folder
    files = sorted(root.glob(f"{prefix}_*.csv"))
    return files[-1] if files else None


def api_dataset_ids() -> set[str] | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/agent-datasets", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return {str(item.get("id") or "") for item in data.get("datasets", []) if item.get("id")}


def make_row(requirement: str, status: str, evidence: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "status": status,
        "evidence": evidence,
        "details_json": json.dumps(details, ensure_ascii=False, sort_keys=True),
    }


def audit_main_packages() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total_rows = 0
    total_low_verification = 0
    total_missing_value = 0
    total_source_gap_with_value = 0
    total_bad_sources = 0
    package_details: dict[str, Any] = {}

    for config in MAIN_DATASETS:
        folder = config["folder"]
        csv_path = folder / config["primary_csv"]
        manifest_path = folder / "manifest.json"
        manifest = read_json(manifest_path)
        package_issues: list[str] = []
        if not manifest_path.exists():
            package_issues.append("manifest_missing")
        if not csv_path.exists():
            package_issues.append("primary_csv_missing")
            package_details[config["id"]] = {"issues": package_issues}
            continue

        data_rows = read_csv(csv_path)
        fields = set(data_rows[0].keys()) if data_rows else set()
        missing_fields = sorted(REQUIRED_ROW_FIELDS - fields)
        if missing_fields:
            package_issues.append("required_fields_missing:" + ",".join(missing_fields))

        low_verification = 0
        missing_value = 0
        source_gap_with_value = 0
        bad_sources = 0
        if not missing_fields:
            for item in data_rows:
                verification_count = as_int(item.get("verification_count"))
                if verification_count is None or verification_count < 2:
                    low_verification += 1
                if item.get("verification_status") in OFFICIAL_VALUE_STATUSES and blank(item.get("official_value")):
                    missing_value += 1
                if item.get("verification_status") in SOURCE_GAP_STATUSES and not blank(item.get("official_value")):
                    source_gap_with_value += 1
                try:
                    parsed_sources = json.loads(item.get("verification_sources") or "")
                except Exception:
                    parsed_sources = None
                if not isinstance(parsed_sources, list) or verification_count is None or len(parsed_sources) < verification_count:
                    bad_sources += 1

        total_rows += len(data_rows)
        total_low_verification += low_verification
        total_missing_value += missing_value
        total_source_gap_with_value += source_gap_with_value
        total_bad_sources += bad_sources
        package_details[config["id"]] = {
            "rows": len(data_rows),
            "manifest_id": manifest.get("id", ""),
            "manifest_quality": (manifest.get("quality") or {}).get("status", "") if isinstance(manifest.get("quality"), dict) else "",
            "missing_fields": missing_fields,
            "low_verification": low_verification,
            "missing_official_value": missing_value,
            "source_gap_with_official_value": source_gap_with_value,
            "bad_verification_sources": bad_sources,
            "issues": package_issues,
        }

    status = "pass"
    if any(detail.get("issues") for detail in package_details.values()):
        status = "fail"
    if total_low_verification or total_missing_value or total_source_gap_with_value or total_bad_sources:
        status = "fail"
    rows.append(
        make_row(
            "main_data_packages_preserve_required_fields_and_row_integrity",
            status,
            "main package CSVs and manifests",
            {
                "total_rows": total_rows,
                "verification_count_lt_2": total_low_verification,
                "missing_official_value": total_missing_value,
                "source_gap_with_official_value": total_source_gap_with_value,
                "bad_verification_sources": total_bad_sources,
                "packages": package_details,
            },
        )
    )
    return rows


def audit_status_csv(folder: str, prefix: str, requirement: str, allowed_statuses: set[str]) -> dict[str, Any]:
    path = latest_csv(folder, prefix)
    if path is None:
        return make_row(requirement, "fail", f"agent_knowledge/{folder}/", {"issue": "audit_csv_missing"})
    rows = read_csv(path)
    bad = [row for row in rows if row.get("status") not in allowed_statuses]
    return make_row(
        requirement,
        "pass" if not bad else "fail",
        path.relative_to(ROOT).as_posix(),
        {
            "rows": len(rows),
            "bad_rows": len(bad),
            "status_counts": {status: sum(1 for row in rows if row.get("status") == status) for status in sorted({row.get("status") for row in rows})},
        },
    )


def audit_url_reachability() -> dict[str, Any]:
    path = latest_csv("source_url_reachability_audits", "source_url_reachability")
    if path is None:
        return make_row("source_urls_have_no_hard_failures", "fail", "agent_knowledge/source_url_reachability_audits/", {"issue": "audit_csv_missing"})
    rows = read_csv(path)
    status_counts = {status: sum(1 for row in rows if row.get("status") == status) for status in sorted({row.get("status") for row in rows})}
    hard_failures = sum(count for status, count in status_counts.items() if status in HARD_URL_FAILURES)
    return make_row(
        "source_urls_have_no_hard_failures",
        "pass" if hard_failures == 0 else "fail",
        path.relative_to(ROOT).as_posix(),
        {
            "unique_urls": len(rows),
            "hard_failures": hard_failures,
            "status_counts": status_counts,
            "accepted_non_ok_statuses": ["reachable_restricted", "ssl_error"],
        },
    )


def audit_api_visibility() -> dict[str, Any]:
    ids = api_dataset_ids()
    if ids is None:
        return make_row("xiaojing_ai_database_visibility_aligned", "fail", "/api/agent-datasets", {"issue": "api_unavailable"})
    required = {"cmhk_macro_policy_2026-06-19", "quarterly_competitor_metrics_2026-06-18", "cloud_vendor_metrics_2026-06-17"}
    hidden = {"quarterly_competitor_metrics_2026-06-17", "generated_charts"}
    missing_required = sorted(required - ids)
    visible_hidden = sorted(hidden & ids)
    return make_row(
        "xiaojing_ai_database_visibility_aligned",
        "pass" if not missing_required and not visible_hidden else "fail",
        "/api/agent-datasets",
        {
            "dataset_count": len(ids),
            "required_visible": sorted(required),
            "missing_required": missing_required,
            "hidden_or_superseded_not_visible": sorted(hidden),
            "visible_hidden_or_superseded": visible_hidden,
        },
    )


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = ["requirement", "status", "evidence", "details_json"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    lines = [
        f"# Goal Readiness Audit ({AUDIT_DATE})",
        "",
        f"- Requirements checked: {len(rows)}",
        f"- Passed: {passed}",
        f"- Failed: {len(rows) - passed}",
        "",
        "## Requirement Results",
        "",
        "| Requirement | Status | Evidence | Details |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        details = json.loads(row["details_json"])
        lines.append(f"| {row['requirement']} | {row['status']} | {row['evidence']} | `{json.dumps(details, ensure_ascii=False, sort_keys=True)}` |")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- Maps the active CMHK knowledge-base goal to current local evidence.",
            "- Confirms the three main packages preserve official values, verification counts, source-gap boundaries, evidence text, and parseable verification source lists.",
            "- Pulls in the dedicated source-evidence, URL-reachability, forecast-readiness, and database-visibility audits as requirement-level evidence.",
            "- This audit is a completion-readiness map; it does not create or estimate missing data.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(rows: list[dict[str, Any]], path: Path, csv_path: Path, md_path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    failed = len(rows) - passed
    manifest = {
        "id": "goal_readiness_audits",
        "title": "CMHK知识库目标完成度证据审计",
        "summary": "把当前持续维护目标拆成数据完整性、来源证据、URL、预测边界和小竞AI数据库可见性要求，并记录每项要求的当前证据。",
        "source_type": "local_audit",
        "scope": "Goal-level readiness for CMHK competitor, cloud vendor, macro policy, RAG, and forecast support maintenance.",
        "updated_at": AUDIT_DATE,
        "tags": ["audit", "goal-readiness", "knowledge-base", "forecast", "rag"],
        "keywords": ["goal_readiness_audits", "official_value", "verification_count", "source_gap", "forecast_readiness", "agent-datasets"],
        "entrypoints": [md_path.name, csv_path.name],
        "quality": {
            "status": "pass" if failed == 0 else "fail",
            "row_count": len(rows),
            "requirements_checked": len(rows),
            "passed": passed,
            "failed": failed,
            "notes": [
                "This audit maps goal requirements to evidence and should be rerun after any data, source, forecast, or RAG visibility change.",
                "It does not estimate missing data and treats source gaps as acceptable only when official_value is blank and evidence is preserved.",
            ],
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = audit_main_packages()
    rows.append(audit_status_csv("source_evidence_audits", "source_evidence_integrity", "source_evidence_fields_are_complete", {"pass"}))
    rows.append(audit_url_reachability())
    rows.append(audit_status_csv("forecast_readiness_audits", "forecast_readiness_alignment", "forecast_tool_respects_series_boundaries", {"pass"}))
    rows.append(audit_status_csv("agent_guidance_alignment_audits", "agent_guidance_alignment", "agent_guidance_routes_quality_and_prediction_questions_through_audits", {"pass"}))
    rows.append(audit_status_csv("agent_dataset_visibility_audits", "agent_dataset_visibility", "dataset_picker_and_default_rag_visibility_are_audited", {"pass"}))
    rows.append(audit_api_visibility())

    csv_path = OUT_ROOT / f"goal_readiness_{AUDIT_DATE}.csv"
    md_path = OUT_ROOT / f"goal_readiness_{AUDIT_DATE}.md"
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
            print(f"failed {row['requirement']}: {row['details_json']}")
        raise SystemExit(1)
    print("all goal readiness checks passed")


if __name__ == "__main__":
    main()
