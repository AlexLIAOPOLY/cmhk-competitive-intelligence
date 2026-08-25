from __future__ import annotations

import json
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


def _previous_day_news_references(reference: datetime) -> tuple[list[str], list[dict[str, Any]]]:
    target_date = (reference - timedelta(days=1)).date().isoformat()
    run_names: list[str] = []
    items: list[dict[str, Any]] = []
    runs_dir = ROOT / "strategy_briefing" / "runs"
    for path in sorted(runs_dir.glob("*.json")) if runs_dir.exists() else []:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scanned_at = str(payload.get("scanned_at") or payload.get("completed_at") or "")
        if not scanned_at.startswith(target_date):
            continue
        run_names.append(path.name)
        for item in [*((payload.get("news_discovery") or {}).get("items") or []), *(payload.get("candidates") or [])]:
            if isinstance(item, dict):
                items.append({**item, "reference_origin": "previous_day_strategic_news", "reference_run": path.name})
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("url") or item.get("source_url") or item.get("title") or "").strip()
        if key:
            deduped[key] = item
    return run_names[-2:], list(deduped.values())[:300]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


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
        plans: list[dict[str, Any]] = []
        for domain, entity, aliases, _official_urls in NEWS_ENTITY_SOURCES:
            subject = " OR ".join(f'"{alias}"' for alias in aliases[:3])
            query = f"({subject}) (earnings OR results OR revenue OR profit OR subscribers OR ARPU OR capex OR 财报 OR 业绩 OR 营收 OR 用户数 OR 资本开支)"
            plans.append(
                {
                    "module": f"四库资料/{domain}",
                    "query": query,
                    "fallback_query": f'"{entity}" earnings revenue subscribers',
                    "keywords": list(aliases),
                    "lookback_days": 2,
                    "search_origin": "four_database_0100_agent",
                    "semantic_relevance": True,
                }
            )
        items, errors, stats = news_discovery_digest._execute_search_plans(
            plans,
            start_at=reference - timedelta(hours=24),
            end_at=reference,
        )
        previous_runs, previous_references = _previous_day_news_references(reference)
        signals: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in [*items, *previous_references]:
            text = f"{item.get('title', '')} {item.get('summary', '')} {item.get('snippet', '')}"
            if not NEWS_METRIC_RE.search(text):
                continue
            news_url = str(item.get("url") or item.get("source_url") or "").strip()
            for domain, entity, aliases, official_urls in NEWS_ENTITY_SOURCES:
                if not any(alias.casefold() in text.casefold() for alias in aliases):
                    continue
                key = (domain, entity, news_url or str(item.get("title") or ""))
                if key in seen:
                    continue
                seen.add(key)
                signals.append(
                    {
                        "domain": domain,
                        "entity": entity,
                        "title": str(item.get("title") or "").strip(),
                        "news_url": news_url,
                        "published_at": str(item.get("published_at") or item.get("source_date") or ""),
                        "official_followup_urls": list(official_urls),
                        "disposition": "official_followup_required",
                        "reference_origin": str(item.get("reference_origin") or "0100_search_engine"),
                    }
                )
        payload = {
            "schema_version": 1,
            "task_kind": TASK_KIND,
            "run_id": run_id,
            "generated_at_hkt": reference.isoformat(timespec="seconds"),
            "handoff_for_date": reference.date().isoformat(),
            "query_count": int(stats.get("query_count") or len(plans)),
            "search_result_count": len(items),
            "previous_day_news_runs": previous_runs,
            "previous_day_reference_count": len(previous_references),
            "previous_day_references": previous_references,
            "signal_count": len(signals),
            "domains": {domain: sum(signal["domain"] == domain for signal in signals) for domain in ("local", "international", "mainland", "cloud")},
            "errors": errors,
            "policy": "search_results_are_leads_only; 03:00_must_read_official_source_and_pass_field_gates",
            "signals": signals,
        }
        _write_json(OUTPUT, payload)
        try:
            payload["feishu_detail_log"] = append_rows(discovery_rows(payload, plans=plans, search_items=items))
        except Exception as exc:
            payload["feishu_detail_log"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        _write_json(OUTPUT, payload)
        append_crawl_run_event(log_path, {"type": "source_discovery", **{key: payload[key] for key in ("query_count", "search_result_count", "signal_count", "domains")}})
        append_crawl_run_event(log_path, {"type": "feishu_detail_log", **payload["feishu_detail_log"]})
        detail = f"01:00资料搜索完成：{payload['query_count']}个查询、{payload['search_result_count']}条搜索结果、前一日两次任务参考{payload['previous_day_reference_count']}条、{payload['signal_count']}条四库线索；已交接03:00官方来源复核。"
        finalize_operational_crawl_run(run_id, ok=True, duration_ms=round((time.monotonic() - started) * 1000), progress_detail=detail, summary={**payload, "audit_path": str(OUTPUT)})
        return {"ok": True, **payload, "audit_path": str(OUTPUT)}
    except Exception as exc:
        detail = f"01:00四库资料搜索失败：{type(exc).__name__}: {exc}"
        append_crawl_run_event(log_path, {"type": "done", "ok": False, "error": detail})
        finalize_operational_crawl_run(run_id, ok=False, duration_ms=round((time.monotonic() - started) * 1000), progress_detail=detail, failure_stage="four_database_source_discovery")
        return {"ok": False, "error": detail, "run_id": run_id}


if __name__ == "__main__":
    print(json.dumps(run_discovery(), ensure_ascii=False, indent=2))
