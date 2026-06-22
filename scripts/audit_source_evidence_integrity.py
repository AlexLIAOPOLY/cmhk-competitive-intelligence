#!/usr/bin/env python3
"""Audit official source links and evidence fields for CMHK knowledge packages."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DATE = date.today().isoformat()
OUT_ROOT = ROOT / "agent_knowledge" / "source_evidence_audits"

DATASETS = [
    {
        "id": "cmhk_macro_policy_2026-06-19",
        "folder": ROOT / "agent_knowledge" / "cmhk_macro_policy_2026-06-19",
        "primary_csv": "macro_policy_metrics.csv",
        "primary_url_field": "official_source_url",
        "evidence_field": "official_evidence",
    },
    {
        "id": "quarterly_competitor_metrics_2026-06-18",
        "folder": ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18",
        "primary_csv": "quarterly_metrics.csv",
        "primary_url_field": "official_source_url",
        "evidence_field": "official_evidence",
    },
    {
        "id": "cloud_vendor_metrics_2026-06-17",
        "folder": ROOT / "agent_knowledge" / "cloud_vendor_metrics_2026-06-17",
        "primary_csv": "cloud_vendor_metrics_2023_2025.csv",
        "primary_url_field": "primary_source_url",
        "evidence_field": "verification_note",
    },
]

URL_PATTERN = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


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


def parse_sources(value: str) -> tuple[list[dict[str, Any]], str]:
    if blank(value):
        return [], "blank_verification_sources"
    try:
        data = json.loads(value)
    except Exception:
        return [], "verification_sources_not_json"
    if not isinstance(data, list):
        return [], "verification_sources_not_list"
    bad_items = [
        item
        for item in data
        if not isinstance(item, dict)
        or blank(item.get("url"))
        or not URL_PATTERN.match(str(item.get("url") or "").strip())
    ]
    if bad_items:
        return [item for item in data if isinstance(item, dict)], "verification_source_bad_url"
    return [item for item in data if isinstance(item, dict)], ""


def audit_dataset(config: dict[str, Any]) -> dict[str, Any]:
    csv_path = config["folder"] / config["primary_csv"]
    rows = read_csv(csv_path)
    issue_counts: Counter[str] = Counter()
    rows_with_any_issue = 0
    source_counts: list[int] = []
    source_url_hosts: Counter[str] = Counter()

    for row in rows:
        row_issues: list[str] = []
        primary_url = str(row.get(config["primary_url_field"]) or "").strip()
        if blank(primary_url):
            row_issues.append("primary_source_url_blank")
        elif not URL_PATTERN.match(primary_url):
            row_issues.append("primary_source_url_invalid")
        else:
            host = re.sub(r"^https?://", "", primary_url, flags=re.IGNORECASE).split("/")[0].lower()
            source_url_hosts[host] += 1

        if blank(row.get(config["evidence_field"])):
            row_issues.append("evidence_blank")

        verification_count = as_int(row.get("verification_count"))
        if verification_count is None or verification_count < 2:
            row_issues.append("verification_count_lt_2_or_invalid")

        sources, parse_issue = parse_sources(row.get("verification_sources") or "")
        source_counts.append(len(sources))
        if parse_issue:
            row_issues.append(parse_issue)
        if verification_count is not None and len(sources) < verification_count:
            row_issues.append("verification_sources_count_lt_verification_count")
        if sources and not any(str(item.get("url") or "").strip() == primary_url for item in sources):
            row_issues.append("primary_source_url_not_in_verification_sources")

        for issue in row_issues:
            issue_counts[issue] += 1
        if row_issues:
            rows_with_any_issue += 1

    return {
        "dataset_id": config["id"],
        "status": "pass" if not issue_counts else "fail",
        "row_count": len(rows),
        "rows_with_any_issue": rows_with_any_issue,
        "issue_counts_json": json.dumps(issue_counts, ensure_ascii=False, sort_keys=True),
        "min_verification_sources": min(source_counts) if source_counts else 0,
        "max_verification_sources": max(source_counts) if source_counts else 0,
        "top_source_hosts": "; ".join(f"{host}:{count}" for host, count in source_url_hosts.most_common(8)),
        "primary_csv": config["primary_csv"],
        "folder": config["folder"].relative_to(ROOT).as_posix(),
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "dataset_id",
        "status",
        "row_count",
        "rows_with_any_issue",
        "issue_counts_json",
        "min_verification_sources",
        "max_verification_sources",
        "top_source_hosts",
        "folder",
        "primary_csv",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    lines = [
        f"# Source Evidence Integrity Audit ({AUDIT_DATE})",
        "",
        f"- Datasets checked: {len(rows)}",
        f"- Passed: {passed}",
        f"- Failed: {len(rows) - passed}",
        "",
        "## Dataset Results",
        "",
        "| Dataset | Status | Rows | Rows with issues | Min sources | Max sources | Issue counts |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {dataset_id} | {status} | {row_count} | {rows_with_any_issue} | {min_verification_sources} | {max_verification_sources} | {issue_counts_json} |".format(
                **row
            )
        )
    lines.extend(["", "## Scope", ""])
    lines.extend(
        [
            "- Checks every row has a valid primary source URL, nonblank evidence text, parseable `verification_sources`, and at least as many source entries as `verification_count`.",
            "- Confirms the primary source URL is included in `verification_sources` so formal conclusions can trace back to the cited official/public source.",
            "- This is a structural audit of preserved source evidence. It does not replace manual webpage/PDF opening for newly collected data points.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(rows: list[dict[str, Any]], path: Path, csv_path: Path, md_path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    failed = len(rows) - passed
    manifest = {
        "id": "source_evidence_audits",
        "title": "小竞AI来源链接与证据完整性审计",
        "summary": "检查宏观政策、季度/半年度竞对、云厂商数据包每行是否保留可解析来源链接、证据文本和 verification_sources。",
        "source_type": "local_audit",
        "scope": "official/public source links, evidence notes, verification_count alignment, and RAG source traceability.",
        "updated_at": AUDIT_DATE,
        "tags": ["audit", "source-integrity", "evidence", "verification-sources"],
        "keywords": [
            "source_evidence_audits",
            "verification_sources",
            "official_source_url",
            "primary_source_url",
            "official_evidence",
            "verification_count",
        ],
        "entrypoints": [md_path.name, csv_path.name],
        "quality": {
            "status": "pass" if failed == 0 else "fail",
            "row_count": len(rows),
            "datasets_checked": len(rows),
            "passed": passed,
            "failed": failed,
            "notes": [
                "结构审计确认来源链接和证据字段存在且可解析。",
                "新增数据点仍需按用户要求逐条打开官方/公开来源核实。",
                "若本审计失败，不能把相关数据用于正式结论。",
            ],
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = [audit_dataset(config) for config in DATASETS]
    csv_path = OUT_ROOT / f"source_evidence_integrity_{AUDIT_DATE}.csv"
    md_path = OUT_ROOT / f"source_evidence_integrity_{AUDIT_DATE}.md"
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
            print(f"failed {row['dataset_id']}: {row['issue_counts_json']}")
        raise SystemExit(1)
    print("all source evidence cases passed")


if __name__ == "__main__":
    main()
