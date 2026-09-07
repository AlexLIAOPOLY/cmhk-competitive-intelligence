"""Read-only, date-scoped evidence for the six-agent process diagram."""
from __future__ import annotations

import json
import re
from datetime import date as calendar_date
from pathlib import Path

from .research_plan import ARCHITECTURE_VERSION, research_plan
from .six_agent_research import now


def _display_results(payload):
    from .research_freshness import period_key, metric_key
    for agent in [*payload.get("agents", []), payload.get("final_reviewer") or {}]:
        for report in agent.get("reports", []):
            for item in report.get("items", []):
                baseline = item.get("baseline") or report.get("baseline", {}).get(metric_key(item.get("metric")), [])
                if baseline:
                    item["latest_baseline"] = max(baseline, key=lambda row: period_key(row.get("period")) or (0, 0, ""))
    return payload


def research_snapshot(root: Path, date: str = "") -> dict:
    date = date or now()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("日期格式必须为YYYY-MM-DD")
    calendar_date.fromisoformat(date)
    runs = []
    for path in (root / "curation_data" / "research_runs").glob("*/manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if manifest.get("architecture") == ARCHITECTURE_VERSION and str(manifest.get("started_at", ""))[:10] == date:
            runs.append((manifest, path.parent))
    runs.sort(key=lambda item: str(item[0].get("started_at", "")), reverse=True)
    payload = {"ok": True, "architecture": ARCHITECTURE_VERSION, "date": date, "plan": research_plan(),
               "runs": [manifest for manifest, _ in runs], "run": None, "agents": [], "events": []}
    if not runs:
        return _display_results(payload)
    manifest, directory = runs[0]
    payload["run"] = manifest
    # Historical details must use the assignments that actually executed.
    payload["plan"] = manifest.get("plan") or payload["plan"]
    for key, filename in (("accepted_items", "verified_facts.jsonl"), ("result_items", "candidate_facts.jsonl")):
        path = directory / filename
        payload[key] = None
        if path.exists():
            try:
                payload[key] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except (OSError, ValueError):
                pass
    # A latest analysis belongs to this date only when the research run ID matches.
    payload["insight_items"] = []
    try:
        analysis = json.loads((root / "agent_knowledge/executive_intelligence_refresh/ai_analysis.json").read_text(encoding="utf-8"))
        if (analysis.get("agent_run_id") == manifest.get("run_id")
                and str((analysis.get("model_analysis") or {}).get("generated_at_hkt", "")) >= str(manifest.get("started_at", ""))):
            model = analysis.get("model_analysis") or {}
            payload["insight_items"] = [dict(item, domain=summary.get("domain"))
                for summary in model.get("summaries", []) for item in summary.get("focuses", [])]
            payload["insight_items"] += [dict(item, domain="cross") for item in model.get("discoveries", [])]
    except (OSError, ValueError):
        pass
    for task in payload["plan"]:
        path = directory / f"{task['key']}.json"
        try:
            agent = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            agent = {**task, "status": "pending", "reports": []}
        # Keep full queries, responses and passage excerpts; full page bodies
        # are archived on disk rather than duplicated into every UI refresh.
        for report in agent.get("reports", []):
            report["pages"] = {url: {key: value for key, value in page.items() if key != "text"}
                               for url, page in report.get("pages", {}).items()}
        payload["agents"].append(agent)
    try:
        payload["final_reviewer"] = json.loads((directory / "final-review.json").read_text(encoding="utf-8"))
        for report in payload["final_reviewer"].get("reports", []):
            report["pages"] = {url: {k: v for k, v in page.items() if k != "text"}
                               for url, page in report.get("pages", {}).items()}
    except (OSError, ValueError):
        payload["final_reviewer"] = None
    trace_path = directory / "trace.jsonl"
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("run_id") == manifest.get("run_id"):
                payload["events"].append(event)
    return _display_results(payload)
