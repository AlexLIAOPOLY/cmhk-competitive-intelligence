from __future__ import annotations

import json
import operator
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from ai_config import load_ai_config
from company_metrics import (
    AI_CACHE_PATH,
    AI_CACHE_SCHEMA_VERSION,
    DIRTY_SOURCE_LABEL_TERMS,
    KNOWN_COMPANY_NAMES,
    QUALITATIVE_METRIC_RE,
    _direct_value,
    _passes_metric_gate,
)
from normalize_company_metrics_ai import (
    build_tasks,
    call_deepseek,
    clean_text,
    deterministic_extract_task,
    entity_supported_offline,
    fallback_clean_batch,
    load_cache,
)

from .schemas import CandidateFact, EvidenceTask, GapRecord, RecrawlTask, RunSummary
from .storage import DATA_DIR, RUNS_DIR, atomic_write_json, atomic_write_jsonl


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
GLOBAL_CRAWL_ARTIFACTS = [
    "sources.json",
    "write_payload.json",
    "coverage_report.tsv",
    "run_log.tsv",
    "run_log.json",
    "final_audit.md",
]
OFFICIAL_HOST_TERMS = (
    "hkexnews.hk",
    "hkex.com.hk",
    "gov.hk",
    "ofca.gov.hk",
    "pcpd.org.hk",
    "chinamobile",
    "chinatelecom",
    "chinaunicom",
    "hkt.com",
    "hthkh.com",
    "smartone",
    "hkbn.net",
    "hgc.com.hk",
    "i-cablecomm.com",
)
COMMERCIAL_HOST_TERMS = (
    "stockanalysis.com",
    "aastocks.com",
    "finance.sina",
    "financialreports.eu",
)
CORE_COMPANY_ROWS = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}
PRIMARY_PERFORMANCE_ROWS = {2, 5, 8, 11, 15, 17}
AUDIT_REASON_TEXTS = {
    "主体归属未通过",
    "指标语义未通过",
    "抽取结果不可用",
    "数值或事实依据不足",
    "未通过指标格式与单位门禁",
    "包含网页导航或无关文本",
    "定性指标为截断网页片段",
    "缺少可核验公开来源",
    "置信度低于80%",
    "在线模型不可用，离线结果不直接发布",
}


class CurationState(TypedDict, total=False):
    run_id: str
    started_at: str
    limit: int | None
    batch_size: int
    online_ai: bool
    allow_recrawl: bool
    dry_run: bool
    max_recrawl_rows: int
    max_recrawl_rounds: int
    recrawl_round: int
    recrawl_performed: bool
    executed_recrawl_rows: list[int]
    tasks: list[dict[str, Any]]
    existing_items: dict[str, dict[str, Any]]
    candidates: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    recrawl_tasks: list[dict[str, Any]]
    supervisor_decision: str
    supervisor_reason: str
    best_candidates: list[dict[str, Any]]
    best_accepted_count: int
    summary: dict[str, Any]
    node_events: Annotated[list[str], operator.add]
    agent_trace: Annotated[list[dict[str, Any]], operator.add]


def _event(node: str, text: str) -> str:
    line = f"[数据整理][{node}] {text}"
    print(line, flush=True)
    return line


def _compact(value: Any, limit: int = 700) -> Any:
    if isinstance(value, str):
        return clean_text(value, limit)
    if isinstance(value, list):
        return [_compact(item, limit) for item in value[:8]]
    if isinstance(value, dict):
        return {str(key): _compact(item, limit) for key, item in list(value.items())[:20]}
    return value


def _trace(
    state: CurationState,
    node: str,
    phase: str,
    message: str,
    *,
    event_type: str = "agent",
    input: Any | None = None,
    output: Any | None = None,
    tool: str = "",
    result: Any | None = None,
    status: str = "",
    decision: str = "",
    duration_ms: int | None = None,
) -> dict[str, Any]:
    event = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": state.get("run_id", ""),
        "node": node,
        "phase": phase,
        "event_type": event_type,
        "message": clean_text(message, 500),
    }
    if status:
        event["status"] = status
    if decision:
        event["decision"] = clean_text(decision, 500)
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    if input is not None:
        event["input"] = _compact(input)
    if output is not None:
        event["output"] = _compact(output)
    if tool:
        event["tool"] = tool
    if result is not None:
        event["result"] = _compact(result)
    print("AGENT_TRACE=" + json.dumps(event, ensure_ascii=False), flush=True)
    return event


def _trace_pair(
    state: CurationState,
    node: str,
    *,
    input: Any,
    output: Any,
    message: str,
) -> list[dict[str, Any]]:
    return [
        _trace(state, node, "observe", f"{node} 输入已读取。", input=input),
        _trace(state, node, "answer", message, output=output),
    ]


def _source_rank(urls: list[str]) -> tuple[float, str]:
    hosts = [urlparse(url).netloc.lower() for url in urls if url.startswith(("http://", "https://"))]
    if any(any(term in host for term in OFFICIAL_HOST_TERMS) for host in hosts):
        return 1.0, "official"
    if any(any(term in host for term in COMMERCIAL_HOST_TERMS) for host in hosts):
        return 0.62, "commercial"
    if hosts:
        return 0.72, "public"
    return 0.0, "missing"


def _result_status(row_ref: str) -> str:
    match = re.fullmatch(r"row_(\d+)", row_ref or "")
    if not match:
        return ""
    path = RESULTS_DIR / f"{row_ref}.json"
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("status") or "")
    except Exception:
        return ""


def _semantic_key_for_item(item: dict[str, Any]) -> str:
    return str(
        item.get("semantic_key")
        or f"{item.get('company', '')}|{item.get('metric', '')}|{item.get('row_ref', '')}"
    )


