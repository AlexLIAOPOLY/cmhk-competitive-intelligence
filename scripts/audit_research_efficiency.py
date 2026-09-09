#!/usr/bin/env python3
"""Read a research trace without invoking models, crawling, or changing its state."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def audit(directory: Path) -> dict:
    agents = {}
    incomplete_lines = 0
    first = last = None
    for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            incomplete_lines += 1
            continue
        first = first or event.get("ts")
        last = event.get("ts")
        row = agents.setdefault(event.get("agent_id", "unknown"), {
            "model_responses": 0, "responses_with_usage": 0, "provider_tokens": Counter(),
            "finish_reasons": Counter(), "model_elapsed_ms": [], "queries": [],
            "explicitly_reused_queries": 0, "read_records": 0, "cached_read_records": 0,
            "contexts": 0, "original_context_characters": 0, "packed_context_characters": 0,
        })
        data = event.get("data") or {}
        phase = event.get("phase")
        if phase == "model_response":
            row["model_responses"] += 1
            usage = data.get("usage")
            if isinstance(usage, dict):
                row["responses_with_usage"] += 1
                row["provider_tokens"].update({k: v for k, v in usage.items() if isinstance(v, int)})
            row["finish_reasons"][data.get("finish_reason") or "unknown"] += 1
            if isinstance(data.get("elapsed_ms"), (float, int)):
                row["model_elapsed_ms"].append(data["elapsed_ms"])
        elif phase == "search":
            row["queries"].append((data.get("company"), data.get("query")))
            row["explicitly_reused_queries"] += bool(data.get("query_reused"))
        elif phase == "read":
            row["read_records"] += 1
            row["cached_read_records"] += bool(data.get("cache_hit"))
        elif phase == "model_context":
            row["contexts"] += 1
            row["original_context_characters"] += data["original_characters"]
            row["packed_context_characters"] += data["packed_characters"]
    for row in agents.values():
        queries = row.pop("queries")
        row["search_records"] = len(queries)
        row["distinct_company_queries"] = len(set(queries))
        times = row.pop("model_elapsed_ms")
        row["timed_model_responses"] = len(times)
        row["recorded_model_elapsed_ms_sum"] = sum(times) if times else None
        if not row["responses_with_usage"]:
            row["provider_tokens"] = None
        if not row["contexts"]:
            row["original_context_characters"] = row["packed_context_characters"] = None
    return {"run_id": directory.name, "first_event_at": first, "last_event_at": last,
            "unreadable_lines": incomplete_lines, "agents": agents,
            "measurement_boundary": "Provider-reported usage only; missing usage/timing is unknown. "
                "Parallel duration sums are not wall time. Duplicate search records are not necessarily redundant requests. "
                "Context character reduction is not billed token reduction. Active traces may be incomplete."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), ensure_ascii=False, indent=2))
