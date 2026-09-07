"""A single final reviewer can search again before the one database writer runs."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .storage import atomic_write_json, atomic_write_jsonl
from .six_agent_research import collect_sources, merge_results, now, validate_fact, page_mentions_metric
from .research_freshness import compare_candidate


def review_run(directory: Path, *, model_factory=None, collector=None, harness_factory=None) -> dict:
    from . import workflow as w
    from .research_harness import ResearchHarness

    summary = json.loads((directory / "manifest.json").read_text())
    if summary.get("final_review", {}).get("status") == "completed":
        return summary
    collector = collector or collect_sources
    harness_factory = harness_factory or ResearchHarness
    factory = model_factory or (lambda: w._build_supervisor_model(max_tokens=4096, max_retries=0))
    task = {"key": "final-review", "title": "最终审核 Agent", "purpose": "逐公司核对最新指标；缺失或失败可继续联网搜索，一个可信原文即可，不要求三个来源"}
    checkpoint_path = directory / "final-review.json"
    checkpoint = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {**task, "status": "running", "reports": []}
    completed = {r["company"] for r in checkpoint["reports"] if r.get("review_completed")}
    results = [json.loads((directory / f"{t['key']}.json").read_text()) for t in summary["plan"]]
    baseline_path = directory / "baseline.json"
    baseline = json.loads(baseline_path.read_text()).get("companies", {}) if baseline_path.exists() else {}

    def emit(phase, message, data):
        event = {"ts": now(), "run_id": summary["run_id"], "agent_id": task["key"], "node": task["title"],
                 "phase": phase, "message": message, "data": data}
        with (directory / "trace.jsonl").open("a") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        print("RESEARCH_EVENT=" + json.dumps({k: v for k, v in event.items() if k != "data"}, ensure_ascii=False), flush=True)

    summary["final_review"] = {"status": "running", "started_at": now(), "source_requirement": "one_trusted_source"}
    atomic_write_json(directory / "manifest.json", summary)
    harness = harness_factory(task, factory(), emit, validate_fact)
    for agent in results:
        for index, initial in enumerate(agent["reports"]):
            company = initial["company"]
            if company in completed:
                agent["reports"][index] = next(r for r in checkpoint["reports"] if r["company"] == company)
                continue
            report = next((r for r in checkpoint["reports"] if r["company"] == company), None)
            if report is None:
                report = json.loads(json.dumps(initial))
                report["reviewed_metrics"] = []
                checkpoint["reports"].append(report)
            report.setdefault("pages", {})
            report.setdefault("searches", [])
            report.setdefault("baseline", baseline.get(company, {}))
            report.setdefault("incremental", True)
            metrics = [i["metric"] for i in report["items"] if i.get("status") not in {"verified", "no_update", "not_applicable"}]
            emit("review_start", f"{company}：最终审核并补查 {len(metrics)} 项指标", {"company": company, "metrics": metrics})
            # Persist collected pages separately before any inference; resume never repeats a completed search.
            if metrics and not report.get("review_search_completed"):
                try:
                    pages, searches = collector(company, metrics, emit, report.get("baseline", {}))
                    report["pages"].update(pages)
                    report["searches"] = [*report.get("searches", []), *searches]
                except Exception as exc:
                    report["review_search_error"] = str(exc)[:500]
                report["review_search_completed"] = True
                atomic_write_json(checkpoint_path, checkpoint)
            for metric in metrics:
                if metric in report["reviewed_metrics"]:
                    continue
                def save(item):
                    item = compare_candidate(item, report.get("baseline", {}))
                    item["final_reviewed"] = True
                    report["items"] = [row for row in report["items"] if row["metric"] != metric] + [item]
                    report["reviewed_metrics"].append(metric)
                    atomic_write_json(checkpoint_path, checkpoint)
                    emit("review_metric_saved", f"{company}：{metric}最终结果已保存", item)
                try:
                    if not any(p.get("opened") and p.get("official") for p in report["pages"].values()):
                        raise RuntimeError("最终审核仍无法读取可信来源；不能确认该指标最新内容")
                    if not page_mentions_metric(metric, report["pages"]):
                        save({"company": company, "metric": metric, "status": "error", "value": "",
                              "reason": "最终审核已补充搜索并读取可信原文，仍未找到该指标的可核实内容；原有数据保留"})
                    else:
                        harness.extract(company, metric, report["pages"], save, baseline=report.get("baseline", {}))
                except Exception as exc:
                    if metric not in report["reviewed_metrics"]:
                        save({"company": company, "metric": metric, "status": "error", "value": "", "reason": str(exc)[:500]})
            report["review_completed"] = True
            report["status"] = "partial" if any(i["status"] not in {"verified", "no_update", "not_applicable"} for i in report["items"]) else "completed"
            agent["reports"][index] = report
            atomic_write_json(checkpoint_path, checkpoint)
        agent["status"] = "completed" if all(r["status"] == "completed" for r in agent["reports"]) else "partial"
        atomic_write_json(directory / f"{agent['key']}.json", agent)
    facts = merge_results(results, summary["run_id"])
    for agent in results:
        atomic_write_json(directory / f"{agent['key']}.json", agent)
    atomic_write_jsonl(directory / "candidate_facts.jsonl", facts)
    accepted = [f for f in facts if f["decision"] == "accepted"]
    atomic_write_jsonl(directory / "verified_facts.jsonl", accepted)
    counts = Counter(f["research_status"] for f in facts)
    failures = sum(count for state, count in counts.items() if state not in {"verified", "no_update"})
    checkpoint["status"] = "completed"
    atomic_write_json(checkpoint_path, checkpoint)
    summary.update(accepted=len(accepted), review=failures, unchanged=counts["no_update"],
                   agents=[{k: v for k, v in agent.items() if k != "reports"} for agent in results],
                   business_status="updates_available" if accepted else "needs_review" if failures else "no_new_disclosures",
                   tasks=len(facts), metric_status_counts=dict(counts),
                   outcome_counts={"existing": counts["no_update"], "updated": len(accepted), "failed": failures},
                   status="partial" if failures else "completed", completed_at=now(),
                   completed_companies=sum(r["status"] == "completed" for a in results for r in a["reports"]))
    summary["final_review"].update(status="completed", completed_at=now())
    atomic_write_json(directory / "manifest.json", summary)
    return summary
