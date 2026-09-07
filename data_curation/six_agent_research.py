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
TERMINAL = {"verified", "missing", "conflict", "not_applicable", "error", "no_update"}


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
        elif re.search(r"(?:surpassed|exceeded|over|more than|less than|approximately|about|超过|超過|约|約|逾|至少|不足)\s*$", quote[:quote.find(item["value"])], re.I):
            errors.append("原文含超过、约等限定词，value须保留该限定词，不能写成精确值")
        # A report period is often a table/header passage, separate from the metric.
        # Keep the model-selected literal period and attach its actual page excerpt;
        # never invent a year from the URL or turn a relative phrase into a date.
        if item["period"] and item["period"].casefold() not in grounded.casefold():
            offset = body.casefold().find(item["period"].casefold())
            if offset >= 0:
                item["period_quote"] = body[max(0, offset - 100):offset + len(item["period"]) + 100]
                grounded += " " + item["period_quote"]
        if not item["period"] or item["period"].casefold() not in grounded.casefold():
            errors.append("缺少与数据相符的原文期间")
        if w._company_agent_metric_requires_direct_value(item["metric"]) and (
            not item["unit"] or not all(part.casefold() in grounded.casefold() for part in re.sub(r"[()（）]", " ", item["unit"]).split())
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
        has_currency = bool(re.search(r"[$€£¥￥]|(?<![A-Za-z])(?:HKD|USD|RMB|CNY|AED|SAR|SGD|AUD|JPY|KRW|EUR|GBP|INR|CAD)(?![A-Za-z])|\byen\b|\brupees?\b|\beuros?\b|\bwon\b|\b(?:US|U\.S\.|Hong Kong|Singapore|Australian|Canadian) dollars?\b|人民币|人民幣|港币|港幣|日元|韩元|韓圓|美元|新加坡元", rendered, re.I))
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


def disclosure_recency(row: dict, year: int) -> int:
    """Rank discovery metadata only; never infer a fact's reporting period from a URL."""
    text = str(row.get("title") or row.get("discovery_title") or "") + " " + str(row.get("url") or "")
    years = [int(y) for y in re.findall(r"20\d{2}", text) if int(y) <= year]
    current = max(years, default=year - 1)
    dates = re.findall(r"(20\d{2})[/_-](0?[1-9]|1[0-2])[/_-](0?[1-9]|[12]\d|3[01])", text)
    if dates:
        valid = [int(y) * 10000 + int(m) * 100 + int(d) for y,m,d in dates if int(y) <= year]
        if valid:
            return max(valid)
    quarter = re.search(r"[Qq]([1-4])", text)
    month = int(quarter[1]) * 3 if quarter else 12 if re.search(r"annual|full.year|全年|年度", text, re.I) else 6 if re.search(r"interim|half|中期", text, re.I) else 0
    return current * 10000 + month * 100


def collect_sources(company: str, metrics: list[str], emit: Callable, baseline: dict | None = None) -> tuple[dict, list[dict]]:
    from . import workflow as w
    from .schemas import CandidateFact
    profile = w._company_research_profile(company)
    year = datetime.now(HKT).year
    searches, ranked = [], {}
    search_subject = {"Microsoft Azure": "Microsoft", "AWS": "Amazon AWS", "Google Cloud": "Alphabet Google Cloud",
                      "Alibaba Cloud": "Alibaba", "Tencent Cloud": "Tencent", "Oracle Cloud": "Oracle"}.get(company, company)
    # Find the latest disclosure first. Old stored values never enter a search query.
    queries = [("最新披露", f'"{search_subject}" {year} latest financial results earnings')]
    # Anchor discovery to governed investor sources, avoiding product/help pages.
    queries += [("官方最新业绩", f'site:{host} {search_subject} {year} financial results earnings')
                for host in profile["official_hosts"][:2]]
    queries += [(metric, f'"{search_subject}" {year} {" ".join(w._metric_evidence_terms(metric)[:2]) or metric} results') for metric in metrics]
    for metric, query in queries:
        results, provider = w._public_web_search(query, limit=5, timeout=12.0)
        record = {"company": company, "metric": metric, "query": query, "provider": provider, "results": results}
        searches.append(record)
        emit("search", f"{company}：查找最新披露 · {metric}", record)
        for result in results:
            url = str(result.get("url") or "")
            if w._host_matches_governed_official(url, profile["official_hosts"]):
                ranked.setdefault(url, result)
    def recency(row):
        text = str(row.get("title", "")) + " " + str(row.get("url", "")) + " " + str(row.get("snippet", ""))
        years = [int(value) for value in re.findall(r"20\d{2}", text) if int(value) <= year]
        financial = int(bool(re.search(r"result|earning|interim|业绩|業績|financial", text, re.I)))
        irrelevant = bool(re.search(r"learn\.microsoft\.com|developer\.microsoft\.com|/training/|/documentation/|/pricing/|/products/|/resources/cloud-computing", str(row.get("url", "")), re.I))
        return (not irrelevant, disclosure_recency(row, year), financial)
    # Reserve room for official IR entries and the reports linked from them.
    initial = sorted(ranked.values(), key=recency, reverse=True)[:8]
    initial += [{"url": url, "title": "官方最新公告入口"} for url in profile["seed_urls"][:4]]
    pages, discovered = {}, {}
    def read(row):
        url = row["url"]
        if url in pages:
            return
        page = w._read_source_page(url, timeout=15.0)
        page = {**page, "discovery_title": row.get("title", ""), "official": w._host_matches_governed_official(
            str(page.get("final_url") or url), profile["official_hosts"])}
        pages[url] = page
        emit("read", f"{company}：读取最新披露原文", {"company": company, **{k: v for k, v in page.items() if k != "text"}})
        if page.get("opened") and page.get("official"):
            for child in page.get("disclosure_links", []):
                if child.get("url") not in pages and w._host_matches_governed_official(child.get("url", ""), profile["official_hosts"]):
                    discovered.setdefault(child["url"], child)
    for row in initial:
        read(row)
    for row in sorted(discovered.values(), key=recency, reverse=True)[:6]:
        read(row)
    return pages, searches


NO_METRIC_EVIDENCE = "本轮读取的披露中未找到该指标的新数据；不代表库内缺失或已有值错误，保留原库。"


def page_mentions_metric(metric: str, pages: dict) -> bool:
    """Screen the entire opened text; navigation can precede the disclosure."""
    from . import workflow as w
    terms = w._metric_evidence_terms(metric)
    if metric == "云收入":
        terms = [*terms, "sales", "revenue", "收入"]
    return any(
        any(w._metric_term_position(re.sub(r"\s+", " ", str(page.get("text") or "")), term) >= 0 for term in terms)
        for page in pages.values() if page.get("opened") and page.get("official")
    )


def run_assignment(task: dict, emit: Callable, checkpoint: dict | None = None,
                   model_factory: Callable | None = None, collector: Callable = collect_sources, baseline: dict | None = None) -> dict:
    from . import workflow as w
    from .research_harness import ResearchHarness
    from .research_freshness import compare_candidate
    from .research_plan import frontend_metric_plan
    ui_metrics = frontend_metric_plan() if baseline is not None else {}
    factory = model_factory or (lambda: w._build_supervisor_model(max_tokens=4096, max_retries=0))
    harness = ResearchHarness(task, factory(), emit, validate_fact)
    reports = list((checkpoint or {}).get("reports") or [])
    for report in reports:
        retry = [item for item in report.get("items", [])
                 if item.get("status") == "missing" and item.get("reason") == NO_METRIC_EVIDENCE
                 and page_mentions_metric(item["metric"], report.get("pages", {}))]
        if retry:
            report["items"] = [item for item in report["items"] if item not in retry]
            report["status"] = "running"
            emit("screening_recovered", "从已保存完整原文恢复被截断预筛选遗漏的指标", {
                "company": report["company"], "metrics": [item["metric"] for item in retry]})
    completed = {report["company"] for report in reports if report.get("status") == "completed"}
    emit("start", task["purpose"], {"companies": task["companies"]})
    for company in task["companies"]:
        if company in completed:
            continue
        previous = next((report for report in reports if report["company"] == company), {})
        # Resume keeps the saved contract; new incremental tasks follow today's UI.
        metrics = previous.get("metrics") or list(dict.fromkeys([
            *w._company_expected_metrics(company, []),
            *ui_metrics.get(w._company_agent_group(company), []),
        ]))
        company_baseline = (baseline or {}).get(company, {})
        report = {"company": company, "status": "running", "metrics": metrics, "baseline": company_baseline, "incremental": baseline is not None,
                  "items": [item for item in previous.get("items", []) if item.get("status") != "error"],
                  "pages": previous.get("pages", {}), "searches": previous.get("searches", [])}
        reports = [row for row in reports if row["company"] != company] + [report]
        def save(item):
            if baseline is not None:
                item = compare_candidate(item, company_baseline)
                item.setdefault("baseline", company_baseline.get(item.get("metric"), []))
            report["items"] = [row for row in report["items"] if row["metric"] != item["metric"]] + [item]
            emit("metric_saved", f"{company}：{item['metric']}已独立保存", item)
            emit("checkpoint", "逐项保存研究进度", {"reports": reports})
        try:
            if not report["pages"]:
                report["pages"], report["searches"] = (collector(company, metrics, emit, company_baseline) if collector is collect_sources else collector(company, metrics, emit))
                emit("checkpoint", "保存本轮原文；恢复时不重复抓取", {"reports": reports})
            if baseline is not None and not any(page.get("opened") and page.get("official") for page in report["pages"].values()):
                raise RuntimeError("本轮官方披露页面读取全部失败，不能判断是否有更新；保留原库并记录执行失败")
            saved = {item["metric"] for item in report["items"]}
            for metric in metrics:
                if metric in saved:
                    continue
                possible = page_mentions_metric(metric, report["pages"])
                if not possible:
                    save({"company": company, "metric": metric, "status": "missing", "value": "",
                          "reason": NO_METRIC_EVIDENCE})
                    continue
                try:
                    harness.extract(company, metric, report["pages"], save, baseline=company_baseline if baseline is not None else None)
                except Exception as exc:
                    # A later network/length failure cannot discard earlier accepted records.
                    if metric not in {item["metric"] for item in report["items"]}:
                        save({"company": company, "metric": metric, "status": "error", "value": "",
                              "reason": compact(exc)[:500]})
            report["status"] = "partial" if any(item["status"] in {"error", "conflict"} for item in report["items"]) else "completed"
        except Exception as exc:
            report["status"] = "error"
            for metric in metrics:
                if metric not in {item["metric"] for item in report["items"]}:
                    save({"company": company, "metric": metric, "status": "error", "value": "", "reason": compact(exc)[:500]})
        report["completed_at"] = now()
        emit("company_complete", f"{company}研究结束", {"company": company, "status": report["status"], "items": report["items"]})
        emit("checkpoint", "保存研究进度", {"reports": reports})
    result = {**task, "incremental": baseline is not None, "status": "completed" if all(r["status"] == "completed" for r in reports) else "partial",
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
                    "basis": "\n".join(filter(None, [item.get("quote", ""), item.get("context_quote", ""), item.get("period_quote", "")])), "status": "ok" if accepted else "unavailable",
                    "decision": "accepted" if accepted else "unchanged" if item["status"] == "no_update" and report.get("incremental") else "review", "row_ref": f"row_{row}",
                    "sources": [item["source_url"]] if item.get("source_url") else [],
                    "source_tier": "official" if accepted else "unknown", "source_score": 1.0 if accepted else 0,
                    "entity_supported": accepted, "metric_supported": accepted, "value_supported": accepted,
                    "confidence": .9 if accepted else 0, "quality_score": .9 if accepted else 0,
                    "evidence_hash": item.get("evidence_hash", ""), "reasons": [item.get("reason", "")],
                    "entity_basis": item.get("entity_quote", ""),
                    "research_agent_id": agent["key"], "research_status": item["status"],
                    "freshness": item.get("freshness", ""), "baseline": item.get("baseline", []),
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
    from .research_freshness import load_baseline, POLICY
    baseline_path = output_dir / "baseline.json"
    if resume and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())
    else:
        baseline = load_baseline(output_dir.parent.parent.parent)
        atomic_write_json(baseline_path, baseline)
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
                "status": "running", "research_policy": POLICY, "plan": plan, "agent_count": len(plan), "company_count": len(companies)}
    atomic_write_json(output_dir / "manifest.json", manifest)
    results = []
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:
        futures = {}
        for task in plan:
            path = output_dir / f"{task['key']}.json"
            checkpoint = json.loads(path.read_text()) if resume and path.exists() else None
            future = pool.submit(run_assignment, task, emit_for(task), checkpoint, model_factory, collector, baseline["companies"])
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
               "tasks": len(facts), "accepted": len(accepted), "review": sum(fact["decision"] == "review" for fact in facts),
               "unchanged": sum(fact["decision"] == "unchanged" for fact in facts),
               "agents": [{k: v for k, v in result.items() if k != "reports"} for result in results],
               "processed_companies": sum(len(r["reports"]) for r in results),
               "completed_companies": sum(report["status"] == "completed" for r in results for report in r["reports"]),
               "metric_status_counts": dict(Counter(fact["research_status"] for fact in facts)),
               "business_status": "updates_available" if accepted else "needs_review" if any(fact["decision"] == "review" for fact in facts) else "no_new_disclosures",
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
