from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
import ssl
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as clock_time, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import strategic_briefing
from local_competitor_keywords import (
    canonical_competitors_for_text,
    mandatory_search_groups,
    priority_for,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "strategy_briefing"
STATE_PATH = DATA_DIR / "news_digest_state.json"
LATEST_PATH = DATA_DIR / "news_discovery_latest.json"
CRAWL_INDEX_PATH = ROOT / "agent_knowledge" / "crawl_run_logs" / "index.json"
HKT = ZoneInfo("Asia/Hong_Kong")

SCAN_TIMES = tuple(
    clock_time(int(item.split(":", 1)[0]), int(item.split(":", 1)[1]))
    for item in os.environ.get("CMHK_NEWS_DIGEST_SCAN_TIMES", "09:00,14:00").split(",")
    if re.fullmatch(r"\s*\d{1,2}:\d{2}\s*", item)
)
POLL_SECONDS = max(30, int(os.environ.get("CMHK_NEWS_DIGEST_POLL_SECONDS", "60")))
CATCHUP_MINUTES = max(30, int(os.environ.get("CMHK_NEWS_DIGEST_CATCHUP_MINUTES", "120")))
RESULTS_PER_QUERY = max(10, int(os.environ.get("CMHK_NEWS_RESULTS_PER_QUERY", "30")))
PAGE_SIZE = min(10, max(5, int(os.environ.get("CMHK_NEWS_PAGE_SIZE", "8"))))
SEARCH_WORKERS = min(8, max(2, int(os.environ.get("CMHK_NEWS_SEARCH_WORKERS", "6"))))
LATE_INDEX_MIN_RESULTS = max(
    1,
    int(os.environ.get("CMHK_NEWS_LATE_INDEX_MIN_RESULTS", "3")),
)
AGENTIC_SEARCH_ENABLED = os.environ.get("CMHK_NEWS_AGENTIC_SEARCH", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
AGENTIC_EXPANSION_LIMIT = min(
    24,
    max(4, int(os.environ.get("CMHK_NEWS_AGENTIC_EXPANSION_QUERIES", "12"))),
)
AGENTIC_FOLLOWUP_LIMIT = min(
    12,
    max(2, int(os.environ.get("CMHK_NEWS_AGENTIC_FOLLOWUP_QUERIES", "6"))),
)
AGENTIC_AI_ATTEMPTS = min(
    3,
    max(1, int(os.environ.get("CMHK_NEWS_AGENTIC_AI_ATTEMPTS", "3"))),
)
AGENTIC_SEARCH_RESPONSE_FORMAT = strategic_briefing._strict_object_response_format(
    "strategic_news_agentic_search",
    {
        "sufficient": {"type": "boolean"},
        "assessment": {"type": "string"},
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "module": {"type": "string"},
                    "query": {"type": "string"},
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "intent": {"type": "string"},
                    "reason": {"type": "string"},
                    "lookback_days": {"type": "integer"},
                },
                "required": [
                    "module",
                    "query",
                    "keywords",
                    "intent",
                    "reason",
                    "lookback_days",
                ],
                "additionalProperties": False,
            },
        },
    },
)
LOCAL_MODULES = {"竞争对手", "政策/法规类", "香港本地新闻", "市场/产品类"}
LOCAL_TERMS = (
    "香港", "hong kong", "hkt", "pccw", "csl", "1o1o", "hkbn", "hgc",
    "smartone", "数码通", "數碼通", "3hk", "和记电讯", "和記電訊", "ofca",
    "通讯局", "通訊局", "北部都会区", "北部都會區", "数码港", "數碼港",
    "科学园", "科學園", "河套", "新田科技城", "大湾区", "大灣區",
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _clean_text(value: Any, limit: int = 500) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _card_text(value: Any, limit: int = 500) -> str:
    return _clean_text(value, limit).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _normal_title(title: str, source: str) -> str:
    clean = _clean_text(title, 240)
    if source:
        for separator in (" - ", " – ", " — "):
            suffix = separator + source
            if clean.lower().endswith(suffix.lower()):
                clean = clean[: -len(suffix)].strip()
                break
    return clean


def _term_matches(text: str, term: str) -> bool:
    term = _clean_text(term, 120).strip('"\' ')
    if not term:
        return False
    lowered = re.sub(r"\s*&\s*", " ", text.lower())
    pieces = [part.strip() for part in re.split(r"[/\\,，；;\n]+", term) if part.strip()]
    for piece in pieces or [term]:
        token = re.sub(r"\s*&\s*", " ", piece.lower()).strip()
        if not token:
            continue
        if re.fullmatch(r"[a-z0-9.+-]+", token):
            if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered):
                return True
        elif token in lowered:
            return True
    return False


def _parse_news_feed(
    raw: bytes,
    *,
    provider: str,
    module: str,
    keywords: list[str],
    base_query: str,
    start_at: datetime,
    end_at: datetime,
    canonical_competitor: str = "",
    search_origin: str = "",
    semantic_relevance: bool = False,
    agentic_intent: str = "",
    agentic_reason: str = "",
    retrieval_start_at: datetime | None = None,
    retrieval_end_at: datetime | None = None,
) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    output: list[dict[str, Any]] = []
    for item in root.findall("./channel/item")[:RESULTS_PER_QUERY]:
        source = _clean_text(item.findtext("source"), 100)
        if not source:
            for child in item:
                if child.tag.lower().endswith("source"):
                    source = _clean_text(child.text, 100)
                    break
        title = _normal_title(item.findtext("title") or "", source)
        snippet = _clean_text(item.findtext("description"), 360)
        link = _clean_text(item.findtext("link"), 1200)
        if provider == "bing" and "bing.com/news/apiclick" in link.lower():
            target = parse_qs(urlparse(link).query).get("url") or []
            if target:
                link = _clean_text(target[0], 1200)
        published_raw = _clean_text(item.findtext("pubDate"), 100)
        if not title or not link or not published_raw:
            continue
        try:
            published_at = parsedate_to_datetime(published_raw)
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=HKT)
            published_at = published_at.astimezone(HKT)
        except (TypeError, ValueError):
            continue
        if not (start_at <= published_at <= end_at):
            continue
        relevance_text = f"{title} {snippet}"
        searchable = f"{relevance_text} {source}"
        digest = hashlib.sha1(f"{title.lower()}|{source.lower()}".encode("utf-8")).hexdigest()[:10]
        lowered = searchable.lower()
        literal_keywords = [
            item for item in keywords if _term_matches(searchable, item)
        ][:5]
        literal_keyword_match = bool(literal_keywords)
        # Keep retrieval context separate from evidence found in the article.
        # A query term explains why a result was discovered, but must not be
        # presented to the reviewing Agent as a literal content match.  The
        # candidate is still forwarded unchanged, so this correction cannot
        # reduce recall (including Hong Kong-local semantic discoveries).
        query_keywords = list(dict.fromkeys(keywords))[:6]
        matched_keywords = literal_keywords
        candidate = {
            "news_id": f"NEWS-{published_at:%Y%m%d}-{digest}",
            "title": title,
            "url": link,
            "source": source or "公开新闻来源",
            "published_at": published_at.isoformat(timespec="seconds"),
            "search_date": end_at.astimezone(HKT).date().isoformat(),
            "search_window_start": start_at.astimezone(HKT).isoformat(
                timespec="seconds"
            ),
            "search_window_end": end_at.astimezone(HKT).isoformat(
                timespec="seconds"
            ),
            "retrieval_window_start": (
                retrieval_start_at or start_at
            ).astimezone(HKT).isoformat(timespec="seconds"),
            "retrieval_window_end": (
                retrieval_end_at or end_at
            ).astimezone(HKT).isoformat(timespec="seconds"),
            "retrieved_at": end_at.astimezone(HKT).isoformat(timespec="seconds"),
            "module": module,
            "keywords": matched_keywords,
            "query_keywords": query_keywords,
            "snippet": snippet,
            "is_hong_kong": bool(canonical_competitor)
            or any(term in lowered for term in LOCAL_TERMS),
            "query": base_query,
            "search_provider": provider,
            "search_origin": search_origin or "monitoring_sheet_keyword_search",
            "literal_keyword_match": literal_keyword_match,
        }
        if semantic_relevance:
            candidate["semantic_relevance"] = True
            candidate["agentic_intent"] = agentic_intent
            candidate["agentic_reason"] = agentic_reason
        if canonical_competitor:
            candidate["canonical_competitor"] = canonical_competitor
            candidate["search_origin"] = (
                search_origin or "mandatory_local_competitor"
            )
        output.append(candidate)
    return output


