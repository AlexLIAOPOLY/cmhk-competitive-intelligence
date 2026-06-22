from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MEMORY_DIR = ROOT / "agent_knowledge" / "agent_operational_memory"
MEMORY_PATH = MEMORY_DIR / "memories.jsonl"
MANIFEST_PATH = MEMORY_DIR / "manifest.json"
README_PATH = MEMORY_DIR / "README.md"


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,}", text or "")}


def _query_terms(text: str) -> list[str]:
    terms = [item.lower() for item in re.findall(r"[A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}", text or "")]
    cn = re.findall(r"[\u4e00-\u9fff]{2,}", text or "")
    for block in cn:
        terms.extend(block[i : i + 2] for i in range(max(0, len(block) - 1)))
        terms.extend(block[i : i + 3] for i in range(max(0, len(block) - 2)))
    return list(dict.fromkeys(term for term in terms if term))


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
                    "updated_at": "2026-06-20",
                    "quality": "Agent 运行辅助记忆；正式数据结论仍以已选择数据库和审计文件为准。",
                    "visibility": "hidden",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if not README_PATH.exists():
        README_PATH.write_text(
            "# 小竞AI生产运行记忆\n\n"
            "该目录保存 agent 运行辅助记忆。记忆只用于召回用户偏好、生产规则、数据边界和已验证流程，"
            "不得替代正式数据库、官方来源、审计结果或用户本轮明确指令。\n",
            encoding="utf-8",
        )
    MEMORY_PATH.touch(exist_ok=True)


def load_memories(limit: int | None = None) -> list[dict[str, Any]]:
    _ensure_store()
    rows: list[dict[str, Any]] = []
    for line in MEMORY_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict) and item.get("content"):
            rows.append(item)
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


def add_memory(content: str, *, kind: str = "semantic", tags: list[str] | None = None, source: str = "agent") -> dict[str, Any]:
    _ensure_store()
    clean = re.sub(r"\s+", " ", str(content or "")).strip()
    if not clean:
        raise ValueError("memory content is empty")
    now = time.time()
    item = {
        "id": f"mem_{int(now * 1000)}",
        "kind": kind,
        "content": clean[:1200],
        "tags": [str(tag).strip() for tag in (tags or []) if str(tag).strip()][:12],
        "source": source,
        "created_at": now,
        "created_date": time.strftime("%Y-%m-%d", time.localtime(now)),
    }
    with MEMORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def search_memories(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    query_terms = _query_terms(query)
    rows = load_memories()
    scored: list[tuple[float, dict[str, Any]]] = []
    now = time.time()
    for item in rows:
        text = " ".join([str(item.get("content") or ""), " ".join(item.get("tags") or []), str(item.get("kind") or "")])
        overlap = len(query_tokens & _tokens(text))
        substring_hits = sum(1 for term in query_terms if term and term in text.lower())
        if overlap <= 0 and substring_hits <= 0 and query_tokens:
            continue
        age_days = max(0.0, (now - float(item.get("created_at") or now)) / 86400)
        recency = max(0.0, 2.0 - min(age_days, 60) / 30)
        score = overlap * 10 + substring_hits * 3 + recency
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[: max(1, min(limit, 10))]]


def memory_context(query: str, *, limit: int = 5) -> str:
    rows = search_memories(query, limit=limit)
    if not rows:
        return ""
    lines = ["【长期记忆召回】以下为本地可审计运行记忆；用户本轮指令、正式数据库和审计结果优先级更高。"]
    for index, item in enumerate(rows, 1):
        tags = "、".join(item.get("tags") or [])
        lines.append(f"{index}. {item.get('content')}（kind={item.get('kind')}; tags={tags or '无'}; date={item.get('created_date')}）")
    return "\n".join(lines)


def auto_capture_user_memory(message: str) -> dict[str, Any] | None:
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if not text:
        return None
    cues = ["记住", "以后", "默认", "不要", "每次", "偏好", "规则", "必须"]
    if not any(cue in text for cue in cues):
        return None
    if len(text) > 900:
        return None
    return add_memory(text, kind="procedural", tags=["user-preference", "auto-captured"], source="user-message")
