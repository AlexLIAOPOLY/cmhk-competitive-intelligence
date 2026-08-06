from __future__ import annotations

import argparse
import csv
import difflib
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
HKT = ZoneInfo("Asia/Hong_Kong")
STATE_DIR = ROOT / "agent_knowledge" / "executive_intelligence_refresh"
STATE_PATH = STATE_DIR / "latest.json"
AI_ANALYSIS_PATH = STATE_DIR / "ai_analysis.json"
LOCK_PATH = STATE_DIR / ".refresh.lock"
LOG_PATH = STATE_DIR / "refresh.log"
WATCHDOG_STATE_PATH = STATE_DIR / "watchdog.json"
PAGES_PUBLISH_SCRIPT = ROOT / "scripts" / "publish_executive_dashboard_pages.py"
INSIGHT_FORMAT_VERSION = "single_sentence_v1"
MAX_FOCUS_INSIGHT_CHARS = 88
TASK_KIND = "executive-intelligence-refresh"
DOMAIN_LABELS = {
    "local": "本地竞对",
    "international": "国际竞对",
    "cloud": "云厂商",
    "macro": "宏观政策",
}

LOCAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/current_plans.json"
INTERNATIONAL_DIR = ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18"
INTERNATIONAL_PATH = INTERNATIONAL_DIR / "quarterly_metrics.json"
CLOUD_DIR = ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17"
CLOUD_PATH = CLOUD_DIR / "cloud_vendor_metrics_2023_2025.json"
MACRO_DIR = ROOT / "agent_knowledge/cmhk_macro_policy_2026-06-19"
MACRO_PATH = MACRO_DIR / "macro_policy_metrics.json"
VERIFIED_FACTS_PATH = ROOT / "curation_data/verified_facts.jsonl"
DOMAIN_FACT_PATHS = {
    "local": LOCAL_PATH.parent / "agent_verified_facts.json",
    "international": INTERNATIONAL_DIR / "agent_verified_facts.json",
    "cloud": CLOUD_DIR / "agent_verified_facts.json",
    "macro": MACRO_DIR / "agent_verified_facts.json",
}

LOCAL_COMPANIES = {
    "HKT", "csl", "1O1O", "3HK / Hutchison", "Hutchison", "SmarTone", "HKBN", "HGC", "i-CABLE"
}
INTERNATIONAL_COMPANIES = {
    "中国移动", "中国电信", "中国联通", "中国铁塔", "KDDI", "SoftBank", "Telstra", "Jio",
    "T-Mobile US", "AT&T", "Orange", "Telefonica",
}
CLOUD_COMPANIES = {
    "AWS", "Amazon Web Services", "Microsoft Azure", "Azure", "Google Cloud", "Alibaba Cloud",
    "阿里云", "Tencent Cloud", "腾讯云", "Huawei Cloud", "华为云", "Oracle Cloud",
}
MACRO_COMPANIES = {"政策", "香港本地监管", "OFCA", "香港统计处", "政府"}

SAFE_VERIFICATION_STATUSES = {
    "official_match",
    "official_only",
    "official_derived_from_verified_rows",
    "multi_source_or_multi_snapshot_verified",
}


