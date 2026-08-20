import csv
import collections
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Generator
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from ai_rate_limit import (
    RateLimitedChatDeepSeek as ChatDeepSeek,
    reset_internal_ai_priority,
    set_internal_ai_priority,
)
from langgraph.prebuilt import create_react_agent

from ai_config import load_ai_config
from ai_response_compat import deepseek_nonthinking_parameters, load_json_response
from agent_memory import add_memory, auto_capture_user_memory, load_memories, memory_context, search_memories
from agent_production import (
    AgentRunRecorder,
    action_id,
    confirmation_event,
    confirmation_metadata,
    dataset_lineage,
    retrieval_quality,
    rolling_backtest,
)
from crawl_run_registry import latest_crawl_run_summary
from network_utils import urlopen_with_local_proxy_fallback
from rag_llm import build_context_package, default_background_dataset_ids, effective_dataset_ids, list_knowledge_datasets, resolve_dataset_ids, retrieve_context
from chart_renderer import render_chart


_NON_AI_FOLLOW_UP_SUGGESTIONS = {
    "继续深化当前问题",
    "核对相关数据来源",
    "换一个角度继续分析",
    "从缺失部分继续补全",
    "缩小到两家厂商对比",
    "只列现金流具体数据",
    "缩小问题范围后重试",
    "指定需要分析的主体",
    "查看当前可用的数据集",
    "指定要比较的竞对主体",
    "指定最近两周的起止日期",
}


