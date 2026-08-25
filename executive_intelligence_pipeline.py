from __future__ import annotations

import argparse
import csv
import difflib
import fcntl
import hashlib
import itertools
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
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from ai_response_compat import final_chat_message_text, load_json_response, prepare_structured_chat_body, unwrap_items_payload


ROOT = Path(__file__).resolve().parent
HKT = ZoneInfo("Asia/Hong_Kong")
STATE_DIR = ROOT / "agent_knowledge" / "executive_intelligence_refresh"
STATE_PATH = STATE_DIR / "latest.json"
AI_ANALYSIS_PATH = STATE_DIR / "ai_analysis.json"
LOCK_PATH = STATE_DIR / ".refresh.lock"
LOG_PATH = STATE_DIR / "refresh.log"
WATCHDOG_STATE_PATH = STATE_DIR / "watchdog.json"
PAGES_PUBLISH_SCRIPT = ROOT / "scripts" / "publish_executive_dashboard_pages.py"
INSIGHT_FORMAT_VERSION = "strategic_cell_meaning_v8"

FOCUS_RELATION_FEW_SHOTS = (
    "少样本约束：\n"
    "反例：HKBN有27个产品、3HK有24个、SmarTone有21个，说明三家产品较多。"
    "问题：只是复述数字，没有竞对结构和经营含义。\n"
    "正例：HKBN、3HK和SmarTone分别有27、24、21个产品，而i-CABLE和HGC为8、4个，"
    "数量形成两层；但头部三家彼此只差6个，产品数量难以成为头部之间的主要区隔。\n"
    "反例：Google Cloud增长35.8%，高于Oracle 23.9%，说明Google领先。"
    "问题：把单项增速直接等同竞争力。\n"
    "正例：4家直接披露云收入的厂商中，Google Cloud为35.8%、Alibaba Cloud为11.0%，"
    "收入增速形成两层；Azure和Tencent是代理分部口径，不纳入这一比较。\n"
    "反例：投资增长1.3%推动投诉增长2.9%。问题：期间不同且虚构因果。\n"
    "正例：投资数据截至2025年3月，投诉数据为2025自然年，期间不同，"
    "不能判断两者关系，只能分别观察投入变化和服务压力。\n"
    "反例：HKT营收36553百万港元，3HK为5448百万港元，数值存在差距。"
    "问题：只告诉读者数据是什么，没有提炼战略发现。\n"
    "正例：HKT营收36553百万港元、3HK为5448百万港元，可披露收入规模形成头尾分层，"
    "意味着两者竞争资源承载力不在同一量级；但绝对规模不等同经营效率。\n"
    "反例：AWS云利润39834百万美元，Google为6112百万美元，利润定义见明细。"
    "问题：只复述金额和定义。\n"
    "正例：同属经营利润披露的AWS为39834百万美元、Google为6112百万美元，利润池向头部集中，"
    "表明云业务盈利缓冲分层；其他厂商的毛利或调整后EBITA不混入这一判断。\n"
    "反例：三来源数据待补为-，四家公司后付费数据均未披露，因此无法比较。"
    "问题：把空值或占位符当成数字，而且只报告数据缺口。\n"
    "正例：四家公司均缺少可比后付费原值，口径缺口意味着客户价值和客户质量无法穿透比较，"
    "竞争结构判断不能由移动或5G用户总量替代。"
)
MAX_FOCUS_INSIGHT_CHARS = 120
MAX_FOCUS_INSIGHT_SENTENCES = 2
TASK_KIND = "executive-intelligence-refresh"
DOMAIN_LABELS = {
    "local": "本地运营商",
    "international": "国际运营商",
    "mainland": "内地运营商",
    "cloud": "全球云厂商",
    "macro": "宏观政策支撑库",
}
UI_DOMAIN_IDS = ("local", "international", "mainland", "cloud")
SUPPORTING_DOMAIN_IDS = ("macro",)
FACT_DOMAIN_IDS = (*UI_DOMAIN_IDS, *SUPPORTING_DOMAIN_IDS)

LOCAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/current_plans.json"
LOCAL_FINANCIAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json"
INTERNATIONAL_DIR = ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18"
INTERNATIONAL_PATH = INTERNATIONAL_DIR / "quarterly_metrics.json"
GLOBAL_OPERATOR_DIR = ROOT / "agent_knowledge/global_top5_operators_2016_2025"
CLOUD_DIR = ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17"
CLOUD_PATH = CLOUD_DIR / "cloud_vendor_metrics_2023_2025.json"
MACRO_DIR = ROOT / "agent_knowledge/cmhk_macro_policy_2026-06-19"
MACRO_PATH = MACRO_DIR / "macro_policy_metrics.json"
VERIFIED_FACTS_PATH = ROOT / "curation_data/verified_facts.jsonl"
DOMAIN_FACT_PATHS = {
    "local": LOCAL_PATH.parent / "agent_verified_facts.json",
    "international": GLOBAL_OPERATOR_DIR / "agent_verified_facts.json",
    "mainland": INTERNATIONAL_DIR / "agent_verified_facts.json",
    "cloud": CLOUD_DIR / "agent_verified_facts.json",
    "macro": MACRO_DIR / "agent_verified_facts.json",
}

