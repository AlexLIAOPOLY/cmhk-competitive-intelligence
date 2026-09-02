from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import news_discovery_digest
from cmhk.crawl.run_registry import (
    append_crawl_run_event,
    finalize_operational_crawl_run,
    start_crawl_run,
)
from executive_intelligence_pipeline import NEWS_ENTITY_SOURCES, NEWS_METRIC_RE
from cmhk.integrations.four_database_crawl_sheet import append_rows, discovery_rows


ROOT = Path(__file__).resolve().parent
HKT = ZoneInfo("Asia/Hong_Kong")
OUTPUT = ROOT / "agent_knowledge" / "executive_intelligence_refresh" / "source_discovery_latest.json"
TASK_KIND = "four-database-source-discovery"
DOMAIN_LABELS = {
    "local": "本地运营商库",
    "international": "国际运营商库",
    "mainland": "内地运营商库",
    "cloud": "云厂商库",
}

SEARCH_METRIC_TERMS = (
    "earnings", "results", "revenue", "profit", "EBITDA", "ARPU",
    "subscribers", "customers", "capex", '"cloud revenue"',
    "财报", "业绩", "营收", "收入", "利润", "用户数", "客户数", "订户",
    "资本开支", "云收入", "云业务",
)
DISCLOSURE_SEARCH_GROUPS = {
    "financial_results": (
        "earnings", "results", '"financial results"', '"quarterly results"',
        '"interim results"', '"earnings release"', '"annual report"',
        "财报", "业绩", "中期业绩", "季度业绩", "年度业绩", "公告",
    ),
    "operating_metrics": (
        "revenue", "profit", "EBITDA", "ARPU", "subscribers", "customers",
        "capex", "营收", "收入", "利润", "用户数", "客户数", "订户", "资本开支",
    ),
    "cloud_metrics": (
        '"cloud revenue"', '"cloud business"', '"cloud operating income"',
        '"cloud segment"', "Azure", "AWS", "OCI", "云收入", "云业务", "云计算",
    ),
}
DISCOVERY_LOOKBACK_DAYS = 7
NON_DISCLOSURE_LEAD_RE = re.compile(
    r"price\s+to\s+(?:earnings|sales)|enterprise\s+value\s+to\s+ebitda|"
    r"p/e\s+ratio|ev/ebitda|valuation\s+(?:ratio|multiple)",
    re.I,
)


def _build_search_plans() -> list[dict[str, Any]]:
    """Build entity × disclosure-family queries for the real 01:00 providers."""
    plans: list[dict[str, Any]] = []
    for domain, entity, aliases, _official_urls in NEWS_ENTITY_SOURCES:
        subject = " OR ".join(f'"{alias}"' for alias in aliases[:3])
        for disclosure_type, terms in DISCLOSURE_SEARCH_GROUPS.items():
            metric_clause = " OR ".join(terms)
            plans.append(
                {
                    "module": f"四库资料/{domain}",
                    "domain": domain,
                    "entity": entity,
                    "disclosure_type": disclosure_type,
                    "query": f"({subject}) ({metric_clause})",
                    "keywords": [*aliases, *terms],
                    "lookback_days": DISCOVERY_LOOKBACK_DAYS,
                    "search_origin": "four_database_0100_agent",
                    "semantic_relevance": True,
                }
            )
    return plans


