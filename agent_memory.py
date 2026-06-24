from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MEMORY_DIR = ROOT / "agent_knowledge" / "agent_operational_memory"
MEMORY_PATH = MEMORY_DIR / "memories.jsonl"
MANIFEST_PATH = MEMORY_DIR / "manifest.json"
README_PATH = MEMORY_DIR / "README.md"
VALID_KINDS = {"semantic", "episodic", "procedural"}
VALID_STATUSES = {"active", "superseded", "archived"}
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "用户",
    "记忆",
    "规则",
    "默认",
    "以后",
    "必须",
    "不要",
}


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,}", text or "")}


def _token_counts(text: str) -> Counter[str]:
    return Counter(
        token
        for token in _query_terms(text)
        if token and token not in STOPWORDS and len(token) >= 2
    )


def _query_terms(text: str) -> list[str]:
    terms = [item.lower() for item in re.findall(r"[A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}", text or "")]
    cn = re.findall(r"[\u4e00-\u9fff]{2,}", text or "")
    for block in cn:
        terms.extend(block[i : i + 2] for i in range(max(0, len(block) - 1)))
        terms.extend(block[i : i + 3] for i in range(max(0, len(block) - 2)))
    return list(dict.fromkeys(term for term in terms if term))


def _normalize_kind(kind: str | None) -> str:
    clean = str(kind or "semantic").strip().lower()
    return clean if clean in VALID_KINDS else "semantic"


def _clamp_float(value: Any, default: float, lower: float, upper: float) -> float:
    try:
        number = float(value)
    except Exception:
        number = default
    return max(lower, min(upper, number))


def _extract_entities(text: str, tags: list[str] | None = None) -> list[str]:
    raw: list[str] = []
    raw.extend(re.findall(r"\b[A-Z][A-Za-z0-9&._-]{1,}(?:\s+[A-Z][A-Za-z0-9&._-]{1,}){0,4}", text or ""))
    raw.extend(re.findall(r"[\u4e00-\u9fff]{2,12}", text or ""))
    raw.extend(str(tag) for tag in (tags or []) if str(tag).strip())
    entities: list[str] = []
    seen: set[str] = set()
    for item in raw:
        clean = re.sub(r"\s+", " ", str(item or "")).strip(" ，,。；;:：()[]【】")
        if not clean:
            continue
        key = clean.lower()
        if key in seen or key in STOPWORDS:
            continue
        seen.add(key)
        entities.append(clean[:80])
        if len(entities) >= 16:
            break
    return entities


def _fingerprint(content: str, kind: str, tags: list[str] | None = None) -> str:
    normalized = re.sub(r"\s+", " ", str(content or "")).strip().lower()
    tag_text = ",".join(sorted(str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()))
    import hashlib

    return hashlib.sha256(f"{kind}\n{tag_text}\n{normalized}".encode("utf-8")).hexdigest()[:16]