def _accepted_cache_items(items: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in items.values():
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        if str(item.get("metric") or "") in KNOWN_COMPANY_NAMES:
            continue
        if not _cache_item_metric_semantically_valid(item):
            continue
        if _is_truncated_qualitative_fragment(str(item.get("metric") or ""), str(item.get("value") or "")):
            continue
        key = _semantic_key_for_item(item)
        if not key.strip("|"):
            continue
        current = output.get(key)
        current_score = float(current.get("quality_score") or 0.0) if current else -1.0
        item_score = float(item.get("quality_score") or 0.0)
        if current is None or item_score >= current_score:
            output[key] = item
    return output


def _cache_item_metric_semantically_valid(item: dict[str, Any]) -> bool:
    metric = str(item.get("metric") or "")
    evidence = f"{item.get('value', '')}\n{item.get('basis', '')}"
    if metric == "5G-A":
        return bool(re.search(r"\b5G[\s-]?(?:A|Advanced)\b|\b5\.5G\b", evidence, re.IGNORECASE))
    if metric == "Open RAN":
        return bool(re.search(r"\bOpen[\s-]?RAN\b|\bO-RAN\b", evidence, re.IGNORECASE))
    return True


def _is_truncated_qualitative_fragment(metric: str, value: str) -> bool:
    if not QUALITATIVE_METRIC_RE.search(metric):
        return False
    return bool(
        re.search(r"\s\|\s|suggestions found|\b\d+/\d+\b|Search Close", value, re.IGNORECASE)
        or re.match(r"^[a-z]{2,}[,;:\s-]", value)
        or re.match(r"^[a-z]{2,}\s+[A-Z]", value)
    )


def _cache_item_from_fact(fact: CandidateFact) -> dict[str, Any]:
    return {
        "schemaVersion": AI_CACHE_SCHEMA_VERSION,
        "evidence_hash": fact.evidence_hash,
        "company": fact.company,
        "metric": fact.metric,
        "status": "ok" if fact.decision == "accepted" else "unavailable",
        "value": fact.value if fact.decision == "accepted" else "未提取到有效数据",
        "basis": fact.basis,
        "note": "；".join(fact.reasons) or fact.note,
        "entity_supported": fact.entity_supported,
        "metric_supported": fact.metric_supported,
        "value_supported": fact.value_supported,
        "confidence": fact.confidence,
        "quality_score": fact.quality_score,
        "decision": fact.decision,
        "source_tier": fact.source_tier,
        "row_ref": fact.row_ref,
        "semantic_key": f"{fact.company}|{fact.metric}|{fact.row_ref}",
    }


def _normalized_unit_from_context(text: str) -> str:
    unit_match = re.search(
        r"(?:单位(?:应)?为|单位(?:是|[:：]))\s*"
        r"(百万港元|百万\s*(?:HKD|HK\$)|亿港元|万港元|港元|亿元|万元|人民币|美元|"
        r"million\s+(?:HKD|HK\$|Hong Kong dollars?)|HKD\s+million|"
        r"billion\s+(?:HKD|HK\$|Hong Kong dollars?)|HKD\s+billion)",
        text,
        re.IGNORECASE,
    )
    if not unit_match:
        return ""
    unit = unit_match.group(1)
    replacements = (
        (r"百万\s*(?:HKD|HK\$)", "百万港元"),
        (r"million\s+(?:HKD|HK\$|Hong Kong dollars?)|HKD\s+million", "百万港元"),
        (r"billion\s+(?:HKD|HK\$|Hong Kong dollars?)|HKD\s+billion", "十亿港元"),
    )
    for pattern, replacement in replacements:
        if re.fullmatch(pattern, unit, re.IGNORECASE):
            return replacement
    return unit


def _recover_fact_value(fact: CandidateFact) -> str:
    current = clean_text(fact.value, 220)
    context = clean_text(f"{fact.basis}；{fact.note}", 900)
    # Prefer a positive, metric-specific value found in the basis. Models
    # sometimes first reject a distractor and then state the correct value in
    # the same sentence ("并非净利润；净利润为...").
    numeric_metric = bool(
        re.search(
            r"派息|股息|分派|资本开支|收入|收益|EBITDA|利润|用户|客户|ARPU|"
            r"宽频|家宽|套餐|资费|频谱|GDP|CPI|人口|投资",
            fact.metric,
            re.IGNORECASE,
        )
    )
    explicit_positive_value = bool(
        re.search(
            r"(?:为|达|达到|录得|增至|降至|was|were|at|reached|amounted to|reported)"
            r"[^。；]{0,24}(?:HK\$|US\$|RMB|人民币|港元|\$)?\s*[-+]?\d",
            context,
            re.IGNORECASE,
        )
    )
    if numeric_metric and explicit_positive_value:
        for source_text in (fact.basis, fact.note):
            recovered = _direct_value(fact.metric, source_text)
            if recovered and _passes_metric_gate(fact.metric, recovered):
                return clean_text(recovered, 220)
    if re.search(
        r"未提供|未给出|未提及|未包含|未披露|无(?:具体|相关|可用)?"
        r"(?:数据|数字|金额|内容|信息|指标|事实|描述)|仅列出|仅提及|无法确认|未能确认",
        context,
        re.IGNORECASE,
    ):
        return ""
    if QUALITATIVE_METRIC_RE.search(fact.metric) and (
        not fact.value_supported or fact.confidence < 0.8
    ):
        return ""
    if re.fullmatch(r"[-+]?\d[\d,]*(?:\.\d+)?", current):
        unit = _normalized_unit_from_context(context)
        if unit:
            enriched = f"{current}{unit}"
            if _passes_metric_gate(fact.metric, enriched):
                return enriched
    for source_text in (fact.basis, fact.note):
        recovered = _direct_value(fact.metric, source_text)
        if recovered and _passes_metric_gate(fact.metric, recovered):
            return clean_text(recovered, 220)
    return ""


def _recover_explicit_not_applicable(fact: CandidateFact) -> bool:
    context = f"{fact.value} {fact.basis} {fact.note}"
    if fact.metric == "市场反应" and fact.company in {"csl", "1O1O", "3HK"}:
        fact.value = "不适用（品牌非独立上市主体）"
        fact.status = "ok"
        fact.entity_supported = True
        fact.metric_supported = True
        fact.value_supported = True
        fact.confidence = max(fact.confidence, 0.95)
        fact.note = clean_text(f"{fact.note}；依据品牌上市口径确认不适用", 160).strip("；")
        return True
    if not re.search(r"非上市|not listed|private company", context, re.IGNORECASE):
        return False
    if re.search(r"派息|股息|分派|券商观点|市场反应", fact.metric, re.IGNORECASE):
        fact.value = "不适用（非上市主体）"
        fact.status = "ok"
        fact.entity_supported = True
        fact.metric_supported = True
        fact.value_supported = True
        fact.confidence = max(fact.confidence, 0.9)
        fact.note = clean_text(f"{fact.note}；依据主体上市状态确认不适用", 160).strip("；")
        return True
    return False


def ingest_evidence(state: CurationState) -> dict[str, Any]:
    tasks = [EvidenceTask.model_validate(item).model_dump() for item in build_tasks(limit=state.get("limit"))]
    cache = load_cache()
    items = cache.get("items", {}) if cache.get("schemaVersion") == AI_CACHE_SCHEMA_VERSION else {}
    current_ids = {task["id"] for task in tasks}
    current_hashes = {task["id"]: task.get("evidence_hash", "") for task in tasks}
    existing = {
        row_id: item
        for row_id, item in items.items()
        if (
            row_id in current_ids
            and item.get("schemaVersion") == AI_CACHE_SCHEMA_VERSION
            and item.get("evidence_hash")
            and item.get("evidence_hash") == current_hashes.get(row_id)
            and item.get("decision") in {"accepted", "review"}
            and "AI不可用" not in str(item.get("note") or "")
        )
    }
    return {
        "tasks": tasks,
        "existing_items": existing,
        "candidates": [],
        "gaps": [],
        "recrawl_tasks": [],
        "node_events": [_event("证据接收", f"读取 {len(tasks)} 条原始指标证据，复用 {len(existing)} 条缓存判断。")],
        "agent_trace": _trace_pair(
            state,
            "证据接收",
            input={"limit": state.get("limit"), "cache_schema": AI_CACHE_SCHEMA_VERSION},
            output={"tasks": len(tasks), "cache_reused": len(existing)},
            message=f"读取 {len(tasks)} 条原始指标证据，复用 {len(existing)} 条缓存判断。",
        ),
    }


def classify_sources(state: CurationState) -> dict[str, Any]:
    tasks = []
    tier_counts: dict[str, int] = {}
    for raw in state.get("tasks", []):
        task = EvidenceTask.model_validate(raw)
        score, tier = _source_rank(task.sources)
        task.source_score = score
        task.source_tier = tier
        tasks.append(task.model_dump())
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    counts = "、".join(f"{key} {value}" for key, value in sorted(tier_counts.items()))
    return {
        "tasks": tasks,
        "node_events": [_event("来源分类", f"完成来源分级：{counts or '无来源'}。")],
        "agent_trace": _trace_pair(
            state,
            "来源分类",
            input={"tasks": len(state.get("tasks", []))},
            output={"source_tiers": tier_counts},
            message=f"完成来源分级：{counts or '无来源'}。",
        ),
    }


def _candidate_from_cache(task: EvidenceTask, item: dict[str, Any]) -> CandidateFact:
    status = item.get("status") if item.get("status") in {"ok", "unavailable"} else "unavailable"
    entity_supported = bool(item.get("entity_supported"))
    metric_supported = bool(item.get("metric_supported"))
    value_supported = bool(item.get("value_supported"))
    value = clean_text(item.get("value"), 220)
    basis = clean_text(item.get("basis"), 600)
    note = clean_text(item.get("note"), 160)
    semantic_patterns = {
        "5G-A": (r"\b5G[\s-]?(?:A|Advanced)\b|\b5\.5G\b", "5G-A、5G Advanced或5.5G"),
        "Open RAN": (r"\bOpen[\s-]?RAN\b|\bO-RAN\b", "Open RAN或O-RAN"),
    }
    if task.metric in semantic_patterns:
        evidence = f"{task.raw_text}\n{value}\n{basis}"
        pattern, expected = semantic_patterns[task.metric]
        if not re.search(pattern, evidence, re.IGNORECASE):
            status = "unavailable"
            metric_supported = False
            value_supported = False
            value = "未提取到有效数据"
            basis = f"证据未明确出现{expected}，不能支持{task.metric}指标。"
            note = f"确定性语义门禁拒绝将其他技术概念误归类为{task.metric}。"
    return CandidateFact(
        id=task.id,
        company=task.company,
        metric=task.metric,
        value=value,
        basis=basis,
        note=note,
        status=status,
        entity_supported=entity_supported,
        metric_supported=metric_supported,
        value_supported=value_supported,
        confidence=float(item.get("confidence") or 0.0),
        source_score=task.source_score,
        source_tier=task.source_tier,
        row_ref=task.row_ref,
        sources=task.sources,
        evidence_hash=task.evidence_hash,
    )


def extract_facts(state: CurationState) -> dict[str, Any]:
    tasks = [EvidenceTask.model_validate(item) for item in state.get("tasks", [])]
    existing = state.get("existing_items", {})
    candidates: list[CandidateFact] = []
    pending: list[EvidenceTask] = []
    cached_count = 0
    deterministic_count = 0
    for task in tasks:
        deterministic = deterministic_extract_task(task.model_dump())
        if deterministic:
            candidates.append(_candidate_from_cache(task, deterministic))
            deterministic_count += 1
            continue
        cached = existing.get(task.id)
        if isinstance(cached, dict):
            candidates.append(_candidate_from_cache(task, cached))
            cached_count += 1
        else:
            pending.append(task)

    online_used = False
    online_batches = 0
    fallback_batches = 0
    trace_events: list[dict[str, Any]] = [
        _trace(
            state,
            "事实抽取",
            "observe",
            "事实抽取 Agent 收到候选任务和缓存命中情况。",
            input={
                "tasks": len(tasks),
                "cached": len(candidates),
                "deterministic": deterministic_count,
                "pending": len(pending),
                "online_ai": state.get("online_ai", True),
                "batch_size": state.get("batch_size"),
            },
        )
    ]
    batch_size = max(1, int(state.get("batch_size") or 25))
    pending_map = {task.id: task for task in pending}
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        payload = [task.model_dump() for task in batch]
        batch_label = f"{start + 1}-{start + len(batch)} / {len(pending)}"
        if state.get("online_ai", True):
            trace_events.append(
                _trace(
                    state,
                    "事实抽取",
                    "tool_call",
                    f"调用 DeepSeek 清洗批次 {batch_label}。",
                    event_type="tool_call",
                    tool="DeepSeek chat/completions",
                    input={
                        "batch": batch_label,
                        "task_count": len(batch),
                        "sample": [
                            {"id": item["id"], "company": item["company"], "metric": item["metric"]}
                            for item in payload[:3]
                        ],
                    },
                )
            )
            try:
                started = time.monotonic()
                cleaned = call_deepseek(payload)
                online_used = True
                online_batches += 1
                trace_events.append(
                    _trace(
                        state,
                        "事实抽取",
                        "tool_result",
                        f"DeepSeek 返回 {len(cleaned)} 条清洗结果。",
                        event_type="tool_result",
                        tool="DeepSeek chat/completions",
                        result={
                            "batch": batch_label,
                            "returned": len(cleaned),
                            "sample": cleaned[:3],
                        },
                        status="success",
                        duration_ms=round((time.monotonic() - started) * 1000),
                    )
                )
            except Exception as exc:
                fallback_batches += 1
                _event("事实抽取", f"在线模型不可用，本批转入严格离线门禁：{clean_text(exc, 180)}")
                trace_events.append(
                    _trace(
                        state,
                        "事实抽取",
                        "tool_result",
                        "DeepSeek 调用失败，切换到本地严格门禁。",
                        event_type="tool_result",
                        tool="DeepSeek chat/completions",
                        result={"batch": batch_label, "error": clean_text(exc, 400)},
                        status="failed",
                    )
                )
                cleaned = fallback_clean_batch(payload)
        else:
            fallback_batches += 1
            trace_events.append(
                _trace(
                    state,
                    "事实抽取",
                    "tool_call",
                    f"执行本地严格门禁批次 {batch_label}。",
                    event_type="tool_call",
                    tool="fallback_clean_batch",
                    input={"batch": batch_label, "task_count": len(batch)},
                )
            )
            cleaned = fallback_clean_batch(payload)
            trace_events.append(
                _trace(
                    state,
                    "事实抽取",
                    "tool_result",
                    f"本地严格门禁返回 {len(cleaned)} 条结果。",
                    event_type="tool_result",
                    tool="fallback_clean_batch",
                    result={"batch": batch_label, "returned": len(cleaned), "sample": cleaned[:3]},
                )
            )
        for item in cleaned:
            if not isinstance(item, dict) or item.get("id") not in pending_map:
                continue
            task = pending_map[item["id"]]
            candidates.append(_candidate_from_cache(task, item))
    return {
        "candidates": [item.model_dump() for item in candidates],
        "summary": {
            "onlineAiUsed": online_used,
            "onlineBatches": online_batches,
            "fallbackBatches": fallback_batches,
        },
        "node_events": [
            _event(
                "事实抽取",
                f"形成 {len(candidates)} 条候选事实；待抽取 {len(pending)} 条，缓存复用 {cached_count} 条。",
            )
        ],
        "agent_trace": [
            *trace_events,
            _trace(
                state,
                "事实抽取",
                "answer",
                f"形成 {len(candidates)} 条候选事实；待抽取 {len(pending)} 条，缓存复用 {cached_count} 条。",
                output={
                    "candidates": len(candidates),
                    "newly_extracted": len(pending),
                    "cache_reused": cached_count,
                    "deterministic_extracted": deterministic_count,
                    "online_ai_used": online_used,
                    "online_batches": online_batches,
                    "fallback_batches": fallback_batches,
                },
            ),
        ],
    }


def validate_entities(state: CurationState) -> dict[str, Any]:
    tasks = {item["id"]: item for item in state.get("tasks", [])}
    output: list[dict[str, Any]] = []
    rejected = 0
    for raw in state.get("candidates", []):
        fact = CandidateFact.model_validate(raw)
        task = tasks.get(fact.id, {})
        offline_supported = entity_supported_offline(task)
        if offline_supported:
            fact.entity_supported = True
        else:
            fact.entity_supported = False
            fact.reasons.append("来源域名或证据文本不支持该主体")
        if fact.metric in KNOWN_COMPANY_NAMES:
            fact.metric_supported = False
            fact.reasons.append("指标名疑似串入公司名称")
        if not fact.entity_supported or not fact.metric_supported:
            fact.decision = "rejected"
            rejected += 1
        output.append(fact.model_dump())
    return {
        "candidates": output,
        "node_events": [_event("主体校验", f"主体与指标归属校验完成，预拒绝 {rejected} 条。")],
        "agent_trace": _trace_pair(
            state,
            "主体校验",
            input={"candidates": len(state.get("candidates", []))},
            output={"pre_rejected": rejected, "candidates": len(output)},
            message=f"主体与指标归属校验完成，预拒绝 {rejected} 条。",
        ),
    }


def audit_quality(state: CurationState) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    accepted = rejected = review = 0
    evidence_gaps = quality_rejected = 0
    for raw in state.get("candidates", []):
        fact = CandidateFact.model_validate(raw)
        # The audit node may be re-entered after a targeted recrawl. Recompute
        # transient audit reasons instead of carrying stale failures forward.
        fact.reasons = [reason for reason in fact.reasons if reason not in AUDIT_REASON_TEXTS]
        _recover_explicit_not_applicable(fact)
        if (
            fact.status != "ok"
            and fact.entity_supported
            and fact.metric_supported
            and fact.value_supported
            and fact.confidence >= 0.8
        ):
            recovered_value = _direct_value(fact.metric, fact.basis)
            if recovered_value and _passes_metric_gate(fact.metric, recovered_value):
                fact.value = recovered_value
                fact.status = "ok"
                fact.note = clean_text(f"{fact.note}；从依据文本反填结构化值", 160)
        if not _passes_metric_gate(fact.metric, fact.value):
            recovered_value = _recover_fact_value(fact)
            if recovered_value:
                fact.value = recovered_value
                fact.status = "ok"
                fact.value_supported = True
                fact.note = clean_text(f"{fact.note}；从依据文本补全数值或单位", 160).strip("；")
        combined = f"{fact.value} {fact.basis}"
        if not fact.entity_supported:
            fact.reasons.append("主体归属未通过")
        if not fact.metric_supported:
            fact.reasons.append("指标语义未通过")
        if fact.status != "ok":
            fact.reasons.append("抽取结果不可用")
        if not fact.value_supported:
            fact.reasons.append("数值或事实依据不足")
        if not _passes_metric_gate(fact.metric, fact.value):
            fact.reasons.append("未通过指标格式与单位门禁")
        if any(term.lower() in combined.lower() for term in DIRTY_SOURCE_LABEL_TERMS):
            fact.reasons.append("包含网页导航或无关文本")
        if _is_truncated_qualitative_fragment(fact.metric, fact.value):
            fact.reasons.append("定性指标为截断网页片段")
        if fact.source_score < 0.45:
            fact.reasons.append("缺少可核验公开来源")
        if fact.confidence < 0.8:
            fact.reasons.append("置信度低于80%")
        if "AI不可用" in fact.note:
            fact.reasons.append("在线模型不可用，离线结果不直接发布")

        fact.reasons = list(dict.fromkeys(fact.reasons))
        fact.quality_score = round(
            0.35 * float(fact.entity_supported)
            + 0.25 * float(fact.metric_supported)
            + 0.2 * float(fact.value_supported)
            + 0.1 * min(max(fact.confidence, 0.0), 1.0)
            + 0.1 * fact.source_score,
            4,
        )
        if fact.reasons:
            fact.decision = "rejected"
            rejected += 1
            if fact.status != "ok":
                evidence_gaps += 1
            else:
                quality_rejected += 1
        elif fact.quality_score >= 0.84:
            fact.decision = "accepted"
            accepted += 1
        else:
            fact.decision = "review"
            review += 1
        output.append(fact.model_dump())
    return {
        "candidates": output,
        "node_events": [
            _event(
                "质量审计",
                f"发布 {accepted} 条、证据缺口 {evidence_gaps} 条、"
                f"质量拒绝 {quality_rejected} 条、待复核 {review} 条。",
            )
        ],
        "agent_trace": _trace_pair(
            state,
            "质量审计",
            input={"candidates": len(state.get("candidates", []))},
            output={
                "accepted": accepted,
                "evidence_gaps": evidence_gaps,
                "quality_rejected": quality_rejected,
                "review": review,
                "unpublished": rejected,
            },
            message=(
                f"发布 {accepted} 条；{evidence_gaps} 条因证据未覆盖进入补爬，"
                f"{quality_rejected} 条因质量问题拒绝，{review} 条待复核。"
            ),
        ),
    }


def resolve_conflicts(state: CurationState) -> dict[str, Any]:
    candidates = [CandidateFact.model_validate(item) for item in state.get("candidates", [])]
    groups: dict[tuple[str, str, str], list[CandidateFact]] = {}
    for fact in candidates:
        if fact.decision != "accepted":
            continue
        groups.setdefault((fact.company, fact.metric, fact.row_ref), []).append(fact)
    conflicts = 0
    for facts in groups.values():
        values = {re.sub(r"\s+", "", fact.value).lower() for fact in facts}
        if len(values) <= 1:
            continue
        conflicts += 1
        ranked = sorted(facts, key=lambda item: (item.quality_score, item.source_score, item.confidence), reverse=True)
        best = ranked[0]
        for fact in ranked[1:]:
            if best.quality_score - fact.quality_score < 0.08:
                best.decision = "review"
                fact.decision = "review"
                best.reasons.append("同一披露口径存在高质量冲突值")
                fact.reasons.append("同一披露口径存在高质量冲突值")
            else:
                fact.decision = "rejected"
                fact.reasons.append(f"同一披露口径已有更高质量候选：{best.id}")
    return {
        "candidates": [item.model_dump() for item in candidates],
        "node_events": [_event("冲突仲裁", f"检查 {len(groups)} 组事实，发现 {conflicts} 组冲突。")],
        "agent_trace": _trace_pair(
            state,
            "冲突仲裁",
            input={"accepted_groups": len(groups)},
            output={"conflicts": conflicts},
            message=f"检查 {len(groups)} 组事实，发现 {conflicts} 组冲突。",
        ),
    }


def plan_gaps(state: CurationState) -> dict[str, Any]:
    candidates = [CandidateFact.model_validate(item) for item in state.get("candidates", [])]
    accepted_count = sum(item.decision == "accepted" for item in candidates)
    best_count = int(state.get("best_accepted_count") or 0)
    best_candidates = state.get("best_candidates", [])
    trace_events: list[dict[str, Any]] = [
        _trace(
            state,
            "缺口规划",
            "observe",
            "缺口规划 Agent 读取候选事实和当前最佳通过数。",
            input={
                "candidates": len(candidates),
                "accepted_count": accepted_count,
                "best_accepted_count": best_count,
                "allow_recrawl": state.get("allow_recrawl"),
                "recrawl_round": state.get("recrawl_round"),
            },
        )
    ]
    if accepted_count >= best_count:
        best_count = accepted_count
        best_candidates = [item.model_dump() for item in candidates]
    elif int(state.get("recrawl_round") or 0) > 0 and best_candidates:
        candidates = [CandidateFact.model_validate(item) for item in best_candidates]
        accepted_count = best_count
        _event(
            "质量回退保护",
            f"补爬后通过数由 {best_count} 降至 "
            f"{sum(item.get('decision') == 'accepted' for item in state.get('candidates', []))}，"
            "保留补爬前高质量结果。",
        )
    groups: dict[tuple[str, str, str], list[CandidateFact]] = {}
    for fact in candidates:
        groups.setdefault((fact.company, fact.metric, fact.row_ref), []).append(fact)
    gaps: list[GapRecord] = []
    row_stats: dict[str, dict[str, Any]] = {}
    for (company, metric, row_ref), facts in groups.items():
        if any(fact.decision == "accepted" for fact in facts):
            continue
        reason_counts: dict[str, int] = {}
        for fact in facts:
            for reason in fact.reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        reason = max(reason_counts, key=reason_counts.get) if reason_counts else "没有可发布候选"
        gaps.append(
            GapRecord(
                company=company,
                metric=metric,
                row_ref=row_ref,
                reason=reason,
                candidate_ids=[fact.id for fact in facts],
            )
        )
        stats = row_stats.setdefault(
            row_ref,
            {"gaps": 0, "failed": 0, "companies": [], "metrics": []},
        )
        stats["gaps"] += 1
        if company not in stats["companies"]:
            stats["companies"].append(company)
        if metric not in stats["metrics"]:
            stats["metrics"].append(metric)
        if _result_status(row_ref) in {"partial", "failed", "error"}:
            stats["failed"] = 1

    recrawl_tasks: list[RecrawlTask] = []
    if (
        state.get("allow_recrawl")
        and int(state.get("recrawl_round") or 0) < int(state.get("max_recrawl_rounds") or 1)
    ):
        ranked_rows = sorted(
            row_stats.items(),
            key=lambda item: (
                int(item[0].removeprefix("row_") or 0) in PRIMARY_PERFORMANCE_ROWS,
                item[1]["failed"],
                int(item[0].removeprefix("row_") or 0) in CORE_COMPANY_ROWS,
                item[1]["gaps"],
            ),
            reverse=True,
        )
        for row_ref, stats in ranked_rows:
            match = re.fullmatch(r"row_(\d+)", row_ref or "")
            if not match or (not stats["failed"] and stats["gaps"] < 3):
                continue
            recrawl_tasks.append(
                RecrawlTask(
                    row_ref=row_ref,
                    row_number=int(match.group(1)),
                    reason=f"{stats['gaps']} 个指标缺口"
                    + ("，原爬取状态非完整成功" if stats["failed"] else "，现有证据未通过质量门禁"),
                    priority=100 if stats["failed"] else min(90, 50 + stats["gaps"]),
                    attempts=int(state.get("recrawl_round") or 0),
                    companies=stats["companies"],
                    metrics=stats["metrics"],
                )
            )
            if len(recrawl_tasks) >= int(state.get("max_recrawl_rows") or 3):
                break
    return {
        "candidates": [item.model_dump() for item in candidates],
        "gaps": [item.model_dump() for item in gaps],
        "recrawl_tasks": [item.model_dump() for item in recrawl_tasks],
        "best_candidates": best_candidates,
        "best_accepted_count": best_count,
        "node_events": [
            _event("缺口规划", f"识别 {len(gaps)} 个事实缺口，安排 {len(recrawl_tasks)} 个定向补爬行。")
        ],
        "agent_trace": [
            *trace_events,
            _trace(
                state,
                "缺口规划",
                "answer",
                f"识别 {len(gaps)} 个事实缺口，安排 {len(recrawl_tasks)} 个定向补爬行。",
                output={
                    "gaps": len(gaps),
                    "recrawl_tasks": [item.model_dump() for item in recrawl_tasks],
                    "best_accepted_count": best_count,
                },
            ),
        ],
    }


def _build_supervisor_model() -> ChatDeepSeek:
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置 DeepSeek API Key")
    return ChatDeepSeek(
        model=str(config.get("model") or "deepseek-chat"),
        api_key=api_key,
        base_url=str(config.get("base_url") or "https://api.deepseek.com").rstrip("/"),
        temperature=0,
        timeout=120,
        max_retries=1,
    )


def supervise_gap_actions(state: CurationState) -> dict[str, Any]:
    planned = [RecrawlTask.model_validate(item) for item in state.get("recrawl_tasks", [])]
    gaps = [GapRecord.model_validate(item) for item in state.get("gaps", [])]
    trace_events: list[dict[str, Any]] = [
        _trace(
            state,
            "编排决策",
            "observe",
            "Supervisor 收到质量门禁产生的证据缺口和候选补爬任务。",
            input={
                "gaps": len(gaps),
                "candidate_recrawl_rows": [item.row_number for item in planned],
                "recrawl_round": state.get("recrawl_round", 0),
                "max_recrawl_rounds": state.get("max_recrawl_rounds", 1),
            },
        )
    ]
    if not planned:
        reason = "没有满足补爬条件的候选行，进入发布。"
        return {
            "supervisor_decision": "publish",
            "supervisor_reason": reason,
            "recrawl_tasks": [],
            "node_events": [_event("编排决策", reason)],
            "agent_trace": [
                *trace_events,
                _trace(state, "编排决策", "decision", reason, decision="publish", status="success"),
            ],
        }

    allowed = {item.row_number: item for item in planned}
    gap_by_row: dict[int, list[GapRecord]] = {}
    for gap in gaps:
        match = re.fullmatch(r"row_(\d+)", gap.row_ref or "")
        if match:
            gap_by_row.setdefault(int(match.group(1)), []).append(gap)
    decision: dict[str, Any] = {}

    @tool
    def inspect_evidence_gaps(row_numbers: list[int]) -> dict[str, Any]:
        """读取候选行的缺口、抓取状态和缺失指标，供 Supervisor 决策。"""
        rows = []
        for row_number in row_numbers:
            if row_number not in allowed:
                continue
            row_gaps = gap_by_row.get(row_number, [])
            rows.append(
                {
                    "row": row_number,
                    "crawl_status": _result_status(f"row_{row_number}") or "unknown",
                    "gap_count": len(row_gaps),
                    "metrics": [gap.metric for gap in row_gaps[:12]],
                    "companies": list(dict.fromkeys(gap.company for gap in row_gaps))[:12],
                    "reasons": list(dict.fromkeys(gap.reason for gap in row_gaps))[:6],
                    "deterministic_priority": allowed[row_number].priority,
                }
            )
        return {"rows": rows, "max_rows": int(state.get("max_recrawl_rows") or 3)}

    @tool
    def schedule_targeted_recrawl(row_numbers: list[int], rationale: str) -> dict[str, Any]:
        """从允许的候选行中选择补爬行，不能绕过确定性质量门禁。"""
        max_rows = int(state.get("max_recrawl_rows") or 3)
        selected = list(dict.fromkeys(row for row in row_numbers if row in allowed))[:max_rows]
        decision.update({"action": "recrawl", "rows": selected, "reason": clean_text(rationale, 500)})
        return {
            "accepted": bool(selected),
            "selected_rows": selected,
            "rejected_rows": [row for row in row_numbers if row not in allowed],
            "reason": decision.get("reason", ""),
        }

    @tool
    def publish_without_recrawl(reason: str) -> dict[str, Any]:
        """放弃本轮补爬并进入发布，适用于重复抓取无法解决的质量问题。"""
        decision.update({"action": "publish", "rows": [], "reason": clean_text(reason, 500)})
        return {"accepted": True, "action": "publish", "reason": decision["reason"]}

    tools = [inspect_evidence_gaps, schedule_targeted_recrawl, publish_without_recrawl]
    tool_map = {item.name: item for item in tools}
    if state.get("online_ai", True):
        try:
            model = _build_supervisor_model().bind_tools(tools)
            messages: list[Any] = [
                SystemMessage(
                    content=(
                        "你是公开信息数据治理 Supervisor。你不能直接修改事实、质量分数或发布阈值。"
                        "必须先调用 inspect_evidence_gaps 查看候选行，再调用 schedule_targeted_recrawl "
                        "或 publish_without_recrawl 作出唯一决策。补爬只用于抓取失败、证据缺失或关键指标"
                        "缺口；格式问题、主体错误和低质量商业来源不应靠重复补爬解决。"
                        "自然语言说明使用简洁中文段落，不要输出 Markdown 标题或表格，控制在 200 字以内。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"当前有 {len(gaps)} 个证据缺口；规则引擎给出候选行 {sorted(allowed)}。"
                        f"最多补爬 {int(state.get('max_recrawl_rows') or 3)} 行。"
                    )
                ),
            ]
            for _ in range(4):
                started = time.monotonic()
                response = model.invoke(messages)
                messages.append(response)
                trace_events.append(
                    _trace(
                        state,
                        "编排决策",
                        "thinking",
                        clean_text(response.content or "Supervisor 正在选择工具。", 500),
                        output={"tool_calls": response.tool_calls},
                        duration_ms=round((time.monotonic() - started) * 1000),
                    )
                )
                if not response.tool_calls:
                    break
                for call in response.tool_calls:
                    name = str(call.get("name") or "")
                    args = call.get("args") or {}
                    trace_events.append(
                        _trace(
                            state,
                            "编排决策",
                            "tool_call",
                            f"Supervisor 调用工具：{name}。",
                            event_type="tool_call",
                            tool=name,
                            input=args,
                        )
                    )
                    selected_tool = tool_map.get(name)
                    result = (
                        selected_tool.invoke(args)
                        if selected_tool is not None
                        else {"ok": False, "error": f"未知工具：{name}"}
                    )
                    trace_events.append(
                        _trace(
                            state,
                            "编排决策",
                            "tool_result",
                            f"工具 {name} 已返回。",
                            event_type="tool_result",
                            tool=name,
                            result=result,
                            status="success" if result.get("ok", True) is not False else "failed",
                        )
                    )
                    messages.append(
                        ToolMessage(
                            content=json.dumps(result, ensure_ascii=False),
                            tool_call_id=str(call.get("id") or name),
                        )
                    )
                if decision:
                    break
        except Exception as exc:
            trace_events.append(
                _trace(
                    state,
                    "编排决策",
                    "tool_result",
                    "Supervisor 模型不可用，使用规则引擎的安全调度结果。",
                    event_type="tool_result",
                    tool="DeepSeek tool-calling supervisor",
                    result={"error": clean_text(exc, 500)},
                    status="fallback",
                )
            )

    if not decision:
        selected = [item.row_number for item in planned][: int(state.get("max_recrawl_rows") or 3)]
        decision = {
            "action": "recrawl" if selected else "publish",
            "rows": selected,
            "reason": "模型未形成有效工具决策，采用规则引擎优先级。",
        }
    selected_tasks = [allowed[row].model_dump() for row in decision.get("rows", []) if row in allowed]
    action = "recrawl" if selected_tasks and decision.get("action") == "recrawl" else "publish"
    reason = str(decision.get("reason") or "")
    message = (
        f"Supervisor 决定补爬 {', '.join(str(item['row_number']) for item in selected_tasks)}；{reason}"
        if action == "recrawl"
        else f"Supervisor 决定直接发布；{reason}"
    )
    return {
        "supervisor_decision": action,
        "supervisor_reason": reason,
        "recrawl_tasks": selected_tasks,
        "node_events": [_event("编排决策", message)],
        "agent_trace": [
            *trace_events,
            _trace(
                state,
                "编排决策",
                "decision",
                message,
                output={"action": action, "rows": [item["row_number"] for item in selected_tasks]},
                decision=action,
                status="success",
            ),
        ],
    }


def _backup_global_artifacts(run_id: str) -> Path:
    backup_dir = DATA_DIR / "backups" / run_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in GLOBAL_CRAWL_ARTIFACTS:
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, backup_dir / name)
    return backup_dir


