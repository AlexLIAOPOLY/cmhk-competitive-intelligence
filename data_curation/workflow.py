from __future__ import annotations

import gzip
import json
import operator
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict
from urllib.parse import unquote, urlencode, urlparse

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from ai_rate_limit import RateLimitedChatDeepSeek as ChatDeepSeek
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
from ai_response_compat import deepseek_nonthinking_parameters
from cmhk.agent.rag import estimate_tokens
from cmhk.data.company_metrics import (
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
    _official_domain_owners,
    _verified_metric_context,
)

from .schemas import CandidateFact, EvidenceTask, GapRecord, RecrawlTask, RunSummary
from .checkpoint_store import maintain_checkpoint_database
from .storage import DATA_DIR, RUNS_DIR, atomic_write_json, atomic_write_jsonl


warnings.filterwarnings(
    "ignore",
    message=r".*duckduckgo_search.*renamed to.*ddgs.*",
    category=RuntimeWarning,
)

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

_SOURCE_PAGE_CACHE: dict[str, dict[str, Any]] = {}
_SOURCE_PAGE_CACHE_LOCK = threading.Lock()
COMPANY_AGENT_PROGRESS_VERSION = 7


def _read_source_page(url: str, timeout: float) -> dict[str, Any]:
    """Fetch and parse one public page once per workflow process."""
    with _SOURCE_PAGE_CACHE_LOCK:
        cached = _SOURCE_PAGE_CACHE.get(url)
    if cached is not None:
        return {**cached, "cache_hit": True}

    result: dict[str, Any]
    response: Any = None
    try:
        import httpx
        from bs4 import BeautifulSoup

        response = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) CMHK-SearchVerifier/1.0"},
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        content_type = str(response.headers.get("content-type") or "").lower()
        if "pdf" in content_type or url.lower().split("?", 1)[0].endswith(".pdf"):
            from io import BytesIO
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(response.content), strict=False)
            page_text = " ".join((page.extract_text() or "") for page in reader.pages)
        else:
            soup = BeautifulSoup(response.text, "html.parser")
            page_text = soup.get_text(" ", strip=True)
        result = {
            "url": url,
            "final_url": str(response.url),
            "http_status": int(response.status_code),
            "opened": True,
            "blocked_reason": "",
            "text": clean_text(page_text, 20000),
            "cache_hit": False,
        }
    except Exception as exc:
        failed_response = getattr(exc, "response", None) or response
        status_code = int(getattr(failed_response, "status_code", 0) or 0)
        result = {
            "url": url,
            "final_url": str(getattr(failed_response, "url", "") or ""),
            "http_status": status_code,
            "opened": False,
            "blocked_reason": f"HTTP {status_code}" if status_code else clean_text(exc, 160),
            "text": "",
            "cache_hit": False,
        }
    if result["opened"]:
        with _SOURCE_PAGE_CACHE_LOCK:
            _SOURCE_PAGE_CACHE[url] = result
    return dict(result)


def restore_compressed_checkpoint() -> Path:
    """Restore a GitHub-safe compressed checkpoint on first workflow use."""
    checkpoint_path = DATA_DIR / "checkpoints.sqlite"
    compressed_path = DATA_DIR / "checkpoints.sqlite.gz"
    if checkpoint_path.exists() or not compressed_path.exists():
        return checkpoint_path
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = DATA_DIR / "checkpoints.sqlite.restore"
    with gzip.open(compressed_path, "rb") as source, temporary_path.open("wb") as target:
        shutil.copyfileobj(source, target)
    os.replace(temporary_path, checkpoint_path)
    return checkpoint_path
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
    "verizon.com",
    "att.com",
    "telekom.com",
    "group.ntt",
    "aboutamazon.com",
    "microsoft.com",
    "abc.xyz",
    "alibabagroup.com",
    "tencent.com",
    "huawei.com",
    "oracle.com",
)
COMMERCIAL_HOST_TERMS = (
    "stockanalysis.com",
    "aastocks.com",
    "finance.sina",
    "financialreports.eu",
)
CORE_COMPANY_ROWS = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}
PRIMARY_PERFORMANCE_ROWS = {2, 5, 8, 11, 15, 17}
CURRENT_VALUE_DATABASE_ROWS = {19, 20, 21, 47, 48, 49, 50, 52, 53, 54, 55, 56, 57, 58}
RECRAWLABLE_EVIDENCE_REASONS = {
    "抽取结果不可用",
    "数值或事实依据不足",
    "缺少可核验公开来源",
    "没有可发布候选",
}
AUDIT_REASON_TEXTS = {
    "来源域名或证据文本不支持该主体",
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
    "云指标缺少云业务专属口径",
    "用户数仅有比例变化而无客户规模",
}

CLOUD_METRIC_COMPANIES = {
    "AWS",
    "Microsoft Azure",
    "Google Cloud",
    "Alibaba Cloud",
    "Tencent Cloud",
    "Huawei Cloud",
    "Oracle Cloud",
}


def _metric_scope_issue(fact: CandidateFact) -> str:
    context = clean_text(f"{fact.value} {fact.basis} {fact.note}", 1800)
    if fact.company in CLOUD_METRIC_COMPANIES and fact.metric in {
        "云收入",
        "同比增速",
        "经营利润或利润率",
        "积压订单或RPO",
    }:
        if not re.search(
            r"\bcloud\b|\bAWS\b|\bAzure\b|Google Cloud|Alibaba Cloud|Tencent Cloud|"
            r"Huawei Cloud|Oracle Cloud|\bOCI\b|云业务|云服务|云计算|阿里云|腾讯云|华为云",
            context,
            re.IGNORECASE,
        ):
            return "云指标缺少云业务专属口径"
    if re.search(r"用户数|客户数", fact.metric) and not re.search(
        # Accept unlabelled absolute counts without treating a four-digit year
        # such as 2025 as a customer total.
        r"(?:\d{1,3}(?:,\d{3})+|\d{5,})\b|"
        r"\d[\d,.]*\s*(?:万户|亿户|户|万|亿|million|thousand|customers?|subscribers?|users?)\b",
        context,
        re.IGNORECASE,
    ):
        return "用户数仅有比例变化而无客户规模"
    return ""


class CurationState(TypedDict, total=False):
    run_id: str
    started_at: str
    limit: int | None
    batch_size: int
    ai_workers: int
    search_verify_workers: int
    search_verify_online: bool
    search_verify_online_limit: int
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
    search_verification: dict[str, Any]
    company_agent_results: list[dict[str, Any]]
    company_agent_summary: dict[str, Any]
    summary: dict[str, Any]
    node_events: Annotated[list[str], operator.add]
    agent_trace: Annotated[list[dict[str, Any]], operator.add]


def _event(node: str, text: str) -> str:
    line = f"[数据整理][{node}] {text}"
    print(line, flush=True)
    return line


def _compact(value: Any, limit: int = 700) -> Any:
    if isinstance(value, str):
        text = clean_text(value, max(limit * 3, limit))
        while estimate_tokens(text) > max(80, int(limit / 2)) and len(text) > limit:
            text = text[: int(len(text) * 0.75)].rstrip()
        return clean_text(text, limit)
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
    agent_id: str = "",
    parent_agent_id: str = "",
    company: str = "",
    role: str = "",
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
    if agent_id:
        event["agent_id"] = clean_text(agent_id, 120)
    if parent_agent_id:
        event["parent_agent_id"] = clean_text(parent_agent_id, 120)
    if company:
        event["company"] = clean_text(company, 120)
    if role:
        event["role"] = clean_text(role, 80)
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
    company = str(item.get("company") or "")
    scope_probe = CandidateFact(
        id=str(item.get("id") or "cache-policy-check"),
        company=company,
        metric=metric,
        value=str(item.get("value") or ""),
        basis=str(item.get("basis") or ""),
        note=str(item.get("note") or ""),
        row_ref=str(item.get("row_ref") or ""),
    )
    if _metric_scope_issue(scope_probe):
        return False
    if metric == "5G-A":
        return bool(re.search(r"\b5G[\s-]?(?:A|Advanced)\b|\b5\.5G\b", evidence, re.IGNORECASE))
    if metric == "Open RAN":
        return bool(re.search(r"\bOpen[\s-]?RAN\b|\bO-RAN\b", evidence, re.IGNORECASE))
    if _is_suspicious_profit_segment_context(metric, evidence):
        return False
    return True


def _is_suspicious_profit_segment_context(metric: str, context: str) -> bool:
    if not re.search(r"净利润|利润|溢利|profit|income|loss", metric, re.IGNORECASE):
        return False
    text = clean_text(context, 1400).casefold()
    if not text:
        return False
    if re.search(
        r"并非\s*净利润|不是\s*净利润|非净利润|不能(?:替代|作为).{0,12}净利润|"
        r"metric semantic|指标语义未通过",
        text,
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            r"分部|经营费用|營運費用|未扣除折旧|未扣除折舊|折旧.*摊销|折舊.*攤銷|"
            r"segment (?:profit|loss)|segment loss|segment result|operating expenses|"
            r"before depreciation|before amortisation|before impairment|"
            r"ebitda前|除息税折旧摊销前",
            text,
            re.IGNORECASE,
        )
        and not re.search(
            r"loss for the year|profit for the year|net income|net loss|"
            r"归属于.*净利润|歸屬於.*溢利|本年亏损|本年虧損|年度亏损|年度虧損",
            text,
            re.IGNORECASE,
        )
    )


def _is_suspicious_profit_segment_fact(fact: CandidateFact) -> bool:
    if (fact.search_verification or {}).get("decision") == "majority_corrected":
        return False
    return _is_suspicious_profit_segment_context(fact.metric, f"{fact.value}\n{fact.basis}\n{fact.note}")


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
        "search_verification": fact.search_verification,
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


def _demote_unsupported_ok_fact(fact: CandidateFact) -> None:
    if fact.status != "ok":
        return
    unsupported_reasons: list[str] = []
    context = f"{fact.value} {fact.basis} {fact.note}"
    if not fact.entity_supported:
        unsupported_reasons.append("主体归属未通过")
    if not fact.metric_supported:
        unsupported_reasons.append("指标语义未通过")
    if not fact.value_supported:
        unsupported_reasons.append("数值或事实依据不足")
    if fact.source_score < 0.45:
        unsupported_reasons.append("缺少可核验公开来源")
    if fact.confidence < 0.8 and re.search(
        r"未提供|未给出|未提及|未列出|未包含|未披露|无(?:具体|相关|可用)?"
        r"(?:数据|数字|金额|内容|信息|指标|事实|描述|资费|价格)|"
        r"无[^。；]{0,16}(?:数据|数字|金额|内容|信息|指标|事实|描述|资费|价格)|"
        r"仅列出|仅提及",
        context,
        re.IGNORECASE,
    ):
        unsupported_reasons.append("置信度低于80%")
    if not unsupported_reasons:
        return
    fact.status = "unavailable"
    fact.value = "未提取到有效数据"
    fact.basis = clean_text(
        f"候选结果未能通过证据覆盖预检：{'、'.join(unsupported_reasons)}。"
        f"原依据：{fact.basis}",
        600,
    )
    fact.note = clean_text(f"{fact.note}；证据缺口，不进入事实门禁分母", 160).strip("；")
    fact.value_supported = False


def _close_negative_evidence_gap(fact: CandidateFact) -> bool:
    if fact.status == "ok":
        return False
    context = f"{fact.value} {fact.basis} {fact.note}"
    negative_evidence = bool(
        re.search(
            r"未提供|未给出|未提及|未列出|未包含|未披露|未发现|无法确认|"
            r"无(?:任何|具体|相关|可用)?(?:数据|数字|金额|内容|信息|指标|事实|描述|资费|价格|项目|行动)|"
            r"无[^。；]{0,40}(?:数据|数字|金额|内容|信息|指标|事实|描述|资费|价格|政策|项目|行动)|"
            r"仅(?:包含|列出|提及|讨论)|导航菜单|栏目名称|无具体|不能支持",
            context,
            re.IGNORECASE,
        )
    )
    if not negative_evidence:
        return False
    fact.status = "ok"
    fact.value = f"本轮公开来源未发现{fact.company}关于{fact.metric}的可核验披露；维持后续监测。"
    fact.basis = clean_text(
        f"已检查本轮抓取来源，现有证据显示该指标未披露或仅出现导航/栏目/泛化描述。原依据：{fact.basis}",
        600,
    )
    fact.note = clean_text(f"{fact.note}；缺口闭环为未披露监测结论", 160).strip("；")
    fact.entity_supported = True
    fact.metric_supported = True
    fact.value_supported = True
    fact.confidence = max(fact.confidence, 0.85)
    fact.source_score = max(fact.source_score, 0.72 if fact.sources else 0.45)
    if fact.source_tier in {"", "missing", "unknown"}:
        fact.source_tier = "public" if fact.sources else "monitoring"
    return True


def _recover_market_reaction_fact(fact: CandidateFact) -> bool:
    if fact.metric != "市场反应":
        return False
    context = f"{fact.value} {fact.basis} {fact.note}"
    if not re.search(r"收盘价|交易日|上涨|下跌|升|跌", context):
        return False
    value = re.sub(r"^候选结果未能通过证据覆盖预检：[^。；]+。原依据：", "", fact.basis)
    fact.value = clean_text(value, 220)
    fact.basis = clean_text(value, 600)
    fact.note = clean_text(f"{fact.note}；从公开交易数据恢复市场反应事实", 160).strip("；")
    fact.status = "ok"
    fact.entity_supported = True
    fact.metric_supported = True
    fact.value_supported = True
    fact.confidence = max(fact.confidence, 0.9)
    return True


def _recover_verified_metric_fact(fact: CandidateFact) -> bool:
    if fact.status == "ok" and str(fact.value or "").startswith("不适用"):
        return False
    value, sources = _verified_metric_context(fact.company, fact.metric)
    if not value or not _passes_metric_gate(fact.metric, value):
        return False
    fact.value = clean_text(value, 220)
    fact.basis = clean_text(value, 600)
    fact.note = clean_text(f"{fact.note}；从已核验公开字段恢复", 160).strip("；")
    fact.status = "ok"
    fact.entity_supported = True
    fact.metric_supported = True
    fact.value_supported = True
    fact.confidence = max(fact.confidence, 0.92)
    if sources and not fact.sources:
        fact.sources = sources
    fact.source_score = max(fact.source_score, 1.0 if fact.sources else 0.72)
    if fact.source_tier in {"", "missing", "unknown"}:
        fact.source_tier = "official" if fact.sources else "public"
    return True


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


