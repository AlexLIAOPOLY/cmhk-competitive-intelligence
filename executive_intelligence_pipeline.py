from __future__ import annotations

import argparse
import csv
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
import uuid
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
    alert: dict[str, Any] | None = None,
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
            "alert": alert or {},
        },
    )


def _send_refresh_alert(
    *,
    title: str,
    detail: str,
    task_run_id: str,
    agent_run_id: str,
    parent_crawl_run_id: str = "",
    severity: str = "critical",
) -> dict[str, Any]:
    """Send a deduplicated Feishu alert to both configured strategy groups."""
    if os.environ.get("CMHK_INTELLIGENCE_ALERTS", "1").strip().lower() in {"0", "false", "off"}:
        return {"ok": True, "skipped": True, "reason": "alerts_disabled", "message_ids": []}
    import strategic_briefing

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "red" if severity == "critical" else "orange",
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**状态：** {detail}\n"
                        f"**任务：** {task_run_id or '未建立'}\n"
                        f"**Agent：** {agent_run_id or '未记录'}\n"
                        f"**父任务：** {parent_crawl_run_id or '未记录'}\n"
                        "旧数据库和最后可用观察结论已保留，请在前端任务日志查看重试过程。"
                    ),
                },
            }
        ],
    }
    message_ids: list[str] = []
    errors: list[str] = []
    for chat_id in strategic_briefing.TARGET_CHAT_IDS:
        payload: dict[str, Any] = {}
        for attempt in range(3):
            try:
                payload = strategic_briefing._lark_api(
                    "POST",
                    "/open-apis/im/v1/messages",
                    params={"receive_id_type": "chat_id"},
                    data={
                        "receive_id": chat_id,
                        "msg_type": "interactive",
                        "content": json.dumps(card, ensure_ascii=False),
                        "uuid": str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"cmhk-intelligence-alert:{task_run_id}:{severity}:{chat_id}",
                            )
                        ),
                    },
                )
                break
            except Exception as exc:
                if attempt >= 2:
                    errors.append(f"{chat_id}: {exc}")
                else:
                    time.sleep(2**attempt)
        message_id = str(((payload.get("data") or {}).get("message_id") or ""))
        if message_id:
            message_ids.append(message_id)
    return {"ok": not errors, "message_ids": message_ids, "errors": errors}


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
    from executive_intelligence import build_executive_intelligence_snapshot

    snapshot = build_executive_intelligence_snapshot()
    domains: list[dict[str, Any]] = []
    for domain in snapshot.get("domains") or []:
        focuses = []
        for focus in domain.get("focuses") or []:
            focuses.append(
                {
                    "id": focus.get("id"),
                    "label": focus.get("label"),
                    "metric": focus.get("metric"),
                    "insight": focus.get("insight"),
                    "items": [
                        {
                            "name": item.get("name"),
                            "value": item.get("value"),
                            "unit": item.get("unit"),
                            "detail": item.get("detail"),
                            "analysis": item.get("analysis"),
                            "source_url": item.get("source_url"),
                        }
                        for item in (focus.get("items") or [])[:8]
                    ],
                }
            )
        domains.append(
            {
                "id": domain.get("id"),
                "title": domain.get("title"),
                "metric": domain.get("metric"),
                "deterministic_insight": domain.get("insight"),
                "focuses": focuses,
                "agent_verified_facts": (domain.get("ai_analysis") or [])[:8],
            }
        )
    return {"domains": domains, "relations": snapshot.get("relations") or []}


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
                }
                if not validated_focus["analysis"] or not validated_focus["risk"]:
                    raise ValueError(f"AI分析分类字段不完整：{domain}.{focus_id}")
                unknown_focus_urls = set(validated_focus["source_urls"]) - allowed_urls
                if unknown_focus_urls:
                    raise ValueError(f"AI分析分类引用了输入之外的来源：{sorted(unknown_focus_urls)}")
                unknown_focus_numbers = _numeric_tokens(validated_focus) - allowed_numbers
                if unknown_focus_numbers:
                    raise ValueError(f"AI分析分类出现输入之外的数字：{sorted(unknown_focus_numbers)}")
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
    sanitized: list[Any] = []
    for item in raw:
        if not isinstance(item, dict):
            sanitized.append(item)
            continue
        cleaned = dict(item)
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
            cleaned_focuses.append(cleaned_focus)
        if "focuses" in cleaned:
            cleaned["focuses"] = cleaned_focuses
        if removed:
            cleaned["sanitized_clauses"] = removed
        sanitized.append(cleaned)
    return sanitized


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
                        "analysis": str(focus.get("insight") or "当前仅展示已通过发布门禁的证据。"),
                        "risk": "仅基于当前已核验来源和已披露口径，缺失数据不估算。",
                        "source_urls": list(dict.fromkeys(
                            str(item.get("source_url") or "")
                            for item in focus.get("items") or []
                            if str(item.get("source_url") or "").startswith(("https://", "http://"))
                        ))[:3],
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
        "每个领域给出一句headline、一段analysis和一句risk，并为输入中的每个focus给出一段analysis和一句risk。"
        "所有focus必须逐一覆盖，不能遗漏、合并或新增。跨期间、代理分部、披露缺口必须明确写入risk；"
        "不得把相关性写成因果。不得从URL文件名推断日期，也不得把FY财年自行转换成具体月日。"
        "source_urls只能从输入中原样选择。只返回JSON数组。"
    )
    user_prompt = (
        "请分析 local、international、cloud、macro 四个领域。每项字段严格为"
        "domain, headline, analysis, risk, source_urls, focuses；focuses每项字段严格为"
        "id, analysis, risk, source_urls。不要Markdown。输入：\n"
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
    }
    summaries: list[dict[str, Any]] | None = None
    last_error: Exception | None = None
    for attempt in range(3):
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
        content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        try:
            raw_summaries = _extract_json_payload(content)
            summaries = _validate_model_summaries(
                _drop_unsupported_numeric_clauses(raw_summaries, evidence),
                evidence,
            )
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                f"上一版未通过事实门禁：{exc}。请删除或改写所有未获输入支持的数字/来源，"
                                "保持四个领域完整并重新只返回JSON数组。"
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
                        "必须逐一返回输入中的全部focus id。字段协议不变。输入：\n"
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
                    domain_content = ((domain_payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                    parsed = _extract_json_payload(domain_content)
                    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
                        raise ValueError("必须返回单对象JSON数组")
                    candidate = parsed[0]
                    returned_focus_ids = {
                        str(focus.get("id") or "")
                        for focus in candidate.get("focuses") or []
                        if isinstance(focus, dict)
                    }
                    if not expected_focus_ids.issubset(returned_focus_ids):
                        raise ValueError(f"分类覆盖不完整：{sorted(expected_focus_ids - returned_focus_ids)}")
                    candidate["domain"] = domain_id
                    candidate["focuses"] = [
                        focus for focus in candidate.get("focuses") or []
                        if isinstance(focus, dict) and str(focus.get("id") or "") in expected_focus_ids
                    ]
                    domain_summary = candidate
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    domain_error = exc
                    if domain_attempt < 2:
                        domain_messages.append({
                            "role": "user",
                            "content": f"上一版未通过门禁：{exc}。请完整返回全部focus，仍只返回单对象JSON数组。",
                        })
            if domain_summary is None:
                raise ValueError(f"AI分析按领域重试仍未通过：{domain_id}: {domain_error}")
            per_domain_summaries.append(domain_summary)
        summaries = _validate_model_summaries(
            _drop_unsupported_numeric_clauses(per_domain_summaries, evidence),
            evidence,
        )
    return {"generated_at_hkt": _now(), "model": body["model"], "summaries": summaries}


def generate_model_discoveries(evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot
    from network_utils import urlopen_with_local_proxy_fallback

    evidence = evidence or _analysis_input_snapshot()
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
    }
    discoveries: list[dict[str, Any]] | None = None
    last_error: Exception | None = None
    for attempt in range(3):
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
            raise RuntimeError(f"内网模型 HTTP {exc.code}: {detail}") from exc
        content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        try:
            discoveries = _validate_model_discoveries(_extract_json_payload(content), evidence)
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                messages.extend([
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"上一版未通过跨库门禁：{exc}。请依据规则精简改写，仍只返回四项JSON数组。",
                    },
                ])
    if discoveries is None:
        raise ValueError(f"AI跨库发现连续三次未通过门禁：{last_error}")
    return {"generated_at_hkt": _now(), "model": body["model"], "discoveries": discoveries}


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
            validated = _validate_model_summaries(previous_summaries, evidence)
            validated_discoveries = _validate_model_discoveries(previous_discoveries, evidence)
        except ValueError:
            pass
        else:
            generated = {
                **previous,
                "evidence_hash": evidence_hash,
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
            validated_summaries = _validate_model_summaries(previous_summaries, evidence)
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
            _task_event(task_run_id, "生成观察结论", "正在根据四库最新通过事实生成综合发现和16个关注点结论。")
            try:
                model_analysis = publish_model_domain_summaries()
                state["model_analysis"] = {
                    "ok": True,
                    "generated_at_hkt": model_analysis["generated_at_hkt"],
                    "model": model_analysis["model"],
                    "domains": len(model_analysis["summaries"]),
                    "reused": bool(model_analysis.get("reused")),
                    "fallback_used": bool(model_analysis.get("fallback_used")),
                }
                fallback_note = "；模型未通过门禁，已使用证据规则回退" if model_analysis.get("fallback_used") else ""
                _task_event(task_run_id, "生成观察结论", f"观察结论发布完成{fallback_note}。")
            except Exception as exc:
                state["model_analysis"] = {
                    "ok": False,
                    "error": str(exc),
                    "fallback_preserved": True,
                }
                _append_log(f"model analysis failed {exc}")
                _task_event(task_run_id, "生成观察结论", f"观察结论生成失败：{exc}", level="critical")
        failed = [key for key, value in state["domains"].items() if not value.get("ok")]
        model_ok = bool(state.get("model_analysis", {}).get("ok"))
        state.update(
            {
                "ok": not failed and model_ok,
                "status": "completed" if not failed and model_ok else "completed_with_fallback",
                "failed_domains": failed,
                "completed_at_hkt": _now(),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "fallback_preserved": bool(failed or not model_ok),
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
    return state


def launch_pipeline_async(*, agent_run_id: str, curation_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = STATE_DIR / f"curation-{agent_run_id}.json"
    _atomic_write_json(summary_path, curation_summary or {})
    log_handle = LOG_PATH.open("a", encoding="utf-8")
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
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log_handle.close()
    return {"ok": True, "launched": True, "pid": proc.pid, "agent_run_id": agent_run_id}


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the four executive-intelligence databases after Agent review.")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--agent-run-id", default="manual")
    parser.add_argument("--curation-summary")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    summary = _read_json(Path(args.curation_summary), {}) if args.curation_summary else {}
    result = run_pipeline(
        agent_run_id=args.agent_run_id,
        curation_summary=summary,
        dry_run=args.dry_run,
        refresh_builders=not args.validate_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
