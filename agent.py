import json
import os
import re
import subprocess
import sys
import threading
from io import BytesIO
from pathlib import Path
from typing import Any, Generator
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request

from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langgraph.prebuilt import create_react_agent

from ai_config import load_ai_config
from crawl_run_registry import latest_crawl_run_summary
from network_utils import urlopen_with_local_proxy_fallback
from rag_llm import list_knowledge_datasets, retrieve_context

ROOT = Path(__file__).resolve().parent
AGENT_SKILLS_DIR = ROOT / "Codex" / "agent" / "skills"
FRONTEND_SKILL_ORDER = [
    "company-core-metrics",
    "financial-visual-analytics",
    "verification-watch",
]
WEB_SEARCH_INDEX_LOCK = threading.Lock()
WEB_SEARCH_NEXT_INDEX = 6


def _reset_web_search_indexes() -> None:
    global WEB_SEARCH_NEXT_INDEX
    with WEB_SEARCH_INDEX_LOCK:
        WEB_SEARCH_NEXT_INDEX = 6


def _allocate_web_search_indexes(count: int) -> int:
    global WEB_SEARCH_NEXT_INDEX
    with WEB_SEARCH_INDEX_LOCK:
        start = WEB_SEARCH_NEXT_INDEX
        WEB_SEARCH_NEXT_INDEX += max(0, count)
        return start