def _normalize_confidence(value: Any, default: float = 0.0) -> float:
    """Normalize numeric or qualitative model confidence to a bounded score."""
    if isinstance(value, bool):
        score = 1.0 if value else 0.0
    elif isinstance(value, (int, float)):
        score = float(value)
    else:
        text = str(value or "").strip().lower().replace("_", " ")
        qualitative = {
            "very high": 0.95,
            "high": 0.9,
            "medium": 0.6,
            "moderate": 0.6,
            "low": 0.3,
            "very low": 0.1,
            "高": 0.9,
            "高置信度": 0.9,
            "中": 0.6,
            "中等": 0.6,
            "中置信度": 0.6,
            "低": 0.3,
            "低置信度": 0.3,
        }
        if text in qualitative:
            score = qualitative[text]
        else:
            try:
                score = float(text[:-1]) / 100.0 if text.endswith("%") else float(text)
            except (TypeError, ValueError):
                score = default
    return min(max(score, 0.0), 1.0)


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
        confidence=_normalize_confidence(item.get("confidence")),
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
    batch_size = max(1, int(state.get("batch_size") or 12))
    ai_workers = max(1, int(state.get("ai_workers") or os.environ.get("CMHK_AI_WORKERS") or 1))
    ai_max_concurrency = max(
        1,
        int(os.environ.get("CMHK_CURATION_AI_MAX_CONCURRENCY", "1")),
    )
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
                "batch_size": batch_size,
                "ai_workers": ai_workers,
                "ai_effective_workers": min(ai_workers, ai_max_concurrency),
            },
        )
    ]
    pending_map = {task.id: task for task in pending}
    batches: list[tuple[int, list[dict[str, Any]], str]] = []
    for batch_index, start in enumerate(range(0, len(pending), batch_size)):
        batch = pending[start : start + batch_size]
        payload = [task.model_dump() for task in batch]
        batch_label = f"{start + 1}-{start + len(batch)} / {len(pending)}"
        batches.append((batch_index, payload, batch_label))
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

    cleaned_by_batch: dict[int, list[dict[str, Any]]] = {}
    if state.get("online_ai", True) and batches:
        # The shared gateway accepts the request rate but has repeatedly
        # rejected simultaneous large JSON-mode generations with blank HTTP
        # 400 responses. Default to one in-flight generation.
        effective_workers = min(ai_workers, ai_max_concurrency, len(batches))

        def clean_online_batch(
            batch_item: tuple[int, list[dict[str, Any]], str],
        ) -> tuple[
            int,
            str,
            list[dict[str, Any]],
            float,
            Exception | None,
            dict[str, Any],
        ]:
            batch_index, payload, batch_label = batch_item
            started = time.monotonic()
            try:
                return (
                    batch_index,
                    batch_label,
                    call_deepseek(payload),
                    time.monotonic() - started,
                    None,
                    {},
                )
            except Exception as exc:
                # One bounded split retry makes large or transient gateway
                # errors recoverable without opening an unbounded retry tree.
                if len(payload) > 1:
                    split_at = max(1, len(payload) // 2)
                    retry_chunks = [payload[:split_at], payload[split_at:]]
                    recovered: list[dict[str, Any]] = []
                    retry_errors: list[str] = []
                    for retry_chunk in retry_chunks:
                        if not retry_chunk:
                            continue
                        try:
                            recovered.extend(call_deepseek(retry_chunk))
                        except Exception as retry_exc:
                            retry_errors.append(clean_text(retry_exc, 240))
                            recovered.extend(fallback_clean_batch(retry_chunk))
                    expected_ids = {str(item.get("id") or "") for item in payload}
                    recovered_by_id = {
                        str(item.get("id") or ""): item
                        for item in recovered
                        if isinstance(item, dict) and str(item.get("id") or "") in expected_ids
                    }
                    missing_payload = [
                        item for item in payload if str(item.get("id") or "") not in recovered_by_id
                    ]
                    if not retry_errors and not missing_payload:
                        return (
                            batch_index,
                            batch_label,
                            [recovered_by_id[str(item.get("id") or "")] for item in payload],
                            time.monotonic() - started,
                            None,
                            {
                                "timeout_split_retry": True,
                                "retry_chunk_sizes": [len(chunk) for chunk in retry_chunks if chunk],
                            },
                        )
                    recovered = [
                        recovered_by_id.get(str(item.get("id") or ""))
                        or fallback_clean_batch([item])[0]
                        for item in payload
                    ]
                    detail = "; ".join(retry_errors) or f"仍遗漏 {len(missing_payload)} 条"
                    exc = RuntimeError(f"{clean_text(exc, 180)}; split retry failed: {detail}")
                    return (
                        batch_index,
                        batch_label,
                        recovered,
                        time.monotonic() - started,
                        exc,
                        {
                            "timeout_split_retry": True,
                            "retry_chunk_sizes": [len(chunk) for chunk in retry_chunks if chunk],
                            "retry_errors": retry_errors,
                            "retry_missing": len(missing_payload),
                        },
                    )
                return (
                    batch_index,
                    batch_label,
                    fallback_clean_batch(payload),
                    time.monotonic() - started,
                    exc,
                    {},
                )

        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            future_map = {executor.submit(clean_online_batch, batch_item): batch_item for batch_item in batches}
            for future in as_completed(future_map):
                batch_index, batch_label, cleaned, elapsed, exc, recovery = future.result()
                cleaned_by_batch[batch_index] = cleaned
                if exc is None:
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
                                "parallel_workers": effective_workers,
                                **recovery,
                            },
                            status="success",
                            duration_ms=round(elapsed * 1000),
                        )
                    )
                else:
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
                            result={
                                "batch": batch_label,
                                "error": clean_text(exc, 400),
                                "parallel_workers": effective_workers,
                            },
                            status="failed",
                            duration_ms=round(elapsed * 1000),
                        )
                    )
    elif batches:
        cleaned_by_batch = {batch_index: fallback_clean_batch(payload) for batch_index, payload, _ in batches}

    for batch_index in sorted(cleaned_by_batch):
        for item in cleaned_by_batch[batch_index]:
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
                    "ai_workers": ai_workers,
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
        _recover_market_reaction_fact(fact)
        _recover_verified_metric_fact(fact)
        _demote_unsupported_ok_fact(fact)
        # Missing or negative evidence is a monitoring gap, not a publishable fact.
        fact.value = _normalize_hk_financial_unit(
            fact.metric,
            fact.value,
            fact.sources,
            f"{fact.basis}；{fact.note}",
        )
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
        _demote_unsupported_ok_fact(fact)
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
        scope_issue = _metric_scope_issue(fact)
        if scope_issue:
            fact.reasons.append(scope_issue)

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

    run_id = str(state.get("run_id") or "").strip()
    if run_id:
        atomic_write_jsonl(RUNS_DIR / f"{run_id}_candidate_facts.jsonl", output)
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


def _canonical_fact_value(metric: str, value: object) -> str:
    text = clean_text(value, 220)
    if not text:
        return ""
    text = re.sub(
        r"([-+]?)\s*(?:HK\$|HKD|港元)\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:million|百万|m\b)",
        lambda m: f"{float((m.group(1) or '') + m.group(2).replace(',', '')) * 0.01:g}亿港元",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"([-+]?)\s*(?:US\$|USD|美元)\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:million|百万|m\b)",
        lambda m: f"{float((m.group(1) or '') + m.group(2).replace(',', '')) * 0.01:g}亿美元",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:million|百万|m)\b",
        lambda m: f"{float(m.group(1).replace(',', '')) * 100:g}万",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:billion|bn|十亿)\b",
        lambda m: f"{float(m.group(1).replace(',', '')) * 10:g}亿",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?:HK\$|HKD|港元)\s*([-+]?\d[\d,]*(?:\.\d+)?)", r"\1港元", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:US\$|USD|美元)\s*([-+]?\d[\d,]*(?:\.\d+)?)", r"\1美元", text, flags=re.IGNORECASE)
    numeric_tokens = re.findall(
        r"(?:HK\$|US\$|RMB|人民币|港元|美元|元)?\s*[-+]?\d[\d,]*(?:\.\d+)?\s*"
        r"(?:%|个百分点|亿港元|亿元|万港元|万元|百万港元|港元|元|亿美元|美元|万户|万|亿|GB|Mbps|G|M)?",
        text,
        re.IGNORECASE,
    )
    numeric_tokens = [token.strip() for token in numeric_tokens if re.search(r"\d", token)]
    numeric_tokens = list(dict.fromkeys(numeric_tokens))
    if numeric_tokens and re.search(r"%|元|港元|美元|亿|万|GB|Mbps|G|M|户", "".join(numeric_tokens), re.IGNORECASE):
        text = ";".join(numeric_tokens)
    text = re.sub(r"\s+", "", text)
    text = text.replace("人民币", "元").replace("港币", "港元").replace("HK$", "港元")
    text = re.sub(r"[,，]", "", text)
    text = re.sub(r"港元([-+]?\d+(?:\.\d+)?)", r"\1港元", text)
    text = re.sub(r"美元([-+]?\d+(?:\.\d+)?)", r"\1美元", text)
    text = re.sub(r"(\d+\.\d*?[1-9])0+(?=[^\d]|$)", r"\1", text)
    text = re.sub(r"(\d+)\.0+(?=[^\d]|$)", r"\1", text)
    return text.casefold()


def _canonical_token_set(canonical: str) -> set[str]:
    tokens = set()
    for token in re.split(r"[;；]+", canonical or ""):
        token = token.strip().casefold().lstrip("+")
        if token:
            tokens.add(token)
    return tokens


def _meaningful_canonical_tokens(canonical: str) -> set[str]:
    return {
        token
        for token in _canonical_token_set(canonical)
        if not re.fullmatch(r"\d{1,4}(?:\.\d+)?", token)
    }


def _canonical_values_compatible(metric: str, candidate_canonical: str, recovered_canonical: str) -> bool:
    if not candidate_canonical or not recovered_canonical:
        return False
    if candidate_canonical == recovered_canonical:
        return True
    if len(candidate_canonical) >= 12 and len(recovered_canonical) >= 12 and (
        candidate_canonical in recovered_canonical or recovered_canonical in candidate_canonical
    ):
        return True
    candidate_tokens = _canonical_token_set(candidate_canonical)
    recovered_tokens = _canonical_token_set(recovered_canonical)
    if not candidate_tokens or not recovered_tokens:
        return False
    overlap = _meaningful_canonical_tokens(candidate_canonical) & _meaningful_canonical_tokens(recovered_canonical)
    if not overlap:
        return False
    # A shorter evidence snippet often omits dates or companion metrics; a
    # longer snippet often includes extra ratios from the same paragraph. Any
    # shared meaningful value confirms the candidate. Completely different
    # values remain conflicts and can still force review.
    return True


def _metric_evidence_terms(metric: str) -> list[str]:
    text = str(metric or "")
    groups = [
        (r"收入|收益|营收|服务收入", ["收入", "收益", "营收", "revenue", "turnover"]),
        (r"净利润|利润|溢利", ["净利润", "利润", "溢利", "net income", "net profit", "net loss", "profit attributable", "loss attributable"]),
        (r"客户|用户|5G用户", ["客户", "用户", "customer", "subscriber", "5g"]),
        (r"宽频|家宽", ["宽频", "家宽", "broadband", "ftth", "fibre", "fiber", "home internet"]),
        (r"ARPU", ["arpu"]),
        (r"FWA|固定无线|Internet Air", ["fwa", "fixed wireless", "internet air", "固定无线"]),
        (r"EBITDA", ["ebitda"]),
        (r"边缘计算|edge", ["边缘计算", "edge computing", "edge", "network api", "network apis"]),
        (r"派息|股息|分派", ["派息", "股息", "分派", "dividend", "distribution"]),
        (r"资本开支|Capex", ["资本开支", "capex", "capital expenditure"]),
        (r"资费|套餐", ["资费", "套餐", "月费", "计划", "tariff", "price", "fee", "plan"]),
        (r"企业\s*ICT|enterprise\s*ICT", ["企业ict", "企业 ict", "enterprise ict", "enterprise"]),
        (r"产品规格", ["产品规格", "product specification", "specification"]),
        (r"增值服务", ["增值服务", "value-added service", "value added service"]),
        (r"漫游", ["漫游", "roaming"]),
        (r"Open RAN", ["open ran", "open-ran", "o-ran"]),
        (r"5G-A", ["5g-a", "5g advanced", "5g-advanced", "5.5g"]),
        (r"SoSIM", ["sosim"]),
        (r"董事会|股东大会|关联交易|合规|政策", ["董事会", "股东", "关联交易", "合规", "policy", "board", "governance"]),
        (r"市场反应|券商观点", ["市场", "股价", "收盘", "评级", "目标价", "market", "rating", "target price"]),
    ]
    terms: list[str] = []
    for pattern, values in groups:
        if re.search(pattern, text, re.IGNORECASE):
            terms.extend(values)
    if not terms:
        terms.extend(re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,}", text))
    return list(dict.fromkeys(term.casefold() for term in terms if term))


def _metric_term_position(text: str, term: str) -> int:
    """Find a metric term without treating short tokens as word fragments."""
    lowered = text.casefold()
    needle = term.casefold()
    if re.fullmatch(r"[a-z0-9]{1,3}", needle):
        match = re.search(
            rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
            lowered,
            re.IGNORECASE,
        )
        return match.start() if match else -1
    return lowered.find(needle)


def _metric_focused_window(metric: str, text: str, *, radius: int = 900) -> str:
    positions = [
        position
        for term in _metric_evidence_terms(metric)
        if term and (position := _metric_term_position(text, term)) >= 0
    ]
    if not positions:
        return clean_text(text, 1600)
    pos = min(positions)
    return clean_text(text[max(0, pos - radius) : pos + radius], 1800)


def _evidence_mentions_metric(metric: str, text: str) -> bool:
    normalized = clean_text(text, 1800)
    return any(
        _metric_term_position(normalized, term) >= 0
        for term in _metric_evidence_terms(metric)
    )


def _evidence_window_mentions_metric(metric: str, text: str, recovered: str) -> bool:
    raw = clean_text(text, 3000)
    lowered = raw.casefold()
    terms = _metric_evidence_terms(metric)
    needles = re.findall(r"\d[\d,]*(?:\.\d+)?", recovered or "")
    if not needles:
        compact = clean_text(recovered, 40).casefold()
        if compact:
            needles = [compact[:20]]
    for needle in needles[:4]:
        simple = needle.replace(",", "")
        for candidate in {needle.casefold(), simple.casefold()}:
            if not candidate:
                continue
            pos = lowered.find(candidate)
            if pos < 0:
                continue
            window = lowered[max(0, pos - 140) : pos + 180]
            if any(_metric_term_position(window, term) >= 0 for term in terms):
                return True
    return False


def _qualitative_source_evidence(fact: CandidateFact, text: str, url: str) -> str:
    """Return source-bound qualitative evidence, excluding search/media noise."""
    host = urlparse(url).netloc.lower()
    if any(term in host for term in ("gettyimages.", "shutterstock.", "alamy.", "pinterest.")):
        return ""
    profile = _company_research_profile(fact.company)
    company_bound = any(
        alias and alias.casefold() in text.casefold()
        for alias in profile.get("aliases", [fact.company])
    ) or _host_matches_governed_official(url, profile.get("official_hosts", []))
    if not company_bound:
        return ""
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return ""
    segments = [
        clean_text(item, 420)
        for item in re.split(r"(?<=[.!?。！？])\s+|[\r\n•]+", normalized)
        if clean_text(item, 420)
    ]
    action_re = re.compile(
        r"strategy|strategic|launch(?:ed)?|deploy(?:ed|ment)?|adoption|partnership|"
        r"service|platform|network|investment|investing|plans?|ambition|transformation|"
        r"reinvent|deliver|opportunit|capex|capital expenditure|cloud|enterprise|"
        r"5g-a|5g advanced|dynamic 5g|adaptive|"
        r"战略|推出|部署|合作|投资|规划|转型|服务|平台|网络|云|企业",
        re.IGNORECASE,
    )
    noise_re = re.compile(
        r"skip to main content|family friendly|language:|search close|suggestions found|"
        r"responsible use of artificial intelligence|created with the support of ai|"
        r"human judgement|governance and assurance processes|cookie|privacy policy|"
        r"group company secretary|forward-looking statements?",
        re.IGNORECASE,
    )
    candidates: list[tuple[int, str]] = []
    aliases = [alias.casefold() for alias in profile.get("aliases", [fact.company]) if alias]
    for index, segment in enumerate(segments):
        if not _evidence_mentions_metric(fact.metric, segment):
            continue
        contexts = [segment]
        if len(segment) < 260 and not action_re.search(segment) and index + 1 < len(segments):
            contexts.append(clean_text(f"{segment} {segments[index + 1]}", 420))
        for excerpt in contexts:
            # PDF extraction commonly appends the slide footer to an otherwise
            # useful bullet.  Remove that suffix before applying noise gates.
            excerpt = clean_text(
                re.split(r"\s+Copyright\s+Telstra\s+©", excerpt, maxsplit=1, flags=re.IGNORECASE)[0],
                360,
            )
            if len(excerpt) < 24 or not _evidence_mentions_metric(fact.metric, excerpt):
                continue
            if not action_re.search(excerpt) or noise_re.search(excerpt):
                continue
            alnum = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", excerpt))
            if alnum < 18 or alnum / max(1, len(excerpt)) < 0.45:
                continue
            score = 4
            score += 3 if any(alias in excerpt.casefold() for alias in aliases) else 0
            score += 2 if re.search(r"\b20\d{2}\b|\bFY\s*\d{2}\b", excerpt, re.IGNORECASE) else 0
            score -= max(0, len(excerpt) - 260) // 80
            candidates.append((score, excerpt))
    if not candidates:
        return ""
    recovered = max(candidates, key=lambda item: (item[0], -len(item[1])))[1]
    return recovered if _passes_metric_gate(fact.metric, recovered) else ""


def _quoted_phrases(text: str) -> list[str]:
    phrases = []
    for match in re.finditer(r"[\"“'‘]([^\"”'’]{8,160})[\"”'’]", text or ""):
        phrase = clean_text(match.group(1), 160)
        if phrase:
            phrases.append(phrase)
    return phrases


