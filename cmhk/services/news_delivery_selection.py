"""Cheap freshness and recipient-history gates before personal news editing."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import json
import random
from zoneinfo import ZoneInfo

from cmhk.services.news_delivery_dedupe import exact_unique
from cmhk.services.news_topics import topic_score
from cmhk.services.personal_news_skill import normalize_personal_skill

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
                       history: list[dict], send_day: str, seed: str = "", region_preference: str | None = None, topics=None, personal_skill=None) -> list[dict]:
    from cmhk.services.subscriptions import (
        NEWS_CATEGORIES_PER_PUSH, filter_news_by_categories, normalize_news_categories,
    )
    # Expire thousands of archived rows before identity checks or model work.
    candidates = exact_unique(fresh_news(items, send_day), history)
    if normalize_personal_skill(personal_skill):
        # This is an intake queue only. The preparation Agent judges the full
        # original pool before sending; no old section checklist limits it.
        preferred = '国际/行业' if region_preference == 'international' else '香港本地'
        return sorted(candidates, key=lambda item:item.get('region') != preferred)[:limit]
    subscribed = normalize_news_categories(categories)
    # A natural-language topic is an additional interest across editorial
    # sections, not a translation back into the old category checklist.
    extra_sections = {item.get("category") for item in candidates if topic_score(item, topics)}
    candidates = [item for item in candidates
                  if item.get("category") in subscribed or topic_score(item, topics)]
    available = {item.get("category") for item in candidates}
    sections = list(dict.fromkeys([x for x in subscribed if x in available] +
                                 [x for x in normalize_news_categories(list(extra_sections), default_all=False) if x in available]))
    coverage = Counter(item.get("category") for item in exact_unique(history))
    random.Random(seed).shuffle(sections)
    sections.sort(key=lambda section: (-max((topic_score(item, topics) for item in candidates if item.get("category") == section), default=0), coverage[section]))
    sections = sections[:NEWS_CATEGORIES_PER_PUSH]
    if not sections:
        return []  # Empty must not be normalized back to all subscriptions.
    return filter_news_by_categories(candidates, sections, limit=limit, selection_seed=seed, region_preference=region_preference, topics=topics)


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


def prioritize_preparation(items: list[dict], *, runtime_root, attempts: dict[str, int]) -> list[dict]:
    """Move costly retries behind unused alternatives without dropping either.

    A positive cache is only a scheduling hint. The delivery guard still runs
    every source, summary, image and recipient-history check before sending.
    Original order retains region preference and section variety within tiers.
    """
    from cmhk.services.news_text import simplified_news_text

    def identity(item):
        return (str(item.get('source_url') or ''), simplified_news_text(item.get('title')),
                str(item.get('summary') or ''))

    ready = set()
    directory = runtime_root / 'var/subscriptions/news-editor'
    for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:300]:
        try:
            cached = json.loads(path.read_text())
            rows, reviews = cached.get('items', []), cached.get('summary_reviews', [])
            if not rows or len(rows) != len(reviews) or not all(r.get('accepted') is True for r in reviews):
                continue
            for row in rows:
                summary = simplified_news_text(row.get('digest_summary'))
                if row.get('source_url') and row.get('image_key') and 20 <= len(summary) <= 100:
                    ready.add(identity(row))
        except (OSError, ValueError, TypeError, AttributeError):
            continue

    def rank(item):
        key = str(item.get('news_id') or item.get('source_url') or item.get('title') or '')
        tried = attempts.get(key, 0)
        return (tried, -int(item.get("subscription_semantic_score", item.get("subscription_topic_score")) or 0), identity(item) not in ready)

    return sorted(items, key=rank)
