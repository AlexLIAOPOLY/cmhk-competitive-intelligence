"""Source-bound editorial pass for subscription digests; cache before sending."""
from __future__ import annotations

import hashlib
import fcntl
from cmhk.services.news_preparation_budget import acquire_story_lock, deadline as preparation_deadline
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from cmhk.services.news_push_skill import skill_contract, text_model, compatible_skill_hashes
from cmhk.services.news_summary_quality import MAX_SUMMARY_CHARS, SummaryQualityError, enrich_source, repeats_title, review_summaries

from cmhk.services.news_text import simplified_news_text

EDITOR_VERSION = 10



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
        if isinstance(summary, str):
            summary = simplified_news_text(summary)
        if not isinstance(summary, str) or not 20 <= len(summary.strip()) <= MAX_SUMMARY_CHARS:
            raise SummaryQualityError('新闻简介须为20至100字；超长必须重新生成或换稿')
        # Keep editorial instructions out of the reader-facing news introduction.
        editorial_markers = (
            '不能写成', '应分开看', '应把团体倡议', '阅读这类观点',
            '本条现有摘录', '现有材料未提供', '原始报道未披露',
            '原始报道未提供', '原始来源未提供', '原文未披露',
            '不能据此视为', '需要区分两层含义', 'source_content', '无法补充',
        )
        if any(marker in summary for marker in editorial_markers):
            raise SummaryQualityError('新闻简介混入编辑提醒，须依据事件事实重写')
        if repeats_title(item.get('title', ''), summary):
            raise SummaryQualityError('新闻简介与标题重复，须补充原文中的具体事实')
        enriched.append({**item, 'title': simplified_news_text(item.get('title')), 'digest_summary': summary.strip()})
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
            if (cached.get('editor_version') != EDITOR_VERSION or cached.get('skill_hash') not in compatible_skill_hashes()):
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