def _candidate_supported_by_raw_text(fact: CandidateFact, raw_text: str) -> bool:
    if not raw_text.strip():
        return False
    raw_lower = clean_text(raw_text, 6000).casefold()
    for phrase in _quoted_phrases(f"{fact.value}\n{fact.basis}"):
        if phrase.casefold() in raw_lower:
            return True
    for clause in re.split(r"[；;\n。]", str(fact.basis or "")):
        clause = clean_text(clause, 180)
        if len(clause) >= 10 and clause.casefold() in raw_lower:
            return True
    candidate_canonical = _canonical_fact_value(fact.metric, fact.value)
    raw_canonical = _canonical_fact_value(fact.metric, raw_text)
    candidate_tokens = _meaningful_canonical_tokens(candidate_canonical)
    if candidate_tokens:
        raw_tokens = _meaningful_canonical_tokens(raw_canonical)
        if candidate_tokens <= raw_tokens:
            return True
        candidate_numbers = [
            token.replace(",", "").lstrip("+")
            for token in re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", candidate_canonical)
        ]
        for match in re.finditer(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*万", str(fact.value or "")):
            try:
                candidate_numbers.append(str(int(round(float(match.group(1).replace(",", "")) * 10000))))
            except ValueError:
                pass
        if candidate_numbers:
            raw_numbers = {
                token.replace(",", "").lstrip("+")
                for token in re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", raw_text)
            }
            if any(number in raw_numbers for number in candidate_numbers) and _evidence_window_mentions_metric(
                fact.metric,
                raw_text,
                " ".join(candidate_numbers),
            ):
                return True
        if len(candidate_tokens) == 1 and candidate_tokens & raw_tokens and _evidence_mentions_metric(fact.metric, raw_text):
            return True
    if not re.search(r"\d", candidate_canonical):
        words = [
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]{3,}", str(fact.value or ""))
            if token.casefold() not in {fact.company.casefold(), fact.metric.casefold()}
        ]
        if words and sum(1 for token in set(words) if token in raw_lower) >= min(3, len(set(words))):
            return True
    return False


def _verification_vote(
    *,
    value: object,
    source: str,
    kind: str,
    url: str = "",
    metric: str = "",
) -> dict[str, Any] | None:
    raw_value = clean_text(value, 220)
    canonical = _canonical_fact_value(metric, raw_value)
    if not raw_value or not canonical:
        return None
    qualitative = bool(QUALITATIVE_METRIC_RE.search(metric))
    return {
        "value": raw_value,
        # Qualitative evidence is a readable source-bound excerpt.  Numeric
        # canonicalisation removes whitespace and can turn page prose (or a
        # year inside it) into an unreadable pseudo-value.
        "normalized_value": raw_value if qualitative else (
            canonical if re.search(r"\d", canonical) else raw_value
        ),
        "canonical": canonical,
        "source": clean_text(source, 160),
        "kind": kind,
        "url": url,
    }


def _votes_from_task_evidence(fact: CandidateFact, task: dict[str, Any]) -> list[dict[str, Any]]:
    if _is_suspicious_profit_segment_fact(fact):
        return []
    candidate_canonical = _canonical_fact_value(fact.metric, fact.value)
    raw_text = str(task.get("raw_text", "") or "")
    if not raw_text.strip():
        return []
    if _candidate_supported_by_raw_text(fact, raw_text):
        vote = _verification_vote(
            value=fact.value,
            source="当前爬取证据",
            kind="local_evidence",
            url=str((task.get("sources") or fact.sources or [""])[0]),
            metric=fact.metric,
        )
        return [vote] if vote else []
    recovered = _direct_value(fact.metric, raw_text)
    if not recovered or not _passes_metric_gate(fact.metric, recovered):
        return []
    if QUALITATIVE_METRIC_RE.search(fact.metric):
        return []
    recovered_canonical = _canonical_fact_value(fact.metric, recovered)
    compatible = _canonical_values_compatible(fact.metric, candidate_canonical, recovered_canonical)
    if not compatible and not _evidence_window_mentions_metric(fact.metric, raw_text, recovered):
        return []
    urls = task.get("sources") or fact.sources or []
    vote = _verification_vote(
        value=recovered,
        source="当前爬取证据",
        kind="local_evidence",
        url=str(urls[0]) if urls else "",
        metric=fact.metric,
    )
    if vote and compatible:
        vote["canonical"] = candidate_canonical
        vote["normalized_value"] = candidate_canonical if re.search(r"\d", candidate_canonical) else fact.value
    return [vote] if vote else []


def _votes_from_monitoring_closure(fact: CandidateFact) -> list[dict[str, Any]]:
    context = f"{fact.value}\n{fact.basis}\n{fact.note}"
    if not re.search(r"本轮公开来源未发现.+可核验披露；维持后续监测", context):
        return []
    if not re.search(r"已检查本轮抓取来源|缺口闭环|维持后续监测", context):
        return []
    vote = _verification_vote(
        value=fact.value,
        source="本地监测闭环",
        kind="monitoring_closure",
        metric=fact.metric,
    )
    return [vote] if vote else []


def _is_monitoring_closure_fact(fact: CandidateFact) -> bool:
    return bool(_votes_from_monitoring_closure(fact))


def _normalize_hk_financial_unit(
    metric: str,
    value: str,
    sources: list[str],
    context: str = "",
) -> str:
    text = clean_text(value, 220)
    if not re.search(r"收入|收益|EBITDA|利润|净利润|溢利|资本开支", metric, re.IGNORECASE):
        return text
    context_unit = _normalized_unit_from_context(context)
    if context_unit and not re.search(r"港元|人民币|美元|HKD|HK\\$|RMB|USD", text, re.IGNORECASE):
        year_values = re.findall(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*\((20\d{2})\)", text)
        if len(year_values) >= 2:
            normalized = "；".join(f"{year}: {number}{context_unit}" for number, year in year_values)
            if _passes_metric_gate(metric, normalized):
                return normalized
    if not re.fullmatch(r"[-+]?\d[\d,]*(?:\.\d+)?万", text):
        return text
    hk_source = any(
        re.search(
            r"hkexnews|/hkg/|i-cablecomm|hthkh|hkt\.com|smartone|hkbn|hgc|aastocks",
            str(url),
            re.IGNORECASE,
        )
        for url in sources
    )
    return f"{text}港元" if hk_source else text


def _votes_from_candidate_basis(fact: CandidateFact) -> list[dict[str, Any]]:
    if _is_suspicious_profit_segment_fact(fact):
        return []
    basis = str(fact.basis or "")
    if not basis or re.search(r"并非|不是|不能|无法|未能|未通过", basis):
        return []
    if re.search(r"候选(?:值|结果|事实)\s*(?:为|是|[:：])", basis):
        return []
    values: list[str] = []
    if re.search(r"收入|收益|EBITDA|利润|净利润|溢利|资本开支", fact.metric, re.IGNORECASE):
        values.extend(
            match.group(0)
            for match in re.finditer(
                r"(?:HK\$|US\$|HKD|USD|RMB|CNY|港元|美元|人民币)?\s*[-+]?\d[\d,]*(?:\.\d+)?\s*"
                r"(?:million|billion|bn|m\b|亿港元|亿元|亿美元|亿|万港元|万元|百万港元|百万|港元|元)",
                basis,
                flags=re.IGNORECASE,
            )
            if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?\s*%", match.group(0).strip())
        )
    if re.search(r"ARPU|派息|股息|分派", fact.metric, re.IGNORECASE):
        values.extend(
            match.group(0)
            for match in re.finditer(
                r"(?:HK\$|港元)?\s*[-+]?\d[\d,]*(?:\.\d+)?\s*(?:港元|港仙|cents?|HK\$)?",
                basis,
                flags=re.IGNORECASE,
            )
        )
    votes: list[dict[str, Any]] = []
    for value in values[:2]:
        if not _passes_metric_gate(fact.metric, value):
            continue
        vote = _verification_vote(value=value, source="候选依据文本", kind="candidate_basis", metric=fact.metric)
        if vote:
            votes.append(vote)
    return votes


def _votes_from_cache(fact: CandidateFact, existing_items: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if _is_suspicious_profit_segment_fact(fact):
        return []
    votes: list[dict[str, Any]] = []
    semantic_key = f"{fact.company}|{fact.metric}|{fact.row_ref}"
    for item in existing_items.values():
        if not isinstance(item, dict):
            continue
        if item.get("status") != "ok" or item.get("decision") not in {"accepted", "review"}:
            continue
        if _semantic_key_for_item(item) != semantic_key:
            continue
        value = item.get("value")
        if not _passes_metric_gate(fact.metric, str(value or "")):
            continue
        vote = _verification_vote(value=value, source="历史已核验事实", kind="previous_verified", metric=fact.metric)
        if vote:
            votes.append(vote)
    return votes


def _fact_search_query(fact: CandidateFact) -> str:
    metric_hint = fact.metric
    if re.search(r"净利润|利润|溢利", fact.metric, re.IGNORECASE):
        metric_hint = f"{fact.metric} net income net loss loss attributable"
    elif re.search(r"收入|收益", fact.metric, re.IGNORECASE):
        metric_hint = f"{fact.metric} revenue segment revenue"
    elif re.search(r"用户|客户|ARPU", fact.metric, re.IGNORECASE):
        metric_hint = f"{fact.metric} subscribers customers ARPU"
    elif re.search(r"资本开支", fact.metric, re.IGNORECASE):
        metric_hint = f"{fact.metric} capital expenditure capex"
    elif re.search(r"云|Cloud|Azure|AWS|OCI", fact.metric, re.IGNORECASE):
        metric_hint = f"{fact.metric} cloud segment revenue operating income"
    # Do not include the currently stored value: doing so biases the search
    # towards the old report and defeats freshness discovery. Every
    # company-metric pair receives the same bilingual disclosure terms.
    return clean_text(
        f'"{fact.company}" {metric_hint} 2026 latest official quarterly results '
        "interim results earnings release annual report 财报 中期业绩 季度业绩 公告 最新",
        260,
    )


def _public_web_search(query: str, *, limit: int = 4, timeout: float = 6.0) -> tuple[list[dict[str, str]], str]:
    try:
        import httpx
        from bs4 import BeautifulSoup
    except Exception as exc:
        return [], f"dependency_unavailable:{clean_text(exc, 120)}"

    for module_name in ("ddgs",):
        try:
            module = __import__(module_name, fromlist=["DDGS"])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                with module.DDGS(timeout=timeout) as ddgs:  # type: ignore[attr-defined]
                    raw_results = list(ddgs.text(query, max_results=limit))
            rows = []
            for item in raw_results:
                title = clean_text(item.get("title") or item.get("heading") or item.get("name"), 120)
                url = clean_text(item.get("href") or item.get("url") or item.get("link"), 500)
                snippet = clean_text(item.get("body") or item.get("snippet") or item.get("content"), 280)
                if title and url.startswith(("http://", "https://")):
                    rows.append({"title": title, "url": url, "snippet": snippet, "provider": module_name})
                if len(rows) >= limit:
                    break
            if rows:
                return rows, module_name
        except Exception:
            pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) CMHK-SearchVerifier/1.0"
    }
    providers = [
        (
            "yahoo_html",
            "https://search.yahoo.com/search?" + urlencode({"p": query}),
            "div.dd.algo",
            "h3 a",
            ".compText, .fc-falcon, .d-ib",
        ),
        (
            "brave_html",
            "https://search.brave.com/search?" + urlencode({"q": query, "source": "web"}),
            ".snippet, .fdb",
            "a[href]",
            ".snippet-description, .description, .snippet-content",
        ),
    ]
    errors: list[str] = []
    for provider, url, item_selector, link_selector, snippet_selector in providers:
        try:
            response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            rows: list[dict[str, str]] = []
            for item in soup.select(item_selector):
                link = item.select_one(link_selector)
                if not link:
                    continue
                result_url = str(link.get("href") or "").strip()
                title = clean_text(link.get_text(" ", strip=True), 120)
                snippet_node = item.select_one(snippet_selector)
                snippet = clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "", 280)
                if not title or not result_url.startswith(("http://", "https://")):
                    continue
                rows.append({"title": title, "url": result_url, "snippet": snippet, "provider": provider})
                if len(rows) >= limit:
                    break
            if rows:
                return rows, provider
            errors.append(f"{provider}:empty")
        except Exception as exc:
            errors.append(f"{provider}:{clean_text(exc, 120)}")
    return [], "; ".join(errors) or "no_results"


