"""Personal topic preferences and evidence-based ranking inside reviewed news pools."""
from __future__ import annotations

import json
import re

from cmhk.services.news_text import simplified_news_text


def topic_key(name: str) -> str:
    key = simplified_news_text(name).strip().casefold()
    if key in {"ai", "人工智能", "人工智能(ai)", "人工智能（ai）"}:
        return "人工智能"
    return key


def normalize_news_topics(value, *, strict=False) -> list[dict]:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        if isinstance(value, dict):
            value = [value]  # A single well-formed topic is equivalent to a one-item list.
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 12:
            raise ValueError("最多保存12个关注主题。")
        result = {}
        for item in value:
            if not isinstance(item, dict) or set(item) != {"name", "terms"}:
                raise ValueError("关注主题需要名称及相关词。")
            name, terms = item["name"], item["terms"]
            if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 40
                    or not isinstance(terms, list) or not 1 <= len(terms) <= 12
                    or any(not isinstance(t, str) or not 2 <= len(t.strip()) <= 40 for t in terms)):
                raise ValueError("请使用简短、具体的关注主题。")
            if any(any(not part.strip() for part in term.split("&")) for term in terms):
                raise ValueError("相关词不可包含空条件。")
            key = topic_key(name)
            name = "人工智能（AI）" if key == "人工智能" else simplified_news_text(name).strip()
            terms = [simplified_news_text(t).strip() for t in terms]
            if key == "人工智能":
                terms = ["人工智能", "AI", "大模型", "机器学习", "生成式AI", "智能体", *terms]
            result[key] = {"name": name, "terms": list(dict.fromkeys(terms))[:12]}
        return list(result.values())
    except (ValueError, TypeError):
        if strict:
            raise ValueError("关注主题格式无效，请用一句话描述感兴趣的内容。") from None
        return []


def topic_score(item: dict, topics) -> int:
    text = simplified_news_text(" ".join(str(item.get(k) or "") for k in
        ("title", "summary", "digest_summary", "source_excerpt", "content"))).casefold()
    def matches(term):
        term = term.casefold()
        if "&" in term:
            return all(matches(part.strip()) for part in term.split("&") if part.strip())
        if re.fullmatch(r"[a-z0-9 +.\-]+", term):
            return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
        return term in text
    return sum(any(matches(t) for t in [topic["name"], *topic["terms"]])
               for topic in normalize_news_topics(topics))