def _google_news_search(
    plan: dict[str, Any],
    start_at: datetime,
    end_at: datetime,
    *,
    admission_start_at: datetime | None = None,
    admission_end_at: datetime | None = None,
) -> list[dict[str, Any]]:
    retrieval_start_at = start_at
    retrieval_end_at = end_at
    admission_start_at = admission_start_at or start_at
    admission_end_at = admission_end_at or end_at
    base_query = _clean_text(plan.get("fallback_query") or plan.get("query"), 1400)
    module = _clean_text(plan.get("module"), 100) or "其他"
    keywords = [_clean_text(item, 120) for item in (plan.get("keywords") or []) if _clean_text(item, 120)]
    canonical_competitor = _clean_text(plan.get("canonical_competitor"), 120)
    search_origin = _clean_text(plan.get("search_origin"), 100)
    semantic_relevance = bool(plan.get("semantic_relevance"))
    agentic_intent = _clean_text(plan.get("agentic_intent"), 300)
    agentic_reason = _clean_text(plan.get("agentic_reason"), 300)
    if not base_query:
        return []
    if module in {"香港本地新闻", "政策/法规类"}:
        base_query = f"{base_query} (香港 OR \"Hong Kong\")"
    before_date = end_at.date() + timedelta(days=1)
    google_query = f"{base_query} after:{start_at.date().isoformat()} before:{before_date.isoformat()}"
    feeds = [
        (
            "bing",
            "https://www.bing.com/news/search?q="
            + quote_plus(base_query)
            + "&format=rss&mkt=zh-HK&qft=sortbydate%3d%221%22",
        ),
        (
            "google",
            "https://news.google.com/rss/search?q="
            + quote_plus(google_query)
            + "&hl=zh-HK&gl=HK&ceid=HK:zh-Hant",
        ),
    ]
    output: list[dict[str, Any]] = []
    successful_feeds = 0
    last_error: Exception | None = None
    for provider, feed_url in feeds:
        request = Request(
            feed_url,
            headers={"User-Agent": "Mozilla/5.0 CMHK-Strategic-News/1.0"},
        )
        try:
            try:
                raw = urlopen(request, timeout=25).read()
            except URLError as exc:
                if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                    raise
                raw = urlopen(
                    request,
                    timeout=25,
                    context=ssl._create_unverified_context(),
                ).read()
            output.extend(
                _parse_news_feed(
                    raw,
                    provider=provider,
                    module=module,
                    keywords=keywords,
                    base_query=base_query,
                    start_at=admission_start_at,
                    end_at=admission_end_at,
                    canonical_competitor=canonical_competitor,
                    search_origin=search_origin,
                    semantic_relevance=semantic_relevance,
                    agentic_intent=agentic_intent,
                    agentic_reason=agentic_reason,
                    retrieval_start_at=retrieval_start_at,
                    retrieval_end_at=retrieval_end_at,
                )
            )
            successful_feeds += 1
        except Exception as exc:
            last_error = exc
    if not successful_feeds and last_error is not None:
        raise last_error
    return output


def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in sorted(
        items,
        key=lambda row: (
            row.get("published_at") or "",
            bool(row.get("canonical_competitor")),
        ),
        reverse=True,
    ):
        key = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", _clean_text(item.get("title"), 300).lower())
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _tag_competitor_entities(item: dict[str, Any]) -> tuple[str, ...]:
    """Attach content-backed competitor identities without trusting broad queries."""
    existing = [
        _clean_text(value, 120)
        for value in (item.get("canonical_competitors") or [])
        if _clean_text(value, 120)
    ]
    primary = _clean_text(item.get("canonical_competitor"), 120)
    inferred = canonical_competitors_for_text(
        item.get("title"),
        item.get("snippet"),
    )
    entities = tuple(dict.fromkeys([primary, *existing, *inferred]))
    entities = tuple(entity for entity in entities if entity)
    if (
        not entities
        and "竞争对手" in _clean_text(item.get("module"), 100)
        and bool(item.get("literal_keyword_match"))
    ):
        monitored_terms = tuple(
            dict.fromkeys(
                _clean_text(value, 120)
                for value in (item.get("keywords") or [])
                if _clean_text(value, 120)
            )
        )
        if monitored_terms:
            item["monitored_competitor_terms"] = list(monitored_terms)
            return tuple(f"监测词:{term}" for term in monitored_terms)
    if not entities:
        return ()
    item["canonical_competitors"] = list(entities)
    if not primary:
        item["canonical_competitor"] = entities[0]
        item["canonical_competitor_source"] = "article_content_alias"
    return entities


def _competitor_priority(item: dict[str, Any]) -> int:
    entities = _tag_competitor_entities(item)
    if entities:
        return min(priority_for(entity) for entity in entities)
    return 2