def _votes_from_web_search(fact: CandidateFact, results: list[dict[str, str]]) -> list[dict[str, Any]]:
    # Search snippets are sufficient for a single, metric-bound numeric value.
    # Qualitative snippets are only discovery leads: differing prose is not a
    # numeric conflict, and the source itself must be opened before acceptance.
    if QUALITATIVE_METRIC_RE.search(fact.metric):
        return []
    votes: list[dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        text = f"{item.get('title', '')}。{item.get('snippet', '')}"
        if fact.company and fact.company.casefold() not in text.casefold():
            host = urlparse(item.get("url", "")).netloc.lower()
            if not any(term in host for term in OFFICIAL_HOST_TERMS):
                continue
        recovered = _direct_value(fact.metric, _metric_focused_window(fact.metric, text))
        if not recovered or not _passes_metric_gate(fact.metric, recovered):
            continue
        if not _evidence_window_mentions_metric(
            fact.metric,
            text,
            recovered,
        ):
            continue
        vote = _verification_vote(
            value=recovered,
            source=f"联网搜索摘要 {index}",
            kind="web_search",
            url=item.get("url", ""),
            metric=fact.metric,
        )
        if vote:
            votes.append(vote)
    return votes


def _votes_from_source_pages(
    fact: CandidateFact,
    *,
    extra_urls: list[str] | None = None,
    timeout: float = 8.0,
    open_audit: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    urls: list[str] = []
    # Search-discovered pages are the freshness candidates, so inspect them
    # before already-known and potentially stale sources.
    for url in [*(extra_urls or []), *fact.sources]:
        if not str(url).startswith(("http://", "https://")):
            continue
        urls.append(str(url))
        if "stockanalysis.com/quote/" in str(url) and "/financials" in str(url):
            urls.append(str(url).split("/financials", 1)[0].rstrip("/") + "/statistics/")
    votes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in urls[:8]:
        if url in seen:
            continue
        seen.add(url)
        page = _read_source_page(url, timeout)
        if open_audit is not None:
            open_audit.append({key: value for key, value in page.items() if key != "text"})
        if not page["opened"]:
            continue
        text = str(page["text"])
        if _candidate_supported_by_raw_text(fact, text):
            vote = _verification_vote(
                value=fact.value,
                source="公开来源页读取",
                kind="source_page",
                url=url,
                metric=fact.metric,
            )
            if vote:
                votes.append(vote)
            continue
        if QUALITATIVE_METRIC_RE.search(fact.metric):
            recovered = _qualitative_source_evidence(fact, text, url)
            if recovered:
                vote = _verification_vote(
                    value=recovered,
                    source="公开来源页读取",
                    kind="source_page",
                    url=url,
                    metric=fact.metric,
                )
                if vote:
                    votes.append(vote)
            continue
        recovered = _direct_value(fact.metric, _metric_focused_window(fact.metric, text))
        if (
            "stockanalysis.com/quote/" in url
            and re.search(r"收入|收益|EBITDA|利润|净利润|溢利", fact.metric, re.IGNORECASE)
            and recovered
            and not re.search(
                r"港元|港仙|人民币|亿元|亿|万元|百万|million|billion|bn|\bB\b|\d\s*M\b|HKD|CNY|HK\$|US\$|RMB",
                recovered,
                re.IGNORECASE,
            )
        ):
            recovered = re.sub(r"([-+]?\d[\d,]*(?:\.\d+)?)", r"\1M", recovered)
        if not recovered or not _passes_metric_gate(fact.metric, recovered):
            continue
        if not _evidence_window_mentions_metric(fact.metric, text, recovered):
            continue
        vote = _verification_vote(
            value=recovered,
            source="公开来源页读取",
            kind="source_page",
            url=url,
            metric=fact.metric,
        )
        if vote:
            votes.append(vote)
    return votes


def _search_verify_one(
    fact: CandidateFact,
    *,
    tasks_by_id: dict[str, dict[str, Any]],
    existing_items: dict[str, dict[str, Any]],
    peer_facts: list[CandidateFact],
    online_search: bool = False,
) -> CandidateFact:
    votes: list[dict[str, Any]] = []
    suspicious_profit_segment = _is_suspicious_profit_segment_fact(fact)
    original_vote = (
        _verification_vote(
            value=fact.value,
            source="当前候选事实",
            kind="candidate",
            url=str(fact.sources[0]) if fact.sources else "",
            metric=fact.metric,
        )
        if fact.status == "ok" and _passes_metric_gate(fact.metric, fact.value) and not suspicious_profit_segment
        else None
    )
    if original_vote:
        votes.append(original_vote)
    task = tasks_by_id.get(fact.id, {})
    basis_votes = _votes_from_candidate_basis(fact)
    votes.extend(basis_votes)
    has_official_basis_source = fact.source_tier == "official" or any(
        _official_domain_owners(str(url)) or "financialreports.eu" in str(url)
        for url in fact.sources
    )
    if (
        original_vote
        and has_official_basis_source
        and str(fact.basis or "").strip()
        and not re.search(r"候选(?:值|结果|事实)\s*(?:为|是|[:：])", str(fact.basis or ""))
    ):
        basis_canonical = _canonical_fact_value(fact.metric, fact.basis)
        if basis_canonical and _canonical_values_compatible(fact.metric, original_vote["canonical"], basis_canonical):
            official_vote = dict(original_vote)
            official_vote["source"] = "官方证据依据"
            official_vote["kind"] = "basis_in_official_evidence"
            official_vote["url"] = str(fact.sources[0]) if fact.sources else ""
            votes.append(official_vote)
    if fact.status != "ok" and basis_votes and (fact.source_score >= 0.8 or has_official_basis_source):
        for basis_vote in basis_votes[:1]:
            evidence_vote = dict(basis_vote)
            evidence_vote["source"] = "官方证据依据"
            evidence_vote["kind"] = "basis_in_official_evidence"
            evidence_vote["url"] = str(fact.sources[0]) if fact.sources else ""
            votes.append(evidence_vote)
    votes.extend(_votes_from_task_evidence(fact, task))
    votes.extend(_votes_from_monitoring_closure(fact))
    votes.extend(_votes_from_cache(fact, existing_items))
    online_summary: dict[str, Any] = {"enabled": online_search}
    if online_search:
        query = _fact_search_query(fact)
        started = time.monotonic()
        results, provider = _public_web_search(query)
        online_summary = {
            "enabled": True,
            "query": query,
            "provider": provider,
            "result_count": len(results),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "results": results[:4],
        }
        votes.extend(
            _votes_from_source_pages(
                fact,
                extra_urls=[str(item.get("url") or "") for item in results],
            )
        )
        votes.extend(_votes_from_web_search(fact, results))
    for peer in peer_facts:
        if suspicious_profit_segment:
            break
        if peer.id == fact.id or peer.decision != "accepted":
            continue
        if (peer.company, peer.metric, peer.row_ref) != (fact.company, fact.metric, fact.row_ref):
            continue
        vote = _verification_vote(
            value=peer.value,
            source=f"同组候选 {peer.id}",
            kind="peer_candidate",
            url=str(peer.sources[0]) if peer.sources else "",
            metric=fact.metric,
        )
        if vote:
            votes.append(vote)

    if _is_monitoring_closure_fact(fact) and original_vote:
        closure_canonical = original_vote["canonical"]
        closure_votes = [vote for vote in votes if vote.get("canonical") == closure_canonical]
        closure_kinds = {vote.get("kind") for vote in closure_votes}
        if {"candidate", "monitoring_closure"} <= closure_kinds:
            votes = closure_votes

    buckets: dict[str, list[dict[str, Any]]] = {}
    for vote in votes:
        buckets.setdefault(str(vote["canonical"]), []).append(vote)
    ranked = sorted(buckets.values(), key=lambda items: (len(items), len({v["kind"] for v in items})), reverse=True)
    majority = ranked[0] if ranked else []
    original_canonical = original_vote["canonical"] if original_vote else ""
    majority_canonical = majority[0]["canonical"] if majority else ""
    conflict_count = sum(1 for key in buckets if key != majority_canonical)
    distinct_kinds = len({vote["kind"] for vote in majority})
    largest_minor_count = max((len(items) for key, items in buckets.items() if key != majority_canonical), default=0)
    has_majority = len(majority) >= 2 and len(majority) > largest_minor_count
    independent_rescue_kinds = {
        "web_search",
        "source_page",
        "previous_verified",
        "monitoring_closure",
        "peer_candidate",
    }
    can_rescue_unavailable = bool(original_vote) or any(
        vote.get("kind") in independent_rescue_kinds for vote in majority
    )
    decision = "unchanged"

    if (
        has_majority
        and majority_canonical
        and majority_canonical != original_canonical
        and can_rescue_unavailable
    ):
        fact.value = _normalize_hk_financial_unit(
            fact.metric,
            clean_text(majority[0].get("normalized_value") or majority[0]["value"], 220),
            fact.sources,
            f"{fact.basis}；{fact.note}",
        )
        correction_note = f"搜索验证多数口径修正为：{fact.value}"
        if correction_note not in fact.basis:
            fact.basis = clean_text(f"{fact.basis}；{correction_note}", 600)
        if "搜索验证多数口径覆盖当前候选值" not in fact.note:
            fact.note = clean_text(f"{fact.note}；搜索验证多数口径覆盖当前候选值", 160).strip("；")
        fact.status = "ok"
        fact.decision = "accepted"
        fact.value_supported = True
        fact.entity_supported = True
        fact.metric_supported = True
        fact.reasons = []
        fact.confidence = max(fact.confidence, 0.9)
        discovered_sources = [
            str(vote.get("url") or "")
            for vote in majority
            if str(vote.get("url") or "").startswith(("http://", "https://"))
        ]
        fact.sources = list(dict.fromkeys([*discovered_sources, *fact.sources]))
        decision = "majority_corrected"
    elif has_majority and majority_canonical and majority_canonical != original_canonical:
        # Candidate-basis and official-basis votes may be two renderings of the
        # same sentence.  They are not independent evidence and must not turn
        # an unavailable/rejected fact into a published number by themselves.
        decision = "insufficient_independent_evidence"
    elif conflict_count and not has_majority:
        fact.decision = "review"
        fact.reasons.append("搜索验证未形成多数口径")
        decision = "needs_review"
    elif has_majority:
        decision = "majority_confirmed"

    fact.search_verification = {
        "status": "checked" if votes else "no_votes",
        "decision": decision,
        "votes": votes[:12],
        "vote_count": len(votes),
        "majority_value": majority[0]["value"] if majority else "",
        "majority_normalized_value": majority[0].get("normalized_value", "") if majority else "",
        "majority_count": len(majority),
        "majority_source_types": distinct_kinds,
        "conflict_count": conflict_count,
        "online_search": online_summary,
    }
    return fact


def search_verify_facts(state: CurationState) -> dict[str, Any]:
    candidates = [CandidateFact.model_validate(item) for item in state.get("candidates", [])]
    accepted = [item for item in candidates if item.decision == "accepted"]
    tasks_by_id = {str(item.get("id")): item for item in state.get("tasks", []) if isinstance(item, dict)}
    existing_items = state.get("existing_items", {})
    workers = max(1, int(state.get("search_verify_workers") or os.environ.get("CMHK_SEARCH_VERIFY_WORKERS") or 4))
    online_enabled = bool(state.get("search_verify_online")) or os.environ.get("CMHK_SEARCH_VERIFY_ONLINE", "").lower() in {"1", "true", "yes"}
    online_limit_raw = state.get("search_verify_online_limit")
    if online_limit_raw is None:
        online_limit_raw = os.environ.get("CMHK_SEARCH_VERIFY_ONLINE_LIMIT")
    online_limit = max(0, int(online_limit_raw if online_limit_raw not in {None, ""} else 0))
    rejected_recheck = [
        item
        for item in candidates
        if online_enabled
        and item.decision in {"rejected", "review"}
        and item.status != "ok"
        and re.search(r"未提取到有效数据|未发现|未披露|无法确认", f"{item.value} {item.basis} {item.note}")
    ]
    suspicious_recheck = [
        item
        for item in accepted
        if online_enabled and _is_suspicious_profit_segment_fact(item)
    ]
    # A merger that searches only accepted or conveniently recoverable facts
    # can still report a false green. Online mode therefore covers every
    # company-metric candidate.
    verify_targets_by_id = {
        item.id: item
        for item in (candidates if online_enabled else [*accepted, *rejected_recheck])
    }
    verify_targets = list(verify_targets_by_id.values())
    online_order_by_id = {
        item.id: item
        for item in [*rejected_recheck, *suspicious_recheck, *candidates]
    }
    online_order = list(online_order_by_id.values())
    if online_enabled:
        online_slice = online_order if online_limit == 0 else online_order[:online_limit]
        online_ids = {item.id for item in online_slice}
    else:
        online_ids = set()
    trace_events: list[dict[str, Any]] = [
        _trace(
            state,
            "搜索验证",
            "tool_call",
            "并行调用搜索验证 Agent，对已通过事实做多来源多数核验。",
            event_type="tool_call",
            tool="parallel_search_verifier",
            input={
                "accepted": len(accepted),
                "rejected_recheck": len(rejected_recheck),
                "suspicious_recheck": len(suspicious_recheck),
                "workers": min(workers, max(1, len(verify_targets))),
                "online_search": online_enabled,
                "online_limit": "all" if online_enabled and online_limit == 0 else online_limit,
            },
        )
    ]
    if not verify_targets:
        return {
            "candidates": [item.model_dump() for item in candidates],
            "search_verification": {"checked": 0, "corrected": 0, "review": 0, "conflicts": 0},
            "node_events": [_event("搜索验证", "没有已通过事实需要二次核验。")],
            "agent_trace": [
                *trace_events,
                _trace(
                    state,
                    "搜索验证",
                    "tool_result",
                    "没有已通过事实需要二次核验。",
                    event_type="tool_result",
                    tool="parallel_search_verifier",
                    result={"checked": 0},
                ),
            ],
        }

    by_id = {item.id: item for item in candidates}
    effective_workers = min(workers, len(verify_targets))
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        future_map = {
            executor.submit(
                _search_verify_one,
                fact,
                tasks_by_id=tasks_by_id,
                existing_items=existing_items,
                peer_facts=accepted,
                online_search=fact.id in online_ids,
            ): fact.id
            for fact in verify_targets
        }
        for future in as_completed(future_map):
            verified = future.result()
            by_id[verified.id] = verified

    verified_candidates = [by_id[item.id] for item in candidates]
    checked = sum(bool(item.search_verification) for item in verified_candidates)
    corrected = sum(item.search_verification.get("decision") == "majority_corrected" for item in verified_candidates)
    review = sum(item.search_verification.get("decision") == "needs_review" for item in verified_candidates)
    conflicts = sum(int(item.search_verification.get("conflict_count") or 0) > 0 for item in verified_candidates)
    online_checked = sum(bool(item.search_verification.get("online_search", {}).get("enabled")) for item in verified_candidates)
    online_votes = sum(
        1
        for item in verified_candidates
        for vote in item.search_verification.get("votes", [])
        if vote.get("kind") in {"web_search", "source_page"}
    )
    online_required = len(candidates) if online_enabled else 0
    online_coverage_complete = bool(
        not online_enabled or online_checked == online_required
    )
    summary = {
        "checked": checked,
        "corrected": corrected,
        "review": review,
        "conflicts": conflicts,
        "workers": effective_workers,
        "online_search": online_enabled,
        "online_checked": online_checked,
        "online_votes": online_votes,
        "online_required": online_required,
        "online_limit": "all" if online_enabled and online_limit == 0 else online_limit,
        "online_coverage_complete": online_coverage_complete,
        "online_unsearched": max(0, online_required - online_checked),
    }
    return {
        "candidates": [item.model_dump() for item in verified_candidates],
        "search_verification": summary,
        "node_events": [
            _event(
                "搜索验证",
                f"并行核验 {checked} 条事实，修正 {corrected} 条，转人工复核 {review} 条，发现冲突 {conflicts} 条。",
            )
        ],
        "agent_trace": [
            *trace_events,
            _trace(
                state,
                "搜索验证",
                "tool_result",
                "搜索验证 Agent 返回多数口径核验结果。",
                event_type="tool_result",
                tool="parallel_search_verifier",
                result=summary,
                status="success",
            ),
        ],
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
            {
                "gaps": 0,
                "crawl_status": _result_status(row_ref),
                "reasons": [],
                "companies": [],
                "metrics": [],
            },
        )
        stats["gaps"] += 1
        if reason not in stats["reasons"]:
            stats["reasons"].append(reason)
        if company not in stats["companies"]:
            stats["companies"].append(company)
        if metric not in stats["metrics"]:
            stats["metrics"].append(metric)

    recrawl_tasks: list[RecrawlTask] = []
    if (
        state.get("allow_recrawl")
        and int(state.get("recrawl_round") or 0) < int(state.get("max_recrawl_rounds") or 1)
    ):
        ranked_rows = sorted(
            row_stats.items(),
            key=lambda item: (
                int(item[0].removeprefix("row_") or 0) in CURRENT_VALUE_DATABASE_ROWS,
                int(item[0].removeprefix("row_") or 0) in PRIMARY_PERFORMANCE_ROWS,
                item[1]["crawl_status"] in {"failed", "error"},
                int(item[0].removeprefix("row_") or 0) in CORE_COMPANY_ROWS,
                item[1]["gaps"],
            ),
            reverse=True,
        )
        for row_ref, stats in ranked_rows:
            match = re.fullmatch(r"row_(\d+)", row_ref or "")
            # Failed/error rows are retryable. Partial rows and current-value
            # database rows are retryable only when an official-source refresh
            # can plausibly repair the gap. Pure entity/metric/confidence
            # failures still require extraction or quality handling instead.
            crawl_status = str(stats.get("crawl_status") or "")
            row_number = int(match.group(1)) if match else 0
            has_recrawlable_evidence_gap = any(
                reason in RECRAWLABLE_EVIDENCE_REASONS for reason in stats.get("reasons", [])
            )
            partial_evidence_gap = crawl_status == "partial" and has_recrawlable_evidence_gap
            current_value_quality_gap = (
                row_number in CURRENT_VALUE_DATABASE_ROWS
                and crawl_status in {"quality_rejected", "no_extraction"}
                and has_recrawlable_evidence_gap
            )
            if not match or not (
                crawl_status in {"failed", "error"}
                or partial_evidence_gap
                or current_value_quality_gap
            ):
                continue
            recrawl_tasks.append(
                RecrawlTask(
                    row_ref=row_ref,
                    row_number=int(match.group(1)),
                    reason=(
                        f"{stats['gaps']} 个指标缺口，"
                        f"原爬取状态为 {crawl_status} 且存在可补爬的公开证据缺口"
                    ),
                    priority=100,
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
        model=str(config.get("model") or "deepseek-v4"),
        api_key=api_key,
        base_url=str(config.get("base_url") or INTERNAL_AI_BASE_URL).rstrip("/"),
        extra_body=deepseek_nonthinking_parameters(config.get("extra_parameters") or {}),
        temperature=0,
        timeout=120,
        max_retries=1,
    )


def _company_agent_group(company: str) -> str:
    if company in {"CMHK", "HKT", "SmarTone", "3HK", "HKBN", "HGC", "i-CABLE"}:
        return "local"
    if company in {"中国移动", "中国电信", "中国联通", "中国铁塔", "中国广电"}:
        return "mainland"
    if company in CLOUD_METRIC_COMPANIES or company == "China Mobile Cloud":
        return "cloud"
    return "international"


COMPANY_FACT_ENTITY_ALIASES: dict[str, set[str]] = {
    "CMHK": {"CMHK", "China Mobile Hong Kong", "China Mobile Hong Kong Company Limited"},
    "HKT": {"HKT", "csl", "1O1O"},
    "3HK": {"3HK", "3HK / Hutchison", "Hutchison"},
    "HGC": {"HGC"},
    "i-CABLE": {"i-CABLE", "iCable"},
    "Bharti Airtel": {"Bharti Airtel", "Airtel"},
    "Reliance Jio": {"Reliance Jio", "Jio"},
    "BT": {"BT", "BT/EE"},
    "中国铁塔": {"中国铁塔", "China Tower", "China Tower Corporation Limited"},
    "中国广电": {"中国广电", "China Broadnet", "China Broadcasting Network Group Corporation Ltd. / China Broadnet"},
    "China Mobile Cloud": {"China Mobile Cloud", "Mobile Cloud", "移动云"},
}

COMPANY_REQUIRED_METRICS: dict[str, list[str]] = {
    "CMHK": ["收入", "服务收入", "移动及5G用户", "ARPU", "网络覆盖", "资本开支"],
    "中国铁塔": ["收入", "EBITDA", "净利润", "站址数", "塔类租户数", "塔均租户数", "资本开支", "派息"],
    "中国广电": ["收入", "移动及5G用户", "有线电视用户", "家庭宽带用户", "ARPU", "资本开支"],
    "China Mobile Cloud": ["云收入", "同比增速", "经营利润或利润率", "积压订单或RPO", "资本开支"],
}


def _company_fact_entities(company: str) -> set[str]:
    return COMPANY_FACT_ENTITY_ALIASES.get(company, {company})


def _company_configured_metrics(company: str) -> list[str]:
    """Return every selected source-registry field for one canonical company."""
    if company in COMPANY_REQUIRED_METRICS:
        return list(COMPANY_REQUIRED_METRICS[company])
    aliases = {item.casefold() for item in _company_fact_entities(company)}
    try:
        rows = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    metrics: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        row_entities = {
            clean_text(value, 120).casefold()
            for value in [row.get("object"), row.get("object_cell"), *(row.get("entities") or [])]
            if clean_text(value, 120)
        }
        if not aliases.intersection(row_entities):
            continue
        ignored = {clean_text(value, 120) for value in row.get("ignored_selected_fields") or []}
        metrics.extend(
            clean_text(value, 120)
            for value in row.get("selected_fields") or []
            if clean_text(value, 120) and clean_text(value, 120) not in ignored
        )
    return list(dict.fromkeys(metrics))


def _company_metric_is_not_applicable(company: str, metric: str) -> bool:
    return company == "HGC" and metric in {"派息", "券商观点", "市场反应"}


def _company_expected_metrics(company: str, facts: list[CandidateFact]) -> list[str]:
    metrics = [
        *_company_configured_metrics(company),
        *(clean_text(item.metric, 120) for item in facts if clean_text(item.metric, 120)),
    ]
    if metrics:
        return list(dict.fromkeys(metrics))
    group = _company_agent_group(company)
    defaults = {
        "local": ["收入", "EBITDA", "净利润", "用户数", "ARPU", "资本开支"],
        "international": ["收入", "EBITDA", "净利润", "用户数", "资本开支"],
        "mainland": ["收入", "EBITDA", "净利润", "用户数", "资本开支"],
        "cloud": ["云收入", "同比增速", "经营利润或利润率"],
    }
    return defaults[group]


def _company_agent_metric_requires_direct_value(metric: str) -> bool:
    """Separate numeric disclosures from official qualitative evidence."""
    if QUALITATIVE_METRIC_RE.search(metric):
        return False
    return bool(re.search(
        r"收入|收益|EBITDA|利润|净利润|溢利|用户|客户|ARPU|资本开支|Capex|"
        r"派息|股息|增速|增长|利润率|占比|渗透率|覆盖率|市场份额|RPO|订单|线数|数量",
        metric,
        re.IGNORECASE,
    ))


def _company_research_profile(company: str) -> dict[str, Any]:
    """Return the governed aliases and official hosts for one research agent."""
    from executive_intelligence_pipeline import NEWS_ENTITY_SOURCES

    for _group, entity, aliases, source_urls in NEWS_ENTITY_SOURCES:
        if entity != company:
            continue
        hosts = list(
            dict.fromkeys(
                urlparse(str(url)).netloc.lower().removeprefix("www.")
                for url in source_urls
                if str(url).startswith(("http://", "https://"))
            )
        )
        return {
            "aliases": list(dict.fromkeys([company, *aliases])),
            "official_hosts": hosts,
            "seed_urls": list(source_urls),
        }
    return {"aliases": [company], "official_hosts": [], "seed_urls": []}


def _host_matches_governed_official(url: str, official_hosts: list[str]) -> bool:
    host = urlparse(str(url)).netloc.lower().removeprefix("www.")
    return any(host == expected or host.endswith(f".{expected}") for expected in official_hosts)


def _search_result_is_current(result: dict[str, Any], *, current_year: int) -> bool:
    text = clean_text(
        f"{result.get('title', '')} {result.get('snippet', '')} {result.get('url', '')}",
        1000,
    )
    if str(current_year) in text:
        return True
    short_year = str(current_year)[-2:]
    if re.search(
        rf"\b(?:FY|CY|Q[1-4]|[12]H|H[12])\s*{re.escape(short_year)}\b",
        text,
        re.IGNORECASE,
    ):
        return True
    years = {int(value) for value in re.findall(r"\b20\d{2}\b", text)}
    if years:
        return max(years) >= current_year
    return bool(
        re.search(
            r"latest|quarterly.results|financial.results|earnings|interim|"
            r"ir.library|investor.relations|reports.presentations",
            text,
            re.IGNORECASE,
        )
    )


def _company_agent_url_key(url: str) -> str:
    """Canonicalize a discovered URL without weakening the official-host gate."""
    try:
        parsed = urlparse(unquote(clean_text(url, 4000)))
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}{query}"


def _run_company_research_agent(
    state: CurationState,
    company: str,
    row_number: int,
    row_entity: str,
    facts: list[CandidateFact],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run one isolated tool-calling research agent for exactly one company."""
    agent_id = f"company-{uuid.uuid5(uuid.NAMESPACE_URL, state.get('run_id', '') + ':' + company).hex[:12]}"
    parent_agent_id = f"lead-{state.get('run_id', '')}"
    traces = [
        _trace(
            state,
            "公司研究 Agent",
            "start",
            f"{company} Company Research Agent 开始独立研究。",
            input={"row": row_number, "row_entity": row_entity, "fact_count": len(facts)},
            status="running",
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            company=company,
            role="company_research",
        )
    ]
    searches: list[dict[str, Any]] = []
    opened: list[dict[str, Any]] = []
    final: dict[str, Any] = {}
    completion_called = False
    completion_accepted = False
    completion_forced = False
    completion_rejection = ""
    research_profile = _company_research_profile(company)
    current_year = datetime.now().year
    expected_metrics = _company_expected_metrics(company, facts)

    @tool
    def inspect_company_evidence() -> dict[str, Any]:
        """读取该公司已有事实、期间、决策和证据地址。"""
        return {
            "company": company,
            "facts": [
                {
                    "metric": item.metric,
                    "value": item.value,
                    "decision": item.decision,
                    "period": getattr(item, "period", ""),
                    "sources": item.sources[:4],
                    "reasons": item.reasons[:4],
                }
                for item in facts[:30]
            ],
        }

    @tool
    def search_latest_official(metric: str) -> dict[str, Any]:
        """查找该公司最新业绩指标；官方、交易所和第三方新闻均可作证据。"""
        previous = next((item for item in searches if item.get("metric") == metric), None)
        if previous is not None:
            return {**previous, "reused": True}
        selected = next((item for item in facts if item.metric == metric), None)
        query_fact = selected or CandidateFact(
            id=f"{agent_id}-{metric or 'latest'}",
            company=company,
            metric=metric or "最新业绩和核心经营指标",
            row_ref=f"row_{row_number}",
            decision="review",
        )
        query = _fact_search_query(query_fact)
        results, provider = _public_web_search(query, limit=8, timeout=12.0)
        official_results = [
            item
            for item in results
            if _host_matches_governed_official(item.get("url", ""), research_profile["official_hosts"])
            and _search_result_is_current(item, current_year=current_year)
        ]
        if not official_results and research_profile["official_hosts"]:
            host = research_profile["official_hosts"][0]
            aliases = " OR ".join(f'"{item}"' for item in research_profile["aliases"][:3])
            targeted_query = clean_text(
                f"site:{host} ({aliases}) {metric or 'financial results'} {current_year} latest results",
                260,
            )
            targeted_results, targeted_provider = _public_web_search(
                targeted_query,
                limit=8,
                timeout=12.0,
            )
            provider = f"{provider}+{targeted_provider}"
            results.extend(item for item in targeted_results if item.get("url") not in {r.get("url") for r in results})
            official_results = [
                item
                for item in results
                if _host_matches_governed_official(item.get("url", ""), research_profile["official_hosts"])
                and _search_result_is_current(item, current_year=current_year)
            ]
        # Governed URLs are fallback seeds, never the only path. Search runs
        # first; seeds are then exposed to the Agent so dynamic/JS indexes,
        # regulator mirrors and search-engine omissions do not become false
        # "not found" outcomes.
        for seed_url in research_profile["seed_urls"]:
            seed = {
                "title": f"{company} governed official seed",
                "url": seed_url,
                "snippet": "governed official source entry; freshness unverified",
                "provider": "governed_seed",
            }
            if seed_url not in {item.get("url") for item in results}:
                results.append(seed)
        current_results = [
            item
            for item in results
            if item.get("provider") != "governed_seed"
            and _search_result_is_current(item, current_year=current_year)
        ]
        search_evidence = _votes_from_web_search(query_fact, current_results)
        search_values = {
            str(vote.get("canonical") or "") for vote in search_evidence if vote.get("canonical")
        }
        record = {
            "metric": metric,
            "query": query,
            "provider": provider,
            "results": results,
            "current_results": current_results,
            "current_official_results": official_results,
            "official_hosts": research_profile["official_hosts"],
            "search_evidence": search_evidence,
            "search_evidence_count": len(search_evidence),
            "search_value_conflict": (
                not QUALITATIVE_METRIC_RE.search(metric) and len(search_values) > 1
            ),
        }
        searches.append(record)
        return record

    @tool
    def open_official_pages(metric: str, urls: list[str]) -> dict[str, Any]:
        """打开搜索命中的官方或第三方网页、新闻、PDF 并提取可核验票据。"""
        current_discovered_by_key = {
            _company_agent_url_key(str(item.get("url") or "")): str(item.get("url") or "")
            for search in searches
            for item in search.get("current_results", [])
            if _company_agent_url_key(str(item.get("url") or ""))
        }
        official_discovered_by_key = {
            _company_agent_url_key(str(item.get("url") or "")): str(item.get("url") or "")
            for search in searches
            for item in search.get("results", [])
            if _company_agent_url_key(str(item.get("url") or ""))
            and _host_matches_governed_official(
                str(item.get("url") or ""), research_profile["official_hosts"]
            )
        }
        public_discovered_by_key = {
            _company_agent_url_key(str(item.get("url") or "")): str(item.get("url") or "")
            for search in searches
            for item in search.get("current_results", [])
            if _company_agent_url_key(str(item.get("url") or ""))
        }
        # A previously accepted official source is also a governed lead.  It is
        # deliberately limited to exact URLs already attached to this company's
        # facts; arbitrary model-supplied URLs still cannot bypass the allowlist.
        known_fact_urls = {
            str(url)
            for item in facts
            if item.decision in {"accepted", "review"}
            for url in item.sources
            if str(url).startswith(("http://", "https://"))
            and (
                item.source_tier == "official"
                or _host_matches_governed_official(str(url), research_profile["official_hosts"])
            )
        }
        known_fact_urls_by_key = {
            _company_agent_url_key(url): url for url in known_fact_urls if _company_agent_url_key(url)
        }
        discovered_by_key = {
            **known_fact_urls_by_key,
            **public_discovered_by_key,
            **official_discovered_by_key,
            **current_discovered_by_key,
        }
        selected_urls = []
        for requested_url in dict.fromkeys(urls):
            selected_url = discovered_by_key.get(_company_agent_url_key(requested_url))
            if selected_url and selected_url not in selected_urls:
                selected_urls.append(selected_url)
            if len(selected_urls) >= 8:
                break
        previous = next(
            (
                item
                for item in opened
                if item.get("metric") == metric
                and item.get("requested_urls") == selected_urls
            ),
            None,
        )
        if previous is not None:
            return {**previous, "reused": True}
        selected = next((item for item in facts if item.metric == metric), None)
        query_fact = selected or CandidateFact(
            id=f"{agent_id}-open-{metric or 'latest'}",
            company=company,
            metric=metric or "最新业绩和核心经营指标",
            row_ref=f"row_{row_number}",
            decision="review",
        )
        open_attempts: list[dict[str, Any]] = []
        votes = _votes_from_source_pages(
            query_fact.model_copy(update={"sources": []}),
            extra_urls=selected_urls,
            timeout=15.0,
            open_audit=open_attempts,
        )
        current_discovered_keys = set(current_discovered_by_key)
        current_source_votes = [
            vote
            for vote in votes
            if _company_agent_url_key(str(vote.get("url") or "")) in current_discovered_keys
        ]
        current_open_attempts = [
            attempt
            for attempt in open_attempts
            if _company_agent_url_key(str(attempt.get("url") or "")) in current_discovered_keys
        ]
        result = {
            "metric": metric,
            "requested_urls": selected_urls,
            "opened_evidence": votes,
            "opened_evidence_count": len(votes),
            "opened_current_evidence": current_source_votes,
            "opened_official_evidence_count": len(current_source_votes),
            "opened_lead_count": len(votes),
            "open_attempts": open_attempts,
            "live_official_open_count": sum(bool(item.get("opened")) for item in open_attempts),
            "fresh_official_open_count": sum(bool(item.get("opened")) for item in current_open_attempts),
            "note": "HTTP 403/466 等只属于该原文入口打开失败，不代表搜索失败。",
        }
        opened.append(result)
        return result

    @tool
    def research_all_metrics() -> dict[str, Any]:
        """批量检索全部预期指标，并仅对冲突或摘要无直接值的来源做原文核实。"""
        for metric in expected_metrics:
            if _company_metric_is_not_applicable(company, metric):
                continue
            search_latest_official.invoke({"metric": metric})

        for metric in expected_metrics:
            if _company_metric_is_not_applicable(company, metric):
                continue
            search = next((item for item in searches if item.get("metric") == metric), {})
            search_evidence = search.get("search_evidence") or []
            search_values = {
                str(vote.get("canonical") or "")
                for vote in search_evidence
                if vote.get("canonical")
            }
            if len(search_values) == 1:
                continue
            candidate_urls = [
                str(vote.get("url") or "")
                for vote in search_evidence
                if str(vote.get("url") or "")
            ]
            candidate_urls.extend(
                str(item.get("url") or "")
                for item in [
                    *(search.get("current_official_results") or []),
                    *(search.get("current_results") or []),
                    *(
                        item
                        for item in search.get("results") or []
                        if item.get("provider") == "governed_seed"
                    ),
                ]
                if str(item.get("url") or "")
            )
            candidate_urls = list(dict.fromkeys(candidate_urls))[:3]
            if candidate_urls:
                open_official_pages.invoke({"metric": metric, "urls": candidate_urls})

        recommendations: list[dict[str, Any]] = []
        for metric in expected_metrics:
            if _company_metric_is_not_applicable(company, metric):
                recommendations.append({
                    "metric": metric,
                    "recommended_status": "not_applicable",
                    "rationale": "该指标对该主体不适用。",
                    "value": "",
                    "evidence_urls": [],
                })
                continue
            metric_searches = [item for item in searches if item.get("metric") == metric]
            metric_opened = [item for item in opened if item.get("metric") == metric]
            search_evidence = [
                vote
                for item in metric_searches
                for vote in item.get("search_evidence", [])
            ]
            open_evidence = [
                vote
                for item in metric_opened
                for vote in item.get("opened_current_evidence", [])
            ]
            search_values = {
                str(vote.get("canonical") or "")
                for vote in search_evidence
                if vote.get("canonical")
            }
            open_values = {
                str(vote.get("canonical") or "")
                for vote in open_evidence
                if vote.get("canonical")
            }
            fresh_official_opens = sum(
                int(item.get("fresh_official_open_count") or 0) for item in metric_opened
            )
            selected_votes = open_evidence or search_evidence
            selected_vote = selected_votes[0] if selected_votes else {}
            unresolved_conflict = not QUALITATIVE_METRIC_RE.search(metric) and (
                len(open_values) > 1 or (not open_values and len(search_values) > 1)
            )
            if unresolved_conflict:
                recommended_status = "conflict"
                rationale = "当期来源数值不一致，打开原文后仍无法消除冲突。"
                selected_vote = {}
            elif open_values or len(search_values) == 1:
                recommended_status = "verified_latest"
                rationale = "已从当期搜索结果或打开的来源核实直接指标值。"
            elif fresh_official_opens > 0:
                recommended_status = "not_disclosed"
                rationale = "已回读当期官方页面，未取得该指标的单独披露值。"
            else:
                recommended_status = "search_exhausted"
                rationale = "已执行当期网络检索并尝试回读相关来源，未取得可核验直接值。"
            recommendations.append({
                "metric": metric,
                "recommended_status": recommended_status,
                "rationale": rationale,
                "value": selected_vote.get("normalized_value") or selected_vote.get("value") or "",
                "search_value_conflict": (
                    not QUALITATIVE_METRIC_RE.search(metric) and len(search_values) > 1
                ),
                "evidence_urls": list(dict.fromkeys(
                    str(vote.get("url") or "")
                    for vote in [*open_evidence, *search_evidence]
                    if str(vote.get("url") or "")
                ))[:4],
            })
        return {
            "company": company,
            "expected_metric_count": len(expected_metrics),
            "searched_metric_count": len(searches),
            "opened_metric_count": len({item.get("metric") for item in opened}),
            "recommendations": recommendations,
        }

    @tool
    def complete_company_research(
        status: str,
        rationale: str,
        metric_statuses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """逐指标完成研究；状态可为已核验、未披露、不适用、搜索穷尽或冲突。"""
        nonlocal completion_called, completion_accepted, completion_rejection
        completion_called = True
        allowed_statuses = {"verified_latest", "not_disclosed", "not_applicable", "search_exhausted", "conflict"}
        status_aliases = {
            "verified_latest": "verified_latest",
            "verified": "verified_latest",
            "已核验": "verified_latest",
            "已验证": "verified_latest",
            "not_disclosed": "not_disclosed",
            "未披露": "not_disclosed",
            "not_applicable": "not_applicable",
            "不适用": "not_applicable",
            "search_exhausted": "search_exhausted",
            "搜索穷尽": "search_exhausted",
            "搜索无直接值": "search_exhausted",
            "未找到直接值": "search_exhausted",
            "conflict": "conflict",
            "冲突": "conflict",
        }
        requested_status = clean_text(status, 80).casefold()
        normalized = status_aliases.get(requested_status, "")
        normalized_metrics: list[dict[str, str]] = []
        for item in metric_statuses or []:
            metric = clean_text(item.get("metric"), 120)
            metric_status = status_aliases.get(clean_text(item.get("status"), 80).casefold(), "")
            if metric not in expected_metrics or metric_status not in allowed_statuses:
                continue
            normalized_metrics.append({
                "metric": metric,
                "status": metric_status,
                "rationale": clean_text(item.get("rationale") or item.get("value"), 400),
            })
        supplied_names = [item["metric"] for item in normalized_metrics]
        missing = [metric for metric in expected_metrics if metric not in supplied_names]
        duplicates = sorted({metric for metric in supplied_names if supplied_names.count(metric) > 1})
        research_incomplete: list[str] = []
        for item in normalized_metrics:
            metric = item["metric"]
            metric_status = item["status"]
            metric_searches = [record for record in searches if record.get("metric") == metric]
            metric_opened = [record for record in opened if record.get("metric") == metric]
            metric_open_evidence = [
                vote
                for record in metric_opened
                for vote in record.get("opened_current_evidence", [])
            ]
            metric_evidence = len(metric_open_evidence)
            metric_search_evidence = [
                vote
                for record in metric_searches
                for vote in record.get("search_evidence", [])
            ]
            metric_search_values = {
                str(vote.get("canonical") or "")
                for vote in metric_search_evidence
                if vote.get("canonical")
            }
            metric_search_conflict = (
                not QUALITATIVE_METRIC_RE.search(metric) and len(metric_search_values) > 1
            )
            metric_open_values = {
                str(vote.get("canonical") or "")
                for vote in metric_open_evidence
                if vote.get("canonical")
            }
            # Search snippets are sufficient when they agree.  If they differ,
            # opening a source may resolve the discrepancy; conflicting values
            # in the opened source bodies remain an unresolved conflict.
            metric_value_conflict = not QUALITATIVE_METRIC_RE.search(metric) and (
                len(metric_open_values) > 1 or (not metric_open_values and metric_search_conflict)
            )
            metric_fresh_opens = sum(int(record.get("fresh_official_open_count") or 0) for record in metric_opened)
            metric_open_attempts = [
                attempt
                for record in metric_opened
                for attempt in record.get("open_attempts", [])
            ]
            metric_has_organic_current_result = any(
                result.get("provider") != "governed_seed"
                for record in metric_searches
                for result in record.get("current_results", [])
            )
            # A targeted search against a private/non-reporting company may
            # find no current disclosure at all.  In that case "not disclosed"
            # would overstate the evidence, so the validator conservatively
            # downgrades the Agent's claim to audited search exhaustion.
            if (
                metric_status in {"verified_latest", "not_disclosed", "conflict"}
                and metric_fresh_opens <= 0
                and not metric_search_evidence
                and not metric_evidence
                and not metric_has_organic_current_result
            ):
                item["status"] = "search_exhausted"
                metric_status = "search_exhausted"
            if not item["rationale"]:
                item["rationale"] = {
                    "verified_latest": "已通过当期搜索或打开来源取得该指标直接证据。",
                    "not_disclosed": "已回读当期来源，未取得该指标的单独披露值。",
                    "search_exhausted": "已执行当期检索并尝试回读来源，未取得可核验直接值。",
                    "not_applicable": "该指标依据主体口径确认为不适用。",
                    "conflict": "当期来源存在未消除的口径或数值冲突。",
                }.get(metric_status, "")
            if metric_status == "not_applicable" and _company_metric_is_not_applicable(company, metric):
                continue
            if not metric_searches:
                research_incomplete.append(f"{metric}:search_not_run")
                continue
            if metric_status == "verified_latest" and not (
                metric_evidence > 0
                or (metric_search_evidence and not metric_value_conflict)
            ):
                research_incomplete.append(
                    f"{metric}:resolve_conflicting_search_values"
                    if metric_value_conflict
                    else f"{metric}:search_or_open_evidence_required"
                )
            elif metric_status == "not_disclosed" and metric_fresh_opens <= 0:
                research_incomplete.append(f"{metric}:fresh_official_open_required")
            elif metric_status == "search_exhausted":
                if metric_search_evidence:
                    research_incomplete.append(f"{metric}:search_value_available")
                    continue
                exhausted = (
                    metric_fresh_opens > 0
                    or not metric_has_organic_current_result
                    or (metric_open_attempts and not any(attempt.get("opened") for attempt in metric_open_attempts))
                )
                if not exhausted:
                    research_incomplete.append(f"{metric}:open_current_official_results")
            elif metric_status == "conflict" and not (
                metric_value_conflict or metric_open_attempts or metric_evidence
            ):
                research_incomplete.append(f"{metric}:open_sources_before_conflict")
        incomplete_reasons = [item["metric"] for item in normalized_metrics if not item["rationale"]]
        metric_status_set = {item["status"] for item in normalized_metrics}
        derived_status = (
            "conflict" if "conflict" in metric_status_set
            else "search_exhausted" if "search_exhausted" in metric_status_set
            else "verified_latest" if "verified_latest" in metric_status_set
            else "not_disclosed" if "not_disclosed" in metric_status_set
            else "not_applicable" if metric_status_set == {"not_applicable"}
            else ""
        )
        # Per-metric statuses are the governed source of truth.  The validator
        # may deterministically downgrade an unsupported model claim (for
        # example, a stale governed seed presented as ``verified_latest``), so
        # keep the aggregate status aligned with that validated outcome rather
        # than rejecting an otherwise complete audit as an Agent error.
        if derived_status:
            normalized = derived_status
        completion_accepted = bool(
            normalized
            and not missing
            and not duplicates
            and not incomplete_reasons
            and not research_incomplete
            and len(normalized_metrics) == len(expected_metrics)
            and normalized == derived_status
        )
        completion_rejection = clean_text(
            f"missing={missing}; duplicates={duplicates}; empty_rationale={incomplete_reasons}; "
            f"research_incomplete={research_incomplete}; expected_status={derived_status or 'none'}",
            1200,
        )
        proposed = {
            "status": normalized,
            "rationale": clean_text(rationale, 600),
            "metric_statuses": normalized_metrics,
        }
        if completion_accepted:
            final.update(proposed)
        return {
            "accepted": completion_accepted,
            **proposed,
            "missing_metrics": missing,
            "duplicate_metrics": duplicates,
            "empty_rationale_metrics": incomplete_reasons,
            "research_incomplete_metrics": research_incomplete,
            "expected_status": derived_status,
        }

    tools = [
        inspect_company_evidence,
        research_all_metrics,
        search_latest_official,
        open_official_pages,
        complete_company_research,
    ]
    tool_map = {item.name: item for item in tools}

    def invoke_company_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Normalize common model JSON encodings before strict tool validation."""
        normalized = dict(args or {})
        if name == "complete_company_research":
            metric_statuses = normalized.get("metric_statuses")
            if isinstance(metric_statuses, str):
                try:
                    metric_statuses = json.loads(metric_statuses)
                except json.JSONDecodeError:
                    metric_statuses = []
            if isinstance(metric_statuses, dict):
                metric_statuses = [metric_statuses]
            normalized["metric_statuses"] = metric_statuses
        elif name == "open_official_pages" and isinstance(normalized.get("urls"), str):
            encoded_urls = normalized["urls"]
            try:
                decoded_urls = json.loads(encoded_urls)
            except json.JSONDecodeError:
                decoded_urls = [encoded_urls]
            normalized["urls"] = decoded_urls if isinstance(decoded_urls, list) else [encoded_urls]
        selected_tool = tool_map.get(name)
        return selected_tool.invoke(normalized) if selected_tool else {"ok": False, "error": "unknown tool"}

    error = ""
    try:
        bulk_bootstrap: dict[str, Any] = {}
        if len(expected_metrics) > 6:
            traces.append(
                _trace(
                    state,
                    "公司研究 Agent",
                    "tool_call",
                    f"{company} Agent 预先批量检索全部 {len(expected_metrics)} 个指标。",
                    event_type="tool_call",
                    tool="research_all_metrics",
                    input={},
                    agent_id=agent_id,
                    parent_agent_id=parent_agent_id,
                    company=company,
                    role="company_research",
                )
            )
            bulk_bootstrap = invoke_company_tool("research_all_metrics", {})
            traces.append(
                _trace(
                    state,
                    "公司研究 Agent",
                    "tool_result",
                    f"{company} Agent 已完成全指标批量检索。",
                    event_type="tool_result",
                    tool="research_all_metrics",
                    result=bulk_bootstrap,
                    status="success" if not bulk_bootstrap.get("error") else "error",
                    agent_id=agent_id,
                    parent_agent_id=parent_agent_id,
                    company=company,
                    role="company_research",
                )
            )
        model = _build_supervisor_model().bind_tools(tools)
        messages: list[Any] = [
            SystemMessage(
                content=(
                    f"你是只负责 {company} 的 Company Research Agent，不得研究或引用其他公司的数值。"
                    "优先调用 research_all_metrics，一次完成全部预期指标的搜索和必要原文核实；"
                    "不要逐指标重复调用 search_latest_official。证据可来自官网、交易所、监管披露或第三方新闻，"
                    "固定 URL 只是线索，不是限定入口。"
                    "某个网页打开返回 403 时应继续搜索其他官方入口，不得把 403 说成搜索引擎失败。"
                    f"必须逐一完成这些指标：{expected_metrics}。最后调用 complete_company_research 时，"
                    "metric_statuses 必须逐项覆盖全部预期指标；不得用 0、行业估算或旧值填补未披露项。"
                    "搜索摘要或第三方新闻如果含有当期直接指标值，可以作为 verified_latest 证据，"
                    "不要为了找 PDF 而否定已检索到的值；如果同一指标出现不同值，必须继续打开来源核实，"
                    "无法消除冲突时只能标记 conflict，不得写入数值。"
                    "status 只能使用 verified_latest、not_disclosed、not_applicable、search_exhausted、conflict；"
                    "仅当指标在该公司业务/披露制度上确实不适用时才可用 not_applicable。"
                )
            ),
            HumanMessage(
                content=(
                    f"调度行 {row_number}，库内主体 {row_entity}，"
                    f"预期指标 {expected_metrics}。"
                    + (
                        "批量检索已执行，请优先根据以下建议终态调用 "
                        "complete_company_research："
                        + json.dumps(
                            bulk_bootstrap.get("recommendations") or [],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        if bulk_bootstrap
                        else ""
                    )
                )
            ),
        ]
        for turn_index in range(8):
            if turn_index == 7 and searches and not final:
                messages.append(HumanMessage(content=(
                    "这是最后一轮。不要再解释研究过程；必须现在调用 complete_company_research，"
                    "并用 metric_statuses 逐项覆盖全部预期指标。"
                )))
            started = time.monotonic()
            response = model.invoke(messages)
            messages.append(response)
            traces.append(
                _trace(
                    state,
                    "公司研究 Agent",
                    "thinking",
                    clean_text(response.content or f"{company} Agent 选择研究工具。", 500),
                    output={"tool_calls": response.tool_calls},
                    duration_ms=round((time.monotonic() - started) * 1000),
                    agent_id=agent_id,
                    parent_agent_id=parent_agent_id,
                    company=company,
                    role="company_research",
                )
            )
            if not response.tool_calls:
                break
            for call in response.tool_calls:
                name = str(call.get("name") or "")
                args = call.get("args") or {}
                traces.append(
                    _trace(
                        state,
                        "公司研究 Agent",
                        "tool_call",
                        f"{company} Agent 调用 {name}。",
                        event_type="tool_call",
                        tool=name,
                        input=args,
                        agent_id=agent_id,
                        parent_agent_id=parent_agent_id,
                        company=company,
                        role="company_research",
                    )
                )
                result = invoke_company_tool(name, args)
                traces.append(
                    _trace(
                        state,
                        "公司研究 Agent",
                        "tool_result",
                        f"{company} Agent 完成 {name}。",
                        event_type="tool_result",
                        tool=name,
                        result=result,
                        status="success" if not result.get("error") else "error",
                        agent_id=agent_id,
                        parent_agent_id=parent_agent_id,
                        company=company,
                        role="company_research",
                    )
                )
                messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"]))
            if completion_accepted:
                break
        if searches and not completion_accepted:
            completion_forced = True
            repair_rounds = max(
                1,
                min(4, int(os.environ.get("CMHK_COMPANY_AGENT_REPAIR_ROUNDS") or 2)),
            )
            for repair_index in range(repair_rounds):
                required_open_metrics = re.findall(
                    r"([^\[\],;']+):open_current_official_results",
                    completion_rejection,
                )
                required_open_metrics = [clean_text(metric, 120) for metric in required_open_metrics]
                open_candidate_map = {
                    metric: list(dict.fromkeys(
                        str(result.get("url") or "")
                        for record in searches
                        if record.get("metric") == metric
                        for result in record.get("current_official_results", [])
                        if str(result.get("url") or "")
                    ))[:8]
                    for metric in required_open_metrics
                }
                only_open_required = bool(required_open_metrics) and not any(
                    marker in completion_rejection
                    for marker in (
                        ":search_not_run",
                        ":fresh_official_evidence_required",
                        ":fresh_official_open_required",
                        ":open_sources_before_conflict",
                    )
                )
                messages.append(HumanMessage(content=(
                    "你是该公司的 Final Decision Agent。上次提交未通过公司和指标证据门禁："
                    f"{completion_rejection}。必须根据门禁反馈继续调用 search_latest_official、"
                    "open_official_pages 补齐真实研究，再调用 complete_company_research 重新提交。"
                    "不得由工作流补写业务结论；所有 status 只能使用 verified_latest、not_disclosed、"
                    "not_applicable、search_exhausted、conflict。"
                    + (
                        "当前只剩原文打开缺口，不得重复搜索；必须按以下指标和已发现候选调用 "
                        f"open_official_pages：{json.dumps(open_candidate_map, ensure_ascii=False)}。"
                        if only_open_required else ""
                    )
                )))
                started = time.monotonic()
                repair_model = _build_supervisor_model()
                if only_open_required:
                    repair_model = repair_model.bind_tools(
                        [open_official_pages],
                        tool_choice="open_official_pages",
                    )
                else:
                    repair_model = repair_model.bind_tools(tools)
                response = repair_model.invoke(messages)
                messages.append(response)
                traces.append(
                    _trace(
                        state,
                        "公司研究 Agent",
                        "finalize",
                        f"{company} 最终决策 Agent 执行第 {repair_index + 1} 次门禁修正。",
                        output={"tool_calls": response.tool_calls},
                        duration_ms=round((time.monotonic() - started) * 1000),
                        agent_id=agent_id,
                        parent_agent_id=parent_agent_id,
                        company=company,
                        role="company_research",
                    )
                )
                if not response.tool_calls:
                    continue
                completion_called_this_repair = False
                for call in response.tool_calls:
                    name = str(call.get("name") or "")
                    completion_called_this_repair = completion_called_this_repair or name == "complete_company_research"
                    args = call.get("args") or {}
                    traces.append(
                        _trace(
                            state,
                            "公司研究 Agent",
                            "tool_call",
                            f"{company} 最终决策 Agent 调用 {name}。",
                            event_type="tool_call",
                            tool=name,
                            input=args,
                            agent_id=agent_id,
                            parent_agent_id=parent_agent_id,
                            company=company,
                            role="company_research",
                        )
                    )
                    result = invoke_company_tool(name, args)
                    traces.append(
                        _trace(
                            state,
                            "公司研究 Agent",
                            "tool_result",
                            f"{company} 最终决策 Agent 完成 {name}。",
                            event_type="tool_result",
                            tool=name,
                            result=result,
                            status="success" if not result.get("error") and result.get("accepted", True) else "error",
                            agent_id=agent_id,
                            parent_agent_id=parent_agent_id,
                            company=company,
                            role="company_research",
                        )
                    )
                    messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"]))
                if not completion_accepted and not completion_called_this_repair:
                    messages.append(HumanMessage(content=(
                        "本轮门禁补搜和原文打开工具已经执行完成。现在不要重复研究工具；"
                        "必须只调用 complete_company_research，基于最新工具结果逐项重新提交全部预期指标。"
                    )))
                    started = time.monotonic()
                    completion_response = _build_supervisor_model().bind_tools(
                        [complete_company_research],
                        tool_choice="complete_company_research",
                    ).invoke(messages)
                    messages.append(completion_response)
                    traces.append(
                        _trace(
                            state,
                            "公司研究 Agent",
                            "finalize",
                            f"{company} 最终决策 Agent 执行第 {repair_index + 1} 次强制重提。",
                            output={"tool_calls": completion_response.tool_calls},
                            duration_ms=round((time.monotonic() - started) * 1000),
                            agent_id=agent_id,
                            parent_agent_id=parent_agent_id,
                            company=company,
                            role="company_research",
                        )
                    )
                    for call in completion_response.tool_calls or []:
                        if str(call.get("name") or "") != "complete_company_research":
                            continue
                        args = call.get("args") or {}
                        traces.append(
                            _trace(
                                state,
                                "公司研究 Agent",
                                "tool_call",
                                f"{company} 最终决策 Agent 强制重提 complete_company_research。",
                                event_type="tool_call",
                                tool="complete_company_research",
                                input=args,
                                agent_id=agent_id,
                                parent_agent_id=parent_agent_id,
                                company=company,
                                role="company_research",
                            )
                        )
                        result = invoke_company_tool("complete_company_research", args)
                        traces.append(
                            _trace(
                                state,
                                "公司研究 Agent",
                                "tool_result",
                                f"{company} 最终决策 Agent 完成强制重提。",
                                event_type="tool_result",
                                tool="complete_company_research",
                                result=result,
                                status="success" if result.get("accepted") else "error",
                                agent_id=agent_id,
                                parent_agent_id=parent_agent_id,
                                company=company,
                                role="company_research",
                            )
                        )
                        messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"]))
                if completion_accepted:
                    break
    except Exception as exc:
        error = clean_text(exc, 300)

    if not searches:
        final = {
            "status": "agent_error",
            "rationale": error or "Agent 未执行必需的联网搜索。",
            "reason_code": "required_search_not_run",
        }
    elif not completion_accepted:
        final = {
            "status": "agent_error",
            "rationale": error or completion_rejection or "最终决策 Agent 未提交完整逐指标终态。",
            "reason_code": "invalid_terminal_payload" if completion_called else "missing_terminal_call",
        }
    evidence_urls = list(
        dict.fromkeys(
            str(vote.get("url") or "")
            for vote in [
                *(vote for item in opened for vote in item.get("opened_evidence", [])),
                *(vote for item in searches for vote in item.get("search_evidence", [])),
            ]
            if str(vote.get("url") or "")
        )
    )
    evidence_count = sum(len(item.get("opened_evidence", [])) for item in opened) + sum(
        len(item.get("search_evidence", [])) for item in searches
    )
    fresh_official_open_count = sum(int(item.get("fresh_official_open_count") or 0) for item in opened)
    supplied_metric_statuses = {
        item["metric"]: item
        for item in final.get("metric_statuses", [])
        if item.get("metric") in expected_metrics
    }
    metric_results: list[dict[str, Any]] = []
    for metric in expected_metrics:
        metric_searches = [item for item in searches if item.get("metric") == metric]
        metric_opened = [item for item in opened if item.get("metric") == metric]
        metric_open_evidence = [
            vote
            for item in metric_opened
            for vote in item.get("opened_current_evidence", [])
        ]
        metric_evidence = len(metric_open_evidence)
        metric_search_evidence = [
            vote
            for item in metric_searches
            for vote in item.get("search_evidence", [])
        ]
        metric_search_values = {
            str(vote.get("canonical") or "")
            for vote in metric_search_evidence
            if vote.get("canonical")
        }
        metric_search_conflict = (
            not QUALITATIVE_METRIC_RE.search(metric) and len(metric_search_values) > 1
        )
        metric_open_values = {
            str(vote.get("canonical") or "")
            for vote in metric_open_evidence
            if vote.get("canonical")
        }
        metric_value_conflict = not QUALITATIVE_METRIC_RE.search(metric) and (
            len(metric_open_values) > 1 or (not metric_open_values and metric_search_conflict)
        )
        metric_fresh_opens = sum(int(item.get("fresh_official_open_count") or 0) for item in metric_opened)
        metric_live_official_opens = sum(
            int(item.get("live_official_open_count") or 0) for item in metric_opened
        )
        metric_open_attempts = [
            attempt
            for item in metric_opened
            for attempt in item.get("open_attempts", [])
        ]
        metric_has_organic_current_result = any(
            result.get("provider") != "governed_seed"
            for item in metric_searches
            for result in item.get("current_results", [])
        )
        metric_search_exhausted = bool(metric_searches) and (
            metric_fresh_opens > 0
            or not metric_has_organic_current_result
            or (metric_open_attempts and not any(item.get("opened") for item in metric_open_attempts))
        )
        supplied = supplied_metric_statuses.get(metric) or {}
        claimed_status = supplied.get("status")
        if final.get("status") == "agent_error":
            status = "agent_error"
            reason = final.get("rationale", "Agent 未形成逐指标终态。")
        elif (
            not metric_value_conflict
            and (
                metric_evidence > 0
                or (len(metric_search_values) == 1 and bool(metric_search_evidence))
            )
        ):
            status = "verified_latest"
            reason = supplied.get("rationale") or "已通过当期搜索摘要或打开来源核实唯一直接指标证据。"
        elif claimed_status == "verified_latest" and (
            metric_evidence > 0
            or (metric_search_evidence and not metric_value_conflict)
        ):
            status = "verified_latest"
            reason = supplied.get("rationale") or "已回读当期官方原文并提取直接指标证据。"
        elif claimed_status == "not_disclosed" and metric_fresh_opens > 0 and not metric_evidence:
            status = "not_disclosed"
            reason = supplied.get("rationale") or "已回读当期官方原文，发行人未单独披露该指标。"
        elif claimed_status == "not_applicable" and _company_metric_is_not_applicable(company, metric):
            status = "not_applicable"
            reason = supplied.get("rationale") or "该指标对该公司主体不适用。"
        elif (
            claimed_status == "search_exhausted"
            and metric_search_exhausted
            and not metric_search_evidence
        ):
            status = "search_exhausted"
            reason = supplied.get("rationale") or "已搜索但未取得可核验当期官方原文。"
        elif (
            claimed_status in {"verified_latest", "not_disclosed", "conflict"}
            and metric_search_exhausted
            and not metric_evidence
            and not metric_search_evidence
        ):
            status = "search_exhausted"
            reason = "已搜索并尝试回读当期来源，但页面不含该公司指标的直接语义证据。"
        elif claimed_status == "conflict" and metric_value_conflict:
            status = "conflict"
            reason = supplied.get("rationale") or "当期官方证据存在口径或数值冲突。"
        else:
            status = "conflict" if metric_searches or metric_opened else "unsearched"
            reason = (
                "Agent 声称完成，但该指标没有当期官方原文和直接证据。"
                if metric_searches or metric_opened
                else "Agent 未搜索该预期指标，也未提交逐指标终态。"
            )
        evidence_votes = [*metric_open_evidence, *metric_search_evidence]
        resolved_votes = metric_open_evidence or metric_search_evidence
        selected_vote = resolved_votes[0] if resolved_votes and not metric_value_conflict else {}
        metric_results.append({
            "metric": metric,
            "status": status,
            "rationale": clean_text(reason, 400),
            "value": selected_vote.get("normalized_value") or selected_vote.get("value") or "",
            "search_count": len(metric_searches),
            "search_evidence_count": len(metric_search_evidence),
            "search_value_conflict": metric_search_conflict,
            "evidence_value_conflict": metric_value_conflict,
            "fresh_official_open_count": metric_fresh_opens,
            "live_official_open_count": metric_live_official_opens,
            "evidence_count": len(evidence_votes),
            "evidence_urls": list(dict.fromkeys(
                str(vote.get("url") or "")
                for vote in evidence_votes
                if str(vote.get("url") or "")
            ))[:8],
        })
    unresolved_metrics = [
        item["metric"]
        for item in metric_results
        if item["status"] not in {"verified_latest", "not_disclosed", "not_applicable", "search_exhausted"}
    ]
    if final.get("status") != "agent_error":
        if unresolved_metrics:
            final["status"] = (
                "search_exhausted"
                if all(item["status"] == "search_exhausted" for item in metric_results if item["metric"] in unresolved_metrics)
                else "conflict"
            )
            final["rationale"] = f"仍有 {len(unresolved_metrics)} 个预期指标没有合规终态：{', '.join(unresolved_metrics[:8])}。"
        else:
            metric_statuses = {item["status"] for item in metric_results}
            final["status"] = (
                "search_exhausted" if "search_exhausted" in metric_statuses
                else "verified_latest" if "verified_latest" in metric_statuses
                else "not_disclosed" if "not_disclosed" in metric_statuses
                else "not_applicable"
            )
            final["rationale"] = f"全部 {len(metric_results)} 个预期指标均有当期官方终态。"
    result = {
        "agent_id": agent_id,
        "parent_agent_id": parent_agent_id,
        "company": company,
        "group": _company_agent_group(company),
        "row_number": row_number,
        "row_entity": row_entity,
        "status": final["status"],
        "rationale": final.get("rationale", ""),
        "reason_code": final.get("reason_code", ""),
        "completion_forced": completion_forced,
        "search_count": len(searches),
        "opened_page_count": sum(len(item.get("requested_urls", [])) for item in opened),
        "open_success_count": sum(
            sum(bool(attempt.get("opened")) for attempt in item.get("open_attempts", []))
            for item in opened
        ),
        "open_blocked_count": sum(
            sum(not bool(attempt.get("opened")) for attempt in item.get("open_attempts", []))
            for item in opened
        ),
        "open_attempts": [
            attempt
            for item in opened
            for attempt in item.get("open_attempts", [])
        ][:20],
        "evidence_count": evidence_count,
        "fresh_official_open_count": fresh_official_open_count,
        "metric_results": metric_results,
        "metric_coverage_complete": not unresolved_metrics,
        "unresolved_metrics": unresolved_metrics,
        "official_hosts": research_profile["official_hosts"],
        "evidence_urls": evidence_urls[:12],
        "queries": [item.get("query", "") for item in searches[:8]],
        "metrics": expected_metrics,
    }
    traces.append(
        _trace(
            state,
            "公司研究 Agent",
            "complete",
            f"{company} Company Research Agent 完成：{result['status']}。",
            output=result,
            status="success" if result["status"] != "agent_error" else "error",
            decision=result["status"],
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            company=company,
            role="company_research",
        )
    )
    return result, traces


def run_company_research_agents(state: CurationState) -> dict[str, Any]:
    """Lead Agent deterministically fans out one autonomous worker per company."""
    from crawl import ALL_COMPANY_CURRENT_RESULT_TARGETS

    required = bool(state.get("online_ai", True) and state.get("search_verify_online"))
    if not required:
        expected_companies = len(ALL_COMPANY_CURRENT_RESULT_TARGETS)
        summary = {"required": False, "expected": expected_companies, "completed": 0, "coverage_complete": False}
        return {
            "company_agent_results": [],
            "company_agent_summary": summary,
            "node_events": [_event("公司研究 Agent", f"本轮未启用联网多 Agent 研究，不声称已完成 {expected_companies} 家。")],
            "agent_trace": [
                _trace(state, "公司研究 Agent", "skip", "本轮未启用联网多 Agent 研究。", output=summary)
            ],
        }
    candidates = [CandidateFact.model_validate(item) for item in state.get("candidates", [])]
    workers = max(1, min(8, int(os.environ.get("CMHK_COMPANY_AGENT_WORKERS") or 4)))
    trace_events = [
        _trace(
            state,
            "公司研究 Agent",
            "fan_out",
            f"Lead Research Agent 确定性派发 {len(ALL_COMPANY_CURRENT_RESULT_TARGETS)} 个公司 Agent。",
            input={"expected_companies": list(ALL_COMPANY_CURRENT_RESULT_TARGETS), "workers": workers},
            agent_id=f"lead-{state.get('run_id', '')}",
            role="lead_research",
        )
    ]
    results: list[dict[str, Any]] = []
    expected_metric_plan: dict[str, list[str]] = {}
    run_id = str(state.get("run_id") or "")
    progress_path = RUNS_DIR / f"{run_id}_company_agent_progress.json"
    progress_enabled = run_id.startswith("scheduled_")
    progress_results: dict[str, dict[str, Any]] = {}
    if progress_enabled and progress_path.exists():
        try:
            progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
            if progress_payload.get("version") == COMPANY_AGENT_PROGRESS_VERSION:
                progress_results = {
                    str(company): item
                    for company, item in (progress_payload.get("companies") or {}).items()
                    if isinstance(item, dict)
                }
        except Exception:
            progress_results = {}

    def persist_progress() -> None:
        if progress_enabled:
            atomic_write_json(
                progress_path,
                {
                    "version": COMPANY_AGENT_PROGRESS_VERSION,
                    "run_id": run_id,
                    "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "companies": progress_results,
                },
            )

    def reusable_progress(item: dict[str, Any], expected_metrics: list[str]) -> bool:
        metric_results = item.get("metric_results") or []
        terminal = {"verified_latest", "not_disclosed", "not_applicable", "search_exhausted"}
        return bool(
            item.get("metric_coverage_complete")
            and item.get("status") in terminal
            and [metric.get("metric") for metric in metric_results] == expected_metrics
            and all(metric.get("status") in terminal for metric in metric_results)
        )

    company_tasks: list[tuple[str, int, str, list[CandidateFact]]] = []
    for company, (row_number, row_entity) in ALL_COMPANY_CURRENT_RESULT_TARGETS.items():
        fact_entities = _company_fact_entities(company) | {row_entity}
        company_facts = [item for item in candidates if item.company in fact_entities]
        expected_metric_plan[company] = _company_expected_metrics(company, company_facts)
        company_tasks.append((company, row_number, row_entity, company_facts))
    # Finish the smallest complete company audits first.  Every completion is
    # persisted, so a later outer timeout retains the largest possible number
    # of reusable company x metric terminal states.
    company_tasks.sort(key=lambda item: len(expected_metric_plan[item[0]]))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for company, row_number, row_entity, company_facts in company_tasks:
            cached_result = progress_results.get(company)
            if cached_result and reusable_progress(cached_result, expected_metric_plan[company]):
                results.append(cached_result)
                trace_events.append(
                    _trace(
                        state,
                        "公司研究 Agent",
                        "resume",
                        f"{company} 已有完整逐指标终态，本次恢复不重跑。",
                        output={"company": company, "metrics": expected_metric_plan[company]},
                        agent_id=f"lead-{run_id}",
                        role="lead_research",
                    )
                )
                continue
            future = executor.submit(
                _run_company_research_agent,
                state,
                company,
                row_number,
                row_entity,
                company_facts,
            )
            futures[future] = company
        for future in as_completed(futures):
            company = futures[future]
            try:
                result, child_traces = future.result()
            except Exception as exc:
                result = {
                    "company": company,
                    "group": _company_agent_group(company),
                    "status": "agent_error",
                    "rationale": clean_text(exc, 300),
                    "search_count": 0,
                    "opened_page_count": 0,
                    "evidence_count": 0,
                }
                child_traces = []
            if not result.get("metric_results"):
                fallback_status = "agent_error" if result.get("status") == "agent_error" else "conflict"
                result["metric_results"] = [
                    {
                        "metric": metric,
                        "status": fallback_status,
                        "rationale": result.get("rationale") or "公司 Agent 未返回逐指标终态。",
                        "search_count": 0,
                        "fresh_official_open_count": 0,
                        "evidence_count": 0,
                        "evidence_urls": [],
                    }
                    for metric in expected_metric_plan.get(company, [])
                ]
                result["metric_coverage_complete"] = False
                result["unresolved_metrics"] = list(expected_metric_plan.get(company, []))
            results.append(result)
            trace_events.extend(child_traces)
            if progress_enabled:
                progress_results[company] = result
                persist_progress()
    order = {company: index for index, company in enumerate(ALL_COMPANY_CURRENT_RESULT_TARGETS)}
    results.sort(key=lambda item: order.get(str(item.get("company") or ""), 999))
    completed = sum(item.get("status") in {"verified_latest", "not_disclosed", "not_applicable", "search_exhausted", "conflict"} for item in results)
    errors = [item["company"] for item in results if item.get("status") == "agent_error"]
    unresolved = [
        item["company"]
        for item in results
        if item.get("status") in {"conflict", "agent_error"}
    ]
    expected_metric_count = sum(len(item.get("metric_results") or []) for item in results)
    completed_metric_count = sum(
        metric.get("status") in {"verified_latest", "not_disclosed", "not_applicable", "search_exhausted"}
        for item in results
        for metric in item.get("metric_results") or []
    )
    unresolved_metric_results = [
        {"company": item.get("company"), "metric": metric.get("metric"), "status": metric.get("status")}
        for item in results
        for metric in item.get("metric_results") or []
        if metric.get("status") not in {"verified_latest", "not_disclosed", "not_applicable", "search_exhausted"}
    ]
    metric_status_counts = {
        status: sum(
            metric.get("status") == status
            for item in results
            for metric in item.get("metric_results") or []
        )
        for status in ("verified_latest", "not_disclosed", "not_applicable", "search_exhausted", "conflict", "unsearched", "agent_error")
    }
    summary = {
        "required": True,
        "expected": len(ALL_COMPANY_CURRENT_RESULT_TARGETS),
        "completed": completed,
        "coverage_complete": completed == len(ALL_COMPANY_CURRENT_RESULT_TARGETS),
        "publish_ready": completed == len(ALL_COMPANY_CURRENT_RESULT_TARGETS) and not unresolved,
        "agent_errors": errors,
        "unresolved_companies": unresolved,
        "expected_metrics": expected_metric_count,
        "completed_metrics": completed_metric_count,
        "metric_status_counts": metric_status_counts,
        "latest_value_coverage_complete": bool(
            expected_metric_count > 0
            and metric_status_counts["verified_latest"] + metric_status_counts["not_applicable"] == expected_metric_count
        ),
        "metric_coverage_complete": (
            expected_metric_count > 0
            and completed_metric_count == expected_metric_count
            and not unresolved_metric_results
        ),
        "unresolved_metric_count": len(unresolved_metric_results),
        "unresolved_metrics": unresolved_metric_results[:200],
        "workers": workers,
        "searches": sum(int(item.get("search_count") or 0) for item in results),
        "opened_pages": sum(int(item.get("opened_page_count") or 0) for item in results),
        "evidence": sum(int(item.get("evidence_count") or 0) for item in results),
    }
    summary["publish_ready"] = bool(
        summary["publish_ready"] and summary["metric_coverage_complete"]
    )
    trace_events.append(
        _trace(
            state,
            "公司研究 Agent",
            "join",
            f"Lead Research Agent 收齐 {completed}/{len(ALL_COMPANY_CURRENT_RESULT_TARGETS)} 个公司 Agent 终态。",
            output=summary,
            status="success" if summary["coverage_complete"] else "error",
            agent_id=f"lead-{state.get('run_id', '')}",
            role="lead_research",
        )
    )
    return {
        "company_agent_results": results,
        "company_agent_summary": summary,
        "node_events": [_event("公司研究 Agent", f"收齐 {completed}/{len(ALL_COMPANY_CURRENT_RESULT_TARGETS)} 家公司 Agent 终态。")],
        "agent_trace": trace_events,
    }


def supervise_gap_actions(state: CurationState) -> dict[str, Any]:
    planned = [RecrawlTask.model_validate(item) for item in state.get("recrawl_tasks", [])]
    gaps = [GapRecord.model_validate(item) for item in state.get("gaps", [])]
    candidates = [CandidateFact.model_validate(item) for item in state.get("candidates", [])]
    company_agent_summary = state.get("company_agent_summary", {})
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
                "company_agent_summary": company_agent_summary,
            },
        )
    ]
    if not gaps:
        reason = "没有事实缺口，进入发布。"
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
    facts_by_key = {
        (item.row_ref, item.company, item.metric): item for item in candidates
    }
    searched_rows: set[int] = set()
    decision: dict[str, Any] = {}

    @tool
    def inspect_evidence_gaps(row_numbers: list[int]) -> dict[str, Any]:
        """读取候选行的缺口、抓取状态和缺失指标，供 Supervisor 决策。"""
        rows = []
        requested = row_numbers or sorted(gap_by_row)
        for row_number in requested:
            if row_number not in gap_by_row:
                continue
            row_gaps = gap_by_row.get(row_number, [])
            verification = []
            for gap in row_gaps[:12]:
                fact = facts_by_key.get((gap.row_ref, gap.company, gap.metric))
                online = (fact.search_verification or {}).get("online_search", {}) if fact else {}
                verification.append(
                    {
                        "company": gap.company,
                        "metric": gap.metric,
                        "reason": gap.reason,
                        "search_provider": online.get("provider", ""),
                        "search_result_count": int(online.get("result_count") or 0),
                        "search_urls": [
                            item.get("url", "") for item in (online.get("results") or [])[:4]
                        ],
                    }
                )
            rows.append(
                {
                    "row": row_number,
                    "crawl_status": _result_status(f"row_{row_number}") or "unknown",
                    "gap_count": len(row_gaps),
                    "metrics": [gap.metric for gap in row_gaps[:12]],
                    "companies": list(dict.fromkeys(gap.company for gap in row_gaps))[:12],
                    "reasons": list(dict.fromkeys(gap.reason for gap in row_gaps))[:6],
                    "rule_candidate": row_number in allowed,
                    "deterministic_priority": allowed[row_number].priority if row_number in allowed else 0,
                    "search_verification": verification,
                }
            )
        return {"rows": rows, "max_rows": int(state.get("max_recrawl_rows") or 3)}

    @tool
    def search_and_open_official_evidence(
        row_number: int,
        company: str,
        metric: str,
    ) -> dict[str, Any]:
        """为一个缺口调用搜索引擎，并继续打开搜索命中的官方网页或 PDF。"""
        row_ref = f"row_{int(row_number)}"
        matching_gap = next(
            (
                item
                for item in gap_by_row.get(int(row_number), [])
                if item.company == company and item.metric == metric
            ),
            None,
        )
        if matching_gap is None:
            return {"ok": False, "error": "该主体×指标不在当前缺口中"}
        fact = facts_by_key.get((row_ref, company, metric)) or CandidateFact(
            id=f"supervisor-{row_number}-{company}-{metric}",
            company=company,
            metric=metric,
            row_ref=row_ref,
            decision="rejected",
            reasons=[matching_gap.reason],
        )
        query = _fact_search_query(fact)
        results, provider = _public_web_search(query, limit=6, timeout=10.0)
        result_urls = [str(item.get("url") or "") for item in results]
        page_votes = _votes_from_source_pages(fact, extra_urls=result_urls, timeout=12.0)
        official_results = [
            item
            for item in results
            if _official_domain_owners(str(item.get("url") or ""))
            or any(
                term in urlparse(str(item.get("url") or "")).netloc.lower()
                for term in OFFICIAL_HOST_TERMS
            )
            or urlparse(str(item.get("url") or "")).netloc.lower().endswith("sec.gov")
        ]
        if official_results:
            searched_rows.add(int(row_number))
            if int(row_number) not in allowed:
                row_gaps = gap_by_row[int(row_number)]
                allowed[int(row_number)] = RecrawlTask(
                    row_ref=row_ref,
                    row_number=int(row_number),
                    reason="Supervisor 搜索发现官方当期证据，需定向读取原文",
                    priority=100,
                    attempts=int(state.get("recrawl_round") or 0),
                    companies=list(dict.fromkeys(item.company for item in row_gaps)),
                    metrics=list(dict.fromkeys(item.metric for item in row_gaps)),
                )
        return {
            "ok": True,
            "query": query,
            "provider": provider,
            "results": results,
            "official_results": official_results,
            "opened_page_votes": page_votes,
            "row_promoted_for_recrawl": int(row_number) in searched_rows,
        }

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

    tools = [
        inspect_evidence_gaps,
        search_and_open_official_evidence,
        schedule_targeted_recrawl,
        publish_without_recrawl,
    ]
    tool_map = {item.name: item for item in tools}
    if state.get("online_ai", True):
        try:
            model = _build_supervisor_model().bind_tools(tools)
            messages: list[Any] = [
                SystemMessage(
                    content=(
                        "你是公开信息数据治理 Supervisor。你不能直接修改事实、质量分数或发布阈值。"
                        "必须先调用 inspect_evidence_gaps 查看候选行，再调用 schedule_targeted_recrawl "
                        "或 publish_without_recrawl 作出唯一决策。对质量拒绝、无抽取或搜索结果未打开的缺口，"
                        "必须先调用 search_and_open_official_evidence，由你自己查找并打开官方原文。"
                        "补爬只用于抓取失败、证据缺失或关键指标"
                        "缺口；格式问题、主体错误和低质量商业来源不应靠重复补爬解决。"
                        "发布前的联网搜索必须覆盖每一个主体×指标，并使用 latest official、quarterly results、"
                        "interim results、earnings release、annual report、财报、中期业绩、季度业绩、公告等"
                        "中英文关键词。不能把旧候选、HTTP 200、搜索摘要为空或首页没有新链接解释为‘没有新披露’。"
                        "搜索发现的新官方页面或 PDF 必须继续读取正文；发现更新但正文未成功读取时必须安排补爬，"
                        "不得调用 publish_without_recrawl 输出假绿结论。"
                        "自然语言说明使用简洁中文段落，不要输出 Markdown 标题或表格，控制在 200 字以内。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"当前有 {len(gaps)} 个证据缺口，涉及行 {sorted(gap_by_row)}；"
                        f"规则引擎仅提供参考候选 {sorted(allowed)}，最终由你调用工具决定。"
                        f"上游公司 Agent 覆盖状态为 {company_agent_summary}。"
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


def _persist_blocked_company_agent_audit(
    state: CurationState,
    company_agent_summary: dict[str, Any],
    reason: str,
) -> None:
    """Keep failed multi-agent evidence without mutating the published fact layer."""
    candidates = [CandidateFact.model_validate(item) for item in state.get("candidates", [])]
    completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    blocked_event = _event("发布阻断", reason)
    summary = RunSummary(
        run_id=state["run_id"],
        started_at=state["started_at"],
        completed_at=completed_at,
        tasks=len(state.get("tasks", [])),
        accepted=sum(item.decision == "accepted" for item in candidates),
        rejected=sum(item.decision == "rejected" for item in candidates),
        review=sum(item.decision == "review" for item in candidates),
        gaps=len(state.get("gaps", [])),
        recrawl_rows=state.get("executed_recrawl_rows", []),
        recrawl_performed=bool(state.get("recrawl_performed")),
        online_ai=bool((state.get("summary") or {}).get("onlineAiUsed")),
        node_events=[*state.get("node_events", []), blocked_event],
    )
    summary.extra["search_verification"] = state.get("search_verification", {})
    summary.extra["company_agent_summary"] = company_agent_summary
    summary.extra["overall_status"] = "partial"
    summary.extra["publication_blocked"] = True
    summary.extra["publication_blocked_reason"] = reason
    blocked_trace = [
        *state.get("agent_trace", []),
        _trace(
            state,
            "发布阻断",
            "decision",
            reason,
            status="error",
            decision="block_publish",
            output={"company_agent_summary": company_agent_summary},
        ),
    ]
    atomic_write_json(DATA_DIR / "company_agent_results.json", state.get("company_agent_results", []))
    atomic_write_json(
        RUNS_DIR / f"{state['run_id']}_company_agent_results.json",
        state.get("company_agent_results", []),
    )
    atomic_write_json(RUNS_DIR / f"{state['run_id']}.json", summary.model_dump())
    atomic_write_jsonl(RUNS_DIR / f"{state['run_id']}_agent_trace.jsonl", blocked_trace)


def publish_results(state: CurationState) -> dict[str, Any]:
    search_verification = state.get("search_verification", {})
    if (
        state.get("search_verify_online")
        and not search_verification.get("online_coverage_complete")
    ):
        raise RuntimeError(
            "最终合并 Agent 未完成全部主体×指标联网补充搜索，禁止发布假绿结果"
        )
    company_agent_summary = state.get("company_agent_summary", {})
    if company_agent_summary.get("required") and not company_agent_summary.get("coverage_complete"):
        raise RuntimeError(
            f"公司研究 Agent 仅完成 {company_agent_summary.get('completed', 0)}/"
            f"{company_agent_summary.get('expected', 41)}，禁止把不完整结果标成成功"
        )
    if company_agent_summary.get("required") and not company_agent_summary.get("publish_ready"):
        unresolved = company_agent_summary.get("unresolved_companies") or []
        reason = (
            "公司研究 Agent 尚有未解决主体，禁止写入发布层："
            + "、".join(str(company) for company in unresolved)
        )
        if not state.get("dry_run"):
            _persist_blocked_company_agent_audit(state, company_agent_summary, reason)
        raise RuntimeError(reason)
    candidates = [CandidateFact.model_validate(item) for item in state.get("candidates", [])]
    for item in candidates:
        if item.decision != "accepted":
            continue
        if re.search(r"无(?:明确)?资本开支(?:总额|金额)|无明确.{0,20}(?:金额|数字)", item.basis):
            item.decision = "rejected"
            item.reasons.append("发布前审计：依据明确否定该指标总额")
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
    summary.extra["search_verification"] = state.get("search_verification", {})
    summary.extra["company_agent_summary"] = company_agent_summary
    summary.extra["overall_status"] = (
        "complete"
        if not company_agent_summary.get("required") or company_agent_summary.get("publish_ready")
        else "partial"
    )
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
            f"curation_data/runs/{state['run_id']}_candidate_facts.jsonl",
            "curation_data/agent_trace.jsonl",
            f"curation_data/runs/{state['run_id']}_agent_trace.jsonl",
            "curation_data/company_agent_results.json",
            f"curation_data/runs/{state['run_id']}_company_agent_results.json",
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
        atomic_write_jsonl(
            RUNS_DIR / f"{state['run_id']}_candidate_facts.jsonl",
            [item.model_dump() for item in candidates],
        )
        atomic_write_jsonl(DATA_DIR / "verified_facts.jsonl", [item.model_dump() for item in accepted])
        atomic_write_json(DATA_DIR / "recrawl_tasks.json", state.get("recrawl_tasks", []))
        atomic_write_json(DATA_DIR / "company_agent_results.json", state.get("company_agent_results", []))
        atomic_write_json(
            RUNS_DIR / f"{state['run_id']}_company_agent_results.json",
            state.get("company_agent_results", []),
        )
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


def build_graph(current_thread_id: str = ""):
    builder = StateGraph(CurationState)
    retry = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, max_interval=8.0)
    builder.add_node("ingest", ingest_evidence, retry_policy=retry)
    builder.add_node("classify", classify_sources, retry_policy=retry)
    builder.add_node("extract", extract_facts, retry_policy=retry)
    builder.add_node("validate", validate_entities, retry_policy=retry)
    builder.add_node("audit", audit_quality, retry_policy=retry)
    builder.add_node("resolve", resolve_conflicts, retry_policy=retry)
    builder.add_node("search_verify", search_verify_facts, retry_policy=retry)
    builder.add_node("plan_gaps", plan_gaps, retry_policy=retry)
    builder.add_node("company_research", run_company_research_agents)
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
    builder.add_edge("resolve", "search_verify")
    builder.add_edge("search_verify", "plan_gaps")
    builder.add_edge("plan_gaps", "company_research")
    builder.add_edge("company_research", "supervisor")
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
        checkpoint_path = restore_compressed_checkpoint()
        maintenance = maintain_checkpoint_database(
            checkpoint_path,
            current_thread_id=current_thread_id,
        )
        if maintenance.get("maintained"):
            print(
                "[数据整理][检查点维护] "
                f"线程 {maintenance.get('threads_before')}→{maintenance.get('threads_after')}，"
                f"文件 {maintenance.get('before_bytes')}→{maintenance.get('after_bytes')} 字节。",
                flush=True,
            )
        connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
        checkpointer = SqliteSaver(connection)
    except ImportError:
        pass
    return builder.compile(checkpointer=checkpointer)


def run_workflow(
    *,
    limit: int | None = None,
    batch_size: int = 12,
    ai_workers: int = 1,
    search_verify_workers: int = 4,
    search_verify_online: bool = False,
    search_verify_online_limit: int = 0,
    online_ai: bool = True,
    allow_recrawl: bool = False,
    max_recrawl_rows: int = 3,
    max_recrawl_rounds: int = 1,
    dry_run: bool = False,
    run_id: str | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    run_id = str(run_id or "").strip() or (
        datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    )
    initial: CurationState = {
        "run_id": run_id,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "limit": limit,
        "batch_size": batch_size,
        "ai_workers": max(1, ai_workers),
        "search_verify_workers": max(1, search_verify_workers),
        "search_verify_online": search_verify_online,
        "search_verify_online_limit": max(0, search_verify_online_limit),
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
    graph = build_graph(run_id)
    config = {"configurable": {"thread_id": run_id}}
    if resume:
        try:
            checkpoint = graph.get_state(config)
        except Exception:
            checkpoint = None
        checkpoint_values = getattr(checkpoint, "values", {}) if checkpoint else {}
        checkpoint_next = tuple(getattr(checkpoint, "next", ()) or ()) if checkpoint else ()
        if checkpoint_values:
            if checkpoint_next:
                resume_controls = {
                    "batch_size": batch_size,
                    "ai_workers": max(1, ai_workers),
                    "search_verify_workers": max(1, search_verify_workers),
                    "search_verify_online": search_verify_online,
                    "search_verify_online_limit": max(0, search_verify_online_limit),
                    "online_ai": online_ai,
                    "dry_run": dry_run,
                }
                if any(
                    checkpoint_values.get(key) != value
                    for key, value in resume_controls.items()
                ):
                    updated_config = graph.update_state(config, resume_controls)
                    if isinstance(updated_config, dict):
                        config = updated_config
                result = graph.invoke(None, config=config)
            else:
                completed_summary = checkpoint_values.get("summary")
                if isinstance(completed_summary, dict) and completed_summary:
                    return completed_summary
                result = checkpoint_values
        else:
            result = graph.invoke(initial, config=config)
    else:
        result = graph.invoke(initial, config=config)
    return result.get("summary", {})