def _restore_global_artifacts(backup_dir: Path) -> None:
    for name in GLOBAL_CRAWL_ARTIFACTS:
        source = backup_dir / name
        target = ROOT / name
        if source.exists():
            shutil.copy2(source, target)


def recrawl_gaps(state: CurationState) -> dict[str, Any]:
    tasks = [RecrawlTask.model_validate(item) for item in state.get("recrawl_tasks", [])]
    if not tasks:
        return {
            "node_events": [_event("定向补爬", "没有需要执行的补爬任务。")],
            "agent_trace": [
                _trace(state, "定向补爬", "answer", "没有需要执行的补爬任务。", output={"recrawl_tasks": 0})
            ],
        }
    row_numbers = sorted({task.row_number for task in tasks})
    backup_dir = _backup_global_artifacts(state["run_id"])
    env = os.environ.copy()
    env["CMHK_ROWS"] = ",".join(str(row) for row in row_numbers)
    env["CMHK_GAP_TARGETS"] = json.dumps(
        {
            str(task.row_number): {
                "companies": task.companies,
                "metrics": task.metrics,
            }
            for task in tasks
        },
        ensure_ascii=False,
    )
    env["CMHK_CRAWL_MAX_SECONDS"] = str(min(int(env.get("CMHK_CRAWL_MAX_SECONDS", "900")), 600))
    command = [sys.executable, str(ROOT / "crawl.py")]
    trace_events = [
        _trace(
            state,
            "定向补爬",
            "tool_call",
            f"调用爬虫补爬行 {', '.join(map(str, row_numbers))}。",
            event_type="tool_call",
            tool="subprocess.run",
            input={
                "command": command,
                "cwd": str(ROOT),
                "env": {
                    "CMHK_ROWS": env["CMHK_ROWS"],
                    "CMHK_GAP_TARGETS": json.loads(env["CMHK_GAP_TARGETS"]),
                    "CMHK_CRAWL_MAX_SECONDS": env["CMHK_CRAWL_MAX_SECONDS"],
                },
                "timeout": 720,
            },
        )
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=720,
        )
    finally:
        _restore_global_artifacts(backup_dir)
    trace_events.append(
        _trace(
            state,
            "定向补爬",
            "tool_result",
            "补爬子进程已返回。",
            event_type="tool_result",
            tool="subprocess.run",
            result={
                "returncode": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-1200:],
                "stderr_tail": (proc.stderr or "")[-1200:],
            },
        )
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "定向补爬失败")[-1000:])
    return {
        "recrawl_round": int(state.get("recrawl_round") or 0) + 1,
        "recrawl_performed": True,
        "executed_recrawl_rows": row_numbers,
        "node_events": [_event("定向补爬", f"完成行 {', '.join(map(str, row_numbers))} 的补爬，重新进入整理流程。")],
        "agent_trace": [
            *trace_events,
            _trace(
                state,
                "定向补爬",
                "answer",
                f"完成行 {', '.join(map(str, row_numbers))} 的补爬，重新进入整理流程。",
                output={"executed_rows": row_numbers},
            ),
        ],
    }