def _normalize_follow_up_suggestions(items: Any) -> list[str]:
    """Normalize model-generated follow-ups for the three suggestion buttons."""
    if not isinstance(items, (list, tuple)):
        return []
    internal_or_answer_fragment = re.compile(
        r"(?:是否需要我|需要我(?:来)?|要我(?:来)?|我可以(?:为你|为您)?|"
        r"读取.*文件|内部工具|web_search|read_webpage|search_local_reports|"
        r"^(?:数据来源|数据完整性|分析局限性)\s*[:：])",
        re.IGNORECASE,
    )
    direct_request = re.compile(
        r"^(?:请|帮我|如何|为什么|什么|哪些|哪个|是否|能否|怎么|多少|何时|哪里|"
        r"查看|分析|对比|比较|评估|梳理|解释|预测|计算|核验|展示|总结|补充)"
    )
    normalized: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item = item.get("question") or item.get("text") or item.get("suggestion")
        text = re.sub(r"^\s*(?:[-*•]\s*|\d+[.)、]\s*)", "", str(item or "")).strip()
        text = re.sub(r"^推荐追问\s*[:：]\s*", "", text).strip()
        text = re.sub(r"(?:相关)?文件来源", "官方来源", text)
        text = re.sub(r"[*_`]+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        request_like = text.endswith(("？", "?")) or bool(direct_request.search(text))
        if (
            not text
            or len(text) > 100
            or text in normalized
            or internal_or_answer_fragment.search(text)
            or not request_like
        ):
            continue
        normalized.append(text)
        if len(normalized) == 3:
            break
    return normalized


def _extract_follow_up_suggestions(value: str) -> list[str]:
    """Parse model suggestions from JSON, nested tags, or Markdown bullets."""
    text = str(value or "").strip()
    tag_match = re.search(r"<suggestions(?:\s[^>]*)?>([\s\S]*?)</suggestions\s*>", text, re.IGNORECASE)
    payload = (tag_match.group(1) if tag_match else text).strip()
    payload = re.sub(r"^```(?:json)?\s*", "", payload, flags=re.IGNORECASE)
    payload = re.sub(r"\s*```$", "", payload)

    json_candidates = [payload]
    array_match = re.search(r"\[[\s\S]*\]", payload)
    if array_match and array_match.group(0) != payload:
        json_candidates.append(array_match.group(0))
    object_match = re.search(r"\{[\s\S]*\}", payload)
    if object_match and object_match.group(0) != payload:
        json_candidates.append(object_match.group(0))
    for candidate in json_candidates:
        try:
            parsed = load_json_response(candidate, operation="小竞AI推荐追问")
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            parsed = parsed.get("suggestions") or parsed.get("questions") or parsed.get("follow_ups")
        normalized = _normalize_follow_up_suggestions(parsed)
        if normalized:
            return normalized

    nested = re.findall(r"<suggestion(?:\s[^>]*)?>([\s\S]*?)</suggestion\s*>", payload, re.IGNORECASE)
    normalized = _normalize_follow_up_suggestions(nested)
    if normalized:
        return normalized

    bullet_lines = [
        match.group(1)
        for match in re.finditer(r"(?m)^\s*(?:[-*•]\s+|\d+[.)、]\s*)(.+?)\s*$", payload)
    ]
    return _normalize_follow_up_suggestions(bullet_lines)


def _suggestions_are_ai_specific(items: list[str]) -> bool:
    if len(items) != 3 or all(item in _NON_AI_FOLLOW_UP_SUGGESTIONS for item in items):
        return False
    normalized = [re.sub(r"[\s？?。！!，,、：:；;]", "", item).lower() for item in items]
    return len(set(normalized)) == 3


def _emergency_follow_up_suggestions(user_request: str, answer: str) -> list[str]:
    """Last-resort UI continuity when every internal model endpoint is unavailable."""
    combined = f"{user_request}\n{answer}"
    if re.search(r"5G|6G|AI|人工智能", combined, re.IGNORECASE):
        return ["梳理关键时间线并标注官方来源", "对比相关主体、指标与政策差异", "评估对CMHK经营与网络部署的影响"]
    if re.search(r"云|AWS|Azure|Google|阿里|腾讯|华为", combined, re.IGNORECASE):
        return ["对比主要云厂商的同口径经营指标", "梳理近三年投入变化并标注来源", "评估这些变化对CMHK的机会与风险"]
    return ["深入分析当前结论的关键依据", "补充同口径数据与权威来源对比", "把结论转化为可执行的行动建议"]


def _ensure_ai_follow_up_suggestions(
    user_request: str,
    answer: str,
    *,
    thinking_enabled: bool = False,
) -> tuple[list[str], dict[str, int], str]:
    """Guarantee three follow-ups without making answer completion depend on them."""
    embedded = _extract_follow_up_suggestions(answer)
    if _suggestions_are_ai_specific(embedded):
        return embedded, {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}, "answer"

    config = load_ai_config()
    clean_answer = re.sub(
        r"<suggestions(?:\s[^>]*)?>[\s\S]*?</suggestions\s*>",
        "",
        str(answer or ""),
        flags=re.IGNORECASE,
    ).strip()
    prompt_messages = [
        SystemMessage(
            content=(
                "根据用户问题和当前回答，自主生成3个自然、具体、互不重复的简体中文后续问题，"
                "让用户可以直接点击继续对话。问题应承接回答中尚值得继续分析的内容，"
                "不要复述答案、描述内部工具或询问是否要读取文件。"
                "只输出JSON对象，格式为{\"suggestions\":[\"问题1\",\"问题2\",\"问题3\"]}。"
            )
        ),
        HumanMessage(
            content=(
                f"问题：{str(user_request or '').strip()[:400]}\n"
                f"回答：{clean_answer[:1200] or '本轮操作已完成。'}"
            )
        ),
    ]
    selected_model = _agent_model_name(thinking_enabled=thinking_enabled)
    # Use the known concise company model first. Some reasoning-oriented models
    # can consume the gateway's entire short-output budget on hidden reasoning
    # and return an empty visible JSON body.
    model_names = list(dict.fromkeys(["deepseek-v4", selected_model, "GLM"]))[:3]
    total_usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    for model_name in model_names:
        model = ChatDeepSeek(
            model=model_name,
            api_key=config.get("api_key", ""),
            api_base=config.get("base_url", ""),
            extra_body={
                **deepseek_nonthinking_parameters(config.get("extra_parameters") or {}),
                "response_format": {"type": "json_object"},
            },
            temperature=0.2,
            disable_streaming=True,
            max_retries=1,
            max_tokens=500,
        )
        try:
            response = model.invoke(prompt_messages)
        except Exception:
            continue
        usage = _message_token_usage(response)
        for key in total_usage:
            total_usage[key] += usage[key]
        generated = _extract_follow_up_suggestions(str(getattr(response, "content", "") or ""))
        if _suggestions_are_ai_specific(generated):
            return generated, total_usage, "dedicated_model"

    return _emergency_follow_up_suggestions(user_request, clean_answer), total_usage, "emergency"


ROOT = Path(__file__).resolve().parent
AGENT_SKILLS_DIR = ROOT / "Codex" / "agent" / "skills"
CHAT_THREADS_PATH = ROOT / "agent_chat_threads" / "threads.json"
FRONTEND_SKILL_ORDER = [
    "executive-briefing",
    "quarterly-competitor-metrics",
    "cloud-vendor-metrics",
    "macro-policy-context",
    "trend-forecasting",
    "financial-visual-analytics",
]
WEB_SEARCH_INDEX_LOCK = threading.Lock()
WEB_SEARCH_NEXT_INDEX = 6
SELECTED_DATASET_IDS: ContextVar[set[str] | None] = ContextVar("SELECTED_DATASET_IDS", default=None)
SELECTED_SKILL_IDS: ContextVar[set[str] | None] = ContextVar("SELECTED_SKILL_IDS", default=None)
APPROVED_ACTION_IDS: ContextVar[set[str]] = ContextVar("APPROVED_ACTION_IDS", default=set())
ACTIVE_CHAT_THREAD_ID: ContextVar[str] = ContextVar("ACTIVE_CHAT_THREAD_ID", default="")
CURRENT_USER_REQUEST: ContextVar[str] = ContextVar("CURRENT_USER_REQUEST", default="")
WEB_SEARCH_AVAILABLE: ContextVar[bool] = ContextVar("WEB_SEARCH_AVAILABLE", default=False)


def _reset_web_search_indexes() -> None:
    global WEB_SEARCH_NEXT_INDEX
    with WEB_SEARCH_INDEX_LOCK:
        WEB_SEARCH_NEXT_INDEX = 6


def _allocate_web_search_indexes(count: int) -> int:
    global WEB_SEARCH_NEXT_INDEX
    with WEB_SEARCH_INDEX_LOCK:
        start = WEB_SEARCH_NEXT_INDEX
        WEB_SEARCH_NEXT_INDEX += max(0, count)
        return start


def _clean_search_text(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _parse_skill_frontmatter(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"description": "", "tags": [], "data": ""}
    match = re.search(r"^##\s+前端展示\s*\n(?P<body>.*?)(?=^##\s+|\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return meta
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue
        item = line.lstrip("-").strip()
        if "：" not in item:
            continue
        key, value = item.split("：", 1)
        key = key.strip()
        value = value.strip()
        if key == "简介":
            meta["description"] = value
        elif key == "标签":
            meta["tags"] = [part.strip() for part in re.split(r"[、,，]", value) if part.strip()]
        elif key == "数据":
            meta["data"] = value
    return meta


def available_agent_skills() -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    if not AGENT_SKILLS_DIR.exists():
        return []
    for skill_file in sorted(AGENT_SKILLS_DIR.glob("*/SKILL.md")):
        skill_id = skill_file.parent.name
        try:
            text = skill_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        display_meta = _parse_skill_frontmatter(text)
        title = skill_id
        summary = ""
        for line in text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            if clean.startswith("#") and title == skill_id:
                title = clean.lstrip("#").strip() or title
                continue
            if not summary and not clean.startswith(("-", "`", "#")):
                summary = clean[:180]
                break
        by_id[skill_id] = {
            "id": skill_id,
            "title": title,
            "summary": display_meta.get("description") or summary or "项目内 Agent skill",
            "description": display_meta.get("description") or summary or "项目内 Agent skill",
            "tags": display_meta.get("tags") or [],
            "data": display_meta.get("data") or "",
            "path": skill_file.relative_to(ROOT).as_posix(),
        }
    preferred = [by_id[skill_id] for skill_id in FRONTEND_SKILL_ORDER if skill_id in by_id]
    preferred_ids = {item["id"] for item in preferred}
    remaining = [item for skill_id, item in sorted(by_id.items()) if skill_id not in preferred_ids]
    return [*preferred, *remaining]


def _selected_skill_context(skill_ids: list[str] | None, message: str = "") -> str:
    if not skill_ids:
        return ""
    by_id = {item["id"]: item for item in available_agent_skills()}
    lines: list[str] = []
    for skill_id in skill_ids:
        clean_id = re.sub(r"[^A-Za-z0-9_.-]", "", str(skill_id or ""))
        item = by_id.get(clean_id)
        if item:
            lines.append(
                f"- {clean_id}: {item.get('description') or item.get('summary') or item.get('title') or clean_id}"
            )
    return "\n".join(lines)


def _looks_like_blocked_or_encoded_text(text: str) -> bool:
    sample = " ".join((text or "").split())[:2400]
    if not sample:
        return False
    if re.search(r"_waf_|waf|captcha|verify|访问验证|安全验证|人机验证", sample, re.IGNORECASE):
        return True
    compact = re.sub(r"\s+", "", sample)
    if len(compact) < 300:
        return False
    encoded_chars = sum(1 for ch in compact if ch.isalnum() or ch in "+/=_-")
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", compact))
    return encoded_chars / max(len(compact), 1) > 0.92 and cjk_chars < 20


def _search_query_from_instruction(value: str) -> str:
    text = _clean_search_text(value, 200)
    text = re.sub(r"^(请|帮我|麻烦)?(上网|联网|网上)?(搜一下|搜索一下|搜搜|搜索|查一下|查询)", "", text).strip()
    text = re.sub(r"(给我|帮我)?(?:找|列|提供)?[一二两三四五六七八九十\d]+个?来源.*$", "", text).strip(" ，,。；;")
    return text or _clean_search_text(value, 200)


def _normalize_search_results(items: list[dict[str, Any]], limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        title = _clean_search_text(item.get("title") or item.get("heading") or item.get("name"), 120)
        url = _clean_search_text(item.get("url") or item.get("href") or item.get("link"), 500)
        snippet = _clean_search_text(
            item.get("content") or item.get("body") or item.get("snippet") or item.get("description"),
            320,
        )
        if not title or not url or not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


_SEARCH_QUERY_STOP_WORDS = {
    "一下", "一下子", "相关", "资料", "信息", "最新", "事件", "时间线",
    "the", "and", "for", "with", "from", "latest", "news", "information",
}


def _search_query_terms(query: str) -> list[str]:
    clean = _clean_search_text(query, 240).lower()
    candidates = re.findall(r"[a-z][a-z0-9.+-]{1,}|[\u4e00-\u9fff]{2,}", clean)
    domain_markers = (
        "香港", "频谱", "政策", "监管", "拍卖", "分配", "续期", "牌照",
        "通讯事务", "通讯办", "人口", "收入", "利润", "用户", "覆盖",
        "云计算", "人工智能", "资本开支",
    )
    candidates.extend(marker for marker in domain_markers if marker in clean)
    terms: list[str] = []
    for term in candidates:
        term = term.strip().lower()
        if (
            not term
            or term in _SEARCH_QUERY_STOP_WORDS
            or re.fullmatch(r"(?:19|20)\d{2}", term)
            or term.isdigit()
            or term in terms
        ):
            continue
        terms.append(term)
    return terms[:16]


def _search_result_domain(url: str) -> str:
    return urlparse(str(url or "")).netloc.lower().split(":", 1)[0].removeprefix("www.")


def _filter_relevant_search_results(
    items: list[dict[str, str]],
    query: str,
    limit: int,
    *,
    required_domains: tuple[str, ...] = (),
) -> tuple[list[dict[str, str]], int]:
    """Reject search-engine poisoning and unrelated pages before they reach the model."""
    terms = _search_query_terms(query)
    required = tuple(domain.lower().removeprefix("www.") for domain in required_domains)
    blocked_root_pages = {
        "google.com", "yandex.ru", "bing.com", "baidu.com", "duckduckgo.com",
    }
    blocked_content = re.compile(
        r"(?:onlyfans|成人视频|色情|成人视频|авто|автомоб|коврик|багажник)",
        re.IGNORECASE,
    )
    accepted: list[dict[str, str]] = []
    for item in items:
        domain = _search_result_domain(item.get("url") or "")
        path = urlparse(item.get("url") or "").path.strip("/")
        haystack = " ".join(
            [item.get("title") or "", item.get("snippet") or "", item.get("url") or ""]
        ).lower()
        if (
            (domain in blocked_root_pages and not path)
            or blocked_content.search(haystack)
            or (required and not any(domain == wanted or domain.endswith("." + wanted) for wanted in required))
        ):
            continue
        matched = {term for term in terms if term in haystack}
        minimum = 1 if len(terms) <= 2 else 2
        domain_match = bool(
            required and any(domain == wanted or domain.endswith("." + wanted) for wanted in required)
        )
        if not domain_match and len(matched) < minimum:
            continue
        accepted.append(item)
        if len(accepted) >= limit:
            break
    return accepted, max(0, len(items) - len(accepted))


def _official_search_context(query: str) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Return trustworthy official entry points for domains with known authoritative sources."""
    text = str(query or "")
    if re.search(r"香港|Hong\s*Kong|OFCA|通讯事务|通訊事務", text, re.IGNORECASE) and re.search(
        r"5G|6G|频谱|頻譜|电讯|電訊|通讯|通訊|监管|監管", text, re.IGNORECASE
    ):
        year = datetime.now().year
        return (
            ("ofca.gov.hk", "coms-auth.hk"),
            [
                {
                    "title": "OFCA：香港通讯及频谱政策里程碑",
                    "url": "https://www.ofca.gov.hk/tc/news_info/milestones/index.html",
                    "snippet": "香港5G频谱分配、拍卖、牌照及监管政策的官方时间线入口。",
                },
                {
                    "title": "OFCA：香港无线电频谱拍卖",
                    "url": "https://www.ofca.gov.hk/tc/industry_focus/radio_spectrum/auctions/index.html",
                    "snippet": "香港各移动频段拍卖、分配结果、牌照条款及频谱使用费的官方入口。",
                },
                {
                    "title": f"OFCA：{year}至{year + 2}年频谱发布计划",
                    "url": f"https://www.ofca.gov.hk/filemanager/ofca/en/content_144/spectrum_plan{year}_en.pdf",
                    "snippet": "香港未来三年可供分配及重新分配频谱的官方计划。",
                },
            ],
        )
    if re.search(r"香港|Hong\s*Kong|C&SD|统计处|統計處", text, re.IGNORECASE) and re.search(
        r"人口|住户|住戶|收入|GDP|消费|消費|就业|就業|统计|統計", text, re.IGNORECASE
    ):
        return (
            ("censtatd.gov.hk",),
            [
                {
                    "title": "香港政府统计处：统计数据",
                    "url": "https://www.censtatd.gov.hk/en/",
                    "snippet": "香港人口、住户、收入、消费、就业及本地生产总值的官方统计入口。",
                }
            ],
        )
    return (), []


def _unwrap_search_redirect(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "search.yahoo.com" in parsed.netloc and "/RU=" in parsed.path:
        encoded = parsed.path.split("/RU=", 1)[1].split("/RK=", 1)[0]
        return unquote(encoded)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        if query.get("uddg"):
            return query["uddg"][0]
    query = parse_qs(parsed.query)
    for key in ("url", "u"):
        if query.get(key):
            return query[key][0]
    return url


def _search_with_searxng(query: str, limit: int) -> list[dict[str, str]]:
    base_url = (os.environ.get("SEARXNG_URL") or os.environ.get("CMHK_SEARXNG_URL") or "").strip().rstrip("/")
    if not base_url:
        return []
    params = urlencode({"q": query, "format": "json", "language": "zh-CN"})
    req = Request(
        f"{base_url}/search?{params}",
        headers={"User-Agent": "CMHK-Research-Agent/1.0"},
    )
    with urlopen_with_local_proxy_fallback(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    raw_results = payload.get("results") if isinstance(payload, dict) else []
    return _normalize_search_results(raw_results or [], limit)


def _search_with_duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS  # type: ignore
    except Exception:
        return []
    with DDGS() as ddgs:
        raw_results = list(ddgs.text(query, max_results=limit))
    return _normalize_search_results(raw_results, limit)


def _search_with_duckduckgo_html(query: str, limit: int) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup

    req = Request(
        "https://html.duckduckgo.com/html/?" + urlencode({"q": query}),
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urlopen_with_local_proxy_fallback(req, timeout=20) as response:
        html = response.read().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    raw_results: list[dict[str, Any]] = []
    for block in soup.select(".result"):
        link = block.select_one(".result__a[href]") or block.select_one('a[href]')
        if not link:
            continue
        snippet_node = block.select_one(".result__snippet")
        raw_results.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": _unwrap_search_redirect(link.get("href") or ""),
                "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            }
        )
    return _normalize_search_results(raw_results, limit)


def _search_with_brave_html(query: str, limit: int) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup

    req = Request(
        "https://search.brave.com/search?" + urlencode({"q": query, "source": "web"}),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen_with_local_proxy_fallback(req, timeout=20) as response:
        html = response.read().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    raw_results: list[dict[str, Any]] = []
    for block in soup.select(".snippet"):
        link = block.select_one('a[href^="http"]')
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        url = _unwrap_search_redirect(link.get("href") or "")
        text = block.get_text(" ", strip=True)
        snippet = text.replace(title, "", 1).strip(" -")
        raw_results.append({"title": title, "url": url, "snippet": snippet})
    return _normalize_search_results(raw_results, limit)


def _search_with_yahoo_html(query: str, limit: int) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup

    req = Request(
        "https://search.yahoo.com/search?" + urlencode({"p": query}),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen_with_local_proxy_fallback(req, timeout=20) as response:
        html = response.read().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    raw_results: list[dict[str, Any]] = []
    for block in soup.select(".dd.algo"):
        link = block.select_one(".compTitle a[href]") or block.select_one('a[href^="http"]')
        title_node = block.select_one("h3.title") or link
        snippet_node = block.select_one(".compText p") or block.select_one("p")
        if not link or not title_node:
            continue
        raw_results.append(
            {
                "title": title_node.get_text(" ", strip=True),
                "url": _unwrap_search_redirect(link.get("href") or ""),
                "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            }
        )
    return _normalize_search_results(raw_results, limit)


def _display_tool_result(tool_name: str, content: str, meta_event: dict[str, Any] | None) -> str:
    if tool_name == "list_local_datasets":
        return content[:4000].rstrip()
    if tool_name == "list_crawl_runs":
        return content[:4000].rstrip()
    if tool_name == "web_search":
        refs = (meta_event or {}).get("references") or []
        if not refs:
            preview = content.strip()
            return preview[:1200].rstrip() if preview else "联网搜索完成，但没有返回可展示来源。"
        lines = [f"联网搜索完成，找到 {len(refs)} 个来源："]
        for ref in refs[:6]:
            links = ref.get("links") or []
            link = links[0] if links else {}
            label = _clean_search_text(ref.get("source") or link.get("label") or "来源", 120)
            url = _clean_search_text(link.get("url") or "", 300)
            lines.append(f"[{ref.get('index')}] {label}" + (f"\n{url}" if url else ""))
        preview = content.strip()
        if preview:
            lines.append("\n具体返回内容：")
            lines.append(preview[:4000].rstrip())
        return "\n".join(lines)
    if tool_name == "search_local_reports":
        refs = (meta_event or {}).get("references") or []
        preview = content.strip()
        if "【本地资料】" in preview and "【联网资料】" in preview:
            local_preview, web_preview = preview.split("【联网资料】", 1)
            return (
                f"已同时检索本地与联网资料，共找到 {len(refs)} 个相关来源。\n\n"
                f"{local_preview[:2200].rstrip()}\n\n"
                f"【联网资料】\n{web_preview[:1800].strip()}"
            ).rstrip()
        return (
            f"已读取已选数据库摘要，找到 {len(refs)} 个相关片段。\n\n"
            f"具体返回内容：\n{preview[:4000].rstrip()}"
        ).rstrip()
    if tool_name == "read_local_reference":
        if content.startswith("本地引用读取失败"):
            return content
        return f"已读取数据库原文。\n\n具体返回内容：\n{content[:4000].rstrip()}"
    if tool_name == "read_agent_skill":
        if content.startswith("Agent Skill 读取失败"):
            return content
        return f"Agent Skill 已读取。\n\n具体返回内容：\n{content[:6000].rstrip()}"
    if tool_name == "read_webpage":
        if content.startswith(("网页读取失败", "网页读取跳过", "读取网页")):
            return "网页读取失败，已改用搜索摘要和本地资料。"
        if content.startswith("PDF读取失败"):
            return "PDF 读取失败，已改用搜索摘要和本地资料。"
        return f"网页读取完成。\n\n具体返回内容：\n{content[:4000].rstrip()}"
    if tool_name == "render_python_chart":
        return content[:4000].rstrip()
    if len(content) > 1200:
        return content[:1200].rstrip() + "\n..."
    return content


def _selected_dataset_ids() -> set[str] | None:
    return SELECTED_DATASET_IDS.get()


def _effective_selected_dataset_ids() -> set[str] | None:
    return effective_dataset_ids(_selected_dataset_ids())


def _dataset_id_for_agent_knowledge_source(source: str) -> str:
    clean = str(source or "").strip().removeprefix("/references/")
    parts = clean.split("/")
    if len(parts) >= 2 and parts[0] == "agent_knowledge":
        folder = ROOT / "agent_knowledge" / parts[1]
        if folder.exists():
            for dataset in list_knowledge_datasets():
                if dataset.get("folder") == f"agent_knowledge/{parts[1]}":
                    return str(dataset.get("id") or parts[1])
        return parts[1]
    return ""


def _dataset_is_selected(source: str) -> bool:
    selected = _effective_selected_dataset_ids()
    if selected is None:
        return True
    dataset_id = _dataset_id_for_agent_knowledge_source(source)
    return not dataset_id or dataset_id in selected


def _is_action_approved(name: str, payload: Any = None) -> bool:
    approved = APPROVED_ACTION_IDS.get()
    return action_id(name, payload) in approved


def _require_action_confirmation(name: str, payload: Any = None, description: str = "") -> str | None:
    if _is_action_approved(name, payload):
        return None
    event = confirmation_event(name, payload, description)
    return (
        f"需要用户确认后才能执行：{event['label']}。\n"
        f"- 原因：{event['risk']}\n"
        f"- 操作说明：{event['description']}\n"
        "请点击前端确认按钮后再执行。"
        f"\n{confirmation_metadata(event)}"
    )


@tool
def read_agent_skill(skill_id: str) -> str:
    """读取本轮已选择的 Agent Skill 完整 SKILL.md 指令。
    Agent 可在需要专业分析方法时读取前端已选择的 Skill。
    """
    clean_id = re.sub(r"[^A-Za-z0-9_.-]", "", str(skill_id or ""))
    if not clean_id:
        return "Agent Skill 读取失败：skill_id 为空。"
    selected_ids = {
        re.sub(r"[^A-Za-z0-9_.-]", "", str(item or ""))
        for item in (SELECTED_SKILL_IDS.get() or set())
        if str(item or "").strip()
    }
    allowed = {item["id"] for item in available_agent_skills()}
    if clean_id not in allowed:
        return f"Agent Skill 读取失败：{clean_id} 不是前端允许的主要 Skill。"
    if selected_ids and clean_id not in selected_ids:
        return f"Agent Skill 读取失败：{clean_id} 本轮未在前端 Skill 按钮中选择。"
    skill_file = AGENT_SKILLS_DIR / clean_id / "SKILL.md"
    if not skill_file.exists():
        return f"Agent Skill 读取失败：未找到 {clean_id}/SKILL.md。"
    try:
        text = skill_file.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception as exc:
        return f"Agent Skill 读取失败：{clean_id} 无法读取，原因：{_clean_search_text(exc, 160)}。"
    if not text:
        return f"Agent Skill 读取失败：{clean_id}/SKILL.md 内容为空。"
    referenced_files = sorted(
        {
            match
            for match in re.findall(r"`([^`]+?\.(?:md|csv|json|py|txt))`", text, flags=re.IGNORECASE)
            if not match.startswith(("/", "http://", "https://")) and ".." not in match
        }
    )
    refs_text = "\n".join(f"- {item}" for item in referenced_files) or "- 未发现显式引用文件"
    return (
        f"[Agent Skill: {clean_id}]\n"
        f"路径：{skill_file.relative_to(ROOT).as_posix()}\n"
        "已读取完整 SKILL.md。若下列引用文件与本轮任务相关，应继续用本地检索/读取工具追溯，而不是只停留在 Skill 标题。\n"
        f"引用文件线索：\n{refs_text}\n\n"
        f"{text}"
    )


@tool
def list_local_datasets() -> str:
    """列出小竞 AI 后端当前可检索和读取的本地数据集。
    当用户问“你能访问哪些数据”“数据放哪里”“有哪些内部/外部数据”，或你准备做趋势分析、问数、核验前需要了解可用数据时，先使用此工具。
    """
    selected_ids = _effective_selected_dataset_ids()
    datasets = list_knowledge_datasets(dataset_ids=selected_ids)
    if not datasets:
        return "当前没有可用的本地数据库。"
    background_ids = default_background_dataset_ids()
    lines = ["本轮可检索的本地数据库："]
    visible_count = sum(1 for dataset in datasets if dataset.get("id") not in background_ids)
    if background_ids:
        lines.append(
            "说明：前端只展示用户可选的主数据库；爬虫日志、运行审计等支撑库由后端默认加载，用于追溯和排错。"
        )
    if visible_count:
        lines.append(f"用户已选择主数据库 {visible_count} 个。")
    for index, dataset in enumerate(datasets, 1):
        background_label = "（后台默认加载）" if dataset.get("id") in background_ids else ""
        entrypoints = dataset.get("entrypoints") or []
        files = dataset.get("files") or []
        lines.append(
            "\n".join(
                [
                    f"[数据集 {index}] {dataset.get('title') or dataset.get('id')}{background_label}",
                    f"- id: {dataset.get('id')}",
                    f"- 类型: {dataset.get('source_type') or 'local'}",
                    f"- 范围: {dataset.get('scope') or '未说明'}",
                    f"- 简介: {dataset.get('summary') or '未说明'}",
                    f"- 标签: {'、'.join(dataset.get('tags') or []) or '无'}",
                    f"- 入口文件: {', '.join(entrypoints) or '未指定'}",
                    f"- 文件夹: {dataset.get('folder')}",
                ]
            )
        )
    # Dataset enumeration is UI/context metadata, not evidence. Do not emit
    # citation references here; otherwise later RAG results that also start at
    # [1] create duplicate footer numbers and ambiguous inline citations.
    meta_data = {"type": "meta", "sources": [d.get("title") for d in datasets], "links": [], "references": []}
    return "\n\n".join(lines) + f"\n<metadata>{json.dumps(meta_data, ensure_ascii=False)}</metadata>"


@tool
def list_crawl_runs(limit: int = 5) -> str:
    """列出最近几次全量爬虫运行索引。
    当用户询问爬虫日志、上次爬虫结果、失败链接、覆盖率、飞书日志页、Agent 数据整理运行记录或调度追溯时，先使用此工具。
    """
    return latest_crawl_run_summary(max(1, int(limit or 5)))


def _search_local_reports_only(query: str, max_results: int = 12) -> str:
    """Return local retrieval evidence without deciding how the Agent uses it."""
    limit = max(1, int(max_results or 12))
    selected_ids = _effective_selected_dataset_ids()
    chunks = retrieve_context(
        query,
        limit=limit,
        dataset_ids=selected_ids,
    )
    # Models may shorten a tool query and accidentally drop a decisive metric
    # qualifier. Keep exact rows matched from the original user request at the
    # front of every local search in the same turn.
    original_request = _clean_search_text(CURRENT_USER_REQUEST.get(), 1200)
    if original_request and original_request != _clean_search_text(query, 1200):
        original_chunks = retrieve_context(
            original_request,
            limit=limit,
            dataset_ids=selected_ids,
        )
        exact_prefixes = (
            "精确年度运营商指标行：",
            "精確年度運營商指標行：",
            "香港本地运营商精确年度指标行：",
            "香港本地運營商精確年度指標行：",
        )
        priority = [
            chunk for chunk in original_chunks
            if str(chunk.get("text") or "").startswith(exact_prefixes)
        ]
        if priority:
            seen = {(str(chunk.get("source") or ""), str(chunk.get("text") or "")) for chunk in priority}
            chunks = (priority + [
                chunk for chunk in chunks
                if (str(chunk.get("source") or ""), str(chunk.get("text") or "")) not in seen
            ])[:limit]
    if not chunks:
        return "没有找到相关的本地报告信息。"
    context_package = build_context_package(chunks, model=_agent_model_name())
    chunks = context_package["chunks"]
    audit = context_package["audit"]
    quality = retrieval_quality(query, chunks, audit)

    result = []
    references = []
    meta_links = []
    seen_urls = set()
    for i, chunk in enumerate(chunks):
        ref_label = f"{chunk['source']} · 片段 {i + 1}"
        result.append(f"[来源 {i+1}: {ref_label}]\n{chunk['text']}")
        chunk_links = chunk.get("links", [])
        references.append(
            {
                "index": i + 1,
                "source": ref_label,
                "links": [
                    {
                        **link,
                        "label": f"{link.get('label') or chunk['source']} · 片段 {i + 1}",
                    }
                    for link in chunk_links
                ],
            }
        )
        for link in chunk_links:
            url = link.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                meta_links.append(link)

    text_output = "\n\n".join(result)
    meta_data = {
        "type": "meta",
        "sources": [chunk["source"] for chunk in chunks],
        "links": meta_links,
        "references": references,
        "contextAudit": audit,
        "retrievalQuality": quality,
    }
    return f"{text_output}\n<metadata>{json.dumps(meta_data, ensure_ascii=False)}</metadata>"


@tool
def search_local_reports(query: str, max_results: int = 12) -> str:
    """按当前分析意图研究本地数据库、报告和公开网页。
    联网开启时，这个工具会用同一查询同时返回“本地资料”和“联网资料”；联网关闭时只查本地。
    query 要写清本次想找的主体、指标、时期和比较维度；不同分析目的应使用不同查询，
    例如“套餐价格与合约”和“网络时延、抖动、稳定性”不要写成同一个宽泛查询。
    返回“没有找到”只代表本次查询未命中，不代表数据库中一定不存在；可自行换词继续搜索，
    也可用 list_local_datasets 或 read_local_reference 检查覆盖范围和原文。
    max_results 是本次希望取得的候选数量，后端不会静默缩减；一次结果不足时可提高数量或换词继续检索。
    此工具不限制同一轮调用次数，模型可以按分析需要反复检索。
    """
    limit = max(1, int(max_results or 12))
    local_raw = _search_local_reports_only(query, limit)
    if not WEB_SEARCH_AVAILABLE.get():
        return local_raw
    web_raw = _web_search_only(query, limit)
    return _merge_local_and_web_research(local_raw, web_raw)


def _read_local_reference_text(source: str) -> str:
    import web_app

    clean = str(source or "").strip()
    if not clean:
        return "本地引用读取失败：来源为空。"
    if clean.startswith("/references/"):
        clean = clean.removeprefix("/references/")
    if not _dataset_is_selected(clean):
        return f"本地引用读取失败：{clean} 所属数据库本轮未被前端选择，后端不会把它发送给 AI。"
    target = web_app.reference_path(clean)
    if not target or not target.exists():
        return f"本地引用读取失败：未找到允许读取的本地引用 {clean}。"
    if clean == "agent_knowledge/competitor_product_tariffs/product_tariffs_formal_agent_records.csv":
        original_request = _clean_search_text(CURRENT_USER_REQUEST.get(), 1200)
        if original_request:
            tariff_chunks = [
                chunk
                for chunk in retrieve_context(
                    original_request,
                    limit=8,
                    dataset_ids={"competitor_product_tariffs"},
                )
                if chunk.get("source") == clean
                and "数据集全局覆盖锚点" in str(chunk.get("text") or "")
            ]
            if tariff_chunks:
                structured_text = "\n\n".join(
                    str(chunk.get("text") or "")
                    for chunk in tariff_chunks
                )
                return (
                    f"[本地引用: {clean}]\n"
                    "以下为根据本轮用户问题读取的正式资费结构化原文；"
                    "它覆盖所有相关品牌块，不能用 CSV 文件头附近的单一品牌代替全库结论。\n"
                    f"{structured_text[:18000]}"
                )
    try:
        text = web_app.read_display_text(target)
    except Exception as exc:
        return f"本地引用读取失败：{clean} 无法读取，原因：{_clean_search_text(exc, 160)}。"
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return f"本地引用读取失败：{clean} 内容为空。"
    # Keep each individual result within the model context budget. This is a
    # per-result payload size boundary, not a tool invocation limit.
    limit = 18000 if clean.startswith("agent_knowledge/") else 12000
    return f"[本地引用: {clean}]\n{text[:limit]}"


@tool
def read_local_reference(source: str) -> str:
    """读取本地引用文件的原文内容。
    当 `search_local_reports` 返回 `weekly_report.md`、`final_audit.md`、`coverage_report.tsv`、`run_log.tsv` 或 `row_*.json`
    等本地来源，而你需要查看更完整上下文、核对本地口径或追溯原始抓取结果时，优先使用此工具。
    参数可以是文件名，也可以是 `/references/...` 链接。
    此工具不限制同一轮调用次数；模型可以按分析需要读取任意来源，也可以重复读取同一来源。
    """
    return _read_local_reference_text(source)


def _web_search_only(query: str, max_results: int = 5) -> str:
    """Return public-web search evidence without deciding how the Agent uses it."""
    query = _search_query_from_instruction(query)
    if not query:
        return "搜索关键词为空。"
    limit = max(1, int(max_results or 5))
    provider = "searxng"
    failures: list[str] = []
    try:
        results = _search_with_searxng(query, limit)
    except Exception as exc:
        results = []
        failures.append(f"SearXNG: {_clean_search_text(exc, 120)}")
    if not results:
        provider = "ddgs"
        try:
            results = _search_with_duckduckgo(query, limit)
        except Exception as exc:
            failures.append(f"DDGS: {_clean_search_text(exc, 120)}")
            results = []
    if not results:
        provider = "duckduckgo_html"
        try:
            results = _search_with_duckduckgo_html(query, limit)
        except Exception as exc:
            failures.append(f"DuckDuckGo HTML: {_clean_search_text(exc, 120)}")
            results = []
    if not results:
        provider = "yahoo_html"
        try:
            results = _search_with_yahoo_html(query, limit)
        except Exception as exc:
            failures.append(f"Yahoo: {_clean_search_text(exc, 120)}")
            results = []
    if not results:
        provider = "brave_html"
        try:
            results = _search_with_brave_html(query, limit)
        except Exception as exc:
            failures.append(f"Brave: {_clean_search_text(exc, 120)}")
            results = []
    official_domains, official_seeds = _official_search_context(query)
    if not results and official_seeds:
        results = list(official_seeds)
        provider = "official_entrypoints"
    elif not results:
        detail = "；".join(failures[-4:]) if failures else "搜索源没有返回结果"
        return (
            f"联网搜索未返回可用网页结果。查询：{query}。搜索源状态：{detail}。"
            "建议稍后重试，或配置稳定的自托管 SearXNG：设置 SEARXNG_URL 后重启后端。"
        )

    raw_result_count = len(results)
    relevant_results, discarded_count = _filter_relevant_search_results(results, query, limit)
    if official_domains:
        official_results, _ = _filter_relevant_search_results(
            results,
            query,
            limit,
            required_domains=official_domains,
        )
        merged: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        # For known regulator/government topics, fail closed to the official
        # domains. SEO-poisoned pages can repeat query terms in hidden snippets
        # and must never be reintroduced merely because keyword scoring passed.
        for item in [*official_results, *official_seeds]:
            url = item.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(item)
            if len(merged) >= limit:
                break
        results = merged
        if official_seeds and not official_results:
            provider = f"{provider}+official_entrypoints"
    else:
        results = relevant_results
    if not results:
        detail = "；".join(failures[-4:]) if failures else f"{provider} 返回的页面均与查询无关"
        return (
            f"联网搜索未返回与查询相关的可用网页结果。查询：{query}。"
            f"已过滤 {raw_result_count} 个无关或低质量结果。搜索源状态：{detail}。"
            "不得引用这些被过滤页面；请改用更具体的实体、指标或官方机构名称重试。"
        )

    lines = []
    references = []
    links = []
    start_index = _allocate_web_search_indexes(len(results))
    for offset, item in enumerate(results):
        index = start_index + offset
        title = item["title"]
        url = item["url"]
        snippet = item.get("snippet") or ""
        lines.append(f"[来源 {index}: {title}]\n链接：{url}\n摘要：{snippet}")
        link = {"label": title, "url": url}
        links.append(link)
        references.append({"index": index, "source": title, "links": [link]})
    meta_data = {
        "type": "meta",
        "provider": provider,
        "discardedIrrelevant": discarded_count,
        "officialDomains": list(official_domains),
        "sources": [item["title"] for item in results],
        "links": links,
        "references": references,
    }
    quality_note = ""
    if discarded_count:
        quality_note = (
            f"[联网检索质量] 已过滤 {discarded_count} 个与查询无关或低质量的结果；"
            "下列来源才可用于回答。\n\n"
        )
    return (
        quality_note
        + "\n\n".join(lines)
        + f"\n<metadata>{json.dumps(meta_data, ensure_ascii=False)}</metadata>"
    )


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索公开网页信息。
    当此工具可用且问题涉及可核验的外部事实或数据时使用。
    query 应对应当前要核验的具体事实或数据维度；一次结果不足时，可自行换关键词、
    语言、主体或官方域名继续检索，并结合 read_webpage 阅读关键原文。
    此工具不限制同一轮调用次数；max_results 不会被后端静默缩减。
    """
    return _web_search_only(query, max_results)


def _tool_text_and_metadata(value: str) -> tuple[str, dict[str, Any]]:
    match = re.search(r"\n?<metadata>(.*?)</metadata>\s*$", str(value or ""), re.DOTALL)
    if not match:
        return str(value or "").strip(), {}
    try:
        metadata = json.loads(match.group(1))
    except Exception:
        metadata = {}
    return str(value or "")[: match.start()].rstrip(), metadata


def _merge_local_and_web_research(local_raw: str, web_raw: str) -> str:
    """Merge two read-only retrieval payloads into one citation package."""
    local_text, local_meta = _tool_text_and_metadata(local_raw)
    web_text, web_meta = _tool_text_and_metadata(web_raw)

    local_refs = list(local_meta.get("references") or [])
    web_refs = list(web_meta.get("references") or [])
    next_index = max(
        [int(ref.get("index") or 0) for ref in local_refs if isinstance(ref, dict)] or [0]
    ) + 1
    reindexed_web_refs: list[dict[str, Any]] = []
    for offset, ref in enumerate(web_refs):
        if not isinstance(ref, dict):
            continue
        old_index = int(ref.get("index") or 0)
        new_index = next_index + offset
        if old_index:
            web_text = web_text.replace(f"[来源 {old_index}:", f"[来源 {new_index}:")
        reindexed_web_refs.append({**ref, "index": new_index})

    metadata = {
        "type": "meta",
        "sources": [*(local_meta.get("sources") or []), *(web_meta.get("sources") or [])],
        "links": [*(local_meta.get("links") or []), *(web_meta.get("links") or [])],
        "references": [*local_refs, *reindexed_web_refs],
        "contextAudit": local_meta.get("contextAudit"),
        "retrievalQuality": local_meta.get("retrievalQuality"),
        "webProvider": web_meta.get("provider"),
    }
    return (
        "【本地资料】\n"
        f"{local_text or '本地检索未返回结果。'}\n\n"
        "【联网资料】\n"
        f"{web_text or '联网检索未返回结果。'}\n"
        f"<metadata>{json.dumps(metadata, ensure_ascii=False)}</metadata>"
    )


@tool
def trigger_crawl(row_id: int) -> str:
    """触发针对特定行的爬虫任务。
    参数 row_id 是配置表中的行号。
    如果你需要最新抓取某一行的数据，使用此工具。注意这可能需要十几秒。
    """
    payload = {"row_id": int(row_id)}
    confirmation = _require_action_confirmation("trigger_crawl", payload, f"定向爬取配置表第 {row_id} 行。")
    if confirmation:
        return confirmation
    env = os.environ.copy()
    env["CMHK_ROWS"] = str(row_id)
    try:
        proc = subprocess.run([sys.executable, str(ROOT / "crawl.py")], env=env, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return f"爬取完成 (Row {row_id}):\nStdout: {proc.stdout[:1000]}..."
        else:
            return f"爬取失败 (Row {row_id}):\nStderr: {proc.stderr}"
    except Exception as e:
        return f"执行爬虫异常: {str(e)}"


@tool
def trigger_full_crawl() -> str:
    """触发完整公开信息爬取、飞书同步和公司指标刷新。
    当用户明确要求重新爬取、全量抓取、更新公开信息数据或跑完整采集流程时使用。该操作可能耗时较长。
    """
    import web_app

    confirmation = _require_action_confirmation("trigger_full_crawl", {}, "执行完整公开信息爬取、飞书同步和公司指标刷新。")
    if confirmation:
        return confirmation
    try:
        result = web_app.run_crawl()
    except Exception as exc:
        return f"完整爬取执行异常：{_clean_search_text(exc, 240)}"
    status = "成功" if result.get("ok") else "失败"
    return (
        f"完整爬取{status}。\n"
        f"- 退出码：{result.get('returnCode')}\n"
        f"- 耗时：{result.get('durationMs', '未知')} ms\n"
        f"- stdout：{_clean_search_text(result.get('stdout') or '', 1500)}\n"
        f"- stderr：{_clean_search_text(result.get('stderr') or '', 1500)}"
    )

@tool
def trigger_report_generation() -> str:
    """触发本地周报生成任务。
    当用户明确要求生成战略内参周报、重新生成周报或输出 Word 周报时使用。它会调用 Web 层生成流程，生成 docx 并同步生成音频摘要。
    """
    import web_app

    confirmation = _require_action_confirmation("trigger_report_generation", {}, "生成正式 Word 周报并同步音频摘要。")
    if confirmation:
        return confirmation
    try:
        result = web_app.run_report_generation()
    except Exception as exc:
        return f"执行周报生成异常：{_clean_search_text(exc, 240)}"
    status = "成功" if result.get("ok") else "失败"
    outputs = result.get("status", {}).get("outputs", [])
    latest = outputs[0].get("name") if outputs else "未找到输出文件"
    return (
        f"周报生成{status}。\n"
        f"- 最新文件：{latest}\n"
        f"- 退出码：{result.get('returnCode')}\n"
        f"- 耗时：{result.get('durationMs', '未知')} ms\n"
        f"- 音频：{json.dumps(result.get('audio'), ensure_ascii=False)[:800]}\n"
        f"- stdout：{_clean_search_text(result.get('stdout') or '', 1200)}\n"
        f"- stderr：{_clean_search_text(result.get('stderr') or '', 1200)}"
    )


@tool
def trigger_carrier_performance_report_generation() -> str:
    """触发运营商业绩摘要 Word 报告生成。
    当用户明确要求生成运营商业绩摘要、业绩对标摘要或运营商报告时使用。它会生成 docx 并同步生成音频摘要。
    """
    import web_app

    confirmation = _require_action_confirmation(
        "trigger_carrier_performance_report_generation",
        {},
        "生成运营商业绩摘要 Word 报告并同步音频摘要。",
    )
    if confirmation:
        return confirmation
    try:
        result = web_app.run_carrier_performance_generation()
    except Exception as exc:
        return f"执行业绩摘要生成异常：{_clean_search_text(exc, 240)}"
    status = "成功" if result.get("ok") else "失败"
    outputs = [item for item in result.get("status", {}).get("outputs", []) if item.get("reportType") == "carrier-performance"]
    latest = outputs[0].get("name") if outputs else "未找到业绩摘要输出文件"
    return (
        f"运营商业绩摘要生成{status}。\n"
        f"- 最新文件：{latest}\n"
        f"- 退出码：{result.get('returnCode')}\n"
        f"- 耗时：{result.get('durationMs', '未知')} ms\n"
        f"- 音频：{json.dumps(result.get('audio'), ensure_ascii=False)[:800]}\n"
        f"- stdout：{_clean_search_text(result.get('stdout') or '', 1200)}\n"
        f"- stderr：{_clean_search_text(result.get('stderr') or '', 1200)}"
    )


@tool
def list_report_outputs(limit: int = 0) -> str:
    """列出当前可下载的正式 Word 输出文件。
    当用户询问输出文件、周报在哪里、有哪些 Word、最新文件、下载对象或报告产物时使用。
    """
    import web_app

    try:
        status = web_app.build_status()
    except Exception as exc:
        return f"读取输出文件失败：{_clean_search_text(exc, 200)}"
    outputs = status.get("outputs") or []
    if not outputs:
        return "当前没有可用输出文件。"
    lines = ["当前可用输出文件："]
    refs = []
    links = []
    visible_outputs = outputs[: max(1, int(limit))] if int(limit or 0) > 0 else outputs
    for index, item in enumerate(visible_outputs, 1):
        name = item.get("name") or item.get("path") or f"output-{index}"
        report_type = item.get("reportType") or "unknown"
        mtime = item.get("mtimeText") or item.get("mtime") or ""
        path = item.get("path") or item.get("path_str") or ""
        url = f"/outputs/{path}" if path else ""
        audio = item.get("audio", {}).get("exists")
        lines.append(f"{index}. {name}；类型：{report_type}；更新时间：{mtime}；音频：{'有' if audio else '无'}；路径：{path}")
        if url:
            link = {"label": name, "url": url}
            links.append(link)
            refs.append({"index": index, "source": name, "links": [link]})
    meta = {"type": "meta", "sources": [item.get("name") for item in visible_outputs], "links": links, "references": refs}
    return "\n".join(lines) + f"\n<metadata>{json.dumps(meta, ensure_ascii=False)}</metadata>"


@tool
def get_crawl_settings_summary() -> str:
    """读取当前爬取设置摘要。
    当用户询问当前爬取范围、启用哪些行、覆盖多少主体/字段、设置内容或数据内容配置时使用。只读取摘要，不修改设置。
    """
    import web_app

    try:
        settings = web_app.build_settings_payload()
    except Exception as exc:
        return f"读取爬取设置失败：{_clean_search_text(exc, 200)}"
    summary = settings.get("summary") or {}
    rows = settings.get("rows") or []
    enabled = [row for row in rows if row.get("enabled")]
    preview = []
    for row in enabled:
        entities = row.get("entities") or []
        fields = row.get("fields") or []
        preview.append(
            f"- 第 {row.get('row')} 行：主体 {len(entities)} 个，字段 {len(fields)} 个，目标链接 {len(row.get('sourceUrls') or [])} 个"
        )
    return (
        "当前爬取设置摘要：\n"
        f"- 启用行：{summary.get('enabledRows')} / {summary.get('totalRows')}\n"
        f"- 已选主体：{summary.get('selectedEntities')}\n"
        f"- 已选字段：{summary.get('selectedFields')}\n"
        f"- 配置来源：飞书主表\n"
        + "\n".join(preview)
    )

def _read_webpage_text(url: str) -> str:
    from bs4 import BeautifulSoup
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,text/plain;q=0.9,*/*;q=0.1'})
        with urlopen_with_local_proxy_fallback(req, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(12_000_000)
        is_pdf = re.search(r"application/pdf", content_type, re.IGNORECASE) or urlparse(url).path.lower().endswith(".pdf") or raw[:4] == b"%PDF"
        if is_pdf:
            try:
                from pypdf import PdfReader

                reader = PdfReader(BytesIO(raw))
                pages = []
                for page in reader.pages[:12]:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        pages.append(page_text.strip())
                text = re.sub(r"\s+", " ", "\n".join(pages)).strip()
                if len(text) < 80:
                    return "PDF读取失败：该 PDF 未抽取到足够文本，可能是扫描件或加密文件。"
                return text[:12000]
            except Exception as exc:
                return f"PDF读取失败：{_clean_search_text(exc, 200)}。"
        if not re.search(r"text/html|text/plain|application/xhtml\+xml", content_type, re.IGNORECASE):
            return f"网页读取跳过：该链接返回 {content_type or '非文本内容'}，请使用搜索摘要或官方 PDF/公告页面。"
        if b"\x00" in raw[:2048]:
            return "网页读取跳过：该链接返回二进制内容，无法作为正文展示。"
        html = raw.decode("utf-8", errors="ignore")
        if not re.search(r"<html|<body|<article|<p[\s>]", html, re.IGNORECASE):
            text_probe = " ".join(html.split())
            if _looks_like_blocked_or_encoded_text(text_probe):
                return "网页读取失败：该链接返回反爬验证或加密内容，无法作为正文展示。"
            if len(text_probe) > 200 and not re.fullmatch(r"[A-Za-z0-9+/=\s]+", text_probe[:2000]):
                return text_probe[:8000]
            return "网页读取失败：该链接没有返回可解析正文。"
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if _looks_like_blocked_or_encoded_text(text):
            return "网页读取失败：该链接返回反爬验证或加密内容，无法作为正文展示。"
        if len(text) < 80:
            return "网页读取失败：该链接正文过短或需要浏览器验证。"
        return text[:10000]
    except Exception as e:
        return f"读取网页 {url} 失败: {str(e)}"


@tool
def read_webpage(url: str) -> str:
    """访问并读取指定 URL 的纯文本内容。
    当用户提供一个网页链接，并要求你阅读、总结或提取其中的信息时，使用此工具。
    对 PDF 财报或公告链接会尝试抽取 PDF 文本；对反爬、二进制或浏览器验证页面会返回失败原因。
    """
    return _read_webpage_text(url)


def _decode_chart_spec_payload(chart_spec: Any) -> dict[str, Any]:
    payload: Any = chart_spec
    for _ in range(3):
        if isinstance(payload, str):
            raw = payload.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            payload = json.loads(raw)
            continue
        if isinstance(payload, dict) and "chart_spec" in payload and not {"x", "series"}.issubset(payload.keys()):
            payload = payload.get("chart_spec")
            continue
        break
    if not isinstance(payload, dict):
        raise ValueError("chart_spec 必须是 JSON 对象。")
    return _normalize_chart_spec_payload(payload)


def _normalize_chart_spec_payload(spec: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(spec)
    series = []
    for item in normalized.get("series") or []:
        if not isinstance(item, dict):
            continue
        series_item = dict(item)
        if "data" not in series_item and "values" in series_item:
            series_item["data"] = series_item.get("values")
        series.append(series_item)
    normalized["series"] = series
    return normalized


@tool
def render_python_chart(chart_spec: str) -> str:
    """用 Python/Matplotlib 生成中文可正常渲染的 PNG 图表。
    当用户要求画图或数据适合可视化时，在完成数据检索和核验后调用；可按分析目的调用多次生成互补图表。
    参数必须是 JSON 字符串，包含 type、title、unit、x、series；series 每项使用 data 数组（values 也兼容），气泡图可额外提供 sizes。type 支持 line、bar、grouped_bar、horizontal_bar、stacked_bar、area、stacked_area、pie、donut、scatter、bubble、radar、heatmap、histogram、box、combo。请勿提供 notes 或图表底部的解释性文字。
    """
    try:
        spec = _decode_chart_spec_payload(chart_spec)
    except Exception as exc:
        return (
            f"Python 图表生成失败：chart_spec 不是可用 JSON，原因：{_clean_search_text(exc, 160)}。"
            "请修正参数后重新调用。"
        )
    try:
        result = render_chart(spec)
    except Exception as exc:
        return (
            f"Python 图表生成失败：{_clean_search_text(exc, 200)}。"
            "请修正为包含 x 和 series.data 的 JSON 后重新调用。"
        )
    title = _clean_search_text(spec.get("title") or "Python 图表", 120)
    return (
        f"Python 图表已生成：\n\n![{title}]({result['url']})\n\n"
        f"图表文件：{result['path']}\n"
        f"中文字体：{result['font']}"
    )


@tool
def render_quarterly_metric_chart(
    subject: str,
    metric_key: str = "revenue",
    category: str = "",
    chart_type: str = "line",
) -> str:
    """从已选择季度指标库读取某主体某指标的完整可用时间序列并直接生成 PNG 图表。
    用户要求季度/半年度趋势图时直接调用本工具；它会返回真实 PNG，不要误称无法生成图片。
    不需要先手工拼 chart_spec。
    subject 例如 AWS、中国移动、Google Cloud；metric_key 例如 revenue、cloud_revenue、capital_expenditures。
    """
    subject = _clean_search_text(subject, 100)
    metric_key = _clean_search_text(metric_key or "revenue", 100)
    category = _clean_search_text(category, 100)
    chart_type = _clean_search_text(chart_type or "line", 30)
    if chart_type not in {"line", "bar", "area"}:
        chart_type = "line"
    csv_path = _selected_quarterly_metrics_path()
    if csv_path is None:
        return "季度指标图生成失败：当前未选择可用的季度/半年度指标数据库。"

    rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("subject") or "").strip() != subject:
                continue
            if (row.get("metric_key") or "").strip() != metric_key:
                continue
            if category and (row.get("category") or "").strip() not in {"", category}:
                continue
            value = _parse_metric_number(row.get("official_value") or row.get("value"))
            if value is None or row.get("verification_status") == "source_gap_confirmed":
                continue
            rows.append({**row, "_numeric_value": value})
    rows.sort(key=lambda row: _period_sort_key_for_forecast(row.get("period") or ""))
    if not rows:
        return f"季度指标图生成失败：数据库中没有 {subject} / {metric_key} 的可用数值序列。"

    unit = (rows[-1].get("official_unit") or rows[-1].get("unit") or "").strip()
    metric_zh = (rows[-1].get("metric_zh") or metric_key).strip()
    periods = [(row.get("period") or "").strip() for row in rows]
    values = [float(row["_numeric_value"]) for row in rows]
    title = f"{subject} {metric_zh}趋势（{periods[0]}–{periods[-1]}）"
    result = render_chart(
        {
            "type": chart_type,
            "title": title,
            "unit": unit,
            "x": periods,
            "series": [{"name": metric_zh, "data": values}],
        }
    )
    source = csv_path.relative_to(ROOT).as_posix()
    conflicts = [
        (row.get("period") or "").strip()
        for row in rows
        if row.get("verification_status") == "official_conflict"
    ]
    metadata = {
        "type": "meta",
        "sources": [source],
        "links": [{"label": source, "url": f"/references/{source}"}],
        "references": [
            {
                "index": 1,
                "source": source,
                "links": [{"label": source, "url": f"/references/{source}"}],
            }
        ],
    }
    conflict_note = (
        f"\n官方口径冲突期间：{', '.join(conflicts)}；图中采用 official_value。"
        if conflicts
        else ""
    )
    return (
        f"完整时间序列图已生成：{subject} / {metric_key}，"
        f"{len(rows)} 个数据点，{periods[0]} 至 {periods[-1]}，单位 {unit}。"
        f"{conflict_note}\n\n![{title}]({result['url']})\n\n"
        f"图表文件：{result['path']}\n"
        f"<metadata>{json.dumps(metadata, ensure_ascii=False)}</metadata>"
    )


def _parse_metric_number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(",", "").replace("%", "").replace("−", "-")
    text = re.sub(r"[^\d.\-]", "", text)
    if text in {"", "-", ".", "-."}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _period_sort_key_for_forecast(period: str) -> tuple[int, int]:
    text = str(period or "").strip().upper()
    match = re.match(r"Q([1-4])\s+(\d{4})$", text)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.match(r"FY(\d{4})\s+Q([1-4])$", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.match(r"H([12])\s+(\d{4})$", text)
    if match:
        return int(match.group(2)), int(match.group(1))
    return 9999, 9


def _next_quarter_label(period: str, steps: int = 1) -> str:
    fiscal_style = bool(re.match(r"FY\d{4}\s+Q[1-4]$", str(period or "").strip().upper()))
    year, quarter = _period_sort_key_for_forecast(period)
    for _ in range(steps):
        quarter += 1
        if quarter > 4:
            quarter = 1
            year += 1
    if fiscal_style:
        return f"FY{year} Q{quarter}"
    return f"Q{quarter} {year}"


def _next_half_year_label(period: str, steps: int = 1) -> str:
    year, half = _period_sort_key_for_forecast(period)
    for _ in range(steps):
        half += 1
        if half > 2:
            half = 1
            year += 1
    return f"H{half} {year}"


def _hw_additive_forecast(values: list[float], horizon: int, season_length: int = 4) -> tuple[list[float], str, float | None]:
    if len(values) < season_length * 2:
        return _seasonal_naive_forecast(values, horizon, season_length), "seasonal_naive_insufficient_history", None
    best: tuple[float, list[float], tuple[float, float, float]] | None = None
    alphas = [0.2, 0.4, 0.6, 0.8]
    betas = [0.05, 0.15, 0.30]
    gammas = [0.05, 0.15, 0.30]
    initial_level = sum(values[:season_length]) / season_length
    second_level = sum(values[season_length:season_length * 2]) / season_length
    initial_trend = (second_level - initial_level) / season_length
    seasonals = [values[i] - initial_level for i in range(season_length)]
    for alpha in alphas:
        for beta in betas:
            for gamma in gammas:
                level = initial_level
                trend = initial_trend
                seasonal = seasonals[:]
                fitted: list[float] = []
                errors: list[float] = []
                ok = True
                for i, actual in enumerate(values):
                    if i >= season_length:
                        forecast = level + trend + seasonal[i % season_length]
                        fitted.append(forecast)
                        errors.append(actual - forecast)
                    prev_level = level
                    try:
                        level = alpha * (actual - seasonal[i % season_length]) + (1 - alpha) * (level + trend)
                        trend = beta * (level - prev_level) + (1 - beta) * trend
                        seasonal[i % season_length] = gamma * (actual - level) + (1 - gamma) * seasonal[i % season_length]
                    except Exception:
                        ok = False
                        break
                    if not all(math.isfinite(item) for item in [level, trend, seasonal[i % season_length]]):
                        ok = False
                        break
                if not ok or not errors:
                    continue
                rmse = math.sqrt(sum(err * err for err in errors) / len(errors))
                future = [level + step * trend + seasonal[(len(values) + step - 1) % season_length] for step in range(1, horizon + 1)]
                if best is None or rmse < best[0]:
                    best = (rmse, future, (alpha, beta, gamma))
    if best is None:
        return _seasonal_naive_forecast(values, horizon, season_length), "seasonal_naive_fit_failed", None
    rmse, future, params = best
    method = f"holt_winters_additive_grid_search(alpha={params[0]}, beta={params[1]}, gamma={params[2]}, season_length={season_length})"
    return future, method, rmse


def _seasonal_naive_forecast(values: list[float], horizon: int, season_length: int = 4) -> list[float]:
    if not values:
        return []
    if len(values) < season_length:
        return [values[-1]] * horizon
    return [values[-season_length + ((step - 1) % season_length)] for step in range(1, horizon + 1)]


def _selected_quarterly_metrics_path() -> Path | None:
    selected = _selected_dataset_ids()
    candidates: list[tuple[str, float, Path]] = []
    root = ROOT / "agent_knowledge"
    if not root.exists():
        return None
    for folder in root.glob("quarterly_competitor_metrics_*"):
        if not folder.is_dir():
            continue
        csv_path = folder / "quarterly_metrics.csv"
        if not csv_path.exists():
            continue
        dataset_id = folder.name
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            dataset_id = str(manifest.get("id") or dataset_id)
            visibility = str(manifest.get("visibility") or "").strip().lower()
            updated_at = str(manifest.get("updated_at") or "").strip()
        except Exception:
            visibility = ""
            updated_at = ""
        if visibility in {"hidden", "superseded", "archived"}:
            continue
        if selected is not None and dataset_id not in selected and folder.name not in selected:
            continue
        candidates.append((updated_at, csv_path.stat().st_mtime, csv_path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


@tool
def forecast_quarterly_metric(
    forecast_spec: str = "",
    subject: str = "",
    metric_key: str = "revenue",
    horizon: int = 4,
    category: str = "",
) -> str:
    """用已选择的季度/半年度指标数据库做趋势预测。
    当用户要求“预测未来”“趋势预测”“forecast”“未来4个季度”等时使用。
    优先传结构化参数 subject、metric_key、horizon、category；也兼容 forecast_spec JSON 字符串。季度数据会优先使用 official_value；official_conflict 采用 official_value，source_gap 行不参与预测。
    """
    raw = str(forecast_spec or "").strip()
    spec: dict[str, Any] = {}
    if raw:
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            spec = json.loads(raw)
        except Exception:
            spec = {}
    subject = _clean_search_text(spec.get("subject") or subject, 80)
    metric_key = _clean_search_text(spec.get("metric_key") or metric_key or "revenue", 80)
    category = _clean_search_text(spec.get("category") or category, 80)
    horizon = max(1, int(spec.get("horizon") or horizon or 4))
    if not subject:
        return "预测失败：缺少 subject。请指定主体，例如 AWS、中国移动、Microsoft Azure / Intelligent Cloud。"
    csv_path = _selected_quarterly_metrics_path()
    if csv_path is None:
        return "预测失败：当前未选择可用的 quarterly_competitor_metrics 数据库。请在数据库按钮中选择 5 年季度/半年度数据包。"
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("subject") != subject or row.get("metric_key") != metric_key:
                continue
            if category and row.get("category") and row.get("category") != category:
                continue
            if row.get("grain") not in {"quarter", "half_year"}:
                continue
            if row.get("verification_status") == "source_gap_confirmed":
                continue
            value = _parse_metric_number(row.get("official_value") or row.get("value"))
            if value is None:
                continue
            rows.append({**row, "_numeric_value": value})
    rows.sort(key=lambda row: _period_sort_key_for_forecast(row.get("period") or ""))
    grain_counts = collections.Counter(row.get("grain") or "quarter" for row in rows)
    grain = grain_counts.most_common(1)[0][0] if grain_counts else "quarter"
    rows = [row for row in rows if (row.get("grain") or "quarter") == grain]
    sample_label = "半年度" if grain == "half_year" else "季度"
    season_length = 2 if grain == "half_year" else 4
    if len(rows) < 8:
        return f"预测失败：{subject} {metric_key} 可用{sample_label}样本只有 {len(rows)} 个，少于 8 个，不适合做趋势预测。"
    periods = [row["period"] for row in rows]
    values = [float(row["_numeric_value"]) for row in rows]
    forecasts, method, rmse = _hw_additive_forecast(values, horizon, season_length)
    backtest = rolling_backtest(values, season_length, _hw_additive_forecast)
    residual_proxy = rmse if rmse is not None else (statistics.pstdev(values[-8:]) if len(values) >= 8 else 0.0)
    if grain == "half_year":
        future_periods = [_next_half_year_label(periods[-1], step) for step in range(1, horizon + 1)]
    else:
        future_periods = [_next_quarter_label(periods[-1], step) for step in range(1, horizon + 1)]
    unit = rows[-1].get("official_unit") or rows[-1].get("unit") or ""
    metric_zh = rows[-1].get("metric_zh") or metric_key
    table_lines = [
        "| 预测期 | 预测值 | 低位区间 | 高位区间 |",
        "|---|---:|---:|---:|",
    ]
    for period, forecast in zip(future_periods, forecasts):
        low = forecast - residual_proxy
        high = forecast + residual_proxy
        table_lines.append(f"| {period} | {forecast:,.0f} | {low:,.0f} | {high:,.0f} |")
    history_tail = [
        {"period": period, "value": value}
        for period, value in zip(periods, values)
    ]
    chart_spec = {
        "type": "line",
        "title": f"{subject} {metric_zh} 历史与预测",
        "unit": unit,
        "x": periods + future_periods,
        "series": [
            {"name": "历史", "data": values + [None] * horizon},
            {"name": "预测", "data": [None] * len(values) + [round(item, 3) for item in forecasts]},
        ],
    }
    try:
        chart_result = render_chart(chart_spec)
        chart_md = f"![{chart_spec['title']}]({chart_result['url']})\n图表文件：{chart_result['path']}"
    except Exception as exc:
        chart_md = f"图表生成失败：{_clean_search_text(exc, 160)}"
    source = csv_path.relative_to(ROOT).as_posix()
    payload = {
        "type": "meta",
        "sources": [source],
        "links": [{"label": source, "url": f"/references/{source}"}],
        "references": [{"index": 1, "source": source, "links": [{"label": source, "url": f"/references/{source}"}]}],
        "forecastAudit": {
            "subject": subject,
            "metric_key": metric_key,
            "horizon": horizon,
            "sample_count": len(values),
            "grain": grain,
            "model": method,
            "rmse": rmse,
            "backtest": backtest,
        },
    }
    if backtest.get("ok"):
        scores = backtest.get("scores") or {}
        baseline_text = (
            f"- 回测窗口：{backtest.get('windows')} 个；"
            f"Holt-Winters RMSE={scores.get('holt_winters', {}).get('rmse', 0):,.3f}，"
            f"naive RMSE={scores.get('naive', {}).get('rmse', 0):,.3f}，"
            f"seasonal naive RMSE={scores.get('seasonal_naive', {}).get('rmse', 0):,.3f}；"
            f"RMSE 最优：{backtest.get('best_baseline')}。\n"
        )
    else:
        baseline_text = f"- 回测：{backtest.get('reason') or '未执行'}\n"
    return (
        f"趋势预测结果：{subject} {metric_zh}（{metric_key}）\n"
        f"- 数据来源：{source}\n"
        f"- 历史样本：{len(values)} 个{sample_label}，{periods[0]} 至 {periods[-1]}\n"
        f"- 数值口径：优先 official_value；official_conflict 采用官方值；source_gap 不参与拟合。\n"
        f"- 模型：{method}\n"
        f"- 回测误差代理 RMSE：{rmse:,.3f}\n"
        f"{baseline_text}" if rmse is not None else
        f"趋势预测结果：{subject} {metric_zh}（{metric_key}）\n"
        f"- 数据来源：{source}\n"
        f"- 历史样本：{len(values)} 个{sample_label}，{periods[0]} 至 {periods[-1]}\n"
        f"- 数值口径：优先 official_value；official_conflict 采用官方值；source_gap 不参与拟合。\n"
        f"- 模型：{method}\n"
        f"{baseline_text}"
    ) + (
        "\n".join(table_lines)
        + "\n\n"
        + chart_md
        + "\n\n"
        + "重要说明：这是基于历史序列的机械趋势预测，不是投资建议；未纳入管理层指引、宏观变量、政策、竞争和一次性项目影响。\n"
        + f"最近历史样本：{json.dumps(history_tail, ensure_ascii=False)}"
        + f"\n<metadata>{json.dumps(payload, ensure_ascii=False)}</metadata>"
    )

@tool
def get_system_status() -> str:
    """获取系统运行状态和爬虫统计数据（包括最近爬取的成功数、失败数等）。
    当你需要了解系统的健康状况或数据收集的全景概览时，使用此工具。
    """
    import web_app
    try:
        status = web_app.build_status()
        return f"系统状态快照：\n{json.dumps(status, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"获取系统状态失败: {str(e)}"


@tool
def search_agent_memory(query: str, limit: int = 5) -> str:
    """搜索小竞AI本地长期运行记忆。
    当用户询问偏好、之前确认过的生产规则、长期约束、上下文管理策略或历史工作流时使用。
    记忆只作为辅助上下文，不代替当前选择数据库和实际工具结果。
    """
    rows = search_memories(query, limit=limit)
    if not rows:
        return "未找到相关长期记忆。"
    lines = ["小竞AI长期记忆命中："]
    for index, item in enumerate(rows, 1):
        lines.append(
            f"[记忆 {index}] {item.get('content')}\n"
            f"- kind: {item.get('kind')}\n"
            f"- tags: {'、'.join(item.get('tags') or []) or '无'}\n"
            f"- entities: {'、'.join(item.get('entities') or []) or '无'}\n"
            f"- score: {item.get('score', 'n/a')}; importance: {item.get('importance')}; confidence: {item.get('confidence')}\n"
            f"- date: {item.get('created_date')}; access_count: {item.get('access_count', 0)}"
        )
    return "\n\n".join(lines)


def _chat_message_content(message: dict[str, Any], limit: int = 1200) -> str:
    return _clean_search_text(message.get("content") or message.get("text") or "", limit)


def _parse_chat_history_time(value: Any, *, end_of_period: bool = False) -> datetime | None:
    """Parse tool-supplied or stored ISO timestamps in the server's timezone."""
    text = str(value or "").strip()
    if not text:
        return None
    date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text))
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if date_only and end_of_period:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    local_tz = datetime.now().astimezone().tzinfo
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(local_tz)


def _chat_history_rows(
    query: str = "",
    limit: int = 5,
    context_window: int = 2,
    start_time: str = "",
    end_time: str = "",
    role: str = "all",
    thread_id: str = "",
) -> list[dict[str, Any]]:
    if not CHAT_THREADS_PATH.exists():
        return []
    try:
        data = json.loads(CHAT_THREADS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    threads = data.get("threads") if isinstance(data, dict) else data
    if not isinstance(threads, list):
        return []
    clean_query = _clean_search_text(query, 300)
    query_terms = {term for term in re.split(r"[\s,，。；;:：!?！？、]+", clean_query.lower()) if term}
    profile_query = _is_user_profile_query(clean_query)
    start_at = _parse_chat_history_time(start_time)
    end_at = _parse_chat_history_time(end_time, end_of_period=True)
    if str(start_time or "").strip() and start_at is None:
        return []
    if str(end_time or "").strip() and end_at is None:
        return []
    if start_at and end_at and start_at > end_at:
        start_at, end_at = end_at, start_at
    requested_role = str(role or "all").strip().lower()
    if requested_role in {"ai", "model", "assistant", "助手"}:
        requested_role = "assistant"
    elif requested_role in {"user", "human", "用户", "我"}:
        requested_role = "user"
    else:
        requested_role = "all"
    requested_thread_id = _clean_search_text(thread_id, 120)
    rows: list[dict[str, Any]] = []
    active_thread_id = ACTIVE_CHAT_THREAD_ID.get()
    current_request = _clean_search_text(CURRENT_USER_REQUEST.get(), 1200)
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        current_thread_id = str(thread.get("id") or "")
        if requested_thread_id and current_thread_id != requested_thread_id:
            continue
        messages = thread.get("messages") if isinstance(thread.get("messages"), list) else []
        thread_title = _clean_search_text(thread.get("title") or "", 120)
        thread_created_at = _parse_chat_history_time(thread.get("createdAt"))
        thread_updated_at = _parse_chat_history_time(thread.get("updatedAt"))
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            content = _chat_message_content(message, 1200)
            if not content:
                continue
            if (
                current_thread_id == active_thread_id
                and index >= max(0, len(messages) - 2)
                and (
                    content == current_request
                    or content.startswith("正在分析请求")
                )
            ):
                continue
            role = str(message.get("role") or "").lower()
            role = "assistant" if role in {"assistant", "ai", "model"} else "user"
            if requested_role != "all" and role != requested_role:
                continue
            if profile_query and role != "user":
                continue
            message_created_at = _parse_chat_history_time(message.get("createdAt"))
            message_completed_at = _parse_chat_history_time(message.get("completedAt"))
            precise_time = message_created_at or message_completed_at
            if start_at or end_at:
                if precise_time:
                    if start_at and precise_time < start_at:
                        continue
                    if end_at and precise_time > end_at:
                        continue
                else:
                    # Legacy messages have no per-message timestamp. Keep them
                    # only when their saved thread interval overlaps the query,
                    # and report the lower precision instead of inventing a time.
                    interval_start = thread_created_at or thread_updated_at
                    interval_end = thread_updated_at or thread_created_at
                    if start_at and interval_end and interval_end < start_at:
                        continue
                    if end_at and interval_start and interval_start > end_at:
                        continue
            haystack = f"{thread_title} {content}".lower()
            score = 1 if not clean_query else 0
            if clean_query and clean_query.lower() in haystack:
                score += 20
            score += sum(2 for term in query_terms if term in haystack)
            if profile_query:
                low_content = content.strip().lower()
                if low_content in {"你好", "您好", "hi", "hello", "hey", "ok", "好的", "谢谢"}:
                    continue
                score += 6
                if score > 0 and thread_title:
                    score += 2
            if score <= 0:
                continue
            start = max(0, index - max(0, int(context_window or 0)))
            end = min(len(messages), index + max(0, int(context_window or 0)) + 1)
            context_messages = []
            for context_index in range(start, end):
                context_message = messages[context_index]
                if not isinstance(context_message, dict):
                    continue
                context_role_raw = str(context_message.get("role") or "").lower()
                if profile_query and context_role_raw != "user":
                    continue
                context_content = _chat_message_content(context_message, 1200)
                if not context_content:
                    continue
                if profile_query and context_content.strip().lower() in {"你好", "您好", "hi", "hello", "hey", "ok", "好的", "谢谢"}:
                    continue
                context_messages.append(
                    {
                        "message_index": context_index + 1,
                        "role": context_message.get("role") or "unknown",
                        "content": context_content,
                        "created_at": context_message.get("createdAt") or "",
                        "is_match": context_index == index,
                    }
                )
            rows.append(
                {
                    "score": score,
                    "thread_id": thread.get("id") or "",
                    "thread_title": thread_title or "未命名对话",
                    "thread_created_at": thread.get("createdAt") or "",
                    "thread_updated_at": thread.get("updatedAt") or "",
                    "message_index": index + 1,
                    "role": role,
                    "content": content,
                    "created_at": message.get("createdAt") or "",
                    "completed_at": message.get("completedAt") or "",
                    "time_precision": "message" if precise_time else "thread_range",
                    "context_messages": context_messages,
                }
            )
    rows.sort(key=lambda item: (int(item["score"]), str(item.get("thread_updated_at") or "")), reverse=True)
    return rows[: max(1, int(limit or 5))]


@tool
def search_chat_history(
    query: str = "",
    start_time: str = "",
    end_time: str = "",
    role: str = "all",
    thread_id: str = "",
    limit: int = 5,
    context_window: int = 2,
) -> str:
    """按内容和时间搜索小竞AI已保存的全部历史聊天线程。
    当当前问题依赖过去对话、用户说“之前/当时/那次/上周/某日/某个时刻”、指代不清但可能需要回看，
    或需要核对用户或AI过去说过什么时，可自主调用。query 可留空以纯时间检索；start_time/end_time
    使用 ISO 8601（如 2026-07-22 或 2026-07-22T17:00:00+08:00）；role 可选 all/user/assistant；
    thread_id 可限定单个会话；context_window 控制命中前后消息数量。不要为普通当前事实查询无故调用。
    该工具只读，不等同于长期记忆；回答时要说明命中的线程、角色、消息序号和时间精度。
    """
    rows = _chat_history_rows(
        query=query,
        limit=limit,
        context_window=max(0, int(context_window or 0)),
        start_time=start_time,
        end_time=end_time,
        role=role,
        thread_id=thread_id,
    )
    if not rows:
        requested_range = ""
        if start_time or end_time:
            requested_range = f"（时间范围：{start_time or '最早'} 至 {end_time or '现在'}）"
        return f"未在已保存的历史聊天线程中找到匹配消息{requested_range}。"
    lines = ["历史聊天记录命中："]
    for index, item in enumerate(rows, 1):
        role = "AI" if str(item.get("role") or "").lower() == "assistant" else "用户"
        if item.get("time_precision") == "message":
            time_text = item.get("created_at") or item.get("completed_at") or "未记录"
            precision_text = "逐条消息准确时间"
        else:
            time_text = f"{item.get('thread_created_at') or '未知'} 至 {item.get('thread_updated_at') or '未知'}"
            precision_text = "旧记录仅有会话时间范围"
        lines.append(
            f"[聊天命中 {index}] thread={item.get('thread_title')} ({item.get('thread_id')}); "
            f"message_index={item.get('message_index')}; role={role}; time={time_text}; precision={precision_text}\n"
            f"{item.get('content')}"
        )
        context_messages = item.get("context_messages") if isinstance(item.get("context_messages"), list) else []
        if context_messages:
            lines.append("邻近对话上下文：")
            for context_message in context_messages:
                context_role = "AI" if str(context_message.get("role") or "").lower() == "assistant" else "用户"
                marker = " ← 命中" if context_message.get("is_match") else ""
                lines.append(
                    f"- message_index={context_message.get('message_index')}; role={context_role}{marker}: "
                    f"{context_message.get('content')}"
                )
    return "\n\n".join(lines)


@tool
def remember_agent_memory(content: str, kind: str = "semantic", tags: str = "", importance: float = 0.7, confidence: float = 0.85) -> str:
    """写入一条小竞AI长期运行记忆。
    只在用户明确要求“记住/以后都/默认/规则/偏好”，或你确认这是跨会话可复用的生产规则时使用。
    不要写入 API key、个人隐私、未验证数据值或完整聊天历史。
    """
    tag_list = [item.strip() for item in re.split(r"[,，;；\s]+", tags or "") if item.strip()]
    try:
        item = add_memory(
            content,
            kind=kind or "semantic",
            tags=tag_list,
            source="agent-tool",
            importance=importance,
            confidence=confidence,
        )
    except Exception as exc:
        return f"写入长期记忆失败：{exc}"
    return (
        f"已写入长期记忆：{item['id']}，kind={item.get('kind')}，"
        f"importance={item.get('importance')}，confidence={item.get('confidence')}，date={item['created_date']}。"
    )


@tool
def list_agent_memory(limit: int = 10) -> str:
    """列出最近的小竞AI长期运行记忆，用于审计 agent 记住了什么。"""
    rows = load_memories(limit=max(1, int(limit or 10)))
    if not rows:
        return "当前没有长期记忆。"
    return "\n\n".join(
        f"[记忆 {index}] {item.get('content')}\n"
        f"- kind: {item.get('kind')}\n"
        f"- tags: {'、'.join(item.get('tags') or []) or '无'}\n"
        f"- entities: {'、'.join(item.get('entities') or []) or '无'}\n"
        f"- status: {item.get('status')}; importance: {item.get('importance')}; confidence: {item.get('confidence')}\n"
        f"- date: {item.get('created_date')}; access_count: {item.get('access_count', 0)}"
        for index, item in enumerate(rows, 1)
    )


@tool
def list_database_lineage() -> str:
    """列出本轮已选择数据库的版本、血缘、manifest、文件数量和指纹。
    当用户问数据库来源、版本、是否过期、数据血缘、可审计性，或需要正式说明当前答案基于哪个数据包时使用。
    """
    rows = dataset_lineage(_effective_selected_dataset_ids())
    if not rows:
        return "当前未选择任何可见数据库，无法生成数据库血缘。"
    lines = ["本轮已选择数据库血缘："]
    for index, row in enumerate(rows, 1):
        lines.append(
            "\n".join(
                [
                    f"[数据库 {index}] {row.get('title') or row.get('id')}",
                    f"- id: {row.get('id')}",
                    f"- version: {row.get('version') or '未声明'}",
                    f"- built_at: {row.get('built_at') or row.get('updated_at') or '未声明'}",
                    f"- row_count: {row.get('row_count') or '未声明'}",
                    f"- verified_count: {row.get('verified_count') or '未声明'}",
                    f"- gap_count: {row.get('gap_count') or '未声明'}",
                    f"- manifest: {row.get('manifest_path') or '无'}",
                    f"- files: {row.get('file_count')} 个，fingerprint={row.get('fingerprint')}",
                    f"- quality: {row.get('quality') or '未说明'}",
                ]
            )
        )
    return "\n\n".join(lines)

def _thinking_model_name(model_name: str) -> str:
    return model_name


def _agent_model_name(thinking_enabled: bool = False) -> str:
    config = load_ai_config()
    model_name = config.get("model", "deepseek-v4")
    if thinking_enabled:
        return _thinking_model_name(str(model_name))
    return str(model_name)


def _agent_tools(allow_web_search: bool = True, user_message: str | None = None):
    all_tools = [
        read_agent_skill,
        list_local_datasets,
        list_crawl_runs,
        search_local_reports,
        read_local_reference,
        trigger_crawl,
        trigger_full_crawl,
        trigger_report_generation,
        trigger_carrier_performance_report_generation,
        list_report_outputs,
        get_crawl_settings_summary,
        render_python_chart,
        render_quarterly_metric_chart,
        forecast_quarterly_metric,
        get_system_status,
        search_agent_memory,
        search_chat_history,
        remember_agent_memory,
        list_agent_memory,
        list_database_lineage,
    ]
    # Tool descriptions, not keyword gates, tell the Agent when each capability
    # is useful. Side-effecting tools still enforce their own approval checks.
    tools = list(all_tools)
    if allow_web_search:
        tools[4:4] = [read_webpage]
    return tools


def get_agent(
    thinking_enabled: bool = False,
    allow_web_search: bool = True,
    runtime_context: dict[str, Any] | None = None,
    user_message: str | None = None,
):
    config = load_ai_config()
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "")
    model_name = _agent_model_name(thinking_enabled=thinking_enabled)

    from network_utils import _available_proxy_urls
    proxies = _available_proxy_urls()
    if proxies and not os.environ.get("HTTP_PROXY"):
        os.environ["HTTP_PROXY"] = proxies[0]
        os.environ["HTTPS_PROXY"] = proxies[0]
        
    llm = ChatDeepSeek(
        model=model_name,
        api_key=api_key,
        api_base=base_url,
        extra_body=(
            dict(config.get("extra_parameters") or {})
            if thinking_enabled
            else deepseek_nonthinking_parameters(config.get("extra_parameters") or {})
        ),
        temperature=0.1,
        disable_streaming=True,
        max_retries=3,
        max_tokens=4096,
    )
    
    tools = _agent_tools(allow_web_search=allow_web_search, user_message=user_message)

    runtime_context = runtime_context or {}
    runtime_lines = [
        f"- 本轮消息准确发送时间: {runtime_context.get('current_time') or 'unknown'}",
        f"- 本轮时区: {runtime_context.get('timezone') or 'unknown'} ({runtime_context.get('utc_offset') or ''})",
        f"- 请求 IP: {runtime_context.get('visible_ip') or runtime_context.get('client_ip') or 'unknown'}",
        f"- X-Forwarded-For: {runtime_context.get('forwarded_for') or 'none'}",
        f"- 位置推断: {runtime_context.get('location_hint') or 'unknown'}",
    ]
    runtime_context_text = "\n".join(runtime_lines)
    web_search_instruction = (
        "联网搜索已开启；search_local_reports 会同时返回本地和联网资料。"
        "由你判断查询方式与次数，并比较两边证据，指出冲突、未命中和时效差异。\n"
        if allow_web_search
        else ""
    )

    system_message = (
        "你是中国移动战略部公开信息监测系统的小竞AI。理解用户意图，自主选择可用的 "
        "Agent Skill、数据库和工具，直接给出清晰、专业的简体中文答案。\n"
        "当前运行上下文：\n"
        f"{runtime_context_text}\n"
        "上述时间由后端在每条消息到达时重新计算；理解“今天、现在、最近、上一季度”等相对时间时使用它。\n"
        "根据工具描述自主规划、检索和回答。"
        f"{web_search_instruction}"
        "只依据本轮可见数据和真实工具结果；证据不足、冲突或不可比时如实说明。"
        "工具结果含有“[来源 N: ...]”或 references 元数据时，凡是据此写出的数据、事实和结论，"
        "都要在对应句子或表格单元格中紧跟原来源编号，例如 [1] 或 [1,2]；"
        "沿用工具给出的编号，不得自造编号，也不能只在回答末尾罗列来源而省略文内引用。"
        "回答当前问题本身，不套用上一轮的结构；需要图表或其他产物时使用相应工具。"
        "输出会在前端按 Markdown 渲染；只使用前端能直接呈现的标准标题、段落、列表、加粗、链接和表格，"
        "不要使用单星号斜体或用星号包裹整段文字。尽量减少 emoji、图标和装饰符号，除非用户明确要求，否则标题直接使用文字。"
        "有副作用的操作仍须遵循工具自身的审批要求。"
    )
    
    return create_react_agent(llm, tools, prompt=system_message)


def _selected_skill_summaries(skill_ids: list[str] | None) -> list[dict[str, str]]:
    requested = [re.sub(r"[^A-Za-z0-9_.-]", "", str(item or "")) for item in (skill_ids or [])]
    requested = [item for item in requested if item]
    if not requested:
        return []
    by_id = {item["id"]: item for item in available_agent_skills()}
    rows = []
    for skill_id in requested:
        item = by_id.get(skill_id)
        if not item:
            continue
        rows.append({
            "id": skill_id,
            "title": str(item.get("title") or skill_id),
            "summary": str(item.get("description") or item.get("summary") or ""),
        })
    return rows


def _selected_dataset_summaries(dataset_ids: set[str]) -> list[dict[str, str]]:
    effective_ids = effective_dataset_ids(dataset_ids)
    if not effective_ids:
        return []
    rows = []
    for item in list_knowledge_datasets(dataset_ids=effective_ids):
        rows.append({
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or item.get("id") or ""),
            "folder": str(item.get("folder") or ""),
            "summary": str(item.get("summary") or item.get("scope") or ""),
        })
    return rows


def _context_tool_content(title: str, rows: list[dict[str, str]], id_key: str = "id") -> str:
    if not rows:
        return f"{title}：无。"
    lines = [f"{title}：{len(rows)} 项"]
    for index, row in enumerate(rows, 1):
        name = row.get("title") or row.get(id_key) or f"项目 {index}"
        row_id = row.get(id_key) or ""
        summary = row.get("summary") or row.get("folder") or ""
        suffix = f"（{row_id}）" if row_id and row_id != name else ""
        lines.append(f"{index}. {name}{suffix}" + (f"\n   {summary}" if summary else ""))
    return "\n".join(lines)


def _stream_agent_events(agent: Any, inputs: dict[str, Any]):
    try:
        # LangGraph requires an integer recursion_limit and otherwise defaults
        # to a small fixed step count. sys.maxsize removes the product-level
        # tool/step quota while transport errors and user cancellation can
        # still end a genuinely failed request.
        return agent.stream(
            inputs,
            stream_mode="messages",
            config={"recursion_limit": sys.maxsize},
        )
    except TypeError:
        return agent.stream(inputs, stream_mode="messages")


def _format_conversation_history(history: list[dict[str, Any]] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for item in history[-8:]:
        role = "AI" if str(item.get("role") or "").lower() == "assistant" else "用户"
        content = _clean_search_text(item.get("content") or "", 1800)
        if content:
            created_at = _clean_search_text(item.get("createdAt") or "", 48)
            completed_at = _clean_search_text(item.get("completedAt") or "", 48)
            time_parts = []
            if created_at:
                time_parts.append(f"发送时间 {created_at}")
            if role == "AI" and completed_at:
                time_parts.append(f"完成时间 {completed_at}")
            time_text = f" [{'; '.join(time_parts)}]" if time_parts else ""
            lines.append(f"{role}{time_text}: {content}")
    if not lines:
        return ""
    return "同一聊天线程的最近对话如下，用于理解代词、继续追问和上一轮结论；若与本轮用户新指令冲突，以本轮新指令为准。\n" + "\n".join(lines)


def _tool_process_text(tool_name: str) -> str:
    labels = {
        "read_agent_skill": "我读取相关 Agent Skill 的完整指令。",
        "list_local_datasets": "我读取本轮已选数据库列表。",
        "search_agent_memory": "我查找长期记忆中是否有相关规则。",
        "search_local_reports": "我读取已选数据库并检索摘要片段。",
        "read_local_reference": "我读取命中的数据库原文，确认数据口径和来源。",
        "web_search": "我联网检索公开来源。",
        "read_webpage": "我读取网页原文核验细节。",
        "render_python_chart": "我基于已核验数据生成图表。",
        "render_quarterly_metric_chart": "我读取完整季度序列并直接生成趋势图。",
        "forecast_quarterly_metric": "我调用趋势预测工具，使用历史数据生成预测。",
        "get_system_status": "我读取系统当前状态。",
        "search_chat_history": "我搜索已保存的历史聊天记录。",
        "list_report_outputs": "我查看已有报告输出。",
        "list_crawl_runs": "我读取爬虫运行日志。",
    }
    return labels.get(tool_name, f"我调用 {tool_name or '工具'} 获取依据。")


def _is_plain_conversational_query(message: str) -> bool:
    text = re.sub(r"\s+", "", str(message or "")).strip().lower()
    if not text:
        return False
    domain_terms = (
        "收入",
        "营收",
        "趋势",
        "预测",
        "数据",
        "图表",
        "来源",
        "报告",
        "周报",
        "铁塔",
        "移动",
        "联通",
        "电信",
        "云厂商",
        "宏观",
        "政策",
        "aws",
        "azure",
        "hkt",
    )
    if any(term in text for term in domain_terms):
        return False
    greetings = {"你好", "您好", "hi", "hello", "hey", "在吗", "谢谢", "好的", "ok", "嗯", "嗨"}
    identity_questions = {"你是", "你是谁", "你叫什么", "你能做什么", "介绍一下你自己", "自我介绍"}
    return text in greetings or text in identity_questions or (len(text) <= 12 and any(item in text for item in identity_questions))


def _is_user_profile_query(message: str) -> bool:
    text = re.sub(r"\s+", "", str(message or "")).strip().lower()
    if not text:
        return False
    profile_markers = (
        "我是谁",
        "我的身份",
        "了解我",
        "你了解我",
        "认识我",
        "知道我",
        "我对什么感兴趣",
        "我感兴趣",
        "感兴趣",
        "兴趣",
        "我的兴趣",
        "我的偏好",
        "我偏好",
        "偏好",
        "我关注什么",
        "我关心什么",
        "关注方向",
        "我常问什么",
        "我之前问过什么",
        "我的画像",
        "用户画像",
    )
    return any(marker in text for marker in profile_markers)


def _message_token_usage(message: AIMessage | AIMessageChunk) -> dict[str, int]:
    """Normalize provider token metadata without depending on one gateway shape."""
    candidates: list[dict[str, Any]] = []
    usage_metadata = getattr(message, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        candidates.append(usage_metadata)
    for container_name in ("response_metadata", "additional_kwargs"):
        container = getattr(message, container_name, None)
        if not isinstance(container, dict):
            continue
        for key in ("token_usage", "usage", "usage_metadata"):
            value = container.get(key)
            if isinstance(value, dict):
                candidates.append(value)

    for usage in candidates:
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
        if total_tokens or input_tokens or output_tokens:
            return {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": total_tokens or input_tokens + output_tokens,
            }
    return {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}


def stream_agent(
    message: str,
    force_web_search: bool = False,
    selected_skill_ids: list[str] | None = None,
    selected_dataset_ids: list[str] | None = None,
    thinking_enabled: bool = False,
    approved_action_ids: list[str] | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    emit_context_events: bool = True,
    loaded_skill_ids: list[str] | None = None,
    runtime_context: dict[str, Any] | None = None,
    active_thread_id: str = "",
) -> Generator[dict[str, Any], None, None]:
    _reset_web_search_indexes()
    original_user_message = message
    plain_conversation = _is_plain_conversational_query(message)
    try:
        captured_memory = None if plain_conversation else auto_capture_user_memory(message)
    except Exception:
        captured_memory = None
    recalled_memory = "" if plain_conversation else memory_context(message, limit=5)
    requested_dataset_set = {
        re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]", "", str(item or ""))
        for item in (selected_dataset_ids or [])
        if str(item or "").strip()
    }
    selected_dataset_set = resolve_dataset_ids(requested_dataset_set) or set()
    selected_skill_set = {
        re.sub(r"[^A-Za-z0-9_.-]", "", str(item or ""))
        for item in (selected_skill_ids or [])
        if str(item or "").strip()
    }
    dataset_token = SELECTED_DATASET_IDS.set(selected_dataset_set)
    skill_token = SELECTED_SKILL_IDS.set(selected_skill_set)
    approved_token = APPROVED_ACTION_IDS.set({str(item) for item in (approved_action_ids or []) if str(item).strip()})
    thread_token = ACTIVE_CHAT_THREAD_ID.set(
        re.sub(r"[^A-Za-z0-9_.:-]", "", str(active_thread_id or ""))[:160]
    )
    request_token = CURRENT_USER_REQUEST.set(_clean_search_text(original_user_message, 1200))
    web_search_token = WEB_SEARCH_AVAILABLE.set(force_web_search)
    recorder = AgentRunRecorder(
        message=message,
        selected_dataset_ids=sorted(selected_dataset_set),
        selected_skill_ids=[str(item) for item in (selected_skill_ids or [])],
        web_search_enabled=force_web_search,
        thinking_enabled=thinking_enabled,
        approved_action_ids=approved_action_ids or [],
    )
    try:
        agent = get_agent(
            thinking_enabled=thinking_enabled,
            allow_web_search=force_web_search,
            runtime_context=runtime_context,
            user_message=original_user_message,
        )
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        try:
            agent = get_agent(
                thinking_enabled=thinking_enabled,
                allow_web_search=force_web_search,
                user_message=original_user_message,
            )
        except TypeError as fallback_exc:
            if "unexpected keyword" not in str(fallback_exc):
                raise
            agent = get_agent(thinking_enabled=thinking_enabled, allow_web_search=force_web_search)
    thinking_step = 0

    def thinking_event(text: str) -> dict[str, Any]:
        nonlocal thinking_step
        thinking_step += 1
        return {"type": "thinking_status", "text": f"{thinking_step}. {text}"}

    if captured_memory:
        event = {"type": "process", "step": "长期记忆", "text": f"已记录一条运行记忆：{captured_memory.get('id')}。"}
        recorder.observe(event)
        yield event
    if recalled_memory:
        event = {"type": "process", "step": "长期记忆", "text": "已召回本地长期运行记忆作为辅助上下文。"}
        recorder.observe(event)
        yield event

    skill_context = _selected_skill_context(selected_skill_ids, original_user_message)
    # Selected skills and datasets are injected as model context below. They are not
    # rendered as fake tool calls; the UI should only show tools the Agent chose.
    if recalled_memory:
        message = f"{recalled_memory}\n\n用户问题：{message}"
    history_context = _format_conversation_history(conversation_history)
    if history_context:
        message = f"{history_context}\n\n本轮用户问题：{message}"
    if skill_context:
        message = (
            "前端已选择的 Agent Skill：\n"
            f"{skill_context}\n\n"
            f"用户问题：{message}"
        )
    if selected_dataset_set:
        message = (
            f"前端已选择的本地数据库 id：{', '.join(sorted(selected_dataset_set))}\n\n"
            f"用户问题：{message}"
        )
    inputs = {"messages": [("user", message)]}
    
    tool_calls_acc = {}
    pending_tool_calls: dict[str, dict[str, str]] = {}
    emitted_process_tools: set[str] = set()
    token_usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    def finalize_pending_tool_calls(reason: str) -> Generator[dict[str, Any], None, None]:
        """Close every visible tool card even when the Agent loop stops early."""
        for tool_call_id, pending in list(pending_tool_calls.items()):
            tc_data = tool_calls_acc.get(tool_call_id) or pending
            event = {
                "type": "tool_call_result",
                "id": tool_call_id,
                "name": str(tc_data.get("name") or pending.get("name") or "工具"),
                "args": str(tc_data.get("args") or ""),
                "content": f"工具调用已停止：{reason}",
            }
            pending_tool_calls.pop(tool_call_id, None)
            recorder.observe(event)
            yield event

    def chunk_reasoning_text(chunk: AIMessage | AIMessageChunk) -> str:
        """Read provider reasoning fields without mixing them into the final answer."""
        containers = [
            getattr(chunk, "additional_kwargs", None),
            getattr(chunk, "response_metadata", None),
        ]
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in ("reasoning_content", "reasoning", "thinking_content"):
                value = container.get(key)
                if isinstance(value, str) and value:
                    return value

        content = getattr(chunk, "content", None)
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").lower()
                if block_type not in {"reasoning", "reasoning_content", "thinking"}:
                    continue
                value = block.get("text") or block.get("content") or block.get("reasoning_content")
                if isinstance(value, str) and value:
                    parts.append(value)
            return "".join(parts)
        return ""

    def visible_reasoning_text(chunk: AIMessage | AIMessageChunk) -> str:
        """Return the model-provided reasoning without content classification or rewriting."""
        return chunk_reasoning_text(chunk).strip()

    def replay_validated_text(text: str, *, delay_seconds: float = 0.022) -> Generator[str, None, None]:
        """Replay validated full model text as ordered SSE-sized chunks."""
        if not text:
            return
        if len(text) <= 18:
            yield text
            return
        cursor = 0
        while cursor < len(text):
            remaining = len(text) - cursor
            size = min(24, max(8, math.ceil(remaining / 12)))
            end = min(len(text), cursor + size)
            punctuation = re.search(r"[，。；：！？、\n]", text[cursor:end + 8])
            if punctuation and punctuation.end() >= 6:
                end = cursor + punctuation.end()
            yield text[cursor:end]
            cursor = end
            if cursor < len(text):
                time.sleep(delay_seconds)

    def follow_up_event() -> dict[str, Any]:
        suggestions, suggestion_usage, source = _ensure_ai_follow_up_suggestions(
            original_user_message,
            "".join(recorder.answer_parts),
            thinking_enabled=thinking_enabled,
        )
        for key in token_usage:
            token_usage[key] += suggestion_usage[key]
        event = {
            "type": "suggestions",
            "items": suggestions,
            "generatedByAI": source != "emergency",
            "source": source,
        }
        recorder.record["suggestions"] = suggestions
        recorder.record["suggestions_source"] = source
        recorder.record["suggestions_generated_by_ai"] = source != "emergency"
        return event

    priority_token = set_internal_ai_priority("interactive")
    status_event = {
        "type": "status",
        "text": "已进入完整 Agent 流程，正在分析问题并规划工具调用。",
    }
    recorder.observe(status_event)
    yield status_event
    try:
        events = _stream_agent_events(agent, inputs)
        for chunk, metadata in events:
            if isinstance(chunk, (AIMessage, AIMessageChunk)):
                full_message = isinstance(chunk, AIMessage) and not isinstance(chunk, AIMessageChunk)
                chunk_usage = _message_token_usage(chunk)
                for key in token_usage:
                    token_usage[key] += chunk_usage[key]
                reasoning_text = visible_reasoning_text(chunk)
                if reasoning_text:
                    reasoning_parts = (
                        replay_validated_text(reasoning_text)
                        if isinstance(chunk, AIMessage) and not isinstance(chunk, AIMessageChunk)
                        else [reasoning_text]
                    )
                    for reasoning_part in reasoning_parts:
                        event = {"type": "reasoning", "text": reasoning_part}
                        recorder.observe(event)
                        yield event
                if chunk.content and isinstance(chunk.content, str):
                    content_parts = (
                        replay_validated_text(chunk.content, delay_seconds=0.018)
                        if isinstance(chunk, AIMessage) and not isinstance(chunk, AIMessageChunk)
                        else [chunk.content]
                    )
                    for content_part in content_parts:
                        event = {"type": "delta", "text": content_part}
                        recorder.observe(event)
                        yield event
                tool_call_chunks = getattr(chunk, "tool_call_chunks", None) or []
                if not tool_call_chunks:
                    for index, tool_call in enumerate(getattr(chunk, "tool_calls", None) or []):
                        if not isinstance(tool_call, dict):
                            continue
                        args = tool_call.get("args", {})
                        tool_call_chunks.append({
                            "index": index,
                            "id": tool_call.get("id"),
                            "name": tool_call.get("name"),
                            "args": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
                        })
                if tool_call_chunks:
                    for tc in tool_call_chunks:
                        index = tc.get("index")
                        tc_id = tc.get("id")
                        
                        if tc_id:
                            current_key = tc_id
                            tool_calls_acc[index] = current_key
                            tool_calls_acc[current_key] = {"name": tc.get("name"), "args": "", "id": tc_id}
                            if thinking_enabled:
                                yield thinking_event(f"准备调用工具：{tc.get('name') or '工具'}。")
                            process_tool_name = tc.get("name") or "工具"
                            pending_tool_calls[tc_id] = {
                                "id": str(tc_id),
                                "name": str(process_tool_name),
                            }
                            process_text = ""
                            if process_tool_name not in emitted_process_tools:
                                emitted_process_tools.add(process_tool_name)
                                process_text = _tool_process_text(process_tool_name)
                            event = {
                                "type": "tool_call_start",
                                "id": tc_id,
                                "name": process_tool_name,
                                "processText": process_text,
                            }
                            recorder.observe(event)
                            yield event
                        else:
                            current_key = tool_calls_acc.get(index)
                            
                        if current_key and tc.get("args"):
                            tool_calls_acc[current_key]["args"] += tc["args"]
            elif isinstance(chunk, ToolMessage):
                args_str = ""
                tc_data = tool_calls_acc.get(chunk.tool_call_id)
                if tc_data:
                    args_str = tc_data.get("args", "")
                pending_tool_calls.pop(str(chunk.tool_call_id or ""), None)
                
                content = chunk.content
                raw_tool_content = str(content or "")

                # Parse metadata if present
                meta_event = None
                if "<metadata>" in content:
                    match = re.search(r"<metadata>(.*?)</metadata>", content)
                    if match:
                        try:
                            meta_event = json.loads(match.group(1))
                        except Exception:
                            pass
                        content = content.replace(match.group(0), "")
                
                # Attempt to parse json from string for better formatting if it's a known JSON string
                if content.startswith("系统状态快照：\n"):
                    try:
                        # Extract the JSON part and format it
                        json_str = content[len("系统状态快照：\n"):]
                        parsed = json.loads(json_str)
                        content = "系统状态快照：\n" + json.dumps(parsed, ensure_ascii=False, indent=2)
                    except:
                        pass
                elif content.startswith("{") or content.startswith("["):
                    try:
                        parsed = json.loads(content)
                        content = json.dumps(parsed, ensure_ascii=False, indent=2)
                    except:
                        pass

                if meta_event:
                    recorder.observe(meta_event)
                    yield meta_event
                    
                tool_name = str((tc_data or {}).get("name") or "工具")
                display_content = _display_tool_result(tool_name, content.strip(), meta_event)
                if thinking_enabled:
                    yield thinking_event(f"工具返回结果：{tool_name} 已完成，开始把结果纳入来源核验和回答组织。")
                event = {
                    "type": "tool_call_result",
                    "id": chunk.tool_call_id,
                    "name": tool_name,
                    "args": args_str,
                    "content": display_content,
                }
                recorder.observe(event)
                yield event
        if pending_tool_calls:
            yield from finalize_pending_tool_calls(
                "Agent 事件流已经结束，但没有收到此工具的返回结果。"
            )
        suggestions_event = follow_up_event()
        recorder.observe(suggestions_event)
        yield suggestions_event
        summary = recorder.finish()
        yield {
            "type": "run_summary",
            "runId": summary["run_id"],
            "durationMs": summary["duration_ms"],
            "toolCount": len(summary.get("tool_calls") or []),
            "status": summary.get("status"),
            "usage": {
                "inputTokens": token_usage["inputTokens"] or int(summary.get("input_tokens_estimate") or 0),
                "outputTokens": token_usage["outputTokens"] or int(summary.get("answer_tokens_estimate") or 0),
                "totalTokens": token_usage["totalTokens"] or (
                    int(summary.get("input_tokens_estimate") or 0)
                    + int(summary.get("answer_tokens_estimate") or 0)
                ),
                "estimated": token_usage["totalTokens"] <= 0,
            },
        }
        yield {"type": "done"}
    except Exception as e:
        error_text = str(e)
        if pending_tool_calls:
            yield from finalize_pending_tool_calls(
                "Agent 执行已经结束，但没有收到此工具的返回结果。"
            )
        event = {"type": "error", "text": f"Agent 调用失败: {error_text}"}
        recorder.observe(event)
        yield event
        recorder.finish()
        yield {"type": "done"}
    finally:
        reset_internal_ai_priority(priority_token)
        SELECTED_DATASET_IDS.reset(dataset_token)
        SELECTED_SKILL_IDS.reset(skill_token)
        APPROVED_ACTION_IDS.reset(approved_token)
        ACTIVE_CHAT_THREAD_ID.reset(thread_token)
        CURRENT_USER_REQUEST.reset(request_token)
        WEB_SEARCH_AVAILABLE.reset(web_search_token)