def _previous_day_news_references(reference: datetime) -> tuple[list[str], list[dict[str, Any]], int]:
    target_date = (reference - timedelta(days=1)).date().isoformat()
    completed_runs: list[tuple[Path, dict[str, Any]]] = []
    items: list[dict[str, Any]] = []
    runs_dir = ROOT / "strategy_briefing" / "runs"
    for path in sorted(runs_dir.glob("*.json")) if runs_dir.exists() else []:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scanned_at = str(payload.get("scanned_at") or payload.get("completed_at") or "")
        if not scanned_at.startswith(target_date) or str(payload.get("status") or "") != "completed":
            continue
        completed_runs.append((path, payload))
    # The 01:00 job consumes only the two completed scheduled batches from the
    # previous business day. Older retries/extra runs must not inflate B1.
    authoritative_runs = sorted(
        completed_runs,
        key=lambda pair: str(pair[1].get("scanned_at") or pair[1].get("completed_at") or pair[0].name),
    )[-2:]
    for path, payload in authoritative_runs:
        for item in [*((payload.get("news_discovery") or {}).get("items") or []), *(payload.get("candidates") or [])]:
            if isinstance(item, dict):
                items.append({**item, "reference_origin": "previous_day_strategic_news", "reference_run": path.name})
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("url") or item.get("source_url") or item.get("title") or "").strip()
        if key:
            deduped[key] = item
    unique_references = list(deduped.values())
    return [path.name for path, _payload in authoritative_runs], unique_references[:300], len(unique_references)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _build_signals(
    plans: list[dict[str, Any]],
    items: list[dict[str, Any]],
    previous_references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create entity-scoped handoffs and reject valuation-page metric noise."""
    plans_by_query = {
        str(plan.get("fallback_query") or plan.get("query") or "").strip(): plan
        for plan in plans
    }
    sources_by_key = {
        (domain, entity): (aliases, official_urls)
        for domain, entity, aliases, official_urls in NEWS_ENTITY_SOURCES
    }
    signals: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in [*items, *previous_references]:
        text = f"{item.get('title', '')} {item.get('summary', '')} {item.get('snippet', '')}"
        if not NEWS_METRIC_RE.search(text) or NON_DISCLOSURE_LEAD_RE.search(text):
            continue
        query_plan = plans_by_query.get(str(item.get("query") or "").strip())
        explicit_domain = str(item.get("domain") or "").strip()
        explicit_entity = str(item.get("entity") or "").strip()
        scoped_keys: list[tuple[str, str]]
        if query_plan:
            scoped_keys = [(str(query_plan["domain"]), str(query_plan["entity"]))]
        elif explicit_domain and explicit_entity and (explicit_domain, explicit_entity) in sources_by_key:
            scoped_keys = [(explicit_domain, explicit_entity)]
        else:
            scoped_keys = list(sources_by_key)
        news_url = str(item.get("url") or item.get("source_url") or "").strip()
        for domain, entity in scoped_keys:
            aliases, official_urls = sources_by_key[(domain, entity)]
            if not any(alias.casefold() in text.casefold() for alias in aliases):
                continue
            key = (domain, entity, news_url or str(item.get("title") or ""))
            if key in seen:
                continue
            seen.add(key)
            signals.append({
                "domain": domain,
                "entity": entity,
                "title": str(item.get("title") or "").strip(),
                "news_url": news_url,
                "published_at": str(item.get("published_at") or item.get("source_date") or ""),
                "disclosure_type": str(
                    item.get("disclosure_type")
                    or (query_plan or {}).get("disclosure_type")
                    or ""
                ),
                "official_followup_urls": list(official_urls),
                "disposition": "official_followup_required",
                "reference_origin": str(item.get("reference_origin") or "0100_search_engine"),
            })
    return signals


def _search_audit(
    plans: list[dict[str, Any]],
    items: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a readable, per-database audit without upgrading search leads to facts."""
    results_by_query: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        results_by_query.setdefault(str(item.get("query") or "").strip(), []).append(item)

    query_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    domains: dict[str, dict[str, Any]] = {}
    for domain, label in DOMAIN_LABELS.items():
        domain_plans = [plan for plan in plans if plan.get("domain") == domain]
        domain_items = [item for item in items if item.get("module") == f"四库资料/{domain}"]
        domain_signals = [signal for signal in signals if signal.get("domain") == domain]
        domains[domain] = {
            "label": label,
            "query_count": len(domain_plans),
            "result_count": len(domain_items),
            "signal_count": len(domain_signals),
            "zero_result_query_count": sum(
                not results_by_query.get(str(plan.get("fallback_query") or plan.get("query") or "").strip())
                for plan in domain_plans
            ),
            "status": "有候选，等待03:00追官方原文" if domain_signals else "本轮未形成可交接线索",
        }
        for plan in domain_plans:
            query = str(plan.get("fallback_query") or plan.get("query") or "").strip()
            query_rows.append({
                "domain": domain,
                "domain_label": label,
                "entity": str(plan.get("entity") or "").strip(),
                "disclosure_type": str(plan.get("disclosure_type") or "").strip(),
                "query": query,
                "lookback_days": int(plan.get("lookback_days") or 0),
                "result_count": len(results_by_query.get(query, [])),
                "status": (
                    "searched_with_results"
                    if results_by_query.get(query)
                    else "searched_zero_result"
                ),
            })
        for item in domain_items:
            item_url = str(item.get("url") or item.get("source_url") or "").strip()
            matched_signal = next((
                signal for signal in domain_signals
                if str(signal.get("news_url") or "").strip() == item_url
            ), None)
            result_rows.append({
                "domain": domain,
                "domain_label": label,
                "entity": next((
                    str(plan.get("entity") or "")
                    for plan in domain_plans
                    if str(plan.get("fallback_query") or plan.get("query") or "").strip()
                    == str(item.get("query") or "").strip()
                ), ""),
                "disclosure_type": str(item.get("disclosure_type") or ""),
                "title": str(item.get("title") or "").strip(),
                "source": str(item.get("source") or "公开新闻来源").strip(),
                "published_at": str(item.get("published_at") or "").strip(),
                "url": item_url,
                "provider": str(item.get("search_provider") or "").strip(),
                "handoff": bool(matched_signal),
                "disposition": "已形成线索，交接03:00追官方原文" if matched_signal else "未形成交接线索，不直接入库",
                "reason": "标题或摘要同时命中四库主体和财务／用户／资本开支字段" if matched_signal else "未同时通过四库主体与指标字段筛选",
            })
    return {"domains": domains, "queries": query_rows, "results": result_rows}


def _append_readable_audit_events(
    log_path: Path,
    payload: dict[str, Any],
) -> None:
    audit = payload.get("search_audit") or {}
    append_crawl_run_event(log_path, {
        "type": "source_discovery_scope",
        "generated_at_hkt": payload.get("generated_at_hkt"),
        "window_hours": 24,
        "query_count": payload.get("query_count"),
        "search_result_count": payload.get("search_result_count"),
        "previous_day_reference_count": payload.get("previous_day_reference_count"),
        "signal_count": payload.get("signal_count"),
        "policy": "搜索结果只作线索；03:00追官方原文并通过字段门禁后才可入库",
    })
    for reference in payload.get("previous_day_references") or []:
        append_crawl_run_event(log_path, {
            "type": "source_discovery_previous_reference",
            "title": reference.get("title"),
            "source": reference.get("source"),
            "published_at": reference.get("published_at") or reference.get("source_date"),
            "url": reference.get("url") or reference.get("source_url"),
            "reference_run": reference.get("reference_run"),
            "disposition": "作为补充线索参与四库主体与指标字段筛选",
        })
    for domain in DOMAIN_LABELS:
        summary = (audit.get("domains") or {}).get(domain) or {}
        append_crawl_run_event(log_path, {"type": "source_discovery_domain", "domain": domain, **summary})
        for query in audit.get("queries") or []:
            if query.get("domain") == domain:
                append_crawl_run_event(log_path, {"type": "source_discovery_query", **query})
        for result in audit.get("results") or []:
            if result.get("domain") == domain:
                append_crawl_run_event(log_path, {"type": "source_discovery_result", **result})
        for signal in payload.get("signals") or []:
            if signal.get("domain") == domain:
                append_crawl_run_event(log_path, {"type": "source_discovery_handoff", **signal})
    for error in payload.get("errors") or []:
        append_crawl_run_event(log_path, {"type": "source_discovery_error", "error": str(error)})


def run_discovery(now: datetime | None = None) -> dict[str, Any]:
    reference = (now or datetime.now(HKT)).astimezone(HKT)
    started = time.monotonic()
    run = start_crawl_run(
        trigger="每日01:00四库资料搜索",
        scope=f"四库更新资料 {reference.date().isoformat()}",
        task_kind=TASK_KIND,
        phase="搜索引擎检索",
        progress_detail="按四库主体和指标字段检索最近24小时资料，结果只作为03:00官方原文追踪线索。",
    )
    run_id = str(run["crawl_run_id"])
    log_path = Path(str(run["stream_log_path"]))
    try:
        plans = _build_search_plans()
        items, errors, stats = news_discovery_digest._execute_search_plans(
            plans,
            start_at=reference - timedelta(days=DISCOVERY_LOOKBACK_DAYS),
            end_at=reference,
        )
        previous_runs, previous_references, previous_reference_unique_total = _previous_day_news_references(reference)
        signals = _build_signals(plans, items, previous_references)
        payload = {
            "schema_version": 2,
            "task_kind": TASK_KIND,
            "run_id": run_id,
            "generated_at_hkt": reference.isoformat(timespec="seconds"),
            "handoff_for_date": reference.date().isoformat(),
            "query_count": int(stats.get("query_count") or len(plans)),
            "search_result_count": len(items),
            "previous_day_news_runs": previous_runs,
            "previous_day_reference_count": len(previous_references),
            "previous_day_reference_unique_total": previous_reference_unique_total,
            "previous_day_reference_limit": 300,
            "previous_day_reference_truncated": previous_reference_unique_total > len(previous_references),
            "previous_day_references": previous_references,
            "signal_count": len(signals),
            "domains": {domain: sum(signal["domain"] == domain for signal in signals) for domain in ("local", "international", "mainland", "cloud")},
            "errors": errors,
            "policy": "search_results_are_leads_only; seven_day_window_handles_indexing_delay; 03:00_must_read_official_source_and_pass_field_gates",
            "signals": signals,
        }
        payload["search_audit"] = _search_audit(plans, items, signals)
        payload["coverage_matrix"] = list(payload["search_audit"].get("queries") or [])
        payload["coverage_complete"] = (
            len(payload["coverage_matrix"]) == len(plans) and not errors
        )
        _write_json(OUTPUT, payload)
        try:
            payload["feishu_detail_log"] = append_rows(discovery_rows(payload, plans=plans, search_items=items))
        except Exception as exc:
            payload["feishu_detail_log"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        _write_json(OUTPUT, payload)
        _append_readable_audit_events(log_path, payload)
        append_crawl_run_event(log_path, {"type": "feishu_detail_log", **payload["feishu_detail_log"]})
        log_ok = bool((payload.get("feishu_detail_log") or {}).get("readback_verified"))
        detail = f"01:00资料搜索完成：{payload['query_count']}个查询、{payload['search_result_count']}条搜索结果、前一日两次任务参考{payload['previous_day_reference_count']}条、{payload['signal_count']}条四库线索；已交接03:00官方来源复核。"
        if not log_ok:
            detail += f" 飞书四库爬虫明细日志写入或回读失败：{(payload.get('feishu_detail_log') or {}).get('error') or '未取得正向回读证据'}。"
        payload["ok"] = log_ok
        _write_json(OUTPUT, payload)
        finalize_operational_crawl_run(
            run_id, ok=log_ok, duration_ms=round((time.monotonic() - started) * 1000), progress_detail=detail,
            failure_stage="" if log_ok else "four_database_feishu_log", summary={**payload, "audit_path": str(OUTPUT)},
        )
        return {**payload, "audit_path": str(OUTPUT)}
    except Exception as exc:
        detail = f"01:00四库资料搜索失败：{type(exc).__name__}: {exc}"
        append_crawl_run_event(log_path, {"type": "done", "ok": False, "error": detail})
        finalize_operational_crawl_run(run_id, ok=False, duration_ms=round((time.monotonic() - started) * 1000), progress_detail=detail, failure_stage="four_database_source_discovery")
        return {"ok": False, "error": detail, "run_id": run_id}


if __name__ == "__main__":
    print(json.dumps(run_discovery(), ensure_ascii=False, indent=2))
