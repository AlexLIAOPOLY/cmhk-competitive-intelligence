"""Source-bound editorial pass for subscription digests; cache before sending."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from cmhk.services.news_push_skill import skill_contract

EDITOR_VERSION = 8



def _validate(result: Any, items: list[dict]) -> dict:
    if not isinstance(result, dict):
        raise ValueError('新闻编辑结果无效')
    rows = result.get('items')
    if not isinstance(rows, list) or len(rows) != len(items):
        raise ValueError('新闻编辑返回条数不完整')
    enriched = []
    for index, (item, row) in enumerate(zip(items, rows)):
        if not isinstance(row, dict) or row.get('id') != str(index):
            raise ValueError('新闻编辑返回标识不匹配')
        summary = row.get('summary')
        if not isinstance(summary, str) or not 20 <= len(summary.strip()) <= 500:
            raise ValueError('新闻摘要缺失或超长')
        # Keep editorial instructions out of the reader-facing news introduction.
        editorial_markers = (
            '不能写成', '应分开看', '应把团体倡议', '阅读这类观点',
            '本条现有摘录', '现有材料未提供', '原始报道未披露',
            '原始报道未提供', '原始来源未提供', '原文未披露',
            '不能据此视为', '需要区分两层含义',
        )
        if any(marker in summary for marker in editorial_markers):
            raise ValueError('新闻简介混入编辑提醒，须依据事件事实重写')
        enriched.append({**item, 'digest_summary': summary.strip()})
    return {'skill_hash': skill_contract()[1], 'items': enriched, 'editor_version': EDITOR_VERSION, 'status': 'model_generated'}


def _reuse_cached_items(inputs: list[dict], cache_dir: Path) -> list[dict] | None:
    """Reuse reviewed prose only for byte-equivalent source evidence, never titles alone."""
    def identity(item):
        return json.dumps({key: value for key, value in item.items() if key != 'id'},
                          ensure_ascii=False, sort_keys=True)
    wanted = {identity(item) for item in inputs}
    found = {}
    # Bound migration/read work to recent complete cards. A miss uses normal AI.
    paths = sorted(cache_dir.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)[:200]
    for path in paths:
        try:
            cached = json.loads(path.read_text())
            if (cached.get('editor_version') != EDITOR_VERSION or cached.get('skill_hash') != skill_contract()[1]):
                continue
            sources, rows = cached['inputs'], cached['model_output']['items']
            if len(sources) != len(rows):
                continue
            for source, row in zip(sources, rows):
                key = identity(source)
                if (key in wanted and key not in found and row.get('id') == source.get('id')
                        and isinstance(row.get('summary'), str)):
                    found[key] = row
            if len(found) == len(wanted):
                return [{**found[identity(item)], 'id': item['id']} for item in inputs]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def prepare_digest(payload: Any, runtime_root: Path, *, model_call: Callable | None = None) -> dict:
    items = payload.get('items', []) if isinstance(payload, dict) else payload
    if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
        raise ValueError('新闻推送数据格式无效')
    if not items:
        return {'items': []}
    # Recover source excerpts lost in the legacy delivery queue, matching exact URLs only.
    by_url = {}
    try:
        archive = json.loads((runtime_root / 'strategy_briefing/candidates.json').read_text())
        for record in archive.get('items', []):
            for key in ('source_url', 'url'):
                if record.get(key):
                    by_url[record[key]] = record
    except (OSError, ValueError, TypeError):
        pass
    # Completed-run reviews retain richer excerpts than the public candidate index.
    runs = runtime_root / 'strategy_briefing/runs'
    for path in sorted(runs.glob('*.json'), reverse=True)[:8]:
        try:
            review = json.loads(path.read_text()).get('review_sheet', {})
            for record in review.get('ai_review_items', []):
                for field in ('source_url', 'url'):
                    url = record.get(field)
                    if url and (url not in by_url or not by_url[url].get('source_summary')):
                        by_url[url] = record
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    inputs = []
    for index, item in enumerate(items):
        record = by_url.get(item.get('source_url')) or by_url.get(item.get('url')) or {}
        evidence = {k: str(item.get(k) or record.get(k) or '')[:5000]
                    for k in ('title', 'summary', 'source_summary', 'snippet', 'description',
                              'content', 'source', 'published_at', 'category', 'inclusion_reason')}
        inputs.append({'id': str(index), **evidence,
                       'supporting_sources': item.get('supporting_sources') or record.get('supporting_sources') or []})
    encoded = json.dumps({'version': EDITOR_VERSION, 'skill_hash': skill_contract()[1], 'items': inputs}, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(encoded.encode()).hexdigest()
    target = runtime_root / 'var/subscriptions/news-editor' / f'{key}.json'
    try:
        cached = json.loads(target.read_text())
        # Validate cached output too; retain current titles, URLs, source dates and categories.
        return _validate(cached['model_output'], items)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if model_call is None:
        from strategic_briefing import _call_internal_ai
        model_call = _call_internal_ai
    response_format = {"type": "json_schema", "json_schema": {
        "name": "personal_news_editor", "strict": True,
        "schema": {"type": "object", "additionalProperties": False,
                   "required": ["items"], "properties": {
                       "items": {"type": "array", "minItems": len(items), "maxItems": len(items),
                                 "items": {"type": "object", "additionalProperties": False,
                                           "required": ["id", "summary"],
                                           "properties": {name: {"type": "string"}
                                                          for name in ("id", "summary")}}}}}}}
    reused = _reuse_cached_items(inputs, target.parent)
    if reused:
        result = {'items': reused}
    else:
        result = model_call(skill_contract()[0], json.dumps({'editorial_version': EDITOR_VERSION, 'task': '按少样本示例的字段分工重新撰写：新闻简介直接交代事件事实，不输出编辑提醒、阅读建议或材料缺失清单；不输出综述或AI解析。示例只是写法，不是本次事实。', 'items': inputs}, ensure_ascii=False),
                        max_tokens=max(16000, len(items) * 1200),
                        response_format=response_format,
                        # Long personal digests can exhaust the reasoning/output
                        # allowance. The durable harness retries truncation once
                        # with a larger allowance; preparation runs before send time.
                        deadline_monotonic=time.monotonic() + 360,
                        _structured_response_retries=1)
    prepared = _validate(result, items)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f'.{uuid.uuid4().hex}.tmp')
    temporary.write_text(json.dumps({'inputs': inputs, 'model_output': result, **prepared}, ensure_ascii=False, indent=2))
    os.replace(temporary, target)
    return prepared