def publish_results(state: CurationState) -> dict[str, Any]:
    candidates = [CandidateFact.model_validate(item) for item in state.get("candidates", [])]
    accepted = [item for item in candidates if item.decision == "accepted"]
    rejected = [item for item in candidates if item.decision == "rejected"]
    review = [item for item in candidates if item.decision == "review"]
    evidence_gaps = sum(item.status != "ok" for item in rejected)
    quality_rejected = len(rejected) - evidence_gaps
    completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    publish_event = _event(
        "发布",
        f"发布层写入 {len(accepted)} 条，拒绝 {len(rejected)} 条，待人工复核 {len(review)} 条。",
    )
    trace_events: list[dict[str, Any]] = [
        _trace(
            state,
            "发布",
            "observe",
            "发布 Agent 汇总候选事实并准备写入发布层。",
            input={
                "candidates": len(candidates),
                "accepted": len(accepted),
                "rejected": len(rejected),
                "review": len(review),
                "dry_run": state.get("dry_run"),
            },
        )
    ]
    summary = RunSummary(
        run_id=state["run_id"],
        started_at=state["started_at"],
        completed_at=completed_at,
        tasks=len(state.get("tasks", [])),
        accepted=len(accepted),
        rejected=len(rejected),
        review=len(review),
        gaps=len(state.get("gaps", [])),
        recrawl_rows=state.get("executed_recrawl_rows", []),
        recrawl_performed=bool(state.get("recrawl_performed")),
        online_ai=bool((state.get("summary") or {}).get("onlineAiUsed")),
        node_events=[*state.get("node_events", []), publish_event],
    )
    summary.extra["evidence_gaps"] = evidence_gaps
    summary.extra["quality_rejected"] = quality_rejected
    summary.extra["supervisor_decision"] = state.get("supervisor_decision", "")
    summary.extra["supervisor_reason"] = state.get("supervisor_reason", "")
    summary.extra["online_batches"] = int((state.get("summary") or {}).get("onlineBatches") or 0)
    summary.extra["fallback_batches"] = int((state.get("summary") or {}).get("fallbackBatches") or 0)
    if not state.get("dry_run"):
        cache_backup_path = None
        previous_cache: dict[str, Any] = {}
        if AI_CACHE_PATH.exists():
            backup_dir = DATA_DIR / "cache_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            cache_backup_path = backup_dir / f"{state['run_id']}_before_publish.json"
            shutil.copy2(AI_CACHE_PATH, cache_backup_path)
            try:
                previous_cache = json.loads(AI_CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:
                previous_cache = {}
        cache_items: dict[str, dict[str, Any]] = {}
        for fact in candidates:
            cache_items[fact.id] = _cache_item_from_fact(fact)
        previous_items = (
            previous_cache.get("items", {})
            if previous_cache.get("schemaVersion") == AI_CACHE_SCHEMA_VERSION and isinstance(previous_cache, dict)
            else {}
        )
        previous_accepted = _accepted_cache_items(previous_items if isinstance(previous_items, dict) else {})
        current_accepted = _accepted_cache_items(cache_items)
        current_semantic_keys = {_semantic_key_for_item(item) for item in cache_items.values()}
        current_hashes_by_key = {
            _semantic_key_for_item(item): str(item.get("evidence_hash") or "")
            for item in cache_items.values()
        }
        preserved = 0
        protected_keys: set[str] = set()
        for key, previous_item in previous_accepted.items():
            if key not in current_semantic_keys:
                continue
            if (
                not previous_item.get("evidence_hash")
                or previous_item.get("evidence_hash") != current_hashes_by_key.get(key)
            ):
                continue
            current_item = current_accepted.get(key)
            current_score = float(current_item.get("quality_score") or 0.0) if current_item else -1.0
            previous_score = float(previous_item.get("quality_score") or 0.0)
            if current_item is not None and current_score >= previous_score:
                continue
            preserve_id = "preserved_" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:24]
            cache_items[preserve_id] = {
                **previous_item,
                "schemaVersion": AI_CACHE_SCHEMA_VERSION,
                "note": clean_text(
                    f"{previous_item.get('note', '')}；跨运行质量保护：保留上一轮更高质量事实",
                    220,
                ).strip("；"),
                "decision": "accepted",
                "preserved_from_previous_run": True,
            }
            preserved += 1
            protected_keys.add(key)
        if preserved:
            preserved_event = _event("缓存保护", f"保留上一轮更高质量事实 {preserved} 条，避免本轮离线/补爬退化覆盖。")
            summary.node_events.append(preserved_event)
            summary.extra["preserved_previous_facts"] = preserved
            summary.extra["protected_semantic_keys"] = sorted(protected_keys)[:50]
            trace_events.append(
                _trace(
                    state,
                    "发布",
                    "answer",
                    f"跨运行质量保护保留上一轮更高质量事实 {preserved} 条。",
                    output={"preserved_previous_facts": preserved, "protected_semantic_keys": sorted(protected_keys)[:10]},
                )
            )
        write_targets = [
            str(AI_CACHE_PATH.relative_to(ROOT)),
            "curation_data/candidate_facts.jsonl",
            "curation_data/verified_facts.jsonl",
            "curation_data/recrawl_tasks.json",
            "curation_data/latest.json",
            f"curation_data/runs/{state['run_id']}.json",
            "curation_data/agent_trace.jsonl",
            f"curation_data/runs/{state['run_id']}_agent_trace.jsonl",
        ]
        trace_events.append(
            _trace(
                state,
                "发布",
                "tool_call",
                "写入 AI 缓存、事实 JSONL、缺口任务、运行摘要和 Agent trace。",
                event_type="tool_call",
                tool="atomic_write_json / atomic_write_jsonl",
                input={"targets": write_targets},
            )
        )
        atomic_write_json(
            AI_CACHE_PATH,
            {
                "schemaVersion": AI_CACHE_SCHEMA_VERSION,
                "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                "workflow": "langgraph-multi-agent",
                "runId": state["run_id"],
                "items": cache_items,
            },
        )
        atomic_write_jsonl(DATA_DIR / "candidate_facts.jsonl", [item.model_dump() for item in candidates])
        atomic_write_jsonl(DATA_DIR / "verified_facts.jsonl", [item.model_dump() for item in accepted])
        atomic_write_json(DATA_DIR / "recrawl_tasks.json", state.get("recrawl_tasks", []))
        atomic_write_json(DATA_DIR / "latest.json", summary.model_dump())
        atomic_write_json(RUNS_DIR / f"{state['run_id']}.json", summary.model_dump())
        if cache_backup_path:
            summary.extra["cache_backup"] = str(cache_backup_path.relative_to(ROOT))
            atomic_write_json(DATA_DIR / "latest.json", summary.model_dump())
            atomic_write_json(RUNS_DIR / f"{state['run_id']}.json", summary.model_dump())
        final_trace = [
            *state.get("agent_trace", []),
            *trace_events,
            _trace(
                state,
                "发布",
                "tool_result",
                "发布层文件写入完成。",
                event_type="tool_result",
                tool="atomic_write_json / atomic_write_jsonl",
                result={"targets": write_targets, "ok": True},
            ),
            _trace(
                state,
                "发布",
                "answer",
                (
                    f"发布完成：发布 {len(accepted)} 条，证据缺口 {evidence_gaps} 条，"
                    f"质量拒绝 {quality_rejected} 条，待复核 {len(review)} 条。"
                ),
                output={
                    **summary.model_dump(),
                    "evidence_gaps": evidence_gaps,
                    "quality_rejected": quality_rejected,
                },
            ),
        ]
        atomic_write_jsonl(DATA_DIR / "agent_trace.jsonl", final_trace)
        atomic_write_jsonl(RUNS_DIR / f"{state['run_id']}_agent_trace.jsonl", final_trace)
        summary.extra["agent_trace"] = "curation_data/agent_trace.jsonl"
        atomic_write_json(DATA_DIR / "latest.json", summary.model_dump())
        atomic_write_json(RUNS_DIR / f"{state['run_id']}.json", summary.model_dump())
    return {
        "summary": summary.model_dump(),
        "node_events": [publish_event],
        "agent_trace": trace_events,
    }


