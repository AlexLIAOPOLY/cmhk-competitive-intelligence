"""Read-only, date-scoped evidence for the six-agent process diagram."""
from __future__ import annotations

import json
import os
import re
from datetime import date as calendar_date
from pathlib import Path

from .research_plan import ARCHITECTURE_VERSION, research_plan
from cmhk.intelligence.ai_provenance import model_generated_only
from .six_agent_research import now


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _task_for_run(root: Path, directory: Path, manifest: dict) -> dict | None:
    try:
        launch = json.loads((directory / "process.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        launch = {}
    task_run_id = str(launch.get("task_run_id") or "")
    research_id = str(manifest.get("run_id") or "")
    try:
        index = json.loads((root / "agent_knowledge/crawl_run_logs/index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = []
    records = index if isinstance(index, list) else index.get("runs", index.get("items", []))
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        summary = record.get("operational_summary") if isinstance(record.get("operational_summary"), dict) else {}
        matches_task = bool(
            task_run_id
            and str(record.get("crawl_run_id") or "") == task_run_id
        )
        matches_research = bool(
            research_id
            and str(summary.get("agent_run_id") or "") == research_id
        )
        if matches_task or matches_research:
            failure_stage = str(record.get("failure_stage") or "")
            cancelled = failure_stage == "user_cancelled" or bool(
                summary.get("cancelled_by_user")
            )
            return {
                "task_id": "crawl:" + str(record.get("crawl_run_id") or task_run_id),
                "run_status": (
                    "cancelled"
                    if cancelled
                    else str(record.get("run_status") or "")
                ),
                "failure_stage": failure_stage,
                "status_detail": str(record.get("status_detail") or ""),
                "started_at_hkt": str(record.get("started_at_hkt") or ""),
                "completed_at_hkt": str(record.get("completed_at_hkt") or ""),
            }
    if launch or manifest:
        return {
            "task_id": "research:" + directory.name,
            "run_status": "running" if _process_alive(int(launch.get("pid") or 0)) else "failed",
            "failure_stage": "",
            "status_detail": "任务归档索引缺失，已从研究运行目录恢复。",
            "started_at_hkt": str(manifest.get("started_at") or launch.get("launched_at") or ""),
            "completed_at_hkt": str(manifest.get("completed_at") or ""),
        }
    return None


def _reconcile_run_status(root: Path, directory: Path, manifest: dict) -> tuple[dict, dict | None]:
    task = _task_for_run(root, directory, manifest)
    publication = manifest.get("publication") if isinstance(manifest.get("publication"), dict) else {}
    final_review = manifest.get("final_review") if isinstance(manifest.get("final_review"), dict) else {}
    cancelled = bool(publication.get("cancelled_by_user")) or str((task or {}).get("failure_stage") or "") == "user_cancelled"
    terminal_task = str((task or {}).get("run_status") or "") in {"completed", "failed", "error", "cutoff", "cancelled"}
    terminal_publication = str(publication.get("status") or "") in {"completed", "failed", "error", "cancelled"}
    if str(final_review.get("status") or "") == "running" and (terminal_task or terminal_publication):
        final_review = dict(final_review)
        final_review["recorded_status"] = "running"
        final_review["status"] = "cancelled" if cancelled else "error"
        final_review["completed_at"] = str(publication.get("completed_at") or (task or {}).get("completed_at_hkt") or manifest.get("completed_at") or "")
        manifest["final_review"] = final_review
    if cancelled:
        if task:
            task = dict(task)
            task["run_status"] = "cancelled"
        manifest["display_status"] = "cancelled"
        publication = dict(publication)
        publication["recorded_status"] = str(publication.get("status") or "")
        publication["status"] = "cancelled"
        manifest["publication"] = publication
    return manifest, task


def _display_results(payload):
    from .research_freshness import period_key, metric_key
    from .research_source_audit import annotate_snapshot
    for agent in [*payload.get("agents", []), payload.get("final_reviewer") or {}]:
        for report in agent.get("reports", []):
            for item in report.get("items", []):
                baseline = item.get("baseline") or report.get("baseline", {}).get(metric_key(item.get("metric")), [])
                if baseline and not item.get("latest_baseline"):
                    item["latest_baseline"] = max(baseline, key=lambda row: period_key(row.get("period")) or (0, 0, ""))
    return annotate_snapshot(payload)


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
    manifest, task = _reconcile_run_status(root, directory, manifest)
    payload["run"] = manifest
    payload["task"] = task
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
    # Archived completion flags are not proof that current files still contain
    # the data. Detect a later deployment overwrite as well as a failed write.
    if manifest.get("research_policy") == "latest_disclosure_incremental_v1" and manifest.get("publication"):
        from .research_storage import audit_storage
        check = audit_storage(root, payload.get("accepted_items") or [], expected=int(manifest.get("accepted") or 0))
        payload["storage_readback"] = check
        publication = dict(manifest["publication"])
        publication["recorded_database_updated"] = publication.get("database_updated", False)
        publication["database_updated"] = check["ok"] and check["accepted"] > 0
        publication["storage_readback"] = check
        manifest["publication"] = publication
        receipts = {item["id"]: item for item in check["items"]}
        from .research_storage import fact_id
        for item in payload.get("accepted_items") or []:
            item["storage"] = receipts.get(fact_id(item))
    # A latest analysis belongs to this date only when the research run ID matches.
    payload["insight_items"] = []
    try:
        analysis = json.loads((root / "agent_knowledge/executive_intelligence_refresh/ai_analysis.json").read_text(encoding="utf-8"))
        if (analysis.get("agent_run_id") == manifest.get("run_id")
                and str((analysis.get("model_analysis") or {}).get("generated_at_hkt", "")) >= str(manifest.get("started_at", ""))):
            model = analysis.get("model_analysis") or {}
            # Legacy template bundles remain archived, never reclassified as AI.
            if model_generated_only(model):
                payload["insight_items"] = [dict(item, domain=summary.get("domain"))
                    for summary in model.get("summaries", []) for item in summary.get("focuses", [])]
                payload["insight_items"] += [dict(item, domain="cross") for item in model.get("discoveries", [])]
            else:
                # The archived mixed batch separately attests its four model-made
                # discoveries. Show those historical outputs, never its templates;
                # this exception is display-only and cannot admit a cache/publication.
                recorded = (manifest.get("publication") or {}).get("model_analysis") or {}
                if (recorded.get("discovery_model") == model.get("discovery_model")
                        and recorded.get("discovery_model")
                        and "fallback" not in str(model.get("discovery_model"))
                        and recorded.get("evidence_hash") == model.get("evidence_hash")
                        and not recorded.get("discovery_fallback_used")
                        and not model.get("discovery_fallback_used")
                        and not model.get("manual_discovery_regeneration")
                        and model.get("discovery_evidence_repair_count") == 0
                        and len(model.get("discoveries") or []) == recorded.get("discoveries_passed")):
                    payload["insight_items"] = [dict(item, domain="cross", origin="historical_ai")
                        for item in model.get("discoveries", [])]
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
        from .review_store import load_review
        payload["final_reviewer"] = load_review(directory, evidence=False)
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