LOCAL_COMPANIES = {
    "HKT", "csl", "1O1O", "3HK / Hutchison", "Hutchison", "SmarTone", "HKBN", "HGC", "i-CABLE"
}
MAINLAND_COMPANIES = {"中国移动", "中国电信", "中国联通", "中国铁塔", "中国广电"}
INTERNATIONAL_COMPANIES = {
    "KDDI", "SoftBank", "Telstra", "Jio", "Reliance Jio", "Bharti Airtel",
    "T-Mobile US", "AT&T", "Verizon", "Orange", "Telefonica", "Vodafone",
    "SK Telecom", "Deutsche Telekom", "NTT", "NTT Group",
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
    from cmhk.crawl.run_registry import append_crawl_run_event, heartbeat_crawl_run

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
    from cmhk.crawl.run_registry import append_crawl_run_event, start_crawl_run

    scope = f"Agent审核 {agent_run_id}"
    if parent_crawl_run_id:
        scope += f" · 父任务 {parent_crawl_run_id}"
    if recovery_reason:
        scope += f" · {recovery_reason}"
    task = start_crawl_run(
        trigger="四库与观察结论自动更新",
        scope=scope,
        task_kind=TASK_KIND,
        parent_crawl_run_id=parent_crawl_run_id,
        phase="等待刷新进程",
        progress_detail=(
            "任务已归档，正在更新战略总览的本地运营商、国际运营商、内地运营商和全球云厂商四域；"
            "宏观政策库继续作为支撑数据维护。"
        ),
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
    from cmhk.crawl.run_registry import finalize_operational_crawl_run

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
    if company in MAINLAND_COMPANIES:
        return "mainland"
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

    domains: dict[str, list[dict[str, Any]]] = {key: [] for key in FACT_DOMAIN_IDS}
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
    for domain in FACT_DOMAIN_IDS:
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
    from cmhk.intelligence.executive import build_executive_intelligence_evidence_snapshot

    # Rendered relations are intentionally excluded. The hash must move only
    # when source-backed facts or the deterministic evidence pack changes.
    return build_executive_intelligence_evidence_snapshot()


def _extract_json_payload(text: str) -> Any:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("模型本次未返回有效内容")
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


def _extract_focus_response(text: str) -> dict[str, Any]:
    """Parse one focus object and salvage a model response cut after its fields."""
    try:
        parsed = _extract_json_payload(text)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?|```$", "", str(text or "").strip(), flags=re.I).strip()
        headline_match = re.search(r'"headline"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned, re.S)
        analysis_match = re.search(r'"analysis"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned, re.S)
        if not analysis_match:
            analysis_match = re.search(r'"analysis"\s*:\s*"(.*)$', cleaned, re.S)
        if not headline_match or not analysis_match:
            raise
        headline = json.loads(f'"{headline_match.group(1)}"')
        raw_analysis = re.sub(r'"?\s*[,}]?\s*$', "", analysis_match.group(1).strip())
        try:
            analysis = json.loads(f'"{raw_analysis}"')
        except json.JSONDecodeError:
            analysis = raw_analysis.replace('\\"', '"')
        parsed = {"headline": headline, "analysis": analysis}
    if isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        raise ValueError("模型未返回单项洞察对象")
    return parsed


def _pin_scoped_model_identity(raw: Any, domain_id: str, focus_id: str = "") -> Any:
    """Restore identifiers fixed by a scoped request before evidence-based repairs run."""
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        return raw
    pinned = json.loads(json.dumps(raw, ensure_ascii=False))
    pinned[0]["domain"] = domain_id
    focuses = pinned[0].get("focuses") or []
    if focus_id and isinstance(focuses, list) and len(focuses) == 1 and isinstance(focuses[0], dict):
        focuses[0]["id"] = focus_id
    return pinned


def _numeric_tokens(value: Any) -> set[str]:
    tokens = set()
    for token in re.findall(r"(?<![\d.])[-+]?\d+(?:\.\d+)?", json.dumps(value, ensure_ascii=False)):
        try:
            tokens.add(f"{float(token):g}")
        except ValueError:
            pass
    return tokens


def _focus_value_tokens(focus: dict[str, Any]) -> set[str]:
    """Return values explicitly present in the current focus evidence."""
    values: list[Any] = []
    metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
    if metric.get("value") not in (None, ""):
        values.append(metric.get("value"))
    for item in focus.get("items") or []:
        if not isinstance(item, dict):
            continue
        for key in ("value", "record_count", "component_count", "low", "high", "detail"):
            if item.get(key) not in (None, ""):
                values.append(item.get(key))
        for component in item.get("components") or []:
            if isinstance(component, dict):
                for key in ("value", "detail"):
                    if component.get(key) not in (None, ""):
                        values.append(component.get(key))
    values.append(len([item for item in focus.get("items") or [] if isinstance(item, dict)]))
    return _numeric_tokens(values)


_ANALYTICAL_JUDGEMENT_TERMS = (
    "领先", "落后", "高于", "低于", "最高", "最低", "差距", "距离", "变化", "增长",
    "下降", "回落", "改善", "加速", "放缓", "分化", "集中", "重叠", "梯度", "饱和",
    "压力", "风险", "机会", "空间", "优势", "短板", "不同", "差异", "相差", "居首",
    "覆盖", "完整", "充分", "不足", "多于", "少于", "强于", "弱于", "扩大", "收窄",
    "深度", "约束", "承压", "断层", "区隔", "选择", "新增", "负担", "转化", "压力",
)
_INTERPRETIVE_CONNECTORS = (
    "表明", "反映", "说明", "意味着", "显示", "因此", "主要来自", "并非", "而非", "本质上",
    "取决于", "受制于", "源于", "不能等同", "不能直接", "并不等同", "不等于", "不可直接", "不完全是", "更接近",
)
_INTERPRETIVE_DIMENSIONS = (
    "结构", "口径", "集中", "可比", "驱动", "依赖", "饱和", "错位", "背离", "同步",
    "脱钩", "分层", "梯队", "边界", "质量", "效率", "弹性", "定价权", "产品广度",
    "增速", "方向", "幅度", "梯度",
    "分布", "阵营", "正负", "强弱", "两层",
    "记录颗粒度", "记录密度", "渗透", "变现", "盈利", "利润", "收入", "客户", "网络", "竞争", "产品类型", "产品选择", "产品数量", "购买力", "价格", "套餐", "投入", "资本", "负担", "流量", "连接", "服务", "优惠条件",
)
_DEEP_RELATION_MARKERS = (
    "主要来自", "源于", "驱动", "并非", "而非", "不等同", "不等价", "不等于", "不能", "不可",
    "受制", "约束", "转为", "集中于", "断层", "同步", "脱钩", "结构性差异", "口径放大",
    "接近饱和", "趋于饱和", "未形成", "不再来自", "共同拉开", "梯队分布",
    "分层竞争", "头部主导", "偏态分布", "不代表", "不纳入", "未纳入", "难形成", "受压", "承压", "混排", "重合", "差距", "不同", "并列信号",
    "多数", "少数", "唯一", "同向", "分组", "覆盖全部", "覆盖大部分",
    "梯队", "层次", "范围", "样本", "部分覆盖", "高低", "同类",
)
_ACTION_ADVICE_PHRASES = (
    "建议", "值得关注", "后续关注", "应优先", "需优先", "优先关注", "优先评估", "优先验证",
    "应关注", "需关注", "应评估", "需评估", "应验证", "需验证", "应采用", "需采用",
    "应补齐", "需补齐", "应锁定", "需锁定", "应兼顾", "需兼顾", "应降低", "需降低",
    "应提升", "需提升", "应复制", "需复制", "应区分", "需区分", "可考虑",
    "应更关注", "需转化",
)


def _contains_action_advice(value: Any) -> bool:
    text = str(value or "")
    if any(phrase in text for phrase in _ACTION_ADVICE_PHRASES):
        return True
    return bool(re.search(
        r"(?:建议|值得关注|后续关注|优先|应(?:当|该|更|以|关注|评估|验证|采用|补齐|锁定|兼顾|降低|提升|复制|区分)|"
        r"需(?:要|转化|关注|评估|验证|采用|补齐|锁定|兼顾|降低|提升|复制|区分))",
        text,
    ))


def _has_deep_interpretation(value: Any) -> bool:
    """Require an evidence interpretation, not a metric restatement or recommendation."""
    text = str(value or "").strip()
    return (
        any(term in text for term in _ANALYTICAL_JUDGEMENT_TERMS)
        and any(term in text for term in _INTERPRETIVE_CONNECTORS)
        and any(term in text for term in _INTERPRETIVE_DIMENSIONS)
        and any(term in text for term in _DEEP_RELATION_MARKERS)
        and not _contains_action_advice(text)
    )


def _has_business_judgement(value: Any) -> bool:
    """Backward-compatible name for the current deep-interpretation gate."""
    return _has_deep_interpretation(value)


_OVERVIEW_STRATEGIC_HEADLINES = {
    ("local", "revenue"): "持续竞争资源明显分层",
    ("local", "ebitda"): "持续投入能力形成断层",
    ("local", "net_profit"): "盈利防线出现两极分化",
    ("local", "postpaid"): "经常性收入底盘分层",
    ("international", "revenue"): "跨国资源底盘形成分层",
    ("international", "ebitda"): "经营缓冲厚度明显分化",
    ("international", "net_profit"): "利润池控制力出现分化",
    ("international", "postpaid_arpu"): "客户规模与价值信号错位",
    ("mainland", "revenue"): "规模优势固化资源壁垒",
    ("mainland", "ebitda"): "现金创造支撑能力分层",
    ("mainland", "net_profit"): "盈利韧性向头部集中",
    ("mainland", "postpaid"): "客户覆盖底盘形成断层",
    ("cloud", "revenue"): "生态承载力形成头尾断层",
    ("cloud", "profit"): "盈利飞轮集中于头部",
    ("cloud", "investment"): "资本军备能力明显分层",
}

_OVERVIEW_STRATEGIC_HEADLINE_VARIANTS = {
    ("local", "revenue"): ("持续竞争资源明显分层", "网络与获客投入空间分化", "规模底盘拉开防守容错"),
    ("local", "ebitda"): ("持续投入能力形成断层", "价格竞争缓冲明显分化", "经营容错空间拉开层次"),
    ("local", "net_profit"): ("盈利防线出现两极分化", "自我融资空间明显分层", "再投资能力呈现断层"),
    ("local", "postpaid"): ("经常性收入底盘分层", "客户保有风险明显分化", "续约底盘拉开层次"),
    ("international", "revenue"): ("跨国资源底盘形成分层", "网络与渠道投入空间分化", "全球获客资源承载力分层"),
    ("international", "ebitda"): ("经营缓冲厚度明显分化", "价格竞争容错拉开层次", "持续网络投入能力分层"),
    ("international", "net_profit"): ("利润池控制力出现分化", "自我融资与再投资空间分层", "周期防守能力拉开差距"),
    ("international", "postpaid_arpu"): ("客户规模与价值信号错位", "客户质量不能只看规模", "客户经营底盘口径分化"),
    ("mainland", "revenue"): ("规模优势固化资源壁垒", "网络与获客投入能力分层", "经营防守资源拉开层次"),
    ("mainland", "ebitda"): ("现金创造支撑能力分层", "持续投入缓冲明显分化", "价格竞争容错拉开差距"),
    ("mainland", "net_profit"): ("盈利韧性向头部集中", "自我融资能力形成断层", "再投资空间明显分化"),
    ("mainland", "postpaid"): ("客户覆盖底盘形成断层", "客户规模梯队拉开层次", "交叉销售基础明显分化"),
    ("cloud", "revenue"): ("生态承载力形成头尾断层", "生态扩张资源明显分层", "基础设施投入空间分化"),
    ("cloud", "profit"): ("盈利飞轮集中于头部", "再投资与价格竞争空间分层", "盈利缓冲拉开生态差距"),
    ("cloud", "investment"): ("资本军备能力明显分层", "基础设施扩张空间分化", "持续扩容能力形成断层"),
}

_OVERVIEW_DIRECT_HEADLINE_TERMS = (
    "FY", "财年", "营收", "EBITDA", "净利润", "后付费用户", "云收入", "云利润", "资本开支",
    "金额", "绝对值", "序列", "入库", "披露", "口径", "数据", "待补", "重新判断", "按三来源",
)

_OVERVIEW_STRATEGIC_MEANING_TERMS = (
    "持续投入", "竞争投入", "网络投入", "客户获取", "客户保有", "价格竞争", "价格战", "经营容错",
    "自我融资", "再投资", "经常性收入", "收入底盘", "客户价值", "客户质量", "续约", "流失",
    "生态扩张", "资本军备", "基础设施", "客户经营战略",
)


def _strategic_focus_headline(
    domain: str, focus_id: str, fallback: Any = "", *, variant_index: int = 0
) -> str:
    variants = _OVERVIEW_STRATEGIC_HEADLINE_VARIANTS.get((domain, focus_id))
    if variants:
        return variants[variant_index % len(variants)]
    return _OVERVIEW_STRATEGIC_HEADLINES.get((domain, focus_id), str(fallback or "").strip())


def _focus_gate_error(domain: str, focus_id: str, analysis: str, evidence_focus: dict[str, Any]) -> str:
    if re.match(r"^(?:但|但是|然而|而|这说明|这表明|这意味着|因此)", analysis) or re.search(
        r"(?:意味着|说明|表明)中(?:[，,。！？!?]|$)|存在差距个|(?:变化|观察)[，,]分别为", analysis
    ):
        return f"AI分析分类句序不完整：{domain}.{focus_id}"
    terminal_marks = re.findall(r"[。！？!?]", analysis)
    if len(analysis) > MAX_FOCUS_INSIGHT_CHARS or not terminal_marks or (
        len(terminal_marks) > MAX_FOCUS_INSIGHT_SENTENCES
    ) or not re.search(r"[。！？!?]$", analysis):
        return (
            f"AI分析分类必须精炼为一至两句、总长不超过{MAX_FOCUS_INSIGHT_CHARS}字："
            f"{domain}.{focus_id}"
        )
    if _contains_action_advice(analysis):
        return f"AI分析分类含行动建议而非数据洞察：{domain}.{focus_id}"
    if (domain, focus_id) in _OVERVIEW_STRATEGIC_HEADLINES and not any(
        term in analysis for term in _OVERVIEW_STRATEGIC_MEANING_TERMS
    ):
        return f"AI分析分类仍停留在报数，缺少当前格子的战略意义：{domain}.{focus_id}"
    if (domain, focus_id) in _OVERVIEW_STRATEGIC_HEADLINES and "不能纳入这一判断" in analysis:
        return f"AI分析引用有效竞对数值后又排除该竞对，判断自相矛盾：{domain}.{focus_id}"
    unsupported_causal = tuple(
        term for term in ("导致", "造成", "推动", "带来", "源于", "驱动")
        if term in analysis and not any(boundary in analysis for boundary in ("不能判断", "无法判断", "不能建立", "不代表"))
    )
    if unsupported_causal:
        return f"AI分析分类使用了未经证据支持的因果词{unsupported_causal}：{domain}.{focus_id}"
    focus_numbers = _focus_value_tokens(evidence_focus)
    analysis_numbers = _numeric_tokens(analysis)
    focus_items = [item for item in evidence_focus.get("items") or [] if isinstance(item, dict)]
    has_disclosed_value = any(
        item.get("value") not in (None, "", "-")
        or any(point.get("value") not in (None, "", "-") for point in item.get("trend") or [] if isinstance(point, dict))
        for item in focus_items
    )
    if focus_numbers and has_disclosed_value and not (focus_numbers & analysis_numbers):
        return f"AI分析分类缺少输入数值证据：{domain}.{focus_id}"
    if (domain, focus_id) == ("local", "financials"):
        companies_by_period: dict[str, int] = {}
        financial_items = [item for item in evidence_focus.get("items") or [] if isinstance(item, dict)]
        company_mentions: list[tuple[int, int, int]] = []
        for item_index, item in enumerate(financial_items):
            company = str(item.get("name") or "").strip()
            aliases = sorted(
                {alias for alias in (company, company.split("/")[0].strip()) if alias},
                key=len,
                reverse=True,
            )
            for alias in aliases:
                company_mentions.extend(
                    (match.start(), match.end(), item_index)
                    for match in re.finditer(re.escape(alias), analysis, flags=re.IGNORECASE)
                )
        company_mentions.sort(key=lambda mention: (mention[0], -(mention[1] - mention[0])))
        distinct_mentions: list[tuple[int, int, int]] = []
        for mention in company_mentions:
            if distinct_mentions and mention[0] == distinct_mentions[-1][0]:
                continue
            distinct_mentions.append(mention)
        company_segments: dict[int, list[str]] = {}
        for mention_index, (start, _, item_index) in enumerate(distinct_mentions):
            segment_end = (
                distinct_mentions[mention_index + 1][0]
                if mention_index + 1 < len(distinct_mentions)
                else len(analysis)
            )
            company_segments.setdefault(item_index, []).append(analysis[start:segment_end].replace(",", ""))

        for item_index, item in enumerate(financial_items):
            if not isinstance(item, dict):
                continue
            company_value_mentioned = False
            components = [component for component in item.get("components") or [] if isinstance(component, dict)]
            for component in components:
                if not isinstance(component, dict) or str(component.get("metric_key") or "") not in {
                    "revenue", "net_profit", "ebitda", "capital_expenditure",
                }:
                    continue
                value_match = re.search(
                    r"[-+]?\d[\d,]*(?:\.\d+)?",
                    str(component.get("value") or ""),
                )
                if value_match:
                    normalized_value = value_match.group().replace(",", "")
                    if any(
                        re.search(rf"(?<![\d.]){re.escape(normalized_value)}(?![\d.])", segment)
                        for segment in company_segments.get(item_index, [])
                    ):
                        company_value_mentioned = True
            if company_segments.get(item_index) and company_value_mentioned:
                component_period = next(
                    (str(component.get("detail") or "").strip() for component in components if component.get("detail")),
                    "",
                )
                period = component_period or str(item.get("period") or item.get("detail") or "期间待核").split("·", 1)[0].strip()
                companies_by_period[period] = companies_by_period.get(period, 0) + 1
        if max(companies_by_period.values(), default=0) < 2:
            return f"财务战略解读必须比较同期间至少两家公司各自的经营数值：{domain}.{focus_id}"
        if re.search(r"不纳入同一期间|不作同一期间|非同期间", analysis):
            return f"财务战略解读与已校验的同期间比较矛盾：{domain}.{focus_id}"
        if re.search(r"披露|发布|数量|密度|完整度", analysis):
            return f"财务战略解读不得以发布时间或披露数量代替经营指标：{domain}.{focus_id}"
    if not _has_deep_interpretation(analysis):
        return f"AI分析分类缺少结构、驱动或可比性解释：{domain}.{focus_id}"
    restriction_phrases = (
        "缺失值不估算", "缺失数据不估算", "只比较已结构化", "仅比较已结构化",
        "用于判断", "用于识别", "用于展示", "展示可分析", "此处比较", "聚焦云业务",
        "高增长集中", "说明存在差异", "说明存在差距",
    )
    if any(phrase in analysis for phrase in restriction_phrases):
        return f"AI分析分类仍以方法说明代替洞察：{domain}.{focus_id}"
    forbidden_by_focus = {
        ("local", "scale"): (
            "赛道", "月费", "资费区间", "重叠", "交集", "资本负担", "利润转化",
            "增长质量", "购买力", "服务压力", "存量竞争", "爆款", "套餐",
        ),
        ("local", "fibre_value"): ("增长质量", "低价吸引", "全市场覆盖"),
        ("local", "overlap"): ("增长质量", "增长能力"),
        ("international", "revenue"): ("EBITDA", "利润", "资本", "用户", "ARPU", "ARPA"),
        ("international", "ebitda"): ("净利润", "用户", "ARPU", "ARPA", "资本开支", "利润率", "增速", "同比"),
        ("international", "net_profit"): ("EBITDA", "用户", "ARPU", "ARPA", "资本开支", "利润率", "增速", "同比"),
        ("international", "postpaid_arpu"): ("EBITDA", "净利润", "资本开支"),
    }
    forbidden_terms = forbidden_by_focus.get((domain, focus_id), ())
    leaked_terms = [term for term in forbidden_terms if term in analysis]
    if leaked_terms:
        return (
            f"AI分析分类混入其他页维度{leaked_terms}：{domain}.{focus_id}"
        )
    if domain == "international" and focus_id in {"revenue", "ebitda", "net_profit", "postpaid_arpu"}:
        mentioned = {
            str(item.get("name") or "")
            for item in evidence_focus.get("items") or []
            if str(item.get("name") or "") and str(item.get("name") or "") in analysis
        }
        if len(mentioned) < 2:
            return f"国际运营商AI解读必须引用至少两家公司原值：{domain}.{focus_id}"
        if focus_id == "postpaid_arpu":
            if not all(term in analysis for term in ("Verizon", "ARPA", "NTT Group", "手机订阅")):
                return f"后付费用户数解读必须保留Verizon ARPA与NTT手机订阅替代口径：{domain}.{focus_id}"
            items = [item for item in evidence_focus.get("items") or [] if isinstance(item, dict)]
            positions = sorted(
                (analysis.find(str(item.get("name") or "")), item)
                for item in items
                if str(item.get("name") or "") and str(item.get("name") or "") in analysis
            )
            paired_companies = 0
            for index, (start, item) in enumerate(positions):
                end = positions[index + 1][0] if index + 1 < len(positions) else len(analysis)
                segment = analysis[start:end]
                components = item.get("components") or []
                arpu_component = next(
                    (component for component in components if "ARPU/ARPA" in str(component.get("label") or "")),
                    None,
                )
                main_value = _display_number(item.get("value"))
                arpu_value = _display_number((arpu_component or {}).get("value"))
                if main_value in segment and arpu_value in segment:
                    paired_companies += 1
            if paired_companies < 2:
                return f"后付费用户数解读必须把至少两家公司的用户数与各自ARPU或ARPA正确配对：{domain}.{focus_id}"
    if (domain, focus_id) == ("local", "mobile_price"):
        ranges = [
            (float(item["low"]), float(item["high"]))
            for item in evidence_focus.get("items") or []
            if isinstance(item, dict)
            and isinstance(item.get("low"), (int, float))
            and isinstance(item.get("high"), (int, float))
        ]
        has_overlap = any(
            max(left[0], right[0]) <= min(left[1], right[1])
            for index, left in enumerate(ranges)
            for right in ranges[index + 1:]
        )
        if has_overlap and any(phrase in analysis for phrase in ("未重合", "没有重合", "无重合")):
            return (
                f"AI分析分类与输入价格区间矛盾：{domain}.{focus_id}"
            )
    if (domain, focus_id) == ("local", "overlap"):
        mentions_mobile = "个人5G" in analysis
        mentions_fibre = "光纤家宽" in analysis
        if mentions_mobile and not mentions_fibre and any(name in analysis for name in ("HKBN", "i-CABLE")):
            return f"AI分析分类把家宽主体混入个人5G：{domain}.{focus_id}"
        if mentions_fibre and not mentions_mobile and any(name in analysis for name in ("3HK", "SmarTone")):
            return f"AI分析分类把个人5G主体混入家宽：{domain}.{focus_id}"
        if "HGC区间独立" in analysis:
            return f"AI分析分类把未发现重合误写为区间独立：{domain}.{focus_id}"
    if (domain, focus_id) == ("cloud", "profit") and re.search(
        r"(?:七|7)家中仅(?:六|6)家", analysis
    ):
        return f"AI分析分类自行统计了样本家数：{domain}.{focus_id}"
    return ""


def _repair_generated_focus_analysis(
    analysis: str,
    allowed_numeric_evidence: dict[str, Any],
) -> tuple[str, bool]:
    """Repair common model formatting slips without inventing a new judgement."""
    repaired = re.sub(r"\s+", " ", str(analysis or "")).strip()
    original = repaired
    allowed_numbers = _numeric_tokens(allowed_numeric_evidence)
    unknown_numbers = _numeric_tokens(repaired) - allowed_numbers
    for number in sorted(unknown_numbers, key=len, reverse=True):
        # Models often subtract two admitted percentages despite an explicit ban.
        # Keep the qualitative comparison and remove only that derived result.
        derived_difference = re.compile(
            rf"(?:仅|只)?(?:相差|差距(?:仅|为|仅为)?|差|高出|低于)\s*"
            rf"{re.escape(number)}\s*(?:个?百分点|%|港元/月|港元|倍|个)?"
        )
        repaired = derived_difference.sub("存在差距", repaired)

    if len(repaired) > MAX_FOCUS_INSIGHT_CHARS:
        # A trailing disclosure caveat is useful but lower priority when the same
        # sample boundary is already stated earlier in the sentence.
        repaired = re.sub(
            r"[，；][^，；。！？]*(?:未披露|未提供|数据缺失)[^。！？]*[。！？]$",
            "。",
            repaired,
        )
    if len(repaired) > MAX_FOCUS_INSIGHT_CHARS:
        repaired = re.sub(r"[，；]?样本(?:仅|限于)[^，；。！？]*[，；]", "，", repaired, count=1)
    repaired = re.sub(r"[，；]{2,}", "，", repaired).strip("，； ")
    if repaired and not re.search(r"[。！？!?]$", repaired):
        repaired += "。"
    return repaired, repaired != original


def _compact_generated_focus_analysis(
    domain_id: str,
    focus_id: str,
    analysis: str,
    evidence_focus: dict[str, Any],
    allowed_numeric_evidence: dict[str, Any],
) -> tuple[str, bool]:
    """Select the strongest evidence-bearing clauses from an overlong AI answer."""
    normalized = re.sub(r"\s+", " ", str(analysis or "")).strip()
    if not normalized:
        return normalized, False
    if not _focus_gate_error(domain_id, focus_id, normalized, evidence_focus):
        return normalized, False

    clauses = [
        clause.strip(" ，；。！？!?\t")
        for clause in re.split(r"[，；。！？!?]+", normalized)
        if clause.strip(" ，；。！？!?\t")
    ]
    if len(clauses) < 2:
        return normalized, False
    # Exhaustive subsequence search is bounded to keep regeneration latency
    # predictable. Model answers are already capped at a few short sentences.
    if len(clauses) > 12:
        clauses = [*clauses[:2], *clauses[-10:]]
    allowed_numbers = _numeric_tokens(allowed_numeric_evidence)
    candidates: list[tuple[tuple[int, int, int, int, int], str]] = []
    for size in range(2, len(clauses) + 1):
        for indices in itertools.combinations(range(len(clauses)), size):
            selected_clauses = [clauses[index] for index in indices]
            if any(re.match(r"^(?:不纳入|未纳入)(?:比较|排名)?$", clause) for clause in selected_clauses):
                continue
            candidate = "，".join(selected_clauses) + "。"
            if len(candidate) > MAX_FOCUS_INSIGHT_CHARS:
                continue
            if _numeric_tokens(candidate) - allowed_numbers:
                continue
            if _focus_gate_error(domain_id, focus_id, candidate, evidence_focus):
                continue
            evidence_count = len(_numeric_tokens(candidate) & allowed_numbers)
            numeric_mentions = re.findall(r"(?<![\d.])[-+]?\d+(?:\.\d+)?", candidate)
            duplicate_numbers = len(numeric_mentions) - len({f"{float(value):g}" for value in numeric_mentions})
            interpretive_count = sum(term in candidate for term in _INTERPRETIVE_CONNECTORS)
            business_count = sum(
                term in candidate
                for term in (*_ANALYTICAL_JUDGEMENT_TERMS, *_INTERPRETIVE_DIMENSIONS, *_DEEP_RELATION_MARKERS)
            )
            candidates.append((
                (evidence_count, -duplicate_numbers, business_count, interpretive_count, -len(candidate)),
                candidate,
            ))
    if not candidates:
        return normalized, False
    return max(candidates, key=lambda item: item[0])[1], True


def _final_grounded_focus_repair(
    domain_id: str,
    focus: dict[str, Any],
    *,
    regeneration_index: int,
    recent_insights: list[str],
) -> str | None:
    """Return a fresh, gated evidence repair after all model prose attempts fail."""
    seed = _compact_grounded_focus_analysis(domain_id, focus)
    allowed_numeric_evidence = {
        "metric": focus.get("metric"),
        "items": [
            {
                "name": item.get("name"),
                "value": item.get("value"),
                "unit": item.get("unit"),
                "detail": item.get("detail"),
                "analysis": item.get("analysis"),
            }
            for item in focus.get("items") or []
            if isinstance(item, dict)
        ],
    }
    prefixes = ("按当前可比口径，", "从同口径样本看，", "就当前披露边界而言，", "从当前数据关系看，")
    candidates = [seed]
    clauses = [part.strip() for part in re.split(r"[；。]", seed) if part.strip()]
    for offset in range(len(prefixes)):
        prefix = prefixes[(max(1, regeneration_index) - 1 + offset) % len(prefixes)]
        ordered = clauses[offset % len(clauses):] + clauses[:offset % len(clauses)] if clauses else [seed]
        candidates.append(prefix + "；".join(ordered) + "。")
    recent = {re.sub(r"\s+", "", str(value or "")) for value in recent_insights}
    for candidate in candidates[1:] + candidates[:1]:
        candidate, _ = _repair_generated_focus_analysis(candidate, allowed_numeric_evidence)
        candidate, _ = _compact_generated_focus_analysis(
            domain_id, str(focus.get("id") or ""), candidate, focus, allowed_numeric_evidence,
        )
        if _focus_gate_error(domain_id, str(focus.get("id") or ""), candidate, focus):
            continue
        if re.sub(r"\s+", "", candidate) in recent:
            continue
        return candidate
    return None


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
            # Numeric anchoring is allowed only for prose that already contains a
            # deep interpretation; it cannot turn filler or advice into insight.
            if not _has_deep_interpretation(analysis):
                continue
            metric = evidence_focus.get("metric") if isinstance(evidence_focus.get("metric"), dict) else {}
            value = metric.get("value")
            label = str(metric.get("label") or "最新指标")
            if value in (None, "", "-", "—") or any(
                placeholder in label for placeholder in ("待补", "未披露", "暂无")
            ):
                continue
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
    """Replace shallow numeric prose with an evidence-grounded deep interpretation."""
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
            if not analysis or _has_deep_interpretation(analysis):
                continue
            if not (_numeric_tokens(analysis) & _focus_value_tokens(evidence_focus)):
                continue
            if not any(term in analysis for term in _ANALYTICAL_JUDGEMENT_TERMS):
                continue
            focus["analysis"] = _compact_grounded_focus_analysis(domain_id, evidence_focus)
            focus["deep_interpretation_repaired"] = True
    return repaired


def _repair_focus_conciseness(raw: Any, evidence: dict[str, Any]) -> Any:
    """Keep one or two concise deep-insight sentences, otherwise use grounded fallback."""
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
            candidate = re.sub(r"\s+", " ", original).strip()
            if candidate and not re.search(r"[。！？!?]$", candidate):
                candidate += "。"
            if not _focus_gate_error(domain_id, focus_id, candidate, evidence_focus):
                focus["analysis"] = candidate
            else:
                focus["analysis"] = _compact_grounded_focus_analysis(domain_id, evidence_focus)
            if focus["analysis"] != original:
                focus["deep_format_repaired"] = True
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


def _validate_model_summaries(
    raw: Any,
    evidence: dict[str, Any],
    *,
    expected_domains: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("AI分析没有返回items数组")
    expected = expected_domains or {
        str(domain.get("id") or "") for domain in evidence.get("domains") or [] if str(domain.get("id") or "")
    }
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
                    "headline": str(focus_item.get("headline") or "").strip(),
                    "analysis": str(focus_item.get("analysis") or "").strip(),
                    "risk": str(focus_item.get("risk") or "").strip(),
                    "source_urls": [str(url) for url in focus_item.get("source_urls") or []],
                    "entities": [],
                }
                if str(focus_item.get("origin") or "") == "evidence_rule":
                    validated_focus["origin"] = "evidence_rule"
                if not validated_focus["analysis"] or not validated_focus["risk"]:
                    raise ValueError(f"AI分析分类字段不完整：{domain}.{focus_id}")
                if (domain, focus_id) in _OVERVIEW_STRATEGIC_HEADLINES and (
                    not validated_focus["headline"]
                    or any(term in validated_focus["headline"] for term in _OVERVIEW_DIRECT_HEADLINE_TERMS)
                ):
                    validated_focus["headline"] = _strategic_focus_headline(domain, focus_id)
                if (domain, focus_id) == ("local", "financials") and any(
                    term in validated_focus["headline"]
                    for term in ("披露", "发布", "数量", "密度", "完整度", "口径", "边界")
                ):
                    raise ValueError("财务战略解读标题不得以披露或口径说明为结论：local.financials")
                evidence_focus = next(
                    focus for focus in (evidence_by_domain.get(domain, {}).get("focuses") or [])
                    if str(focus.get("id") or "") == focus_id
                )
                if validated_focus["headline"] and re.sub(r"\s+", "", validated_focus["headline"]) == re.sub(
                    r"\s+", "", str(evidence_focus.get("label") or "")
                ):
                    validated_focus["headline"] = str(evidence_focus.get("headline") or "").strip()
                unknown_focus_urls = set(validated_focus["source_urls"]) - allowed_urls
                if unknown_focus_urls:
                    raise ValueError(f"AI分析分类引用了输入之外的来源：{sorted(unknown_focus_urls)}")
                unknown_focus_numbers = _numeric_tokens(validated_focus) - allowed_numbers
                if unknown_focus_numbers:
                    raise ValueError(f"AI分析分类出现输入之外的数字：{sorted(unknown_focus_numbers)}")
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
    domain_order = {
        str(domain.get("id") or ""): index
        for index, domain in enumerate(evidence.get("domains") or [])
    }
    return sorted(result, key=lambda item: domain_order.get(item["domain"], len(domain_order)))


def _evidence_urls_by_domain(evidence: dict[str, Any]) -> dict[str, set[str]]:
    urls: dict[str, set[str]] = {
        str(domain.get("id") or ""): set()
        for domain in evidence.get("domains") or [] if str(domain.get("id") or "")
    }
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


def _repair_discovery_conciseness(raw: Any) -> Any:
    """Fit otherwise valid model discoveries into the published card contract."""
    if not isinstance(raw, list):
        return raw

    def clip(value: Any, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        clauses = [part.strip() for part in re.split(r"(?<=[。！？；;])", text) if part.strip()]
        kept: list[str] = []
        for clause in clauses:
            candidate = "".join([*kept, clause])
            if len(candidate) > limit:
                break
            kept.append(clause)
        if kept:
            return "".join(kept).strip()
        return text[:limit].rstrip("，、；;：: ")

    repaired: list[Any] = []
    for item in raw:
        if not isinstance(item, dict):
            repaired.append(item)
            continue
        title = clip(item.get("title"), 28)
        detail = clip(item.get("detail"), 110)
        if not any(term in f"{title}。{detail}" for term in _INTERPRETIVE_CONNECTORS):
            detail = clip(f"这表明{detail}", 110)
        repaired.append({
            **item,
            "title": title,
            "detail": detail,
            "kind": clip(item.get("kind") or "AI综合研判", 12),
        })
    return repaired


def _validate_model_discoveries(raw: Any, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError("AI跨库发现必须恰好返回四项")
    expected_domains = {
        str(domain.get("id") or "") for domain in evidence.get("domains") or [] if str(domain.get("id") or "")
    }
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
        combined_text = f'{discovery["title"]}。{discovery["detail"]}'
        if _contains_action_advice(combined_text):
            raise ValueError("AI跨库发现含行动建议而非数据洞察")
        if allowed_numbers:
            if not (_numeric_tokens(combined_text) & allowed_numbers):
                raise ValueError("AI跨库发现缺少输入数值证据")
            if not _has_deep_interpretation(combined_text):
                raise ValueError("AI跨库发现缺少结构、驱动或跨领域关系解释")
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


def _display_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _ranked_focus_items(focus: dict[str, Any]) -> list[dict[str, Any]]:
    def numeric_rank(item: dict[str, Any]) -> float:
        value = item.get("value")
        try:
            return float(value)
        except (TypeError, ValueError):
            match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
            return float(match.group()) if match else float("-inf")

    return sorted(
        [item for item in focus.get("items") or [] if isinstance(item, dict) and item.get("value") not in (None, "")],
        key=numeric_rank,
        reverse=True,
    )


def _compact_grounded_focus_analysis(domain: str, focus: dict[str, Any]) -> str:
    focus_id = str(focus.get("id") or "")
    items = _ranked_focus_items(focus)
    by_name = {str(item.get("name") or ""): item for item in items}
    metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
    metric_value = _display_number(metric.get("value"))
    metric_unit = str(metric.get("unit") or "")
    strategic_fallback = str(focus.get("insight") or "").strip()
    if domain in {"local", "mainland"} and focus_id in {"revenue", "ebitda", "net_profit", "postpaid"}:
        if len(items) >= 2:
            high, low = items[0], items[-1]
            high_name, low_name = str(high.get("name") or ""), str(low.get("name") or "")
            high_value, low_value = _display_number(high.get("value")), _display_number(low.get("value"))
            unit = str(high.get("unit") or low.get("unit") or "")
            if focus_id == "revenue":
                return (
                    f"{high_name} FY2025营收{high_value}{unit}，{low_name}{low_value}{unit}；"
                    "收入底盘断层意味着头部可承受更高强度的网络与客户获取投入，尾部同等资源消耗下经营容错更低；规模不等同效率。"
                )
            if focus_id == "ebitda":
                return (
                    f"{high_name} FY2025 EBITDA为{high_value}{unit}，{low_name}{low_value}{unit}；"
                    "盈利缓冲断层意味着头部持续投入与承受价格竞争的空间更厚，尾部防守容错更窄；EBITDA不等同现金流。"
                )
            if focus_id == "net_profit":
                low_signal = "已为负值" if float(low.get("value") or 0) < 0 else "位于样本尾部"
                return (
                    f"{high_name} FY2025净利润{high_value}{unit}，{low_name}{low_value}{unit}且{low_signal}；"
                    "利润池断层意味着头部具备更强自我融资与再投资空间，尾部在价格竞争中的盈利防线更薄。"
                )
            return (
                f"{high_name} FY2025移动客户{high_value}{unit}，{low_name}{low_value}{unit}；"
                "客户覆盖底盘形成梯队，意味着头部具备更广的交叉销售与网络规模摊薄基础；未结合ARPU与活跃度仍不能判断客户价值。"
            )
        if focus_id == "postpaid":
            named = "、".join(str(item.get("name") or "") for item in focus.get("items") or [] if item.get("name"))
            return (
                f"{named}当前均缺少可比移动客户原值；披露不足使客户覆盖底盘无法穿透比较，"
                "且不能由5G用户数替代集团移动客户总数。"
            )
    if domain == "international" and focus_id in {"revenue", "ebitda", "net_profit", "postpaid_arpu"} and items:
        high, low = items[0], items[-1]
        high_name, low_name = str(high.get("name") or ""), str(low.get("name") or "")
        high_value, low_value = _display_number(high.get("value")), _display_number(low.get("value"))
        if focus_id == "revenue":
            return (
                f"{high_name} FY2025营收{high_value}十亿美元，{low_name}{low_value}十亿美元，"
                "收入底盘分层意味着跨国网络、渠道与客户获取投入的承载空间不同；营收规模仍不等同盈利能力。"
            )
        if focus_id == "ebitda":
            return (
                f"{high_name} EBITDA约{high_value}十亿美元，{low_name}约{low_value}十亿美元，"
                "盈利缓冲分层意味着网络投入与价格竞争的经营容错不同；非GAAP调整口径仍不可直接等同。"
            )
        if focus_id == "net_profit":
            return (
                f"{high_name} FY2025净利润约{high_value}十亿美元，{low_name}约{low_value}十亿美元，"
                "利润池分层意味着自我融资、再投资与周期防守空间不同；绝对值仍不等同盈利效率。"
            )
        verizon = by_name.get("Verizon") or high
        ntt = by_name.get("NTT Group") or low
        verizon_arpu = next(
            (component.get("value") for component in verizon.get("components") or [] if "ARPU/ARPA" in str(component.get("label") or "")),
            None,
        )
        ntt_arpu = next(
            (component.get("value") for component in ntt.get("components") or [] if "ARPU/ARPA" in str(component.get("label") or "")),
            None,
        )
        return (
            f"Verizon {_display_number(verizon.get('value'))}百万连接、ARPA {_display_number(verizon_arpu)}美元/月；"
            f"NTT Group {_display_number(ntt.get('value'))}百万手机订阅替代口径、ARPU {_display_number(ntt_arpu)}美元/月。"
            "客户基础与客户价值错位，意味着客户质量不能只看规模；口径不同不可混排。"
        )
    if strategic_fallback and _has_deep_interpretation(strategic_fallback):
        return strategic_fallback

    if (domain, focus_id) == ("local", "scale") and items:
        record_leader = max(items, key=lambda item: float(item.get("record_count") or item.get("value") or 0))
        unique_leader = max(items, key=lambda item: float(item.get("component_count") or 0))
        return (
            f"{record_leader.get('name')}有{_display_number(record_leader.get('record_count') or record_leader.get('value'))}条记录，"
            f"但唯一方案仅{_display_number(record_leader.get('component_count'))}个、低于{unique_leader.get('name')}的"
            f"{_display_number(unique_leader.get('component_count'))}个，表面规模优势主要来自记录重复而非产品广度。"
        )
    if (domain, focus_id) == ("local", "track") and len(items) >= 2:
        leaders = [str(item.get("name") or "") for item in items if item.get("value") == items[0].get("value")]
        return (
            f"{'与'.join(leaders[:2])}均覆盖{_display_number(items[0].get('value'))}个赛道，"
            "但组合分别集中于移动/漫游与企业/家宽，广度相同并不等同于直接产品重叠。"
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
            return (
                f"{low[1]}{_display_number(low[2])}至{high[1]}{_display_number(high[2])}{unit}看似相差{gap_text}{unit}，"
                "但混合了通行证、家宽与移动套餐，价格梯度主要反映产品类型而非单纯品牌溢价。"
            )
    if (domain, focus_id) == ("local", "overlap"):
        return (
            f"最多仅重叠{metric_value}{metric_unit}，且交集分散在个人5G、企业移动与家宽，"
            "说明本地竞争仍是分赛道交锋，并未形成全产品线正面重叠。"
        )
    if (domain, focus_id) == ("international", "growth") and items:
        high, low = items[0], items[-1]
        return (
            f"四家最新增速从{_display_number(high.get('value'))}%到{_display_number(low.get('value'))}%，"
            "正负并存表明行业已由同步扩张转为收入结构分化。"
        )
    if (domain, focus_id) == ("international", "momentum") and items:
        high, low = items[0], items[-1]
        return (
            f"四家动量全部为负，介于{_display_number(high.get('value'))}至{_display_number(low.get('value'))}个百分点，"
            "说明本期并非个别公司波动，而是行业增长同步降速。"
        )
    if (domain, focus_id) == ("international", "investment") and items:
        comparable = items
        if comparable:
            high, low = comparable[0], comparable[-1]
            return (
                f"资本开支占营收从{_display_number(high.get('value'))}%到{_display_number(low.get('value'))}%，"
                "按同期收入归一后仍呈结构性差异，且不能直接等同投资回报高低。"
            )
    if (domain, focus_id) == ("international", "disclosure") and items:
        high, low = items[0], items[-1]
        return (
            f"披露最多{_display_number(high.get('value'))}项、最少{_display_number(low.get('value'))}项，差距有限，"
            "说明公开信息广度并不能解释经营质量高低。"
        )
    if (domain, focus_id) == ("cloud", "revenue") and items:
        high, low = items[0], items[-1]
        return (
            f"最高的{high.get('name')} FY2024云收入{_display_number(high.get('value'))}百万美元，"
            f"最低的{low.get('name')}{_display_number(low.get('value'))}百万美元；"
            "云收入底盘断层意味着头部具备更强生态扩张与基础设施持续投入空间；代理分部与重分类口径仍不能直接等同。"
        )
    if (domain, focus_id) == ("cloud", "trend") and items:
        high, low = items[0], items[-1]
        return (
            f"增速变化从{_display_number(high.get('value'))}到{_display_number(low.get('value'))}个百分点，"
            "说明当前梯队变化主要来自二线厂商再加速，而非全行业同步回暖。"
        )
    if (domain, focus_id) == ("cloud", "profit") and items:
        direct = [item for item in items if "经营利润" in str(item.get("detail") or "")]
        high, low = (direct[0], direct[-1]) if len(direct) >= 2 else (items[0], items[-1])
        return (
            f"同属经营利润披露的{high.get('name')} FY2024为{_display_number(high.get('value'))}百万美元，"
            f"{low.get('name')}为{_display_number(low.get('value'))}百万美元；利润池向头部集中并形成主导梯队，意味着头部可用更厚盈利缓冲支撑再投资与价格竞争。"
        )
    if (domain, focus_id) == ("cloud", "investment") and items:
        high, low = items[0], items[-1]
        return (
            f"{high.get('name')} FY2024集团资本开支{_display_number(high.get('value'))}百万美元，"
            f"{low.get('name')}{_display_number(low.get('value'))}百万美元；资本军备能力明显分层，意味着基础设施扩张承载空间不同，"
            "但集团投入并非云业务单独投入，不能据此判断投入转化效率。"
        )
    if (domain, focus_id) == ("cloud", "disclosure"):
        return (
            f"{metric_value}项披露混合直接分部、代理分部与综合口径，"
            "表明数据丰富度上升并未消除跨厂商可比性断层。"
        )
    if (domain, focus_id) == ("macro", "market"):
        broadband = by_name.get("移动宽带用户", {})
        household = by_name.get("家庭宽带渗透率", {})
        return (
            f"移动连接{metric_value}万与移动宽带{_display_number(broadband.get('value'))}万几乎重合，"
            f"家庭宽带渗透率已达{_display_number(household.get('value'))}%，说明连接市场接近饱和，增量不再来自基础覆盖。"
        )
    if (domain, focus_id) == ("macro", "traffic"):
        per_sub = by_name.get("每移动宽带用户流量", {})
        per_capita = by_name.get("人均移动流量", {})
        return (
            f"人均流量{_display_number(per_capita.get('value'))}GB远高于每移动宽带用户"
            f"{_display_number(per_sub.get('value'))}GB，差异来自多连接口径，流量总量不能等同单用户使用强度。"
        )
    if (domain, focus_id) == ("macro", "spending"):
        cpi = by_name.get("甲类消费物价指数", {})
        return (
            f"家庭月入中位数{metric_value}港元而甲类消费物价指数为{_display_number(cpi.get('value'))}，"
            "说明名义消费规模与实际套餐可负担力并不等价，购买力受价格水平约束。"
        )
    if (domain, focus_id) == ("macro", "governance"):
        complaints = by_name.get("电讯投诉", {})
        coverage = by_name.get("5G人口覆盖", {})
        return (
            f"5G覆盖已超过{_display_number(coverage.get('value'))}%仍有{_display_number(complaints.get('value'))}宗投诉，"
            "说明网络竞争瓶颈已从覆盖可达性转为服务质量与体验一致性。"
        )
    label = str(metric.get("label") or focus.get("label") or "最新指标")
    if metric_value:
        return f"{label}{metric_value}{metric_unit}与同组差异并存，数据结构表明绝对规模不能单独解释竞争质量。"
    numbers = sorted(_focus_value_tokens(focus), key=lambda item: float(item))
    anchor = numbers[0] if numbers else ""
    return (
        f"当前值{anchor}与同组差异并存，数据结构表明绝对规模不能单独解释竞争质量。"
        if anchor else "现有证据结构不完整，尚不能形成可比的深层结论。"
    )


def _deterministic_focus_analysis(domain: str, focus: dict[str, Any]) -> str:
    """Produce a numerically grounded fallback that must pass the full focus gate."""
    return _compact_grounded_focus_analysis(domain, focus)


def _deterministic_domain_summaries(
    evidence: dict[str, Any], *, validate: bool = True,
) -> list[dict[str, Any]]:
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
                        "headline": _strategic_focus_headline(
                            str(domain.get("id") or ""),
                            str(focus.get("id") or ""),
                            focus.get("headline"),
                        ),
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
    return _validate_model_summaries(summaries, evidence) if validate else summaries


def _deterministic_discoveries(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    urls_by_domain = _evidence_urls_by_domain(evidence)
    focuses = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }

    def metric(domain_id: str, focus_id: str) -> tuple[str, str]:
        focus = focuses.get((domain_id, focus_id)) or {}
        value = focus.get("metric", {}).get("value") if isinstance(focus.get("metric"), dict) else ""
        unit = focus.get("metric", {}).get("unit") if isinstance(focus.get("metric"), dict) else ""
        return _display_number(value), str(unit or "")

    def period(domain_id: str, focus_id: str) -> str:
        focus = focuses.get((domain_id, focus_id)) or {}
        metric_payload = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
        match = re.search(r"FY(20\d{2})", str(metric_payload.get("label") or ""))
        return f"FY{match.group(1)}" if match else "最新披露期"

    local_revenue, local_revenue_unit = metric("local", "revenue")
    international_revenue, international_revenue_unit = metric("international", "revenue")
    cloud_revenue, cloud_revenue_unit = metric("cloud", "revenue")
    mainland_revenue, mainland_revenue_unit = metric("mainland", "revenue")
    mainland_postpaid, mainland_postpaid_unit = metric("mainland", "postpaid")
    local_period = period("local", "revenue")
    international_period = period("international", "revenue")
    mainland_period = period("mainland", "revenue")
    cloud_period = period("cloud", "revenue")
    relations = [
        {
            "from": "mainland", "to": "local", "title": f"{local_period}香港与内地财务口径分开",
            "detail": (
                f"内地营收卡片为{mainland_revenue}{mainland_revenue_unit}，香港为{local_revenue}{local_revenue_unit}；"
                f"两组均采用{mainland_period}/{local_period}最新已核验披露，但币种与主体范围结构不同；这表明数值高低不能直接等同经营质量。"
            ),
        },
        {
            "from": "international", "to": "cloud", "title": f"{cloud_period}云收入与运营商财务分口径",
            "detail": (
                f"云收入卡片为{cloud_revenue}{cloud_revenue_unit}，国际营收卡片为{international_revenue}{international_revenue_unit}；"
                f"分别采用{cloud_period}/{international_period}最新已核验披露，分部规模与集团财务口径结构不同，因此不能直接混合排名。"
            ),
        },
        {
            "from": "local", "to": "cloud", "title": f"{local_period}香港财务与云收入边界不同",
            "detail": (
                f"香港营收卡片为{local_revenue}{local_revenue_unit}，云收入卡片为{cloud_revenue}{cloud_revenue_unit}；"
                f"分别采用{local_period}/{cloud_period}最新已核验披露，公司整体与云分部范围结构不同；这表明两者不可直接比较。"
            ),
        },
        {
            "from": "mainland", "to": "international", "title": f"{mainland_period}内地与国际用户口径分开",
            "detail": (
                f"内地后付费用户数披露不足，国际营收卡片为{international_revenue}{international_revenue_unit}；"
                f"国际侧采用{international_period}最新披露；两者用户口径结构不同，因此不能直接拿移动用户总数替代后付费竞争判断。"
            ),
        },
    ]
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


def _safe_discovery_regeneration_fallback(
    evidence: dict[str, Any],
    source_domain: str,
    target_domain: str,
    *,
    current: dict[str, Any],
    regeneration_index: int,
) -> dict[str, Any] | None:
    """Rotate evidence-only cross-domain judgements when every model returns unusable output."""
    focuses = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }
    urls_by_domain = _evidence_urls_by_domain(evidence)

    def metric(domain_id: str, focus_id: str) -> str:
        focus = focuses.get((domain_id, focus_id)) or {}
        raw_metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
        return f"{_display_number(raw_metric.get('value'))}{str(raw_metric.get('unit') or '')}"

    def item_value(domain_id: str, focus_id: str, keyword: str) -> str:
        focus = focuses.get((domain_id, focus_id)) or {}
        for item in focus.get("items") or []:
            if keyword in str(item.get("name") or ""):
                return f"{_display_number(item.get('value'))}{str(item.get('unit') or '')}"
        return ""

    local_revenue = metric("local", "revenue")
    international_revenue = metric("international", "revenue")
    mainland_revenue = metric("mainland", "revenue")
    cloud_revenue = metric("cloud", "revenue")
    variants: dict[tuple[str, str], list[tuple[str, str]]] = {
        ("mainland", "local"): [
            (
                "香港与内地财务分口径",
                f"内地营收卡片{mainland_revenue}与香港营收卡片{local_revenue}分属不同币种和主体范围，"
                "说明绝对规模不能直接等同经营质量。",
            ),
            (
                "两地营收规模不能混排",
                f"香港营收卡片{local_revenue}与内地营收卡片{mainland_revenue}采用不同货币和企业范围，"
                "表明两组绝对值存在结构差异，只能在各自市场内解释。",
            ),
            (
                "香港与内地主体边界不同",
                f"内地营收{mainland_revenue}描述内地运营商集团，香港营收{local_revenue}描述本地运营主体，"
                "说明市场边界不同，金额高低不能直接比较。",
            ),
        ],
        ("international", "cloud"): [
            (
                "运营商与云收入分口径",
                f"国际运营商营收卡片{international_revenue}与云收入卡片{cloud_revenue}分属集团和分部口径，"
                "说明两域主体结构不同，绝对规模不能直接换算经营能力。",
            ),
            (
                "集团营收与云分部收入分层",
                f"国际运营商营收{international_revenue}与云收入{cloud_revenue}分属集团财务和业务分部，"
                "表明两者范围不同，不能按同一维度混排。",
            ),
            (
                "两类市场绝对规模分层",
                f"云收入{cloud_revenue}与国际运营商营收{international_revenue}分属不同主体和币种口径，"
                "说明两域形成分层信号，不能直接作经营效率比较。",
            ),
        ],
        ("local", "cloud"): [
            (
                "香港与云收入边界不同",
                f"香港营收卡片{local_revenue}衡量公司收入，云收入卡片{cloud_revenue}衡量云分部规模，"
                "说明两项指标存在主体和币种差异，不能直接比较。",
            ),
            (
                "公司营收不等同云分部收入",
                f"香港营收卡片为{local_revenue}，云收入卡片为{cloud_revenue}，"
                "表明公司整体与云分部属于不同口径，两者不能直接换算。",
            ),
            (
                "两类收入绝对值不能混排",
                f"香港营收{local_revenue}与云收入{cloud_revenue}分别描述公司整体和云分部绝对规模，"
                "说明两域指标主体、币种与范围不同。",
            ),
        ],
        ("mainland", "international"): [
            (
                "内地与国际客户口径分开",
                f"内地运营商营收卡片{mainland_revenue}与国际运营商营收卡片{international_revenue}采用不同币种和集团范围，"
                "说明绝对金额不能替代跨市场客户价值判断。",
            ),
            (
                "两类运营商披露边界不同",
                f"内地营收{mainland_revenue}与国际营收{international_revenue}覆盖不同企业和币种，"
                "表明两组集团收入不能混作统一客户价值排名。",
            ),
            (
                "内地与国际指标不可替代",
                f"国际营收卡片{international_revenue}与内地营收卡片{mainland_revenue}分属不同市场，"
                "说明两域收入规模不能用来互相替代用户质量判断。",
            ),
        ],
    }
    options = variants.get((source_domain, target_domain))
    if not options:
        return None
    source_urls = [
        sorted(urls_by_domain[domain_id])[0]
        for domain_id in (source_domain, target_domain)
        if urls_by_domain.get(domain_id)
    ]
    current_signature = tuple(re.sub(r"\s+", "", str(current.get(key) or "")) for key in ("title", "detail"))
    for offset in range(len(options)):
        title, detail = options[(regeneration_index + offset) % len(options)]
        candidate = {
            "from": source_domain,
            "to": target_domain,
            "title": title,
            "detail": detail,
            "kind": "数据证据解读",
            "source_urls": source_urls,
        }
        candidate_signature = tuple(re.sub(r"\s+", "", str(candidate.get(key) or "")) for key in ("title", "detail"))
        if candidate_signature != current_signature:
            return candidate
    return None


def _normalize_fresh_focus_headline(
    headline: Any,
    *,
    label: str,
    recent_headlines: list[str],
    forbidden_terms: tuple[str, ...] = (),
) -> str:
    """Fit a fresh model title to the card without discarding valid analysis."""
    normalized = str(headline or "").replace("5G", "五G").replace("5g", "五G")
    normalized = re.sub(r"[\s\d０-９％%。，,；;：:！？!?（）()【】\[\]、]", "", normalized)
    normalized = re.sub(
        r"(个百分点|港元|亿元|万元|万户|万项|MHz|MB|GB|项|个)$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = (
        normalized
        .replace("中国联通", "联通")
        .replace("中国移动", "移动")
        .replace("中国电信", "电信")
        .replace("资本投入强度", "投入强度")
        .replace("五G", "5G")
    )
    if len(normalized) > 14:
        normalized = re.sub(r"(增长质量|经营质量|竞争质量|市场表现)$", "", normalized)
    candidates = [
        normalized if len(normalized) <= 14 else "",
        f"{label}关系重新判断"[:14],
        f"{label}口径边界显现"[:14],
        f"{label}结构重新分化"[:14],
        "数据关系出现新分层",
        "口径边界重新显现",
    ]
    recent = [re.sub(r"\s+", "", str(value or "")) for value in recent_headlines]
    for candidate in dict.fromkeys(candidates):
        if not (4 <= len(candidate) <= 14):
            continue
        if any(term in candidate for term in ("洞察", "研判", "格局分化", *forbidden_terms)):
            continue
        if _contains_action_advice(candidate):
            continue
        if max(
            (difflib.SequenceMatcher(None, previous, candidate).ratio() for previous in recent),
            default=0.0,
        ) >= 0.96:
            continue
        return candidate
    raise ValueError(f"无法生成与最近版本不同的短标题：{str(headline or '')[:40]}")


def _safe_focus_regeneration_fallback(
    domain_id: str,
    focus: dict[str, Any],
    *,
    regeneration_index: int,
    recent_insights: list[str],
) -> dict[str, Any] | None:
    """Return rotating evidence-only judgements when every model attempt fails."""
    focus_id = str(focus.get("id") or "")
    supported = {
        ("macro", "service"),
        ("international", "growth"),
    }
    if (domain_id, focus_id) not in supported:
        return None
    items = {
        str(item.get("name") or ""): item
        for item in focus.get("items") or []
        if isinstance(item, dict)
    }

    def value(name: str) -> str:
        return _display_number((items.get(name) or {}).get("value"))

    if (domain_id, focus_id) == ("macro", "service"):
        variants = [
            (
                "供给指标不等同服务改善",
                f"5G人口覆盖{value('5G人口覆盖')}、已分配公共移动及5G频谱{value('已分配公共移动及5G频谱')}MHz，"
                f"说明供给资源已处高位；电讯业投资同比{value('电讯业投资')}%与投诉同比{value('电讯投诉')}%的期间不同，"
                "不能据此判断投入是否转化为服务改善。",
            ),
            (
                "投入与投诉期间错位",
                f"电讯业投资同比{value('电讯业投资')}%反映截至2025-03-31的投入变化，"
                f"投诉同比{value('电讯投诉')}%反映截至2025-12-31的服务压力；两项期间不同，不能比较增速差距。",
            ),
            (
                "供给规模不代表服务质量",
                f"投诉同比{value('电讯投诉')}%只说明截至2025-12-31的服务压力变化；"
                f"5G人口覆盖{value('5G人口覆盖')}与频谱{value('已分配公共移动及5G频谱')}MHz是供给背景，"
                "不能等同服务质量改善。",
            ),
        ]
    else:
        variants = [
            (
                "营收增长分成正负两层",
                f"Q1 2026中国铁塔{value('中国铁塔')}%、中国移动{value('中国移动')}%仍为正增长，"
                f"中国联通{value('中国联通')}%、中国电信{value('中国电信')}%已转负，"
                "表明四家公司分成正负两层，行业并非同步扩张。",
            ),
            (
                "行业扩张已明显分化",
                f"中国铁塔{value('中国铁塔')}%与中国移动{value('中国移动')}%保持增长，"
                f"中国联通{value('中国联通')}%及中国电信{value('中国电信')}%下降，"
                "说明同一季度的收入方向已经分化，而非四家公司共同增长。",
            ),
            (
                "正增长仅集中于两家",
                f"Q1 2026四家公司中，中国铁塔{value('中国铁塔')}%和中国移动{value('中国移动')}%为正，"
                f"中国联通{value('中国联通')}%与中国电信{value('中国电信')}%为负；"
                "这说明增长只集中在两家，并非行业整体回升。",
            ),
        ]
    normalized_recent = [re.sub(r"\s+", "", str(item or "")) for item in recent_insights]
    start = (max(1, regeneration_index) - 1) % len(variants)
    for offset in range(len(variants)):
        headline, analysis = variants[(start + offset) % len(variants)]
        if _focus_gate_error(domain_id, focus_id, analysis, focus):
            continue
        similarity = max(
            (
                difflib.SequenceMatcher(None, previous, re.sub(r"\s+", "", analysis)).ratio()
                for previous in normalized_recent if previous
            ),
            default=0.0,
        )
        if similarity >= 0.84:
            continue
        return {
            "generated_at_hkt": _now(),
            "model": "evidence-rule-fallback",
            "focus": {
                "id": focus_id,
                "headline": headline,
                "analysis": analysis,
                "risk": "仅基于当前已核验记录；异期间指标不作因果推断。",
                "source_urls": [],
                "origin": "evidence_rule",
            },
        }
    return None


def generate_model_focus_insight(
    domain_id: str,
    focus: dict[str, Any],
    *,
    temperature: float = 0.25,
) -> dict[str, Any]:
    """Generate only the current overview judgement, without repeating entity summaries."""
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot
    from network_utils import urlopen_with_local_proxy_fallback

    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置内网模型密钥")
    focus_id = str(focus.get("id") or "")
    focus_contracts = {
        ("local", "financials"): (
            "只分析同一报告期间、同一币种下的收入与净利润关系；必须至少引用两家公司收入或净利润原值。"
            "披露项数只作样本完整度边界，不能成为标题或主要结论；不得把FY全年与H1半年直接排名。"
        ),
        ("local", "revenue"): "只比较FY2025营收绝对值；必须从至少两家原值提炼收入基础或竞争资源承载力分层，不得只复述高低。",
        ("local", "ebitda"): "只比较FY2025 EBITDA绝对值；必须解释经营现金创造代理或盈利缓冲分层，不得引入净利润或利润率。",
        ("local", "net_profit"): "只比较FY2025净利润绝对值；必须解释利润池或盈利韧性分化，不得只写金额差距。",
        ("local", "postpaid"): "只比较FY2025后付费用户绝对值；从客户基础与经常性收入基础切入，缺失值只能作为样本边界。",
        ("local", "scale"): "只分析运营商之间去重后在售产品数量的分层与区隔；记录数只作数据质量边界，不能成为标题或主要结论。",
        ("local", "mobile_price"): "只分析个人5G的月费中位数、价格带重合与价格区隔。",
        ("local", "fibre_value"): "只分析家宽每千兆月费及合约期对价格优势的影响。",
        ("local", "overlap"): (
            "只分析同一套餐类型内的月费区间重合，不得跨套餐类型比较。"
        ),
        ("international", "growth"): "只比较Q1 2026四家企业营收同比的正负分层与增长强弱，不解释无证据原因。",
        ("international", "momentum"): "只比较四家企业本期与上期营收增速变化，说明放缓范围或梯队，不使用驱动、导致等因果词。",
        ("international", "investment"): "只比较同期间资本开支占营收比例，并明确缺失主体与投入比例不等于投资回报。",
        ("international", "margin"): "只比较已披露且同口径经营利润率的层次与样本边界，不计算输入外差值。",
        ("international", "revenue"): "只比较统一折算为十亿美元的营收绝对值和十年绝对值序列；不得引入增速、指数、利润、资本或用户维度。",
        ("international", "ebitda"): "只比较FY2025统一折算的EBITDA绝对值；不得引入利润率、增速、净利润、资本或用户维度。",
        ("international", "net_profit"): "只比较FY2025统一折算的净利润绝对值；不得引入同比、增速、利润率、EBITDA、资本或用户维度。",
        ("international", "postpaid_arpu"): "只比较百万用户和美元/月的ARPU/ARPA；必须说明Verizon是ARPA、NTT为手机订阅替代口径。",
        ("cloud", "revenue"): "只比较FY2024云收入绝对金额；先区分直接云收入口径与代理分部口径，不得引入增速、利润率或自行换算。",
        ("cloud", "trend"): "只比较同一厂商FY2024至FY2025收入增速方向，说明提速覆盖面与例外主体。",
        ("cloud", "profit"): "只解释FY2024云利润绝对金额及经营利润、调整后EBITA和代理分部毛利的定义边界；不得引入利润率、增速或自行换算。",
        ("cloud", "investment"): "只比较FY2024集团资本开支绝对值；提炼资源承载力层次，同时明确集团投入不等于云业务单独投入或投入转化效率。",
        ("cloud", "margin_change"): "只比较各厂商自身同口径利润率变化的正负方向，不把不同利润定义混成统一排名。",
        ("macro", "connections"): "只解释登记数量、移动宽带登记和每百人登记的共同变化及多卡/联网设备边界，不等同独立客户。",
        ("macro", "traffic"): "只比较总流量与每连接流量同比，解释规模和单连接强度差异；禁止使用驱动、导致等因果词。",
        ("macro", "purchasing"): "只使用当前同月家庭收入、消费物价和输入中的购买力代理原值；不引用旧月份或自行重算。",
        ("macro", "service"): "只分别解释异期间的投资、投诉及网络供给背景，不比较差值、不建立因果。",
        ("mainland", "revenue"): "只比较FY2025营收绝对值；必须从至少两家原值提炼收入基础或竞争资源承载力分层，不得只复述高低。",
        ("mainland", "ebitda"): "只比较FY2025 EBITDA绝对值；必须解释经营现金创造代理或盈利缓冲分层，不得引入净利润或利润率。",
        ("mainland", "net_profit"): "只比较FY2025净利润绝对值；必须解释利润池或盈利韧性分化，不得只写金额差距。",
        ("mainland", "postpaid"): "只比较中国移动、中国电信和中国联通FY2025移动客户绝对值；联通必须明确为官方期初加全年净增推导约值。",
    }
    focus_contract = focus_contracts.get(
        (domain_id, focus_id),
        "只分析当前focus标签、metric和items直接表达的同一指标维度，不得借用其他页面维度。",
    )
    recent_insights = list(dict.fromkeys(
        str(value or "").strip()
        for value in [focus.get("insight"), *(focus.get("recent_insights") or [])]
        if str(value or "").strip()
    ))[-12:]
    recent_headlines = list(dict.fromkeys(
        str(value or "").strip()
        for value in [focus.get("headline"), *(focus.get("recent_headlines") or [])]
        if str(value or "").strip()
    ))[-12:]
    scale_has_record_counts = (
        (domain_id, focus_id) == ("local", "scale")
        and any(item.get("record_count") for item in focus.get("items") or [] if isinstance(item, dict))
    )
    focus_angle_options = {
        ("local", "financials"): (
            "比较H1 2026同期间收入规模与净利润转化的分层，至少引用两家公司原值",
            "比较同期间收入较高与净利润较高主体是否一致，不计算输入外比率",
            "从同期间收入梯队与净利润梯队是否同步切入，并保留缺失指标边界",
            "说明FY全年与H1半年不可混排，同时用H1 2026至少两家公司原值形成战略判断",
        ),
        ("local", "mobile_price"): (
            "比较两家月费中位数与价格带重合，判断中位数差异是否形成清晰区隔",
            "比较两家价格带宽度与共同覆盖区间，说明竞争重合范围",
            "从只有两家披露的样本边界切入，说明结论不能代表全市场",
            "从基础档重合与高价端延伸切入，但不得计算新差值",
        ),
        ("local", "fibre_value"): (
            "比较每千兆月费的价格层次，并保留合约期和覆盖边界",
            "判断低价组与高价组是否形成梯队，不计算新倍数",
            "从折算价不等于客户最终成本切入，仍须引用至少两个主体原值",
            "比较中位折算价的离散程度，禁止补写安装费或优惠金额",
        ),
        ("local", "overlap"): (
            "只判断个人5G价格区间重合及其区隔含义",
            "只判断光纤家宽同类价格重合及其区隔含义",
            "比较哪些同类组合有重合、哪些没有，不跨产品类型",
            "从价格带重合不等于产品同质切入，仍须引用原始区间",
        ),
        ("international", "growth"): (
            "按正增长与负增长分成两层",
            "比较最高与最低原值呈现的增长梯队，不计算差值",
            "说明正增长只集中于哪些主体，并保留同季度边界",
            "判断四家是否同步扩张，禁止解释无证据原因",
        ),
        ("international", "momentum"): (
            "说明四家公司增速变化是否同向",
            "比较放缓幅度较大的主体与其余主体，只引用输入原值",
            "从放缓覆盖面切入，禁止使用驱动、导致、源于",
            "判断增长动量是否形成梯队，不计算新差值",
        ),
        ("international", "investment"): (
            "比较联通与移动、电信的投入比例层次",
            "从移动与电信比例接近切入，不计算两者差值",
            "从铁塔缺少同口径值的样本边界切入",
            "说明投入比例不等于投资回报，仍须引用至少两个原值",
        ),
        ("international", "margin"): (
            "比较已披露经营利润率的高低梯队，不计算新差值",
            "从头部与中尾部利润缓冲层次切入",
            "从只有三家可比的样本边界切入",
            "说明利润率不等于绝对利润，仍须引用至少两个主体原值",
        ),
        ("international", "revenue"): (
            "比较FY2025统一折算营收的高低梯队，至少引用两家原值",
            "比较四家十年营收绝对值方向，不计算增速或指数",
            "从头部营收是否接近切入，不计算输入外差值",
            "说明统一汇率便于规模比较，但不等于盈利能力",
        ),
        ("international", "ebitda"): (
            "比较FY2025 EBITDA折算金额梯队，保留非GAAP口径边界",
            "只比较EBITDA绝对规模，不引入利润率或增速",
            "从高位集中度切入，不把不同调整项视为完全可比",
            "引用至少两家EBITDA绝对值形成判断",
        ),
        ("international", "net_profit"): (
            "按FY2025净利润绝对值分层，引用最高与最低原值",
            "只比较净利润折算金额，不引入同比、增速或利润率",
            "从绝对规模差距切入，不将单年数值外推为增长趋势",
            "说明集团范围与财年口径边界",
        ),
        ("international", "postpaid_arpu"): (
            "比较百万用户规模与美元/月用户价值的梯队",
            "说明Verizon ARPA与其他ARPU不能直接等同",
            "说明NTT手机订阅数不是后付费用户口径",
            "引用至少两家用户数与ARPU/ARPA原值形成分层判断",
        ),
        ("local", "revenue"): (
            "从最高与最低营收原值提炼竞争资源承载力分层",
            "从头部与中尾部收入基础断层切入，不计算输入外比例",
            "说明收入规模层次不等同经营效率，但不能只写口径边界",
            "引用至少两家公司原值，判断可披露收入基础是否集中",
        ),
        ("local", "ebitda"): (
            "从最高与最低EBITDA原值提炼盈利缓冲分层",
            "判断经营现金创造代理是否形成头尾断层",
            "比较至少两家公司原值，不引入利润率或净利润",
            "说明EBITDA规模层次对竞争资源承载的有界含义",
        ),
        ("local", "net_profit"): (
            "从正负利润或最高最低原值提炼盈利韧性分化",
            "判断利润池是否向头部集中，不计算输入外比例",
            "引用至少两家公司净利润原值形成战略发现",
            "说明利润绝对值分层而非复述金额高低",
        ),
        ("local", "postpaid"): (
            "从已披露两家后付费用户原值提炼客户基础分层",
            "说明客户基础不等同客户价值，缺失主体只作边界",
            "判断经常性收入基础是否存在规模层次",
            "引用至少两家原值，禁止以总用户或5G用户补位",
        ),
        ("cloud", "revenue"): (
            "比较FY2024云收入绝对金额梯队，至少引用两个主体原值",
            "把直接披露云收入与代理分部口径分开说明",
            "从直接披露与代理分部两种口径边界切入，不引入增速",
            "说明统一为百万美元只便于观察规模，不等于盈利能力",
        ),
        ("cloud", "trend"): (
            "说明多数厂商提速与唯一放缓主体",
            "从提速覆盖面切入，不计算新比例",
            "比较提速幅度较大的主体与其余主体，只引用输入原值",
            "判断变化方向是否一致，并明确缺少可比历史的主体",
        ),
        ("cloud", "profit"): (
            "比较FY2024云利润绝对金额，并说明不同利润定义不可直接混排",
            "从经营利润、代理分部毛利与调整后EBITA定义不同切入",
            "说明已披露与未披露主体的样本边界",
            "引用至少两个主体利润绝对金额，不计算新差值或利润率",
        ),
        ("cloud", "investment"): (
            "比较已披露集团资本开支的头尾层次，提炼资源承载力差异",
            "从Google与Azure高位投入接近切入，不计算输入外差值",
            "说明集团投入不等于云业务单独投入或投入转化效率",
            "引用至少两个主体原值形成战略发现，缺失主体只作样本边界",
        ),
        ("mainland", "revenue"): (
            "从最高与最低营收原值提炼收入基础和资源承载力分层",
            "判断头部与中尾部是否形成断层，不计算输入外比例",
            "引用至少两家原值，不能只说主体规模不同",
            "说明收入规模层次不等同经营效率",
        ),
        ("mainland", "ebitda"): (
            "比较已披露两家EBITDA原值，提炼盈利缓冲层次",
            "从经营现金创造代理的头尾差异切入",
            "说明只有两家可比的样本边界，但不能只报告缺口",
            "不得引入净利润、利润率或输入外数字",
        ),
        ("mainland", "net_profit"): (
            "从最高与最低净利润原值提炼利润池集中或盈利韧性分化",
            "比较头部与中尾部利润绝对值层次，不计算新比例",
            "引用至少两家公司原值形成战略发现",
            "只比较当前中国移动、中国电信和中国联通三家，不补入其他主体",
        ),
        ("mainland", "postpaid"): (
            "比较移动、电信和联通FY2025移动客户绝对值",
            "明确联通约值来自官方期初加全年净增推导",
            "从客户覆盖底盘对交叉销售和网络规模摊薄的影响切入",
            "只分析当前三家，不补入其他运营商或5G用户数",
        ),
        ("cloud", "margin_change"): (
            "按自身同口径利润率改善与减弱分组",
            "比较改善主体与下降主体的方向分化，不计算新差值",
            "从不同利润定义不能跨厂商统一排名切入",
            "说明收入增长不等于利润转化同步改善",
        ),
        ("macro", "connections"): (
            "比较三项登记指标增速接近的共同特征",
            "从多卡和联网设备使登记数不等于独立客户切入",
            "说明每百人登记高位的口径边界，不推算客户人数",
            "区分连接规模变化与客户规模变化",
        ),
        ("macro", "traffic"): (
            "比较总流量与每连接流量增速的层次",
            "从规模增长与单连接使用强度分化切入",
            "说明两项增速不同但不建立因果",
            "判断流量增长是否主要体现在总量层面，只引用原值",
        ),
        ("macro", "purchasing"): (
            "比较当前家庭收入与消费物价原值，引用输入中的购买力代理值",
            "从购买力代理为负切入，但不等同电讯消费变化",
            "从同月口径边界切入，禁止引用旧月份数字",
            "说明收入与物价方向形成压力，但不预测消费行为",
        ),
        ("macro", "service"): (
            "说明投资与投诉期间不同，不能直接关联",
            "从5G覆盖与频谱只属于网络供给背景切入",
            "比较投入规模与服务压力的口径边界，不计算差值",
            "说明覆盖高位不等同服务质量改善",
        ),
    }
    angle_options = focus_angle_options.get((domain_id, focus_id)) or (
        (
            "比较头部三家与尾部两家的数量层次，必须说明竞争结构分成哪两层",
            "从头部三家去重产品数量相近切入，必须说明三家之间的数量差距有限",
            "比较尾部两家与头部三家的选择宽度，说明数量差距对应的产品覆盖层次",
            "从数据边界切入，必须说明产品数量不能等同产品吸引力、价值或竞争力",
        )
        if scale_has_record_counts
        else (
            "从竞争区隔或增长质量切入",
            "从资本投入比例或利润转化切入",
            "从需求强度或购买力压力切入",
            "从服务压力或数据边界切入",
        )
    )
    regeneration_index = max(1, int(focus.get("regeneration_index") or len(recent_insights) or 1))
    angle_instruction = angle_options[(regeneration_index - 1) % len(angle_options)]
    request_nonce = hashlib.sha256(
        f"{time.time_ns()}-{os.urandom(16).hex()}".encode("utf-8")
    ).hexdigest()[:20]
    include_item_detail = (domain_id, focus_id) != ("local", "scale")
    compact_focus = {
        "id": focus_id,
        "label": focus.get("label"),
        "metric": focus.get("metric"),
        "scope": focus_contract,
        "required_angle": angle_instruction,
        "items": [
            {
                "name": item.get("name"),
                "value": item.get("value"),
                "unit": item.get("unit"),
                **({
                    "record_count": item.get("record_count"),
                    "deduplicated_plan_count": item.get("component_count"),
                } if scale_has_record_counts else {}),
                **({"detail": item.get("detail")} if include_item_detail else {}),
                **({"analysis": item.get("analysis")} if (domain_id, focus_id) == ("local", "overlap") else {}),
                **({"relationships": item.get("components")} if (domain_id, focus_id) == ("local", "overlap") else {}),
                **({"metrics": item.get("components")} if (domain_id, focus_id) == ("local", "financials") else {}),
            }
            for item in focus.get("items") or []
            if isinstance(item, dict)
        ],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是电信竞争情报分析员。只返回JSON对象{headline:string,analysis:string}。"
                "任务不是解释指标，而是比较当前items中至少两个竞对、期间或指标，找出数据关系及其有界经营含义。"
                "headline是随本次判断重新生成的4至14字结论标题，不含数字、单位、标点或行动建议，"
                "不得复用旧版标题。标题必须直接概括这组数字对持续投入、竞争防守、客户收入底盘、盈利飞轮或资本军备的意义；"
                "禁止用年份、指标名、金额、绝对值、序列、入库、披露、口径、数据或重新判断充当标题。只能使用输入数字和事实。"
                "analysis必须一至两句、120字内，引用输入具体数值，给出结构、集中度、"
                "口径可比性、市场阶段或指标关系判断；结论还必须落到资源承载、现金创造、盈利韧性、"
                "利润池、投入转化、客户价值、收入基础或竞争结构中的至少一项；换一个有效分析角度，不能解释指标定义、"
                "复述高低增减、给行动建议或编造因果。正文必须进一步落到持续投入能力、价格竞争容错、客户获取/保有、"
                "自我融资/再投资、生态扩张或基础设施资本军备中的至少一项，不能以‘形成梯队’作为句号。所有数字必须原样选自metric.value或items.value；"
                "引用某个有效items.value后不得又说该主体‘不能纳入这一判断’；只有value为空或输入明确标注代理口径时才可作为边界。"
                "local.financials还可原样选自items.metrics.value。禁止自行加总、计算占比或创造衍生数字。"
                "结论必须使用表明、说明、意味着、主要来自、并非、而非或不能等同中的至少一个连接词。"
                "必须严格遵守输入scope，只能总结当前页，"
                "不得把相邻页或item附带信息扩展为当前页结论。"
                "禁止把单项高低直接写成领先、竞争力、定价权或因果；少于3个可比对象时必须明确样本边界。"
                "如果items.value全部为空、横线或待补，不得输出‘待补为-’、空值、占位符或虚构数字；"
                "此时直接解释该口径缺口限制了哪一种客户价值、盈利质量或竞争结构判断。"
                "禁止使用导致、造成、推动、带来、源于、驱动等因果词；输入scope要求说明驱动时，也只能改写为关系或边界。"
                + FOCUS_RELATION_FEW_SHOTS
            ),
        },
        {
            "role": "user",
            "content": (
                f"请求唯一标识（仅用于避免服务端缓存，不得写入答案）：{request_nonce}\n"
                f"只重新生成{domain_id}.{focus_id}当前洞察，必须采用required_angle，"
                "必须只使用下方当前证据，不得补入历史数字或旧版句式：\n"
            )
            + json.dumps(compact_focus, ensure_ascii=False),
        },
    ]
    model = str(config.get("model") or "deepseek-v4")
    base_models = list(dict.fromkeys([model, "GLM", "Qwen3-30B-A3B-Instruct-2507"]))
    has_safe_outage_fallback = scale_has_record_counts or (domain_id, focus_id) in {
        ("macro", "service"),
        ("international", "growth"),
    }
    attempt_models = [*base_models, *base_models]
    previous_insights = [re.sub(r"\s+", "", value) for value in recent_insights]
    last_error: ValueError | None = None
    headline = f"{str(focus.get('label') or '当前指标').strip()}结构重新分化"[:14]
    for attempt, attempt_model in enumerate(attempt_models):
        if attempt >= len(base_models):
            grounded_seed = _compact_grounded_focus_analysis(domain_id, focus)
            attempt_messages = [
                {
                    "role": "system",
                    "content": (
                        "你是电信数据分析员。只返回合法JSON对象{headline,analysis}。"
                        "在不改变任何数字和事实的前提下，把证据底稿改写为新的数据关系结论。"
                        "标题4至14字且不含数字；正文一至两句、100字内。"
                        "禁止建议、因果词、衍生计算和证据外事实。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "focus": compact_focus,
                        "required_angle": angle_instruction,
                        "grounded_seed": grounded_seed,
                        "forbidden_recent_headlines": recent_headlines,
                        "request_nonce": f"{request_nonce}-{attempt}",
                    }, ensure_ascii=False),
                },
            ]
        else:
            attempt_messages = list(messages)
        if attempt and attempt < len(base_models):
            retry_angle = angle_instruction
            attempt_messages.append({
                "role": "user",
                "content": (
                    f"上一版未通过新洞察门禁：{last_error}。必须换一个分析角度和句式，"
                    "不得复用current_insight或既有标题；若错误涉及衍生数字，只并列输入原值，"
                    f"不得输出相减、相加或换算结果；本次改用‘{retry_angle}’，该角度覆盖上一条"
                    "required_angle；仍只能使用输入原值，只返回JSON对象。"
                ),
            })
        request_id = f"focus-{domain_id}-{focus_id}-{request_nonce}-{attempt}"
        request = urllib.request.Request(
            f"{str(config.get('base_url') or INTERNAL_AI_BASE_URL).rstrip('/')}/chat/completions"
            f"?request_id={urllib.parse.quote(request_id, safe='')}",
            data=json.dumps(prepare_structured_chat_body({
                **dict(config.get("extra_parameters") or {}),
                "model": attempt_model,
                "messages": attempt_messages,
                "temperature": temperature if attempt == 0 else max(0.55, temperature),
                "max_tokens": 480,
            }), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
                "X-Request-ID": request_id,
            },
            method="POST",
        )
        wait_for_internal_ai_slot(f"executive-intelligence-focus-{domain_id}-{focus_id}")
        try:
            with urlopen_with_local_proxy_fallback(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:800]
            last_error = ValueError(f"内网模型 HTTP {exc.code}: {detail}")
            if attempt + 1 < len(attempt_models):
                continue
            raise RuntimeError(str(last_error)) from exc
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = ValueError(f"模型连接或响应异常：{exc}")
            if attempt + 1 < len(attempt_models):
                continue
            raise last_error
        try:
            parsed = load_json_response(
                final_chat_message_text(payload, operation="单项AI洞察"), operation="单项AI洞察"
            )
            if not isinstance(parsed, dict):
                raise ValueError("单项AI洞察未返回JSON对象")
            headline = re.sub(r"\s+", " ", str(parsed.get("headline") or "")).strip()
            analysis = re.sub(r"\s+", " ", str(parsed.get("analysis") or "")).strip()
            forbidden_headline_terms = {
                ("local", "scale"): ("赛道", "月费", "资费", "重叠", "交集"),
                ("local", "financials"): ("披露", "发布", "数量", "密度", "完整度", "口径", "边界"),
            }.get((domain_id, focus_id), ())
            headline = _normalize_fresh_focus_headline(
                headline,
                label=str(focus.get("label") or "当前指标").strip(),
                recent_headlines=[] if scale_has_record_counts else recent_headlines,
                forbidden_terms=forbidden_headline_terms,
            )
            if (domain_id, focus_id) in _OVERVIEW_STRATEGIC_HEADLINES and any(
                term in headline for term in _OVERVIEW_DIRECT_HEADLINE_TERMS
            ):
                headline = _strategic_focus_headline(
                    domain_id, focus_id, variant_index=regeneration_index - 1 + attempt
                )
            if (domain_id, focus_id) == ("local", "financials") and (
                "重要财务指标" in headline
                or "重新" in headline
                or any(term in headline for term in forbidden_headline_terms)
            ):
                financial_headlines = (
                    "收入规模呈现分层",
                    "收入与利润梯队分化",
                    "规模差距映射利润分层",
                    "同期间业绩形成梯队",
                )
                headline = financial_headlines[(regeneration_index - 1 + attempt) % len(financial_headlines)]
            if "分散" in headline and any(term in analysis for term in ("集中", "头部三家", "主要来自头部")):
                raise ValueError(f"AI洞察标题与正文判断相反：{headline}")
            headline_similarities = [
                difflib.SequenceMatcher(None, previous, headline).ratio()
                for previous in recent_headlines
            ]
            if max(headline_similarities, default=0.0) >= 0.96:
                label = str(focus.get("label") or "当前指标").strip()
                fallback_headlines = _OVERVIEW_STRATEGIC_HEADLINE_VARIANTS.get(
                    (domain_id, focus_id),
                    (
                        f"{label}呈现头尾断层",
                        f"{label}形成梯队分化",
                        f"{label}分布明显失衡",
                        f"{label}集中于头部主体",
                        f"{label}尾部显著分化",
                        f"{label}结构出现分层",
                        f"{label}头部优势扩大",
                        f"{label}供给呈现偏态",
                        f"{label}主体差异拉开",
                        f"{label}层次重新分化",
                    ),
                )
                fallback_start = (regeneration_index - 1 + attempt) % len(fallback_headlines)
                headline = next(
                    (
                        fallback_headlines[(fallback_start + offset) % len(fallback_headlines)]
                        for offset in range(len(fallback_headlines))
                        if fallback_headlines[(fallback_start + offset) % len(fallback_headlines)]
                        not in recent_headlines
                    ),
                    fallback_headlines[fallback_start],
                )
            if analysis and not re.search(r"[。！？!?]$", analysis):
                analysis += "。"
            # Repair two recurring model slips before applying the strict gate:
            # derived differences and an overlong trailing disclosure caveat.
            allowed_numeric_evidence = {
                "metric": compact_focus.get("metric"),
                "items": compact_focus.get("items"),
            }
            analysis, analysis_repaired = _repair_generated_focus_analysis(
                analysis,
                allowed_numeric_evidence,
            )
            analysis, analysis_compacted = _compact_generated_focus_analysis(
                domain_id,
                focus_id,
                analysis,
                focus,
                allowed_numeric_evidence,
            )
            analysis_repaired = analysis_repaired or analysis_compacted
            gate_error = _focus_gate_error(domain_id, focus_id, analysis, focus)
            if gate_error:
                grounded_seed = _compact_grounded_focus_analysis(domain_id, focus)
                merged = f"{grounded_seed.rstrip('。！？!?')}；{analysis}"
                merged, _ = _repair_generated_focus_analysis(
                    merged,
                    allowed_numeric_evidence,
                )
                merged, _ = _compact_generated_focus_analysis(
                    domain_id,
                    focus_id,
                    merged,
                    focus,
                    allowed_numeric_evidence,
                )
                if not _focus_gate_error(domain_id, focus_id, merged, focus):
                    analysis = merged
                    analysis_repaired = True
                    gate_error = ""
            if gate_error:
                raise ValueError(gate_error)
            if scale_has_record_counts:
                angle_index = (regeneration_index - 1) % len(angle_options)
                angle_passed = (
                    (sum(name in analysis for name in ("HKBN", "3HK", "SmarTone", "i-CABLE", "HGC")) >= 4
                     and any(term in analysis for term in ("两层", "头部", "尾部")))
                    if angle_index == 0 else
                    (any(term in analysis for term in ("接近", "相近", "差距有限")))
                    if angle_index == 1 else
                    ("i-CABLE" in analysis and "HGC" in analysis and any(term in analysis for term in ("选择", "覆盖", "层次")))
                    if angle_index == 2 else
                    (
                        any(term in analysis for term in ("不能等同", "不代表", "并不等同"))
                        and any(term in analysis for term in ("吸引力", "价值", "竞争力"))
                    )
                )
                if not angle_passed:
                    raise ValueError(f"AI洞察未真正采用指定的新分析角度：{angle_instruction}")
            # Validate against exactly what the model was allowed to see. Hidden
            # cross-focus details must never make their numbers look admissible.
            unknown_numbers = _numeric_tokens(analysis) - _numeric_tokens(allowed_numeric_evidence)
            if unknown_numbers:
                raise ValueError(f"AI分析分类出现输入之外的数字：{sorted(unknown_numbers)}")
            normalized_analysis = re.sub(r"\s+", "", analysis)
            similarities = [
                difflib.SequenceMatcher(None, previous_insight, normalized_analysis).ratio()
                for previous_insight in previous_insights
                if previous_insight
            ]
            similarity = max(similarities, default=0.0)
            # The same small evidence set necessarily shares names and numeric
            # anchors. Reject near-copies, but allow a genuinely different
            # judgement angle even when those immutable anchors keep lexical
            # similarity moderately high.
            if similarity >= 0.94:
                raise ValueError(f"新洞察与最近洞察过于相似：{similarity:.0%}")
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = ValueError(str(exc))
            if attempt + 1 < len(attempt_models):
                continue
            break
        return {
            "generated_at_hkt": _now(),
            "model": attempt_model,
            "focus": {
                "id": focus_id,
                "headline": headline,
                "analysis": analysis,
                "risk": "仅基于当前已核验记录；跨期间、缺失值和异口径不作因果推断。",
                "source_urls": [],
                **({"repaired": True} if analysis_repaired else {}),
            },
        }
    grounded_repair = _final_grounded_focus_repair(
        domain_id,
        focus,
        regeneration_index=regeneration_index,
        recent_insights=recent_insights,
    )
    if grounded_repair:
        if (domain_id, focus_id) == ("local", "financials"):
            financial_headlines = (
                "收入规模呈现分层",
                "收入与利润梯队分化",
                "规模差距映射利润分层",
                "同期间业绩形成梯队",
            )
            repaired_headline = financial_headlines[(regeneration_index - 1) % len(financial_headlines)]
        elif (domain_id, focus_id) in _OVERVIEW_STRATEGIC_HEADLINES:
            repaired_headline = _strategic_focus_headline(domain_id, focus_id)
        else:
            repaired_headline = _normalize_fresh_focus_headline(
                "",
                label=str(focus.get("label") or "当前指标").strip(),
                recent_headlines=recent_headlines,
            )
        return {
            "generated_at_hkt": _now(),
            "model": attempt_models[-1],
            "focus": {
                "id": focus_id,
                "headline": repaired_headline,
                "analysis": grounded_repair,
                "risk": "仅基于当前已核验记录；跨期间、缺失值和异口径不作因果推断。",
                "source_urls": [],
                "repaired": True,
            },
        }
    if scale_has_record_counts:
        items = compact_focus.get("items") or []
        angle_index = (regeneration_index - 1) % len(angle_options)
        if angle_index == 0:
            a, b, c = items[:3]
            d, e = items[-2:]
            headline = "产品数量形成两层"
            analysis = (
                f"{a.get('name')}、{b.get('name')}、{c.get('name')}分别有{_display_number(a.get('value'))}、"
                f"{_display_number(b.get('value'))}、{_display_number(c.get('value'))}个产品，"
                f"而{d.get('name')}、{e.get('name')}为{_display_number(d.get('value'))}、{_display_number(e.get('value'))}个；"
                "数量形成头尾两层，但头部三家彼此接近，难以靠数量形成区隔。"
            )
        elif angle_index == 1:
            a, b, c = items[:3]
            headline = "头部选择宽度接近"
            analysis = (
                f"{a.get('name')}{_display_number(a.get('value'))}个、{b.get('name')}"
                f"{_display_number(b.get('value'))}个与{c.get('name')}{_display_number(c.get('value'))}个相近，"
                "说明头部三家的当前套餐选择宽度差距有限。"
            )
        elif angle_index == 2:
            a, b = items[-2:]
            headline = "尾部套餐选择较少"
            analysis = (
                f"{a.get('name')}{_display_number(a.get('value'))}个、{b.get('name')}"
                f"{_display_number(b.get('value'))}个，说明两家在当前收录中的套餐选择较少；"
                "这只反映选择宽度，不代表产品价值。"
            )
        else:
            headline = "数量不代表吸引力"
            analysis = (
                f"去重后在售产品{_display_number((compact_focus.get('metric') or {}).get('value'))}个，"
                "但产品数量不能等同产品吸引力、价值或竞争力；"
                "这页只能说明当前收录的选择宽度。"
            )
        return {
            "generated_at_hkt": _now(),
            "model": "evidence-rule-fallback",
            "focus": {
                "id": focus_id,
                "headline": headline,
                "analysis": analysis,
                "risk": "仅基于当前已核验记录；产品数量不代表产品吸引力。",
                "source_urls": [],
                "origin": "evidence_rule",
            },
        }
    safe_fallback = _safe_focus_regeneration_fallback(
        domain_id,
        focus,
        regeneration_index=regeneration_index,
        recent_insights=recent_insights,
    )
    if safe_fallback:
        return safe_fallback
    raise last_error or ValueError("AI洞察生成失败")


def generate_model_domain_summaries(
    evidence: dict[str, Any] | None = None,
    *,
    temperature: float = 0.0,
    allow_partial_domains: bool = False,
) -> dict[str, Any]:
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
        "任务不是解释数据，而是从每个focus的竞对、期间或指标之间找出可验证关系，并说明这项关系对竞争结构、"
        "价格区隔、增长质量、利润转化、需求强度或服务压力的有界含义。"
        "每个领域给出一句headline、一段analysis和一句risk；为每个focus给出analysis、risk；"
        "并为每个focus中的每个实体逐一给出headline、analysis、risk、evidence_labels和source_urls。"
        "实体analysis只需准确陈述该实体的事实、期间、单位和口径，不强迫单个实体推导经营含义；"
        "evidence_labels必须从该实体components的label中原样选择，不能编造。所有focus和实体必须逐一覆盖，不能遗漏、合并或新增。"
        "禁止写按排名、图中排序、同一视图、便于比较、数据库内、此视图、不代表经营排名等界面说明或空话。"
        "每个focus的analysis必须是一至两句、总长不超过120字；有有效数值时必须引用至少一个输入具体数值作为证据；"
        "若该focus所有value均为空、横线或待补，不得输出‘待补为-’、空值、占位符或虚构数字，"
        "而要直接解释这一口径缺口限制了哪一种客户价值、盈利质量或竞争结构判断；"
        "结论必须解释数字背后的结构、驱动因素、集中度、口径可比性、市场阶段或指标关系，不能停留在数字高低、增减或事实复述；"
        "禁止写建议、应、需、优先、关注、评估、验证、补齐、转向等行动话术，也不要告诉读者下一步做什么。"
        "全部17个focus都必须给出深层解释性结论，而不是指标定义、展示方法、新闻式发生描述或泛化业务建议。"
        "focus.headline必须是战略意义判断，不能照抄页签或指标名称，也不能用年份、金额、绝对值、序列、入库、披露、口径或数据作标题。"
        "overview四区域的focus正文在引用具体数字后，必须继续说明其对持续投入、价格竞争容错、客户收入底盘、"
        "自我融资与再投资、生态扩张或基础设施资本军备的意义，不能停在高低、分层或梯队描述。"
        "每个focus至少比较两个竞对、两个期间或两个指标；无法同口径比较时，结论必须是不可比边界而非强行排名。"
        "禁止无证据写领先、竞争力、定价权、导致、造成、推动、带来、源于或驱动；少于3个可比对象时明确样本边界。"
        "local.price必须明确写出品牌月费中位数的最低值、最高值和至少一个价格差距，不能把‘缺失值不估算’当作结论。"
        "local.financials必须比较同期间至少两家公司的收入、净利润、EBITDA或资本开支原值；"
        "发布日期、披露项数和资料完整度只能写入risk，不能成为headline或analysis的主要结论。"
        "跨期间、代理分部、披露缺口必须明确写入risk；"
        "不得把相关性写成因果。不得从URL文件名推断日期，也不得把FY财年自行转换成具体月日。"
        "source_urls只能从输入中原样选择。只返回JSON对象，顶层字段只能是items数组。"
        + FOCUS_RELATION_FEW_SHOTS
    )
    requested_domain_ids = [str(domain.get("id") or "") for domain in evidence.get("domains") or []]
    validation_domains = set(requested_domain_ids) if allow_partial_domains else None
    user_prompt = (
        f"请分析输入中的领域：{', '.join(requested_domain_ids)}。返回{{\"items\":[...]}}，每项字段严格为"
        "domain, headline, analysis, risk, source_urls, focuses；focuses每项字段严格为"
        "id, headline, analysis, risk, source_urls, entities；entities每项字段严格为"
        "name, headline, analysis, risk, evidence_labels, source_urls。不要Markdown。输入：\n"
        + json.dumps(evidence, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    body = prepare_structured_chat_body({
        **dict(config.get("extra_parameters") or {}),
        "model": str(config.get("model") or "deepseek-v4"),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 16000,
    })
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
        try:
            content = final_chat_message_text(payload, operation="17项AI洞察")
            raw_summaries = unwrap_items_payload(
                load_json_response(content, operation="17项AI洞察"), operation="17项AI洞察"
            )
            summaries = _validate_model_summaries(
                _repair_model_summaries(
                    _drop_unsupported_numeric_clauses(raw_summaries, evidence),
                    evidence,
                ),
                evidence,
                expected_domains=validation_domains,
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
                                "保持四个领域、全部focus和全部实体完整并重新只返回JSON对象{\"items\":[...]}。"
                            ),
                        },
                    ]
                )
    if summaries is None:
        # Older model deployments sometimes follow the four-domain shape but omit
        # nested focus summaries. Retry one domain at a time so every focus can be
        # checked explicitly without asking the model to hold all views at once.
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
                        f"只分析 {domain_id} 这一个领域，返回JSON对象{{\"items\":[单个领域对象]}}。"
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
                    domain_content = final_chat_message_text(
                        domain_payload, operation=f"{domain_id}领域AI洞察"
                    )
                    parsed = unwrap_items_payload(
                        load_json_response(domain_content, operation=f"{domain_id}领域AI洞察"),
                        operation=f"{domain_id}领域AI洞察",
                    )
                    if len(parsed) != 1 or not isinstance(parsed[0], dict):
                        raise ValueError("必须返回只含一个领域对象的items数组")
                    candidate = _drop_unsupported_numeric_clauses(
                        _pin_scoped_model_identity([parsed[0]], domain_id),
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
                                "每个focus.analysis用一至两句、总长不超过120字：引用输入原值，并解释数字背后的结构、驱动、"
                                "集中度、口径可比性或市场阶段。禁止建议、应、需、优先、关注、评估、验证等行动话术。"
                                "不要只复述高低增减或解释指标用途。仍只返回JSON对象{\"items\":[单个领域对象]}。"
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
                                "你是电信竞争情报分析员。只返回合法JSON对象，顶层字段只能是items数组，不要解释。只能使用输入证据。"
                                "逐一覆盖items中的全部实体，name必须原样；实体只需准确陈述事实、期间、单位和口径，"
                                "不强迫单个实体推导经营含义。evidence_labels如使用，只能原样选自该实体components.label。"
                                "focus.analysis必须用一至两句、总长不超过120字，引用输入具体数值并解释结构、驱动、"
                                "集中度、口径可比性或市场阶段；禁止行动建议与数字复述。"
                                "禁止写按排名、图中排序、同一视图、便于比较、数据库内、此视图等界面说明。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"只分析 {domain_id}.{focus_id} 这一个分类，返回JSON对象{{\"items\":[只含一个focus的领域对象]}}。"
                                f"实体name必须完整且原样等于：{json.dumps(sorted(expected_names), ensure_ascii=False)}。"
                                "items固定结构为：[{domain,headline,analysis,risk,source_urls,focuses:[{id,analysis,risk,"
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
                            focus_content = final_chat_message_text(
                                focus_payload, operation=f"{domain_id}.{focus_id} AI洞察"
                            )
                            parsed = unwrap_items_payload(
                                load_json_response(
                                    focus_content, operation=f"{domain_id}.{focus_id} AI洞察"
                                ),
                                operation=f"{domain_id}.{focus_id} AI洞察",
                            )
                            if len(parsed) != 1 or not isinstance(parsed[0], dict):
                                raise ValueError("必须返回只含一个领域对象的items数组")
                            candidate = _drop_unsupported_numeric_clauses(
                                _pin_scoped_model_identity([parsed[0]], domain_id, focus_id),
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
                                        "focus.analysis必须用一至两句、总长不超过120字，引用输入原值并解释数字背后的结构、驱动、"
                                        "集中度、口径可比性或市场阶段；禁止建议、应、需、优先、关注、评估、验证等行动话术，"
                                        "也不能只复述高低增减或指标定义。只返回合法JSON对象{\"items\":[单个领域对象]}。"
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
            expected_domains=validation_domains,
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


def _manual_discovery_evidence(
    evidence: dict[str, Any], source_domain: str, target_domain: str
) -> dict[str, Any]:
    """Give manual regeneration two explicit numeric anchors instead of both full domains."""
    focus_map = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
        if isinstance(focus, dict)
    }
    anchor_focus_ids = {
        ("mainland", "local"): (("mainland", "revenue"), ("local", "revenue")),
        ("international", "cloud"): (("international", "revenue"), ("cloud", "revenue")),
        ("local", "cloud"): (("local", "revenue"), ("cloud", "revenue")),
        ("mainland", "international"): (("mainland", "revenue"), ("international", "revenue")),
    }
    selected = anchor_focus_ids.get((source_domain, target_domain))
    if not selected:
        return {"required_values": [], "evidence": []}
    anchors: list[dict[str, Any]] = []
    for domain_id, focus_id in selected:
        focus = focus_map.get((domain_id, focus_id)) or {}
        metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
        items = [item for item in focus.get("items") or [] if isinstance(item, dict)]
        raw_value = metric.get("value")
        unit = str(metric.get("unit") or "")
        label = str(metric.get("label") or focus.get("title") or focus_id)
        source_url = next(
            (str(item.get("source_url") or "") for item in items if str(item.get("source_url") or "")),
            "",
        )
        value = f"{_display_number(raw_value)}{unit}"
        anchors.append({
            "domain": domain_id,
            "focus": focus_id,
            "label": label,
            "value": value,
            "source_url": source_url,
        })
    required_lens = {
        ("mainland", "local"): "区分内地与香港运营主体、币种和市场范围，不能用绝对金额直接判断经营质量。",
        ("international", "cloud"): "判断传统运营商与云业务所处增长阶段是否分层，不把增速差直接等同经营效率。",
        ("local", "cloud"): "区分香港运营商整体财务与全球云分部收入，解释主体、币种和范围边界。",
        ("mainland", "international"): "区分内地移动用户披露与国际后付费、订阅及集团财务口径，不能互相替代。",
    }.get((source_domain, target_domain), "解释两项指标的口径和市场阶段边界。")
    return {
        "required_values": [item["value"] for item in anchors],
        "required_lens": required_lens,
        "evidence": anchors,
    }


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
        "你是电信竞争情报分析员。从local、international、mainland、cloud四个战略总览数据域中提炼恰好四条跨库发现。"
        "每条必须联系两个不同领域，四条不得重复同一领域组合，且四个领域都要被覆盖。"
        "不要逐库摘要，不要写论文，不要复述发生了什么；标题写数据关系结论，detail只解释背后的结构、驱动、"
        "集中度、口径差异、市场阶段或跨领域背离。禁止建议、应、需、优先、关注、评估、验证、补齐、转向等行动话术。"
        "只能使用输入JSON里的事实、数字、期间、口径和来源；不得新增数字、伪造因果或从URL推断信息。"
        "每条detail必须使用表明、说明、意味着、并非、而非或不能等同中的至少一个连接词，把数字证据连到关系判断。"
        "source_urls必须分别包含两个领域在输入中原样提供的来源。只返回JSON对象，顶层字段只能是items数组。"
    )
    user_prompt = (
        "请返回{\"items\":[四条发现]}，每项字段严格为from,to,title,detail,kind,source_urls。"
        "title不超过28字，detail不超过110字，kind统一写AI综合研判。不要Markdown。输入：\n"
        + json.dumps(prompt_evidence, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    body = prepare_structured_chat_body({
        **dict(config.get("extra_parameters") or {}),
        "model": str(config.get("model") or "deepseek-v4"),
        "messages": messages,
        "temperature": 0.0,
        # Four compact discoveries still need enough room for compatible
        # gateways that reserve part of the allowance before final JSON.
        "max_tokens": 4000,
    })
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
        try:
            content = final_chat_message_text(payload, operation="跨库AI发现")
            discoveries = _validate_model_discoveries(
                _repair_discovery_conciseness(
                    unwrap_items_payload(
                        load_json_response(content, operation="跨库AI发现"), operation="跨库AI发现"
                    )
                ),
                evidence,
            )
            used_model = discovery_model
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < len(discovery_models):
                messages.extend([
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"上一版未通过跨库门禁：{exc}。请改成有数字锚点的深层数据关系结论，只解释结构、驱动、"
                            "集中度、口径或市场阶段；每条detail必须含表明、说明、意味着、并非、而非或不能等同之一，"
                            "不写发生了什么，不提建议或下一步；仍只返回{\"items\":[四条发现]}。"
                        ),
                    },
                ])
    if discoveries is None:
        raise ValueError(f"AI跨库发现连续三次未通过门禁：{last_error}")
    return {"generated_at_hkt": _now(), "model": used_model, "discoveries": discoveries}


def regenerate_model_discovery(
    index: int,
    source_domain: str,
    target_domain: str,
    *,
    path: Path = AI_ANALYSIS_PATH,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Regenerate one cross-library discovery while preserving the other three."""
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot
    from network_utils import urlopen_with_local_proxy_fallback

    def report(message: str) -> None:
        if progress:
            progress(message)

    if index not in range(4):
        raise ValueError("跨库洞察序号必须为0至3")
    expected_domains = set(UI_DOMAIN_IDS)
    if source_domain not in expected_domains or target_domain not in expected_domains or source_domain == target_domain:
        raise ValueError("跨库洞察领域组合无效")

    report("正在读取两域当前证据")
    evidence = _analysis_input_snapshot()
    evidence_hash = _content_hash(evidence)
    analysis = _read_json(path, {}) or {}
    previous = analysis.get("model_analysis") or {}
    previous_is_current = bool(
        str(previous.get("evidence_hash") or "") == evidence_hash
        and str(previous.get("insight_format") or "") == INSIGHT_FORMAT_VERSION
        and previous.get("summaries")
    )
    discoveries = json.loads(json.dumps(
        previous.get("discoveries") if previous_is_current else _deterministic_discoveries(evidence),
        ensure_ascii=False,
    ))
    discoveries = _validate_model_discoveries(discoveries, evidence)
    current = discoveries[index]
    if {str(current.get("from") or ""), str(current.get("to") or "")} != {source_domain, target_domain}:
        raise ValueError("跨库洞察位置与当前领域组合不一致，请刷新页面后重试")

    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置内网模型密钥")
    scoped_evidence = _manual_discovery_evidence(evidence, source_domain, target_domain)
    messages = [
        {
            "role": "system",
            "content": (
                "你是电信竞争情报分析员。只重新生成指定两个领域的一条跨库发现。"
                "只返回JSON对象{from,to,title,detail,kind,source_urls}。from和to必须保持输入顺序；"
                "title不超过28字，detail不超过110字，kind写AI综合研判。detail必须逐字包含required_values中的"
                "两个值，且两个领域各一个；只解释结构、口径边界或市场阶段；"
                "禁止建议、应、需、优先、关注、评估、验证等行动话术。"
                "detail必须遵守required_lens；detail必须包含“表明、反映、说明”三者之一且只用一个即可；"
                "关系判断可使用分层、差距、不同、并非、不等于、重合、错位、边界等最贴合证据的词。"
                "不要使用‘脱钩’、‘结构性差异’或任何驱动因果话术，也不要连续堆叠多个解释连接词。"
                "required_lens已经给出可解释边界；不得进一步猜测增速或差距为何发生，不得补写AI、算力、基站共享、"
                "套餐组合、客户需求等输入中没有的驱动因素。"
                "source_urls必须逐字使用evidence中两个领域各自的source_url，不得新增数字、来源或伪造因果。"
                "必须依据证据重新推导一条判断，不得复述输入指令或请求编号。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"from": source_domain, "to": target_domain, **scoped_evidence}, ensure_ascii=False),
        },
    ]
    configured_model = str(config.get("model") or "deepseek-v4")
    base_models = list(dict.fromkeys(["Qwen3-30B-A3B-Instruct-2507", "GLM", configured_model]))
    models = [*base_models, *base_models]
    last_error: Exception | None = None
    replacement: dict[str, Any] | None = None
    used_model = models[0]
    pair_key = f"{source_domain}.{target_domain}"
    prior_counts = previous.get("manual_discovery_regeneration_counts") or {}
    if not isinstance(prior_counts, dict):
        prior_counts = {}
    regeneration_count = int(prior_counts.get(pair_key) or 0) + 1
    prior_history = previous.get("manual_discovery_regeneration_history") or {}
    if not isinstance(prior_history, dict):
        prior_history = {}
    relation_history = [
        str(value or "").strip()
        for value in prior_history.get(pair_key) or []
        if str(value or "").strip()
    ][-12:]
    prior_title_history = previous.get("manual_discovery_regeneration_title_history") or {}
    if not isinstance(prior_title_history, dict):
        prior_title_history = {}
    relation_title_history = [
        str(value or "").strip()
        for value in prior_title_history.get(pair_key) or []
        if str(value or "").strip()
    ][-12:]
    current_text = "".join(re.sub(r"\s+", "", str(current.get(key) or "")) for key in ("title", "detail"))
    comparison_history = [*relation_history, current_text]
    fallback_used = False
    report("正在生成新的跨库判断")
    regeneration_angles = {
        ("mainland", "local"): (
            "内地与香港运营主体属于不同市场范围",
            "人民币与港元绝对金额不能直接混排",
            "集团范围与本地运营主体存在披露边界",
            "收入规模不等于经营质量",
        ),
        ("international", "cloud"): (
            "传统运营商与云业务处于不同增长阶段",
            "两类市场增速分层但不等于经营效率差距",
            "企业范围与业务范围不同，数值只作阶段对照",
            "低个位数增长与高双位数增长形成阶段梯队",
        ),
        ("local", "cloud"): (
            "香港公司整体与全球云分部属于不同口径",
            "公司营收不等于云业务收入",
            "本地市场范围与全球业务范围不能直接换算",
            "港元与美元绝对金额只能说明各自规模",
        ),
        ("mainland", "international"): (
            "内地移动用户与国际后付费口径属于不同层面",
            "用户总量不能替代客户价值判断",
            "集团营收与后付费客户指标不能混排",
            "披露缺口限制跨市场客户质量比较",
        ),
    }.get((source_domain, target_domain), ("口径边界", "市场阶段", "范围差异", "测量层次"))
    grounded_seed = _safe_discovery_regeneration_fallback(
        evidence,
        source_domain,
        target_domain,
        current=current,
        regeneration_index=regeneration_count - 1,
    )
    for attempt, model in enumerate(models):
        request_id = f"relation-{index}-{uuid4().hex}"
        angle = regeneration_angles[(regeneration_count - 1 + attempt) % len(regeneration_angles)]
        if attempt >= len(base_models) and grounded_seed:
            request_messages = [
                {
                    "role": "system",
                    "content": (
                        "只返回合法JSON对象{from,to,title,detail,kind,source_urls}。"
                        "严格保留证据底稿中的领域、两个数字和两个来源，改写成一条新的口径或市场阶段判断。"
                        "detail不超过100字；禁止脱钩、结构性差异、驱动、因果、建议和证据外事实。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "from": source_domain,
                        "to": target_domain,
                        **scoped_evidence,
                        "required_angle": angle,
                        "grounded_seed": grounded_seed,
                        "recent_titles_to_avoid": [str(item.get("title") or "") for item in discoveries],
                        "request_id": request_id,
                    }, ensure_ascii=False),
                },
            ]
        else:
            request_messages = [*messages, {
                "role": "user",
                "content": (
                    f"本次重生成请求编号：{request_id}。该编号只用于隔离缓存，不属于证据，不得写入答案。"
                    f"本次必须从“{angle}”形成与最近版本不同的新判断。"
                ),
            }]
        request = urllib.request.Request(
            f"{str(config.get('base_url') or INTERNAL_AI_BASE_URL).rstrip('/')}/chat/completions",
            data=json.dumps(prepare_structured_chat_body({
                **dict(config.get("extra_parameters") or {}),
                "model": model,
                "messages": request_messages,
                "temperature": 0.25 if attempt == 0 else 0.55,
                "max_tokens": 520,
            }), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
                "X-Request-ID": request_id,
            },
            method="POST",
        )
        wait_for_internal_ai_slot(f"executive-intelligence-discovery-{index}")
        try:
            with urlopen_with_local_proxy_fallback(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
            parsed = load_json_response(
                final_chat_message_text(response_payload, operation="跨库AI发现重生成"),
                operation="跨库AI发现重生成",
            )
            if isinstance(parsed, list) and len(parsed) == 1:
                parsed = parsed[0]
            if not isinstance(parsed, dict):
                raise ValueError("模型未返回单项跨库洞察对象")
            if str(parsed.get("from") or "") != source_domain or str(parsed.get("to") or "") != target_domain:
                raise ValueError("模型改变了跨库领域组合")
            unsupported_driver_terms = (
                "驱动", "脱钩", "结构性差异", "需求扩张", "供给扩张", "集中度",
                "AI扩张", "AI需求", "算力需求", "基础设施规模化", "基站共享", "存量基站",
                "客户需求", "套餐组合", "站址扩张", "基建空间",
            )
            leaked_drivers = [term for term in unsupported_driver_terms if term in str(parsed.get("detail") or "")]
            if leaked_drivers:
                raise ValueError(f"模型补写了输入之外的驱动因素：{leaked_drivers}")
            detail = str(parsed.get("detail") or "")
            missing_required_values = [value for value in scoped_evidence["required_values"] if value not in detail]
            if missing_required_values:
                raise ValueError(f"模型未逐字引用两个当前数值：{missing_required_values}")
            current_signature = tuple(re.sub(r"\s+", "", str(current.get(key) or "")) for key in ("title", "detail"))
            parsed_signature = tuple(re.sub(r"\s+", "", str(parsed.get(key) or "")) for key in ("title", "detail"))
            if parsed_signature == current_signature:
                raise ValueError("模型返回了与当前跨库洞察完全相同的结果")
            parsed_text = "".join(parsed_signature)
            parsed_title = re.sub(r"\s+", "", str(parsed.get("title") or ""))
            if max(
                (
                    difflib.SequenceMatcher(None, re.sub(r"\s+", "", title), parsed_title).ratio()
                    for title in relation_title_history
                ),
                default=0.0,
            ) >= 0.94:
                raise ValueError("模型返回的跨库标题与最近版本过于相似")
            if max(
                (difflib.SequenceMatcher(None, previous_text, parsed_text).ratio() for previous_text in comparison_history),
                default=0.0,
            ) >= 0.82:
                raise ValueError("模型返回的跨库判断与最近版本语义过于相似")
            candidate = [dict(item) for item in discoveries]
            candidate[index] = parsed
            replacement = _validate_model_discoveries(candidate, evidence)[index]
            used_model = model
            break
        except (ValueError, json.JSONDecodeError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            messages.append({
                "role": "user",
                "content": f"上一版未通过门禁：{exc}。保持领域组合，换一个数据关系角度，只返回合法JSON对象。",
            })
    if replacement is None:
        fallback = grounded_seed
        if fallback is None:
            raise ValueError("模型本次未返回有效内容")
        candidate = [dict(item) for item in discoveries]
        candidate[index] = fallback
        try:
            replacement = _validate_model_discoveries(candidate, evidence)[index]
        except ValueError as exc:
            raise ValueError("模型本次未返回有效内容") from exc
        used_model = "evidence-rule-fallback"
        fallback_used = True

    report("证据校验通过，正在返回洞察")
    discoveries[index] = replacement
    generated_at = _now()
    updated_counts = dict(prior_counts)
    updated_counts[pair_key] = regeneration_count
    updated_history = json.loads(json.dumps(prior_history, ensure_ascii=False))
    replacement_text = "".join(
        re.sub(r"\s+", "", str(replacement.get(key) or ""))
        for key in ("title", "detail")
    )
    updated_history[pair_key] = list(dict.fromkeys([
        *relation_history,
        current_text,
        replacement_text,
    ]))[-12:]
    updated_title_history = json.loads(json.dumps(prior_title_history, ensure_ascii=False))
    updated_title_history[pair_key] = list(dict.fromkeys([
        *relation_title_history,
        str(current.get("title") or "").strip(),
        str(replacement.get("title") or "").strip(),
    ]))[-12:]
    generated = {
        **previous,
        "generated_at_hkt": generated_at,
        "discoveries": discoveries,
        "discovery_model": used_model,
        "discovery_generated_at_hkt": generated_at,
        "evidence_hash": evidence_hash,
        "insight_format": INSIGHT_FORMAT_VERSION,
        "reused": False,
        "manual_discovery_regeneration_counts": updated_counts,
        "manual_discovery_regeneration_history": updated_history,
        "manual_discovery_regeneration_title_history": updated_title_history,
        "manual_discovery_regeneration": {
            "index": index,
            "from": source_domain,
            "to": target_domain,
            "generated_at_hkt": generated_at,
            "count": regeneration_count,
            "fallback_used": fallback_used,
            "fallback_reason": str(last_error or "") if fallback_used else "",
        },
    }
    analysis["model_analysis"] = generated
    _atomic_write_json(path, analysis)
    return {
        "ok": True,
        "index": index,
        **replacement,
        "model": used_model,
        "fallback_used": fallback_used,
        "generated_at_hkt": generated_at,
    }


def publish_model_domain_summaries(path: Path = AI_ANALYSIS_PATH) -> dict[str, Any]:
    analysis = _read_json(path, {}) or {}
    evidence = _analysis_input_snapshot()
    evidence_hash = _content_hash(evidence)
    previous = analysis.get("model_analysis") or {}
    previous_summaries = previous.get("summaries") or []
    previous_discoveries = previous.get("discoveries") or []
    previous_hash = str(previous.get("evidence_hash") or "")
    previous_format_current = str(previous.get("insight_format") or "") == INSIGHT_FORMAT_VERSION
    if (
        previous_summaries and previous_discoveries and previous_hash == evidence_hash
        and previous_format_current and not previous.get("fallback_used")
    ):
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
    if previous_summaries and previous_hash == evidence_hash and previous_format_current and not previous.get("fallback_used"):
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


def regenerate_model_focus_summary(
    domain_id: str,
    focus_id: str,
    *,
    path: Path = AI_ANALYSIS_PATH,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Regenerate one visible insight against the current evidence and merge it atomically."""
    def report(message: str) -> None:
        if progress:
            progress(message)

    report("正在读取当前证据")
    evidence = _analysis_input_snapshot()
    evidence_hash = _content_hash(evidence)
    domain_evidence = next(
        (domain for domain in evidence.get("domains") or [] if str(domain.get("id") or "") == domain_id),
        None,
    )
    if not domain_evidence:
        raise ValueError(f"未知竞争情报领域：{domain_id}")
    focus_evidence = next(
        (focus for focus in domain_evidence.get("focuses") or [] if str(focus.get("id") or "") == focus_id),
        None,
    )
    if not focus_evidence:
        raise ValueError(f"未知竞争情报关注点：{domain_id}.{focus_id}")

    analysis = _read_json(path, {}) or {}
    previous = analysis.get("model_analysis") or {}
    previous_is_current = bool(
        str(previous.get("evidence_hash") or "") == evidence_hash
        and str(previous.get("insight_format") or "") == INSIGHT_FORMAT_VERSION
        and previous.get("summaries")
    )
    previous_focus = next((
        focus
        for summary in previous.get("summaries") or []
        if str(summary.get("domain") or "") == domain_id
        for focus in summary.get("focuses") or []
        if str(focus.get("id") or "") == focus_id
    ), None) if previous_is_current else None
    history_key = f"{domain_id}.{focus_id}"
    previous_history = previous.get("manual_focus_regeneration_history") or {}
    recent_insights = (
        previous_history.get(history_key) or []
        if isinstance(previous_history, dict)
        else []
    )
    previous_title_history = previous.get("manual_focus_regeneration_title_history") or {}
    if not isinstance(previous_title_history, dict):
        previous_title_history = {}
    recent_headlines = previous_title_history.get(history_key) or []
    if not isinstance(recent_headlines, list):
        recent_headlines = []
    previous_counts = previous.get("manual_focus_regeneration_counts") or {}
    if not isinstance(previous_counts, dict):
        previous_counts = {}
    regeneration_index = int(previous_counts.get(history_key) or 0) + 1
    generation_focus = {
        **focus_evidence,
        "insight": str((previous_focus or {}).get("analysis") or focus_evidence.get("insight") or ""),
        "headline": str((previous_focus or {}).get("headline") or ""),
        "recent_insights": recent_insights,
        "recent_headlines": recent_headlines,
        "regeneration_index": regeneration_index,
    }
    report("正在生成新的数据判断")
    try:
        scoped = generate_model_focus_insight(domain_id, generation_focus, temperature=0.25)
    except Exception as exc:
        # Manual regeneration must remain usable when the internal model is
        # temporarily slow or unavailable. Rotate wording only; all numbers,
        # units, periods and judgements still come from the validated focus.
        fallback_summary = next(
            item for item in _deterministic_domain_summaries(evidence, validate=False)
            if str(item.get("domain") or "") == domain_id
        )
        fallback_focus = next(
            item for item in fallback_summary.get("focuses") or []
            if str(item.get("id") or "") == focus_id
        )
        fallback_focus = json.loads(json.dumps(fallback_focus, ensure_ascii=False))
        fallback_analysis = str(fallback_focus.get("analysis") or "")
        wording_variants = (
            (("表明", "说明"), ("意味着", "反映"), ("不能", "不可")),
            (("说明", "表明"), ("反映", "意味着"), ("不可", "不能")),
        )
        for old, new in wording_variants[(regeneration_index - 1) % len(wording_variants)]:
            fallback_analysis = fallback_analysis.replace(old, new)
        previous_analysis = str((previous_focus or {}).get("analysis") or "")
        if fallback_analysis == previous_analysis:
            for old, new in wording_variants[regeneration_index % len(wording_variants)]:
                fallback_analysis = fallback_analysis.replace(old, new)
        fallback_focus["analysis"] = fallback_analysis
        fallback_focus["origin"] = "evidence_rule"
        scoped = {
            "model": "deterministic-evidence-fallback",
            "focus": fallback_focus,
            "fallback_reason": str(exc)[:500],
        }
    scoped_focus = scoped.get("focus")
    if not isinstance(scoped_focus, dict):
        raise ValueError(f"模型未返回当前洞察：{domain_id}.{focus_id}")

    report("正在校验数字与来源")
    # Rebuild the non-target summaries from current evidence before merging the
    # newly generated focus. A previously valid bundle can still contain copy
    # produced under an older metric meaning (for example record counts rather
    # than deduplicated plan counts); validating that whole stale bundle would
    # reject an otherwise valid new focus and leave the UI apparently unchanged.
    summaries = _deterministic_domain_summaries(evidence, validate=False)
    discoveries = (
        json.loads(json.dumps(previous.get("discoveries") or [], ensure_ascii=False))
        if previous_is_current
        else _deterministic_discoveries(evidence)
    )

    target_domain = next(item for item in summaries if str(item.get("domain") or "") == domain_id)
    target_domain["focuses"] = [
        {**item, **scoped_focus} if str(item.get("id") or "") == focus_id else item
        for item in target_domain.get("focuses") or []
    ]
    repaired_summaries = _repair_model_summaries(summaries, evidence)
    repaired_target = next(
        item for item in repaired_summaries if str(item.get("domain") or "") == domain_id
    )
    validated_target = _validate_model_summaries(
        [repaired_target], evidence, expected_domains={domain_id},
    )[0]
    previous_by_domain = {
        str(item.get("domain") or ""): item
        for item in previous.get("summaries") or []
        if isinstance(item, dict) and str(item.get("domain") or "")
    }
    validated_summaries = []
    for item in repaired_summaries:
        item_domain = str(item.get("domain") or "")
        if item_domain == domain_id:
            validated_summaries.append(validated_target)
            continue
        try:
            validated_summaries.extend(_validate_model_summaries(
                [item], evidence, expected_domains={item_domain},
            ))
        except ValueError:
            # Regenerating one visible tab must not be blocked by a concurrent
            # edit in another domain. Preserve its last summary and leave that
            # domain to its own generation cycle.
            if item_domain in previous_by_domain:
                validated_summaries.append(previous_by_domain[item_domain])
    report("证据校验通过，正在返回洞察")
    if previous_is_current:
        try:
            validated_discoveries = _validate_model_discoveries(discoveries, evidence)
        except ValueError:
            validated_discoveries = _deterministic_discoveries(evidence)
    else:
        validated_discoveries = discoveries

    generated_at = _now()
    updated_history = json.loads(json.dumps(previous_history, ensure_ascii=False)) \
        if isinstance(previous_history, dict) else {}
    updated_history[history_key] = list(dict.fromkeys([
        *[str(value or "").strip() for value in recent_insights if str(value or "").strip()],
        str((previous_focus or {}).get("analysis") or "").strip(),
        str(scoped_focus.get("analysis") or "").strip(),
    ]))[-12:]
    updated_counts = json.loads(json.dumps(previous_counts, ensure_ascii=False))
    updated_counts[history_key] = regeneration_index
    updated_title_history = json.loads(json.dumps(previous_title_history, ensure_ascii=False))
    updated_title_history[history_key] = list(dict.fromkeys([
        *[str(value or "").strip() for value in recent_headlines if str(value or "").strip()],
        str((previous_focus or {}).get("headline") or "").strip(),
        str(scoped_focus.get("headline") or "").strip(),
    ]))[-12:]
    generated = {
        **previous,
        "generated_at_hkt": generated_at,
        "model": str(scoped.get("model") or previous.get("model") or "internal-ai"),
        "summaries": validated_summaries,
        "discoveries": validated_discoveries,
        "evidence_hash": evidence_hash,
        "insight_format": INSIGHT_FORMAT_VERSION,
        "reused": False,
        "manual_focus_regeneration_history": updated_history,
        "manual_focus_regeneration_counts": updated_counts,
        "manual_focus_regeneration_title_history": updated_title_history,
        "manual_focus_regeneration": {"domain": domain_id, "focus": focus_id, "generated_at_hkt": generated_at},
    }
    if not previous_is_current:
        generated["fallback_used"] = True
        generated["fallback_reason"] = "仅当前洞察由AI重新生成，其他洞察使用当前证据回退。"
    analysis["model_analysis"] = generated
    _atomic_write_json(path, analysis)
    return {
        "ok": True,
        "domain": domain_id,
        "focus": focus_id,
        "headline": str(scoped_focus.get("headline") or ""),
        "analysis": str(scoped_focus.get("analysis") or ""),
        "model": generated["model"],
        "origin": str(scoped_focus.get("origin") or "ai"),
        "repaired": bool(scoped_focus.get("repaired")),
        "generated_at_hkt": generated_at,
        "evidence_hash": evidence_hash,
    }


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
        if path.resolve() == LOCAL_PATH.resolve():
            financial_payload = _read_json(LOCAL_FINANCIAL_PATH, {}) or {}
            financial_quality = financial_payload.get("quality") or {}
            reports = [
                item for item in financial_payload.get("reports", [])
                if item.get("verification_status") == "official_document_extracted"
                and int(item.get("core_metric_count") or 0) >= 2
            ]
            if not financial_quality.get("ok") or not reports:
                failures = "；".join(str(item) for item in financial_quality.get("failures") or [])
                raise ValueError(f"本地竞对官方财报结构化门禁未通过：{failures or '没有已通过记录'}")
            latest_report = max(
                reports,
                key=lambda item: (str(item.get("publication_date") or ""), _period_rank(item.get("period"))),
            )
            result["financial_reports"] = len(reports)
            result["latest_financial_period"] = str(latest_report.get("period") or "")
            result["latest_financial_publication_date"] = str(latest_report.get("publication_date") or "")
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
    busy_wait_seconds = max(30, int(os.environ.get("CMHK_PAGES_BUSY_WAIT_SECONDS", "600")))
    busy_deadline = time.monotonic() + busy_wait_seconds
    attempt = 0
    while True:
        attempt += 1
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
        if time.monotonic() >= busy_deadline:
            raise RuntimeError(f"GitHub.io发布队列等待超过{busy_wait_seconds}秒：{result}")
        time.sleep(5)
    if result.get("status") not in {"published", "verified", "unchanged"}:
        raise RuntimeError(f"GitHub.io未完成公开验证：{result}")
    if not str(result.get("public_url") or "").startswith("https://") or not result.get("site_version"):
        raise RuntimeError(f"GitHub.io验证结果字段不完整：{result}")
    return {"ok": True, "attempts": attempt, **result}


def _run_overview_source_recrawl(*, dry_run: bool = False) -> dict[str, Any]:
    """Recheck the official documents that feed the four domains shown in the UI."""
    script = ROOT / "scripts" / "crawl_requested_overview_010304_official_sources.py"
    output = ROOT / "agent_knowledge" / "requested_overview_010304_2016_2025" / "official_source_recrawl.json"
    if not script.is_file():
        raise RuntimeError(f"战略总览官方来源复查脚本不存在：{script}")
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run", "path": str(output)}
    environment = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment.pop(key, None)
    completed = subprocess.run(
        [_builder_python(), str(script)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=1800,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"战略总览官方来源复查失败({completed.returncode})：{(completed.stderr or completed.stdout)[-1200:]}"
        )
    try:
        summary = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError(f"战略总览官方来源复查结果无法解析：{(completed.stdout or completed.stderr)[-1200:]}") from exc
    if not output.is_file() or int(summary.get("retrieved") or 0) <= 0:
        raise RuntimeError(f"战略总览官方来源复查没有形成有效读回：{summary}")
    return {"ok": True, "path": str(output), **summary}


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
        "ui_contract": {
            "domain_ids": list(UI_DOMAIN_IDS),
            "supporting_database_ids": list(SUPPORTING_DOMAIN_IDS),
        },
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
        local_validation = state["domains"]["local"].get("validation") or {}
        local_rows = int(local_validation.get("rows") or 0)
        financial_reports = int(local_validation.get("financial_reports") or 0)
        latest_finance = " · ".join(
            str(local_validation.get(key) or "")
            for key in ("latest_financial_period", "latest_financial_publication_date")
            if local_validation.get(key)
        )
        _task_event(
            task_run_id,
            "本地竞对",
            f"本地竞对库校验通过，共 {local_rows} 条记录；官方财报 {financial_reports} 份"
            f"{f'；最新 {latest_finance}' if latest_finance else ''}。",
        )
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
        if refresh_builders:
            _task_event(
                task_run_id,
                "战略总览来源复查",
                "正在逐一复查当前战略总览四域所引用的官方文件，结果只写审计旁路，不覆盖已核验数值。",
            )
            try:
                state["overview_source_recrawl"] = _run_overview_source_recrawl(dry_run=dry_run)
                recrawl = state["overview_source_recrawl"]
                _task_event(
                    task_run_id,
                    "战略总览来源复查",
                    f"官方来源复查完成：成功 {int(recrawl.get('retrieved') or 0)}，失败 {int(recrawl.get('failed') or 0)}。",
                )
            except Exception as exc:
                state["overview_source_recrawl"] = {"ok": False, "error": str(exc)}
                _append_log(f"overview source recrawl failed {exc}")
                _task_event(task_run_id, "战略总览来源复查", f"官方来源复查失败：{exc}", level="critical")
        else:
            state["overview_source_recrawl"] = {
                "ok": True,
                "skipped": True,
                "reason": "refresh_builders_disabled",
            }
        if dry_run:
            state["model_analysis"] = {"ok": True, "skipped": True, "reason": "dry_run"}
        else:
            current_evidence = _analysis_input_snapshot()
            expected_focus_count = sum(
                len(domain.get("focuses") or [])
                for domain in current_evidence.get("domains") or []
            )
            _task_event(
                task_run_id,
                "生成AI洞察",
                f"正在根据四库最新通过事实生成AI洞察，并对{expected_focus_count}个关注点逐一执行深层解释、简洁度与事实门禁。",
            )
            try:
                model_analysis = publish_model_domain_summaries()
                passed_focus_count = sum(
                    len(summary.get("focuses") or [])
                    for summary in model_analysis.get("summaries") or []
                )
                state["model_analysis"] = {
                    "ok": True,
                    "generated_at_hkt": model_analysis["generated_at_hkt"],
                    "model": model_analysis["model"],
                    "domains": len(model_analysis["summaries"]),
                    "focuses_expected": expected_focus_count,
                    "focuses_passed": passed_focus_count,
                    "reused": bool(model_analysis.get("reused")),
                    "fallback_used": bool(model_analysis.get("fallback_used")),
                    "fallback_reason": str(model_analysis.get("fallback_reason") or ""),
                    "evidence_hash": str(model_analysis.get("evidence_hash") or ""),
                    "discovery_model": str(model_analysis.get("discovery_model") or ""),
                    "discovery_fallback_used": bool(model_analysis.get("discovery_fallback_used")),
                    "discovery_fallback_reason": str(model_analysis.get("discovery_fallback_reason") or ""),
                }
                state["ui_contract"].update(
                    {
                        "focuses_expected": expected_focus_count,
                        "focuses_passed": passed_focus_count,
                        "summary_domain_ids": [
                            str(summary.get("domain") or "") for summary in model_analysis.get("summaries") or []
                        ],
                        "aligned": (
                            [str(summary.get("domain") or "") for summary in model_analysis.get("summaries") or []]
                            == list(UI_DOMAIN_IDS)
                            and passed_focus_count == expected_focus_count
                        ),
                    }
                )
                fallback_note = (
                    f"；回退原因：{state['model_analysis']['fallback_reason']}"
                    if model_analysis.get("fallback_used") else "；未触发回退"
                )
                _task_event(
                    task_run_id,
                    "生成AI洞察",
                    f"{passed_focus_count}/{expected_focus_count}关注点门禁通过；模型：{state['model_analysis']['model']}；"
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
        recrawl_ok = bool(state.get("overview_source_recrawl", {}).get("ok"))
        ui_contract_ok = bool(dry_run or state.get("ui_contract", {}).get("aligned"))
        core_ok = not failed and model_ok and recrawl_ok and ui_contract_ok
        if dry_run:
            state["pages_publish"] = {"ok": True, "skipped": True, "reason": "dry_run"}
        elif core_ok:
            _task_event(
                task_run_id,
                "更新主页UI",
                f"四库与{int(state['model_analysis'].get('focuses_passed') or 0)}个AI洞察均已通过，"
                "正在重建主页数据源、发布GitHub.io并读取公开版本验证。",
            )
            try:
                pages_publish = _publish_and_verify_github_pages()
                state["pages_publish"] = pages_publish
                _task_event(
                    task_run_id,
                    "更新主页UI",
                    f"主页数据源与公开站点已同步并验证；版本：{pages_publish.get('site_version')}；地址：{pages_publish.get('public_url')}",
                )
            except Exception as exc:
                state["pages_publish"] = {"ok": False, "error": str(exc)}
                _append_log(f"github pages publish failed {exc}")
                _task_event(task_run_id, "更新主页UI", f"主页同步、公开发布或验证失败：{exc}", level="critical")
        else:
            state["pages_publish"] = {"ok": False, "skipped": True, "reason": "core_gate_failed"}
        pages_ok = bool(state.get("pages_publish", {}).get("ok"))
        used_fallback = bool(state.get("model_analysis", {}).get("fallback_used"))
        pipeline_ok = core_ok and pages_ok and not used_fallback
        if pipeline_ok:
            final_status = "completed"
        elif core_ok and not pages_ok:
            final_status = "failed_frontend_publish"
        else:
            final_status = "completed_with_fallback"
        state.update(
            {
                "ok": pipeline_ok,
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


def _validated_fallback_complete(result: dict[str, Any]) -> bool:
    """Accept only a fully gated deterministic fallback after AI retries end."""
    analysis = result.get("model_analysis")
    pages = result.get("pages_publish")
    if not isinstance(analysis, dict) or not isinstance(pages, dict):
        return False
    expected = int(analysis.get("focuses_expected") or 0)
    passed = int(analysis.get("focuses_passed") or 0)
    return bool(
        result.get("status") == "completed_with_fallback"
        and not result.get("failed_domains")
        and analysis.get("fallback_used")
        and expected > 0
        and passed == expected
        and pages.get("ok")
    )


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
    fallback_complete = _validated_fallback_complete(result)
    if fallback_complete:
        # The online model path was exhausted, but every deterministic insight
        # passed the same evidence/focus gates and the public artifact was read
        # back. Preserve the degraded status without misreporting the entire
        # morning crawler as failed or retrying it forever.
        result["ok"] = True
        result["degraded"] = True
        result["recovery_exhausted"] = True
    ok = bool(result.get("ok") or result.get("skipped"))
    if ok:
        if result.get("skipped"):
            detail = "已有另一条四库任务执行，本次已安全合并。"
        elif fallback_complete:
            detail = (
                f"在线AI连续 {attempts} 次未通过后，已使用通过全部证据门禁的确定性回退；"
                f"{int((result.get('model_analysis') or {}).get('focuses_passed') or 0)}个洞察及公开页面回读完整。"
            )
        elif (result.get("pages_publish") or {}).get("ok"):
            focus_count = int((result.get("model_analysis") or {}).get("focuses_passed") or 0)
            detail = f"四库、{focus_count}个AI洞察、前端数据源及GitHub.io公开验证已完成，共执行 {attempts} 次。"
        else:
            detail = (
                f"四库、{int((result.get('model_analysis') or {}).get('focuses_passed') or 0)}个AI洞察和前端数据源已完成，但GitHub.io发布验证未通过："
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
    from cmhk.crawl.run_registry import load_index

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
