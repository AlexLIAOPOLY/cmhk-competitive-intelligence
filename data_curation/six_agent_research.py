"""Single-pass research: six long-lived workers -> one merge -> publication.

No fixed URL crawl, discovery handoff, company sub-agents or backward edges.
Research helpers perform I/O; only the six workers call the model. Every task
has a bounded search/read budget and emits its missing fields as results.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from .research_plan import ARCHITECTURE_VERSION, research_plan
from .storage import atomic_write_json, atomic_write_jsonl


HKT = ZoneInfo("Asia/Hong_Kong")
TERMINAL = {"verified", "missing", "conflict", "not_applicable", "error"}


def now() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def metric_value_is_bound(metric: str, value: str, quote: str) -> bool:
    """A matching word elsewhere in a long passage is not a value/metric binding."""
    labels = {
        "通信服务收入": r"communications? service revenue|telecom(?:munications?) service revenue|通信服务收入|通信服務收入",
        "服务收入": r"service revenue|服务收入|服務收入",
        "EBITDA": r"\bEBITDA\b",
        "净利润": r"net (?:profit|income)|profit attributable|净利润|淨利潤|股东应占溢利|股東應佔溢利",
        "资本开支": r"capital expenditure|capital investment|\bcapex\b|资本开支|資本開支|资本支出|資本支出",
        "ARPU": r"\bARPU\b|average revenue per user|average revenue per subscriber|每户平均收入|每戶平均收入",
        "云收入": r"(?:cloud|AWS|Azure|云|雲).{0,65}(?:sales|revenue|收入)|(?:sales|revenue|收入).{0,65}(?:cloud|AWS|Azure|云|雲)",
    }
    label = labels.get(metric)
    number = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", value)
    if not label or not number:
        return True
    token = number.group()
    for match in re.finditer(re.escape(token), quote):
        # Limit the left context to the current clause; do not borrow a label
        # from a previous sentence/row describing a different business metric.
        prefix = quote[max(0, match.start() - 180):match.start()]
        prefix = re.split(r"[。；;•]|(?<=[a-z])\.\s+", prefix)[-1]
        if re.search(label, prefix, re.I):
            return True
    return False


def validate_fact(proposed: dict, company: str, metrics: list[str], pages: dict[str, dict]) -> dict:
    """Bind a proposed value to an actually opened official passage and period.

