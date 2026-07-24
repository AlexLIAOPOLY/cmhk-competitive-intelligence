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
from local_competitor_keywords import mandatory_search_groups, priority_for


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "strategy_briefing"
STATE_PATH = DATA_DIR / "news_digest_state.json"
LATEST_PATH = DATA_DIR / "news_discovery_latest.json"
CRAWL_INDEX_PATH = ROOT / "agent_knowledge" / "crawl_run_logs" / "index.json"
HKT = ZoneInfo("Asia/Hong_Kong")

SCAN_TIMES = tuple(
    clock_time(int(item.split(":", 1)[0]), int(item.split(":", 1)[1]))
    for item in os.environ.get("CMHK_NEWS_DIGEST_SCAN_TIMES", "09:00,15:00").split(",")
    if re.fullmatch(r"\s*\d{1,2}:\d{2}\s*", item)
)
POLL_SECONDS = max(30, int(os.environ.get("CMHK_NEWS_DIGEST_POLL_SECONDS", "60")))
CATCHUP_MINUTES = max(30, int(os.environ.get("CMHK_NEWS_DIGEST_CATCHUP_MINUTES", "120")))
RESULTS_PER_QUERY = max(10, int(os.environ.get("CMHK_NEWS_RESULTS_PER_QUERY", "30")))
MAX_RESULTS = max(20, int(os.environ.get("CMHK_NEWS_MAX_RESULTS", "120")))
PAGE_SIZE = min(10, max(5, int(os.environ.get("CMHK_NEWS_PAGE_SIZE", "8"))))
SEARCH_WORKERS = min(8, max(2, int(os.environ.get("CMHK_NEWS_SEARCH_WORKERS", "6"))))

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


def _relevant(text: str, keywords: list[str]) -> bool:
    meaningful = [item for item in keywords if len(_clean_text(item)) >= 2]
    return not meaningful or any(_term_matches(text, item) for item in meaningful)


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
        if not _relevant(relevance_text, keywords):
            continue
        searchable = f"{relevance_text} {source}"
        digest = hashlib.sha1(f"{title.lower()}|{source.lower()}".encode("utf-8")).hexdigest()[:10]
        lowered = searchable.lower()
        matched_keywords = [
            item for item in keywords if _term_matches(searchable, item)
        ][:5]
        if canonical_competitor:
            matched_keywords = list(
                dict.fromkeys([canonical_competitor, *matched_keywords])
            )[:6]
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
            "retrieved_at": end_at.astimezone(HKT).isoformat(timespec="seconds"),
            "module": module,
            "keywords": matched_keywords,
            "snippet": snippet,
            "is_hong_kong": bool(canonical_competitor)
            or any(term in lowered for term in LOCAL_TERMS),
            "query": base_query,
            "search_provider": provider,
            "search_origin": search_origin or "monitoring_sheet_keyword_search",
        }
        if canonical_competitor:
            candidate["canonical_competitor"] = canonical_competitor
            candidate["search_origin"] = (
                search_origin or "mandatory_local_competitor"
            )
        output.append(candidate)
    return output


def _google_news_search(plan: dict[str, Any], start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
    base_query = _clean_text(plan.get("fallback_query") or plan.get("query"), 1400)
    module = _clean_text(plan.get("module"), 100) or "其他"
    keywords = [_clean_text(item, 120) for item in (plan.get("keywords") or []) if _clean_text(item, 120)]
    canonical_competitor = _clean_text(plan.get("canonical_competitor"), 120)
    search_origin = _clean_text(plan.get("search_origin"), 100)
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
                    start_at=start_at,
                    end_at=end_at,
                    canonical_competitor=canonical_competitor,
                    search_origin=search_origin,
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


def collect_news(start_at: datetime, end_at: datetime) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    errors: list[str] = []
    try:
        spec = strategic_briefing.read_monitoring_spec()
        base_plans = strategic_briefing._query_plans(
            spec,
            strategic_briefing._load_state(),
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
    plans = competitor_plans + priority_plans + base_plans
    all_items: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as executor:
        future_map = {
            executor.submit(
                _google_news_search,
                plan,
                end_at - timedelta(days=int(plan.get("lookback_days") or 0))
                if int(plan.get("lookback_days") or 0) > 0
                else start_at,
                end_at,
            ): plan
            for plan in plans
        }
        for future in as_completed(future_map):
            plan = future_map[future]
            try:
                all_items.extend(future.result())
            except Exception as exc:
                errors.append(f"{_clean_text(plan.get('module'), 80)}: {type(exc).__name__}: {_clean_text(exc, 160)}")
    deduplicated = _deduplicate(all_items)
    module_order = {str(plan.get("module") or "其他"): index for index, plan in enumerate(plans)}
    def competitor_priority(item: dict[str, Any]) -> int:
        canonical = str(item.get("canonical_competitor") or "")
        if canonical:
            return priority_for(canonical)
        text = " ".join(
            str(item.get(key) or "")
            for key in ("title", "snippet", "query", "keywords")
        ).casefold()
        if any(term in text for term in ("hkt", "hong kong telecommunications", "香港电讯", "香港電訊", "pccw", "电讯盈科", "電訊盈科", "csl", "1o1o")):
            return 0
        if any(term in text for term in ("hkbn", "smartone", "hgc", "3 hong kong", "i-cable")):
            return 1
        return 2

    deduplicated.sort(
        key=lambda item: (
            competitor_priority(item),
            module_order.get(str(item.get("module") or "其他"), 999),
            -datetime.fromisoformat(str(item["published_at"])).timestamp(),
        )
    )
    return deduplicated[:MAX_RESULTS], errors, spec


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
    if not morning:
        # Retain one hour of overlap for articles indexed shortly after the 09:00 run.
        # Downstream URL/title deduplication prevents overlap from becoming new rows.
        return today.replace(hour=8), now
    days_back = 3 if now.weekday() == 0 else 1
    return today - timedelta(days=days_back), now


def _send_card(card: dict[str, Any]) -> str:
    payload = strategic_briefing._lark_api(
        "POST",
        "/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        data={
            "receive_id": strategic_briefing.TARGET_CHAT_ID,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
    )
    return str(((payload.get("data") or {}).get("message_id") or ""))


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


def send_digest(now: datetime | None = None, *, morning: bool | None = None) -> dict[str, Any]:
    now = (now or datetime.now(HKT)).astimezone(HKT)
    morning = (now.hour < 12) if morning is None else morning
    slot_label = "上午全量" if morning else "下午全量"
    start_at, end_at = _window(now, morning)
    items, errors, spec = collect_news(start_at, end_at)
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
            message_ids.append(_send_card(card))
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
        "message_ids": message_ids,
        "items": items,
    }
    if items:
        _write_json(LATEST_PATH, payload)
    else:
        payload["preserved_previous_news_pool"] = True
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
