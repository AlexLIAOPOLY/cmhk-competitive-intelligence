"""A reader-owned, versioned brief; free prose, independent of editorial categories."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from cmhk.services.news_topics import normalize_news_topics
from cmhk.services.news_text import simplified_news_text


def normalize_personal_skill(value, *, strict=False):
    try:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = [value]  # One prose instruction is equivalent to one list item.
            if isinstance(value, str):
                value = [value]
        if value is None:
            if strict:
                raise ValueError('个人阅读要求不能是null')
            value = []
        if (not isinstance(value, list) or len(value) > 30 or
                any(not isinstance(p, str) or not 1 <= len(p.strip()) <= 300 for p in value)):
            raise ValueError('个人阅读要求应为简短的逐条说明。')
        return list(dict.fromkeys(simplified_news_text(p).strip() for p in value))
    except (ValueError, TypeError):
        if strict:
            raise ValueError('个人阅读要求格式无效，请直接描述你希望怎样安排内容。') from None
        return []


def skill_revision(points):
    return hashlib.sha256(json.dumps(normalize_personal_skill(points), ensure_ascii=False).encode()).hexdigest()


def legacy_topic_skill(topics):
    return [f"优先关注{topic['name']}相关的内容。" for topic in normalize_news_topics(topics)]


def skill_markdown(points):
    return '# 个人阅读要求\n\n' + '\n'.join(f'{i}. {p}' for i,p in enumerate(normalize_personal_skill(points),1)) + '\n'


def owner_directory(root, profile, open_id):
    owner = hashlib.sha256(f'{profile}\0{open_id}'.encode()).hexdigest()
    return Path(root) / 'var/subscriptions/personal-news-skills' / owner


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temp.replace(path)


def export_personal_skill(root, profile, open_id, points):
    directory = owner_directory(root, profile, open_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'SKILL.md'
    text = skill_markdown(points)
    if not target.exists() or target.read_text() != text:
        temp = target.with_suffix(f'.{os.getpid()}.tmp')
        temp.write_text(text); temp.replace(target)
    return target


def last_allocation(root, profile, open_id):
    try:
        value = json.loads((owner_directory(root, profile, open_id) / 'last-selection.json').read_text())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None