The model supplies interpretation. This boundary prevents unsupported claims,
different companies, search snippets and invented URLs becoming database facts.
"""
    from . import workflow as w
    item = {key: compact(proposed.get(key)) for key in (
        "company", "metric", "status", "value", "period", "unit", "source_url", "quote", "context_quote", "reason")}
    item["company"] = company
    errors = []
    if proposed.get("company", company) != company:
        errors.append("返回了任务范围以外的公司")
    if item["metric"] not in metrics:
        errors.append("返回了任务范围以外的指标")
    if item["status"] not in TERMINAL:
        errors.append("未返回有效处理状态")
    if item["status"] == "not_applicable" and not w._company_metric_is_not_applicable(company, item["metric"]):
        errors.append("没有不适用依据")
    if item["status"] == "verified":
        page = pages.get(item["source_url"], {})
        body = compact(page.get("text"))
        quote = item["quote"]
        context = item["context_quote"]
        grounded = quote + " " + context
        profile = w._company_research_profile(company)
        # Issuer identity is often in a filing header, not in every financial
        # sentence (which says "the Company"). Bind to the archived header too.
        issuer_header = body[:1500] if re.search(r"\.pdf(?:[?#]|$)|/Archives/edgar/", item["source_url"], re.I) else ""
        if issuer_header and any(w._company_alias_mentions_text(alias, issuer_header) for alias in profile["aliases"]):
            item["entity_quote"] = issuer_header
        if not page.get("opened") or not page.get("official"):
            errors.append("未成功读取该官方原文")
        if len(quote) < 20 or quote not in body:
            errors.append("原文摘录不在实际读取的页面中")
        if context and context not in body:
            errors.append("期间或单位的上下文摘录不在同一原文中")
        if not any(w._company_alias_mentions_text(alias, grounded + " " + item.get("entity_quote", "")) for alias in profile["aliases"]):
            errors.append("摘录没有明确对应公司主体")
        if not item["value"] or item["value"] not in quote:
            errors.append("数值或描述不在引用原文中")
        if not item["period"] or item["period"] not in grounded:
            errors.append("缺少与数据相符的原文期间")
        if w._company_agent_metric_requires_direct_value(item["metric"]) and (
            not item["unit"] or not all(part in grounded for part in item["unit"].split())
        ):
            errors.append("数值缺少原文单位")
        scales = {"billion": r"\bbillions?\b|十亿|十億", "million": r"\bmillions?\b|百万|百萬",
                  "thousand": r"\bthousands?\b|千", "yi": r"(?<!十)亿|(?<!十)億"}
        value_scales = {name for name, pattern in scales.items() if re.search(pattern, item["value"], re.I)}
        unit_scales = {name for name, pattern in scales.items() if re.search(pattern, item["unit"], re.I)}
        if value_scales and unit_scales and value_scales != unit_scales:
            errors.append("数值与单位的数量级不一致，不能混用billion与million等口径")
        monetary = bool(re.search(r"收入|收益|EBITDA|净利润|淨利潤|ARPU|资本开支|資本開支|派息|股息", item["metric"], re.I))
        rendered = item["value"] + " " + item["unit"]
        rate_metric = bool(re.search(r"率|同比|增速|增幅|margin|growth", item["metric"], re.I))
        has_currency = bool(re.search(r"[$€£¥￥]|(?<![A-Za-z])(?:HKD|USD|RMB|CNY|AED|SAR|SGD|AUD|JPY|KRW|EUR|GBP|INR|CAD)(?![A-Za-z])|人民币|人民幣|港币|港幣|日元|韩元|韓圓|美元|新加坡元", rendered, re.I))
        if monetary and not has_currency and not (rate_metric and re.search(r"%|％", rendered)):
            errors.append("金额缺少明确币种；只写million或billion不足以更新金额指标")
        cloud_sales = item["metric"] == "云收入" and bool(re.search(r"sales|revenue|收入", quote, re.I)) and any(
            w._company_alias_mentions_text(alias, quote) for alias in profile["aliases"])
        if not w._evidence_mentions_metric(item["metric"], quote) and not cloud_sales:
            errors.append("引用原文没有对应指标")
        if not metric_value_is_bound(item["metric"], item["value"], quote):
            errors.append("数值所在原文句段没有对应指标标签；不得用总收入替代服务收入等子指标")
        if not w._passes_metric_gate(item["metric"], f"{item['value']} {item['unit']}"):
            errors.append("值不符合指标类型")
        item["evidence_hash"] = hashlib.sha256(body.encode()).hexdigest()
    if errors:
        item["status"] = "conflict"
        item["reason"] = "；".join(errors)
    if item["status"] != "verified":
        item["value"] = ""
    return item


def collect_sources(company: str, metrics: list[str], emit: Callable) -> tuple[dict, list[dict]]:
    from . import workflow as w
    from .schemas import CandidateFact
    profile = w._company_research_profile(company)
    searches = []
    ranked: dict[str, dict] = {}
    # Each required metric is searched once; pages are deduplicated per company.
    for metric in metrics:
        query = w._fact_search_query(CandidateFact(id="search", company=company, metric=metric))
        results, provider = w._public_web_search(query, limit=4, timeout=12.0)
        record = {"company": company, "metric": metric, "query": query, "provider": provider, "results": results}
        searches.append(record)
        emit("search", f"{company}：检索{metric}", record)
        for result in results:
            url = str(result.get("url") or "")
            if w._host_matches_governed_official(url, profile["official_hosts"]):
                ranked.setdefault(url, result)
    for url in profile["seed_urls"]:
        ranked.setdefault(url, {"url": url, "title": "官方参考入口"})
    pages = {}
    for url in list(ranked)[:8]:
        page = w._read_source_page(url, timeout=15.0)
        page = {**page, "official": w._host_matches_governed_official(
            str(page.get("final_url") or url), profile["official_hosts"])}
        pages[url] = page
        emit("read", f"{company}：读取官方原文", {"company": company, **{k: v for k, v in page.items() if k != "text"}})
    return pages, searches


def run_assignment(task: dict, emit: Callable, checkpoint: dict | None = None,
                   model_factory: Callable | None = None, collector: Callable = collect_sources) -> dict:
    from . import workflow as w
    from .research_harness import ResearchHarness
    factory = model_factory or (lambda: w._build_supervisor_model(max_tokens=4096, max_retries=0))
    harness = ResearchHarness(task, factory(), emit, validate_fact)
    reports = list((checkpoint or {}).get("reports") or [])
    completed = {report["company"] for report in reports if report.get("status") == "completed"}
    emit("start", task["purpose"], {"companies": task["companies"]})
    for company in task["companies"]:
        if company in completed:
            continue
        metrics = w._company_expected_metrics(company, [])
        previous = next((report for report in reports if report["company"] == company), {})
        report = {"company": company, "status": "running", "metrics": metrics,
                  "items": [item for item in previous.get("items", []) if item.get("status") != "error"],
                  "pages": previous.get("pages", {}), "searches": previous.get("searches", [])}
        reports = [row for row in reports if row["company"] != company] + [report]
        def save(item):
            report["items"] = [row for row in report["items"] if row["metric"] != item["metric"]] + [item]
            emit("metric_saved", f"{company}：{item['metric']}已独立保存", item)
            emit("checkpoint", "逐项保存研究进度", {"reports": reports})
        try:
            if not report["pages"]:
                report["pages"], report["searches"] = collector(company, metrics, emit)
                emit("checkpoint", "保存本轮原文；恢复时不重复抓取", {"reports": reports})
            saved = {item["metric"] for item in report["items"]}
            for metric in metrics:
                if metric in saved:
                    continue
                possible = any(w._evidence_mentions_metric(metric, str(page.get("text") or "")) or (
                    metric == "云收入" and re.search(r"sales|revenue|收入", str(page.get("text") or ""), re.I))
                    for page in report["pages"].values() if page.get("opened") and page.get("official"))
                if not possible:
                    save({"company": company, "metric": metric, "status": "missing", "value": "",
                          "reason": "本轮成功读取的官方原文中未定位到该指标；记录缺口，不调用模型补写或触发回抓"})
                    continue
                try:
                    harness.extract(company, metric, report["pages"], save)
                except Exception as exc:
                    # A later network/length failure cannot discard earlier accepted records.
                    if metric not in {item["metric"] for item in report["items"]}:
                        save({"company": company, "metric": metric, "status": "error", "value": "",
                              "reason": compact(exc)[:500]})
            report["status"] = "partial" if any(item["status"] == "error" for item in report["items"]) else "completed"
        except Exception as exc:
            report["status"] = "error"
            for metric in metrics:
                if metric not in {item["metric"] for item in report["items"]}:
                    save({"company": company, "metric": metric, "status": "error", "value": "", "reason": compact(exc)[:500]})
        report["completed_at"] = now()
        emit("company_complete", f"{company}研究结束", {"company": company, "status": report["status"], "items": report["items"]})
        emit("checkpoint", "保存研究进度", {"reports": reports})
    result = {**task, "status": "completed" if all(r["status"] == "completed" for r in reports) else "partial",
              "reports": reports, "completed_at": now()}
    emit("complete", f"{task['title']}提交结果", {"status": result["status"], "companies": len(reports)})
    return result


def merge_results(results: list[dict], run_id: str) -> list[dict]:
    from crawl import ALL_COMPANY_CURRENT_RESULT_TARGETS
    facts = []
    seen = set()
    for agent in results:
        for report in agent["reports"]:
            for item in report["items"]:
                if item.get("status") == "verified":
                    checked = validate_fact(item, report["company"], report["metrics"], report.get("pages", {}))
                    item.update(checked)
                key = (item["company"], item["metric"])
                if key in seen:
                    raise ValueError(f"研究结果重复提交：{key}")
                seen.add(key)
                accepted = item["status"] == "verified"
                value, unit = item.get("value", ""), item.get("unit", "")
                rendered_value = value if not unit or all(part in value for part in unit.split()) else f"{value} {unit}".strip()
                row = ALL_COMPANY_CURRENT_RESULT_TARGETS[item["company"]][0]
                facts.append({
                    "id": hashlib.sha256(f"{run_id}:{key}".encode()).hexdigest()[:24],
                    "company": item["company"], "metric": item["metric"],
                    "value": rendered_value if accepted else "",
                    "period": item.get("period", ""), "unit": item.get("unit", ""),
                    "basis": "\n".join(filter(None, [item.get("quote", ""), item.get("context_quote", "")])), "status": "ok" if accepted else "unavailable",
                    "decision": "accepted" if accepted else "review", "row_ref": f"row_{row}",
                    "sources": [item["source_url"]] if item.get("source_url") else [],
                    "source_tier": "official" if accepted else "unknown", "source_score": 1.0 if accepted else 0,
                    "entity_supported": accepted, "metric_supported": accepted, "value_supported": accepted,
                    "confidence": .9 if accepted else 0, "quality_score": .9 if accepted else 0,
                    "evidence_hash": item.get("evidence_hash", ""), "reasons": [item.get("reason", "")],
                    "entity_basis": item.get("entity_quote", ""),
                    "research_agent_id": agent["key"], "research_status": item["status"],
                })
    return facts


def run_research(*, run_id: str, output_dir: Path, resume: bool = False,
                 assignments: list[dict] | None = None, model_factory: Callable | None = None,
                 collector: Callable = collect_sources) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "research.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("相同研究批次正在执行，拒绝重复启动") from exc
        return _run_research_unlocked(run_id=run_id, output_dir=output_dir, resume=resume,
            assignments=assignments, model_factory=model_factory, collector=collector)


def _run_research_unlocked(*, run_id: str, output_dir: Path, resume: bool = False,
                 assignments: list[dict] | None = None, model_factory: Callable | None = None,
                 collector: Callable = collect_sources) -> dict:
    # Dataclass tuples serialize to JSON arrays; compare canonical wire values
    # so an unchanged plan can actually resume after a process restart.
    plan = json.loads(json.dumps(research_plan() if assignments is None else assignments, ensure_ascii=False))
    if not 1 <= len(plan) <= 6 or len({task["key"] for task in plan}) != len(plan):
        raise ValueError("必须配置一至六个不同的研究Agent")
    companies = [company for task in plan for company in task["companies"]]
    if len(companies) != len(set(companies)):
        raise ValueError("公司任务不能重复分配")
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = now()
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if not resume or previous.get("run_id") != run_id or previous.get("plan") != plan:
            raise ValueError("已有研究记录；只能显式恢复相同运行编号和任务分配")
        if previous.get("status") == "completed":
            return previous
        started_at = previous["started_at"]
    lock = threading.Lock()
    trace_path = output_dir / "trace.jsonl"
    def emit_for(task):
        def emit(phase, message, data):
            if phase == "checkpoint":
                atomic_write_json(output_dir / f"{task['key']}.json", {**task, "status": "running", **data})
                return
            event = {"ts": now(), "run_id": run_id, "agent_id": task["key"], "node": task["title"],
                     "phase": phase, "message": message, "data": data}
            with lock, trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            print("RESEARCH_EVENT=" + json.dumps({k: v for k, v in event.items() if k != "data"}, ensure_ascii=False), flush=True)
        return emit
    manifest = {"architecture": ARCHITECTURE_VERSION, "run_id": run_id, "started_at": started_at,
                "harness": {"name": "deepagents", "version": "0.7.13", "atomic_metric_submission": True},
                "status": "running", "plan": plan, "agent_count": len(plan), "company_count": len(companies)}
    atomic_write_json(output_dir / "manifest.json", manifest)
    results = []
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:
        futures = {}
        for task in plan:
            path = output_dir / f"{task['key']}.json"
            checkpoint = json.loads(path.read_text()) if resume and path.exists() else None
            future = pool.submit(run_assignment, task, emit_for(task), checkpoint, model_factory, collector)
            futures[future] = task
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                from . import workflow as w
                reports = []
                for company in task["companies"]:
                    metrics = w._company_expected_metrics(company, [])
                    reports.append({"company": company, "status": "error", "metrics": metrics, "items": [
                        {"company": company, "metric": metric, "status": "error", "value": "", "reason": compact(exc)[:500]}
                        for metric in metrics]})
                result = {**task, "status": "error", "reports": reports, "error": compact(exc)[:500]}
            atomic_write_json(output_dir / f"{task['key']}.json", result)
            results.append(result)
    results.sort(key=lambda result: [task["key"] for task in plan].index(result["key"]))
    facts = merge_results(results, run_id)
    for result in results:
        atomic_write_json(output_dir / f"{result['key']}.json", result)
    accepted = [fact for fact in facts if fact["decision"] == "accepted"]
    atomic_write_jsonl(output_dir / "candidate_facts.jsonl", facts)
    atomic_write_jsonl(output_dir / "verified_facts.jsonl", accepted)
    summary = {**manifest, "completed_at": now(), "status": "completed" if all(r["status"] == "completed" for r in results) else "partial",
               "tasks": len(facts), "accepted": len(accepted), "review": len(facts) - len(accepted),
               "agents": [{k: v for k, v in result.items() if k != "reports"} for result in results],
               "processed_companies": sum(len(r["reports"]) for r in results),
               "completed_companies": sum(report["status"] == "completed" for r in results for report in r["reports"]),
               "metric_status_counts": dict(Counter(fact["research_status"] for fact in facts)),
               "business_status": "updates_available" if accepted else "no_verified_updates",
               "recrawl_performed": False}
    atomic_write_json(output_dir / "manifest.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="六Agent单向研究，独立输出本轮事实和详细记录")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id or "research_" + datetime.now(HKT).strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    result = run_research(run_id=run_id, output_dir=args.output_dir, resume=args.resume)
    print("RESEARCH_SUMMARY=" + json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
