#!/usr/bin/env python3
"""Audit CMHK agent knowledge packages for schema and source integrity."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DATE = date.today().isoformat()
OUT_ROOT = ROOT / "agent_knowledge" / "knowledge_integrity_audits"

DATASETS = [
    {
        "id": "cmhk_macro_policy_2026-06-19",
        "folder": ROOT / "agent_knowledge" / "cmhk_macro_policy_2026-06-19",
        "primary_csv": "macro_policy_metrics.csv",
        "primary_json": "macro_policy_metrics.json",
    },
    {
        "id": "quarterly_competitor_metrics_2026-06-18",
        "folder": ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18",
        "primary_csv": "quarterly_metrics.csv",
        "primary_json": "quarterly_metrics.json",
    },
    {
        "id": "cloud_vendor_metrics_2026-06-17",
        "folder": ROOT / "agent_knowledge" / "cloud_vendor_metrics_2026-06-17",
        "primary_csv": "cloud_vendor_metrics_2023_2025.csv",
        "primary_json": "cloud_vendor_metrics_2023_2025.json",
    },
    {
        "id": "forecast_readiness_audits",
        "folder": ROOT / "agent_knowledge" / "forecast_readiness_audits",
        "primary_csv": f"forecast_readiness_alignment_{AUDIT_DATE}.csv",
        "primary_json": "",
        "required_fields": set(),
        "audit_status_column": "status",
        "pass_statuses": {"pass"},
        "allow_missing_primary_json": True,
    },
    {
        "id": "source_evidence_audits",
        "folder": ROOT / "agent_knowledge" / "source_evidence_audits",
        "primary_csv": f"source_evidence_integrity_{AUDIT_DATE}.csv",
        "primary_json": "",
        "required_fields": set(),
        "audit_status_column": "status",
        "pass_statuses": {"pass"},
        "allow_missing_primary_json": True,
    },
    {
        "id": "source_url_reachability_audits",
        "folder": ROOT / "agent_knowledge" / "source_url_reachability_audits",
        "primary_csv": f"source_url_reachability_{AUDIT_DATE}.csv",
        "primary_json": "",
        "required_fields": set(),
        "audit_status_column": "status",
        "pass_statuses": {"ok", "reachable_restricted", "ssl_error"},
        "allow_missing_primary_json": True,
    },
    {
        "id": "agent_dataset_visibility_audits",
        "folder": ROOT / "agent_knowledge" / "agent_dataset_visibility_audits",
        "primary_csv": f"agent_dataset_visibility_{AUDIT_DATE}.csv",
        "primary_json": "",
        "required_fields": set(),
        "audit_status_column": "status",
        "pass_statuses": {"pass"},
        "allow_missing_primary_json": True,
    },
    {
        "id": "goal_readiness_audits",
        "folder": ROOT / "agent_knowledge" / "goal_readiness_audits",
        "primary_csv": f"goal_readiness_{AUDIT_DATE}.csv",
        "primary_json": "",
        "required_fields": set(),
        "audit_status_column": "status",
        "pass_statuses": {"pass"},
        "allow_missing_primary_json": True,
    },
    {
        "id": "agent_guidance_alignment_audits",
        "folder": ROOT / "agent_knowledge" / "agent_guidance_alignment_audits",
        "primary_csv": f"agent_guidance_alignment_{AUDIT_DATE}.csv",
        "primary_json": "",
        "required_fields": set(),
        "audit_status_column": "status",
        "pass_statuses": {"pass"},
        "allow_missing_primary_json": True,
    },
]

REQUIRED_FIELDS = {
    "official_value",
    "official_unit",
    "verification_status",
    "verification_count",
}

SOURCE_GAP_STATUSES = {"source_gap_confirmed"}
OFFICIAL_VALUE_STATUSES = {
    "official_match",
    "official_only",
    "official_conflict",
    "official_derived_from_verified_rows",
    "verified_against_official_source",
    "derived_from_verified_rows",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_int(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except Exception:
        return None


def blank(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or text.lower() in {"nan", "n/a", "na", "none", "-"}


def manifest_row_count(manifest: dict[str, Any]) -> int | None:
    quality = manifest.get("quality")
    if isinstance(quality, dict):
        count = as_int(quality.get("row_count"))
        if count is not None:
            return count
    return as_int(manifest.get("row_count"))


def audit_dataset(config: dict[str, Any]) -> dict[str, Any]:
    dataset_id = config["id"]
    folder: Path = config["folder"]
    manifest_path = folder / "manifest.json"
    csv_path = folder / config["primary_csv"]
    primary_json = config.get("primary_json") or ""
    json_path = folder / primary_json if primary_json else None
    result: dict[str, Any] = {
        "dataset_id": dataset_id,
        "folder": folder.relative_to(ROOT).as_posix(),
        "primary_csv": config["primary_csv"],
        "primary_json": primary_json,
        "status": "pass",
        "issues": [],
    }

    if not folder.exists():
        result["status"] = "fail"
        result["issues"].append("dataset_folder_missing")
        return result
    if not manifest_path.exists():
        result["status"] = "fail"
        result["issues"].append("manifest_missing")
        return result
    if not csv_path.exists():
        result["status"] = "fail"
        result["issues"].append("primary_csv_missing")
        return result
    if json_path is not None and not json_path.exists():
        result["status"] = "fail"
        result["issues"].append("primary_json_missing")
        return result

    manifest = read_json(manifest_path)
    rows = read_csv(csv_path)
    fields = set(rows[0].keys()) if rows else set()
    entrypoints = manifest.get("entrypoints") if isinstance(manifest.get("entrypoints"), list) else []
    missing_entrypoints = [name for name in entrypoints if not (folder / name).exists()]
    required_fields = config.get("required_fields", REQUIRED_FIELDS)
    missing_fields = sorted(set(required_fields) - fields)
    status_column = str(config.get("audit_status_column") or "verification_status")
    status_counts = Counter(row.get(status_column, "") for row in rows)
    low_verification = 0
    bad_verification_count = 0
    if "verification_count" in fields:
        for row in rows:
            count = as_int(row.get("verification_count"))
            if count is None:
                bad_verification_count += 1
                low_verification += 1
            elif count < 2:
                low_verification += 1
    missing_official_value = sum(
        1
        for row in rows
        if row.get("verification_status") in OFFICIAL_VALUE_STATUSES and blank(row.get("official_value"))
    )
    source_gap_with_value = sum(
        1
        for row in rows
        if row.get("verification_status") in SOURCE_GAP_STATUSES and not blank(row.get("official_value"))
    )
    row_count_in_manifest = manifest_row_count(manifest)

    result.update(
        {
            "row_count": len(rows),
            "manifest_id": manifest.get("id", ""),
            "manifest_quality_status": (manifest.get("quality") or {}).get("status", "")
            if isinstance(manifest.get("quality"), dict)
            else "",
            "manifest_row_count": row_count_in_manifest,
            "missing_required_fields": ";".join(missing_fields),
            "missing_entrypoints": ";".join(missing_entrypoints),
            "verification_count_lt_2": low_verification,
            "bad_verification_count": bad_verification_count,
            "missing_official_value_for_official_rows": missing_official_value,
            "source_gap_rows_with_official_value": source_gap_with_value,
            "status_counts_json": json.dumps(status_counts, ensure_ascii=False, sort_keys=True),
        }
    )

    if manifest.get("id") != dataset_id:
        result["issues"].append("manifest_id_mismatch")
    if row_count_in_manifest is not None and row_count_in_manifest != len(rows):
        result["issues"].append("manifest_row_count_mismatch")
    if missing_entrypoints:
        result["issues"].append("entrypoint_missing")
    if missing_fields:
        result["issues"].append("required_fields_missing")
    if low_verification:
        result["issues"].append("verification_count_lt_2")
    if missing_official_value:
        result["issues"].append("official_value_missing")
    if source_gap_with_value:
        result["issues"].append("source_gap_has_official_value")
    pass_statuses = config.get("pass_statuses")
    if pass_statuses:
        bad_status_rows = sum(1 for row in rows if row.get(status_column) not in pass_statuses)
        result["audit_status_fail_rows"] = bad_status_rows
        if bad_status_rows:
            result["issues"].append("audit_status_fail_rows")

    if result["issues"]:
        result["status"] = "fail"
    return result


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        raise RuntimeError("no audit rows")
    fields = [
        "dataset_id",
        "status",
        "issues",
        "row_count",
        "manifest_row_count",
        "manifest_quality_status",
        "verification_count_lt_2",
        "missing_official_value_for_official_rows",
        "source_gap_rows_with_official_value",
        "missing_required_fields",
        "missing_entrypoints",
        "status_counts_json",
        "folder",
        "primary_csv",
        "primary_json",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["issues"] = ";".join(row.get("issues") or [])
            writer.writerow(out)


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    lines = [
        f"# Agent Knowledge Integrity Audit ({AUDIT_DATE})",
        "",
        f"- Datasets checked: {len(rows)}",
        f"- Passed: {passed}",
        f"- Failed: {len(rows) - passed}",
        "",
        "## Dataset Results",
        "",
        "| Dataset | Status | Rows | Manifest row count | Verification < 2 | Missing official_value | Source-gap with value | Issues |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {dataset_id} | {status} | {row_count} | {manifest_row_count} | {verification_count_lt_2} | {missing_official_value_for_official_rows} | {source_gap_rows_with_official_value} | {issues} |".format(
                dataset_id=row["dataset_id"],
                status=row["status"],
                row_count=row.get("row_count", ""),
                manifest_row_count="" if row.get("manifest_row_count") is None else row.get("manifest_row_count"),
                verification_count_lt_2=row.get("verification_count_lt_2", ""),
                missing_official_value_for_official_rows=row.get("missing_official_value_for_official_rows", ""),
                source_gap_rows_with_value=row.get("source_gap_rows_with_official_value", ""),
                source_gap_rows_with_official_value=row.get("source_gap_rows_with_official_value", ""),
                issues=", ".join(row.get("issues") or []) or "none",
            )
        )
    lines.extend(["", "## Status Counts", ""])
    for row in rows:
        lines.append(f"### {row['dataset_id']}")
        lines.append("")
        counts = json.loads(row.get("status_counts_json") or "{}")
        for status, count in counts.items():
            lines.append(f"- {status or '(blank)'}: {count}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(rows: list[dict[str, Any]], path: Path, csv_path: Path, md_path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    failed = len(rows) - passed
    manifest = {
        "id": "knowledge_integrity_audits",
        "title": "小竞AI知识库完整性审计",
        "summary": "统一检查当前竞对/云厂商/宏观政策知识库的 manifest、入口文件、行数、official_value、verification_status、verification_count 和 source-gap 边界。",
        "source_type": "local_audit",
        "scope": "小竞AI数据库选择、RAG 检索、预测前数据质量检查和维护验收。",
        "updated_at": AUDIT_DATE,
        "tags": ["audit", "knowledge-integrity", "source-integrity", "rag"],
        "keywords": [
            "knowledge_integrity_audits",
            "verification_count",
            "official_value",
            "source_gap_confirmed",
            "quarterly_competitor_metrics_2026-06-18",
            "cloud_vendor_metrics_2026-06-17",
            "cmhk_macro_policy_2026-06-19",
        ],
        "entrypoints": [md_path.name, csv_path.name],
        "quality": {
            "status": "pass" if failed == 0 else "fail",
            "row_count": len(rows),
            "datasets_checked": len(rows),
            "passed": passed,
            "failed": failed,
            "notes": [
                "审计记录本身是维护证据，不是预测目标数据。",
                "若 failed > 0，必须先修复对应知识库或登记 source-gap 边界，再用于正式结论。",
                "当前审计检查 verification_count < 2、official_value 缺失、source-gap 带值、manifest row_count 和 entrypoints。",
            ],
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = [audit_dataset(config) for config in DATASETS]
    csv_path = OUT_ROOT / f"knowledge_integrity_audit_{AUDIT_DATE}.csv"
    md_path = OUT_ROOT / f"knowledge_integrity_audit_{AUDIT_DATE}.md"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path)
    manifest_path = OUT_ROOT / "manifest.json"
    write_manifest(rows, manifest_path, csv_path, md_path)
    print(f"wrote {csv_path.relative_to(ROOT)}")
    print(f"wrote {md_path.relative_to(ROOT)}")
    print(f"wrote {manifest_path.relative_to(ROOT)}")
    failed = [row for row in rows if row["status"] != "pass"]
    if failed:
        print("failed datasets:")
        for row in failed:
            print(f"- {row['dataset_id']}: {', '.join(row['issues'])}")
        raise SystemExit(1)
    print("all datasets passed")


if __name__ == "__main__":
    main()