def _now() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _append_log(message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _task_stream_path(task_run_id: str) -> Path:
    return ROOT / "agent_knowledge" / "crawl_run_logs" / "runs" / f"{task_run_id}.jsonl"


def _task_event(
    task_run_id: str,
    phase: str,
    detail: str,
    *,
    worker_pid: int = 0,
    level: str = "info",
) -> None:
    """Write one human-readable task-log line and update the unified-task heartbeat."""
    if not task_run_id:
        return
    from crawl_run_registry import append_crawl_run_event, heartbeat_crawl_run

    heartbeat_crawl_run(
        task_run_id,
        phase,
        detail,
        worker_pid=worker_pid or os.getpid(),
        append_log=False,
    )
    prefix = "预警" if level == "critical" else "后备重试" if level == "retry" else phase
    append_crawl_run_event(
        _task_stream_path(task_run_id),
        {
            "type": "log",
            "text": f"[{datetime.now(HKT).strftime('%H:%M:%S')}] [{prefix}] {detail}",
        },
    )


def _start_refresh_task(
    *,
    agent_run_id: str,
    parent_crawl_run_id: str = "",
    recovery_reason: str = "",
) -> dict[str, Any]:
    from crawl_run_registry import append_crawl_run_event, start_crawl_run

    scope = f"Agent审核 {agent_run_id}"
    if parent_crawl_run_id:
        scope += f" · 父任务 {parent_crawl_run_id}"
    if recovery_reason:
        scope += f" · {recovery_reason}"
    task = start_crawl_run(
        trigger="四库与观察结论自动更新",
        scope=scope,
        task_kind=TASK_KIND,
        phase="等待刷新进程",
        progress_detail="任务已归档，正在启动本地竞对、国际竞对、云厂商和宏观政策更新。",
    )
    task_run_id = str(task["crawl_run_id"])
    append_crawl_run_event(
        task["stream_log_path"],
        {
            "type": "log",
            "text": (
                f"[{datetime.now(HKT).strftime('%H:%M:%S')}] [任务启动] "
                f"四库更新已接收；Agent run={agent_run_id}；父任务={parent_crawl_run_id or '无'}。"
            ),
        },
    )
    return task


def _finalize_refresh_task(
    task_run_id: str,
    *,
    ok: bool,
    detail: str,
    result: dict[str, Any],
    attempts: int,
) -> None:
    if not task_run_id:
        return
    from crawl_run_registry import finalize_operational_crawl_run

    _task_event(
        task_run_id,
        "任务完成" if ok else "任务失败",
        detail,
        level="info" if ok else "critical",
    )
    finalize_operational_crawl_run(
        task_run_id,
        ok=ok,
        duration_ms=int(result.get("total_duration_ms") or result.get("duration_ms") or 0),
        progress_detail=detail,
        failure_stage="" if ok else "executive_intelligence_refresh",
        summary={
            "attempts": attempts,
            "agent_run_id": result.get("agent_run_id", ""),
            "failed_domains": result.get("failed_domains", []),
            "status": result.get("status", ""),
            "notification_policy": "local_log_only",
            "model_analysis": result.get("model_analysis", {}),
            "pages_publish": result.get("pages_publish", {}),
        },
    )


def _content_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _first_source(fact: dict[str, Any]) -> str:
    for source in fact.get("sources") or []:
        value = str(source or "").strip()
        if value.startswith(("https://", "http://")):
            return value
    return ""


def _fact_domain(fact: dict[str, Any]) -> str | None:
    company = str(fact.get("company") or "").strip()
    if company in LOCAL_COMPANIES:
        return "local"
    if company in CLOUD_COMPANIES:
        return "cloud"
    if company in INTERNATIONAL_COMPANIES:
        return "international"
    if company in MACRO_COMPANIES:
        return "macro"
    metric = str(fact.get("metric") or "")
    if any(token in metric for token in ("政策", "监管", "频谱", "投诉", "GDP", "消费")):
        return "macro"
    return None


def _accepted_fact(fact: dict[str, Any]) -> bool:
    basis = str(fact.get("basis") or "")
    if re.search(r"无(?:明确)?资本开支(?:总额|金额)|无明确.{0,20}(?:金额|数字)", basis):
        return False
    return bool(
        fact.get("decision") == "accepted"
        and fact.get("status") == "ok"
        and fact.get("entity_supported")
        and fact.get("metric_supported")
        and fact.get("value_supported")
        and float(fact.get("quality_score") or 0) >= 0.85
        and _first_source(fact)
    )


def build_ai_analysis(
    *,
    agent_run_id: str,
    verified_facts_path: Path = VERIFIED_FACTS_PATH,
    curation_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    if verified_facts_path.exists():
        for line in verified_facts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                fact = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _accepted_fact(fact) and _fact_domain(fact):
                facts.append(fact)

    domains: dict[str, list[dict[str, Any]]] = {key: [] for key in ("local", "international", "cloud", "macro")}
    seen: set[tuple[str, str, str]] = set()
    facts.sort(
        key=lambda item: (
            str(item.get("source_tier") or "") == "official",
            float(item.get("quality_score") or 0),
            float(item.get("confidence") or 0),
        ),
        reverse=True,
    )
    for fact in facts:
        domain = _fact_domain(fact)
        if not domain:
            continue
        key = (domain, str(fact.get("company") or ""), str(fact.get("metric") or ""))
        if key in seen:
            continue
        seen.add(key)
        domains[domain].append(
            {
                "company": fact.get("company") or "",
                "metric": fact.get("metric") or "",
                "analysis": fact.get("value") or fact.get("basis") or "",
                "basis": fact.get("basis") or "",
                "source_url": _first_source(fact),
                "source_tier": fact.get("source_tier") or "",
                "quality_score": round(float(fact.get("quality_score") or 0), 3),
                "confidence": round(float(fact.get("confidence") or 0), 3),
                "row_ref": fact.get("row_ref") or "",
                "evidence_hash": fact.get("evidence_hash") or "",
            }
        )

    for domain, items in domains.items():
        domains[domain] = items[:8]
    summary = curation_summary or {}
    return {
        "schema_version": 1,
        "generated_at_hkt": _now(),
        "agent_run_id": agent_run_id,
        "curation": {
            "accepted": int(summary.get("accepted") or 0),
            "rejected": int(summary.get("rejected") or 0),
            "review": int(summary.get("review") or 0),
            "gaps": int(summary.get("gaps") or 0),
        },
        "domain_counts": {key: len(value) for key, value in domains.items()},
        "domains": domains,
        "method": "仅使用本轮 Agent 发布层 accepted 且主体、指标、数值均受证据支持的事实；质量分低于0.85或无来源链接的事实不会进入领导看板。",
    }


def publish_ai_analysis(
    *,
    agent_run_id: str,
    verified_facts_path: Path = VERIFIED_FACTS_PATH,
    output_path: Path = AI_ANALYSIS_PATH,
    curation_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_ai_analysis(
        agent_run_id=agent_run_id,
        verified_facts_path=verified_facts_path,
        curation_summary=curation_summary,
    )
    previous = _read_json(output_path, {}) or {}
    if previous.get("model_analysis"):
        payload["model_analysis"] = previous["model_analysis"]
    comparable = {key: value for key, value in payload.items() if key != "generated_at_hkt"}
    old_comparable = {key: value for key, value in previous.items() if key != "generated_at_hkt"}
    changed = _content_hash(comparable) != _content_hash(old_comparable)
    if changed or not output_path.exists():
        _atomic_write_json(output_path, payload)
    return {"ok": True, "changed": changed, "path": str(output_path), **payload}


def publish_domain_fact_sidecars(
    analysis: dict[str, Any],
    *,
    output_paths: dict[str, Path] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish official Agent facts beside each primary database.

    These sidecars let newly crawled financial-report facts reach the domain
    database and frontend immediately without silently rewriting audited KPI
    rows. Only official-source facts are eligible; the primary tables continue
    to use their stricter schema-specific promotion gates.
    """
    paths = output_paths or DOMAIN_FACT_PATHS
    results: dict[str, Any] = {}
    for domain in ("local", "international", "cloud", "macro"):
        facts = [
            item for item in ((analysis.get("domains") or {}).get(domain) or [])
            if str(item.get("source_tier") or "").strip().lower() == "official"
            and str(item.get("source_url") or "").startswith(("https://", "http://"))
        ]
        payload = {
            "schema_version": 1,
            "domain": domain,
            "agent_run_id": analysis.get("agent_run_id") or "",
            "generated_at_hkt": analysis.get("generated_at_hkt") or _now(),
            "facts": facts,
            "method": (
                "每日爬虫经Agent审核后，仅将accepted、证据支持且source_tier=official的事实写入旁路库；"
                "旁路事实用于穿透分析，不直接覆盖主表KPI。"
            ),
        }
        path = paths[domain]
        previous = _read_json(path, {}) or {}
        comparable = {key: value for key, value in payload.items() if key != "generated_at_hkt"}
        old_comparable = {key: value for key, value in previous.items() if key != "generated_at_hkt"}
        changed = _content_hash(comparable) != _content_hash(old_comparable)
        if changed and not dry_run:
            _atomic_write_json(path, payload)
        results[domain] = {
            "path": str(path),
            "facts": len(facts),
            "changed": changed,
            "published": bool(changed and not dry_run),
        }
    return results


def _analysis_input_snapshot() -> dict[str, Any]:
    from executive_intelligence import build_executive_intelligence_evidence_snapshot

    # Rendered relations are intentionally excluded. The hash must move only
    # when source-backed facts or the deterministic evidence pack changes.
    return build_executive_intelligence_evidence_snapshot()


def _extract_json_payload(text: str) -> Any:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\[\s*\{.*\}\s*\])", cleaned, re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def _numeric_tokens(value: Any) -> set[str]:
    tokens = set()
    for token in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", json.dumps(value, ensure_ascii=False)):
        try:
            tokens.add(f"{float(token):g}")
        except ValueError:
            pass
    return tokens


def _focus_value_tokens(focus: dict[str, Any]) -> set[str]:
    """Return metric values only; periods, IDs and numbers embedded in labels do not count."""
    values: list[Any] = []
    metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
    if metric.get("value") not in (None, ""):
        values.append(metric.get("value"))
    for item in focus.get("items") or []:
        if not isinstance(item, dict):
            continue
        for key in ("value", "record_count", "component_count"):
            if item.get(key) not in (None, ""):
                values.append(item.get(key))
        for component in item.get("components") or []:
            if isinstance(component, dict) and component.get("value") not in (None, ""):
                values.append(component.get("value"))
    return _numeric_tokens(values)


_ANALYTICAL_JUDGEMENT_TERMS = (
    "领先", "落后", "高于", "低于", "最高", "最低", "差距", "距离", "变化", "增长",
    "下降", "回落", "改善", "加速", "放缓", "分化", "集中", "重叠", "梯度", "饱和",
    "压力", "风险", "机会", "空间", "优势", "短板", "不同", "差异", "相差", "居首",
    "覆盖", "完整", "充分", "不足", "多于", "少于", "强于", "弱于", "扩大", "收窄",
    "深度", "约束", "承压",
)
_BUSINESS_JUDGEMENT_TERMS = (
    "经营上", "业务上", "竞争上", "决策上", "意味着", "应", "需", "有利于", "不利于",
    "影响", "支撑", "制约", "对冲", "拖累", "转向", "优先", "转化", "变现", "提升",
    "降低", "客户流失", "获客", "留存", "资源配置", "投入回报", "竞争压力", "经营风险",
)


def _has_business_judgement(value: Any) -> bool:
    """Require both an analytical comparison and an explicit business implication."""
    text = str(value or "").strip()
    return (
        any(term in text for term in _ANALYTICAL_JUDGEMENT_TERMS)
        and any(term in text for term in _BUSINESS_JUDGEMENT_TERMS)
    )


def _focus_gate_error(domain: str, focus_id: str, analysis: str, evidence_focus: dict[str, Any]) -> str:
    terminal_marks = re.findall(r"[。！？!?]", analysis)
    if len(analysis) > MAX_FOCUS_INSIGHT_CHARS or len(terminal_marks) > 1 or (
        terminal_marks and not re.search(r"[。！？!?]$", analysis)
    ):
        return f"AI分析分类必须精炼为一句话：{domain}.{focus_id}；内容：{analysis[:180]}"
    focus_numbers = _focus_value_tokens(evidence_focus)
    analysis_numbers = _numeric_tokens(analysis)
    if focus_numbers and not (focus_numbers & analysis_numbers):
        return f"AI分析分类缺少输入数值判断：{domain}.{focus_id}；内容：{analysis[:180]}"
    if not _has_business_judgement(analysis):
        return f"AI分析分类缺少比较变化与业务判断：{domain}.{focus_id}；内容：{analysis[:180]}"
    restriction_phrases = (
        "缺失值不估算", "缺失数据不估算", "只比较已结构化", "仅比较已结构化",
        "用于判断", "用于识别", "用于展示", "展示可分析", "此处比较",
    )
    if any(phrase in analysis for phrase in restriction_phrases) and len(analysis_numbers) == 0:
        return f"AI分析分类仍以方法说明代替洞察：{domain}.{focus_id}；内容：{analysis[:180]}"
    return ""


def _repair_focus_numeric_anchors(raw: Any, evidence: dict[str, Any]) -> Any:
    """Keep genuine model judgement while anchoring it to an exact focus metric."""
    if not isinstance(raw, list):
        return raw
    evidence_by_focus = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }
    repaired = json.loads(json.dumps(raw, ensure_ascii=False))
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        for focus in domain.get("focuses") or []:
            if not isinstance(focus, dict):
                continue
            focus_id = str(focus.get("id") or "")
            evidence_focus = evidence_by_focus.get((domain_id, focus_id)) or {}
            analysis = str(focus.get("analysis") or "").strip()
            focus_numbers = _focus_value_tokens(evidence_focus)
            if not analysis or not focus_numbers or (_numeric_tokens(analysis) & focus_numbers):
                continue
            # Numeric anchoring is allowed only for model prose that already contains
            # a real comparison/change plus business implication; it cannot rescue filler.
            if not _has_business_judgement(analysis):
                continue
            metric = evidence_focus.get("metric") if isinstance(evidence_focus.get("metric"), dict) else {}
            value = metric.get("value")
            if value in (None, ""):
                continue
            label = str(metric.get("label") or "最新指标")
            unit = str(metric.get("unit") or "")
            focus["analysis"] = f"{label}为{value}{unit}；{analysis}"
            focus["numeric_anchor_repaired"] = True
    return repaired


def _repair_entity_evidence_labels(raw: Any, evidence: dict[str, Any]) -> Any:
    """Map harmless model paraphrases back to exact input labels; never create labels."""
    if not isinstance(raw, list):
        return raw
    evidence_entities = {
        (str(domain.get("id") or ""), str(focus.get("id") or ""), str(entity.get("name") or "")): entity
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
        for entity in focus.get("items") or []
    }
    repaired = json.loads(json.dumps(raw, ensure_ascii=False))
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        for focus in domain.get("focuses") or []:
            if not isinstance(focus, dict):
                continue
            focus_id = str(focus.get("id") or "")
            for entity in focus.get("entities") or []:
                if not isinstance(entity, dict):
                    continue
                evidence_entity = evidence_entities.get(
                    (domain_id, focus_id, str(entity.get("name") or ""))
                ) or {}
                allowed_labels = [
                    str(component.get("label") or "")
                    for component in evidence_entity.get("components") or []
                    if str(component.get("label") or "")
                ]
                if not allowed_labels:
                    continue
                mapped: list[str] = []
                for raw_label in entity.get("evidence_labels") or []:
                    label = str(raw_label or "")
                    if label in allowed_labels:
                        mapped.append(label)
                        continue
                    matches = difflib.get_close_matches(label, allowed_labels, n=1, cutoff=0.72)
                    if matches:
                        mapped.append(matches[0])
                entity["evidence_labels"] = list(dict.fromkeys(mapped))
                source_url = str(evidence_entity.get("source_url") or "")
                entity["source_urls"] = [source_url] if source_url and source_url in (entity.get("source_urls") or []) else []
    return repaired


def _repair_focus_business_implications(raw: Any, evidence: dict[str, Any]) -> Any:
    """Append a scoped decision implication only to numeric, analytical model prose."""
    if not isinstance(raw, list):
        return raw
    evidence_by_focus = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }
    repaired = json.loads(json.dumps(raw, ensure_ascii=False))
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        for focus in domain.get("focuses") or []:
            if not isinstance(focus, dict):
                continue
            focus_id = str(focus.get("id") or "")
            analysis = str(focus.get("analysis") or "").strip()
            evidence_focus = evidence_by_focus.get((domain_id, focus_id)) or {}
            if not analysis or _has_business_judgement(analysis):
                continue
            if not (_numeric_tokens(analysis) & _focus_value_tokens(evidence_focus)):
                continue
            if not any(term in analysis for term in _ANALYTICAL_JUDGEMENT_TERMS):
                continue
            implication = _FOCUS_BUSINESS_IMPLICATIONS.get((domain_id, focus_id), "")
            if implication:
                focus["analysis"] = f"{analysis.rstrip('。；')}；{implication}"
                focus["business_implication_repaired"] = True
    return repaired


def _repair_focus_conciseness(raw: Any, evidence: dict[str, Any]) -> Any:
    """Collapse each visible focus insight to one grounded decision sentence."""
    if not isinstance(raw, list):
        return raw
    evidence_by_focus = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }
    repaired = json.loads(json.dumps(raw, ensure_ascii=False))
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        for focus in domain.get("focuses") or []:
            if not isinstance(focus, dict):
                continue
            focus_id = str(focus.get("id") or "")
            evidence_focus = evidence_by_focus.get((domain_id, focus_id)) or {}
            original = str(focus.get("analysis") or "").strip()
            clauses = [item.strip(" ；;。！？!?") for item in re.split(r"[。！？!?\n]+", original) if item.strip()]
            numeric_clause = next(
                (item for item in clauses if _numeric_tokens(item) & _focus_value_tokens(evidence_focus)),
                "",
            )
            business_clause = next((item for item in clauses if _has_business_judgement(item)), "")
            merged = numeric_clause
            if business_clause and business_clause != numeric_clause:
                merged = f"{numeric_clause}；{business_clause}" if numeric_clause else business_clause
            candidate = merged.rstrip("；;。！？!?") + "。" if merged else ""
            if not _focus_gate_error(domain_id, focus_id, candidate, evidence_focus):
                focus["analysis"] = candidate
            else:
                focus["analysis"] = _compact_grounded_focus_analysis(domain_id, evidence_focus)
            if focus["analysis"] != original:
                focus["single_sentence_repaired"] = True
    return repaired


def _repair_model_summaries(raw: Any, evidence: dict[str, Any]) -> Any:
    repaired = _repair_focus_conciseness(
        _repair_entity_evidence_labels(
            _repair_focus_business_implications(
                _repair_focus_numeric_anchors(raw, evidence),
                evidence,
            ),
            evidence,
        ),
        evidence,
    )
    evidence_by_domain = {
        str(domain.get("id") or ""): domain for domain in evidence.get("domains") or []
    }
    if not isinstance(repaired, list):
        return repaired
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        evidence_domain = evidence_by_domain.get(domain_id) or {}
        focus_analyses = [
            str(focus.get("analysis") or "").strip()
            for focus in domain.get("focuses") or []
            if isinstance(focus, dict) and str(focus.get("analysis") or "").strip()
        ]
        if not str(domain.get("headline") or "").strip():
            domain["headline"] = f"{evidence_domain.get('title') or domain_id}竞争信号已形成量化判断"
        if not str(domain.get("analysis") or "").strip():
            domain["analysis"] = " ".join(focus_analyses[:2]) or str(
                evidence_domain.get("deterministic_insight") or "当前证据已完成量化校验。"
            )
        if not str(domain.get("risk") or "").strip():
            domain["risk"] = "仅基于当前已核验来源与披露口径；跨期间、代理分部和缺失值不作因果推断。"
        if not isinstance(domain.get("source_urls"), list):
            domain["source_urls"] = []
    return repaired


def _validate_model_summaries(raw: Any, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("AI分析没有返回JSON数组")
    expected = {"local", "international", "cloud", "macro"}
    allowed_numbers = _numeric_tokens(evidence)
    allowed_urls = {
        str(item.get("source_url") or "")
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
        for item in focus.get("items") or []
        if str(item.get("source_url") or "").startswith(("https://", "http://"))
    }
    allowed_urls.update(
        str(item.get("source_url") or "")
        for domain in evidence.get("domains") or []
        for item in domain.get("agent_verified_facts") or []
        if str(item.get("source_url") or "").startswith(("https://", "http://"))
    )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    evidence_by_domain = {
        str(domain.get("id") or ""): domain for domain in evidence.get("domains") or []
    }
    filler_phrases = ("按排名", "图中排序", "同一视图", "便于比较", "数据库内", "此视图", "不代表经营排名")
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("AI分析包含非对象条目")
        domain = str(item.get("domain") or "")
        if domain not in expected or domain in seen:
            raise ValueError(f"AI分析领域非法或重复：{domain}")
        seen.add(domain)
        summary = {
            "domain": domain,
            "headline": str(item.get("headline") or "").strip(),
            "analysis": str(item.get("analysis") or "").strip(),
            "risk": str(item.get("risk") or "").strip(),
            "source_urls": [str(url) for url in item.get("source_urls") or []],
            "focuses": [],
        }
        if not summary["headline"] or not summary["analysis"] or not summary["risk"]:
            raise ValueError(f"AI分析字段不完整：{domain}")
        unknown_urls = set(summary["source_urls"]) - allowed_urls
        if unknown_urls:
            raise ValueError(f"AI分析引用了输入之外的来源：{sorted(unknown_urls)}")
        unknown_numbers = _numeric_tokens(summary) - allowed_numbers
        if unknown_numbers:
            raise ValueError(f"AI分析出现输入之外的数字：{sorted(unknown_numbers)}")
        expected_focuses = {
            str(focus.get("id") or "")
            for focus in (evidence_by_domain.get(domain, {}).get("focuses") or [])
            if str(focus.get("id") or "")
        }
        raw_focuses = item.get("focuses") or []
        if expected_focuses:
            if not isinstance(raw_focuses, list):
                raise ValueError(f"AI分析分类总结格式非法：{domain}")
            focus_seen: set[str] = set()
            validated_focuses: list[dict[str, Any]] = []
            for focus_item in raw_focuses:
                if not isinstance(focus_item, dict):
                    raise ValueError(f"AI分析分类总结包含非对象条目：{domain}")
                focus_id = str(focus_item.get("id") or "")
                if focus_id not in expected_focuses or focus_id in focus_seen:
                    raise ValueError(f"AI分析分类非法或重复：{domain}.{focus_id}")
                focus_seen.add(focus_id)
                validated_focus = {
                    "id": focus_id,
                    "analysis": str(focus_item.get("analysis") or "").strip(),
                    "risk": str(focus_item.get("risk") or "").strip(),
                    "source_urls": [str(url) for url in focus_item.get("source_urls") or []],
                    "entities": [],
                }
                if not validated_focus["analysis"] or not validated_focus["risk"]:
                    raise ValueError(f"AI分析分类字段不完整：{domain}.{focus_id}")
                unknown_focus_urls = set(validated_focus["source_urls"]) - allowed_urls
                if unknown_focus_urls:
                    raise ValueError(f"AI分析分类引用了输入之外的来源：{sorted(unknown_focus_urls)}")
                unknown_focus_numbers = _numeric_tokens(validated_focus) - allowed_numbers
                if unknown_focus_numbers:
                    raise ValueError(f"AI分析分类出现输入之外的数字：{sorted(unknown_focus_numbers)}")
                evidence_focus = next(
                    focus for focus in (evidence_by_domain.get(domain, {}).get("focuses") or [])
                    if str(focus.get("id") or "") == focus_id
                )
                focus_gate_error = _focus_gate_error(
                    domain,
                    focus_id,
                    validated_focus["analysis"],
                    evidence_focus,
                )
                if focus_gate_error:
                    raise ValueError(focus_gate_error)
                evidence_entities = {
                    str(entity.get("name") or ""): entity
                    for entity in evidence_focus.get("items") or []
                    if str(entity.get("name") or "")
                }
                raw_entities = focus_item.get("entities") or []
                if not isinstance(raw_entities, list):
                    raise ValueError(f"AI分析实体总结格式非法：{domain}.{focus_id}")
                entity_seen: set[str] = set()
                for raw_entity in raw_entities:
                    if not isinstance(raw_entity, dict):
                        raise ValueError(f"AI分析实体总结包含非对象条目：{domain}.{focus_id}")
                    name = str(raw_entity.get("name") or "").strip()
                    if name not in evidence_entities or name in entity_seen:
                        raise ValueError(f"AI分析实体非法或重复：{domain}.{focus_id}.{name}")
                    entity_seen.add(name)
                    entity_summary = {
                        "name": name,
                        "headline": str(raw_entity.get("headline") or "").strip(),
                        "analysis": str(raw_entity.get("analysis") or "").strip(),
                        "risk": str(raw_entity.get("risk") or "").strip(),
                        "evidence_labels": [str(label) for label in raw_entity.get("evidence_labels") or []],
                        "source_urls": [str(url) for url in raw_entity.get("source_urls") or []],
                    }
                    if not entity_summary["headline"] or not entity_summary["analysis"] or not entity_summary["risk"]:
                        raise ValueError(f"AI分析实体字段不完整：{domain}.{focus_id}.{name}")
                    if any(phrase in entity_summary["analysis"] for phrase in filler_phrases):
                        raise ValueError(f"AI分析实体仍含界面废话：{domain}.{focus_id}.{name}")
                    allowed_labels = {
                        str(component.get("label") or "")
                        for component in evidence_entities[name].get("components") or []
                        if str(component.get("label") or "")
                    }
                    if allowed_labels and not entity_summary["evidence_labels"]:
                        raise ValueError(f"AI分析实体未引用组成明细：{domain}.{focus_id}.{name}")
                    unknown_labels = set(entity_summary["evidence_labels"]) - allowed_labels
                    if unknown_labels:
                        raise ValueError(f"AI分析实体引用未知明细：{domain}.{focus_id}.{name}.{sorted(unknown_labels)}")
                    entity_allowed_urls = {
                        str(evidence_entities[name].get("source_url") or "")
                    } - {""}
                    unknown_entity_urls = set(entity_summary["source_urls"]) - entity_allowed_urls
                    if unknown_entity_urls:
                        raise ValueError(f"AI分析实体引用了输入之外的来源：{sorted(unknown_entity_urls)}")
                    unknown_entity_numbers = _numeric_tokens(entity_summary) - _numeric_tokens(evidence_entities[name])
                    if unknown_entity_numbers:
                        raise ValueError(
                            f"AI分析实体出现输入之外的数字：{domain}.{focus_id}.{name}.{sorted(unknown_entity_numbers)}"
                        )
                    validated_focus["entities"].append(entity_summary)
                if entity_seen != set(evidence_entities):
                    raise ValueError(
                        f"AI分析实体不完整：{domain}.{focus_id}.{sorted(set(evidence_entities) - entity_seen)}"
                    )
                validated_focuses.append(validated_focus)
            if focus_seen != expected_focuses:
                raise ValueError(f"AI分析分类不完整：{domain}.{sorted(expected_focuses - focus_seen)}")
            summary["focuses"] = validated_focuses
        result.append(summary)
    if seen != expected:
        raise ValueError(f"AI分析领域不完整：{sorted(expected - seen)}")
    return sorted(result, key=lambda item: ("local", "international", "cloud", "macro").index(item["domain"]))


def _evidence_urls_by_domain(evidence: dict[str, Any]) -> dict[str, set[str]]:
    urls: dict[str, set[str]] = {key: set() for key in ("local", "international", "cloud", "macro")}
    for domain in evidence.get("domains") or []:
        domain_id = str(domain.get("id") or "")
        if domain_id not in urls:
            continue
        for focus in domain.get("focuses") or []:
            for item in focus.get("items") or []:
                source_url = str(item.get("source_url") or "")
                if source_url.startswith(("https://", "http://")):
                    urls[domain_id].add(source_url)
        for item in domain.get("agent_verified_facts") or []:
            source_url = str(item.get("source_url") or "")
            if source_url.startswith(("https://", "http://")):
                urls[domain_id].add(source_url)
    return urls


def _validate_model_discoveries(raw: Any, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError("AI跨库发现必须恰好返回四项")
    expected_domains = {"local", "international", "cloud", "macro"}
    allowed_numbers = _numeric_tokens(evidence)
    urls_by_domain = _evidence_urls_by_domain(evidence)
    allowed_urls = set().union(*urls_by_domain.values())
    result: list[dict[str, Any]] = []
    pairs: set[tuple[str, str]] = set()
    covered_domains: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("AI跨库发现包含非对象条目")
        source_domain = str(item.get("from") or "")
        target_domain = str(item.get("to") or "")
        if source_domain not in expected_domains or target_domain not in expected_domains or source_domain == target_domain:
            raise ValueError(f"AI跨库发现领域非法：{source_domain}->{target_domain}")
        pair = tuple(sorted((source_domain, target_domain)))
        if pair in pairs:
            raise ValueError(f"AI跨库发现重复关联：{pair}")
        pairs.add(pair)
        covered_domains.update(pair)
        discovery = {
            "from": source_domain,
            "to": target_domain,
            "title": str(item.get("title") or "").strip(),
            "detail": str(item.get("detail") or "").strip(),
            "kind": str(item.get("kind") or "AI综合研判").strip(),
            "source_urls": list(dict.fromkeys(str(url) for url in item.get("source_urls") or [])),
        }
        if not discovery["title"] or not discovery["detail"]:
            raise ValueError("AI跨库发现标题或结论为空")
        if len(discovery["title"]) > 28 or len(discovery["detail"]) > 110 or len(discovery["kind"]) > 12:
            raise ValueError("AI跨库发现不够精炼")
        unknown_urls = set(discovery["source_urls"]) - allowed_urls
        if unknown_urls:
            raise ValueError(f"AI跨库发现引用了输入之外的来源：{sorted(unknown_urls)}")
        for domain_id in pair:
            if urls_by_domain[domain_id] and not (set(discovery["source_urls"]) & urls_by_domain[domain_id]):
                raise ValueError(f"AI跨库发现缺少{domain_id}领域来源")
        unknown_numbers = _numeric_tokens(discovery) - allowed_numbers
        if unknown_numbers:
            raise ValueError(f"AI跨库发现出现输入之外的数字：{sorted(unknown_numbers)}")
        result.append(discovery)
    if covered_domains != expected_domains:
        raise ValueError(f"AI跨库发现领域覆盖不完整：{sorted(expected_domains - covered_domains)}")
    return result


def _drop_unsupported_numeric_clauses(raw: Any, evidence: dict[str, Any]) -> Any:
    if not isinstance(raw, list):
        return raw
    allowed_numbers = _numeric_tokens(evidence)
    allowed_urls = {
        str(item.get("source_url") or "")
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
        for item in focus.get("items") or []
        if str(item.get("source_url") or "").startswith(("https://", "http://"))
    }
    allowed_urls.update(
        str(item.get("source_url") or "")
        for domain in evidence.get("domains") or []
        for item in domain.get("agent_verified_facts") or []
        if str(item.get("source_url") or "").startswith(("https://", "http://"))
    )
    evidence_entities = {
        (
            str(domain.get("id") or ""),
            str(focus.get("id") or ""),
            str(entity.get("name") or ""),
        ): entity
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
        for entity in focus.get("items") or []
    }
    sanitized: list[Any] = []
    for item in raw:
        if not isinstance(item, dict):
            sanitized.append(item)
            continue
        cleaned = dict(item)
        cleaned["source_urls"] = [
            str(url) for url in cleaned.get("source_urls") or [] if str(url) in allowed_urls
        ]
        removed = 0
        for field in ("headline", "analysis", "risk"):
            text = str(cleaned.get(field) or "")
            clauses = re.split(r"(?<=[。；;])", text)
            kept: list[str] = []
            for clause in clauses:
                if _numeric_tokens(clause) - allowed_numbers:
                    removed += 1
                    continue
                kept.append(clause)
            cleaned[field] = "".join(kept).strip()
        cleaned_focuses: list[Any] = []
        for focus in cleaned.get("focuses") or []:
            if not isinstance(focus, dict):
                cleaned_focuses.append(focus)
                continue
            cleaned_focus = dict(focus)
            cleaned_focus["source_urls"] = [
                str(url) for url in cleaned_focus.get("source_urls") or [] if str(url) in allowed_urls
            ]
            for field in ("analysis", "risk"):
                text = str(cleaned_focus.get(field) or "")
                clauses = re.split(r"(?<=[。；;])", text)
                kept = []
                for clause in clauses:
                    if _numeric_tokens(clause) - allowed_numbers:
                        removed += 1
                        continue
                    kept.append(clause)
                cleaned_focus[field] = "".join(kept).strip()
                if not cleaned_focus[field]:
                    cleaned_focus[field] = str(cleaned.get(field) or "").strip()
            cleaned_entities: list[Any] = []
            for entity in cleaned_focus.get("entities") or []:
                if not isinstance(entity, dict):
                    cleaned_entities.append(entity)
                    continue
                cleaned_entity = dict(entity)
                entity_evidence = evidence_entities.get((
                    str(cleaned.get("domain") or ""),
                    str(cleaned_focus.get("id") or ""),
                    str(cleaned_entity.get("name") or ""),
                ), {})
                entity_allowed_urls = {str(entity_evidence.get("source_url") or "")} - {""}
                cleaned_entity["source_urls"] = [
                    str(url)
                    for url in cleaned_entity.get("source_urls") or []
                    if str(url) in entity_allowed_urls
                ]
                for field in ("headline", "analysis", "risk"):
                    text = str(cleaned_entity.get(field) or "")
                    clauses = re.split(r"(?<=[。；;])", text)
                    kept = []
                    entity_allowed_numbers = _numeric_tokens(entity_evidence)
                    for clause in clauses:
                        if _numeric_tokens(clause) - entity_allowed_numbers:
                            removed += 1
                            continue
                        kept.append(clause)
                    cleaned_entity[field] = "".join(kept).strip()
                cleaned_entity["analysis"] = re.sub(
                    r"(?i)components\s*具体包含[:：]?", "具体包含：", cleaned_entity["analysis"]
                )
                if not cleaned_entity["headline"]:
                    cleaned_entity["headline"] = f"{cleaned_entity.get('name') or '该对象'}结构已更新"
                if not cleaned_entity["analysis"]:
                    cleaned_entity["analysis"] = str(
                        entity_evidence.get("analysis") or entity_evidence.get("detail") or "当前没有足够明细形成判断。"
                    )
                if not cleaned_entity["risk"]:
                    cleaned_entity["risk"] = "缺失、重复或异口径记录不作推算。"
                cleaned_entities.append(cleaned_entity)
            if "entities" in cleaned_focus:
                cleaned_focus["entities"] = cleaned_entities
            cleaned_focuses.append(cleaned_focus)
        if "focuses" in cleaned:
            cleaned["focuses"] = cleaned_focuses
        if removed:
            cleaned["sanitized_clauses"] = removed
        sanitized.append(cleaned)
    return sanitized


_FOCUS_BUSINESS_IMPLICATIONS = {
    ("local", "scale"): "方案差异扩大，需优先验证产品广度能否转化为获客。",
    ("local", "track"): "赛道覆盖分化，竞争上应优先补齐高价值场景。",
    ("local", "price"): "价格梯度明显，定价应兼顾低价获客与主产品价值。",
    ("local", "overlap"): "赛道重叠集中，应以差异化权益降低价格压力。",
    ("international", "growth"): "增长分化，需优先复制领先者的有效收入结构。",
    ("international", "momentum"): "动量回落，经营上应验证收入修复能否持续。",
    ("international", "gap"): "增速差距扩大，应优先锁定可修复竞争位置的业务。",
    ("international", "disclosure"): "披露深度分化，应优先采用可交叉验证指标。",
    ("cloud", "growth"): "增长梯队分化，竞争上应兼顾规模与收入质量。",
    ("cloud", "trend"): "增速变化分化，应验证动量能否转化为份额与黏性。",
    ("cloud", "profit"): "利润率差距扩大，经营上应同时校验规模变现与口径。",
    ("cloud", "disclosure"): "披露深度分化，应区分纯云、代理分部与综合口径。",
    ("macro", "market"): "市场趋于饱和，经营上应转向存量客户价值提升。",
    ("macro", "traffic"): "流量需求分化，应优先评估体验投入的套餐转化。",
    ("macro", "spending"): "消费能力分化，定价应兼顾购买力与价值提升。",
    ("macro", "governance"): "投资与体验约束并存，应优先降低服务风险。",
}


def _compact_grounded_focus_analysis(domain: str, focus: dict[str, Any]) -> str:
    focus_id = str(focus.get("id") or "")
    implication = _FOCUS_BUSINESS_IMPLICATIONS.get(
        (domain, focus_id),
        "竞争位置出现变化，业务上应优先评估收入与客户影响。",
    )
    if (domain, focus_id) == ("local", "price"):
        ranked: list[tuple[float, str, Any]] = []
        for item in focus.get("items") or []:
            try:
                numeric = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            ranked.append((numeric, str(item.get("name") or "品牌"), item.get("value")))
        if ranked:
            low = min(ranked)
            high = max(ranked)
            gap = high[0] - low[0]
            gap_text = str(int(gap)) if gap.is_integer() else f"{gap:g}"
            unit = str((focus.get("metric") or {}).get("unit") or "港元/月")
            return f"{low[1]}最低{low[2]}{unit}、{high[1]}最高{high[2]}{unit}，相差{gap_text}{unit}；定价应兼顾低价获客与主产品价值。"
    metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
    value = metric.get("value")
    label = str(metric.get("label") or focus.get("title") or "最新指标")
    unit = str(metric.get("unit") or "")
    if value not in (None, ""):
        return f"{label}{value}{unit}；{implication.rstrip('。')}。"
    numbers = sorted(_focus_value_tokens(focus), key=lambda item: float(item))
    anchor = numbers[0] if numbers else ""
    return f"当前值{anchor}；{implication.rstrip('。')}。" if anchor else implication


def _deterministic_focus_analysis(domain: str, focus: dict[str, Any]) -> str:
    """Produce a numerically grounded fallback that must pass the same 16-focus gate."""
    return _compact_grounded_focus_analysis(domain, focus)


def _deterministic_domain_summaries(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a fail-closed summary directly from the validated evidence pack."""
    summaries: list[dict[str, Any]] = []
    for domain in evidence.get("domains") or []:
        sources = [
            str(item.get("source_url") or "")
            for focus in domain.get("focuses") or []
            for item in focus.get("items") or []
            if str(item.get("source_url") or "").startswith(("https://", "http://"))
        ]
        summaries.append(
            {
                "domain": str(domain.get("id") or ""),
                "headline": f"{domain.get('title') or '该领域'}最新证据已更新",
                "analysis": str(domain.get("deterministic_insight") or "当前仅展示已通过发布门禁的证据。"),
                "risk": "仅基于当前已核验来源和已披露口径；缺失数据不估算，跨期间与代理口径不作因果推断。",
                "source_urls": list(dict.fromkeys(sources))[:3],
                "focuses": [
                    {
                        "id": str(focus.get("id") or ""),
                        "analysis": _deterministic_focus_analysis(
                            str(domain.get("id") or ""),
                            focus,
                        ),
                        "risk": "仅基于当前已核验来源和已披露口径，缺失数据不估算。",
                        "source_urls": list(dict.fromkeys(
                            str(item.get("source_url") or "")
                            for item in focus.get("items") or []
                            if str(item.get("source_url") or "").startswith(("https://", "http://"))
                        ))[:3],
                        "entities": [
                            {
                                "name": str(entity.get("name") or ""),
                                "headline": f"{entity.get('name') or '该对象'}明细已核验",
                                "analysis": str(entity.get("analysis") or entity.get("detail") or "当前没有足够明细形成判断。"),
                                "risk": "仅基于当前结构化明细；缺失、重复或异口径记录不作推算。",
                                "evidence_labels": [
                                    str(component.get("label") or "")
                                    for component in entity.get("components") or []
                                    if str(component.get("label") or "")
                                ][:6],
                                "source_urls": [str(entity.get("source_url") or "")]
                                if str(entity.get("source_url") or "").startswith(("https://", "http://")) else [],
                            }
                            for entity in focus.get("items") or []
                            if str(entity.get("name") or "")
                        ],
                    }
                    for focus in domain.get("focuses") or []
                    if str(focus.get("id") or "")
                ],
            }
        )
    return _validate_model_summaries(summaries, evidence)


def _deterministic_discoveries(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    urls_by_domain = _evidence_urls_by_domain(evidence)
    relations = list(evidence.get("relations") or [])[:4]
    fallback_pairs = (
        ("macro", "local", "市场底盘与本地产品竞争联动", "市场底盘与本地产品供给需放在同一视图持续观察。"),
        ("international", "cloud", "运营商与云厂商增长节奏分化", "运营商与云厂商的最新披露显示不同增长节奏，需按原始口径对照。"),
        ("local", "cloud", "连接产品与云服务竞争面重叠", "本地连接产品与云服务正在形成可联合观察的企业市场竞争面。"),
        ("macro", "international", "投资与增长转化共同承压", "市场投资、网络覆盖与运营商增长需联合观察转化效率。"),
    )
    while len(relations) < 4:
        source_domain, target_domain, title, detail = fallback_pairs[len(relations)]
        relations.append({
            "from": source_domain,
            "to": target_domain,
            "title": title,
            "detail": detail,
            "kind": "证据规则回退",
        })
    discoveries: list[dict[str, Any]] = []
    for relation in relations:
        source_domain = str(relation.get("from") or "")
        target_domain = str(relation.get("to") or "")
        source_urls = []
        for domain_id in (source_domain, target_domain):
            if urls_by_domain.get(domain_id):
                source_urls.append(sorted(urls_by_domain[domain_id])[0])
        discoveries.append({
            "from": source_domain,
            "to": target_domain,
            "title": str(relation.get("title") or ""),
            "detail": str(relation.get("detail") or ""),
            "kind": "证据规则回退",
            "source_urls": source_urls,
        })
    return _validate_model_discoveries(discoveries, evidence)


def generate_model_domain_summaries(evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot
    from network_utils import urlopen_with_local_proxy_fallback

    evidence = evidence or _analysis_input_snapshot()
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置内网模型密钥")
    system_prompt = (
        "你是电信竞争情报分析员。只能使用输入JSON里的事实、数字、期间、口径和来源，不得补充常识数字或猜测。"
        "每个领域给出一句headline、一段analysis和一句risk；为每个focus给出analysis、risk；"
        "并为每个focus中的每个实体逐一给出headline、analysis、risk、evidence_labels和source_urls。"
        "实体analysis必须先说清具体包含哪些组成明细，再指出结构、集中度、变化或差距及其业务含义；"
        "evidence_labels必须从该实体components的label中原样选择，不能编造。所有focus和实体必须逐一覆盖，不能遗漏、合并或新增。"
        "禁止写按排名、图中排序、同一视图、便于比较、数据库内、此视图、不代表经营排名等界面说明或空话。"
        "每个focus的analysis必须压缩为不超过88个字符的一句话，只引用至少一个输入具体数值，并说明差距、梯度、集中度或变化带来的业务判断；"
        "上述数值与业务判断要求适用于全部16个focus，任何focus只写指标定义、展示方法或事实罗列都不合格；"
        "每个focus必须同时写出可量化的比较/变化结论，以及它对收入、客户、产品、网络、竞争或资源投入的含义。"
        "local.price必须明确写出品牌月费中位数的最低值、最高值和至少一个价格差距，不能把‘缺失值不估算’当作结论。"
        "跨期间、代理分部、披露缺口必须明确写入risk；"
        "不得把相关性写成因果。不得从URL文件名推断日期，也不得把FY财年自行转换成具体月日。"
        "source_urls只能从输入中原样选择。只返回JSON数组。"
    )
    user_prompt = (
        "请分析 local、international、cloud、macro 四个领域。每项字段严格为"
        "domain, headline, analysis, risk, source_urls, focuses；focuses每项字段严格为"
        "id, analysis, risk, source_urls, entities；entities每项字段严格为"
        "name, headline, analysis, risk, evidence_labels, source_urls。不要Markdown。输入：\n"
        + json.dumps(evidence, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    body = {
        "model": str(config.get("model") or "deepseek-v4"),
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 16000,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    summaries: list[dict[str, Any]] | None = None
    last_error: Exception | None = None
    used_models: set[str] = set()
    entity_count = sum(
        len(focus.get("items") or [])
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    )
    # Large all-domain payloads can exceed the internal gateway response window.
    # Split them by domain immediately; each response remains independently gated.
    primary_attempts = 0 if entity_count > 40 else 3
    for attempt in range(primary_attempts):
        body["messages"] = messages
        request = urllib.request.Request(
            f"{str(config.get('base_url') or INTERNAL_AI_BASE_URL).rstrip('/')}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        wait_for_internal_ai_slot("executive-intelligence-analysis")
        try:
            with urlopen_with_local_proxy_fallback(request, timeout=180) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:800]
            raise RuntimeError(f"内网模型 HTTP {exc.code}: {detail}") from exc
        message = (payload.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or message.get("reasoning_content") or ""
        try:
            raw_summaries = _extract_json_payload(content)
            summaries = _validate_model_summaries(
                _repair_model_summaries(
                    _drop_unsupported_numeric_clauses(raw_summaries, evidence),
                    evidence,
                ),
                evidence,
            )
            used_models.add(str(body["model"]))
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < primary_attempts:
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                f"上一版未通过事实门禁：{exc}。请删除或改写所有未获输入支持的数字/来源，"
                                "保持四个领域、全部focus和全部实体完整并重新只返回JSON数组。"
                            ),
                        },
                    ]
                )
    if summaries is None:
        # Older model deployments sometimes follow the four-domain shape but omit
        # nested focus summaries. Retry one domain at a time so every focus can be
        # checked explicitly without asking the model to hold all 16 views at once.
        per_domain_summaries: list[dict[str, Any]] = []
        for domain_evidence in evidence.get("domains") or []:
            domain_id = str(domain_evidence.get("id") or "")
            expected_focus_ids = {
                str(focus.get("id") or "")
                for focus in domain_evidence.get("focuses") or []
                if str(focus.get("id") or "")
            }
            domain_messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"只分析 {domain_id} 这一个领域，返回只含一个对象的JSON数组。"
                        "必须逐一返回输入中的全部focus id及其全部实体。字段协议不变。输入：\n"
                        + json.dumps({"domains": [domain_evidence]}, ensure_ascii=False)
                    ),
                },
            ]
            domain_summary: dict[str, Any] | None = None
            domain_error: Exception | None = None
            for domain_attempt in range(3):
                request = urllib.request.Request(
                    f"{str(config.get('base_url') or INTERNAL_AI_BASE_URL).rstrip('/')}/chat/completions",
                    data=json.dumps({**body, "messages": domain_messages}, ensure_ascii=False).encode("utf-8"),
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    method="POST",
                )
                wait_for_internal_ai_slot(f"executive-intelligence-analysis-{domain_id}")
                try:
                    with urlopen_with_local_proxy_fallback(request, timeout=180) as response:
                        domain_payload = json.loads(response.read().decode("utf-8"))
                    domain_message = (domain_payload.get("choices") or [{}])[0].get("message") or {}
                    domain_content = domain_message.get("content") or domain_message.get("reasoning_content") or ""
                    parsed = _extract_json_payload(domain_content)
                    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
                        raise ValueError("必须返回单对象JSON数组")
                    candidate = _drop_unsupported_numeric_clauses(
                        [parsed[0]],
                        {"domains": [domain_evidence]},
                    )
                    candidate = _repair_model_summaries(
                        candidate,
                        {"domains": [domain_evidence]},
                    )[0]
                    returned_focus_ids = {
                        str(focus.get("id") or "")
                        for focus in candidate.get("focuses") or []
                        if isinstance(focus, dict)
                    }
                    if not expected_focus_ids.issubset(returned_focus_ids):
                        raise ValueError(f"分类覆盖不完整：{sorted(expected_focus_ids - returned_focus_ids)}")
                    returned_by_focus = {
                        str(focus.get("id") or ""): {
                            str(entity.get("name") or "") for entity in focus.get("entities") or []
                            if isinstance(entity, dict) and str(entity.get("name") or "")
                        }
                        for focus in candidate.get("focuses") or [] if isinstance(focus, dict)
                    }
                    for evidence_focus in domain_evidence.get("focuses") or []:
                        focus_id = str(evidence_focus.get("id") or "")
                        expected_names = {
                            str(entity.get("name") or "") for entity in evidence_focus.get("items") or []
                            if str(entity.get("name") or "")
                        }
                        if returned_by_focus.get(focus_id, set()) != expected_names:
                            raise ValueError(f"实体覆盖不完整：{focus_id}")
                        returned_focus = next(
                            focus for focus in candidate.get("focuses") or []
                            if isinstance(focus, dict) and str(focus.get("id") or "") == focus_id
                        )
                        focus_gate_error = _focus_gate_error(
                            domain_id,
                            focus_id,
                            str(returned_focus.get("analysis") or ""),
                            evidence_focus,
                        )
                        if focus_gate_error:
                            raise ValueError(focus_gate_error)
                    candidate["domain"] = domain_id
                    candidate["focuses"] = [
                        focus for focus in candidate.get("focuses") or []
                        if isinstance(focus, dict) and str(focus.get("id") or "") in expected_focus_ids
                    ]
                    domain_summary = candidate
                    used_models.add(str(body["model"]))
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    domain_error = exc
                    if domain_attempt < 2:
                        domain_messages.append({
                            "role": "user",
                            "content": (
                                f"上一版未通过门禁：{exc}。请完整返回全部focus和全部实体。"
                                "每个focus.analysis只用一句话：引用输入原值、写比较/变化并明确对收入、客户、产品、"
                                "网络、竞争或资源投入的业务含义，总长不超过88个字符；不要只解释指标用途。仍只返回单对象JSON数组。"
                            ),
                        })
            if domain_summary is None:
                focus_parts: list[dict[str, Any]] = []
                domain_fields: dict[str, Any] | None = None
                for focus_evidence in domain_evidence.get("focuses") or []:
                    focus_id = str(focus_evidence.get("id") or "")
                    expected_names = {
                        str(entity.get("name") or "") for entity in focus_evidence.get("items") or []
                        if str(entity.get("name") or "")
                    }
                    focus_messages = [
                        {
                            "role": "system",
                            "content": (
                                "你是电信竞争情报分析员。只返回合法JSON数组，不要解释。只能使用输入证据。"
                                "逐一覆盖items中的全部实体，name必须原样；每个实体先说明components具体包含什么，"
                                "再写结构、变化或差距及业务含义。evidence_labels只能原样选自该实体components.label。"
                                "focus.analysis必须用不超过88个字符的一句话引用输入具体数值、写明比较或变化并解释经营影响。"
                                "禁止写按排名、图中排序、同一视图、便于比较、数据库内、此视图等界面说明。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"只分析 {domain_id}.{focus_id} 这一个分类，返回只含一个领域对象、一个focus的JSON数组。"
                                f"实体name必须完整且原样等于：{json.dumps(sorted(expected_names), ensure_ascii=False)}。"
                                "固定结构为：[{domain,headline,analysis,risk,source_urls,focuses:[{id,analysis,risk,"
                                "source_urls,entities:[{name,headline,analysis,risk,evidence_labels,source_urls}]}]}]。输入：\n"
                                + json.dumps({"domains": [{**domain_evidence, "focuses": [focus_evidence]}]}, ensure_ascii=False)
                            ),
                        },
                    ]
                    focus_candidate: dict[str, Any] | None = None
                    focus_error: Exception | None = None
                    configured_model = str(body["model"])
                    focus_models = list(dict.fromkeys(["Qwen3-30B-A3B-Instruct-2507", "GLM", configured_model]))
                    for focus_attempt, focus_model in enumerate(focus_models):
                        request = urllib.request.Request(
                            f"{str(config.get('base_url') or INTERNAL_AI_BASE_URL).rstrip('/')}/chat/completions",
                            data=json.dumps({**body, "model": focus_model, "messages": focus_messages}, ensure_ascii=False).encode("utf-8"),
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                            method="POST",
                        )
                        wait_for_internal_ai_slot(f"executive-intelligence-analysis-{domain_id}-{focus_id}")
                        try:
                            with urlopen_with_local_proxy_fallback(request, timeout=180) as response:
                                focus_payload = json.loads(response.read().decode("utf-8"))
                            focus_message = (focus_payload.get("choices") or [{}])[0].get("message") or {}
                            focus_content = focus_message.get("content") or focus_message.get("reasoning_content") or ""
                            parsed = _extract_json_payload(focus_content)
                            if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
                                raise ValueError("必须返回单对象JSON数组")
                            candidate = _drop_unsupported_numeric_clauses(
                                [parsed[0]],
                                {"domains": [{**domain_evidence, "focuses": [focus_evidence]}]},
                            )
                            candidate = _repair_model_summaries(
                                candidate,
                                {"domains": [{**domain_evidence, "focuses": [focus_evidence]}]},
                            )[0]
                            returned_focuses = [
                                focus for focus in candidate.get("focuses") or []
                                if isinstance(focus, dict) and str(focus.get("id") or "") == focus_id
                            ]
                            if len(returned_focuses) != 1:
                                raise ValueError(f"必须只返回分类 {focus_id}")
                            returned_names = {
                                str(entity.get("name") or "") for entity in returned_focuses[0].get("entities") or []
                                if isinstance(entity, dict) and str(entity.get("name") or "")
                            }
                            if returned_names != expected_names:
                                raise ValueError(f"实体覆盖不完整：{sorted(expected_names - returned_names)}")
                            focus_gate_error = _focus_gate_error(
                                domain_id,
                                focus_id,
                                str(returned_focuses[0].get("analysis") or ""),
                                focus_evidence,
                            )
                            if focus_gate_error:
                                raise ValueError(focus_gate_error)
                            focus_candidate = candidate
                            focus_candidate["domain"] = domain_id
                            focus_candidate["focuses"] = returned_focuses
                            used_models.add(focus_model)
                            break
                        except (ValueError, json.JSONDecodeError) as exc:
                            focus_error = exc
                            if focus_attempt + 1 < len(focus_models):
                                focus_messages.append({
                                    "role": "user",
                                    "content": (
                                        f"上一版未通过门禁：{exc}。请只返回该focus及全部实体。"
                                        "focus.analysis必须用不超过88个字符的一句话引用输入原值、写比较或变化，并明确收入、客户、"
                                        "产品、网络、竞争或资源投入含义，不能写成指标定义。只返回合法JSON数组。"
                                    ),
                                })
                    if focus_candidate is None:
                        raise ValueError(
                            f"AI分析按分类重试仍未通过：{domain_id}.{focus_id}: {focus_error}; 领域错误：{domain_error}"
                        )
                    if domain_fields is None:
                        domain_fields = {
                            key: focus_candidate.get(key)
                            for key in ("domain", "headline", "analysis", "risk", "source_urls")
                        }
                    focus_parts.extend(focus_candidate["focuses"])
                domain_summary = {**(domain_fields or {"domain": domain_id}), "focuses": focus_parts}
            per_domain_summaries.append(domain_summary)
        summaries = _validate_model_summaries(
            _repair_model_summaries(
                _drop_unsupported_numeric_clauses(per_domain_summaries, evidence),
                evidence,
            ),
            evidence,
        )
    return {
        "generated_at_hkt": _now(),
        "model": "+".join(sorted(used_models)) if used_models else str(body["model"]),
        "summaries": summaries,
    }


def _compact_discovery_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep decision-level metrics and sources; omit entity/component payloads."""
    domains: list[dict[str, Any]] = []
    for domain in evidence.get("domains") or []:
        compact_focuses: list[dict[str, Any]] = []
        for focus in domain.get("focuses") or []:
            compact_focuses.append({
                "id": focus.get("id"),
                "title": focus.get("title"),
                "metric": focus.get("metric"),
                "insight": focus.get("insight"),
                "items": [
                    {
                        "name": item.get("name"),
                        "value": item.get("value"),
                        "unit": item.get("unit"),
                        "source_url": item.get("source_url"),
                    }
                    for item in (focus.get("items") or [])[:4]
                    if isinstance(item, dict)
                ],
            })
        domains.append({
            "id": domain.get("id"),
            "title": domain.get("title"),
            "deterministic_insight": domain.get("deterministic_insight"),
            "focuses": compact_focuses,
        })
    return {"domains": domains, "relations": list(evidence.get("relations") or [])[:4]}


def generate_model_discoveries(evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot
    from network_utils import urlopen_with_local_proxy_fallback

    evidence = evidence or _analysis_input_snapshot()
    prompt_evidence = _compact_discovery_evidence(evidence)
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置内网模型密钥")
    system_prompt = (
        "你是电信竞争情报分析员。从local、international、cloud、macro四库证据中提炼恰好四条跨库发现。"
        "每条必须联系两个不同领域，四条不得重复同一领域组合，且四个领域都要被覆盖。"
        "不要逐库摘要，不要写论文，标题是一句可决策结论，detail只补一句核心根据。"
        "只能使用输入JSON里的事实、数字、期间、口径和来源；不得新增数字、伪造因果或从URL推断信息。"
        "source_urls必须分别包含两个领域在输入中原样提供的来源。只返回JSON数组。"
    )
    user_prompt = (
        "请返回四条发现，每项字段严格为from,to,title,detail,kind,source_urls。"
        "title不超过28字，detail不超过110字，kind统一写AI综合研判。不要Markdown。输入：\n"
        + json.dumps(prompt_evidence, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    body = {
        "model": str(config.get("model") or "deepseek-v4"),
        "messages": messages,
        "temperature": 0.0,
    }
    discoveries: list[dict[str, Any]] | None = None
    last_error: Exception | None = None
    configured_model = str(body["model"])
    discovery_models = list(dict.fromkeys(["Qwen3-30B-A3B-Instruct-2507", "GLM", configured_model]))
    used_model = configured_model
    for attempt, discovery_model in enumerate(discovery_models):
        body["model"] = discovery_model
        body["messages"] = messages
        request = urllib.request.Request(
            f"{str(config.get('base_url') or INTERNAL_AI_BASE_URL).rstrip('/')}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        wait_for_internal_ai_slot("executive-intelligence-discoveries")
        try:
            with urlopen_with_local_proxy_fallback(request, timeout=180) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:800]
            last_error = RuntimeError(f"内网模型 HTTP {exc.code}: {detail}")
            continue
        except (TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            continue
        message = (payload.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or message.get("reasoning_content") or ""
        try:
            discoveries = _validate_model_discoveries(_extract_json_payload(content), evidence)
            used_model = discovery_model
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < len(discovery_models):
                messages.extend([
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"上一版未通过跨库门禁：{exc}。请依据规则精简改写，仍只返回四项JSON数组。",
                    },
                ])
    if discoveries is None:
        raise ValueError(f"AI跨库发现连续三次未通过门禁：{last_error}")
    return {"generated_at_hkt": _now(), "model": used_model, "discoveries": discoveries}


def publish_model_domain_summaries(path: Path = AI_ANALYSIS_PATH) -> dict[str, Any]:
    analysis = _read_json(path, {}) or {}
    evidence = _analysis_input_snapshot()
    evidence_hash = _content_hash(evidence)
    previous = analysis.get("model_analysis") or {}
    previous_summaries = previous.get("summaries") or []
    previous_discoveries = previous.get("discoveries") or []
    previous_hash = str(previous.get("evidence_hash") or "")
    if previous_summaries and previous_discoveries and previous_hash == evidence_hash and not previous.get("fallback_used"):
        try:
            validated = _validate_model_summaries(
                _repair_model_summaries(previous_summaries, evidence),
                evidence,
            )
            validated_discoveries = _validate_model_discoveries(previous_discoveries, evidence)
        except ValueError:
            pass
        else:
            generated = {
                **previous,
                "evidence_hash": evidence_hash,
                "insight_format": INSIGHT_FORMAT_VERSION,
                "summaries": validated,
                "discoveries": validated_discoveries,
                "reused": True,
            }
            analysis["model_analysis"] = generated
            _atomic_write_json(path, analysis)
            return {"ok": True, **generated}
    summaries_reused = False
    if previous_summaries and previous_hash == evidence_hash and not previous.get("fallback_used"):
        try:
            validated_summaries = _validate_model_summaries(
                _repair_model_summaries(previous_summaries, evidence),
                evidence,
            )
        except ValueError:
            validated_summaries = []
        else:
            summaries_reused = True
    if summaries_reused:
        generated = {
            "generated_at_hkt": str(previous.get("generated_at_hkt") or _now()),
            "model": str(previous.get("model") or "validated-previous-analysis"),
            "summaries": validated_summaries,
        }
    else:
        try:
            generated = generate_model_domain_summaries(evidence)
        except Exception as exc:
            generated = {
                "generated_at_hkt": _now(),
                "model": "deterministic-evidence-fallback",
                "summaries": _deterministic_domain_summaries(evidence),
                "fallback_used": True,
                "fallback_reason": str(exc)[:500],
            }
    try:
        discovery_payload = generate_model_discoveries(evidence)
    except Exception as exc:
        discovery_payload = {
            "generated_at_hkt": _now(),
            "model": "deterministic-evidence-fallback",
            "discoveries": _deterministic_discoveries(evidence),
            "fallback_used": True,
            "fallback_reason": str(exc)[:500],
        }
    generated["discoveries"] = discovery_payload["discoveries"]
    generated["discovery_model"] = discovery_payload["model"]
    generated["discovery_generated_at_hkt"] = discovery_payload["generated_at_hkt"]
    if discovery_payload.get("fallback_used"):
        generated["discovery_fallback_used"] = True
        generated["discovery_fallback_reason"] = discovery_payload.get("fallback_reason", "")
    generated["evidence_hash"] = evidence_hash
    generated["insight_format"] = INSIGHT_FORMAT_VERSION
    generated["reused"] = False
    analysis["model_analysis"] = generated
    _atomic_write_json(path, analysis)
    return {"ok": True, **generated}


def _period_rank(value: Any) -> tuple[int, int, int]:
    text = str(value or "")
    import re
    iso = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if iso:
        return tuple(int(item) for item in iso.groups())
    quarter = re.search(r"Q([1-4])\s+(20\d{2})", text)
    if quarter:
        return int(quarter.group(2)), int(quarter.group(1)) * 3, 31
    year = re.search(r"(20\d{2})", text)
    return (int(year.group(1)), 0, 0) if year else (0, 0, 0)


def validate_database(domain: str, path: Path, previous_path: Path | None = None) -> dict[str, Any]:
    payload = _read_json(path)
    if payload is None:
        raise ValueError(f"{domain} 数据文件无法解析：{path}")
    rows = payload if isinstance(payload, list) else payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{domain} 数据库为空：{path}")
    previous_payload = _read_json(previous_path) if previous_path and previous_path.exists() else None
    previous_rows = previous_payload if isinstance(previous_payload, list) else (previous_payload or {}).get("rows") or []
    if previous_rows and len(rows) < int(len(previous_rows) * 0.95):
        raise ValueError(f"{domain} 行数降级：{len(previous_rows)} -> {len(rows)}")

    result: dict[str, Any] = {"rows": len(rows), "path": str(path), "latest_period": "", "quality": "passed"}
    if domain == "local":
        bad = [row for row in rows if int(row.get("verification_count") or 0) < 2 or not row.get("source_url")]
        if bad:
            raise ValueError(f"本地竞对存在 {len(bad)} 条未达到双重验证或缺少来源的记录")
        result["verified_rows"] = len(rows)
    elif domain in {"international", "cloud"}:
        usable = [row for row in rows if str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES]
        if not usable:
            raise ValueError(f"{domain} 没有可供前端使用的已核验记录")
        period_key = "period_end" if domain == "international" else "fiscal_year"
        result["latest_period"] = max((str(row.get(period_key) or "") for row in usable), key=_period_rank, default="")
        result["verified_rows"] = len(usable)
    elif domain == "macro":
        bad = [
            row for row in rows
            if row.get("verification_status") not in {"official_match", "source_gap_confirmed"}
            or int(row.get("verification_count") or 0) < 2
        ]
        if bad:
            raise ValueError(f"宏观库存在 {len(bad)} 条未通过官方来源门禁的记录")
        result["latest_period"] = max((str(row.get("period_end") or "") for row in rows), key=_period_rank, default="")
        result["verified_rows"] = len(rows) - sum(row.get("verification_status") == "source_gap_confirmed" for row in rows)

    if previous_rows and domain != "local":
        previous_period_key = "fiscal_year" if domain == "cloud" else "period_end"
        comparable_previous = previous_rows
        if domain in {"international", "cloud"}:
            comparable_previous = [
                row for row in previous_rows
                if str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES
            ]
        elif domain == "macro":
            comparable_previous = [row for row in previous_rows if row.get("verification_status") == "official_match"]
        previous_latest = max(
            (str(row.get(previous_period_key) or "") for row in comparable_previous),
            key=_period_rank,
            default="",
        )
        if result["latest_period"] and previous_latest and _period_rank(result["latest_period"]) < _period_rank(previous_latest):
            raise ValueError(f"{domain} 最新期间倒退：{previous_latest} -> {result['latest_period']}")
    return result


def _run_builder(command: list[str], env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _builder_python() -> str:
    configured = str(os.environ.get("CMHK_INTELLIGENCE_BUILDER_PYTHON") or "").strip()
    if configured:
        return configured
    homebrew_python = Path("/opt/homebrew/bin/python3")
    return str(homebrew_python) if homebrew_python.exists() else sys.executable


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _merge_international_candidate(stage: Path, target: Path) -> dict[str, Any]:
    candidate_path = stage / "quarterly_metrics.json"
    current_path = target / "quarterly_metrics.json"
    candidate = _read_json(candidate_path, {}) or {}
    current = _read_json(current_path, {}) or {}
    candidate_rows = list(candidate.get("rows") or [])
    current_rows = list(current.get("rows") or [])

    def key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("subject") or ""),
            str(row.get("period") or ""),
            str(row.get("metric_key") or ""),
        )

    merged = {key(row): row for row in current_rows}
    added = 0
    upgraded = 0
    for row in candidate_rows:
        row_key = key(row)
        previous = merged.get(row_key)
        if previous is None:
            merged[row_key] = row
            added += 1
            continue
        old_status = str(previous.get("verification_status") or "")
        new_status = str(row.get("verification_status") or "")
        if new_status in SAFE_VERIFICATION_STATUSES and old_status not in SAFE_VERIFICATION_STATUSES:
            merged[row_key] = row
            upgraded += 1
    merged_rows = sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("category") or ""),
            str(row.get("subject") or ""),
            str(row.get("metric_key") or ""),
            _period_rank(row.get("period_end") or row.get("period")),
        ),
    )
    candidate["rows"] = merged_rows
    candidate["merge"] = {
        "strategy": "preserve_existing_verified_rows_and_add_new_builder_rows",
        "current_rows": len(current_rows),
        "builder_rows": len(candidate_rows),
        "added_rows": added,
        "upgraded_rows": upgraded,
        "published_rows": len(merged_rows),
    }
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_rows_csv(stage / "quarterly_metrics.csv", merged_rows)
    manifest_path = stage / "manifest.json"
    manifest = _read_json(manifest_path, {}) or {}
    manifest["row_count"] = len(merged_rows)
    if isinstance(manifest.get("quality"), dict):
        manifest["quality"]["row_count"] = len(merged_rows)
        manifest["quality"].setdefault("notes", []).append(
            "自动刷新采用保守合并：保留既有已核验行，只新增构建器发现的新键或升级更高验证等级的行。"
        )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return candidate["merge"]


def _promote_directory(stage: Path, target: Path) -> None:
    parent = target.parent
    candidate = parent / f".{target.name}.candidate-{os.getpid()}"
    backup = parent / f".{target.name}.backup-{os.getpid()}"
    shutil.rmtree(candidate, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        shutil.copytree(target, candidate)
    else:
        candidate.mkdir(parents=True)
    for source in stage.rglob("*"):
        if not source.is_file():
            continue
        destination = candidate / source.relative_to(stage)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    moved_old = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_old = True
        os.replace(candidate, target)
    except Exception:
        if moved_old and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        shutil.rmtree(candidate, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)


def _refresh_builder_domain(domain: str, *, dry_run: bool = False) -> dict[str, Any]:
    configs = {
        "international": {
            "script": ROOT / "scripts/build_quarterly_metrics_knowledge.py",
            "target": INTERNATIONAL_DIR,
            "file": "quarterly_metrics.json",
            "env": {"CMHK_QUARTERLY_METRICS_BUILD_DATE": "2026-06-18", "CMHK_QUARTERLY_METRICS_OUT_ROOT": "{stage}"},
            "timeout": 1800,
        },
        "cloud": {
            "script": ROOT / "scripts/build_cloud_vendor_metrics_knowledge.py",
            "target": CLOUD_DIR,
            "file": "cloud_vendor_metrics_2023_2025.json",
            "env": {"CMHK_CLOUD_METRICS_BUILD_DATE": "2026-06-17", "CMHK_CLOUD_METRICS_OUT_ROOT": "{stage}"},
            "timeout": 300,
        },
        "macro": {
            "script": ROOT / "scripts/build_macro_policy_knowledge.py",
            "target": MACRO_DIR,
            "file": "macro_policy_metrics.json",
            "env": {"CMHK_MACRO_POLICY_BUILD_DATE": "2026-06-19", "CMHK_MACRO_POLICY_OUT_ROOT": "{stage}"},
            "timeout": 1800,
        },
    }
    config = configs[domain]
    with tempfile.TemporaryDirectory(prefix=f"cmhk-{domain}-refresh-") as temp_dir:
        stage = Path(temp_dir) / "dataset"
        env = os.environ.copy()
        env.update({key: value.format(stage=stage) for key, value in config["env"].items()})
        proc = _run_builder([_builder_python(), str(config["script"])], env, int(config["timeout"]))
        if proc.returncode:
            raise RuntimeError(f"{domain} 构建失败({proc.returncode})：{(proc.stderr or proc.stdout)[-1200:]}")
        merge = _merge_international_candidate(stage, Path(config["target"])) if domain == "international" else None
        candidate = stage / str(config["file"])
        validation = validate_database(domain, candidate, Path(config["target"]) / str(config["file"]))
        current_payload = _read_json(Path(config["target"]) / str(config["file"]), {})
        candidate_payload = _read_json(candidate, {})
        if isinstance(candidate_payload, dict):
            candidate_payload = {key: value for key, value in candidate_payload.items() if key != "generated_at"}
        if isinstance(current_payload, dict):
            current_payload = {key: value for key, value in current_payload.items() if key != "generated_at"}
        changed = _content_hash(candidate_payload) != _content_hash(current_payload)
        if not dry_run and changed:
            if domain == "international":
                with tempfile.TemporaryDirectory(prefix="cmhk-international-promote-") as promote_dir:
                    promote_stage = Path(promote_dir)
                    for name in ("quarterly_metrics.json", "quarterly_metrics.csv", "manifest.json"):
                        shutil.copy2(stage / name, promote_stage / name)
                    _promote_directory(promote_stage, Path(config["target"]))
            else:
                _promote_directory(stage, Path(config["target"]))
        return {
            "ok": True,
            "changed": changed,
            "promoted": bool(changed and not dry_run),
            "validation": validation,
            "merge": merge,
            "stdout_tail": (proc.stdout or "")[-600:],
        }


def _publish_and_verify_github_pages() -> dict[str, Any]:
    """Publish the freshly written four-domain snapshot and require public readback."""
    if not PAGES_PUBLISH_SCRIPT.is_file():
        raise RuntimeError(f"GitHub.io发布脚本不存在：{PAGES_PUBLISH_SCRIPT}")
    environment = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment.pop(key, None)
    environment.setdefault("CMHK_INTELLIGENCE_SOURCE_URL", "http://127.0.0.1:8765/")
    result: dict[str, Any] = {}
    for attempt in range(1, 37):
        completed = subprocess.run(
            [sys.executable, str(PAGES_PUBLISH_SCRIPT), "--force"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(
                f"GitHub.io发布失败({completed.returncode})：{(completed.stderr or completed.stdout)[-1200:]}"
            )
        try:
            result = json.loads((completed.stdout or "").strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GitHub.io发布结果无法解析：{(completed.stdout or completed.stderr)[-1200:]}") from exc
        if result.get("status") != "busy":
            break
        if attempt < 36:
            time.sleep(5)
    if result.get("status") not in {"published", "verified", "unchanged"}:
        raise RuntimeError(f"GitHub.io未完成公开验证：{result}")
    if not str(result.get("public_url") or "").startswith("https://") or not result.get("site_version"):
        raise RuntimeError(f"GitHub.io验证结果字段不完整：{result}")
    return {"ok": True, "attempts": attempt, **result}


def run_pipeline(
    *,
    agent_run_id: str,
    curation_summary: dict[str, Any] | None = None,
    dry_run: bool = False,
    refresh_builders: bool = True,
    task_run_id: str = "",
    attempt: int = 1,
) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_handle.close()
        return {"ok": True, "skipped": True, "reason": "refresh_already_running"}

    started = time.monotonic()
    state: dict[str, Any] = {
        "ok": False,
        "status": "running",
        "started_at_hkt": _now(),
        "agent_run_id": agent_run_id,
        "dry_run": dry_run,
        "task_run_id": task_run_id,
        "attempt": attempt,
        "domains": {},
    }
    _atomic_write_json(STATE_PATH, state)
    _append_log(f"start agent_run_id={agent_run_id} dry_run={dry_run}")
    _task_event(
        task_run_id,
        "发布审核事实",
        f"第 {attempt} 次执行开始，正在发布Agent已通过事实并校验本地竞对库。",
    )
    try:
        if dry_run:
            ai_payload = build_ai_analysis(agent_run_id=agent_run_id, curation_summary=curation_summary)
            ai_result = {
                "ok": True,
                "changed": _content_hash({key: value for key, value in ai_payload.items() if key != "generated_at_hkt"})
                != _content_hash({key: value for key, value in (_read_json(AI_ANALYSIS_PATH, {}) or {}).items() if key != "generated_at_hkt"}),
                "domain_counts": ai_payload["domain_counts"],
                "path": str(AI_ANALYSIS_PATH),
            }
        else:
            ai_result = publish_ai_analysis(
                agent_run_id=agent_run_id,
                curation_summary=curation_summary,
            )
        state["ai_analysis"] = {
            "ok": True,
            "changed": ai_result["changed"],
            "domain_counts": ai_result["domain_counts"],
            "path": ai_result["path"],
        }
        state["domain_fact_sidecars"] = publish_domain_fact_sidecars(
            ai_result,
            dry_run=dry_run,
        )
        state["domains"]["local"] = {
            "ok": True,
            "changed": False,
            "validation": validate_database("local", LOCAL_PATH),
            "note": "本地竞对数据库已由本轮 crawl.py 更新；发布桥只复核，不重复抓取。",
        }
        local_rows = int((state["domains"]["local"].get("validation") or {}).get("rows") or 0)
        _task_event(task_run_id, "本地竞对", f"本地竞对库校验通过，共 {local_rows} 条记录。")
        if refresh_builders:
            for domain in ("international", "cloud", "macro"):
                label = DOMAIN_LABELS[domain]
                _task_event(task_run_id, label, f"正在联网重建{label}数据库并执行发布门禁。")
                try:
                    state["domains"][domain] = _refresh_builder_domain(domain, dry_run=dry_run)
                    _append_log(f"{domain} ok changed={state['domains'][domain]['changed']}")
                    validation = state["domains"][domain].get("validation") or {}
                    changed = "已更新" if state["domains"][domain].get("changed") else "无数据变化"
                    _task_event(
                        task_run_id,
                        label,
                        f"{label}门禁通过，{changed}；总记录 {int(validation.get('rows') or 0)} 条。",
                    )
                except Exception as exc:
                    state["domains"][domain] = {"ok": False, "changed": False, "promoted": False, "error": str(exc)}
                    _append_log(f"{domain} failed {exc}")
                    _task_event(task_run_id, label, f"{label}更新失败：{exc}", level="critical")
        else:
            for domain, path in (("international", INTERNATIONAL_PATH), ("cloud", CLOUD_PATH), ("macro", MACRO_PATH)):
                state["domains"][domain] = {
                    "ok": True,
                    "changed": False,
                    "validation": validate_database(domain, path),
                    "note": "本次仅验证现有数据库，未执行联网重建。",
                }
                validation = state["domains"][domain].get("validation") or {}
                _task_event(
                    task_run_id,
                    DOMAIN_LABELS[domain],
                    f"仅校验现有数据库通过，共 {int(validation.get('rows') or 0)} 条记录。",
                )
        if dry_run:
            state["model_analysis"] = {"ok": True, "skipped": True, "reason": "dry_run"}
        else:
            _task_event(task_run_id, "生成AI洞察", "正在根据四库最新通过事实生成AI洞察，并对16个关注点逐一执行数值与业务判断门禁。")
            try:
                model_analysis = publish_model_domain_summaries()
                state["model_analysis"] = {
                    "ok": True,
                    "generated_at_hkt": model_analysis["generated_at_hkt"],
                    "model": model_analysis["model"],
                    "domains": len(model_analysis["summaries"]),
                    "reused": bool(model_analysis.get("reused")),
                    "fallback_used": bool(model_analysis.get("fallback_used")),
                    "fallback_reason": str(model_analysis.get("fallback_reason") or ""),
                    "evidence_hash": str(model_analysis.get("evidence_hash") or ""),
                    "discovery_model": str(model_analysis.get("discovery_model") or ""),
                    "discovery_fallback_used": bool(model_analysis.get("discovery_fallback_used")),
                    "discovery_fallback_reason": str(model_analysis.get("discovery_fallback_reason") or ""),
                }
                fallback_note = (
                    f"；回退原因：{state['model_analysis']['fallback_reason']}"
                    if model_analysis.get("fallback_used") else "；未触发回退"
                )
                _task_event(
                    task_run_id,
                    "生成AI洞察",
                    f"16/16关注点门禁通过；模型：{state['model_analysis']['model']}；"
                    f"证据哈希：{state['model_analysis']['evidence_hash'][:16]}{fallback_note}。",
                )
            except Exception as exc:
                state["model_analysis"] = {
                    "ok": False,
                    "error": str(exc),
                    "fallback_preserved": True,
                }
                _append_log(f"model analysis failed {exc}")
                _task_event(task_run_id, "生成AI洞察", f"AI洞察生成失败：{exc}", level="critical")
        failed = [key for key, value in state["domains"].items() if not value.get("ok")]
        model_ok = bool(state.get("model_analysis", {}).get("ok"))
        core_ok = not failed and model_ok
        if dry_run:
            state["pages_publish"] = {"ok": True, "skipped": True, "reason": "dry_run"}
        elif core_ok:
            _task_event(task_run_id, "发布GitHub.io", "四库与16个AI洞察均已通过，正在发布并读取公开站点版本进行验证。")
            try:
                pages_publish = _publish_and_verify_github_pages()
                state["pages_publish"] = pages_publish
                _task_event(
                    task_run_id,
                    "发布GitHub.io",
                    f"公开站点已验证；版本：{pages_publish.get('site_version')}；地址：{pages_publish.get('public_url')}",
                )
            except Exception as exc:
                state["pages_publish"] = {"ok": False, "error": str(exc)}
                _append_log(f"github pages publish failed {exc}")
                _task_event(task_run_id, "发布GitHub.io", f"公开发布或验证失败：{exc}", level="critical")
        else:
            state["pages_publish"] = {"ok": False, "skipped": True, "reason": "core_gate_failed"}
        pages_ok = bool(state.get("pages_publish", {}).get("ok"))
        used_fallback = bool(state.get("model_analysis", {}).get("fallback_used"))
        if core_ok and pages_ok and not used_fallback:
            final_status = "completed"
        elif core_ok and not pages_ok:
            final_status = "completed_with_publish_warning"
        else:
            final_status = "completed_with_fallback"
        state.update(
            {
                "ok": core_ok,
                "status": final_status,
                "failed_domains": failed,
                "completed_at_hkt": _now(),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "fallback_preserved": bool(failed or not model_ok or used_fallback or not pages_ok),
            }
        )
    except Exception as exc:
        state.update(
            {
                "ok": False,
                "status": "failed",
                "error": str(exc),
                "completed_at_hkt": _now(),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "fallback_preserved": True,
            }
        )
        _append_log(f"pipeline failed {exc}")
    _atomic_write_json(STATE_PATH, state)
    _append_log(f"done status={state['status']} duration_ms={state['duration_ms']}")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    lock_handle.close()
    return state


def _retry_delays() -> list[int]:
    raw = os.environ.get("CMHK_INTELLIGENCE_RETRY_DELAYS", "60,300")
    delays: list[int] = []
    for item in raw.split(","):
        try:
            delays.append(max(0, int(item.strip())))
        except ValueError:
            continue
    return delays or [60, 300]


def run_pipeline_with_recovery(
    *,
    agent_run_id: str,
    curation_summary: dict[str, Any] | None = None,
    dry_run: bool = False,
    refresh_builders: bool = True,
    task_run_id: str = "",
    parent_crawl_run_id: str = "",
    max_attempts: int | None = None,
) -> dict[str, Any]:
    """Retry the safe refresh and keep all status reporting in the local task log."""
    attempts_limit = max_attempts or max(1, int(os.environ.get("CMHK_INTELLIGENCE_MAX_ATTEMPTS", "3")))
    attempts_limit = min(5, attempts_limit)
    delays = _retry_delays()
    overall_started = time.monotonic()
    result: dict[str, Any] = {}
    attempts = 0
    for attempt in range(1, attempts_limit + 1):
        attempts = attempt
        result = run_pipeline(
            agent_run_id=agent_run_id,
            curation_summary=curation_summary,
            dry_run=dry_run,
            refresh_builders=refresh_builders,
            task_run_id=task_run_id,
            attempt=attempt,
        )
        if result.get("ok") or result.get("skipped"):
            break
        if attempt < attempts_limit:
            delay = delays[min(attempt - 1, len(delays) - 1)]
            failed = "、".join(DOMAIN_LABELS.get(item, item) for item in result.get("failed_domains") or [])
            reason = failed or str(result.get("error") or result.get("status") or "未通过门禁")
            _task_event(
                task_run_id,
                "后备重试",
                f"第 {attempt} 次未完成（{reason}），{delay} 秒后执行第 {attempt + 1} 次。旧数据继续保留。",
                level="retry",
            )
            time.sleep(delay)

    result = dict(result)
    result["total_duration_ms"] = round((time.monotonic() - overall_started) * 1000)
    result["attempts"] = attempts
    result["agent_run_id"] = agent_run_id
    ok = bool(result.get("ok") or result.get("skipped"))
    if ok:
        if result.get("skipped"):
            detail = "已有另一条四库任务执行，本次已安全合并。"
        elif (result.get("pages_publish") or {}).get("ok"):
            detail = f"四库、16个AI洞察、前端数据源及GitHub.io公开验证已完成，共执行 {attempts} 次。"
        else:
            detail = (
                f"四库、16个AI洞察和前端数据源已完成，但GitHub.io发布验证未通过："
                f"{(result.get('pages_publish') or {}).get('error') or '未返回原因'}。"
            )
    else:
        failed = "、".join(DOMAIN_LABELS.get(item, item) for item in result.get("failed_domains") or [])
        detail = f"连续 {attempts} 次未通过，失败范围：{failed or result.get('error') or '观察结论'}；旧数据已保留。"
    result["notification_policy"] = "local_log_only"
    _finalize_refresh_task(
        task_run_id,
        ok=ok,
        detail=detail,
        result=result,
        attempts=attempts,
    )
    return result


def launch_pipeline_async(
    *,
    agent_run_id: str,
    curation_summary: dict[str, Any] | None = None,
    parent_crawl_run_id: str = "",
    recovery_reason: str = "",
) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = STATE_DIR / f"curation-{agent_run_id}.json"
    _atomic_write_json(summary_path, curation_summary or {})
    task = _start_refresh_task(
        agent_run_id=agent_run_id,
        parent_crawl_run_id=parent_crawl_run_id,
        recovery_reason=recovery_reason,
    )
    task_run_id = str(task["crawl_run_id"])
    log_handle = LOG_PATH.open("a", encoding="utf-8")
    try:
        try:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--scheduled",
                    "--agent-run-id",
                    agent_run_id,
                    "--curation-summary",
                    str(summary_path),
                    "--task-run-id",
                    task_run_id,
                    "--parent-crawl-run-id",
                    parent_crawl_run_id,
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except Exception as exc:
            failed = {"ok": False, "status": "failed", "agent_run_id": agent_run_id, "error": str(exc)}
            _finalize_refresh_task(
                task_run_id,
                ok=False,
                detail=f"刷新进程启动失败：{exc}",
                result=failed,
                attempts=0,
            )
            raise
    finally:
        log_handle.close()
    _task_event(
        task_run_id,
        "等待刷新进程",
        f"刷新进程已启动，PID {proc.pid}；任务日志将持续记录四库阶段。",
        worker_pid=proc.pid,
    )
    return {
        "ok": True,
        "launched": True,
        "pid": proc.pid,
        "agent_run_id": agent_run_id,
        "task_run_id": task_run_id,
        "task_id": f"crawl:{task_run_id}",
    }


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def monitor_scheduled_refresh_health(now: datetime | None = None) -> dict[str, Any]:
    """Recover once when a completed 03:00 crawl has no matching four-database publication."""
    from crawl_run_registry import load_index

    now = (now or datetime.now(HKT)).astimezone(HKT)
    scheduled = next(
        (
            item
            for item in load_index()
            if item.get("trigger") == "定时爬虫"
            and item.get("run_status") == "completed"
            and str(item.get("completed_at_hkt") or "").startswith(now.date().isoformat())
            and str((item.get("curation") or {}).get("agent_run_id") or "")
        ),
        None,
    )
    if not scheduled:
        return {"ok": True, "status": "no_scheduled_crawl_today"}
    crawl_run_id = str(scheduled.get("crawl_run_id") or "")
    agent_run_id = str((scheduled.get("curation") or {}).get("agent_run_id") or "")
    completed_at = datetime.fromisoformat(str(scheduled.get("completed_at_hkt"))).astimezone(HKT)
    latest = _read_json(STATE_PATH, {}) or {}
    if (
        latest.get("ok")
        and str(latest.get("agent_run_id") or "") == agent_run_id
        and str(latest.get("completed_at_hkt") or "") >= str(scheduled.get("completed_at_hkt") or "")
    ):
        return {"ok": True, "status": "healthy", "crawl_run_id": crawl_run_id, "agent_run_id": agent_run_id}

    tasks = [
        item
        for item in load_index()
        if item.get("task_kind") == TASK_KIND and agent_run_id in str(item.get("scope") or "")
    ]
    running = next((item for item in tasks if item.get("run_status") == "running"), None)
    if running and _process_alive(int(running.get("worker_pid") or 0)):
        return {"ok": True, "status": "refresh_running", "task_run_id": running.get("crawl_run_id")}

    grace_seconds = max(900, int(os.environ.get("CMHK_INTELLIGENCE_WATCHDOG_GRACE_SECONDS", "5400")))
    if (now - completed_at).total_seconds() < grace_seconds:
        return {"ok": True, "status": "waiting_grace_period", "crawl_run_id": crawl_run_id}

    watchdog = _read_json(WATCHDOG_STATE_PATH, {}) or {}
    recoveries = watchdog.setdefault("recoveries", {})
    if crawl_run_id in recoveries:
        return {"ok": True, "status": "recovery_already_launched", **recoveries[crawl_run_id]}

    launch = launch_pipeline_async(
        agent_run_id=agent_run_id,
        curation_summary=scheduled.get("curation") or {},
        parent_crawl_run_id=crawl_run_id,
        recovery_reason="守护补跑",
    )
    recoveries[crawl_run_id] = {
        "crawl_run_id": crawl_run_id,
        "agent_run_id": agent_run_id,
        "task_run_id": launch.get("task_run_id", ""),
        "launched_at_hkt": _now(),
        "notification_policy": "local_log_only",
    }
    watchdog["updated_at_hkt"] = _now()
    _atomic_write_json(WATCHDOG_STATE_PATH, watchdog)
    return {"ok": True, "status": "recovery_launched", **recoveries[crawl_run_id]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the four executive-intelligence databases after Agent review.")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--agent-run-id", default="manual")
    parser.add_argument("--curation-summary")
    parser.add_argument("--task-run-id", default="")
    parser.add_argument("--parent-crawl-run-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    summary = _read_json(Path(args.curation_summary), {}) if args.curation_summary else {}
    runner = run_pipeline_with_recovery if args.scheduled else run_pipeline
    result = runner(
        agent_run_id=args.agent_run_id,
        curation_summary=summary,
        dry_run=args.dry_run,
        refresh_builders=not args.validate_only,
        task_run_id=args.task_run_id,
        **({"parent_crawl_run_id": args.parent_crawl_run_id} if args.scheduled else {}),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok") and not result.get("skipped"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
