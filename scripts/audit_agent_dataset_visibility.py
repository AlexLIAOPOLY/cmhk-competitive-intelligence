#!/usr/bin/env python3
"""Audit 小竞AI dataset registry and RAG visibility for core knowledge packages."""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_llm import list_knowledge_datasets, retrieve_context  # noqa: E402


AUDIT_DATE = date.today().isoformat()
OUT_ROOT = ROOT / "agent_knowledge" / "agent_dataset_visibility_audits"

EXPECTED_DATASETS = [
    {
        "id": "cmhk_macro_policy_2026-06-19",
        "query": "cmhk_macro_policy_2026-06-19 OFCA C&SD verification_count official_value",
        "must_hit": "agent_knowledge/cmhk_macro_policy_2026-06-19/",
    },
    {
        "id": "quarterly_competitor_metrics_2026-06-18",
        "query": "quarterly_competitor_metrics_2026-06-18 official_verified_with_documented_source_gaps row_count 3013",
        "must_hit": "agent_knowledge/quarterly_competitor_metrics_2026-06-18/",
    },
    {
        "id": "cloud_vendor_metrics_2026-06-17",
        "query": "cloud_vendor_metrics_2026-06-17 AWS FY2025 official_value Huawei source_gap",
        "must_hit": "agent_knowledge/cloud_vendor_metrics_2026-06-17/",
    },
    {
        "id": "knowledge_integrity_audits",
        "query": "knowledge_integrity_audits datasets checked failed 0 verification_count",
        "must_hit": "agent_knowledge/knowledge_integrity_audits/",
    },
    {
        "id": "forecast_readiness_audits",
        "query": "forecast_readiness_audits Alibaba legacy HKT half-year HGC source gap",
        "must_hit": "agent_knowledge/forecast_readiness_audits/",
    },
    {
        "id": "source_evidence_audits",
        "query": "source_evidence_audits rows with issues 0 verification_sources official_evidence",
        "must_hit": "agent_knowledge/source_evidence_audits/",
    },
    {
        "id": "source_url_reachability_audits",
        "query": "source_url_reachability_audits 675 unique URLs ok reachable_restricted ssl_error",
        "must_hit": "agent_knowledge/source_url_reachability_audits/",
    },
    {
        "id": "goal_readiness_audits",
        "query": "goal_readiness_audits official_value verification_count source_gap forecast_readiness agent-datasets",
        "must_hit": "agent_knowledge/goal_readiness_audits/",
    },
    {
        "id": "agent_guidance_alignment_audits",
        "query": "agent_guidance_alignment_audits goal_readiness_audits superseded quarterly_competitor_metrics_2026-06-18",
        "must_hit": "agent_knowledge/agent_guidance_alignment_audits/",
    },
]

FORBIDDEN_DATASET_IDS = {
    "generated_charts",
    "quarterly_competitor_metrics_2026-06-17",
}


def fetch_api_dataset_ids() -> set[str] | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/agent-datasets", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return {str(item.get("id") or "") for item in data.get("datasets", []) if item.get("id")}


def audit_dataset(config: dict[str, str], datasets_by_id: dict[str, dict[str, Any]], api_ids: set[str] | None) -> dict[str, Any]:
    dataset_id = config["id"]
    dataset = datasets_by_id.get(dataset_id)
    issues: list[str] = []
    chunks = []
    if dataset is None:
        issues.append("dataset_missing_from_registry")
    else:
        if not dataset.get("manifest_path"):
            issues.append("manifest_missing")
        entrypoints = dataset.get("entrypoints") or []
        if not entrypoints:
            issues.append("entrypoints_empty")
        files = dataset.get("files") or []
        entrypoint_files = [item for item in files if item.get("entrypoint")]
        if not entrypoint_files:
            issues.append("entrypoint_files_not_marked")
        missing_entrypoints = [name for name in entrypoints if not any(item.get("name") == name for item in files)]
        if missing_entrypoints:
            issues.append("entrypoint_file_missing:" + ",".join(missing_entrypoints))
        chunks = retrieve_context(config["query"], limit=4, dataset_ids={dataset_id})
        if not chunks:
            issues.append("rag_no_chunks")
        elif not any(config["must_hit"] in str(chunk.get("source") or "") for chunk in chunks):
            issues.append("rag_wrong_dataset_hit")
    if api_ids is not None and dataset_id not in api_ids:
        issues.append("dataset_missing_from_api")
    return {
        "dataset_id": dataset_id,
        "status": "pass" if not issues else "fail",
        "issues": ";".join(issues),
        "manifest_path": "" if dataset is None else dataset.get("manifest_path", ""),
        "entrypoint_count": 0 if dataset is None else len(dataset.get("entrypoints") or []),
        "file_count": 0 if dataset is None else len(dataset.get("files") or []),
        "rag_chunk_count": len(chunks),
        "api_checked": api_ids is not None,
    }


