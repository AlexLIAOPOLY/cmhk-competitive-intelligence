from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ai_config import load_ai_config


ROOT = Path(__file__).resolve().parent


def _read_text(path: Path, limit: int = 60000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:limit]


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,}", text or "")}


def _local_ref(source: str) -> str:
    if source in {"weekly_report.docx", "weekly_report_from_word_template.docx", "weekly_report.html", "weekly_report.md"}:
        return f"/outputs/{source}"
    return f"/references/{source}"


def _chunk_text(source: str, text: str, max_chars: int = 1200) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    buffer: list[str] = []
    size = 0
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if size + len(line) > max_chars and buffer:
            chunks.append({"source": source, "text": "\n".join(buffer), "links": [{"label": source, "url": _local_ref(source)}]})
            buffer = []
            size = 0
        buffer.append(line)
        size += len(line)
    if buffer:
        chunks.append({"source": source, "text": "\n".join(buffer), "links": [{"label": source, "url": _local_ref(source)}]})
    return chunks


def _result_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted((ROOT / "results").glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        extracted = data.get("extracted") or {}
        summary = {
            "row": data.get("row"),
            "status": data.get("status"),
            "object": data.get("object"),
            "entities": data.get("entities"),
            "selected_fields": data.get("selected_fields"),
            "extracted": extracted,
            "missing_fields": data.get("missing_fields"),
            "source_urls": data.get("source_urls"),
        }
        links = [{"label": path.name, "url": _local_ref(path.name)}]
        for index, url in enumerate(data.get("source_urls") or [], 1):
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                links.append({"label": f"原始来源 {index}", "url": url})
        chunks.append({"source": path.name, "text": json.dumps(summary, ensure_ascii=False)[:1600], "links": links})
    return chunks


def build_rag_index() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for name in ["weekly_report.md", "final_audit.md", "coverage_report.tsv", "run_log.tsv"]:
        chunks.extend(_chunk_text(name, _read_text(ROOT / name)))
    chunks.extend(_result_chunks())
    return chunks


def retrieve_context(question: str, limit: int = 8) -> list[dict[str, Any]]:
    query_tokens = _tokens(question)
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, chunk in enumerate(build_rag_index()):
        chunk_tokens = _tokens(chunk["text"] + " " + chunk["source"])
        overlap = len(query_tokens & chunk_tokens)
        source_boost = 3 if chunk["source"] == "weekly_report.md" else 0
        if any(key in question for key in ["建议", "风险", "重点", "总结", "摘要", "周报"]):
            source_boost += 2 if chunk["source"] in {"weekly_report.md", "final_audit.md"} else 0
        score = overlap + source_boost
        if score > 0:
            scored.append((score, -index, chunk))
    scored.sort(reverse=True)
    if not scored:
        return build_rag_index()[:limit]
    return [item[2] for item in scored[:limit]]


def citation_markdown(chunks: list[dict[str, Any]], max_items: int = 20) -> str:
    lines: list[str] = []
    for i, chunk in enumerate(chunks):
        links = []
        for link in chunk.get("links", []):
            label = str(link.get("label") or "").strip()
            url = str(link.get("url") or "").strip()
            if label and url:
                links.append(f"[{label}]({url})")
        if links:
            lines.append(f"- [{i+1}] {'，'.join(links)}")
    return "\n".join(lines[:max_items])


def _extract_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def ask_llm_with_rag(question: str) -> dict[str, Any]:
    config = load_ai_config(include_key=True)
    api_key = (os.environ.get("OPENAI_API_KEY") or str(config.get("api_key") or "")).strip()
    if not api_key:
        return {
            "ok": False,
            "configured": False,
            "error": "未配置 API Key，无法调用真正的 LLM。请在页面右上角“AI 设置”里填写并保存。",
            "sources": [],
        }

    provider = str(config.get("provider") or "deepseek").lower()
    model = os.environ.get("OPENAI_MODEL") or str(config.get("model") or "deepseek-v4-flash")
    base_url = str(config.get("base_url") or "https://api.deepseek.com").rstrip("/")
    chunks = retrieve_context(question)
    context = "\n\n".join(
        f"[来源: {chunk['source']}]\n{chunk['text']}" for chunk in chunks
    )[:12000]
    system_prompt = (
        "你是中国移动战略部公开信息监测系统中的 RAG 助手。"
        "只能基于提供的本地周报、爬取结果和审计上下文回答；如果上下文不足，要明确说明。"
        "回答要正式、具体、可执行。涉及建议时，分为重点判断、风险、下一步建议。"
    )
    user_prompt = (
        f"用户问题：{question}\n\n"
        f"本地检索上下文：\n{context}\n\n"
        "请用中文回答。不要编造链接；引用链接由系统在回答末尾追加。"
    )

    if provider == "openai":
        body = {"model": model, "instructions": system_prompt, "input": user_prompt}
        url = f"{base_url or 'https://api.openai.com/v1'}/responses"
    else:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        url = f"{base_url}/chat/completions"

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:800]
        return {"ok": False, "configured": True, "error": f"OpenAI API 调用失败：HTTP {exc.code} {detail}", "sources": []}
    except Exception as exc:
        return {"ok": False, "configured": True, "error": f"OpenAI API 调用失败：{exc}", "sources": []}

    if provider == "openai":
        answer = _extract_output_text(payload)
    else:
        choices = payload.get("choices") or []
        answer = ""
        if choices:
            answer = ((choices[0].get("message") or {}).get("content") or "").strip()
    citations = citation_markdown(chunks)
    if citations:
        answer = f"{answer}\n\n---\n\n**引用来源：**\n{citations}"
    return {
        "ok": bool(answer),
        "configured": True,
        "model": model,
        "provider": provider,
        "content": answer or "模型没有返回可用文本。",
        "sources": [chunk["source"] for chunk in chunks],
    }


