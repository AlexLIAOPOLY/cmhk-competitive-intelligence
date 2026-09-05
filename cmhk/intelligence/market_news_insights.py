from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from ai_config import INTERNAL_AI_BASE_URL, is_internal_ai_base_url, load_ai_config
from ai_key_rotation import open_llm_request
from ai_rate_limit import reset_internal_ai_priority, set_internal_ai_priority, wait_for_internal_ai_slot
from ai_response_compat import deepseek_nonthinking_parameters, final_chat_message_text
from cmhk.intelligence.agent_harness import assert_finish_reason, run_durable_agent


PROMPT_VERSION = "market-news-insights-v1"


def evidence_hash(items: list[dict]) -> str:
    canonical = [
        {
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or ""),
            "summary": str(item.get("summary") or ""),
            "category": str(item.get("category") or ""),
            "sourceDate": str(item.get("sourceDate") or ""),
            "keywords": str(item.get("keywords") or ""),
        }
        for item in sorted(items, key=lambda value: str(value.get("id") or ""))
    ]
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_path(root: Path) -> Path:
    return root / "strategy_briefing" / "intelligence_map_ai_insights.json"


def load_cached_insights(root: Path, revision: str = "") -> dict | None:
    try:
        payload = json.loads(cache_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    insights = payload.get("insights") if isinstance(payload, dict) else None
    if not isinstance(insights, list) or len(insights) != 4:
        return None
    payload["stale"] = bool(revision and payload.get("evidenceHash") != revision)
    return payload


def _write_cache(root: Path, payload: dict) -> None:
    target = cache_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _context(items: list[dict]) -> dict:
    topic_counts = Counter(str(item.get("category") or "其他情报") for item in items)
    entity_counts = Counter(entity for item in items for entity in (item.get("entities") or []))
    concept_counts = Counter(concept for item in items for concept in (item.get("concepts") or []))
    parsed_dates = [date.fromisoformat(str(item["sourceDate"])) for item in items if item.get("sourceDate")]
    momentum: dict[str, dict[str, int]] = {}
    if parsed_dates:
        coverage_end = max(parsed_dates)
        recent_start = coverage_end - timedelta(days=6)
        previous_start = coverage_end - timedelta(days=13)
        for item in items:
            item_date = date.fromisoformat(str(item["sourceDate"]))
            topic = str(item.get("category") or "其他情报")
            row = momentum.setdefault(topic, {"recent": 0, "previous": 0, "delta": 0})
            if item_date >= recent_start:
                row["recent"] += 1
            elif item_date >= previous_start:
                row["previous"] += 1
        for row in momentum.values():
            row["delta"] = row["recent"] - row["previous"]
    ordered = sorted(items, key=lambda item: (str(item.get("sourceDate") or ""), str(item.get("id") or "")), reverse=True)
    return {
        "approvedCount": len(items),
        "coverage": {"start": min(parsed_dates).isoformat() if parsed_dates else "", "end": max(parsed_dates).isoformat() if parsed_dates else ""},
        "topics": topic_counts.most_common(),
        "topicMomentum": momentum,
        "entities": entity_counts.most_common(12),
        "concepts": concept_counts.most_common(12),
        "latestSignals": [
            {
                "id": item["id"],
                "date": item["sourceDate"],
                "source": item["source"],
                "category": item["category"],
                "title": item["title"],
                "summary": str(item.get("summary") or "")[:220],
                "entities": item.get("entities") or [],
                "concepts": item.get("concepts") or [],
            }
            for item in ordered[:20]
        ],
    }


def _prompt(context: dict, nonce: str) -> str:
    return (
        "你是CMHK市场竞争情报分析员。只依据下面已人工审核的新闻快照，生成恰好4条跨新闻洞察。"
        "分别覆盖近期变化、竞对主体动作、跨新闻关联、风险或弱信号；必须是分析发现，不能只复述计数。"
        "只有topicMomentum中delta>0的议题才可称为升温；不得补写外部背景、因果、市场份额、经营结果或不存在的事实。"
        "每条必须引用1至4个输入中的真实新闻id。输出一个JSON对象，唯一字段insights是长度4的数组；"
        "每项严格包含title、body、evidenceIds。title为2至12字，body为25至90个中文字符，禁止Markdown、序号、模型名和运行说明。"
        f"请求批次{nonce}只用于区分重新分析，不是证据，禁止写入输出。\n"
        f"已审核新闻上下文：{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
    )


def _json_object(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        raise RuntimeError("AI未返回结构化洞察")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise RuntimeError("AI洞察结构无效")
    return value


def _validate_insights(raw: object, allowed_ids: set[str]) -> list[dict[str, object]]:
    if not isinstance(raw, list) or len(raw) != 4:
        raise RuntimeError("AI必须返回4条洞察")
    result: list[dict[str, object]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise RuntimeError("AI洞察条目结构无效")
        title = re.sub(r"[`*_#]", "", str(entry.get("title") or "")).strip()[:24]
        body = re.sub(r"[`*_#]", "", str(entry.get("body") or "")).strip()[:180]
        ids = list(dict.fromkeys(str(value) for value in (entry.get("evidenceIds") or []) if str(value) in allowed_ids))[:4]
        if not (2 <= len(title) <= 24 and 10 <= len(body) <= 180 and ids):
            raise RuntimeError("AI洞察缺少有效标题、正文或新闻证据")
        result.append({"title": title, "body": body, "evidenceIds": ids})
    return result


def generate_market_news_insights(
    root: Path,
    *,
    force: bool = False,
    requested_revision: str = "",
    generation_nonce: str = "",
    stream_callback: Callable[[dict], object] | None = None,
) -> dict:
    from cmhk.intelligence.competitor_map import build_competitor_intelligence_map

    snapshot = build_competitor_intelligence_map(root)
    items = snapshot.get("items") or []
    revision = evidence_hash(items)
    if requested_revision and requested_revision != revision:
        raise ValueError("情报已更新，请再次点击AI情报洞察")
    cached = load_cached_insights(root, revision)
    if not force and cached and not cached.get("stale"):
        return {**cached, "cached": True}
    if not items:
        raise ValueError("当前没有可供分析的已审核新闻")

    config = load_ai_config(include_key=True)
    base_url = str(config.get("base_url") or INTERNAL_AI_BASE_URL).strip().rstrip("/")
    api_key = str(config.get("api_key") or "").strip()
    model = str(config.get("model") or "").strip()
    if not base_url or not api_key or not model or not is_internal_ai_base_url(base_url):
        raise RuntimeError("AI配置不完整")
    nonce = generation_nonce or (datetime.now().isoformat() if force else revision)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "严格依据用户提供的已审核新闻JSON做分析，并严格输出指定JSON。"},
            {"role": "user", "content": _prompt(_context(items), nonce)},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    body.update(config.get("extra_parameters") or {})
    body = deepseek_nonthinking_parameters(body)
    body["max_tokens"] = 4096
    body["stream"] = False
    body["cache"] = {"no-cache": True, "no-store": True}

    def execute(attempt: int) -> list[dict]:
        request_body = {**body, "max_tokens": min(16384, 4096 * (2 ** attempt)),
                        "messages": [dict(message) for message in body["messages"]]}
        if attempt:
            request_body["messages"][0]["content"] += (
                f" 输出恢复请求{attempt}：仅返回完整的四条洞察JSON，不输出思考过程。"
            )
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        priority = set_internal_ai_priority("interactive")
        try:
            if stream_callback:
                stream_callback({"type": "status", "message": "内部AI正在分析已审核新闻"})
            wait_for_internal_ai_slot("market-news-insights")
            with open_llm_request(request, timeout=90, config=config,
                                  requested_key=api_key, model=model) as response:
                upstream = json.loads(response.read().decode("utf-8"))
        finally:
            reset_internal_ai_priority(priority)
        assert_finish_reason((upstream.get("choices") or [{}])[0].get("finish_reason", ""))
        text = final_chat_message_text(upstream, operation="市场新闻AI洞察")
        return _validate_insights(_json_object(text).get("insights"), {str(item["id"]) for item in items})

    insights = run_durable_agent(namespace="market-news-insights", directory=cache_path(root).parent / "harness",
        identity={"revision": revision, "prompt": PROMPT_VERSION, "nonce": nonce, "model": model, "base_url": base_url},
        execute=execute)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    result = {
        "ok": True,
        "evidenceHash": revision,
        "promptVersion": PROMPT_VERSION,
        "generatedAt": generated_at,
        "model": model,
        "insights": insights,
    }
    _write_cache(root, result)
    if stream_callback:
        normalized = "\n".join(f"{item['title']}｜{item['body']}" for item in insights)
        for offset in range(0, len(normalized), 18):
            stream_callback({"type": "delta", "text": normalized[offset : offset + 18]})
    return result