def route_after_supervisor(state: CurationState) -> str:
    return "recrawl" if state.get("supervisor_decision") == "recrawl" else "publish"


def build_graph():
    builder = StateGraph(CurationState)
    retry = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, max_interval=8.0)
    builder.add_node("ingest", ingest_evidence, retry_policy=retry)
    builder.add_node("classify", classify_sources, retry_policy=retry)
    builder.add_node("extract", extract_facts, retry_policy=retry)
    builder.add_node("validate", validate_entities, retry_policy=retry)
    builder.add_node("audit", audit_quality, retry_policy=retry)
    builder.add_node("resolve", resolve_conflicts, retry_policy=retry)
    builder.add_node("plan_gaps", plan_gaps, retry_policy=retry)
    builder.add_node("supervisor", supervise_gap_actions, retry_policy=retry)
    # These nodes have external side effects and must not be retried implicitly.
    builder.add_node("recrawl", recrawl_gaps)
    builder.add_node("publish", publish_results)
    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "classify")
    builder.add_edge("classify", "extract")
    builder.add_edge("extract", "validate")
    builder.add_edge("validate", "audit")
    builder.add_edge("audit", "resolve")
    builder.add_edge("resolve", "plan_gaps")
    builder.add_edge("plan_gaps", "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"recrawl": "recrawl", "publish": "publish"},
    )
    builder.add_edge("recrawl", "ingest")
    builder.add_edge("publish", END)
    checkpointer = MemorySaver()
    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(DATA_DIR / "checkpoints.sqlite", check_same_thread=False)
        checkpointer = SqliteSaver(connection)
    except ImportError:
        pass
    return builder.compile(checkpointer=checkpointer)


def run_workflow(
    *,
    limit: int | None = None,
    batch_size: int = 25,
    online_ai: bool = True,
    allow_recrawl: bool = False,
    max_recrawl_rows: int = 3,
    max_recrawl_rounds: int = 1,
    dry_run: bool = False,
) -> dict[str, Any]:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    initial: CurationState = {
        "run_id": run_id,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "limit": limit,
        "batch_size": batch_size,
        "online_ai": online_ai,
        "allow_recrawl": allow_recrawl,
        "dry_run": dry_run,
        "max_recrawl_rows": max_recrawl_rows,
        "max_recrawl_rounds": max_recrawl_rounds,
        "recrawl_round": 0,
        "recrawl_performed": False,
        "executed_recrawl_rows": [],
        "best_candidates": [],
        "best_accepted_count": 0,
        "node_events": [],
        "agent_trace": [],
    }
    result = build_graph().invoke(initial, config={"configurable": {"thread_id": run_id}})
    return result.get("summary", {})