def audit_forbidden(datasets_by_id: dict[str, dict[str, Any]], api_ids: set[str] | None) -> list[dict[str, Any]]:
    rows = []
    for dataset_id in sorted(FORBIDDEN_DATASET_IDS):
        issues = []
        if dataset_id in datasets_by_id:
            issues.append("forbidden_dataset_visible_in_registry")
        if api_ids is not None and dataset_id in api_ids:
            issues.append("forbidden_dataset_visible_in_api")
        rows.append(
            {
                "dataset_id": dataset_id,
                "status": "pass" if not issues else "fail",
                "issues": ";".join(issues),
                "manifest_path": "",
                "entrypoint_count": "",
                "file_count": "",
                "rag_chunk_count": "",
                "api_checked": api_ids is not None,
            }
        )
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "dataset_id",
        "status",
        "issues",
        "manifest_path",
        "entrypoint_count",
        "file_count",
        "rag_chunk_count",
        "api_checked",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], path: Path, api_available: bool) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    lines = [
        f"# Agent Dataset Visibility Audit ({AUDIT_DATE})",
        "",
        f"- Checks: {len(rows)}",
        f"- Passed: {passed}",
        f"- Failed: {len(rows) - passed}",
        f"- API checked: {api_available}",
        "",
        "## Dataset Results",
        "",
        "| Dataset | Status | Entry points | Files | RAG chunks | Issues |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {dataset_id} | {status} | {entrypoint_count} | {file_count} | {rag_chunk_count} | {issues} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- Verifies the core CMHK macro, quarterly competitor/cloud, cloud vendor, and audit datasets are registered with manifests, entrypoints, readable files, and RAG hits.",
            "- Verifies generated output folders and superseded knowledge packages are not exposed as selectable AI databases or default RAG sources.",
            "- If the local web server is running, verifies `/api/agent-datasets` exposes the same expected dataset IDs.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(rows: list[dict[str, Any]], path: Path, csv_path: Path, md_path: Path, api_available: bool) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    failed = len(rows) - passed
    manifest = {
        "id": "agent_dataset_visibility_audits",
        "title": "小竞AI数据库登记与RAG可见性审计",
        "summary": "检查核心知识库和维护审计库是否在小竞AI数据库列表中可见、入口文件存在、RAG 定向检索可命中，并确认空图表目录和 superseded 旧知识包不会作为数据库暴露。",
        "source_type": "local_audit",
        "scope": "小竞AI database picker, backend registry, entrypoints, and RAG retrieval visibility.",
        "updated_at": AUDIT_DATE,
        "tags": ["audit", "dataset-registry", "rag", "frontend-database-picker"],
        "keywords": ["agent_dataset_visibility_audits", "agent-datasets", "RAG", "entrypoints", "generated_charts", "superseded"],
        "entrypoints": [md_path.name, csv_path.name],
        "quality": {
            "status": "pass" if failed == 0 else "fail",
            "row_count": len(rows),
            "checks": len(rows),
            "passed": passed,
            "failed": failed,
            "api_checked": api_available,
            "notes": [
                "核心数据包和审计包必须能被小竞AI后端列出并能定向检索。",
                "无可读知识文件且无 manifest 的输出目录不得暴露为数据库。",
                "被 manifest 标记为 superseded 的旧数据包不得进入默认数据库选择和默认 RAG 范围。",
            ],
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    datasets = list_knowledge_datasets()
    datasets_by_id = {item["id"]: item for item in datasets}
    api_ids = fetch_api_dataset_ids()
    rows = [audit_dataset(config, datasets_by_id, api_ids) for config in EXPECTED_DATASETS]
    rows.extend(audit_forbidden(datasets_by_id, api_ids))
    csv_path = OUT_ROOT / f"agent_dataset_visibility_{AUDIT_DATE}.csv"
    md_path = OUT_ROOT / f"agent_dataset_visibility_{AUDIT_DATE}.md"
    manifest_path = OUT_ROOT / "manifest.json"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path, api_ids is not None)
    write_manifest(rows, manifest_path, csv_path, md_path, api_ids is not None)
    print(f"wrote {csv_path.relative_to(ROOT)}")
    print(f"wrote {md_path.relative_to(ROOT)}")
    print(f"wrote {manifest_path.relative_to(ROOT)}")
    failed = [row for row in rows if row["status"] != "pass"]
    if failed:
        for row in failed:
            print(f"failed {row['dataset_id']}: {row['issues']}")
        raise SystemExit(1)
    print("all dataset visibility checks passed")


if __name__ == "__main__":
    main()
