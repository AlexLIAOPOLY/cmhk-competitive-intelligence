"""Cheap freshness and recipient-history gates before personal news editing."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import random
from zoneinfo import ZoneInfo

from cmhk.services.news_delivery_dedupe import exact_unique

POLICY_VERSION = "recent-news-20260911-v1"
HKT = ZoneInfo("Asia/Hong_Kong")


def fresh_news(items: list[dict], send_day: str) -> list[dict]:
    """Only today/yesterday's source publication dates; discovery is not publication."""
    today = date.fromisoformat(send_day)
    earliest = today - timedelta(days=1)
    selected = []
    for item in items:
        raw = str(item.get("published_at") or item.get("source_date") or "").strip()
        try:
            published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=HKT)
        if earliest <= published.astimezone(HKT).date() <= today:
            selected.append(item)
    return selected


def select_recent_news(items: list[dict], categories, *, limit: int,
                       history: list[dict], send_day: str, seed: str = "") -> list[dict]:
    from cmhk.services.subscriptions import (
        NEWS_CATEGORIES_PER_PUSH, filter_news_by_categories, normalize_news_categories,
    )
    # Expire thousands of archived rows before identity checks or model work.
    candidates = exact_unique(fresh_news(items, send_day), history)
    available = {item.get("category") for item in candidates}
    sections = [x for x in normalize_news_categories(categories) if x in available]
    coverage = Counter(item.get("category") for item in exact_unique(history))
    random.Random(seed).shuffle(sections)
    sections.sort(key=lambda section: coverage[section])
    sections = sections[:NEWS_CATEGORIES_PER_PUSH]
    if not sections:
        return []  # Empty must not be normalized back to all subscriptions.
    return filter_news_by_categories(candidates, sections, limit=limit, selection_seed=seed)


def original_crawl_pool(db, content_ref: str) -> list[dict]:
    """Recover alternatives for an already queued card, within its original round."""
    import json
    if not content_ref.startswith("strategic-crawl:"):
        return []
    slot = content_ref.removeprefix("strategic-crawl:")
    return [json.loads(row[0]) for row in db.execute(
        """SELECT item_json FROM news_crawl_item_pool
           WHERE crawl_date=? AND crawl_slot<=?
           ORDER BY sort_timestamp DESC, crawl_slot DESC""", (slot[:10], slot),
    )]
