"""Read-only, date-scoped evidence for the six-agent process diagram."""
from __future__ import annotations

import json
import re
from datetime import date as calendar_date
from pathlib import Path

from .research_plan import ARCHITECTURE_VERSION, research_plan
from .six_agent_research import now


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
        return payload
    manifest, directory = runs[0]
    payload["run"] = manifest
    for task in research_plan():
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
    trace_path = directory / "trace.jsonl"
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("run_id") == manifest.get("run_id"):
                payload["events"].append(event)
    return payload