def _select_discovery_results(
    items: list[dict[str, Any]],
    *,
    module_order: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Order candidates for review without silently truncating any topic."""
    ordered = sorted(
        items,
        key=lambda item: (
            _competitor_priority(item),
            module_order.get(str(item.get("module") or "其他"), 999),
            -datetime.fromisoformat(str(item["published_at"])).timestamp(),
        ),
    )
    competitor_items: list[dict[str, Any]] = []
    other_items: list[dict[str, Any]] = []
    competitor_counts: dict[str, int] = {}
    module_counts: dict[str, int] = {}
    search_origin_counts: dict[str, int] = {}
    for item in ordered:
        module = _clean_text(item.get("module"), 100) or "其他"
        origin = _clean_text(item.get("search_origin"), 100) or "未标注"
        module_counts[module] = module_counts.get(module, 0) + 1
        search_origin_counts[origin] = search_origin_counts.get(origin, 0) + 1
        entities = _tag_competitor_entities(item)
        if not entities:
            other_items.append(item)
            continue
        competitor_items.append(item)
        for entity in entities:
            competitor_counts[entity] = competitor_counts.get(entity, 0) + 1
    # The former global 120-item truncation made lower-volume competitors,
    # modules and monitoring keywords disappear before AI review. Pass every
    # date-valid, deduplicated candidate to the existing AI/deferred workflow
    # so overload is explicit and retryable instead of silent loss.
    selected = ordered
    return selected, {
        "candidate_count": len(items),
        "result_count": len(selected),
        "recognized_competitor_count": len(competitor_items),
        "recognized_competitor_dropped_count": 0,
        "non_competitor_kept_count": len(other_items),
        "pre_ai_dropped_count": 0,
        "full_recall_mode": True,
        "competitor_counts": competitor_counts,
        "module_counts": module_counts,
        "search_origin_counts": search_origin_counts,
    }


BENCHMARK_OPERATOR_QUERIES: tuple[tuple[str, ...], ...] = (
    ("Vodafone", "BT Group", "Deutsche Telekom", "Telefonica"),
    ("AT&T", "Verizon", "T-Mobile", "SK Telecom", "Singtel"),
    ("NTT Docomo", "KDDI", "Telstra", "Airtel", "SoftBank"),
    ("Hong Kong telecom", "Hong Kong spectrum", "Hong Kong mobile operator", "OFCA"),
)
PRIORITY_NEWS_QUERIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "政策监管",
        (
            "Hong Kong telecom regulation",
            "Hong Kong spectrum policy",
            "OFCA",
            "Hong Kong AI regulation",
            "telecom export control",
        ),
    ),
    (
        "宏观经济",
        (
            "Hong Kong economy",
            "Hong Kong GDP",
            "Hong Kong inflation",
            "Hong Kong interest rates",
            "China PPI telecom",
        ),
    ),
)

LOCAL_STRATEGIC_QUERY_PLANS: tuple[dict[str, Any], ...] = (
    {
        "module": "香港本地新闻",
        "query": (
            '香港 ("自动驾驶" OR "自動駕駛" OR "无人驾驶" OR "無人駕駛" '
            'OR "蘿蔔快跑" OR "萝卜快跑")'
        ),
        "keywords": [
            "香港",
            "自动驾驶",
            "自動駕駛",
            "无人驾驶",
            "無人駕駛",
            "蘿蔔快跑",
            "萝卜快跑",
        ],
        "agentic_intent": "香港智慧交通、自动驾驶测试及商业化进展",
    },
    {
        "module": "香港本地新闻",
        "query": (
            '香港 ("皇岗口岸" OR "皇崗口岸" OR "一地两检" OR "一地兩檢" '
            'OR "跨境基础设施" OR "跨境基建")'
        ),
        "keywords": [
            "香港",
            "皇岗口岸",
            "皇崗口岸",
            "一地两检",
            "一地兩檢",
            "跨境基础设施",
            "跨境基建",
        ],
        "agentic_intent": "香港跨境口岸、基础设施与深港融合变化",
    },
)


def _local_strategic_plans() -> list[dict[str, Any]]:
    return [
        {
            **plan,
            "fallback_query": plan["query"],
            "lookback_days": 7,
            "search_origin": "background_fixed_keywords",
            "semantic_relevance": True,
        }
        for plan in LOCAL_STRATEGIC_QUERY_PLANS
    ]


def _mandatory_competitor_plans() -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for group in mandatory_search_groups():
        names = tuple(group["terms"])
        query = " OR ".join(f'"{name}"' for name in names)
        plans.append(
            {
                "module": "竞争对手",
                "query": query,
                "fallback_query": query,
                "keywords": list(names),
                "canonical_competitor": group["canonical"],
                "search_origin": "mandatory_local_competitor",
            }
        )
    return plans


def _scheduled_crawl_plans(
    end_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn fixed-page discoveries into date-aware news-index searches."""
    try:
        from scheduled_crawl_news_bridge import load_pending_signals

        batch = load_pending_signals(
            strategic_briefing._load_state(),
            end_at,
        )
    except Exception as exc:
        return [], {
            "pending_signal_count": 0,
            "query_count": 0,
            "error": f"{type(exc).__name__}: {_clean_text(exc, 200)}",
        }
    signals = [
        signal
        for signal in (batch.get("signals") or [])
        if isinstance(signal, dict)
    ][: strategic_briefing.MAX_SCHEDULED_CRAWL_SIGNALS]
    plans: list[dict[str, Any]] = []
    for signal in signals:
        # The fixed-page row label is provenance, not evidence that every child
        # link belongs to that operator. Search the discovered headline itself
        # so a broad aggregator cannot prefix unrelated news with the row label
        # and create false competitor matches.
        headline = _clean_text(signal.get("title"), 240)
        query = headline or _clean_text(signal.get("query"), 300)
        signal_id = _clean_text(signal.get("signal_id"), 80)
        if not query or not signal_id:
            continue
        keywords = [
            _clean_text(keyword, 100)
            for keyword in (signal.get("keywords") or [])
            if _clean_text(keyword, 100)
        ]
        monitor_object = _clean_text(signal.get("monitor_object"), 200)
        headline_entities = canonical_competitors_for_text(headline)
        canonical = (
            headline_entities[0]
            if headline_entities
            else strategic_briefing._scheduled_signal_canonical_competitor(
                monitor_object
            )
        )
        plan = {
            "module": _clean_text(signal.get("monitor_category"), 100)
            or "定时页面监控",
            "query": query,
            "fallback_query": query,
            "keywords": keywords or [monitor_object],
            "lookback_days": 3,
            "search_origin": "scheduled_crawl_reference",
            "semantic_relevance": True,
            "agentic_intent": "核验定时页面爬虫发现的新文章线索",
            "agentic_reason": "固定来源页面出现新链接，使用带发布日期的新闻索引确认事件",
            "scheduled_crawl_signal_id": signal_id,
            "scheduled_crawl_run_id": _clean_text(
                signal.get("crawl_run_id"), 100
            ),
            "scheduled_crawl_config_row": _clean_text(
                signal.get("config_row"), 20
            ),
            "scheduled_crawl_parent_url": _clean_text(
                signal.get("parent_url"), 1600
            ),
            "scheduled_crawl_target_url": _clean_text(
                signal.get("target_url"), 1600
            ),
        }
        if canonical:
            plan["canonical_competitor"] = canonical
        plans.append(plan)
    return plans, {
        "pending_signal_count": len(signals),
        "query_count": len(plans),
        "expired_signal_count": len(batch.get("expired_signal_ids") or []),
        "error": "",
    }


def _normalized_query(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean_text(value, 1400)).strip().casefold()


def _sanitize_agentic_query(value: Any) -> str:
    query = " ".join(str(value or "").split())
    # Agentic plans complement fixed-source monitoring and should search the
    # open news index. Models sometimes emit malformed exclusions such as
    # ``-site:smar tone.com.hk``; remove the whole operator (including a split
    # domain tail) instead of sending a broken query to every provider.
    query = re.sub(
        r"(?i)(?<!\S)-?site\s*:\s*\S+"
        r"(?:\s+[a-z0-9][a-z0-9.-]*\.[a-z]{2,})?",
        " ",
        query,
    )
    return re.sub(r"\s+", " ", query).strip()


# A gap query must keep its subject mandatory. "A OR B (intent)" lets a search
# engine satisfy the whole expression with a bare "A", which returns unrelated
# news; "(A OR B) (intent)" keeps the subject group ANDed with the intents.
_MANDATORY_SUBJECT_QUERY_RE = re.compile(r"^\([^()]+\)\s*\([^()]+\)$")
_DEFAULT_GAP_INTENTS = ("资费", "促销", "5G", "网络建设", "合作", "业绩")


def _mandatory_subject_query(aliases: list[str], intents: list[str]) -> str:
    names = [
        _clean_text(alias, 40).strip('"')
        for alias in aliases
        if _clean_text(alias, 40).strip('"')
    ][:3]
    terms = [
        _clean_text(intent, 40).strip('"')
        for intent in intents
        if _clean_text(intent, 40).strip('"')
    ][:6]
    if not names or not terms:
        return ""
    return f"({' OR '.join(names)}) ({' OR '.join(terms)})"


def _deterministic_gap_query(aliases: list[str]) -> str:
    return _mandatory_subject_query(aliases, list(_DEFAULT_GAP_INTENTS))


def _has_unguarded_top_level_or(query: str) -> bool:
    """True when an OR sits outside every bracket, making the subject optional."""
    outside = re.sub(r"\([^()]*\)", " ", query)
    return bool(re.search(r"\bOR\b", outside, flags=re.I))


def _compact_agentic_query(query: str, keywords: list[str] | None = None) -> str:
    """Rewrite planner queries into a mandatory subject group plus intent ORs."""
    query = _sanitize_agentic_query(query)
    if not query:
        return query
    tokens = [
        token.strip('"()')
        for token in re.split(r"\s+", query)
        if token.strip('"()') and token.upper() != "OR"
    ]
    if _MANDATORY_SUBJECT_QUERY_RE.match(query) and len(query) <= 180:
        return query
    # A short all-AND query is already precise enough for a search engine.
    if len(tokens) <= 6 and not _has_unguarded_top_level_or(query):
        return query
    aliases = [
        _clean_text(keyword, 40).strip('"')
        for keyword in (keywords or [])
        if _clean_text(keyword, 40).strip('"')
    ][:3]
    if not aliases:
        aliases = tokens[:2]
    alias_keys = {alias.casefold() for alias in aliases}
    intents: list[str] = []
    trailing_group = re.search(r"\(([^()]+)\)\s*$", query)
    if trailing_group:
        candidates = [
            term.strip()
            for term in re.split(r"\bOR\b", trailing_group.group(1), flags=re.I)
        ]
    else:
        candidates = tokens
    for token in candidates:
        token = token.strip('"()')
        if not token or token.casefold() in alias_keys:
            continue
        if any(
            _term_matches(token, alias) or _term_matches(alias, token)
            for alias in aliases
        ):
            continue
        if token not in intents:
            intents.append(token)
        if len(intents) >= 4:
            break
    compacted = _mandatory_subject_query(
        aliases, intents or list(_DEFAULT_GAP_INTENTS)
    )
    if not compacted:
        return query
    if len(compacted) > 180:
        compacted = _mandatory_subject_query(aliases, intents[:2] or list(_DEFAULT_GAP_INTENTS[:3]))
    return compacted[:180]


def _query_intent_terms(query: str) -> list[str]:
    trailing_group = re.search(r"\(([^()]+)\)\s*$", _clean_text(query, 300))
    if not trailing_group:
        return []
    return [
        term.strip().strip('"')
        for term in re.split(r"\bOR\b", trailing_group.group(1), flags=re.I)
        if term.strip().strip('"')
    ]


def _plan_subject_aliases(plan: dict[str, Any]) -> list[str]:
    aliases = [
        _clean_text(keyword, 40).strip('"')
        for keyword in (plan.get("keywords") or [])
        if _clean_text(keyword, 40).strip('"')
    ]
    canonical = _clean_text(plan.get("canonical_competitor"), 120)
    if canonical:
        for group in mandatory_search_groups():
            if str(group["canonical"]) == canonical:
                aliases = [*aliases, *[str(term) for term in group["terms"]]]
                break
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _simplified_for_matching(value: Any, limit: int = 800) -> str:
    """Planner queries are simplified Chinese; Hong Kong sources are traditional."""
    return strategic_briefing._to_simplified_chinese(value, limit)


def _grounding_term_matches(simplified_text: str, term: str) -> bool:
    return _term_matches(
        simplified_text, _simplified_for_matching(term, 120)
    ) or _term_matches(simplified_text, term)


def _agentic_result_is_grounded(plan: dict[str, Any], item: dict[str, Any]) -> bool:
    """Keep every plausible Agentic hit; only drop copy that answers nothing.

    Discovery prefers extra noise over a miss. Query bracketing already stops
    a bare alias from satisfying the whole search. This gate only removes
    articles that share none of the planner's terms, are not a recognised
    competitor, and were not admitted as semantic coverage. AI review still
    decides what reaches the human sheet.
    """
    if not _clean_text(plan.get("search_origin"), 100).startswith("agentic_"):
        return True
    text = _simplified_for_matching(
        " ".join(
            _clean_text(value, 400)
            for value in (item.get("title"), item.get("snippet"))
            if _clean_text(value, 400)
        )
    )
    if not text:
        return False
    if item.get("semantic_relevance"):
        return True
    terms = list(
        dict.fromkeys(
            [
                *_plan_subject_aliases(plan),
                *_query_intent_terms(str(plan.get("query") or "")),
            ]
        )
    )
    if any(_grounding_term_matches(text, term) for term in terms):
        return True
    return bool(
        canonical_competitors_for_text(item.get("title"), item.get("snippet"))
    )


def _agentic_zero_result_retry_plan(plan: dict[str, Any]) -> dict[str, Any] | None:
    origin = _clean_text(plan.get("search_origin"), 100)
    if not origin.startswith("agentic_"):
        return None
    canonical = _clean_text(plan.get("canonical_competitor"), 120)
    aliases = [
        _clean_text(keyword, 40)
        for keyword in (plan.get("keywords") or [])
        if _clean_text(keyword, 40)
    ]
    if canonical:
        for group in mandatory_search_groups():
            if str(group["canonical"]) == canonical:
                aliases = list(
                    dict.fromkeys(
                        [*aliases, *[str(term) for term in group["terms"]]]
                    )
                )[:3]
                break
    retry_query = _deterministic_gap_query(aliases) or _compact_agentic_query(
        str(plan.get("query") or ""),
        aliases,
    )
    original = _normalized_query(plan.get("fallback_query") or plan.get("query"))
    if not retry_query or _normalized_query(retry_query) == original:
        compacted = _compact_agentic_query(str(plan.get("query") or ""), aliases)
        if not compacted or _normalized_query(compacted) == original:
            return None
        retry_query = compacted
    return {
        **plan,
        "query": retry_query,
        "fallback_query": retry_query,
        "agentic_zero_result_retry": True,
    }


def _coverage_digest(
    items: list[dict[str, Any]],
    *,
    errors: list[str],
) -> dict[str, Any]:
    modules: dict[str, int] = {}
    competitors: dict[str, int] = {}
    for item in items:
        module = _clean_text(item.get("module"), 100) or "其他"
        modules[module] = modules.get(module, 0) + 1
        canonical = _clean_text(item.get("canonical_competitor"), 120)
        if canonical:
            competitors[canonical] = competitors.get(canonical, 0) + 1
    expected_competitors = list(
        dict.fromkeys(str(group["canonical"]) for group in mandatory_search_groups())
    )
    samples = [
        {
            "module": _clean_text(item.get("module"), 80),
            "title": _clean_text(item.get("title"), 180),
            "source": _clean_text(item.get("source"), 80),
            "keywords": [
                _clean_text(keyword, 60)
                for keyword in (item.get("keywords") or [])[:5]
            ],
        }
        for item in items[:20]
    ]
    return {
        "result_count": len(items),
        "module_counts": modules,
        "competitor_counts": competitors,
        "missing_fixed_competitors": [
            name for name in expected_competitors if not competitors.get(name)
        ],
        "query_error_count": len(errors),
        "sample_results": samples,
    }


def _agentic_monitoring_context(spec: dict[str, Any]) -> dict[str, Any]:
    modules = []
    for module in spec.get("modules") or []:
        if not isinstance(module, dict):
            continue
        modules.append(
            {
                "name": _clean_text(module.get("name"), 120),
                "keywords": [
                    _clean_text(keyword, 80)
                    for keyword in (module.get("keywords") or [])[:15]
                    if _clean_text(keyword, 80)
                ],
                "preferred_domains": list(
                    dict.fromkeys(
                        urlparse(str(url)).hostname or ""
                        for url in (module.get("source_urls") or [])
                        if urlparse(str(url)).hostname
                    )
                )[:5],
            }
        )
    fixed_competitors: dict[str, list[str]] = {}
    for group in mandatory_search_groups():
        fixed_competitors.setdefault(str(group["canonical"]), [])
        fixed_competitors[str(group["canonical"])].extend(
            str(term) for term in group["terms"]
        )
    return {
        "modules": modules,
        "fixed_competitors": {
            name: list(dict.fromkeys(aliases))[:8]
            for name, aliases in fixed_competitors.items()
        },
        "benchmark_operators": [
            list(group) for group in BENCHMARK_OPERATOR_QUERIES
        ],
        "priority_topics": [
            {"module": module, "terms": list(terms)}
            for module, terms in PRIORITY_NEWS_QUERIES
        ],
    }


def _normalize_agentic_plans(
    payload: dict[str, Any],
    *,
    phase: str,
    existing_queries: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    raw_queries = payload.get("queries") or payload.get("follow_up_queries") or []
    if not isinstance(raw_queries, list):
        return []
    plans: list[dict[str, Any]] = []
    for raw in raw_queries:
        if not isinstance(raw, dict):
            continue
        raw_keywords = raw.get("keywords") or raw.get("monitoring_terms") or []
        if isinstance(raw_keywords, str):
            raw_keywords = re.split(r"[,，、;；|\n]+", raw_keywords)
        keywords = list(
            dict.fromkeys(
                _clean_text(keyword, 100)
                for keyword in raw_keywords
                if _clean_text(keyword, 100)
            )
        )[:8]
        if not keywords:
            continue
        sanitized = _sanitize_agentic_query(raw.get("query"))
        # Reject runaway queries before compaction so a 180-character flood
        # cannot be silently rewritten into a misleading short search.
        if len(sanitized) > 180:
            continue
        raw_query = _compact_agentic_query(sanitized, keywords)
        if len(raw_query) > 180:
            continue
        query = _clean_text(raw_query, 180)
        normalized = _normalized_query(query)
        if len(query) < 4 or not normalized or normalized in existing_queries:
            continue
        module = _clean_text(raw.get("module"), 100) or "其他"
        competitor_evidence = " ".join([query, *keywords])
        canonical_matches = {
            str(group["canonical"])
            for group in mandatory_search_groups()
            if any(
                _term_matches(competitor_evidence, str(alias))
                for alias in group["terms"]
            )
        }
        try:
            lookback_days = min(7, max(0, int(raw.get("lookback_days") or 0)))
        except (TypeError, ValueError):
            lookback_days = 0
        plan = {
            "module": module,
            "query": query,
            "fallback_query": query,
            "keywords": keywords,
            "lookback_days": lookback_days,
            "search_origin": f"agentic_{phase}",
            "semantic_relevance": True,
            "agentic_intent": _clean_text(raw.get("intent"), 300),
            "agentic_reason": _clean_text(raw.get("reason"), 300),
        }
        if len(canonical_matches) == 1:
            plan["canonical_competitor"] = next(iter(canonical_matches))
        plans.append(plan)
        existing_queries.add(normalized)
        if len(plans) >= limit:
            break
    return plans


def _call_agentic_search_agent(
    *,
    phase: str,
    spec: dict[str, Any],
    coverage: dict[str, Any],
    existing_plans: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
    limit: int,
    target_competitor: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    existing_queries = {
        _normalized_query(plan.get("fallback_query") or plan.get("query"))
        for plan in existing_plans
    }
    monitoring_context = _agentic_monitoring_context(spec)
    target_competitor = _clean_text(target_competitor, 120)
    target_aliases = list(
        (monitoring_context.get("fixed_competitors") or {}).get(
            target_competitor,
            [],
        )
    )
    if target_competitor:
        monitoring_context = {
            **monitoring_context,
            "fixed_competitors": {
                target_competitor: target_aliases,
            },
            "benchmark_operators": [],
            "priority_topics": [],
        }
    system_prompt = (
        "你是香港电信竞对情报的 Agentic Search Planner。只输出合法 JSON 对象，结构为"
        "{\"sufficient\":true或false,\"assessment\":\"覆盖判断\","
        "\"queries\":[{\"module\":\"监测模块\",\"query\":\"可直接交给新闻搜索引擎的查询\","
        "\"keywords\":[\"关联监控词\"],\"intent\":\"要找的事件类型\","
        "\"reason\":\"为什么现有搜索可能漏掉\",\"lookback_days\":0到7}]}。"
        "固定监控、飞书关键词搜索和03:00爬虫信号已经由系统执行，你只能补充查询，不得删除、替代或缩减它们。"
        "根据已检索结果识别未覆盖公司、品牌别名、同义表达、事件类型和主题缺口，再提出少量高价值补搜。"
        "香港本地竞对、香港运营商动态、香港监管政策和本地数字产业政策同列最高优先级。"
        "既要补齐所有被监控运营商及其品牌的结果缺口，也要检查OFCA、创新科技及工业局、"
        "数字政策办公室、香港特区政府与内地部委合作等政策和本地产业事件是否缺失。"
        "还要检查香港智慧交通、自动驾驶测试与商业化、口岸通关、跨境基础设施及深港融合是否有"
        "具体新变化；这类信息即使不是传统电信新闻，也应作为香港本地战略候选交给下游AI审核。"
        "不要只寻找重大事件；产品资费、促销、客户服务、经营数据、网络技术、合作、投资、"
        "管理层、监管和资本市场等任何有明确时效的竞对动态都值得检索。"
        "查询应组合主体/别名与事件意图，例如业绩指引、网络建设、资费调整、合作并购、监管影响、"
        "AI/云/数据中心投资、管理层变化；可使用中英文同义词，但不要只是原关键词逐字重排。"
        "query必须用OR连接别名，再用括号OR连接最多3个事件意图词；"
        "禁止把业绩、财报、营收、资费、合作、管理层等词用空格做成AND查询，否则搜索引擎会零结果。"
        "竞对查询必须同时包含主体和至少一个事件意图词；政策或香港本地查询必须包含香港机构、"
        "政策领域或本地市场对象，并组合发布、签署、实施、咨询、牌照、频谱、投资等事件意图。"
        "禁止仅罗列公司或品牌别名做综合监测，"
        "因为固定搜索已经覆盖这些名称。missing_fixed_competitors表示结果缺口，不表示名称查询未执行。"
        "竞对查询只针对一个canonical竞对，最多包含3个该竞对别名和2组事件意图词；"
        "query最多180个字符。禁止把所有运营商拼进同一查询，禁止重复同一个词，"
        "禁止为了填满长度反复输出同义词。queries数量不得超过query_limit。"
        "为确保JSON稳定，query字段内禁止使用英文双引号字符，主体名称直接写即可；所有字符串必须正确转义。"
        "不要生成网址、site:或-site:搜索运算符、新闻事实或不在监控范围内的新主体。避免重复现有查询。"
        "一般国际AI、芯片或宏观新闻不是补搜重点，除非查询本身能说明其与香港电信市场的直接关系。"
        "若覆盖充分可返回 sufficient=true 和空 queries。"
    )
    if target_competitor:
        system_prompt += (
            f"本次唯一目标是{target_competitor}。只能为该竞对生成最多1条查询，"
            "不得出现其他运营商；若现有结果已覆盖该竞对则返回sufficient=true和空queries。"
        )
    existing_query_values = [
        _clean_text(plan.get("fallback_query") or plan.get("query"), 240)
        for plan in existing_plans
    ]
    if target_competitor and target_aliases:
        existing_query_values = [
            query
            for query in existing_query_values
            if any(_term_matches(query, alias) for alias in target_aliases)
        ]
    user_payload = {
        "phase": phase,
        "time_window": {
            "start": start_at.astimezone(HKT).isoformat(timespec="seconds"),
            "end": end_at.astimezone(HKT).isoformat(timespec="seconds"),
        },
        "query_limit": limit,
        "monitoring_context": monitoring_context,
        "current_coverage": {
            **coverage,
            "missing_fixed_competitors": (
                [target_competitor]
                if target_competitor
                else coverage.get("missing_fixed_competitors") or []
            ),
            "sample_results": list(coverage.get("sample_results") or [])[:8],
        },
        "existing_queries": existing_query_values[-12 if target_competitor else -40 :],
    }
    if target_competitor:
        user_payload["target_competitor"] = target_competitor
        user_payload["target_aliases"] = target_aliases
    last_error = ""
    for attempt in range(1, AGENTIC_AI_ATTEMPTS + 1):
        try:
            attempt_payload = dict(user_payload)
            if attempt > 1:
                attempt_payload["format_correction"] = (
                    "上一次输出不是合法JSON。请重新生成完整JSON对象；"
                    "query字段不要包含英文双引号，不要输出Markdown或解释文字；"
                    "每条query只写一个竞对、最多3个别名和2组事件意图，"
                    "最多180个字符且任何词不得重复。"
                )
            response = strategic_briefing._call_internal_ai(
                system_prompt,
                json.dumps(attempt_payload, ensure_ascii=False),
                # Follow-up plans include a coverage assessment plus several
                # structured queries. A smaller budget intermittently cut the
                # JSON before the closing object, so leave enough room for a
                # complete response and retry malformed output independently.
                max_tokens=max(2600, limit * 320),
                response_format=AGENTIC_SEARCH_RESPONSE_FORMAT,
            )
            plans = _normalize_agentic_plans(
                response,
                phase=phase,
                existing_queries=existing_queries,
                limit=limit,
            )
            if target_competitor:
                for plan in plans:
                    plan["canonical_competitor"] = target_competitor
            sufficient = bool(response.get("sufficient"))
            if not sufficient and not plans:
                raise RuntimeError(
                    "Agent判断仍有覆盖缺口，但未返回通过校验的补搜查询"
                )
            return plans, {
                "status": "completed",
                "attempts": attempt,
                "sufficient": sufficient,
                "assessment": _clean_text(response.get("assessment"), 500),
                "query_count": len(plans),
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {_clean_text(exc, 300)}"
            logging.warning(
                "Agentic Search %s 规划失败 %s/%s：%s",
                phase,
                attempt,
                AGENTIC_AI_ATTEMPTS,
                last_error,
            )
    if target_competitor and target_aliases:
        fallback_query = _deterministic_gap_query(target_aliases)
        fallback_plans = _normalize_agentic_plans(
            {
                "queries": [
                    {
                        "module": "竞争对手",
                        "query": fallback_query,
                        "keywords": list(dict.fromkeys(target_aliases))[:3],
                        "intent": "竞对经营动态兜底补搜",
                        "reason": "Agent补搜计划连续失败，使用正式竞对别名执行确定性补搜",
                    }
                ]
            },
            phase=phase,
            existing_queries=existing_queries,
            limit=1,
        )
        if fallback_plans:
            fallback_plans[0]["canonical_competitor"] = target_competitor
            return fallback_plans, {
                "status": "fallback",
                "attempts": AGENTIC_AI_ATTEMPTS,
                "sufficient": False,
                "assessment": "Agent补搜计划连续失败，已执行确定性竞对补搜",
                "query_count": 1,
                "error": last_error,
            }
    return [], {
        "status": "failed",
        "attempts": AGENTIC_AI_ATTEMPTS,
        "sufficient": False,
        "assessment": "",
        "query_count": 0,
        "error": last_error,
    }


def _call_agentic_followup_agents(
    *,
    spec: dict[str, Any],
    coverage: dict[str, Any],
    existing_plans: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Plan the second round one missing competitor at a time.

    A single all-competitor request can make the model concatenate every alias
    and event word into one unbounded query. Per-target calls keep the Agent's
    authority while making each decision small, auditable and retryable.
    """
    targets = [
        _clean_text(value, 120)
        for value in coverage.get("missing_fixed_competitors") or []
        if _clean_text(value, 120)
    ][:limit]
    if not targets:
        return [], {
            "status": "completed",
            "attempts": 0,
            "sufficient": True,
            "assessment": "Agentic扩展结果已覆盖全部固定竞对，无需第二轮补搜。",
            "query_count": 0,
            "targets": [],
        }
    plans: list[dict[str, Any]] = []
    target_traces: list[dict[str, Any]] = []
    evolving_plans = list(existing_plans)
    for target in targets:
        target_plans, trace = _call_agentic_search_agent(
            phase="followup",
            spec=spec,
            coverage=coverage,
            existing_plans=evolving_plans,
            start_at=start_at,
            end_at=end_at,
            limit=1,
            target_competitor=target,
        )
        plans.extend(target_plans)
        evolving_plans.extend(target_plans)
        target_traces.append({"target": target, **trace})
    completed_count = sum(
        trace.get("status") == "completed" for trace in target_traces
    )
    status = (
        "completed"
        if completed_count == len(target_traces)
        else "partial"
        if completed_count
        else "failed"
    )
    assessments = list(
        dict.fromkeys(
            _clean_text(trace.get("assessment"), 240)
            for trace in target_traces
            if _clean_text(trace.get("assessment"), 240)
        )
    )
    return plans, {
        "status": status,
        "attempts": sum(int(trace.get("attempts") or 0) for trace in target_traces),
        "sufficient": all(bool(trace.get("sufficient")) for trace in target_traces),
        "assessment": "；".join(assessments)[:500],
        "query_count": len(plans),
        "targets": target_traces,
    }


def _execute_search_plans(
    plans: list[dict[str, Any]],
    *,
    start_at: datetime,
    end_at: datetime,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    zero_result_queries: list[str] = []
    retry_count = 0
    retry_result_count = 0
    ungrounded_count = 0

    def _search(plan: dict[str, Any]) -> list[dict[str, Any]]:
        return _google_news_search(
            plan,
            end_at - timedelta(days=int(plan.get("lookback_days") or 0))
            if int(plan.get("lookback_days") or 0) > 0
            else start_at,
            end_at,
            # A fixed-page signal can arrive after the article was indexed.
            # Retrieve its lookback here; the shared admission gate below
            # still limits final rows to this scan's publication window.
            admission_start_at=(
                end_at
                - timedelta(days=int(plan.get("lookback_days") or 0))
                if plan.get("search_origin") == "scheduled_crawl_reference"
                and int(plan.get("lookback_days") or 0) > 0
                else start_at
            ),
            admission_end_at=end_at,
        )

    def _attach_provenance(
        plan: dict[str, Any], found: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        nonlocal ungrounded_count
        provenance_fields = (
            "scheduled_crawl_signal_id",
            "scheduled_crawl_run_id",
            "scheduled_crawl_config_row",
            "scheduled_crawl_parent_url",
            "scheduled_crawl_target_url",
        )
        grounded: list[dict[str, Any]] = []
        for item in found:
            if not _agentic_result_is_grounded(plan, item):
                ungrounded_count += 1
                continue
            for field in provenance_fields:
                if plan.get(field):
                    item[field] = plan[field]
            grounded.append(item)
        return grounded

    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as executor:
        future_map = {
            executor.submit(_search, plan): plan
            for plan in plans
        }
        pending_retries: list[dict[str, Any]] = []
        for future in as_completed(future_map):
            plan = future_map[future]
            try:
                found = _attach_provenance(plan, future.result())
                items.extend(found)
                if found:
                    continue
                zero_result_queries.append(_clean_text(plan.get("query"), 300))
                retry_plan = _agentic_zero_result_retry_plan(plan)
                if retry_plan is not None:
                    pending_retries.append(retry_plan)
            except Exception as exc:
                errors.append(
                    f"{_clean_text(plan.get('module'), 80)}: "
                    f"{type(exc).__name__}: {_clean_text(exc, 160)}"
                )
    for retry_plan in pending_retries:
        retry_count += 1
        try:
            found = _attach_provenance(retry_plan, _search(retry_plan))
            items.extend(found)
            retry_result_count += len(found)
            if not found:
                zero_result_queries.append(
                    "retry:" + _clean_text(retry_plan.get("query"), 280)
                )
        except Exception as exc:
            errors.append(
                f"{_clean_text(retry_plan.get('module'), 80)}: "
                f"{type(exc).__name__}: {_clean_text(exc, 160)}"
            )
    return items, errors, {
        "query_count": len(plans),
        "result_count": len(items),
        "zero_result_count": len(zero_result_queries),
        "zero_result_queries": zero_result_queries[:30],
        "retry_count": retry_count,
        "retry_result_count": retry_result_count,
        "ungrounded_dropped_count": ungrounded_count,
    }


def collect_news(start_at: datetime, end_at: datetime) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    errors: list[str] = []
    try:
        spec = strategic_briefing.read_monitoring_spec()
        base_plans = strategic_briefing._query_plans(
            spec,
            strategic_briefing._load_state(),
            # The 09:00/14:00 discovery crawl is the comprehensive layer:
            # every configured monitoring keyword is searched on every run.
            # The lightweight strategic monitor keeps its rotating limit.
            max_queries=None,
        )
    except Exception as exc:
        # The fixed competitor floor must continue even if the editable Feishu
        # monitoring sheet is unavailable or temporarily contains no keywords.
        spec = {
            "module_count": 0,
            "keyword_count": 0,
            "modules": [],
            "source_urls": [],
            "fixed_competitor_fallback": True,
        }
        base_plans = []
        errors.append(
            "监测表不可用，已继续执行后台固定竞对词库: "
            f"{type(exc).__name__}: {_clean_text(exc, 160)}"
        )
    competitor_plans = _mandatory_competitor_plans()
    for names in BENCHMARK_OPERATOR_QUERIES:
        query = " OR ".join(f'"{name}"' for name in names)
        competitor_plans.append(
            {
                "module": "竞争对手",
                "query": query,
                "fallback_query": query,
                "keywords": list(names),
                "search_origin": "background_fixed_keywords",
            }
        )
    priority_plans: list[dict[str, Any]] = []
    for module, terms in PRIORITY_NEWS_QUERIES:
        query = " OR ".join(f'"{term}"' for term in terms)
        priority_plans.append(
            {
                "module": module,
                "query": query,
                "fallback_query": query,
                "keywords": list(terms),
                "lookback_days": 7,
                "search_origin": "background_fixed_keywords",
            }
        )
    scheduled_plans, scheduled_trace = _scheduled_crawl_plans(end_at)
    if scheduled_trace.get("error"):
        errors.append(
            "定时页面爬虫线索读取失败: "
            + _clean_text(scheduled_trace.get("error"), 240)
        )
    plans = (
        competitor_plans
        + priority_plans
        + _local_strategic_plans()
        + scheduled_plans
        + base_plans
    )
    all_items, search_errors, legacy_stats = _execute_search_plans(
        plans,
        start_at=start_at,
        end_at=end_at,
    )
    scheduled_trace["retrieval_result_count"] = sum(
        item.get("search_origin") == "scheduled_crawl_reference"
        for item in all_items
    )
    scheduled_trace["attempted_signal_ids"] = list(
        dict.fromkeys(
            _clean_text(plan.get("scheduled_crawl_signal_id"), 80)
            for plan in scheduled_plans
            if _clean_text(plan.get("scheduled_crawl_signal_id"), 80)
        )
    )
    errors.extend(search_errors)
    agentic_trace: dict[str, Any] = {
        "enabled": AGENTIC_SEARCH_ENABLED,
        "mode": "fixed_monitoring_plus_agentic_gap_search",
        "fixed_query_count": len(plans),
        "fixed_result_count": len(all_items),
        "fixed_search": legacy_stats,
        "scheduled_crawl_search": scheduled_trace,
        "rounds": [],
    }
    if AGENTIC_SEARCH_ENABLED:
        coverage = _coverage_digest(_deduplicate(all_items), errors=errors)
        expansion_plans, expansion_trace = _call_agentic_search_agent(
            phase="expansion",
            spec=spec,
            coverage=coverage,
            existing_plans=plans,
            start_at=start_at,
            end_at=end_at,
            limit=AGENTIC_EXPANSION_LIMIT,
        )
        expansion_items, expansion_errors, expansion_stats = _execute_search_plans(
            expansion_plans,
            start_at=start_at,
            end_at=end_at,
        )
        all_items.extend(expansion_items)
        errors.extend(expansion_errors)
        expansion_trace["search"] = expansion_stats
        agentic_trace["rounds"].append({"phase": "expansion", **expansion_trace})
        executed_plans = plans + expansion_plans

        followup_plans: list[dict[str, Any]] = []
        followup_items: list[dict[str, Any]] = []
        if expansion_trace.get("status") == "failed":
            followup_trace = {
                "status": "skipped",
                "reason": "expansion_planner_failed",
                "query_count": 0,
            }
            followup_errors: list[str] = []
            followup_stats = {
                "query_count": 0,
                "result_count": 0,
                "zero_result_count": 0,
                "zero_result_queries": [],
            }
        elif expansion_trace.get("sufficient") and not expansion_plans:
            followup_trace = {
                "status": "skipped",
                "reason": "coverage_already_sufficient",
                "query_count": 0,
            }
            followup_errors = []
            followup_stats = {
                "query_count": 0,
                "result_count": 0,
                "zero_result_count": 0,
                "zero_result_queries": [],
            }
        else:
            combined = _deduplicate(all_items)
            followup_coverage = _coverage_digest(combined, errors=errors)
            followup_plans, followup_trace = _call_agentic_followup_agents(
                spec=spec,
                coverage=followup_coverage,
                existing_plans=executed_plans,
                start_at=start_at,
                end_at=end_at,
                limit=AGENTIC_FOLLOWUP_LIMIT,
            )
            followup_items, followup_errors, followup_stats = _execute_search_plans(
                followup_plans,
                start_at=start_at,
                end_at=end_at,
            )
        all_items.extend(followup_items)
        errors.extend(followup_errors)
        followup_trace["search"] = followup_stats
        agentic_trace["rounds"].append({"phase": "followup", **followup_trace})
        agentic_trace["agentic_query_count"] = len(expansion_plans) + len(followup_plans)
        agentic_trace["agentic_result_count"] = len(expansion_items) + len(followup_items)
        agentic_trace["coverage_before"] = coverage
        agentic_trace["coverage_after"] = _coverage_digest(
            _deduplicate(all_items),
            errors=errors,
        )
    else:
        agentic_trace["agentic_query_count"] = 0
        agentic_trace["agentic_result_count"] = 0
    admission_items: list[dict[str, Any]] = []
    admission_rejected = 0
    for item in all_items:
        try:
            published_at = datetime.fromisoformat(
                str(item.get("published_at") or "").replace("Z", "+00:00")
            )
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=HKT)
            published_at = published_at.astimezone(HKT)
        except (TypeError, ValueError):
            admission_rejected += 1
            continue
        if start_at <= published_at <= end_at:
            item["search_window_start"] = start_at.astimezone(HKT).isoformat(
                timespec="seconds"
            )
            item["search_window_end"] = end_at.astimezone(HKT).isoformat(
                timespec="seconds"
            )
            admission_items.append(item)
        else:
            admission_rejected += 1
    all_items = admission_items
    scheduled_trace["admitted_result_count"] = sum(
        item.get("search_origin") == "scheduled_crawl_reference"
        for item in all_items
    )
    scheduled_trace["admitted_signal_ids"] = list(
        dict.fromkeys(
            _clean_text(item.get("scheduled_crawl_signal_id"), 80)
            for item in all_items
            if item.get("search_origin") == "scheduled_crawl_reference"
            and _clean_text(item.get("scheduled_crawl_signal_id"), 80)
        )
    )
    scheduled_trace["result_count"] = scheduled_trace["admitted_result_count"]
    agentic_trace["admission_gate"] = {
        "window_start": start_at.astimezone(HKT).isoformat(timespec="seconds"),
        "window_end": end_at.astimezone(HKT).isoformat(timespec="seconds"),
        "accepted_count": len(all_items),
        "rejected_count": admission_rejected,
    }
    spec = {**spec, "agentic_search": agentic_trace}
    for item in all_items:
        _tag_competitor_entities(item)
    deduplicated = _deduplicate(all_items)
    module_order = {str(plan.get("module") or "其他"): index for index, plan in enumerate(plans)}
    selected, selection_trace = _select_discovery_results(
        deduplicated,
        module_order=module_order,
    )
    agentic_trace["selection_gate"] = selection_trace
    return selected, errors, spec


def _latest_timed_crawl() -> dict[str, Any]:
    rows = _read_json(CRAWL_INDEX_PATH, [])
    if not isinstance(rows, list):
        return {}
    timed = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("trigger") == "定时爬虫"
        and row.get("run_status") == "completed"
    ]
    return max(timed, key=lambda row: str(row.get("started_at_hkt") or ""), default={})


def _window(now: datetime, morning: bool) -> tuple[datetime, datetime]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first_scan = min(SCAN_TIMES, default=clock_time(9, 0))
    overlap_start = today.replace(hour=first_scan.hour, minute=first_scan.minute) - timedelta(hours=1)
    if not morning:
        # Retain one hour of overlap for articles indexed shortly after the morning run.
        # Downstream URL/title deduplication prevents overlap from becoming new rows.
        return overlap_start, now
    # Keep the previous day's full publication window from one hour before the
    # morning slot as a next-morning backstop. News indexes can expose an article hours after its
    # publication time; exact URL/ID dedupe downstream prevents re-insertion.
    return overlap_start - timedelta(days=1), now


def _send_card(card: dict[str, Any]) -> list[str]:
    content = json.dumps(card, ensure_ascii=False)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    message_ids: list[str] = []
    for chat_id in strategic_briefing.TARGET_CHAT_IDS:
        payload = strategic_briefing._lark_api(
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            data={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": content,
                "uuid": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"cmhk-news-digest:{content_hash}:{chat_id}",
                    )
                ),
            },
        )
        message_id = str(((payload.get("data") or {}).get("message_id") or ""))
        if message_id:
            message_ids.append(message_id)
    return message_ids


def _build_cards(
    *,
    now: datetime,
    slot_label: str,
    start_at: datetime,
    end_at: datetime,
    items: list[dict[str, Any]],
    errors: list[str],
    crawl: dict[str, Any],
) -> list[dict[str, Any]]:
    pages = [items[index : index + PAGE_SIZE] for index in range(0, len(items), PAGE_SIZE)] or [[]]
    local_count = sum(bool(item.get("is_hong_kong")) for item in items)
    crawl_log = crawl.get("run_log") or {}
    crawl_url = ((crawl.get("feishu") or {}).get("url") or "")
    cards: list[dict[str, Any]] = []
    ordinal = 0
    for page_index, page in enumerate(pages, start=1):
        elements: list[dict[str, Any]] = []
        if page_index == 1:
            overview = (
                f"**检索窗口：** {start_at:%m月%d日 %H:%M} 至 {end_at:%m月%d日 %H:%M}\n"
                f"**搜索结果：** {len(items)} 条，其中香港相关 {local_count} 条；"
                f"03:00 固定来源扫描 {int(crawl_log.get('rows') or 0)} 个 URL，成功 {int(crawl_log.get('success_urls') or 0)} 个。\n"
                "<font color='grey'>本层仅做时间、关键词、新闻类型与重复项处理，不进行战略重要性筛选。</font>"
            )
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": overview}})
            if crawl_url:
                elements.append(
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "查看03:00爬虫日志"},
                                "type": "default",
                                "url": crawl_url,
                            }
                        ],
                    }
                )
        for item in page:
            ordinal += 1
            published_at = datetime.fromisoformat(str(item["published_at"]))
            keywords = "、".join(item.get("keywords") or []) or "关键词命中"
            locality = "香港相关" if item.get("is_hong_kong") else "国际/行业"
            body = (
                f"<font color='blue'>**{ordinal:02d}. {_card_text(item.get('title'), 220)}**</font>\n"
                f"<font color='green'>{_card_text(item.get('module'), 80)}</font> · {locality} · "
                f"{_card_text(item.get('source'), 100)} · {published_at:%m-%d %H:%M}\n"
                f"**命中：** {_card_text(keywords, 180)}\n"
                f"<font color='grey'>{_card_text(item.get('snippet'), 260) or '搜索结果未提供摘要。'}</font>\n"
                f"<font color='grey'>{_card_text(item.get('news_id'), 60)}</font>"
            )
            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": body}})
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看原文"},
                            "type": "primary",
                            "url": item["url"],
                        }
                    ],
                }
            )
        if page_index == len(pages):
            elements.append({"tag": "hr"})
            note = "下一层由群成员人工筛选进入滚动新闻；本卡不代表已采纳为战略快讯。"
            if errors:
                note += f" 本轮有 {len(errors)} 组查询失败，后台已记录并将在下轮重试。"
            elements.append(
                {"tag": "note", "elements": [{"tag": "plain_text", "content": note}]}
            )
        cards.append(
            {
                "config": {"wide_screen_mode": True, "enable_forward": True},
                "header": {
                    "template": "blue",
                    "title": {
                        "tag": "plain_text",
                        "content": f"搜索到的新闻｜{slot_label}｜{page_index}/{len(pages)}",
                    },
                },
                "elements": elements,
            }
        )
    return cards


def _late_index_retry_delays() -> tuple[int, ...]:
    raw = os.environ.get(
        "CMHK_NEWS_LATE_INDEX_RETRY_DELAYS_SECONDS",
        "300,600,900",
    )
    delays: list[int] = []
    for value in raw.split(","):
        try:
            delay = int(value.strip())
        except ValueError:
            continue
        if delay > 0:
            delays.append(delay)
    return tuple(delays)


def _collect_news_with_late_index_retry(
    start_at: datetime,
    end_at: datetime,
    *,
    progress_callback: Any = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Retry an abnormally small discovery window and union late-indexed rows."""
    merged_items: list[dict[str, Any]] = []
    merged_errors: list[str] = []
    latest_spec: dict[str, Any] = {}
    attempt_audits: list[dict[str, Any]] = []
    delays = _late_index_retry_delays()
    scheduled_delays = (0, *delays)
    for attempt_index, delay_seconds in enumerate(scheduled_delays, start=1):
        if delay_seconds:
            if progress_callback is not None:
                progress_callback(
                    "新闻索引延迟复查",
                    (
                        f"当前仅发现 {len(merged_items)} 条，低于 "
                        f"{LATE_INDEX_MIN_RESULTS} 条可靠完成线；"
                        f"等待 {delay_seconds // 60} 分钟后执行第 {attempt_index} 次检索。"
                    ),
                )
            time.sleep(delay_seconds)
        items, errors, spec = collect_news(start_at, end_at)
        merged_items = _deduplicate([*merged_items, *items])
        merged_errors = list(dict.fromkeys([*merged_errors, *errors]))
        latest_spec = spec
        trace = spec.get("agentic_search") or {}
        attempt_audits.append(
            {
                "attempt": attempt_index,
                "delay_seconds": delay_seconds,
                "result_count": len(items),
                "merged_result_count": len(merged_items),
                "fixed_query_count": int(trace.get("fixed_query_count") or 0),
                "fixed_result_count": int(trace.get("fixed_result_count") or 0),
                "query_error_count": len(errors),
            }
        )
        if len(merged_items) >= LATE_INDEX_MIN_RESULTS:
            break
    latest_trace = dict(latest_spec.get("agentic_search") or {})
    _, selection_trace = _select_discovery_results(
        merged_items,
        module_order={},
    )
    latest_trace["selection_gate"] = selection_trace
    latest_trace["late_index_retry"] = {
        "triggered": len(attempt_audits) > 1,
        "minimum_result_count": LATE_INDEX_MIN_RESULTS,
        "maximum_wait_seconds": sum(delays),
        "attempt_count": len(attempt_audits),
        "attempts": attempt_audits,
        "final_result_count": len(merged_items),
        "recovered_count": max(
            0,
            len(merged_items) - int(attempt_audits[0].get("result_count") or 0),
        ),
        "exhausted": len(merged_items) < LATE_INDEX_MIN_RESULTS,
    }
    latest_spec = {**latest_spec, "agentic_search": latest_trace}
    if progress_callback is not None and len(attempt_audits) > 1:
        progress_callback(
            "新闻索引延迟复查",
            (
                f"共执行 {len(attempt_audits)} 次检索，合并得到 "
                f"{len(merged_items)} 条；晚到补回 "
                f"{latest_trace['late_index_retry']['recovered_count']} 条。"
            ),
        )
    return merged_items, merged_errors, latest_spec


def send_digest(
    now: datetime | None = None,
    *,
    morning: bool | None = None,
    progress_callback: Any = None,
) -> dict[str, Any]:
    now = (now or datetime.now(HKT)).astimezone(HKT)
    morning = (now.hour < 12) if morning is None else morning
    slot_label = "上午全量" if morning else "下午全量"
    start_at, end_at = _window(now, morning)
    items, errors, spec = _collect_news_with_late_index_retry(
        start_at,
        end_at,
        progress_callback=progress_callback,
    )
    crawl = _latest_timed_crawl()
    cards = _build_cards(
        now=now,
        slot_label=slot_label,
        start_at=start_at,
        end_at=end_at,
        items=items,
        errors=errors,
        crawl=crawl,
    )
    message_ids: list[str] = []
    if os.environ.get("CMHK_STRATEGIC_GROUP_NOTIFICATIONS", "0") == "1":
        for card in cards:
            message_ids.extend(_send_card(card))
            time.sleep(0.25)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "slot_label": slot_label,
        "window_start": start_at.isoformat(timespec="seconds"),
        "window_end": end_at.isoformat(timespec="seconds"),
        "spreadsheet_revision": spec.get("revision"),
        "spec_hash": spec.get("spec_hash"),
        "crawl_run_id": crawl.get("crawl_run_id"),
        "crawl_log_url": ((crawl.get("feishu") or {}).get("url") or ""),
        "result_count": len(items),
        "hong_kong_count": sum(bool(item.get("is_hong_kong")) for item in items),
        "query_errors": errors,
        "agentic_search": spec.get("agentic_search") or {},
        "message_ids": message_ids,
        "items": items,
    }
    # Persist an explicit empty pool too. Keeping the previous non-empty file
    # makes a zero-result afternoon rerun the morning candidates and falsely
    # report them as fresh AI confirmations and same-day duplicates.
    _write_json(LATEST_PATH, payload)
    return payload


def _slot_key(now: datetime, slot: clock_time) -> str:
    return f"{now.date().isoformat()}|{slot.strftime('%H:%M')}"


def run_cycle(now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(HKT)).astimezone(HKT)
    state = _read_json(STATE_PATH, {"sent_slots": {}})
    sent_slots = state.setdefault("sent_slots", {})
    result: dict[str, Any] = {"sent": False, "now": now.isoformat(timespec="seconds")}
    for slot in sorted(SCAN_TIMES):
        scheduled = now.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        delay = (now - scheduled).total_seconds()
        key = _slot_key(now, slot)
        if 0 <= delay <= CATCHUP_MINUTES * 60 and key not in sent_slots:
            payload = send_digest(now, morning=slot.hour < 12)
            sent_slots[key] = {
                "sent_at": now.isoformat(timespec="seconds"),
                "result_count": payload["result_count"],
                "message_ids": payload["message_ids"],
            }
            result = {"sent": True, "slot": key, **payload}
            break
    cutoff = now.date() - timedelta(days=14)
    state["sent_slots"] = {
        key: value
        for key, value in sent_slots.items()
        if key[:10] >= cutoff.isoformat()
    }
    state["last_checked_at"] = now.isoformat(timespec="seconds")
    _write_json(STATE_PATH, state)
    return result


def main() -> None:
    while True:
        try:
            run_cycle()
        except Exception:
            logging.exception("全量新闻发现任务执行失败")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CMHK 全量新闻发现与飞书推送")
    parser.add_argument("--send-now", action="store_true", help="立即检索并发送")
    parser.add_argument("--morning", action="store_true", help="使用上午窗口")
    parser.add_argument("--afternoon", action="store_true", help="使用下午窗口")
    args = parser.parse_args()
    if args.send_now:
        selected = True if args.morning else False if args.afternoon else None
        output = send_digest(morning=selected)
        now = datetime.now(HKT)
        state = _read_json(STATE_PATH, {"sent_slots": {}})
        slot = clock_time(9, 0) if output["slot_label"] == "上午全量" else clock_time(15, 0)
        state.setdefault("sent_slots", {})[_slot_key(now, slot)] = {
            "sent_at": now.isoformat(timespec="seconds"),
            "result_count": output["result_count"],
            "message_ids": output["message_ids"],
        }
        _write_json(STATE_PATH, state)
        print(json.dumps({key: value for key, value in output.items() if key != "items"}, ensure_ascii=False, indent=2))
    else:
        main()
