"""Three independent company reviewers feed one deterministic final merge/writer."""
from __future__ import annotations

import fcntl
import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .storage import atomic_write_json, atomic_write_jsonl
from .six_agent_research import collect_sources, merge_results, now, validate_fact, page_mentions_metric
from .research_freshness import compare_candidate, metric_key
from .review_store import ReviewStore, load_company


def review_run(directory: Path, *, model_factory=None, collector=None, harness_factory=None, workers: int = 3) -> dict:
    if not 1 <= workers <= 3:
        raise ValueError("最终审核并发数必须为1至3")
    with (directory / "final-review.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _review_run(directory, model_factory=model_factory, collector=collector,
                           harness_factory=harness_factory, workers=workers)


def _review_run(directory: Path, *, model_factory, collector, harness_factory, workers: int) -> dict:
    from . import workflow as w
    from .research_harness import ResearchHarness

    summary = json.loads((directory / "manifest.json").read_text())
    if summary.get("final_review", {}).get("status") == "completed":
        return summary
    collector = collector or collect_sources
    harness_factory = harness_factory or ResearchHarness
    factory = model_factory or (lambda: w._build_supervisor_model(max_tokens=4096, max_retries=0))
    task = {"key": "final-review", "title": "最终审核 Agent", "purpose": f"{workers}路独立公司审核并行补查；逐项核验后统一汇总，一个可信原文即可，不要求三个来源"}
    results = [json.loads((directory / f"{t['key']}.json").read_text()) for t in summary["plan"]]
    companies = [r["company"] for agent in results for r in agent["reports"]]
    from .research_freshness import load_baseline
    baseline = load_baseline(directory.parent.parent.parent).get("companies", {})
    store = ReviewStore(directory, task, summary["run_id"], companies, workers)
    trace_lock = threading.Lock()

    def emit(phase, message, data):
        event = {"ts": now(), "run_id": summary["run_id"], "agent_id": task["key"], "node": task["title"],
                 "phase": phase, "message": message, "data": data}
        with trace_lock, (directory / "trace.jsonl").open("a") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        print("RESEARCH_EVENT=" + json.dumps({k: v for k, v in event.items() if k != "data"}, ensure_ascii=False), flush=True)

    summary["final_review"] = {"status": "running", "started_at": summary.get("final_review", {}).get("started_at") or now(),
                               "source_requirement": "one_trusted_source", "workers": workers,
                               "execution": "parallel_company_review_v1"}
    atomic_write_json(directory / "manifest.json", summary)
    local = threading.local()
    def worker_harness():
        if not hasattr(local, "harness"):
            local.harness = harness_factory(task, factory(), emit, validate_fact)
        return local.harness

    def review_company(initial):
        company = initial["company"]
        report = load_company(directory, company, evidence=True, run_id=summary["run_id"])
        if report is None:
            report = json.loads(json.dumps(initial))
            report["reviewed_metrics"] = []
            store.save(report, evidence_changed=True)
        if report.get("review_completed"):
            return report
        report.setdefault("reviewed_metrics", [])
        report.setdefault("pages", {})
        report.setdefault("searches", [])
        report["baseline"] = baseline.get(company, {})
        report.setdefault("incremental", True)
        for position, item in enumerate(report["items"]):
            if item.get("status") == "no_update" and not report["baseline"].get(metric_key(item.get("metric"))):
                item.update(status="conflict", value="", reason="库内未找到该指标基线，最终审核须继续补查，不能标记库内已有")
            if item.get("status") == "verified":
                report["items"][position] = compare_candidate(
                    validate_fact(item, company, report["metrics"], report["pages"]), report["baseline"])
        metrics = [i["metric"] for i in report["items"] if i.get("status") not in {"verified", "no_update", "not_applicable"}]
        emit("review_start", f"{company}：最终审核并补查 {len(metrics)} 项指标", {"company": company, "metrics": metrics})
        # Persist collected pages separately before any inference; resume never repeats a completed search.
        if metrics and not report.get("review_search_completed"):
            try:
                pages, searches = collector(company, metrics, emit, report.get("baseline", {}))
                # A failed re-read must never erase already archived evidence.
                for url, page in pages.items():
                    if page.get("opened") or not report["pages"].get(url, {}).get("opened"):
                        report["pages"][url] = page
                report["searches"] = [*report.get("searches", []), *searches]
            except Exception as exc:
                report["review_search_error"] = str(exc)[:500]
            report["review_search_completed"] = True
            store.save(report, evidence_changed=True)
        for metric in metrics:
            if metric in report["reviewed_metrics"]:
                continue
            def save(item):
                item = compare_candidate(item, report.get("baseline", {}))
                item["final_reviewed"] = True
                report["items"] = [row for row in report["items"] if row["metric"] != metric] + [item]
                report["reviewed_metrics"].append(metric)
                store.save(report)
                emit("review_metric_saved", f"{company}：{metric}最终结果已保存", item)
            try:
                if not any(p.get("opened") and p.get("official") for p in report["pages"].values()):
                    raise RuntimeError("最终审核仍无法读取可信来源；不能确认该指标最新内容")
                if not page_mentions_metric(metric, report["pages"]):
                    save({"company": company, "metric": metric, "status": "error", "value": "",
                          "reason": "最终审核已补充搜索并读取可信原文，仍未找到该指标的可核实内容；原有数据保留"})
                else:
                    worker_harness().extract(company, metric, report["pages"], save, baseline=report.get("baseline", {}))
            except Exception as exc:
                if metric not in report["reviewed_metrics"]:
                    save({"company": company, "metric": metric, "status": "error", "value": "", "reason": str(exc)[:500]})
        report["review_completed"] = True
        report["status"] = "partial" if any(i["status"] not in {"verified", "no_update", "not_applicable"} for i in report["items"]) else "completed"
        store.save(report)
        return report

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="final-review") as pool:
        futures = {pool.submit(review_company, initial): (agent, index)
                   for agent in results for index, initial in enumerate(agent["reports"])}
        for future in as_completed(futures):
            agent, index = futures[future]
            agent["reports"][index] = future.result()
    # Only the coordinator writes aggregate facts and original agent reports.
    for agent in results:
        agent["status"] = "completed" if all(r["status"] == "completed" for r in agent["reports"]) else "partial"
    facts = merge_results(results, summary["run_id"])
    from .research_kpi import prepare_facts, persist_preflight
    facts, write_preflight = prepare_facts(directory.parent.parent.parent, facts, summary["run_id"])
    persist_preflight(directory, results, facts, write_preflight, summary, store=store)
    store.complete()
    summary["completed_at"] = now()
    summary["final_review"].update(status="completed", completed_at=now())
    atomic_write_json(directory / "manifest.json", summary)
    return summary
