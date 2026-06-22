#!/usr/bin/env python3
"""Audit Agent prompts and local skills for guidance alignment."""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DATE = date.today().isoformat()
OUT_ROOT = ROOT / "agent_knowledge" / "agent_guidance_alignment_audits"

AGENT_PY = ROOT / "agent.py"
SKILLS_ROOT = ROOT / "Codex" / "agent" / "skills"
LATEST_QUARTERLY_ID = "quarterly_competitor_metrics_2026-06-18"
SUPERSEDED_QUARTERLY_ID = "quarterly_competitor_metrics_2026-06-17"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def make_row(check_id: str, status: str, evidence: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "evidence": evidence,
        "details_json": json.dumps(details, ensure_ascii=False, sort_keys=True),
    }


def audit_system_prompt() -> list[dict[str, Any]]:
    text = read_text(AGENT_PY)
    required = [
        "目标级审计优先",
        "goal_readiness_audits",
        "knowledge_integrity_audits",
        "source_evidence_audits",
        "source_url_reachability_audits",
        "forecast_readiness_audits",
        "agent_dataset_visibility_audits",
        "superseded",
        "不得作为默认数据库或正式结论来源",
    ]
    missing = [item for item in required if item not in text]
    return [
        make_row(
            "agent_system_prompt_requires_goal_audits",
            "pass" if not missing else "fail",
            "agent.py",
            {"missing_required_phrases": missing},
        )
    ]


def audit_skill(skill_id: str, required: list[str], forbidden: list[str] | None = None) -> dict[str, Any]:
    path = SKILLS_ROOT / skill_id / "SKILL.md"
    text = read_text(path)
    missing = [item for item in required if item not in text]
    found_forbidden = [item for item in (forbidden or []) if item in text]
    return make_row(
        f"skill_{skill_id}_alignment",
        "pass" if not missing and not found_forbidden else "fail",
        path.relative_to(ROOT).as_posix(),
        {
            "missing_required_phrases": missing,
            "found_forbidden_phrases": found_forbidden,
        },
    )


def audit_quarterly_skill_superseded_boundary() -> dict[str, Any]:
    path = SKILLS_ROOT / "quarterly-competitor-metrics" / "SKILL.md"
    text = read_text(path)
    old_mentions = [match.start() for match in re.finditer(re.escape(SUPERSEDED_QUARTERLY_ID), text)]
    old_contexts = [
        text[max(0, index - 80) : min(len(text), index + 160)]
        for index in old_mentions
    ]
    unsafe_old_mentions = [
        context
        for context in old_contexts
        if not ("superseded" in context and ("不得" in context or "审计历史" in context))
    ]
    required = [
        LATEST_QUARTERLY_ID,
        SUPERSEDED_QUARTERLY_ID,
        "superseded",
        "不得作为默认数据库或正式结论来源",
        "goal_readiness_audits",
        "official_verified_metrics_2026-06-18.csv",
        "online_verification_2026-06-18.md",
    ]
    missing = [item for item in required if item not in text]
    forbidden = [
        "official_verified_metrics_2026-06-17.csv",
        "online_verification_2026-06-17.md",
        "online_verification_2026-06-17.csv",
    ]
    found_forbidden = [item for item in forbidden if item in text]
    status = "pass" if not missing and not found_forbidden and not unsafe_old_mentions else "fail"
    return make_row(
        "skill_quarterly_uses_latest_package_and_marks_old_superseded",
        status,
        path.relative_to(ROOT).as_posix(),
        {
            "missing_required_phrases": missing,
            "found_forbidden_phrases": found_forbidden,
            "unsafe_old_package_contexts": unsafe_old_mentions,
        },
    )


def audit_all() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(audit_system_prompt())
    rows.append(audit_quarterly_skill_superseded_boundary())
    rows.append(
        audit_skill(
            "trend-forecasting",
            [
                "goal_readiness_audits",
                "knowledge_integrity_audits",
                "forecast_readiness_alignment",
                "forecast_quarterly_metric",
                "source_gap_confirmed",
            ],
        )
    )
    rows.append(
        audit_skill(
            "source-verification",
            [
                "goal_readiness_audits",
                "knowledge_integrity_audits",
                "source_evidence_audits",
                "source_url_reachability_audits",
                "agent_dataset_visibility_audits",
                "superseded",
            ],
        )
    )
    rows.append(
        audit_skill(
            "macro-policy-context",
            [
                "goal_readiness_audits",
                "knowledge_integrity_audits",
                "official_value",
                "source_gap_confirmed",
                "forecast_quarterly_metric",
            ],
        )
    )
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = ["check_id", "status", "evidence", "details_json"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    lines = [
        f"# Agent Guidance Alignment Audit ({AUDIT_DATE})",
        "",
        f"- Checks: {len(rows)}",
        f"- Passed: {passed}",
        f"- Failed: {len(rows) - passed}",
        "",
        "## Check Results",
        "",
        "| Check | Status | Evidence | Details |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        details = json.loads(row["details_json"])
        lines.append(f"| {row['check_id']} | {row['status']} | {row['evidence']} | `{json.dumps(details, ensure_ascii=False, sort_keys=True)}` |")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- Verifies the Agent system prompt and key local skills route data-quality, prediction, source-verification, and macro-policy questions through goal-level audits.",
            "- Verifies the quarterly skill points to the latest official quarterly package and only mentions the old package as superseded audit history.",
            "- This audit prevents prompt/skill drift from bypassing source, forecast, or database visibility gates.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(rows: list[dict[str, Any]], path: Path, csv_path: Path, md_path: Path) -> None:
    passed = sum(1 for row in rows if row["status"] == "pass")
    failed = len(rows) - passed
    manifest = {
        "id": "agent_guidance_alignment_audits",
        "title": "小竞AI Agent提示与Skill对齐审计",
        "summary": "检查 Agent 系统提示和关键项目内 skills 是否优先使用目标级审计、正式使用最新季度包，并把旧季度包限定为 superseded 审计历史。",
        "source_type": "local_audit",
        "scope": "Agent prompt, local skills, goal-readiness routing, superseded package handling, and forecast/source-verification guidance.",
        "updated_at": AUDIT_DATE,
        "tags": ["audit", "agent-guidance", "skills", "prompt", "superseded"],
        "keywords": ["agent_guidance_alignment_audits", "goal_readiness_audits", "superseded", "quarterly_competitor_metrics_2026-06-18", "source-verification"],
        "entrypoints": [md_path.name, csv_path.name],
        "quality": {
            "status": "pass" if failed == 0 else "fail",
            "row_count": len(rows),
            "checks": len(rows),
            "passed": passed,
            "failed": failed,
            "notes": [
                "Agent and skills must use goal-level audit evidence for data quality and prediction readiness questions.",
                "Superseded packages may be mentioned only as audit history, not as default or formal conclusion sources.",
            ],
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = audit_all()
    csv_path = OUT_ROOT / f"agent_guidance_alignment_{AUDIT_DATE}.csv"
    md_path = OUT_ROOT / f"agent_guidance_alignment_{AUDIT_DATE}.md"
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
            print(f"failed {row['check_id']}: {row['details_json']}")
        raise SystemExit(1)
    print("all agent guidance alignment checks passed")


if __name__ == "__main__":
    main()