def _clean_search_text(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _parse_skill_frontmatter(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"description": "", "tags": [], "data": ""}
    match = re.search(r"^##\s+前端展示\s*\n(?P<body>.*?)(?=^##\s+|\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return meta
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue
        item = line.lstrip("-").strip()
        if "：" not in item:
            continue
        key, value = item.split("：", 1)
        key = key.strip()
        value = value.strip()
        if key == "简介":
            meta["description"] = value
        elif key == "标签":
            meta["tags"] = [part.strip() for part in re.split(r"[、,，]", value) if part.strip()]
        elif key == "数据":
            meta["data"] = value
    return meta


def available_agent_skills() -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    if not AGENT_SKILLS_DIR.exists():
        return []
    for skill_file in sorted(AGENT_SKILLS_DIR.glob("*/SKILL.md")):
        skill_id = skill_file.parent.name
        try:
            text = skill_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        display_meta = _parse_skill_frontmatter(text)
        title = skill_id
        summary = ""
        for line in text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            if clean.startswith("#") and title == skill_id:
                title = clean.lstrip("#").strip() or title
                continue
            if not summary and not clean.startswith(("-", "`", "#")):
                summary = clean[:180]
                break
        by_id[skill_id] = {
            "id": skill_id,
            "title": title,
            "summary": display_meta.get("description") or summary or "项目内 Agent skill",
            "description": display_meta.get("description") or summary or "项目内 Agent skill",
            "tags": display_meta.get("tags") or [],
            "data": display_meta.get("data") or "",
            "path": skill_file.relative_to(ROOT).as_posix(),
        }
    visible = [by_id[skill_id] for skill_id in FRONTEND_SKILL_ORDER if skill_id in by_id]
    return visible


def _selected_skill_context(skill_ids: list[str] | None) -> str:
    if not skill_ids:
        return ""
    allowed = {item["id"] for item in available_agent_skills()}
    blocks: list[str] = []
    for skill_id in skill_ids[:5]:
        clean_id = re.sub(r"[^A-Za-z0-9_.-]", "", str(skill_id or ""))
        if clean_id not in allowed:
            continue
        skill_file = AGENT_SKILLS_DIR / clean_id / "SKILL.md"
        try:
            text = skill_file.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            continue
        if text:
            blocks.append(f"## Skill: {clean_id}\n{text[:16000]}")
    return "\n\n".join(blocks)


def _looks_like_blocked_or_encoded_text(text: str) -> bool:
    sample = " ".join((text or "").split())[:2400]
    if not sample:
        return False
    if re.search(r"_waf_|waf|captcha|verify|访问验证|安全验证|人机验证", sample, re.IGNORECASE):
        return True
    compact = re.sub(r"\s+", "", sample)
    if len(compact) < 300:
        return False
    encoded_chars = sum(1 for ch in compact if ch.isalnum() or ch in "+/=_-")
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", compact))
    return encoded_chars / max(len(compact), 1) > 0.92 and cjk_chars < 20


def _search_query_from_instruction(value: str) -> str:
    text = _clean_search_text(value, 200)
    text = re.sub(r"^(请|帮我|麻烦)?(上网|联网|网上)?(搜一下|搜索一下|搜搜|搜索|查一下|查询)", "", text).strip()
    text = re.sub(r"(给我|帮我)?(?:找|列|提供)?[一二两三四五六七八九十\d]+个?来源.*$", "", text).strip(" ，,。；;")
    return text or _clean_search_text(value, 200)


def _normalize_search_results(items: list[dict[str, Any]], limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        title = _clean_search_text(item.get("title") or item.get("heading") or item.get("name"), 120)
        url = _clean_search_text(item.get("url") or item.get("href") or item.get("link"), 500)
        snippet = _clean_search_text(
            item.get("content") or item.get("body") or item.get("snippet") or item.get("description"),
            320,
        )
        if not title or not url or not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _unwrap_search_redirect(url: str) -> str:
    parsed = urlparse(url)
    if "search.yahoo.com" in parsed.netloc and "/RU=" in parsed.path:
        encoded = parsed.path.split("/RU=", 1)[1].split("/RK=", 1)[0]
        return unquote(encoded)
    query = parse_qs(parsed.query)
    for key in ("url", "u"):
        if query.get(key):
            return query[key][0]
    return url


def _search_with_searxng(query: str, limit: int) -> list[dict[str, str]]:
    base_url = (os.environ.get("SEARXNG_URL") or os.environ.get("CMHK_SEARXNG_URL") or "").strip().rstrip("/")
    if not base_url:
        return []
    params = urlencode({"q": query, "format": "json", "language": "zh-CN"})
    req = Request(
        f"{base_url}/search?{params}",
        headers={"User-Agent": "CMHK-Research-Agent/1.0"},
    )
    with urlopen_with_local_proxy_fallback(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    raw_results = payload.get("results") if isinstance(payload, dict) else []
    return _normalize_search_results(raw_results or [], limit)


def _search_with_duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS  # type: ignore
    except Exception:
        return []
    with DDGS() as ddgs:
        raw_results = list(ddgs.text(query, max_results=limit))
    return _normalize_search_results(raw_results, limit)


def _search_with_brave_html(query: str, limit: int) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup

    req = Request(
        "https://search.brave.com/search?" + urlencode({"q": query, "source": "web"}),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen_with_local_proxy_fallback(req, timeout=20) as response:
        html = response.read().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    raw_results: list[dict[str, Any]] = []
    for block in soup.select(".snippet"):
        link = block.select_one('a[href^="http"]')
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        url = _unwrap_search_redirect(link.get("href") or "")
        text = block.get_text(" ", strip=True)
        snippet = text.replace(title, "", 1).strip(" -")
        raw_results.append({"title": title, "url": url, "snippet": snippet})
    return _normalize_search_results(raw_results, limit)


def _search_with_yahoo_html(query: str, limit: int) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup

    req = Request(
        "https://search.yahoo.com/search?" + urlencode({"p": query}),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen_with_local_proxy_fallback(req, timeout=20) as response:
        html = response.read().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    raw_results: list[dict[str, Any]] = []
    for block in soup.select(".dd.algo"):
        link = block.select_one(".compTitle a[href]") or block.select_one('a[href^="http"]')
        title_node = block.select_one("h3.title") or link
        snippet_node = block.select_one(".compText p") or block.select_one("p")
        if not link or not title_node:
            continue
        raw_results.append(
            {
                "title": title_node.get_text(" ", strip=True),
                "url": _unwrap_search_redirect(link.get("href") or ""),
                "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            }
        )
    return _normalize_search_results(raw_results, limit)


def _display_tool_result(tool_name: str, content: str, meta_event: dict[str, Any] | None) -> str:
    if tool_name == "list_local_datasets":
        return content[:4000].rstrip()
    if tool_name == "list_crawl_runs":
        return content[:4000].rstrip()
    if tool_name == "web_search":
        refs = (meta_event or {}).get("references") or []
        if not refs:
            return "联网搜索完成，但没有返回可展示来源。"
        lines = [f"联网搜索完成，找到 {len(refs)} 个来源："]
        for ref in refs[:6]:
            links = ref.get("links") or []
            link = links[0] if links else {}
            label = _clean_search_text(ref.get("source") or link.get("label") or "来源", 120)
            url = _clean_search_text(link.get("url") or "", 300)
            lines.append(f"[{ref.get('index')}] {label}" + (f"\n{url}" if url else ""))
        preview = content.strip()
        if preview:
            lines.append("\n具体返回内容：")
            lines.append(preview[:4000].rstrip())
        return "\n".join(lines)
    if tool_name == "search_local_reports":
        refs = (meta_event or {}).get("references") or []
        preview = content.strip()
        return (
            f"本地检索完成，找到 {len(refs)} 个相关片段。\n\n"
            f"具体返回内容：\n{preview[:4000].rstrip()}"
        ).rstrip()
    if tool_name == "read_local_reference":
        if content.startswith("本地引用读取失败"):
            return content
        return f"本地引用读取完成。\n\n具体返回内容：\n{content[:4000].rstrip()}"
    if tool_name == "read_webpage":
        if content.startswith(("网页读取失败", "网页读取跳过", "读取网页")):
            return "网页读取失败，已改用搜索摘要和本地资料。"
        if content.startswith("PDF读取失败"):
            return "PDF 读取失败，已改用搜索摘要和本地资料。"
        return f"网页读取完成。\n\n具体返回内容：\n{content[:4000].rstrip()}"
    if len(content) > 1200:
        return content[:1200].rstrip() + "\n..."
    return content

@tool
def list_local_datasets() -> str:
    """列出小竞 AI 后端当前可检索和读取的本地数据集。
    当用户问“你能访问哪些数据”“数据放哪里”“有哪些内部/外部数据”，或你准备做趋势分析、问数、核验前需要了解可用数据时，先使用此工具。
    """
    datasets = list_knowledge_datasets()
    if not datasets:
        return "当前没有在 agent_knowledge/ 下发现可用数据集。"
    lines = ["当前可用本地数据集："]
    references = []
    links = []
    for index, dataset in enumerate(datasets, 1):
        entrypoints = dataset.get("entrypoints") or []
        files = dataset.get("files") or []
        primary = next((item for item in files if item.get("name") in entrypoints), files[0] if files else None)
        primary_link = {"label": dataset.get("title") or dataset.get("id"), "url": primary.get("url")} if primary else None
        lines.append(
            "\n".join(
                [
                    f"[数据集 {index}] {dataset.get('title') or dataset.get('id')}",
                    f"- id: {dataset.get('id')}",
                    f"- 类型: {dataset.get('source_type') or 'local'}",
                    f"- 范围: {dataset.get('scope') or '未说明'}",
                    f"- 简介: {dataset.get('summary') or '未说明'}",
                    f"- 标签: {'、'.join(dataset.get('tags') or []) or '无'}",
                    f"- 入口文件: {', '.join(entrypoints) or '未指定'}",
                    f"- 文件夹: {dataset.get('folder')}",
                ]
            )
        )
        if primary_link:
            links.append(primary_link)
            references.append({"index": index, "source": dataset.get("title") or dataset.get("id"), "links": [primary_link]})
    meta_data = {"type": "meta", "sources": [d.get("title") for d in datasets], "links": links, "references": references}
    return "\n\n".join(lines) + f"\n<metadata>{json.dumps(meta_data, ensure_ascii=False)}</metadata>"


@tool
def list_crawl_runs(limit: int = 5) -> str:
    """列出最近几次全量爬虫运行索引。
    当用户询问爬虫日志、上次爬虫结果、失败链接、覆盖率、飞书日志页、Agent 数据整理运行记录或调度追溯时，先使用此工具。
    """
    safe_limit = max(1, min(int(limit or 5), 10))
    return latest_crawl_run_summary(safe_limit)


@tool
def search_local_reports(query: str) -> str:
    """搜索本地的战略部周报、审计日志和之前爬取过的网页数据。
    当你需要了解公司的最新动态、特定主体的近期情况，或是爬虫的执行历史时，请使用此工具。
    """
    chunks = retrieve_context(query, limit=5)
    if not chunks:
        return "没有找到相关的本地报告信息。"
    
    result = []
    references = []
    meta_links = []
    seen_urls = set()
    for i, chunk in enumerate(chunks):
        ref_label = f"{chunk['source']} · 片段 {i + 1}"
        result.append(f"[来源 {i+1}: {ref_label}]\n{chunk['text']}")
        chunk_links = chunk.get("links", [])
        references.append(
            {
                "index": i + 1,
                "source": ref_label,
                "links": [
                    {
                        **link,
                        "label": f"{link.get('label') or chunk['source']} · 片段 {i + 1}",
                    }
                    for link in chunk_links
                ],
            }
        )
        for link in chunk_links:
            url = link.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                meta_links.append(link)
                
    text_output = "\n\n".join(result)[:12000]
    meta_data = {
        "type": "meta",
        "sources": [chunk["source"] for chunk in chunks],
        "links": meta_links,
        "references": references
    }
    return f"{text_output}\n<metadata>{json.dumps(meta_data, ensure_ascii=False)}</metadata>"


@tool
def read_local_reference(source: str) -> str:
    """读取本地引用文件的原文内容。
    当 `search_local_reports` 返回 `weekly_report.md`、`final_audit.md`、`coverage_report.tsv`、`run_log.tsv` 或 `row_*.json`
    等本地来源，而你需要查看更完整上下文、核对本地口径或追溯原始抓取结果时，优先使用此工具。
    参数可以是文件名，也可以是 `/references/...` 链接。
    """
    import web_app

    clean = str(source or "").strip()
    if not clean:
        return "本地引用读取失败：来源为空。"
    if clean.startswith("/references/"):
        clean = clean.removeprefix("/references/")
    target = web_app.reference_path(clean)
    if not target or not target.exists():
        return f"本地引用读取失败：未找到允许读取的本地引用 {clean}。"
    try:
        text = web_app.read_display_text(target)
    except Exception as exc:
        return f"本地引用读取失败：{clean} 无法读取，原因：{_clean_search_text(exc, 160)}。"
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return f"本地引用读取失败：{clean} 内容为空。"
    limit = 60000 if clean.startswith("agent_knowledge/") else 16000
    return f"[本地引用: {clean}]\n{text[:limit]}"


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索公开网页信息。
    当用户要求“上网搜一下”“联网搜索”“查最新消息”“找公开来源”或本地 RAG 没有足够信息时使用。
    优先使用自托管 SearXNG（环境变量 SEARXNG_URL/CMHK_SEARXNG_URL），否则使用开源 DDGS/DuckDuckGo 搜索库。
    """
    query = _search_query_from_instruction(query)
    if not query:
        return "搜索关键词为空。"
    limit = max(1, min(int(max_results or 5), 8))
    provider = "searxng"
    try:
        results = _search_with_searxng(query, limit)
    except Exception as exc:
        results = []
        provider = f"searxng_failed:{_clean_search_text(exc, 120)}"
    if not results:
        provider = "ddgs"
        try:
            results = _search_with_duckduckgo(query, limit)
        except Exception as exc:
            provider = f"ddgs_failed:{_clean_search_text(exc, 120)}"
            results = []
    if not results:
        provider = "yahoo_html"
        try:
            results = _search_with_yahoo_html(query, limit)
        except Exception:
            results = []
    if not results:
        provider = "brave_html"
        try:
            results = _search_with_brave_html(query, limit)
        except Exception as exc:
            return (
                f"联网搜索失败：{_clean_search_text(exc, 240)}。"
                "可配置自托管 SearXNG：设置 SEARXNG_URL 后重启后端。"
            )
    if not results:
        return "没有搜索到可用网页结果。"

    lines = []
    references = []
    links = []
    start_index = _allocate_web_search_indexes(len(results))
    for offset, item in enumerate(results):
        index = start_index + offset
        title = item["title"]
        url = item["url"]
        snippet = item.get("snippet") or ""
        lines.append(f"[来源 {index}: {title}]\n链接：{url}\n摘要：{snippet}")
        link = {"label": title, "url": url}
        links.append(link)
        references.append({"index": index, "source": title, "links": [link]})
    meta_data = {
        "type": "meta",
        "provider": provider,
        "sources": [item["title"] for item in results],
        "links": links,
        "references": references,
    }
    return "\n\n".join(lines) + f"\n<metadata>{json.dumps(meta_data, ensure_ascii=False)}</metadata>"

@tool
def trigger_crawl(row_id: int) -> str:
    """触发针对特定行的爬虫任务。
    参数 row_id 是配置表中的行号。
    如果你需要最新抓取某一行的数据，使用此工具。注意这可能需要十几秒。
    """
    env = os.environ.copy()
    env["CMHK_ROWS"] = str(row_id)
    try:
        proc = subprocess.run([sys.executable, str(ROOT / "crawl.py")], env=env, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return f"爬取完成 (Row {row_id}):\nStdout: {proc.stdout[:1000]}..."
        else:
            return f"爬取失败 (Row {row_id}):\nStderr: {proc.stderr}"
    except Exception as e:
        return f"执行爬虫异常: {str(e)}"

@tool
def feishu_cli(command_args: str) -> str:
    """执行飞书命令行工具 (lark-cli)。
    当你需要与飞书表格进行同步、写入数据，或者查询飞书记录时，请使用此工具。
    由于安全限制，你只需提供 'lark-cli' 后面的参数，例如: 'sheets +read --range 9c638d!A1:B2'
    """
    import shutil
    LARK_CLI = shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"
    
    # Simple shell-like splitting for arguments
    import shlex
    try:
        args = shlex.split(command_args)
    except Exception as e:
        return f"参数解析错误: {e}"
        
    cmd = [LARK_CLI] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            return f"执行成功:\n{proc.stdout}"
        else:
            return f"执行失败:\n{proc.stderr}"
    except Exception as e:
        return f"执行出错: {str(e)}"

@tool
def trigger_report_generation() -> str:
    """触发本地周报生成任务。
    当你被要求“生成周报”、“汇总报告”时，使用此工具。它会调用底层的周报生成脚本并生成 docx 文件。
    """
    try:
        proc = subprocess.run([sys.executable, str(ROOT / "generate_weekly_report.py")], capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return f"周报生成成功！\nStdout: {proc.stdout[-500:]}"
        else:
            return f"周报生成失败:\nStderr: {proc.stderr}"
    except Exception as e:
        return f"执行周报生成异常: {str(e)}"

@tool
def read_webpage(url: str) -> str:
    """访问并读取指定 URL 的纯文本内容。
    当用户提供一个网页链接，并要求你阅读、总结或提取其中的信息时，使用此工具。
    对 PDF 财报或公告链接会尝试抽取 PDF 文本；对反爬、二进制或浏览器验证页面会返回失败原因。
    """
    from bs4 import BeautifulSoup
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,text/plain;q=0.9,*/*;q=0.1'})
        with urlopen_with_local_proxy_fallback(req, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(12_000_000)
        is_pdf = re.search(r"application/pdf", content_type, re.IGNORECASE) or urlparse(url).path.lower().endswith(".pdf") or raw[:4] == b"%PDF"
        if is_pdf:
            try:
                from pypdf import PdfReader

                reader = PdfReader(BytesIO(raw))
                pages = []
                for page in reader.pages[:12]:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        pages.append(page_text.strip())
                text = re.sub(r"\s+", " ", "\n".join(pages)).strip()
                if len(text) < 80:
                    return "PDF读取失败：该 PDF 未抽取到足够文本，可能是扫描件或加密文件。"
                return text[:12000]
            except Exception as exc:
                return f"PDF读取失败：{_clean_search_text(exc, 200)}。"
        if not re.search(r"text/html|text/plain|application/xhtml\+xml", content_type, re.IGNORECASE):
            return f"网页读取跳过：该链接返回 {content_type or '非文本内容'}，请使用搜索摘要或官方 PDF/公告页面。"
        if b"\x00" in raw[:2048]:
            return "网页读取跳过：该链接返回二进制内容，无法作为正文展示。"
        html = raw.decode("utf-8", errors="ignore")
        if not re.search(r"<html|<body|<article|<p[\s>]", html, re.IGNORECASE):
            text_probe = " ".join(html.split())
            if _looks_like_blocked_or_encoded_text(text_probe):
                return "网页读取失败：该链接返回反爬验证或加密内容，无法作为正文展示。"
            if len(text_probe) > 200 and not re.fullmatch(r"[A-Za-z0-9+/=\s]+", text_probe[:2000]):
                return text_probe[:8000]
            return "网页读取失败：该链接没有返回可解析正文。"
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if _looks_like_blocked_or_encoded_text(text):
            return "网页读取失败：该链接返回反爬验证或加密内容，无法作为正文展示。"
        if len(text) < 80:
            return "网页读取失败：该链接正文过短或需要浏览器验证。"
        return text[:10000]
    except Exception as e:
        return f"读取网页 {url} 失败: {str(e)}"

@tool
def get_system_status() -> str:
    """获取系统运行状态和爬虫统计数据（包括最近爬取的成功数、失败数等）。
    当你需要了解系统的健康状况或数据收集的全景概览时，使用此工具。
    """
    import web_app
    try:
        status = web_app.build_status()
        return f"系统状态快照：\n{json.dumps(status, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"获取系统状态失败: {str(e)}"

def _thinking_model_name(model_name: str) -> str:
    configured = (os.environ.get("AI_THINKING_MODEL") or os.environ.get("DEEPSEEK_THINKING_MODEL") or "").strip()
    if configured:
        return configured
    if "deepseek" in model_name.lower():
        return "deepseek-reasoner"
    return model_name


def get_agent(thinking_enabled: bool = False):
    config = load_ai_config()
    api_key = config.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
    base_url = config.get("base_url", "") or os.environ.get("OPENAI_API_BASE", "")
    model_name = config.get("model", "deepseek-chat")
    
    if thinking_enabled:
        model_name = _thinking_model_name(str(model_name))
    elif "reasoner" in str(model_name):
        model_name = "deepseek-chat"
        
    from network_utils import _available_proxy_urls
    proxies = _available_proxy_urls()
    if proxies and not os.environ.get("HTTP_PROXY"):
        os.environ["HTTP_PROXY"] = proxies[0]
        os.environ["HTTPS_PROXY"] = proxies[0]
        
    llm = ChatDeepSeek(
        model=model_name,
        api_key=api_key,
        api_base=base_url,
        max_retries=3,
    )
    
    tools = [
        list_local_datasets,
        list_crawl_runs,
        search_local_reports,
        read_local_reference,
        web_search,
        trigger_crawl,
        feishu_cli,
        trigger_report_generation,
        read_webpage,
        get_system_status,
    ]
    
    system_message = (
        "你是中国移动战略部公开信息监测系统的智能 RAG 和运维助手。\n"
        "调用 `feishu_cli` 时必须使用完整参数 `--spreadsheet-token ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA`，不要使用 `-t` 简写或位置参数。例如查询数据使用：`sheets +read --spreadsheet-token ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA --range 9c638d!A1:C10`。\n"
        "【核心法则】如果你不确定某个 CLI 命令（特别是 `+update`、`+write` 等子命令）的具体用法和参数格式，**绝对不允许瞎猜尝试**！你必须先执行 `feishu_cli sheets +update --help` 等命令查阅帮助文档，然后再进行真正的调用。\n"
        "【重要】核心数据表的工作表名称是\"主表\"，其对应的 sheet_id 为 9c638d。当查询或修改\"主表\"时，务必使用 9c638d 作为 range 前缀，例如 `--range 9c638d!A2:Z2`。\n"
        "【极度重要】表格的列结构可能随时发生变化（用户会动态插入或删除列）。如果你需要读取或写入特定字段的数据，**严禁直接凭记忆写死列号**（例如想当然地认为H列必定是更新频率）。你必须先使用 lark-cli 读取第一行表头（例如 `--range 9c638d!A1:Z1`），精确查明各个字段当前实际所在的字母列后，再执行后续的行列操作！\n"
        "【强制规则 - 来源引用】当你的回答参考了 `search_local_reports`、`web_search` 或其他工具返回的上下文时，必须在文中用 [1], [2] 等格式进行内联标号（对应 [来源 1], [来源 2] 的编号）。本地检索通常使用 [1]-[5]，联网搜索通常从 [6] 开始编号；必须沿用工具结果中的实际编号。**请将标号紧跟在每一条具体的数据或事实后面**，绝对不要把一堆标号集中放在大标题上或段落末尾。**禁止在回答末尾自行输出任何 <引用来源>、<references> 等参考文献列表**，系统会自动展示。\n"
        "【本地数据边界】你能接触到的本地数据不是无限的，必须以工具返回为准：`list_local_datasets` 用于列出标准化数据集，`search_local_reports` 用于检索标准化数据集、周报、审计日志和爬取结果，`read_local_reference` 用于读取可点击引用原文。用户问“你能访问哪些数据”“数据放哪里”“内部/外部数据怎么接入”“后端有哪些数据”时，必须先调用 `list_local_datasets` 再回答。做趋势分析、问数、财报对比、口径核验、图表之前，如果不确定可用数据，也要先调用 `list_local_datasets`。\n"
        "【新增数据规范】后续新增内部或外部数据时，默认放入项目根目录 `agent_knowledge/<dataset_id>/`。每个数据集至少提供 `manifest.json`，建议同时提供 `README.md`、结构化 `data.csv` 或 `data.json`、摘要 `summary.md`、来源 `sources.json`。允许被后端索引和引用的文本文件扩展名只有 `.md`、`.txt`、`.json`、`.csv`、`.tsv`。`manifest.json` 应写明 id、title、summary、source_type、scope、tags、keywords、entrypoints、updated_at、quality。除非工具列出，否则不要声称自己能读取其他本地目录。\n"
        "【爬虫日志调度】每次全量爬虫完成后，系统会登记 `agent_knowledge/crawl_run_logs/`：本地只保存运行索引和摘要，完整逐 URL 日志与 Agent 处理流程写入飞书日志子表。用户问上次爬虫、失败链接、覆盖率、日志在哪、Agent 是否处理完成时，必须先调用 `list_crawl_runs`；需要更细节再用 `search_local_reports` 或 `read_local_reference` 读取 `run_log.tsv`、`coverage_report.tsv`、`final_audit.md`。\n"
        "【检索工具搭配】对公开信息、竞对动态、收入/财报、政策、行业趋势、最新进展等问题，默认尽量同时调用 `search_local_reports` 和 `web_search`：先用 `search_local_reports` 获取本地监测和周报上下文，再用 `web_search` 获取联网公开来源；除非用户明确只要本地或只要联网，不要只调用其中一个。\n"
        "【本地原文优先】`search_local_reports` 只是本地检索摘要；只要问题涉及数据、财报、收入、对比、结论判断或口径核对，并且你已经调用了 `search_local_reports`，就必须至少对一个最相关的本地来源调用 `read_local_reference`（例如 `weekly_report.md` 或 `row_2.json`）查看原文后再回答。如果本地检索结果没有相关来源，才说明本地原文不足。不要在没有读本地引用原文的情况下连续打开外部网页。\n"
        "【本地与联网交叉校验】当 `search_local_reports` 与 `web_search` 返回的数据在日期、口径、金额、比例、主体名称或结论上存在出入时，必须在回答中单独说明差异：分别列出本地资料口径、联网公开来源口径、可能原因和建议采用的可信口径。禁止把冲突数据混合成一个确定结论。\n"
        "【主体公司近三年核心数据 Skill】项目内已建立 `Company Core Metrics Trend Skill`，数据目录为 `agent_knowledge/core_company_metrics_2026-06-16/`。当用户询问中国移动、中国电信、中国联通、中国铁塔、HKT / csl / 1O1O、3HK / Hutchison、SmarTone、HKBN、HGC、i-CABLE 的近三年收入、净利润、毛利率、EBITDA、资本开支、现金流、资产负债、趋势或同业比较时，必须优先通过 `search_local_reports` 检索该目录，并用 `read_local_reference` 读取 `core_metrics_2023_2025.json` 或 `core_metrics_summary.md` 后再回答。该数据包不包含券商观点；HGC 为非上市主体，三年完整财务数据不足，不得估算。\n"
        "【联网搜索】当用户明确要求上网、联网搜索、查最新公开信息，或本地资料不足以回答时，必须调用 `web_search`。搜索后仍需用 [1], [2] 标注具体事实来源；只有用户要求打开网页全文或搜索摘要不足以核实时，才对最多 2 个关键结果调用 `read_webpage`。若 `read_webpage` 返回失败、跳过、浏览器验证或 PDF 抽取失败，不要反复读取同一类链接，应改用搜索摘要、本地引用和其他公开来源交叉验证。\n"
        "【强制规则 - 无图标/Emoji】所有的文字输出中绝对禁止使用任何 Emoji、表情符号或特殊排版图标。保持极其严肃、专业的纯文本风格。\n"
        "【重要】如果你连续 3 次调用某个工具均未能成功（比如参数错误、表名不对或输出过多），请立即停止调用，并直接回复用户当前遇到的困难，不要陷入无限重试的死循环。\n\n"
        "【强制规则 - 推荐追问】你的每一条最终回复（无论长短、无论是否调用了工具）的最后一行都必须包含推荐追问。格式如下，不可省略：\n"
        "<suggestions>[\"追问1\", \"追问2\", \"追问3\"]</suggestions>\n"
        "追问内容应与当前话题紧密相关、对用户有实际价值。这是一条不可违反的系统指令，任何回答如果缺少 <suggestions> 标签都是不合格的。\n"
    )
    
    return create_react_agent(llm, tools, prompt=system_message)

def stream_agent(
    message: str,
    force_web_search: bool = False,
    selected_skill_ids: list[str] | None = None,
    thinking_enabled: bool = False,
) -> Generator[dict[str, Any], None, None]:
    _reset_web_search_indexes()
    agent = get_agent(thinking_enabled=thinking_enabled)
    if thinking_enabled:
        yield {
            "type": "thinking_status",
            "text": "深度思考已开启：正在规划检索、工具调用和来源核验步骤。",
        }
    skill_context = _selected_skill_context(selected_skill_ids)
    if skill_context:
        message = (
            "用户已在前端手动载入以下 Agent Skills。你必须先按这些 SKILL.md 的规则工作；"
            "如果 skill 要求读取本地资料或做来源核验，应主动调用对应工具完成。\n\n"
            f"{skill_context}\n\n"
            f"用户问题：{message}"
        )
    if force_web_search:
        message = (
            "用户已在聊天框打开联网搜索开关。你必须调用 `web_search` 获取公开网页来源；"
            "同时尽量调用 `search_local_reports` 做本地资料交叉验证。"
            "如果本地和联网数据有出入，要明确说明差异和建议采用口径。\n\n"
            f"用户问题：{message}"
        )
    if thinking_enabled:
        message = (
            "用户已打开深度思考开关。请先做更严格的问题拆解、工具选择、来源核验和冲突检查，"
            "但不要输出内部推理过程；只输出可审计的结论、依据、必要步骤和不确定性。\n\n"
            f"用户问题：{message}"
        )
    inputs = {"messages": [("user", message)]}
    
    tool_calls_acc = {}
    
    try:
        events = agent.stream(inputs, stream_mode="messages")
        for chunk, metadata in events:
            if isinstance(chunk, AIMessageChunk):
                if chunk.content and isinstance(chunk.content, str):
                    yield {"type": "delta", "text": chunk.content}
                if chunk.tool_call_chunks:
                    for tc in chunk.tool_call_chunks:
                        index = tc.get("index")
                        tc_id = tc.get("id")
                        
                        if tc_id:
                            current_key = tc_id
                            tool_calls_acc[index] = current_key
                            tool_calls_acc[current_key] = {"name": tc.get("name"), "args": "", "id": tc_id}
                            yield {"type": "tool_call_start", "id": tc_id, "name": tc.get("name") or "工具"}
                        else:
                            current_key = tool_calls_acc.get(index)
                            
                        if current_key and tc.get("args"):
                            tool_calls_acc[current_key]["args"] += tc["args"]
            elif isinstance(chunk, ToolMessage):
                args_str = ""
                tc_data = tool_calls_acc.get(chunk.tool_call_id)
                if tc_data:
                    args_str = tc_data.get("args", "")
                
                content = chunk.content
                
                # Parse metadata if present
                meta_event = None
                if "<metadata>" in content:
                    import re
                    match = re.search(r"<metadata>(.*?)</metadata>", content)
                    if match:
                        try:
                            meta_event = json.loads(match.group(1))
                        except Exception:
                            pass
                        content = content.replace(match.group(0), "")
                
                # Attempt to parse json from string for better formatting if it's a known JSON string
                if content.startswith("系统状态快照：\n"):
                    try:
                        # Extract the JSON part and format it
                        json_str = content[len("系统状态快照：\n"):]
                        parsed = json.loads(json_str)
                        content = "系统状态快照：\n" + json.dumps(parsed, ensure_ascii=False, indent=2)
                    except:
                        pass
                elif content.startswith("{") or content.startswith("["):
                    try:
                        parsed = json.loads(content)
                        content = json.dumps(parsed, ensure_ascii=False, indent=2)
                    except:
                        pass

                if meta_event:
                    yield meta_event
                    
                tool_name = str((tc_data or {}).get("name") or "工具")
                display_content = _display_tool_result(tool_name, content.strip(), meta_event)
                yield {
                    "type": "tool_call_result",
                    "id": chunk.tool_call_id,
                    "name": tool_name,
                    "args": args_str,
                    "content": display_content,
                }
                    
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "text": f"Agent 调用失败: {e}"}
        yield {"type": "done"}