def prepare_digest(payload: Any, runtime_root: Path, *, model_call: Callable | None = None,
                   _single_response: bool = False) -> dict:
    # One publisher story is edited once across recipients and processes. Do not
    # include recipient category/interest fields in this shared work identity.
    items = payload.get('items', []) if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        return _prepare_digest(payload, runtime_root, model_call=model_call, _single_response=_single_response)
    identity = [{k: item.get(k) for k in ('title', 'news_url', 'source_url', 'summary', 'source_summary', 'source_content')}
                for item in items if isinstance(item, dict)]
    key = hashlib.sha256(json.dumps([EDITOR_VERSION, text_model(), identity], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    directory = runtime_root / 'var/subscriptions/news-editor-locks'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (key + '.lock')).open('a') as lock:
        acquire_story_lock(lock)
        return _prepare_digest(payload, runtime_root, model_call=model_call, _single_response=_single_response)


def _prepare_digest(payload: Any, runtime_root: Path, *, model_call: Callable | None = None,
                    _single_response: bool = False) -> dict:
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
                    for k in ('title', 'summary', 'source_summary', 'snippet', 'description', 'source_url', 'news_url',
                              'content', 'source', 'published_at', 'source_content', 'source_evidence_url',
                              'source_page_title', 'source_page_description')}
        evidence = enrich_source(item, evidence, runtime_root)
        inputs.append({'id': str(index), **evidence,
                       'supporting_sources': item.get('supporting_sources') or record.get('supporting_sources') or []})
    encoded = json.dumps({'version': EDITOR_VERSION, 'model': text_model(), 'skill_hash': skill_contract()[1], 'items': inputs}, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(encoded.encode()).hexdigest()
    target = runtime_root / 'var/subscriptions/news-editor' / f'{key}.json'
    try:
        cached = json.loads(target.read_text())
        # Validate cached output too; retain current titles, URLs, source dates and categories.
        prepared = _validate(cached['model_output'], items)
        prepared['summary_reviews'] = review_summaries(inputs, cached['model_output']['items'], runtime_root)
        return prepared
    except (OSError, ValueError, KeyError, TypeError):
        pass
    from cmhk.services.news_delivery_assets import load, save
    failure_path = target.with_suffix('.failed')
    failure = load(failure_path)
    if failure.get('retry_at', 0) > time.time():
        raise SummaryQualityError(failure['error'])
    if model_call is None:
        from strategic_briefing import _call_internal_ai
        model_call = _call_internal_ai
    recovery = target.with_suffix('.single-items')
    _single_response = len(items) == 1 and (_single_response or recovery.exists())
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
        try:
            result = {'items': reused}
            _validate(result, items)
            review_summaries(inputs, reused, runtime_root)
        except ValueError:
            reused = None
    if not reused:
        from strategic_briefing import AIInvalidStructuredResponse, AIUnstructuredResponse
        from cmhk.intelligence.agent_harness import TruncatedModelOutput
        task = '全部输出简体中文，保留英文专名的大小写。每条简介硬性不超过100字（标点、数字、英文均计入），建议60至90字；必须与标题有区别，补充来源支持的细节。超长须重新生成，不直接截断。按少样本示例的字段分工重新撰写：新闻简介直接交代事件事实，不输出编辑提醒、阅读建议或材料缺失清单；不输出综述或AI解析。示例只是写法，不是本次事实。'
        system = skill_contract()[0]
        payload = {'editorial_version': EDITOR_VERSION, 'task': task, 'items': inputs}
        if _single_response:
            response_format = {'type': 'json_schema', 'json_schema': {
                'name': 'personal_news_editor_single', 'strict': True, 'schema': {
                    'type': 'object', 'additionalProperties': False, 'required': ['id', 'summary'],
                    'properties': {'id': {'type': 'string', 'enum': ['0']}, 'summary': {'type': 'string'}}}}}
            system += '\n本次只编辑唯一一条新闻。输出单个对象，字段 id、summary。禁止输出items数组或转义后的JSON字符串。'
            payload = {'editorial_version': EDITOR_VERSION, 'task': task, 'article': inputs[0]}
        if failure:
            payload.update(revision_attempt=uuid.uuid4().hex, revision_required=failure.get('error', ''))
        try:
            if len(items) > 1 and recovery.exists():
                raise ValueError('继续已记录的逐条编辑恢复')
            for attempt in range(2):
                try:
                    result = model_call(system, json.dumps(payload, ensure_ascii=False),
                                        max_tokens=max(16000, len(items) * 1200), response_format=response_format,
                                        model_override=text_model(), deadline_monotonic=preparation_deadline(),
                                        _structured_response_retries=1)
                except AIInvalidStructuredResponse as exc:
                    # Some gateways retain the skill's items envelope even when
                    # asked for a single object. Accept only a complete one-row
                    # JSON object, preserving every byte of model-written prose.
                    # Truncated/stringified arrays and wrong IDs still fail.
                    try:
                        wrapped = json.loads(exc.content)
                        if (not _single_response or not isinstance(wrapped, dict)
                                or set(wrapped) != {'items'} or not isinstance(wrapped['items'], list)
                                or len(wrapped['items']) != 1 or not isinstance(wrapped['items'][0], dict)
                                or set(wrapped['items'][0]) != {'id', 'summary'}
                                or wrapped['items'][0]['id'] != '0'
                                or not isinstance(wrapped['items'][0]['summary'], str)):
                            raise ValueError('not a complete single response')
                        result = wrapped['items'][0]
                    except (ValueError, KeyError, TypeError):
                        raise exc
                if _single_response or (len(items) == 1 and isinstance(result, dict) and set(result) == {'id', 'summary'}):
                    result = {'items': [result]}
                try:
                    _validate(result, items)
                    review_summaries(inputs, result['items'], runtime_root)
                    break
                except SummaryQualityError as exc:
                    if attempt:
                        raise
                    payload['revision_required'] = str(exc)
                    payload['rejected_summary'] = result['items'][0]['summary']
                    payload['task'] += ' 上次简介未通过长度或事实增量审核；必须控制在100字以内。从原文选具体措施、数据、对象或进展重写，禁止换词复述标题或编造。'
        except (ValueError, AIInvalidStructuredResponse, AIUnstructuredResponse, TruncatedModelOutput) as exc:
            if isinstance(exc, ValueError) and not isinstance(exc, SummaryQualityError) and str(exc) not in {
                    '继续已记录的逐条编辑恢复', '新闻编辑结果无效',
                    '新闻编辑返回条数不完整', '新闻编辑返回标识不匹配'}:
                raise
            if _single_response or isinstance(exc, SummaryQualityError):
                if isinstance(exc, SummaryQualityError):
                    save(failure_path, {'error': str(exc), 'retry_at': time.time() + 900,
                                        'status': 'source_or_summary_rejected'})
                raise
            # A live gateway returned a quoted, malformed items array repeatedly.
            # Regenerate each source as a real model result, never repair prose or
            # fabricate missing rows. Completed single-source results checkpoint.
            target.parent.mkdir(parents=True, exist_ok=True)
            recovery.touch()
            rows = []
            for index, item in enumerate(items):
                one = _prepare_digest([item], runtime_root, model_call=model_call, _single_response=True)
                rows.append({'id': str(index), 'summary': one['items'][0]['digest_summary']})
            result = {'items': rows}
    prepared = _validate(result, items)
    prepared['summary_reviews'] = review_summaries(inputs, result['items'], runtime_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f'.{uuid.uuid4().hex}.tmp')
    temporary.write_text(json.dumps({'inputs': inputs, 'model_output': result, **prepared}, ensure_ascii=False, indent=2))
    os.replace(temporary, target)
    return prepared
