from __future__ import annotations

import copy
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import news_discovery_digest as digest
import news_vote_service


_original_build_cards = digest._build_cards
_news_id_pattern = re.compile(r"<font color='grey'>([^<>]+)</font>")


def _vote_button(label: str, decision: str, news_id: str, button_type: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": button_type,
        "value": {
            "action": "news_vote",
            "decision": decision,
            "news_id": news_id,
        },
    }


def _normalized_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"\s*[-–—|｜]\s*[^-–—|｜]{1,32}$", "", text)
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


def _canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = urlencode(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"oc", "gclid"}
        )
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))
    except Exception:
        return url


def _curate_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    kept: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    duplicate_count = 0
    for item in items:
        title_key = _normalized_title(str(item.get("title", "")))
        url_key = _canonical_url(str(item.get("url", "")))
        duplicate = bool(url_key and url_key in seen_urls)
        if not duplicate and title_key:
            duplicate = any(
                title_key == previous
                or (
                    min(len(title_key), len(previous)) >= 16
                    and SequenceMatcher(None, title_key, previous).ratio() >= 0.90
                )
                for previous in seen_titles
            )
        if duplicate:
            duplicate_count += 1
            continue
        kept.append(item)
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.append(title_key)
    return kept, {
        "original": len(items),
        "kept": len(kept),
        "duplicates": duplicate_count,
        "noise": 0,
    }


def _inject_vote_controls(card: dict[str, Any]) -> dict[str, Any]:
    card = copy.deepcopy(card)
    current_news_id = ""
    for element in card.get("elements", []):
        if element.get("tag") == "div":
            content = str(element.get("text", {}).get("content", ""))
            matches = _news_id_pattern.findall(content)
            if matches:
                current_news_id = matches[-1].strip()
        elif element.get("tag") == "action" and current_news_id:
            actions = element.setdefault("actions", [])
            if not any((action.get("value") or {}).get("action") == "news_vote" for action in actions):
                actions.extend(
                    [
                        _vote_button("确认进入滚动", "approve", current_news_id, "primary"),
                        _vote_button("暂缓", "hold", current_news_id, "default"),
                        _vote_button("不采纳", "reject", current_news_id, "danger"),
                    ]
                )
            current_news_id = ""
    for element in card.get("elements", []):
        if element.get("tag") == "note":
            notes = element.get("elements", [])
            if notes:
                notes[0]["content"] = (
                    "确认操作按成员分别记录，可重复点击修改个人选择；"
                    "多人结果不会由第一位点击者直接决定。"
                )
    return card


def _build_cards_with_votes(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    call_kwargs = dict(kwargs)
    source_items = list(call_kwargs.get("items", []))
    curated, stats = _curate_items(source_items)
    call_kwargs["items"] = curated
    cards = [_inject_vote_controls(card) for card in _original_build_cards(*args, **call_kwargs)]
    if cards:
        for element in cards[0].get("elements", []):
            if element.get("tag") == "div":
                text = element.get("text", {})
                text["content"] = (
                    text.get("content", "")
                    + f"\n<font color='grey'>原始检索 {stats['original']} 条；仅去重后 {stats['kept']} 条；"
                    + f"重复 {stats['duplicates']} 条，内容判断全部交由 AI 审核。</font>"
                )
                break
    return cards


digest._build_cards = _build_cards_with_votes


def send_digest(*args: Any, **kwargs: Any) -> dict[str, Any]:
    news_vote_service.ensure_started()
    return digest.send_digest(*args, **kwargs)


def main() -> None:
    news_vote_service.ensure_started()
    digest.main()


def _build_sheet_notice_cards(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    curated, stats = _curate_items(
        [item for item in kwargs.get("items") or [] if isinstance(item, dict)]
    )
    updated = dict(kwargs)
    updated["items"] = curated
    from cmhk.intelligence.news_review_sheet import build_notice_cards

    return build_notice_cards(*args, curation_stats=stats, **updated)


def send_digest(*args: Any, **kwargs: Any) -> dict[str, Any]:
    digest._build_cards = _build_sheet_notice_cards
    return digest.send_digest(*args, **kwargs)


def main() -> None:
    digest._build_cards = _build_sheet_notice_cards
    digest.main()


if __name__ == "__main__":
    main()