def _ensure_store() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST_PATH.exists():
        MANIFEST_PATH.write_text(
            json.dumps(
                {
                    "id": "agent_operational_memory",
                    "title": "小竞AI生产运行记忆",
                    "summary": "本地可审计长期记忆，保存用户偏好、生产规则、数据边界和已验证工作流。",
                    "source_type": "local_agent_memory",
                    "scope": "用于小竞AI和项目内 agent 的跨会话运行上下文，不替代正式数据源。",
                    "tags": ["agent-memory", "production", "context-management"],
                    "keywords": ["memory", "context", "token", "小竞AI", "生产规则"],
                    "entrypoints": ["README.md", "memories.jsonl"],
                    "updated_at": "2026-06-23",
                    "quality": "Agent 运行辅助记忆；正式数据结论仍以已选择数据库和审计文件为准。",
                    "visibility": "hidden",
                    "schema_version": 2,
                    "retrieval": "hybrid_keyword_phrase_entity_recency_importance",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            manifest = {}
        if isinstance(manifest, dict):
            changed = False
            for key, value in {
                "updated_at": "2026-06-23",
                "schema_version": 2,
                "retrieval": "hybrid_keyword_phrase_entity_recency_importance",
            }.items():
                if manifest.get(key) != value:
                    manifest[key] = value
                    changed = True
            if changed:
                MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not README_PATH.exists():
        README_PATH.write_text(
            "# 小竞AI生产运行记忆\n\n"
            "该目录保存 agent 运行辅助记忆。记忆只用于召回用户偏好、生产规则、数据边界和已验证流程，"
            "不得替代正式数据库、官方来源、审计结果或用户本轮明确指令。\n\n"
            "## 记忆类型\n\n"
            "- semantic：稳定事实、偏好、长期约束。\n"
            "- episodic：已完成任务、故障处理、验证过的运行经历。\n"
            "- procedural：可复用流程、检查清单、默认执行规则。\n\n"
            "每条记录带有实体、重要度、置信度、状态、来源和访问统计，便于审计和失效处理。\n",
            encoding="utf-8",
        )
    MEMORY_PATH.touch(exist_ok=True)


def _upgrade_memory(item: dict[str, Any]) -> dict[str, Any]:
    tags = [str(tag).strip() for tag in (item.get("tags") or []) if str(tag).strip()][:12]
    kind = _normalize_kind(item.get("kind"))
    content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
    created_at = _clamp_float(item.get("created_at"), time.time(), 0, time.time() + 86400)
    upgraded = dict(item)
    upgraded.update(
        {
            "schema_version": 2,
            "kind": kind,
            "content": content,
            "tags": tags,
            "status": str(item.get("status") or "active") if str(item.get("status") or "active") in VALID_STATUSES else "active",
            "importance": _clamp_float(item.get("importance"), 0.5, 0.0, 1.0),
            "confidence": _clamp_float(item.get("confidence"), 0.8, 0.0, 1.0),
            "entities": [str(entity).strip() for entity in (item.get("entities") or _extract_entities(content, tags)) if str(entity).strip()][:16],
            "created_at": created_at,
            "created_date": item.get("created_date") or time.strftime("%Y-%m-%d", time.localtime(created_at)),
            "updated_at": float(item.get("updated_at") or created_at),
            "last_accessed_at": float(item.get("last_accessed_at") or 0),
            "access_count": int(item.get("access_count") or 0),
            "fingerprint": item.get("fingerprint") or _fingerprint(content, kind, tags),
        }
    )
    return upgraded


def load_memories(limit: int | None = None, *, include_archived: bool = False) -> list[dict[str, Any]]:
    _ensure_store()
    rows: list[dict[str, Any]] = []
    for line in MEMORY_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict) and item.get("content"):
            upgraded = _upgrade_memory(item)
            if include_archived or upgraded.get("status") != "archived":
                rows.append(upgraded)
    rows.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    return rows[:limit] if limit else rows


def delete_memory(memory_id: str) -> bool:
    _ensure_store()
    target = str(memory_id or "").strip()
    if not target:
        return False
    rows = load_memories()
    kept = [item for item in rows if item.get("id") != target]
    if len(kept) == len(rows):
        return False
    kept.sort(key=lambda item: float(item.get("created_at") or 0))
    with MEMORY_PATH.open("w", encoding="utf-8") as handle:
        for item in kept:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return True


def _rewrite_memories(rows: list[dict[str, Any]]) -> None:
    rows = _dedupe_memory_rows(rows)
    rows.sort(key=lambda item: float(item.get("created_at") or 0))
    with MEMORY_PATH.open("w", encoding="utf-8") as handle:
        for item in rows:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _dedupe_memory_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for raw in rows:
        item = _upgrade_memory(raw)
        fingerprint = str(item.get("fingerprint") or "")
        status = str(item.get("status") or "active")
        if not fingerprint or status != "active":
            passthrough.append(item)
            continue
        key = (status, fingerprint)
        current = merged.get(key)
        if current is None:
            merged[key] = item
            continue
        keep, drop = (current, item)
        if float(item.get("created_at") or 0) > float(current.get("created_at") or 0):
            keep, drop = item, current
        keep["importance"] = max(float(keep.get("importance") or 0), float(drop.get("importance") or 0))
        keep["confidence"] = max(float(keep.get("confidence") or 0), float(drop.get("confidence") or 0))
        keep["access_count"] = int(keep.get("access_count") or 0) + int(drop.get("access_count") or 0)
        keep["last_accessed_at"] = max(float(keep.get("last_accessed_at") or 0), float(drop.get("last_accessed_at") or 0))
        keep["updated_at"] = max(float(keep.get("updated_at") or 0), float(drop.get("updated_at") or 0))
        keep["tags"] = list(dict.fromkeys([*(keep.get("tags") or []), *(drop.get("tags") or [])]))[:12]
        keep["entities"] = list(dict.fromkeys([*(keep.get("entities") or []), *(drop.get("entities") or [])]))[:16]
        keep["schema_version"] = 2
        keep.setdefault("merged_memory_ids", [])
        keep["merged_memory_ids"] = list(dict.fromkeys([*(keep.get("merged_memory_ids") or []), str(drop.get("id") or "")]))[:50]
        merged[key] = keep
    return [*merged.values(), *passthrough]


def compact_memory_store() -> dict[str, int]:
    _ensure_store()
    rows = load_memories(include_archived=True)
    before = len(rows)
    compacted = _dedupe_memory_rows(rows)
    _rewrite_memories(compacted)
    return {"before": before, "after": len(compacted), "removed": max(0, before - len(compacted))}


def add_memory(
    content: str,
    *,
    kind: str = "semantic",
    tags: list[str] | None = None,
    source: str = "agent",
    importance: float = 0.5,
    confidence: float = 0.8,
    source_ref: str = "",
) -> dict[str, Any]:
    _ensure_store()
    clean = re.sub(r"\s+", " ", str(content or "")).strip()
    if not clean:
        raise ValueError("memory content is empty")
    clean_kind = _normalize_kind(kind)
    clean_tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()][:12]
    fingerprint = _fingerprint(clean[:1200], clean_kind, clean_tags)
    now = time.time()
    rows = load_memories(include_archived=True)
    for existing in rows:
        if existing.get("fingerprint") == fingerprint and existing.get("status") == "active":
            existing["updated_at"] = now
            existing["importance"] = max(float(existing.get("importance") or 0), _clamp_float(importance, 0.5, 0, 1))
            existing["confidence"] = max(float(existing.get("confidence") or 0), _clamp_float(confidence, 0.8, 0, 1))
            existing["source"] = source or existing.get("source") or "agent"
            if source_ref:
                existing["source_ref"] = source_ref[:500]
            existing["tags"] = list(dict.fromkeys([*(existing.get("tags") or []), *clean_tags]))[:12]
            existing["entities"] = list(dict.fromkeys([*(existing.get("entities") or []), *_extract_entities(clean, clean_tags)]))[:16]
            existing["schema_version"] = 2
            _rewrite_memories(rows)
            return existing
    item = {
        "id": f"mem_{int(now * 1000)}",
        "schema_version": 2,
        "kind": clean_kind,
        "content": clean[:1200],
        "tags": clean_tags,
        "entities": _extract_entities(clean, clean_tags),
        "source": source,
        "source_ref": str(source_ref or "")[:500],
        "status": "active",
        "importance": _clamp_float(importance, 0.5, 0.0, 1.0),
        "confidence": _clamp_float(confidence, 0.8, 0.0, 1.0),
        "fingerprint": fingerprint,
        "created_at": now,
        "updated_at": now,
        "last_accessed_at": 0,
        "access_count": 0,
        "created_date": time.strftime("%Y-%m-%d", time.localtime(now)),
    }
    with MEMORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def _score_memory(query: str, item: dict[str, Any], now: float) -> float:
    text = " ".join(
        [
            str(item.get("content") or ""),
            " ".join(item.get("tags") or []),
            " ".join(item.get("entities") or []),
            str(item.get("kind") or ""),
        ]
    )
    query_counts = _token_counts(query)
    text_counts = _token_counts(text)
    token_score = 0.0
    for token, count in query_counts.items():
        if token in text_counts:
            token_score += min(count, text_counts[token]) * (2.0 + min(len(token), 12) / 6)
    lowered = text.lower()
    query_terms = _query_terms(query)
    phrase_score = sum(1.5 for term in query_terms if len(term) >= 3 and term in lowered)
    query_entities = {entity.lower() for entity in _extract_entities(query)}
    item_entities = {str(entity).lower() for entity in (item.get("entities") or [])}
    entity_score = len(query_entities & item_entities) * 8
    kind = str(item.get("kind") or "")
    kind_score = 0.0
    if ("怎么" in query or "流程" in query or "规则" in query) and kind == "procedural":
        kind_score += 6
    if ("之前" in query or "上次" in query or "完成" in query) and kind == "episodic":
        kind_score += 6
    if ("偏好" in query or "是什么" in query or "默认" in query) and kind == "semantic":
        kind_score += 4
    age_days = max(0.0, (now - float(item.get("updated_at") or item.get("created_at") or now)) / 86400)
    recency_score = max(0.0, 4.0 - min(age_days, 90) / 22.5)
    importance_score = float(item.get("importance") or 0.5) * 5
    confidence_score = float(item.get("confidence") or 0.8) * 3
    access_score = min(int(item.get("access_count") or 0), 10) * 0.25
    status_penalty = -100 if item.get("status") != "active" else 0
    return token_score + phrase_score + entity_score + kind_score + recency_score + importance_score + confidence_score + access_score + status_penalty


def _mark_accessed(memory_ids: set[str]) -> None:
    if not memory_ids:
        return
    rows = load_memories(include_archived=True)
    now = time.time()
    changed = False
    for item in rows:
        if item.get("id") in memory_ids:
            item["last_accessed_at"] = now
            item["access_count"] = int(item.get("access_count") or 0) + 1
            changed = True
    if changed:
        _rewrite_memories(rows)


def search_memories(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    rows = [item for item in load_memories() if item.get("status") == "active"]
    scored: list[tuple[float, dict[str, Any]]] = []
    now = time.time()
    for item in rows:
        score = _score_memory(query, item, now)
        if score <= 0 and _tokens(query):
            continue
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected = [dict(item, score=round(score, 2)) for score, item in scored[: max(1, min(limit, 10))]]
    _mark_accessed({str(item.get("id")) for item in selected if item.get("id")})
    return selected


def memory_context(query: str, *, limit: int = 5) -> str:
    rows = search_memories(query, limit=limit)
    if not rows:
        return ""
    lines = ["【长期记忆召回】以下为本地可审计运行记忆；用户本轮指令、正式数据库和审计结果优先级更高。"]
    for index, item in enumerate(rows, 1):
        tags = "、".join(item.get("tags") or [])
        entities = "、".join(item.get("entities") or [])
        lines.append(
            f"{index}. {item.get('content')}（kind={item.get('kind')}; tags={tags or '无'}; "
            f"entities={entities or '无'}; importance={item.get('importance')}; confidence={item.get('confidence')}; "
            f"date={item.get('created_date')}）"
        )
    return "\n".join(lines)


def auto_capture_user_memory(message: str) -> dict[str, Any] | None:
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if not text:
        return None
    lowered = text.lower()
    synthetic_test_terms = ["前台发送测试", "只回复 ok", "不要调用工具", "test prompt", "synthetic test"]
    if any(term in lowered for term in synthetic_test_terms):
        return None
    history_query_terms = ["历史聊天", "聊天记录", "之前聊天", "此前聊天", "上一轮", "早先"]
    history_read_terms = ["查", "查询", "搜索", "回答", "是什么", "说过什么", "命中", "序号"]
    if any(term in text for term in history_query_terms) and any(term in text for term in history_read_terms):
        return None
    memory_terms = ["长期记忆", "记忆条目", "agent memory", "memory"]
    read_only_terms = ["列出", "查看", "查询", "搜索", "说明", "展示", "当前", "多少", "数量", "详情", "kind", "entities", "access_count"]
    if any(term.lower() in lowered for term in memory_terms) and any(term in text for term in read_only_terms):
        return None
    cues = ["记住", "以后", "默认", "不要", "每次", "偏好", "规则", "必须", "流程"]
    if not any(cue in text for cue in cues):
        return None
    if len(text) > 900:
        return None
    kind = "procedural" if any(cue in text for cue in ["以后", "默认", "不要", "每次", "规则", "必须", "流程"]) else "semantic"
    return add_memory(
        text,
        kind=kind,
        tags=["user-preference", "auto-captured"],
        source="user-message",
        importance=0.8,
        confidence=0.9,
    )