def stream_llm_with_rag(question: str):
    config = load_ai_config(include_key=True)
    api_key = (os.environ.get("OPENAI_API_KEY") or str(config.get("api_key") or "")).strip()
    if not api_key:
        yield {"type": "error", "text": "未配置 API Key，请在 AI 助手弹窗里的“设置”中填写并保存。"}
        return

    provider = str(config.get("provider") or "deepseek").lower()
    model = os.environ.get("OPENAI_MODEL") or str(config.get("model") or "deepseek-v4-flash")
    base_url = str(config.get("base_url") or "https://api.deepseek.com").rstrip("/")
    
    yield {"type": "process", "step": "检索", "text": "开始从本地文档和爬取结果中进行 RAG 检索..."}
    chunks = retrieve_context(question)
    yield {"type": "process", "step": "完成", "text": f"检索完成，共找到 {len(chunks)} 个相关片段。"}
    
    meta_links = []
    seen_urls = set()
    for chunk in chunks:
        for link in chunk.get("links", []):
            url = link.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                meta_links.append(link)
                
    yield {"type": "meta", "model": model, "provider": provider, "sources": [chunk["source"] for chunk in chunks], "links": meta_links}
    
    context_parts = []
    for i, chunk in enumerate(chunks):
        context_parts.append(f"[来源 {i+1}: {chunk['source']}]\n{chunk['text']}")
    context = "\n\n".join(context_parts)[:12000]
    
    system_prompt = (
        "你是中国移动战略部公开信息监测系统中的 RAG 助手。"
        "只能基于提供的本地周报、爬取结果和审计上下文回答；如果上下文不足，要明确说明。"
        "回答要正式、具体、可执行。涉及建议时，分为：重点判断、风险、下一步建议。"
        "请使用清晰 Markdown：二级标题、编号列表、加粗关键词，避免大段文字堆在一起。"
        "非常重要：请在回答中通过标注如 [1], [2] 来内联引用相应片段的来源（数字对应上下文中的来源编号）。"
    )
    user_prompt = (
        f"用户问题：{question}\n\n"
        f"本地检索上下文：\n{context}\n\n"
        "请用中文回答。务必在段落中使用 [1], [2] 等格式进行来源引用。"
    )

    if provider == "openai":
        body = {"model": model, "instructions": system_prompt, "input": user_prompt, "stream": True}
        url = f"{base_url or 'https://api.openai.com/v1'}/responses"
    else:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "stream": True,
        }
        url = f"{base_url}/chat/completions"

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if provider == "openai":
                    if payload.get("type") == "response.output_text.delta":
                        delta = payload.get("delta", "")
                    else:
                        delta = ""
                else:
                    choices = payload.get("choices") or []
                    delta = ""
                    if choices:
                        delta = ((choices[0].get("delta") or {}).get("content") or "")
                if delta:
                    yield {"type": "delta", "text": delta}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:800]
        yield {"type": "error", "text": f"LLM 调用失败：HTTP {exc.code} {detail}"}
    except Exception as exc:
        yield {"type": "error", "text": f"LLM 调用失败：{exc}"}
    citations = citation_markdown(chunks)
    if citations:
        yield {"type": "delta", "text": f"\n\n---\n\n**引用来源：**\n{citations}"}
    yield {"type": "done"}
