"""Bridge completed fixed-source crawls into the 07:30/14:00 news scans.

The scheduled crawler is deliberately a fixed-source monitor.  This module
does not turn every changed page into a news item.  It records newly discovered
article-like links as search leads, and the strategic news scan remains
responsible for publication-date validation, relevance gating, deduplication,
AI editing, and Feishu review-sheet insertion.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
HKT = ZoneInfo("Asia/Hong_Kong")
BRIDGE_DIR = ROOT / "strategy_briefing" / "scheduled_crawl_bridge"
BASELINE_PATH = BRIDGE_DIR / "baseline.json"
EVENTS_DIR = BRIDGE_DIR / "events"
SCHEMA_VERSION = 1
MAX_PENDING_DAYS = 3

_ARTICLE_URL_RE = re.compile(
    r"(?:/news(?:room)?/|/news[-_ ]?updates?/|/press(?:[-_ ]?releases?)?/|"
    r"/media[-_ ]?(?:centre|center|room)/|/article/|/articles/|"
    r"/announcement/|/announcements/|/insight/|/insights/|/blog/|"
    r"/story/|/stories/|/gia/general/\d{6}/|press\.php\?prid=|"
    r"/20\d{2}/(?:0?[1-9]|1[0-2])(?:/|[-_]))",
    re.I,
)
_LISTING_SUFFIX_RE = re.compile(
    r"(?:/news|/newsroom|/press|/press-releases|/press-room|"
    r"/media|/media-centre|/media-center|/announcements?|"
    r"/news-overview|/press-archive)/?$",
    re.I,
)
_GENERIC_TITLES = {
    "news",
    "newsroom",
    "press",
    "press release",
    "press releases",
    "media",
    "media centre",
    "media center",
    "read more",
    "learn more",
    "more",
    "details",
    "home",
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _clean_text(value: Any, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _canonical_url(value: Any) -> str:
    text = _clean_text(value, 1800)
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            parsed.query,
            "",
        )
    )


def _is_individual_article(url: str, title: str = "") -> bool:
    canonical = _canonical_url(url)
    if not canonical or _LISTING_SUFFIX_RE.search(urlparse(canonical).path):
        return False
    clean_title = _clean_text(title, 240).casefold()
    if clean_title in _GENERIC_TITLES:
        return False
    return bool(_ARTICLE_URL_RE.search(canonical))


def _source_map(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        row = str(source.get("row") or "").strip()
        if row:
            mapped[row] = source
    return mapped


def _signal_keywords(monitor_object: str, title: str) -> list[str]:
    entity_terms = [
        _clean_text(term, 80)
        for term in re.split(r"[/,，、|]+", monitor_object)
        if _clean_text(term, 80)
    ]
    title_terms = [
        term
        for term in re.findall(r"[A-Za-z][A-Za-z0-9+&.-]{2,}|[\u4e00-\u9fff]{2,8}", title)
        if term.casefold() not in {"news", "press", "release", "releases"}
    ]
    return list(dict.fromkeys([*entity_terms, *title_terms]))[:8]


def _query_for_signal(monitor_object: str, title: str) -> str:
    entity = _clean_text(monitor_object.replace("/", " "), 100)
    headline = _clean_text(title, 150)
    return " ".join(part for part in (entity, headline) if part)


def _signal(
    *,
    crawl_run_id: str,
    row: str,
    monitor_object: str,
    monitor_category: str,
    parent_url: str,
    target_url: str,
    title: str,
    discovered_at: str,
    kind: str,
) -> dict[str, Any]:
    canonical_target = _canonical_url(target_url)
    signal_id = "SCN-" + hashlib.sha1(canonical_target.encode("utf-8")).hexdigest()[:16].upper()
    return {
        "signal_id": signal_id,
        "kind": kind,
        "crawl_run_id": crawl_run_id,
        "config_row": row,
        "monitor_object": monitor_object or "未标注",
        "monitor_category": monitor_category or "重大动态/技术",
        "parent_url": _canonical_url(parent_url),
        "target_url": canonical_target,
        "title": _clean_text(title, 300),
        "query": _query_for_signal(monitor_object, title),
        "keywords": _signal_keywords(monitor_object, title),
        "discovered_at": discovered_at,
    }


def capture_completed_crawl(
    crawl_run_id: str,
    rows: list[int],
    *,
    captured_at: datetime | None = None,
    root: Path | None = None,
    bridge_dir: Path | None = None,
) -> dict[str, Any]:
    """Capture new article links after a scheduled crawl fully succeeds."""
    project_root = (root or ROOT).resolve()
    target_dir = (bridge_dir or (project_root / "strategy_briefing" / "scheduled_crawl_bridge")).resolve()
    baseline_path = target_dir / "baseline.json"
    events_dir = target_dir / "events"
    run_log = _read_json(project_root / "run_log.json", [])
    sources = _read_json(project_root / "sources.json", [])
    if not isinstance(run_log, list) or not run_log:
        raise RuntimeError("定时爬虫新闻桥接缺少 run_log.json 记录")
    if not isinstance(sources, list):
        sources = []

    now = (captured_at or datetime.now(HKT)).astimezone(HKT)
    captured_iso = now.isoformat(timespec="seconds")
    previous = _read_json(baseline_path, {})
    previous_pages = previous.get("pages") if isinstance(previous, dict) else {}
    if not isinstance(previous_pages, dict):
        previous_pages = {}
    bootstrap = not bool(previous_pages)
    source_by_row = _source_map(sources)
    current_pages: dict[str, dict[str, Any]] = {}
    signals_by_url: dict[str, dict[str, Any]] = {}
    selected_rows = {str(row) for row in rows}

    for record in run_log:
        if not isinstance(record, dict):
            continue
        row = str(record.get("row") or "").strip()
        if selected_rows and row not in selected_rows:
            continue
        try:
            status = int(float(record.get("http_status") or record.get("status") or 0))
        except (TypeError, ValueError):
            status = 0
        if not 200 <= status < 400 or _clean_text(record.get("error"), 400):
            continue
        parent_url = _canonical_url(record.get("final_url") or record.get("url"))
        if not parent_url:
            continue
        page_links = record.get("discovered_news_links") or record.get("page_links") or []
        normalized_links: dict[str, dict[str, str]] = {}
        for link in page_links if isinstance(page_links, list) else []:
            if isinstance(link, str):
                target_url = _canonical_url(link)
                title = ""
            elif isinstance(link, dict):
                target_url = _canonical_url(link.get("url") or link.get("href"))
                title = _clean_text(link.get("title") or link.get("text"), 300)
            else:
                continue
            if (
                not target_url
                or target_url == parent_url
                or not _is_individual_article(target_url, title)
            ):
                continue
            normalized_links[target_url] = {"url": target_url, "title": title}

        current_pages[parent_url] = {
            "row": row,
            "title": _clean_text(record.get("title"), 300),
            "content_hash": _clean_text(record.get("content_hash"), 100),
            "links": sorted(normalized_links),
        }
        if bootstrap:
            continue
        source = source_by_row.get(row, {})
        monitor_object = _clean_text(source.get("object"), 200)
        monitor_category = _clean_text(source.get("package"), 160)
        old_page = previous_pages.get(parent_url)
        old_links = set(old_page.get("links") or []) if isinstance(old_page, dict) else set()

        # A page can run daily, weekly, or monthly.  Its first observation is
        # always a page-level bootstrap, otherwise the first Monday/monthly run
        # would flood the news pool with every historical child article.
        if old_page is not None:
            for target_url, link in normalized_links.items():
                if target_url in old_links:
                    continue
                signals_by_url[target_url] = _signal(
                    crawl_run_id=crawl_run_id,
                    row=row,
                    monitor_object=monitor_object,
                    monitor_category=monitor_category,
                    parent_url=parent_url,
                    target_url=target_url,
                    title=link["title"] or _clean_text(record.get("title"), 300),
                    discovered_at=captured_iso,
                    kind="new_article_link",
                )

        if old_page is None and _is_individual_article(
            parent_url,
            _clean_text(record.get("title"), 300),
        ):
            signals_by_url.setdefault(
                parent_url,
                _signal(
                    crawl_run_id=crawl_run_id,
                    row=row,
                    monitor_object=monitor_object,
                    monitor_category=monitor_category,
                    parent_url=parent_url,
                    target_url=parent_url,
                    title=_clean_text(record.get("title"), 300),
                    discovered_at=captured_iso,
                    kind="new_configured_article",
                ),
            )

    event = {
        "schema_version": SCHEMA_VERSION,
        "crawl_run_id": crawl_run_id,
        "captured_at": captured_iso,
        "rows": sorted(int(row) for row in selected_rows if row.isdigit()),
        "bootstrap": bootstrap,
        "page_count": len(current_pages),
        "signal_count": len(signals_by_url),
        "signals": list(signals_by_url.values()),
    }
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", crawl_run_id).strip("_") or "scheduled"
    _atomic_write_json(events_dir / f"{safe_run_id}.json", event)
    merged_pages = dict(previous_pages)
    merged_pages.update(current_pages)
    _atomic_write_json(
        baseline_path,
        {
            "schema_version": SCHEMA_VERSION,
            "updated_at": captured_iso,
            "last_crawl_run_id": crawl_run_id,
            "pages": merged_pages,
        },
    )
    return {
        "crawl_run_id": crawl_run_id,
        "bootstrap": bootstrap,
        "page_count": len(current_pages),
        "signal_count": len(signals_by_url),
        "event_path": str((events_dir / f"{safe_run_id}.json").relative_to(project_root)),
    }


def load_pending_signals(
    state: dict[str, Any],
    now: datetime,
    *,
    bridge_dir: Path | None = None,
) -> dict[str, Any]:
    """Load recent signals not yet resolved by a successful news scan."""
    target_dir = bridge_dir or BRIDGE_DIR
    events_dir = target_dir / "events"
    consumed = {
        str(item)
        for item in state.get("scheduled_crawl_consumed_signal_ids") or []
        if str(item)
    }
    signals: dict[str, dict[str, Any]] = {}
    empty_event_ids: list[str] = []
    expired_signal_ids: list[str] = []
    cutoff = now.astimezone(HKT) - timedelta(days=MAX_PENDING_DAYS)
    for path in sorted(events_dir.glob("*.json")) if events_dir.exists() else []:
        event = _read_json(path, {})
        if not isinstance(event, dict):
            continue
        event_signals = event.get("signals")
        if not isinstance(event_signals, list) or not event_signals:
            empty_event_ids.append(path.stem)
            continue
        for signal in event_signals:
            if not isinstance(signal, dict):
                continue
            signal_id = str(signal.get("signal_id") or "").strip()
            if not signal_id or signal_id in consumed:
                continue
            try:
                discovered_at = datetime.fromisoformat(str(signal.get("discovered_at") or "")).astimezone(HKT)
            except (TypeError, ValueError):
                discovered_at = now.astimezone(HKT)
            if discovered_at < cutoff:
                expired_signal_ids.append(signal_id)
                continue
            existing = signals.get(signal_id)
            if existing is None or str(signal.get("discovered_at") or "") > str(
                existing.get("discovered_at") or ""
            ):
                signals[signal_id] = signal
    return {
        "signals": list(signals.values()),
        "empty_event_ids": empty_event_ids,
        "expired_signal_ids": expired_signal_ids,
    }


def commit_signal_attempts(
    state: dict[str, Any],
    attempted_signal_ids: list[str],
    passed_signal_ids: list[str],
    expired_signal_ids: list[str],
    *,
    max_attempts: int = 4,
) -> dict[str, Any]:
    """Update retry counters only after the 07:30/14:00 scan completes."""
    attempts = state.get("scheduled_crawl_signal_attempts")
    if not isinstance(attempts, dict):
        attempts = {}
    consumed = list(state.get("scheduled_crawl_consumed_signal_ids") or [])
    consumed_set = {str(item) for item in consumed if str(item)}
    passed = {str(item) for item in passed_signal_ids if str(item)}
    expired = {str(item) for item in expired_signal_ids if str(item)}
    for signal_id in attempted_signal_ids:
        signal_id = str(signal_id)
        attempts[signal_id] = int(attempts.get(signal_id) or 0) + 1
        if signal_id in passed or attempts[signal_id] >= max_attempts:
            consumed_set.add(signal_id)
    consumed_set.update(expired)
    attempts = {
        key: value
        for key, value in attempts.items()
        if key not in consumed_set
    }
    state["scheduled_crawl_signal_attempts"] = attempts
    state["scheduled_crawl_consumed_signal_ids"] = sorted(consumed_set)[-3000:]
    return {
        "attempted": len(attempted_signal_ids),
        "passed": len(passed),
        "consumed": len(consumed_set),
        "pending_attempts": len(attempts),
    }
