#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "agent_evals"
sys.path.insert(0, str(ROOT))

from agent import search_local_reports, trigger_full_crawl  # noqa: E402
from agent_memory import load_memories  # noqa: E402
from agent_production import eval_summary_line  # noqa: E402
from rag_llm import build_context_package, retrieve_context  # noqa: E402


def case(name: str, passed: bool, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "details": details or {}}


def main() -> int:
    rows: list[dict[str, Any]] = []
    selected = {"quarterly_competitor_metrics_2026-06-18", "cloud_vendor_database", "cmhk_macro_policy_2026-06-19"}

    chunks = retrieve_context("中国移动 2026Q1 收入 official_value verification_count", limit=10, dataset_ids=selected)
    package = build_context_package(chunks, token_budget=6500, model="deepseek-chat")
    ctx = package["context"]
    rows.append(
        case(
            "competitor_rag_official_value",
            "中国移动" in ctx and ("266,478" in ctx or "266478" in ctx) and "verification_count" in ctx,
            {"chunks": len(chunks), "audit": package["audit"]},
        )
    )

    macro_chunks = retrieve_context("OFCA Key Communications Statistics CMHK 收入预测目标 解释变量", limit=10, dataset_ids=selected)
    macro_text = "\n".join(str(item.get("text") or "") for item in macro_chunks)
    rows.append(
        case(
            "macro_not_target_variable",
            "OFCA" in macro_text and ("预测" in macro_text or "exogenous" in macro_text or "解释" in macro_text),
            {"chunks": len(macro_chunks)},
        )
    )

    cloud_chunks = retrieve_context("AWS revenue 未来4个季度", limit=10, dataset_ids=selected)
    cloud_text = "\n".join(str(item.get("text") or "") for item in cloud_chunks)
    rows.append(
        case(
            "cloud_vendor_retrieval",
            "AWS" in cloud_text and ("revenue" in cloud_text or "收入" in cloud_text),
            {"chunks": len(cloud_chunks)},
        )
    )

    denied = trigger_full_crawl.invoke({})
    rows.append(
        case(
            "dangerous_action_requires_confirmation",
            "需要用户确认" in denied and "action_confirmation" in denied,
            {"preview": denied[:300]},
        )
    )

    rows.append(
        case(
            "memory_loads_without_error",
            isinstance(load_memories(limit=5), list),
            {"count": len(load_memories(limit=5))},
        )
    )

    # Tool-level RAG result should carry contextAudit and retrievalQuality metadata.
    rag_result = search_local_reports.invoke({"query": "中国移动 2026Q1 收入 official_value verification_count"})
    rows.append(
        case(
            "rag_metadata_contains_quality",
            "contextAudit" in rag_result and "retrievalQuality" in rag_result,
            {"preview": rag_result[-800:]},
        )
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "latest_agent_evals.json"
    summary = {"ok": all(item["passed"] for item in rows), "summary": eval_summary_line(rows), "cases": rows}
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
