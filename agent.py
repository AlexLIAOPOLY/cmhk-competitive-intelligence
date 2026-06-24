import csv
import collections
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
import threading
from contextvars import ContextVar
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
from agent_memory import add_memory, auto_capture_user_memory, load_memories, memory_context, search_memories
from agent_production import (
    AgentRunRecorder,
    action_id,
    confirmation_event,
    confirmation_metadata,
    dataset_lineage,
    retrieval_quality,
    rolling_backtest,
)
from crawl_run_registry import latest_crawl_run_summary
from network_utils import urlopen_with_local_proxy_fallback
from rag_llm import build_context_package, list_knowledge_datasets, retrieve_context
from chart_renderer import render_chart

ROOT = Path(__file__).resolve().parent
AGENT_SKILLS_DIR = ROOT / "Codex" / "agent" / "skills"
CHAT_THREADS_PATH = ROOT / "agent_chat_threads" / "threads.json"
FRONTEND_SKILL_ORDER = [
    "executive-briefing",
    "quarterly-competitor-metrics",
    "cloud-vendor-metrics",
    "macro-policy-context",
    "trend-forecasting",
]
SKILL_ROUTING_RULES = [
    (
        "quarterly-competitor-metrics",
        r"竞对|季度|半年度|经营数据|财务|收入|营收|利润|EBITDA|ARPU|同比|环比|中国移动|中国联通|中国电信|中国铁塔|HKT|SmarTone|Hutchison|HKBN",
    ),
    (
        "cloud-vendor-metrics",
        r"云厂商|云收入|云业务|AWS|Azure|Google Cloud|Alibaba Cloud|阿里云|腾讯云|Huawei Cloud|华为云|Oracle Cloud|cloud revenue",
    ),
    (
        "macro-policy-context",
        r"宏观|政策|监管|5G|频谱|OFCA|香港电信|电信市场|宽带|移动用户|SIM|实名|监管政策|公共机构|宏观环境",
    ),
    (
        "trend-forecasting",
        r"预测|趋势|未来|forecast|Holt|Winters|回测|naive|seasonal|模型|适用性|风险边界",
    ),
    (
        "executive-briefing",
        r"简报|战略简报|汇报|总结|一页纸|关键证据|重点提炼|风险建议|行动项|管理层|领导|结论先行",
    ),
]
SKILL_BYPASS_PATTERN = re.compile(
    r"历史聊天|聊天记录|之前聊|早先|上一轮|前台发送测试|长期记忆|记忆条目|你记住|列出记忆|你好|您好|谢谢|ok|测试",
    re.IGNORECASE,
)
WEB_SEARCH_INDEX_LOCK = threading.Lock()
WEB_SEARCH_NEXT_INDEX = 6
SELECTED_DATASET_IDS: ContextVar[set[str] | None] = ContextVar("SELECTED_DATASET_IDS", default=None)
SELECTED_SKILL_IDS: ContextVar[set[str] | None] = ContextVar("SELECTED_SKILL_IDS", default=None)
APPROVED_ACTION_IDS: ContextVar[set[str]] = ContextVar("APPROVED_ACTION_IDS", default=set())
CHART_RUN_STATE: ContextVar[dict[str, Any] | None] = ContextVar("CHART_RUN_STATE", default=None)
TOOL_RUN_STATE: ContextVar[dict[str, Any] | None] = ContextVar("TOOL_RUN_STATE", default=None)


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


def _register_tool_invocation(tool_name: str, limit: int) -> str | None:
    state = TOOL_RUN_STATE.get()
    if state is None:
        return None
    counts = state.setdefault("counts", {})
    count = int(counts.get(tool_name) or 0) + 1
    counts[tool_name] = count
    if count > limit:
        return (
            f"{tool_name} 已达到本轮调用上限（{limit} 次），请停止继续调用该工具，"
            "直接基于已经返回的资料给出结论、表格或图表。"
        )
    return None


class MarkdownTableLimiter:
    """Limit streamed Markdown tables before they reach the browser."""

    def __init__(self, max_rows: int = 30, max_columns: int = 8) -> None:
        self.max_rows = max_rows
        self.max_columns = max_columns
        self.buffer = ""
        self.in_table = False
        self.row_count = 0
        self.notice_sent = False

    @staticmethod
    def _is_table_line(line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2

    @staticmethod
    def _is_separator_line(line: str) -> bool:
        cells = line.strip().split("|")[1:-1]
        return bool(cells) and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell or "") for cell in cells)

    def _cap_columns(self, line: str) -> str:
        newline = "\n" if line.endswith("\n") else ""
        cells = line.strip().split("|")[1:-1]
        if len(cells) <= self.max_columns:
            return line
        capped = cells[: self.max_columns]
        return "|" + "|".join(capped) + "|" + newline

    def _process_line(self, line: str) -> str:
        if not self._is_table_line(line):
            self.in_table = False
            self.row_count = 0
            self.notice_sent = False
            return line
        if not self.in_table:
            self.in_table = True
            self.row_count = 0
            self.notice_sent = False
        if self._is_separator_line(line):
            return self._cap_columns(line)
        self.row_count += 1
        if self.row_count > self.max_rows:
            if self.notice_sent:
                return ""
            self.notice_sent = True
            return "\n表格已由后端截断：最多显示 30 行、8 列；请缩小范围或导出 CSV 查看完整数据。\n"
        return self._cap_columns(line)

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self.buffer += text
        output: list[str] = []
        while True:
            newline_index = self.buffer.find("\n")
            if newline_index < 0:
                break
            line = self.buffer[: newline_index + 1]
            self.buffer = self.buffer[newline_index + 1 :]
            output.append(self._process_line(line))
        return "".join(output)

    def flush(self) -> str:
        if not self.buffer:
            return ""
        line = self.buffer
        self.buffer = ""
        stripped = line.strip()
        if stripped.startswith("|") and not stripped.endswith("|"):
            return ""
        return self._process_line(line)


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
    blocks: list[str] = [
        "以下是本轮前端勾选的 Agent Skill 发现信息。"
        "这不是完整 Skill 指令；如果本轮确实需要某个 Skill 的完整规则，再调用 `read_agent_skill(skill_id)` 读取完整 SKILL.md。"
    ]
    for skill_id in skill_ids[:5]:
        clean_id = re.sub(r"[^A-Za-z0-9_.-]", "", str(skill_id or ""))
        if clean_id not in allowed:
            continue
        item = next((row for row in available_agent_skills() if row.get("id") == clean_id), None)
        if item:
            blocks.append(
                "\n".join(
                    [
                        f"## Skill: {clean_id}",
                        f"- 标题: {item.get('title') or clean_id}",
                        f"- 简介: {item.get('description') or item.get('summary') or ''}",
                        f"- 数据: {item.get('data') or ''}",
                        f"- 路径: {item.get('path') or ''}",
                    ]
                )
            )
    return "\n\n".join(blocks)


def _skill_routing_instruction(
    message: str,
    selected_skill_ids: list[str] | None,
    loaded_skill_ids: list[str] | None,
) -> str:
    selected = {
        re.sub(r"[^A-Za-z0-9_.-]", "", str(item or ""))
        for item in (selected_skill_ids or [])
        if str(item or "").strip()
    }
    if not selected:
        return ""
    clean_message = _clean_search_text(message, 1200)
    if not clean_message:
        return ""
    if SKILL_BYPASS_PATTERN.search(clean_message):
        return (
            "Skill 路由判断：本轮更像历史聊天、记忆审计、寒暄或简单测试。"
            "不要为了流程感读取 Skill；优先直接回答或调用更相关的工具。"
        )
    loaded = {
        re.sub(r"[^A-Za-z0-9_.-]", "", str(item or ""))
        for item in (loaded_skill_ids or [])
        if str(item or "").strip()
    }
    matched: list[str] = []
    for skill_id, pattern in SKILL_ROUTING_RULES:
        if skill_id in selected and re.search(pattern, clean_message, re.IGNORECASE):
            matched.append(skill_id)
    if not matched:
        return (
            "Skill 路由判断：本轮未明显命中已选 Skill 的领域任务。"
            "如问题后续需要数据分析、政策解读、趋势预测或战略简报，再选择性读取相关 Skill。"
        )
    target = matched[:2]
    unread = [skill_id for skill_id in target if skill_id not in loaded]
    if unread:
        return (
            "Skill 路由判断：本轮问题明显需要已选 Skill 支撑。"
            f"在正式分析前，优先调用 `read_agent_skill` 读取这些最相关 Skill：{', '.join(unread)}。"
            "最多读取 1-2 个最相关 Skill，不要把所有已选 Skill 全部读一遍；读取后再调用数据库检索、原文核验、预测或图表工具。"
        )
    return (
        "Skill 路由判断：本轮命中的相关 Skill 此前已读取过。"
        f"可沿用这些 Skill 的规则：{', '.join(target)}；只有任务切换或规则不确定时才再次读取。"
    )


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
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "search.yahoo.com" in parsed.netloc and "/RU=" in parsed.path:
        encoded = parsed.path.split("/RU=", 1)[1].split("/RK=", 1)[0]
        return unquote(encoded)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        if query.get("uddg"):
            return query["uddg"][0]
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


def _search_with_duckduckgo_html(query: str, limit: int) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup

    req = Request(
        "https://html.duckduckgo.com/html/?" + urlencode({"q": query}),
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urlopen_with_local_proxy_fallback(req, timeout=20) as response:
        html = response.read().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    raw_results: list[dict[str, Any]] = []
    for block in soup.select(".result"):
        link = block.select_one(".result__a[href]") or block.select_one('a[href]')
        if not link:
            continue
        snippet_node = block.select_one(".result__snippet")
        raw_results.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": _unwrap_search_redirect(link.get("href") or ""),
                "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            }
        )
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
            preview = content.strip()
            return preview[:1200].rstrip() if preview else "联网搜索完成，但没有返回可展示来源。"
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
            f"已读取已选数据库摘要，找到 {len(refs)} 个相关片段。\n\n"
            f"具体返回内容：\n{preview[:4000].rstrip()}"
        ).rstrip()
    if tool_name == "read_local_reference":
        if content.startswith("本地引用读取失败"):
            return content
        return f"已读取数据库原文。\n\n具体返回内容：\n{content[:4000].rstrip()}"
    if tool_name == "read_agent_skill":
        if content.startswith("Agent Skill 读取失败"):
            return content
        return f"Agent Skill 已读取。\n\n具体返回内容：\n{content[:6000].rstrip()}"
    if tool_name == "read_webpage":
        if content.startswith(("网页读取失败", "网页读取跳过", "读取网页")):
            return "网页读取失败，已改用搜索摘要和本地资料。"
        if content.startswith("PDF读取失败"):
            return "PDF 读取失败，已改用搜索摘要和本地资料。"
        return f"网页读取完成。\n\n具体返回内容：\n{content[:4000].rstrip()}"
    if tool_name == "render_python_chart":
        return content[:4000].rstrip()
    if len(content) > 1200:
        return content[:1200].rstrip() + "\n..."
    return content


def _selected_dataset_ids() -> set[str] | None:
    return SELECTED_DATASET_IDS.get()


def _dataset_id_for_agent_knowledge_source(source: str) -> str:
    clean = str(source or "").strip().removeprefix("/references/")
    parts = clean.split("/")
    if len(parts) >= 2 and parts[0] == "agent_knowledge":
        folder = ROOT / "agent_knowledge" / parts[1]
        if folder.exists():
            for dataset in list_knowledge_datasets():
                if dataset.get("folder") == f"agent_knowledge/{parts[1]}":
                    return str(dataset.get("id") or parts[1])
        return parts[1]
    return ""


def _dataset_is_selected(source: str) -> bool:
    selected = _selected_dataset_ids()
    if selected is None:
        return True
    dataset_id = _dataset_id_for_agent_knowledge_source(source)
    return not dataset_id or dataset_id in selected


def _is_action_approved(name: str, payload: Any = None) -> bool:
    approved = APPROVED_ACTION_IDS.get()
    return action_id(name, payload) in approved


def _require_action_confirmation(name: str, payload: Any = None, description: str = "") -> str | None:
    if _is_action_approved(name, payload):
        return None
    event = confirmation_event(name, payload, description)
    return (
        f"需要用户确认后才能执行：{event['label']}。\n"
        f"- 原因：{event['risk']}\n"
        f"- 操作说明：{event['description']}\n"
        "请点击前端确认按钮后再执行。"
        f"\n{confirmation_metadata(event)}"
    )


@tool
def read_agent_skill(skill_id: str) -> str:
    """读取本轮已选择的 Agent Skill 完整 SKILL.md 指令。
    当你准备使用某个前端已选 Agent Skill 时，必须先调用此工具读取完整指令；
    `load_agent_skills` 只表示前端选择了哪些 Skill，不等于已经阅读和执行了 Skill。
    """
    clean_id = re.sub(r"[^A-Za-z0-9_.-]", "", str(skill_id or ""))
    if not clean_id:
        return "Agent Skill 读取失败：skill_id 为空。"
    selected_ids = {
        re.sub(r"[^A-Za-z0-9_.-]", "", str(item or ""))
        for item in (SELECTED_SKILL_IDS.get() or set())
        if str(item or "").strip()
    }
    allowed = {item["id"] for item in available_agent_skills()}
    if clean_id not in allowed:
        return f"Agent Skill 读取失败：{clean_id} 不是前端允许的主要 Skill。"
    if selected_ids and clean_id not in selected_ids:
        return f"Agent Skill 读取失败：{clean_id} 本轮未在前端 Skill 按钮中选择。"
    skill_file = AGENT_SKILLS_DIR / clean_id / "SKILL.md"
    if not skill_file.exists():
        return f"Agent Skill 读取失败：未找到 {clean_id}/SKILL.md。"
    try:
        text = skill_file.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception as exc:
        return f"Agent Skill 读取失败：{clean_id} 无法读取，原因：{_clean_search_text(exc, 160)}。"
    if not text:
        return f"Agent Skill 读取失败：{clean_id}/SKILL.md 内容为空。"
    referenced_files = sorted(
        {
            match
            for match in re.findall(r"`([^`]+?\.(?:md|csv|json|py|txt))`", text, flags=re.IGNORECASE)
            if not match.startswith(("/", "http://", "https://")) and ".." not in match
        }
    )
    refs_text = "\n".join(f"- {item}" for item in referenced_files[:12]) or "- 未发现显式引用文件"
    return (
        f"[Agent Skill: {clean_id}]\n"
        f"路径：{skill_file.relative_to(ROOT).as_posix()}\n"
        "已读取完整 SKILL.md。若下列引用文件与本轮任务相关，应继续用本地检索/读取工具追溯，而不是只停留在 Skill 标题。\n"
        f"引用文件线索：\n{refs_text}\n\n"
        f"{text[:20000]}"
    )


@tool
def list_local_datasets() -> str:
    """列出小竞 AI 后端当前可检索和读取的本地数据集。
    当用户问“你能访问哪些数据”“数据放哪里”“有哪些内部/外部数据”，或你准备做趋势分析、问数、核验前需要了解可用数据时，先使用此工具。
    """
    selected_ids = _selected_dataset_ids()
    datasets = list_knowledge_datasets(dataset_ids=selected_ids)
    if not datasets:
        return "当前未选择任何本地数据库；本轮 AI 不会读取、列举或猜测未选择的数据库内容。请在前端数据库按钮中选择需要发送给 AI 的数据库。"
    lines = ["本轮已选择并可发送给 AI 的本地数据库："]
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
    若用户问题包含“收入同比”“营收同比”“营业收入同比”“收入增长”“revenue_growth_yoy”“YoY”等词，query 必须保留这些同比/增长关键词，不能简化成“收入”或“营业收入”。
    """
    limit_message = _register_tool_invocation("search_local_reports", 6)
    if limit_message:
        return limit_message
    chunks = retrieve_context(query, limit=10, dataset_ids=_selected_dataset_ids())
    if not chunks:
        return "没有找到相关的本地报告信息。"
    context_package = build_context_package(chunks, token_budget=6500, model=_agent_model_name())
    chunks = context_package["chunks"]
    audit = context_package["audit"]
    quality = retrieval_quality(query, chunks, audit)
    
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
                
    text_output = "\n\n".join(result)
    meta_data = {
        "type": "meta",
        "sources": [chunk["source"] for chunk in chunks],
        "links": meta_links,
        "references": references,
        "contextAudit": audit,
        "retrievalQuality": quality,
    }
    return f"{text_output}\n<metadata>{json.dumps(meta_data, ensure_ascii=False)}</metadata>"


@tool
def read_local_reference(source: str) -> str:
    """读取本地引用文件的原文内容。
    当 `search_local_reports` 返回 `weekly_report.md`、`final_audit.md`、`coverage_report.tsv`、`run_log.tsv` 或 `row_*.json`
    等本地来源，而你需要查看更完整上下文、核对本地口径或追溯原始抓取结果时，优先使用此工具。
    参数可以是文件名，也可以是 `/references/...` 链接。
    """
    limit_message = _register_tool_invocation("read_local_reference", 4)
    if limit_message:
        return limit_message
    import web_app

    clean = str(source or "").strip()
    if not clean:
        return "本地引用读取失败：来源为空。"
    if clean.startswith("/references/"):
        clean = clean.removeprefix("/references/")
    if not _dataset_is_selected(clean):
        return f"本地引用读取失败：{clean} 所属数据库本轮未被前端选择，后端不会把它发送给 AI。"
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
    failures: list[str] = []
    try:
        results = _search_with_searxng(query, limit)
    except Exception as exc:
        results = []
        failures.append(f"SearXNG: {_clean_search_text(exc, 120)}")
    if not results:
        provider = "ddgs"
        try:
            results = _search_with_duckduckgo(query, limit)
        except Exception as exc:
            failures.append(f"DDGS: {_clean_search_text(exc, 120)}")
            results = []
    if not results:
        provider = "duckduckgo_html"
        try:
            results = _search_with_duckduckgo_html(query, limit)
        except Exception as exc:
            failures.append(f"DuckDuckGo HTML: {_clean_search_text(exc, 120)}")
            results = []
    if not results:
        provider = "yahoo_html"
        try:
            results = _search_with_yahoo_html(query, limit)
        except Exception as exc:
            failures.append(f"Yahoo: {_clean_search_text(exc, 120)}")
            results = []
    if not results:
        provider = "brave_html"
        try:
            results = _search_with_brave_html(query, limit)
        except Exception as exc:
            failures.append(f"Brave: {_clean_search_text(exc, 120)}")
            results = []
    if not results:
        detail = "；".join(failures[-4:]) if failures else "搜索源没有返回结果"
        return (
            f"联网搜索未返回可用网页结果。查询：{query}。搜索源状态：{detail}。"
            "建议稍后重试，或配置稳定的自托管 SearXNG：设置 SEARXNG_URL 后重启后端。"
        )

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
    payload = {"row_id": int(row_id)}
    confirmation = _require_action_confirmation("trigger_crawl", payload, f"定向爬取配置表第 {row_id} 行。")
    if confirmation:
        return confirmation
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
def trigger_full_crawl() -> str:
    """触发完整公开信息爬取、飞书同步和公司指标刷新。
    当用户明确要求重新爬取、全量抓取、更新公开信息数据或跑完整采集流程时使用。该操作可能耗时较长。
    """
    import web_app

    confirmation = _require_action_confirmation("trigger_full_crawl", {}, "执行完整公开信息爬取、飞书同步和公司指标刷新。")
    if confirmation:
        return confirmation
    try:
        result = web_app.run_crawl()
    except Exception as exc:
        return f"完整爬取执行异常：{_clean_search_text(exc, 240)}"
    status = "成功" if result.get("ok") else "失败"
    return (
        f"完整爬取{status}。\n"
        f"- 退出码：{result.get('returnCode')}\n"
        f"- 耗时：{result.get('durationMs', '未知')} ms\n"
        f"- stdout：{_clean_search_text(result.get('stdout') or '', 1500)}\n"
        f"- stderr：{_clean_search_text(result.get('stderr') or '', 1500)}"
    )

@tool
def feishu_cli(command_args: str) -> str:
    """执行飞书命令行工具 (lark-cli)。
    当你需要与飞书表格进行同步、写入数据，或者查询飞书记录时，请使用此工具。
    由于安全限制，你只需提供 'lark-cli' 后面的参数，例如: 'sheets +read --range 9c638d!A1:B2'
    """
    import shutil
    lowered = str(command_args or "").lower()
    mutating = any(token in lowered for token in ["+write", "+update", "+append", "+delete", "+clear"])
    if mutating:
        payload = {"command_args": command_args}
        confirmation = _require_action_confirmation("feishu_cli", payload, "执行会写入或修改飞书表格的命令。")
        if confirmation:
            return confirmation
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
    当用户明确要求生成战略内参周报、重新生成周报或输出 Word 周报时使用。它会调用 Web 层生成流程，生成 docx 并同步生成音频摘要。
    """
    import web_app

    confirmation = _require_action_confirmation("trigger_report_generation", {}, "生成正式 Word 周报并同步音频摘要。")
    if confirmation:
        return confirmation
    try:
        result = web_app.run_report_generation()
    except Exception as exc:
        return f"执行周报生成异常：{_clean_search_text(exc, 240)}"
    status = "成功" if result.get("ok") else "失败"
    outputs = result.get("status", {}).get("outputs", [])
    latest = outputs[0].get("name") if outputs else "未找到输出文件"
    return (
        f"周报生成{status}。\n"
        f"- 最新文件：{latest}\n"
        f"- 退出码：{result.get('returnCode')}\n"
        f"- 耗时：{result.get('durationMs', '未知')} ms\n"
        f"- 音频：{json.dumps(result.get('audio'), ensure_ascii=False)[:800]}\n"
        f"- stdout：{_clean_search_text(result.get('stdout') or '', 1200)}\n"
        f"- stderr：{_clean_search_text(result.get('stderr') or '', 1200)}"
    )


@tool
def trigger_carrier_performance_report_generation() -> str:
    """触发运营商业绩摘要 Word 报告生成。
    当用户明确要求生成运营商业绩摘要、业绩对标摘要或运营商报告时使用。它会生成 docx 并同步生成音频摘要。
    """
    import web_app

    confirmation = _require_action_confirmation(
        "trigger_carrier_performance_report_generation",
        {},
        "生成运营商业绩摘要 Word 报告并同步音频摘要。",
    )
    if confirmation:
        return confirmation
    try:
        result = web_app.run_carrier_performance_generation()
    except Exception as exc:
        return f"执行业绩摘要生成异常：{_clean_search_text(exc, 240)}"
    status = "成功" if result.get("ok") else "失败"
    outputs = [item for item in result.get("status", {}).get("outputs", []) if item.get("reportType") == "carrier-performance"]
    latest = outputs[0].get("name") if outputs else "未找到业绩摘要输出文件"
    return (
        f"运营商业绩摘要生成{status}。\n"
        f"- 最新文件：{latest}\n"
        f"- 退出码：{result.get('returnCode')}\n"
        f"- 耗时：{result.get('durationMs', '未知')} ms\n"
        f"- 音频：{json.dumps(result.get('audio'), ensure_ascii=False)[:800]}\n"
        f"- stdout：{_clean_search_text(result.get('stdout') or '', 1200)}\n"
        f"- stderr：{_clean_search_text(result.get('stderr') or '', 1200)}"
    )


@tool
def list_report_outputs() -> str:
    """列出当前可下载的正式 Word 输出文件。
    当用户询问输出文件、周报在哪里、有哪些 Word、最新文件、下载对象或报告产物时使用。
    """
    import web_app

    try:
        status = web_app.build_status()
    except Exception as exc:
        return f"读取输出文件失败：{_clean_search_text(exc, 200)}"
    outputs = status.get("outputs") or []
    if not outputs:
        return "当前没有可用输出文件。"
    lines = ["当前可用输出文件："]
    refs = []
    links = []
    for index, item in enumerate(outputs[:30], 1):
        name = item.get("name") or item.get("path") or f"output-{index}"
        report_type = item.get("reportType") or "unknown"
        mtime = item.get("mtimeText") or item.get("mtime") or ""
        path = item.get("path") or item.get("path_str") or ""
        url = f"/outputs/{path}" if path else ""
        audio = item.get("audio", {}).get("exists")
        lines.append(f"{index}. {name}；类型：{report_type}；更新时间：{mtime}；音频：{'有' if audio else '无'}；路径：{path}")
        if url:
            link = {"label": name, "url": url}
            links.append(link)
            refs.append({"index": index, "source": name, "links": [link]})
    meta = {"type": "meta", "sources": [item.get("name") for item in outputs[:30]], "links": links, "references": refs}
    return "\n".join(lines) + f"\n<metadata>{json.dumps(meta, ensure_ascii=False)}</metadata>"


@tool
def get_crawl_settings_summary() -> str:
    """读取当前爬取设置摘要。
    当用户询问当前爬取范围、启用哪些行、覆盖多少主体/字段、设置内容或数据内容配置时使用。只读取摘要，不修改设置。
    """
    import web_app

    try:
        settings = web_app.build_settings_payload()
    except Exception as exc:
        return f"读取爬取设置失败：{_clean_search_text(exc, 200)}"
    summary = settings.get("summary") or {}
    rows = settings.get("rows") or []
    enabled = [row for row in rows if row.get("enabled")]
    preview = []
    for row in enabled[:20]:
        entities = row.get("entities") or []
        fields = row.get("fields") or []
        preview.append(
            f"- 第 {row.get('row')} 行：主体 {len(entities)} 个，字段 {len(fields)} 个，目标链接 {len(row.get('sourceUrls') or [])} 个"
        )
    return (
        "当前爬取设置摘要：\n"
        f"- 启用行：{summary.get('enabledRows')} / {summary.get('totalRows')}\n"
        f"- 已选主体：{summary.get('selectedEntities')}\n"
        f"- 已选字段：{summary.get('selectedFields')}\n"
        f"- 设置文件：crawl_settings.json\n"
        + "\n".join(preview)
    )

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


def _decode_chart_spec_payload(chart_spec: Any) -> dict[str, Any]:
    payload: Any = chart_spec
    for _ in range(3):
        if isinstance(payload, str):
            raw = payload.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            payload = json.loads(raw)
            continue
        if isinstance(payload, dict) and "chart_spec" in payload and not {"x", "series"}.issubset(payload.keys()):
            payload = payload.get("chart_spec")
            continue
        break
    if not isinstance(payload, dict):
        raise ValueError("chart_spec 必须是 JSON 对象。")
    return _normalize_chart_spec_payload(payload)


def _normalize_chart_spec_payload(spec: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(spec)
    series = []
    for item in normalized.get("series") or []:
        if not isinstance(item, dict):
            continue
        series_item = dict(item)
        if "data" not in series_item and "values" in series_item:
            series_item["data"] = series_item.get("values")
        series.append(series_item)
    normalized["series"] = series
    return normalized


def _chart_failure_signature(spec_or_raw: Any) -> str:
    try:
        normalized = _normalize_chart_spec_payload(spec_or_raw) if isinstance(spec_or_raw, dict) else spec_or_raw
        payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        payload = str(spec_or_raw)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


@tool
def render_python_chart(chart_spec: str) -> str:
    """用 Python/Matplotlib 生成中文可正常渲染的 PNG 图表。
    当用户要求画图、趋势图、柱状图、表格+图表或可视化时，在完成数据检索和核验后调用。
    参数必须是 JSON 字符串，包含 type、title、unit、x、series；series 每项使用 data 数组（values 也会被兼容）。请勿提供 notes 或图表底部的解释性文字。
    """
    state = CHART_RUN_STATE.get()
    if state is not None:
        state["calls"] = int(state.get("calls") or 0) + 1
        if state["calls"] > 4:
            return (
                "Python 图表生成停止：本轮图表工具调用次数已达 4 次。"
                "请停止继续调用图表工具，直接基于已检索数据用文字、表格或已有图表回答。"
            )
    try:
        spec = _decode_chart_spec_payload(chart_spec)
    except Exception as exc:
        if state is not None:
            state["failures"] = int(state.get("failures") or 0) + 1
        return (
            f"Python 图表生成失败：chart_spec 不是可用 JSON，原因：{_clean_search_text(exc, 160)}。"
            "不要用相同参数反复调用；如无法修正，请改用文字表格回答。"
        )
    signature = _chart_failure_signature(spec)
    if state is not None:
        failed_signatures = state.setdefault("failed_signatures", {})
        if failed_signatures.get(signature):
            return (
                "Python 图表生成停止：相同图表参数已经失败过。"
                "请不要重复调用，改为给出文字结论或重新检索数据后再生成一张不同口径的图。"
            )
    try:
        result = render_chart(spec)
    except Exception as exc:
        if state is not None:
            state["failures"] = int(state.get("failures") or 0) + 1
            state.setdefault("failed_signatures", {})[signature] = True
            if state["failures"] >= 2:
                return (
                    f"Python 图表生成失败并已停止重试：{_clean_search_text(exc, 200)}。"
                    "本轮不要再调用 `render_python_chart`，请直接用文字、简表或已有数据回答。"
                )
        return (
            f"Python 图表生成失败：{_clean_search_text(exc, 200)}。"
            "请修正为包含 x 和 series.data 的 JSON 后最多再试一次，不要重复同一参数。"
        )
    title = _clean_search_text(spec.get("title") or "Python 图表", 120)
    return (
        f"Python 图表已生成：\n\n![{title}]({result['url']})\n\n"
        f"图表文件：{result['path']}\n"
        f"中文字体：{result['font']}"
    )


def _parse_metric_number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(",", "").replace("%", "").replace("−", "-")
    text = re.sub(r"[^\d.\-]", "", text)
    if text in {"", "-", ".", "-."}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _period_sort_key_for_forecast(period: str) -> tuple[int, int]:
    text = str(period or "").strip().upper()
    match = re.match(r"Q([1-4])\s+(\d{4})$", text)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.match(r"FY(\d{4})\s+Q([1-4])$", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.match(r"H([12])\s+(\d{4})$", text)
    if match:
        return int(match.group(2)), int(match.group(1))
    return 9999, 9


def _next_quarter_label(period: str, steps: int = 1) -> str:
    fiscal_style = bool(re.match(r"FY\d{4}\s+Q[1-4]$", str(period or "").strip().upper()))
    year, quarter = _period_sort_key_for_forecast(period)
    for _ in range(steps):
        quarter += 1
        if quarter > 4:
            quarter = 1
            year += 1
    if fiscal_style:
        return f"FY{year} Q{quarter}"
    return f"Q{quarter} {year}"


def _next_half_year_label(period: str, steps: int = 1) -> str:
    year, half = _period_sort_key_for_forecast(period)
    for _ in range(steps):
        half += 1
        if half > 2:
            half = 1
            year += 1
    return f"H{half} {year}"


def _hw_additive_forecast(values: list[float], horizon: int, season_length: int = 4) -> tuple[list[float], str, float | None]:
    if len(values) < season_length * 2:
        return _seasonal_naive_forecast(values, horizon, season_length), "seasonal_naive_insufficient_history", None
    best: tuple[float, list[float], tuple[float, float, float]] | None = None
    alphas = [0.2, 0.4, 0.6, 0.8]
    betas = [0.05, 0.15, 0.30]
    gammas = [0.05, 0.15, 0.30]
    initial_level = sum(values[:season_length]) / season_length
    second_level = sum(values[season_length:season_length * 2]) / season_length
    initial_trend = (second_level - initial_level) / season_length
    seasonals = [values[i] - initial_level for i in range(season_length)]
    for alpha in alphas:
        for beta in betas:
            for gamma in gammas:
                level = initial_level
                trend = initial_trend
                seasonal = seasonals[:]
                fitted: list[float] = []
                errors: list[float] = []
                ok = True
                for i, actual in enumerate(values):
                    if i >= season_length:
                        forecast = level + trend + seasonal[i % season_length]
                        fitted.append(forecast)
                        errors.append(actual - forecast)
                    prev_level = level
                    try:
                        level = alpha * (actual - seasonal[i % season_length]) + (1 - alpha) * (level + trend)
                        trend = beta * (level - prev_level) + (1 - beta) * trend
                        seasonal[i % season_length] = gamma * (actual - level) + (1 - gamma) * seasonal[i % season_length]
                    except Exception:
                        ok = False
                        break
                    if not all(math.isfinite(item) for item in [level, trend, seasonal[i % season_length]]):
                        ok = False
                        break
                if not ok or not errors:
                    continue
                rmse = math.sqrt(sum(err * err for err in errors) / len(errors))
                future = [level + step * trend + seasonal[(len(values) + step - 1) % season_length] for step in range(1, horizon + 1)]
                if best is None or rmse < best[0]:
                    best = (rmse, future, (alpha, beta, gamma))
    if best is None:
        return _seasonal_naive_forecast(values, horizon, season_length), "seasonal_naive_fit_failed", None
    rmse, future, params = best
    method = f"holt_winters_additive_grid_search(alpha={params[0]}, beta={params[1]}, gamma={params[2]}, season_length={season_length})"
    return future, method, rmse


def _seasonal_naive_forecast(values: list[float], horizon: int, season_length: int = 4) -> list[float]:
    if not values:
        return []
    if len(values) < season_length:
        return [values[-1]] * horizon
    return [values[-season_length + ((step - 1) % season_length)] for step in range(1, horizon + 1)]


def _selected_quarterly_metrics_path() -> Path | None:
    selected = _selected_dataset_ids()
    candidates: list[Path] = []
    root = ROOT / "agent_knowledge"
    if not root.exists():
        return None
    for folder in root.glob("quarterly_competitor_metrics_*"):
        if not folder.is_dir():
            continue
        csv_path = folder / "quarterly_metrics.csv"
        if not csv_path.exists():
            continue
        dataset_id = folder.name
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            dataset_id = str(manifest.get("id") or dataset_id)
            visibility = str(manifest.get("visibility") or "").strip().lower()
        except Exception:
            visibility = ""
        if visibility in {"hidden", "superseded", "archived"}:
            continue
        if selected is not None and dataset_id not in selected and folder.name not in selected:
            continue
        candidates.append(csv_path)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (path.parent.name, path.stat().st_mtime), reverse=True)[0]


@tool
def forecast_quarterly_metric(
    forecast_spec: str = "",
    subject: str = "",
    metric_key: str = "revenue",
    horizon: int = 4,
    category: str = "",
) -> str:
    """用已选择的季度/半年度指标数据库做趋势预测。
    当用户要求“预测未来”“趋势预测”“forecast”“未来4个季度”等时使用。
    优先传结构化参数 subject、metric_key、horizon、category；也兼容 forecast_spec JSON 字符串。季度数据会优先使用 official_value；official_conflict 采用 official_value，source_gap 行不参与预测。
    """
    raw = str(forecast_spec or "").strip()
    spec: dict[str, Any] = {}
    if raw:
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            spec = json.loads(raw)
        except Exception:
            spec = {}
    subject = _clean_search_text(spec.get("subject") or subject, 80)
    metric_key = _clean_search_text(spec.get("metric_key") or metric_key or "revenue", 80)
    category = _clean_search_text(spec.get("category") or category, 80)
    horizon = max(1, min(int(spec.get("horizon") or horizon or 4), 8))
    if not subject:
        return "预测失败：缺少 subject。请指定主体，例如 AWS、中国移动、Microsoft Azure / Intelligent Cloud。"
    csv_path = _selected_quarterly_metrics_path()
    if csv_path is None:
        return "预测失败：当前未选择可用的 quarterly_competitor_metrics 数据库。请在数据库按钮中选择 5 年季度/半年度数据包。"
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("subject") != subject or row.get("metric_key") != metric_key:
                continue
            if category and row.get("category") and row.get("category") != category:
                continue
            if row.get("grain") not in {"quarter", "half_year"}:
                continue
            if row.get("verification_status") == "source_gap_confirmed":
                continue
            value = _parse_metric_number(row.get("official_value") or row.get("value"))
            if value is None:
                continue
            rows.append({**row, "_numeric_value": value})
    rows.sort(key=lambda row: _period_sort_key_for_forecast(row.get("period") or ""))
    grain_counts = collections.Counter(row.get("grain") or "quarter" for row in rows)
    grain = grain_counts.most_common(1)[0][0] if grain_counts else "quarter"
    rows = [row for row in rows if (row.get("grain") or "quarter") == grain]
    sample_label = "半年度" if grain == "half_year" else "季度"
    season_length = 2 if grain == "half_year" else 4
    if len(rows) < 8:
        return f"预测失败：{subject} {metric_key} 可用{sample_label}样本只有 {len(rows)} 个，少于 8 个，不适合做趋势预测。"
    periods = [row["period"] for row in rows]
    values = [float(row["_numeric_value"]) for row in rows]
    forecasts, method, rmse = _hw_additive_forecast(values, horizon, season_length)
    backtest = rolling_backtest(values, season_length, _hw_additive_forecast)
    residual_proxy = rmse if rmse is not None else (statistics.pstdev(values[-8:]) if len(values) >= 8 else 0.0)
    if grain == "half_year":
        future_periods = [_next_half_year_label(periods[-1], step) for step in range(1, horizon + 1)]
    else:
        future_periods = [_next_quarter_label(periods[-1], step) for step in range(1, horizon + 1)]
    unit = rows[-1].get("official_unit") or rows[-1].get("unit") or ""
    metric_zh = rows[-1].get("metric_zh") or metric_key
    table_lines = [
        "| 预测期 | 预测值 | 低位区间 | 高位区间 |",
        "|---|---:|---:|---:|",
    ]
    for period, forecast in zip(future_periods, forecasts):
        low = forecast - residual_proxy
        high = forecast + residual_proxy
        table_lines.append(f"| {period} | {forecast:,.0f} | {low:,.0f} | {high:,.0f} |")
    history_tail = [
        {"period": period, "value": value}
        for period, value in zip(periods[-12:], values[-12:])
    ]
    chart_spec = {
        "type": "line",
        "title": f"{subject} {metric_zh} 历史与预测",
        "unit": unit,
        "x": periods[-12:] + future_periods,
        "series": [
            {"name": "历史", "data": values[-12:] + [None] * horizon},
            {"name": "预测", "data": [None] * len(values[-12:]) + [round(item, 3) for item in forecasts]},
        ],
    }
    try:
        chart_result = render_chart(chart_spec)
        chart_md = f"![{chart_spec['title']}]({chart_result['url']})\n图表文件：{chart_result['path']}"
    except Exception as exc:
        chart_md = f"图表生成失败：{_clean_search_text(exc, 160)}"
    source = csv_path.relative_to(ROOT).as_posix()
    payload = {
        "type": "meta",
        "sources": [source],
        "links": [{"label": source, "url": f"/references/{source}"}],
        "references": [{"index": 1, "source": source, "links": [{"label": source, "url": f"/references/{source}"}]}],
        "forecastAudit": {
            "subject": subject,
            "metric_key": metric_key,
            "horizon": horizon,
            "sample_count": len(values),
            "grain": grain,
            "model": method,
            "rmse": rmse,
            "backtest": backtest,
        },
    }
    if backtest.get("ok"):
        scores = backtest.get("scores") or {}
        baseline_text = (
            f"- 回测窗口：{backtest.get('windows')} 个；"
            f"Holt-Winters RMSE={scores.get('holt_winters', {}).get('rmse', 0):,.3f}，"
            f"naive RMSE={scores.get('naive', {}).get('rmse', 0):,.3f}，"
            f"seasonal naive RMSE={scores.get('seasonal_naive', {}).get('rmse', 0):,.3f}；"
            f"RMSE 最优：{backtest.get('best_baseline')}。\n"
        )
    else:
        baseline_text = f"- 回测：{backtest.get('reason') or '未执行'}\n"
    return (
        f"趋势预测结果：{subject} {metric_zh}（{metric_key}）\n"
        f"- 数据来源：{source}\n"
        f"- 历史样本：{len(values)} 个{sample_label}，{periods[0]} 至 {periods[-1]}\n"
        f"- 数值口径：优先 official_value；official_conflict 采用官方值；source_gap 不参与拟合。\n"
        f"- 模型：{method}\n"
        f"- 回测误差代理 RMSE：{rmse:,.3f}\n"
        f"{baseline_text}" if rmse is not None else
        f"趋势预测结果：{subject} {metric_zh}（{metric_key}）\n"
        f"- 数据来源：{source}\n"
        f"- 历史样本：{len(values)} 个{sample_label}，{periods[0]} 至 {periods[-1]}\n"
        f"- 数值口径：优先 official_value；official_conflict 采用官方值；source_gap 不参与拟合。\n"
        f"- 模型：{method}\n"
        f"{baseline_text}"
    ) + (
        "\n".join(table_lines)
        + "\n\n"
        + chart_md
        + "\n\n"
        + "重要说明：这是基于历史序列的机械趋势预测，不是投资建议；未纳入管理层指引、宏观变量、政策、竞争和一次性项目影响。\n"
        + f"最近历史样本：{json.dumps(history_tail, ensure_ascii=False)}"
        + f"\n<metadata>{json.dumps(payload, ensure_ascii=False)}</metadata>"
    )

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


@tool
def search_agent_memory(query: str, limit: int = 5) -> str:
    """搜索小竞AI本地长期运行记忆。
    当用户询问偏好、之前确认过的生产规则、长期约束、上下文管理策略或历史工作流时使用。
    记忆只作为辅助上下文；正式数据结论仍必须以当前选择数据库、官方来源和审计文件为准。
    """
    rows = search_memories(query, limit=limit)
    if not rows:
        return "未找到相关长期记忆。"
    lines = ["小竞AI长期记忆命中："]
    for index, item in enumerate(rows, 1):
        lines.append(
            f"[记忆 {index}] {item.get('content')}\n"
            f"- kind: {item.get('kind')}\n"
            f"- tags: {'、'.join(item.get('tags') or []) or '无'}\n"
            f"- entities: {'、'.join(item.get('entities') or []) or '无'}\n"
            f"- score: {item.get('score', 'n/a')}; importance: {item.get('importance')}; confidence: {item.get('confidence')}\n"
            f"- date: {item.get('created_date')}; access_count: {item.get('access_count', 0)}"
        )
    return "\n\n".join(lines)


def _chat_message_content(message: dict[str, Any], limit: int = 1200) -> str:
    return _clean_search_text(message.get("content") or message.get("text") or "", limit)


def _chat_history_rows(query: str, limit: int = 5, context_window: int = 2) -> list[dict[str, Any]]:
    if not CHAT_THREADS_PATH.exists():
        return []
    try:
        data = json.loads(CHAT_THREADS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    threads = data.get("threads") if isinstance(data, dict) else data
    if not isinstance(threads, list):
        return []
    clean_query = _clean_search_text(query, 300)
    query_terms = {term for term in re.split(r"[\s,，。；;:：!?！？、]+", clean_query.lower()) if term}
    rows: list[dict[str, Any]] = []
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        messages = thread.get("messages") if isinstance(thread.get("messages"), list) else []
        thread_title = _clean_search_text(thread.get("title") or "", 120)
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            content = _chat_message_content(message, 1200)
            if not content:
                continue
            haystack = f"{thread_title} {content}".lower()
            score = 0
            if clean_query and clean_query.lower() in haystack:
                score += 20
            score += sum(2 for term in query_terms if term in haystack)
            if score <= 0:
                continue
            start = max(0, index - max(0, int(context_window or 0)))
            end = min(len(messages), index + max(0, int(context_window or 0)) + 1)
            context_messages = []
            for context_index in range(start, end):
                context_message = messages[context_index]
                if not isinstance(context_message, dict):
                    continue
                context_content = _chat_message_content(context_message, 1200)
                if not context_content:
                    continue
                context_messages.append(
                    {
                        "message_index": context_index + 1,
                        "role": context_message.get("role") or "unknown",
                        "content": context_content,
                        "created_at": context_message.get("createdAt") or "",
                        "is_match": context_index == index,
                    }
                )
            rows.append(
                {
                    "score": score,
                    "thread_id": thread.get("id") or "",
                    "thread_title": thread_title or "未命名对话",
                    "thread_updated_at": thread.get("updatedAt") or "",
                    "message_index": index + 1,
                    "role": message.get("role") or "unknown",
                    "content": content,
                    "created_at": message.get("createdAt") or "",
                    "context_messages": context_messages,
                }
            )
    rows.sort(key=lambda item: (int(item["score"]), str(item.get("thread_updated_at") or "")), reverse=True)
    return rows[: max(1, min(int(limit or 5), 20))]


@tool
def search_chat_history(query: str, limit: int = 5) -> str:
    """搜索小竞AI已保存的历史聊天线程。
    当用户询问“之前聊过什么”“上一轮/早先/某次我说过什么”“历史聊天记录里有没有”等问题时使用。
    该工具只检索本地保存的聊天线程，不等同于长期记忆；回答时要说明命中的线程、角色和消息序号。
    """
    rows = _chat_history_rows(query, limit=limit)
    if not rows:
        return "未在已保存的历史聊天线程中找到匹配消息。"
    lines = ["历史聊天记录命中："]
    for index, item in enumerate(rows, 1):
        role = "AI" if str(item.get("role") or "").lower() == "assistant" else "用户"
        lines.append(
            f"[聊天命中 {index}] thread={item.get('thread_title')} ({item.get('thread_id')}); "
            f"message_index={item.get('message_index')}; role={role}; updated_at={item.get('thread_updated_at')}\n"
            f"{item.get('content')}"
        )
        context_messages = item.get("context_messages") if isinstance(item.get("context_messages"), list) else []
        if context_messages:
            lines.append("邻近对话上下文：")
            for context_message in context_messages:
                context_role = "AI" if str(context_message.get("role") or "").lower() == "assistant" else "用户"
                marker = " ← 命中" if context_message.get("is_match") else ""
                lines.append(
                    f"- message_index={context_message.get('message_index')}; role={context_role}{marker}: "
                    f"{context_message.get('content')}"
                )
    return "\n\n".join(lines)


@tool
def remember_agent_memory(content: str, kind: str = "semantic", tags: str = "", importance: float = 0.7, confidence: float = 0.85) -> str:
    """写入一条小竞AI长期运行记忆。
    只在用户明确要求“记住/以后都/默认/规则/偏好”，或你确认这是跨会话可复用的生产规则时使用。
    不要写入 API key、个人隐私、未验证数据值或完整聊天历史。
    """
    tag_list = [item.strip() for item in re.split(r"[,，;；\s]+", tags or "") if item.strip()]
    try:
        item = add_memory(
            content,
            kind=kind or "semantic",
            tags=tag_list,
            source="agent-tool",
            importance=importance,
            confidence=confidence,
        )
    except Exception as exc:
        return f"写入长期记忆失败：{exc}"
    return (
        f"已写入长期记忆：{item['id']}，kind={item.get('kind')}，"
        f"importance={item.get('importance')}，confidence={item.get('confidence')}，date={item['created_date']}。"
    )


@tool
def list_agent_memory(limit: int = 10) -> str:
    """列出最近的小竞AI长期运行记忆，用于审计 agent 记住了什么。"""
    rows = load_memories(limit=max(1, min(int(limit or 10), 30)))
    if not rows:
        return "当前没有长期记忆。"
    return "\n\n".join(
        f"[记忆 {index}] {item.get('content')}\n"
        f"- kind: {item.get('kind')}\n"
        f"- tags: {'、'.join(item.get('tags') or []) or '无'}\n"
        f"- entities: {'、'.join(item.get('entities') or []) or '无'}\n"
        f"- status: {item.get('status')}; importance: {item.get('importance')}; confidence: {item.get('confidence')}\n"
        f"- date: {item.get('created_date')}; access_count: {item.get('access_count', 0)}"
        for index, item in enumerate(rows, 1)
    )


@tool
def list_database_lineage() -> str:
    """列出本轮已选择数据库的版本、血缘、manifest、文件数量和指纹。
    当用户问数据库来源、版本、是否过期、数据血缘、可审计性，或需要正式说明当前答案基于哪个数据包时使用。
    """
    rows = dataset_lineage(_selected_dataset_ids())
    if not rows:
        return "当前未选择任何可见数据库，无法生成数据库血缘。"
    lines = ["本轮已选择数据库血缘："]
    for index, row in enumerate(rows, 1):
        lines.append(
            "\n".join(
                [
                    f"[数据库 {index}] {row.get('title') or row.get('id')}",
                    f"- id: {row.get('id')}",
                    f"- version: {row.get('version') or '未声明'}",
                    f"- built_at: {row.get('built_at') or row.get('updated_at') or '未声明'}",
                    f"- row_count: {row.get('row_count') or '未声明'}",
                    f"- verified_count: {row.get('verified_count') or '未声明'}",
                    f"- gap_count: {row.get('gap_count') or '未声明'}",
                    f"- manifest: {row.get('manifest_path') or '无'}",
                    f"- files: {row.get('file_count')} 个，fingerprint={row.get('fingerprint')}",
                    f"- quality: {row.get('quality') or '未说明'}",
                ]
            )
        )
    return "\n\n".join(lines)

def _thinking_model_name(model_name: str) -> str:
    configured = (os.environ.get("AI_THINKING_MODEL") or os.environ.get("DEEPSEEK_THINKING_MODEL") or "").strip()
    if configured:
        return configured
    if "deepseek" in model_name.lower():
        return "deepseek-reasoner"
    return model_name


def _agent_model_name(thinking_enabled: bool = False) -> str:
    config = load_ai_config()
    model_name = config.get("model", "deepseek-chat")
    if thinking_enabled:
        return _thinking_model_name(str(model_name))
    if "reasoner" in str(model_name):
        return "deepseek-chat"
    return str(model_name)


def _agent_tools(allow_web_search: bool = True):
    tools = [
        read_agent_skill,
        list_local_datasets,
        list_crawl_runs,
        search_local_reports,
        read_local_reference,
        trigger_crawl,
        trigger_full_crawl,
        feishu_cli,
        trigger_report_generation,
        trigger_carrier_performance_report_generation,
        list_report_outputs,
        get_crawl_settings_summary,
        render_python_chart,
        forecast_quarterly_metric,
        get_system_status,
        search_agent_memory,
        search_chat_history,
        remember_agent_memory,
        list_agent_memory,
        list_database_lineage,
    ]
    if allow_web_search:
        insert_at = 4
        tools[insert_at:insert_at] = [web_search, read_webpage]
    return tools


def get_agent(thinking_enabled: bool = False, allow_web_search: bool = True, runtime_context: dict[str, Any] | None = None):
    config = load_ai_config()
    api_key = config.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
    base_url = config.get("base_url", "") or os.environ.get("OPENAI_API_BASE", "")
    model_name = _agent_model_name(thinking_enabled=thinking_enabled)

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
    
    tools = _agent_tools(allow_web_search=allow_web_search)

    if allow_web_search:
        source_rule = "【强制规则 - 来源引用】当你的回答参考了 `search_local_reports`、`web_search` 或其他工具返回的上下文时，必须在文中用 [1], [2] 等格式进行内联标号（对应 [来源 1], [来源 2] 的编号）。本地检索通常使用 [1]-[5]，联网搜索通常从 [6] 开始编号；必须沿用工具结果中的实际编号。**请将标号紧跟在每一条具体的数据或事实后面**，绝对不要把一堆标号集中放在大标题上或段落末尾。禁止使用 `[来源: 文件名]`、`[来源: 机构名]`、`[source: ...]` 这种名称型标注，只能使用数字标号。**禁止在回答末尾自行输出任何 <引用来源>、<references> 等参考文献列表**，系统会自动展示。\n"
        retrieval_pairing_rule = "【检索工具搭配】对公开信息、竞对动态、收入/财报、政策、行业趋势、最新进展等问题，默认尽量同时调用 `search_local_reports` 和 `web_search`：先用 `search_local_reports` 获取本地监测和周报上下文，再用 `web_search` 获取联网公开来源；除非用户明确只要本地或只要联网，不要只调用其中一个。\n"
        cross_check_rule = "【本地与联网交叉校验】当 `search_local_reports` 与 `web_search` 返回的数据在日期、口径、金额、比例、主体名称或结论上存在出入时，必须在回答中单独说明差异：分别列出本地资料口径、联网公开来源口径、可能原因和建议采用的可信口径。禁止把冲突数据混合成一个确定结论。\n"
        local_original_rule = "【本地原文优先】`search_local_reports` 只是本地检索摘要；只要问题涉及数据、财报、收入、对比、结论判断或口径核对，并且你已经调用了 `search_local_reports`，就必须至少对一个最相关的本地来源调用 `read_local_reference`（例如 `weekly_report.md` 或 `row_2.json`）查看原文后再回答。如果本地检索结果没有相关来源，才说明本地原文不足。不要在没有读本地引用原文的情况下连续打开外部网页。\n"
        quarterly_crosscheck_sentence = "`needs_official_row_crosscheck` 只能作为线索，正式结论必须继续联网或读取官方来源核验。"
        web_rule = "【联网搜索】当用户明确要求上网、联网搜索、查最新公开信息，或本地资料不足以回答时，必须调用 `web_search`。搜索后仍需用 [1], [2] 标注具体事实来源；只有用户要求打开网页全文或搜索摘要不足以核实时，才对最多 2 个关键结果调用 `read_webpage`。若 `read_webpage` 返回失败、跳过、浏览器验证或 PDF 抽取失败，不要反复读取同一类链接，应改用搜索摘要、本地引用和其他公开来源交叉验证。\n"
    else:
        source_rule = "【强制规则 - 来源引用】当你的回答参考了 `search_local_reports`、`read_local_reference` 或其他本地工具返回的上下文时，必须在文中用 [1], [2] 等格式进行内联标号，并沿用工具结果中的实际编号。**请将标号紧跟在每一条具体的数据或事实后面**，绝对不要把一堆标号集中放在大标题上或段落末尾。禁止使用 `[来源: 文件名]`、`[来源: 机构名]`、`[source: ...]` 这种名称型标注，只能使用数字标号。**禁止在回答末尾自行输出任何 <引用来源>、<references> 等参考文献列表**，系统会自动展示。\n"
        retrieval_pairing_rule = "【本地检索优先】优先调用 `search_local_reports`、`list_local_datasets`、`read_local_reference` 等当前可用工具回答，不得声称使用了未实际调用的工具，不得编造检索结果。用户要求搜索、查最新或公开资料时，也直接按本地可用数据检索和回答；资料不足时，只说明缺少的具体本地依据，并给出可以继续核验的本地数据路径或来源。不要解释当前工具开关、联网能力或前端配置状态。\n"
        cross_check_rule = "【本地核验优先】基于本地标准化数据集、周报、爬虫结果、审计日志和已保存来源进行回答；资料不足时只说明缺少哪些数据或依据。\n"
        local_original_rule = "【本地原文优先】`search_local_reports` 只是本地检索摘要；只要问题涉及数据、财报、收入、对比、结论判断或口径核对，并且你已经调用了 `search_local_reports`，就必须至少对一个最相关的本地来源调用 `read_local_reference`（例如 `weekly_report.md` 或 `row_2.json`）查看原文后再回答。如果本地检索结果没有相关来源，才说明本地原文不足。\n"
        quarterly_crosscheck_sentence = "`needs_official_row_crosscheck` 只能作为线索，正式结论必须读取本地已保存官方来源或本地引用原文核验。"
        web_rule = "【回答方式】只输出答案本身，不额外解释当前能力配置、联网能力或前端设置，也不要引导用户调整前端设置；本地依据不足时，只说缺少哪些本地数据或引用。\n"
    
    runtime_context = runtime_context or {}
    runtime_lines = [
        f"- 当前时间: {runtime_context.get('current_time') or 'unknown'}",
        f"- 时区: {runtime_context.get('timezone') or 'unknown'} ({runtime_context.get('utc_offset') or ''})",
        f"- 请求 IP: {runtime_context.get('visible_ip') or runtime_context.get('client_ip') or 'unknown'}",
        f"- X-Forwarded-For: {runtime_context.get('forwarded_for') or 'none'}",
        f"- 位置推断: {runtime_context.get('location_hint') or 'unknown'}",
    ]
    runtime_context_text = "\n".join(runtime_lines)

    system_message = (
        "你是中国移动战略部公开信息监测系统的智能 RAG 和运维助手。\n"
        "【当前运行上下文】以下信息由后端按本次请求实时注入。凡用户提到“今天、现在、目前、最新、上个季度、上一季度、最近”等相对时间，必须优先用这里的当前时间和时区定位；涉及地域、网络可达性或本地/公网判断时，可参考请求 IP 和位置推断，但不要把粗略位置当作精确地理定位。\n"
        f"{runtime_context_text}\n"
        "调用 `feishu_cli` 时必须使用完整参数 `--spreadsheet-token ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA`，不要使用 `-t` 简写或位置参数。例如查询数据使用：`sheets +read --spreadsheet-token ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA --range 9c638d!A1:C10`。\n"
        "【核心法则】如果你不确定某个 CLI 命令（特别是 `+update`、`+write` 等子命令）的具体用法和参数格式，**绝对不允许瞎猜尝试**！你必须先执行 `feishu_cli sheets +update --help` 等命令查阅帮助文档，然后再进行真正的调用。\n"
        "【重要】核心数据表的工作表名称是\"主表\"，其对应的 sheet_id 为 9c638d。当查询或修改\"主表\"时，务必使用 9c638d 作为 range 前缀，例如 `--range 9c638d!A2:Z2`。\n"
        "【极度重要】表格的列结构可能随时发生变化（用户会动态插入或删除列）。如果你需要读取或写入特定字段的数据，**严禁直接凭记忆写死列号**（例如想当然地认为H列必定是更新频率）。你必须先使用 lark-cli 读取第一行表头（例如 `--range 9c638d!A1:Z1`），精确查明各个字段当前实际所在的字母列后，再执行后续的行列操作！\n"
        f"{source_rule}"
        "【本地数据边界】你能接触到的本地数据不是无限的，必须以工具返回为准：`list_local_datasets` 用于列出标准化数据集，`search_local_reports` 用于检索标准化数据集、周报、审计日志和爬取结果，`read_local_reference` 用于读取可点击引用原文。用户问“你能访问哪些数据”“数据放哪里”“内部/外部数据怎么接入”“后端有哪些数据”时，必须先调用 `list_local_datasets` 再回答。做趋势分析、问数、财报对比、口径核验、图表之前，如果不确定可用数据，也要先调用 `list_local_datasets`。\n"
        "【上下文预算审计】`search_local_reports` 会返回 contextAudit，包含 token_budget、token_estimate、retained_chunks、compressed_chunks、skipped_chunks。若 compressed_chunks 或 skipped_chunks 大于 0，正式回答必须把结论限定在已保留上下文内，并在必要时说明仍需读取原文或缩小问题范围。不要声称已完整读取未进入上下文预算的全部文件。\n"
        "【长期记忆边界】`search_agent_memory`、`remember_agent_memory`、`list_agent_memory` 只用于小竞AI运行偏好、长期规则和已验证流程。长期记忆不能替代本轮用户指令、前端数据库选择、官方来源、审计文件或工具返回结果；若记忆与本轮上下文冲突，必须以本轮上下文为准。\n"
        "【历史聊天边界】当用户询问此前聊天、上一轮、早先说过什么、某个历史对话内容或要求核对聊天记录时，必须调用 `search_chat_history` 检索已保存聊天线程；不要只凭最近 8 条上下文或长期记忆猜测。回答要区分“历史聊天记录命中”和“长期记忆命中”。\n"
        "【Agent Skill 渐进加载】前端选择的 Skill 不是固定开场流程，但它们是专业分析方法。历史聊天查询、寒暄、简单问答、纯记忆审计和无需领域规则的问题，不要为了流程感读取 Skill；但当用户要求分析竞对经营数据、云厂商数据、宏观政策、趋势预测或战略简报时，应优先读取最相关的 1-2 个已选 Skill，再按 Skill 方法调用数据库检索、原文核验、预测或图表工具。不要把所有已选 Skill 全部读一遍。\n"
        "【新增数据规范】后续新增内部或外部数据时，默认放入项目根目录 `agent_knowledge/<dataset_id>/`。每个数据集至少提供 `manifest.json`，建议同时提供 `README.md`、结构化 `data.csv` 或 `data.json`、摘要 `summary.md`、来源 `sources.json`。允许被后端索引和引用的文本文件扩展名只有 `.md`、`.txt`、`.json`、`.csv`、`.tsv`。`manifest.json` 应写明 id、title、summary、source_type、scope、tags、keywords、entrypoints、updated_at、quality。除非工具列出，否则不要声称自己能读取其他本地目录。\n"
        "【数据库选择边界】前端数据库按钮是强访问边界。只有本轮用户已选择的 `agent_knowledge` 数据库才允许被 `list_local_datasets`、`search_local_reports` 和 `read_local_reference` 读取或引用；未选择的数据集不可见。不得根据历史提示、路径记忆或未调用工具的信息声称知道未选择数据库的内容。若季度、核心公司或云厂商数据集被选择，按工具返回的 manifest、CSV/JSON 行和引用原文回答；`verification_count>=2` 表示该行已完成多来源核验，`official_conflict` 表示正式回答采用 `official_value` 并说明标准化值与官方披露冲突。\n"
        "【目标级审计优先】当用户询问“现在数据是否完整/准确/能否预测/数据库是否正常/来源是否可靠/目标完成到哪一步”或要求给出正式数据质量结论时，如果已选择 `goal_readiness_audits`、`knowledge_integrity_audits`、`source_evidence_audits`、`source_url_reachability_audits`、`forecast_readiness_audits` 或 `agent_dataset_visibility_audits`，必须先检索并读取相关审计。正式回答要以这些审计中的 pass/fail、row_count、verification_count、official_value/source_gap 和 API 可见性结果为准；不要只凭主数据包或历史记忆判断完成度。被 manifest 标记为 `superseded`、`hidden` 或 `archived` 的数据包不得作为默认数据库或正式结论来源。\n"
        "【宏观政策数据包】若用户询问 CMHK 预测、趋势判断、香港电信市场、5G、频谱、移动用户、宽带渗透率、SIM 实名、监管政策或宏观环境，并且已选择 `cmhk_macro_policy_*` 数据库，必须检索并读取该数据包。宏观政策包用于解释市场背景、外生变量和政策事件；年度/事件粒度记录不得替代公司季度数据，也不得把政策事件直接当作收入/利润预测目标。正式结论仍使用 `official_value`，`source_gap_confirmed` 不得估算。\n"
        "【精确指标边界】问数时必须严格保持用户要的指标，不得把派生指标改写成基础指标。尤其是：`收入同比`、`营收同比`、`营业收入同比`、`收入增长`、`revenue_growth_yoy`、`YoY` 对应 `metric_key=revenue_growth_yoy`，不是 `revenue`；`EBITDA率` 对应 `metric_key=ebitda_margin`，不是 `ebitda`；`经营利润率` 对应 `operating_margin`，不是 `operating_income`；`毛利率` 对应 `gross_margin`，不是 `gross_profit`。调用 `search_local_reports` 时必须把这些关键词原样带入 query，最终回答也必须引用命中的同一指标行。\n"
        "【表格输出限制】除非用户明确要求导出完整 CSV/Excel，否则最终回答中的 Markdown 表格最多输出 30 行、8 列；超过范围时先给摘要和关键行，并提示用户缩小范围或导出文件。Markdown 表格必须一次性输出完整表头、分隔行和完整数据行，每一行都以 `|` 结尾；单个指标优先用项目符号，不要为了一个数值强行输出表格。后端会对超限表格做截断，不要把大表格分批塞进同一条回答。\n"
        "【爬虫日志调度】每次全量爬虫完成后，系统会登记 `agent_knowledge/crawl_run_logs/`：本地只保存运行索引和摘要，完整逐 URL 日志与 Agent 处理流程写入飞书日志子表。用户问上次爬虫、失败链接、覆盖率、日志在哪、Agent 是否处理完成时，必须先调用 `list_crawl_runs`；需要更细节再用 `search_local_reports` 或 `read_local_reference` 读取 `run_log.tsv`、`coverage_report.tsv`、`final_audit.md`。\n"
        "【操作工具决策权】用户要求生成周报、生成运营商业绩摘要、全量爬取、查看输出文件、查看爬取设置或查看系统状态时，由你根据用户真实意图自行决定是否调用 `trigger_report_generation`、`trigger_carrier_performance_report_generation`、`trigger_full_crawl`、`list_report_outputs`、`get_crawl_settings_summary`、`get_system_status` 等工具。不要把“输出预测表”“生成预测图”“正式结论”等分析表达误判成报告生成；只有用户确实要产出 Word 周报或业绩摘要时才调用生成类工具。\n"
        "【前端展示边界】前端会按事件顺序展示工具调用卡片；工具调用行会自动显示“读取 Skill / 检索数据库 / 联网搜索 / 读取原文”等过程说明。最终正文严禁重复检索过程、工具状态或准备动作，例如“联网已搜到”“本地检索结果只返回”“本地数据已命中”“CSV文件很大”“我继续检索”“我再读取”“数据充足”等。最终正文只输出结论、数据、依据、口径差异和必要不确定性。\n"
        f"{retrieval_pairing_rule}"
        f"{local_original_rule}"
        f"{cross_check_rule}"
        f"{quarterly_crosscheck_sentence}"
        "【Python 图表工具】当用户要求画图、趋势图、柱状图、表格+图表或可视化时，在完成数据检索和核验后必须优先调用 `render_python_chart` 生成 PNG 图表。`chart_spec` 必须是 JSON 对象字符串，结构为 `{\"type\":\"line|bar\",\"title\":\"...\",\"unit\":\"...\",\"x\":[\"2024Q1\"],\"series\":[{\"name\":\"收入\",\"data\":[123]}]}`；series 使用 `data` 数组，不要使用其他字段名。不要把 `<chart>` JSON 当作主要输出，也不要在正文里手写 `<chart>` 块。图表 JSON 的中文标题、图例和备注必须直接写中文，工具会处理中文字体渲染。注意：光画图就行，图片中不要放底部的解释性长段文字（例如详细结论或分析），以防遮挡图例或影响美观。若 `render_python_chart` 返回“停止”或同一参数失败过，必须立即停止图表工具调用，改用文字结论或简表回答。\n"
        "【趋势预测工具】当用户要求“预测未来”“趋势预测”“forecast”“未来4个季度”“未来几个季度/半年”等，并且问题涉及 quarterly_competitor_metrics 数据库中的季度指标时，必须优先调用 `forecast_quarterly_metric`，不要只靠模型心算或简单均值口算。预测工具使用已选数据库、官方优先数值和 Holt-Winters 加性季节模型，并且已经返回预测表和 PNG 图表；除非用户明确要求第二张不同图，否则不要再调用 `render_python_chart` 重复画同一预测图。如果用户同时选择宏观政策包，可用其解释外部背景和风险，但不能把年度/事件粒度宏观政策行混入季度模型拟合。如果用户要求解释，再说明模型局限和非投资建议。\n"
        f"{web_rule}"
        "【强制规则 - 无图标/Emoji】所有的文字输出中绝对禁止使用任何 Emoji、表情符号或特殊排版图标。保持极其严肃、专业的纯文本风格。\n"
        "【重要】如果你连续 3 次调用某个工具均未能成功（比如参数错误、表名不对或输出过多），请立即停止调用，并直接回复用户当前遇到的困难，不要陷入无限重试的死循环。\n\n"
        "【强制规则 - 推荐追问】你的每一条最终回复（无论长短、无论是否调用了工具）的最后一行都必须包含推荐追问。格式如下，不可省略：\n"
        "<suggestions>[\"追问1\", \"追问2\", \"追问3\"]</suggestions>\n"
        "追问内容应与当前话题紧密相关、对用户有实际价值；禁止把打开、关闭或调整前端开关、按钮、工具配置作为追问。这是一条不可违反的系统指令，任何回答如果缺少 <suggestions> 标签都是不合格的。\n"
    )
    
    return create_react_agent(llm, tools, prompt=system_message)


def _selected_skill_summaries(skill_ids: list[str] | None) -> list[dict[str, str]]:
    requested = [re.sub(r"[^A-Za-z0-9_.-]", "", str(item or "")) for item in (skill_ids or [])]
    requested = [item for item in requested if item]
    if not requested:
        return []
    by_id = {item["id"]: item for item in available_agent_skills()}
    rows = []
    for skill_id in requested[:5]:
        item = by_id.get(skill_id)
        if not item:
            continue
        rows.append({
            "id": skill_id,
            "title": str(item.get("title") or skill_id),
            "summary": str(item.get("description") or item.get("summary") or ""),
        })
    return rows


def _selected_dataset_summaries(dataset_ids: set[str]) -> list[dict[str, str]]:
    if not dataset_ids:
        return []
    rows = []
    for item in list_knowledge_datasets(dataset_ids=dataset_ids):
        rows.append({
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or item.get("id") or ""),
            "folder": str(item.get("folder") or ""),
            "summary": str(item.get("summary") or item.get("scope") or ""),
        })
    return rows


def _context_tool_content(title: str, rows: list[dict[str, str]], id_key: str = "id") -> str:
    if not rows:
        return f"{title}：无。"
    lines = [f"{title}：{len(rows)} 项"]
    for index, row in enumerate(rows, 1):
        name = row.get("title") or row.get(id_key) or f"项目 {index}"
        row_id = row.get(id_key) or ""
        summary = row.get("summary") or row.get("folder") or ""
        suffix = f"（{row_id}）" if row_id and row_id != name else ""
        lines.append(f"{index}. {name}{suffix}" + (f"\n   {summary}" if summary else ""))
    return "\n".join(lines)


def _stream_agent_events(agent: Any, inputs: dict[str, Any]):
    try:
        return agent.stream(inputs, stream_mode="messages", config={"recursion_limit": 50})
    except TypeError:
        return agent.stream(inputs, stream_mode="messages")


def _format_conversation_history(history: list[dict[str, Any]] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for item in history[-8:]:
        role = "AI" if str(item.get("role") or "").lower() == "assistant" else "用户"
        content = _clean_search_text(item.get("content") or "", 1800)
        if content:
            lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "同一聊天线程的最近对话如下，用于理解代词、继续追问和上一轮结论；若与本轮用户新指令冲突，以本轮新指令为准。\n" + "\n".join(lines)


def _tool_process_text(tool_name: str) -> str:
    labels = {
        "read_agent_skill": "我读取相关 Agent Skill 的完整指令。",
        "list_local_datasets": "我读取本轮已选数据库列表。",
        "search_agent_memory": "我查找长期记忆中是否有相关规则。",
        "search_local_reports": "我读取已选数据库并检索摘要片段。",
        "read_local_reference": "我读取命中的数据库原文，确认数据口径和来源。",
        "web_search": "我联网检索公开来源。",
        "read_webpage": "我读取网页原文核验细节。",
        "render_python_chart": "我基于已核验数据生成图表。",
        "forecast_quarterly_metric": "我调用趋势预测工具，使用历史数据生成预测。",
        "get_system_status": "我读取系统当前状态。",
        "search_chat_history": "我搜索已保存的历史聊天记录。",
        "list_report_outputs": "我查看已有报告输出。",
        "list_crawl_runs": "我读取爬虫运行日志。",
    }
    return labels.get(tool_name, f"我调用 {tool_name or '工具'} 获取依据。")


def stream_agent(
    message: str,
    force_web_search: bool = False,
    selected_skill_ids: list[str] | None = None,
    selected_dataset_ids: list[str] | None = None,
    thinking_enabled: bool = False,
    approved_action_ids: list[str] | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    emit_context_events: bool = True,
    loaded_skill_ids: list[str] | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> Generator[dict[str, Any], None, None]:
    _reset_web_search_indexes()
    try:
        captured_memory = auto_capture_user_memory(message)
    except Exception:
        captured_memory = None
    recalled_memory = memory_context(message, limit=5)
    selected_dataset_set = {
        re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]", "", str(item or ""))
        for item in (selected_dataset_ids or [])
        if str(item or "").strip()
    }
    selected_skill_set = {
        re.sub(r"[^A-Za-z0-9_.-]", "", str(item or ""))
        for item in (selected_skill_ids or [])
        if str(item or "").strip()
    }
    loaded_skill_set = {
        re.sub(r"[^A-Za-z0-9_.-]", "", str(item or ""))
        for item in (loaded_skill_ids or [])
        if str(item or "").strip()
    }
    dataset_token = SELECTED_DATASET_IDS.set(selected_dataset_set)
    skill_token = SELECTED_SKILL_IDS.set(selected_skill_set)
    approved_token = APPROVED_ACTION_IDS.set({str(item) for item in (approved_action_ids or []) if str(item).strip()})
    chart_token = CHART_RUN_STATE.set({"calls": 0, "failures": 0, "failed_signatures": {}})
    tool_token = TOOL_RUN_STATE.set({"counts": {}})
    recorder = AgentRunRecorder(
        message=message,
        selected_dataset_ids=sorted(selected_dataset_set),
        selected_skill_ids=[str(item) for item in (selected_skill_ids or [])],
        web_search_enabled=force_web_search,
        thinking_enabled=thinking_enabled,
        approved_action_ids=approved_action_ids or [],
    )
    try:
        agent = get_agent(thinking_enabled=thinking_enabled, allow_web_search=force_web_search, runtime_context=runtime_context)
    except TypeError as exc:
        if "runtime_context" not in str(exc):
            raise
        agent = get_agent(thinking_enabled=thinking_enabled, allow_web_search=force_web_search)
    thinking_step = 0

    def thinking_event(text: str) -> dict[str, Any]:
        nonlocal thinking_step
        thinking_step += 1
        return {"type": "thinking_status", "text": f"{thinking_step}. {text}"}

    if captured_memory:
        event = {"type": "process", "step": "长期记忆", "text": f"已记录一条运行记忆：{captured_memory.get('id')}。"}
        recorder.observe(event)
        yield event
    if recalled_memory:
        event = {"type": "process", "step": "长期记忆", "text": "已召回本地长期运行记忆作为辅助上下文。"}
        recorder.observe(event)
        yield event

    skill_context = _selected_skill_context(selected_skill_ids)
    skill_routing_instruction = _skill_routing_instruction(message, selected_skill_ids, loaded_skill_ids)
    # Selected skills and datasets are injected as model context below. They are not
    # rendered as fake tool calls; the UI should only show tools the Agent chose.
    if recalled_memory:
        message = f"{recalled_memory}\n\n用户问题：{message}"
    history_context = _format_conversation_history(conversation_history)
    if history_context:
        message = f"{history_context}\n\n本轮用户问题：{message}"
    if skill_context:
        loaded_skill_note = ""
        loaded_selected = sorted(selected_skill_set & loaded_skill_set)
        if loaded_selected:
            loaded_skill_note = (
                "本聊天线程此前已经读取过以下 Skill 的完整 SKILL.md："
                f"{', '.join(loaded_selected)}。"
                "若本轮只是延续同一问题且前文规则足够，不要重复调用 `read_agent_skill`；"
                "只有任务切换、规则不确定或需要确认具体步骤时才再次读取。\n"
            )
        message = (
            "用户已在前端手动选择以下 Agent Skills。下面只是 Skill 发现信息，不是完整指令。"
            "你可以自行判断是否需要读取某个 Skill 的完整 SKILL.md；"
            "如果本轮只是历史聊天查询、寒暄、简单问答、纯记忆审计，或无需领域规则，直接回答或调用更相关的工具，不要固定先读 Skill。"
            "如果该 Skill 已在本聊天线程前序回合读取过，且本轮只是延续同一问题，可以直接沿用前文规则。\n\n"
            f"{loaded_skill_note}"
            f"{skill_context}\n\n"
            f"{skill_routing_instruction}\n\n"
            f"用户问题：{message}"
        )
    if selected_dataset_set:
        message = (
            "用户已在前端数据库按钮中选择以下本地数据库。本轮只能把这些数据库发送给 AI；"
            "未列出的 agent_knowledge 数据库视为不可见，不能读取、引用或声称知道。\n"
            f"已选择数据库 id：{', '.join(sorted(selected_dataset_set))}\n\n"
            f"用户问题：{message}"
        )
    else:
        message = (
            "用户本轮没有在前端数据库按钮中选择任何本地数据库。"
            "后端不会发送任何前端数据库内容；不得列举、猜测、引用或声称知道未选择数据库的名称、路径或内容。"
            "如需数据库内容，只能提示用户先在前端数据库按钮中选择。"
            "仍可使用周报、审计日志、运行日志等基础本地引用和其他被允许工具。\n\n"
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
    emitted_process_tools: set[str] = set()
    disabled_web_notice_prefixes = (
        "联网搜索已关闭",
        "当前联网搜索已关闭",
        "已关闭联网搜索",
        "由于联网搜索",
        "因为联网搜索",
        "本轮不会调用",
        "我不能联网",
        "当前不能联网",
    )
    disabled_web_notice_markers = (
        "联网搜索已关闭",
        "不会调用 web_search",
        "不会调用 `web_search`",
        "web_search",
        "read_webpage",
        "打开联网搜索",
        "联网搜索开关",
        "前端开关",
        "工具配置",
    )
    disabled_web_notice_buffer = ""
    checking_disabled_web_notice = not force_web_search
    table_limiter = MarkdownTableLimiter()

    def filter_disabled_web_notice(text: str) -> list[str]:
        """Drop a leading web-toggle explanation; keep normal streaming intact."""
        nonlocal disabled_web_notice_buffer, checking_disabled_web_notice
        if not checking_disabled_web_notice:
            return [text] if text else []

        disabled_web_notice_buffer += text
        leading = disabled_web_notice_buffer.lstrip()

        sentence_end_positions = [
            pos
            for pos in (
                leading.find("。"),
                leading.find("\n"),
                leading.find("！"),
                leading.find("？"),
                leading.find(". "),
            )
            if pos >= 0
        ]
        cut_at = min(sentence_end_positions) + 1 if sentence_end_positions else -1
        first_sentence = leading[:cut_at] if cut_at > 0 else leading
        matched_notice = (
            any(prefix.startswith(leading) or leading.startswith(prefix) for prefix in disabled_web_notice_prefixes)
            or any(marker in first_sentence for marker in disabled_web_notice_markers)
        )
        if matched_notice:
            if cut_at < 0:
                return []
            checking_disabled_web_notice = False
            remainder = leading[cut_at:].lstrip()
            disabled_web_notice_buffer = ""
            return [remainder] if remainder else []

        checking_disabled_web_notice = False
        buffered = disabled_web_notice_buffer
        disabled_web_notice_buffer = ""
        return [buffered] if buffered else []
    
    try:
        events = _stream_agent_events(agent, inputs)
        for chunk, metadata in events:
            if isinstance(chunk, AIMessageChunk):
                if chunk.content and isinstance(chunk.content, str):
                    for text in filter_disabled_web_notice(chunk.content):
                        limited_text = table_limiter.feed(text)
                        if limited_text:
                            event = {"type": "delta", "text": limited_text}
                            recorder.observe(event)
                            yield event
                if chunk.tool_call_chunks:
                    for tc in chunk.tool_call_chunks:
                        index = tc.get("index")
                        tc_id = tc.get("id")
                        
                        if tc_id:
                            current_key = tc_id
                            tool_calls_acc[index] = current_key
                            tool_calls_acc[current_key] = {"name": tc.get("name"), "args": "", "id": tc_id}
                            if thinking_enabled:
                                yield thinking_event(f"准备调用工具：{tc.get('name') or '工具'}。")
                            process_tool_name = tc.get("name") or "工具"
                            process_text = ""
                            if process_tool_name not in emitted_process_tools:
                                emitted_process_tools.add(process_tool_name)
                                process_text = _tool_process_text(process_tool_name)
                            event = {
                                "type": "tool_call_start",
                                "id": tc_id,
                                "name": process_tool_name,
                                "processText": process_text,
                            }
                            recorder.observe(event)
                            yield event
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
                    recorder.observe(meta_event)
                    yield meta_event
                    
                tool_name = str((tc_data or {}).get("name") or "工具")
                display_content = _display_tool_result(tool_name, content.strip(), meta_event)
                if thinking_enabled:
                    yield thinking_event(f"工具返回结果：{tool_name} 已完成，开始把结果纳入来源核验和回答组织。")
                event = {
                    "type": "tool_call_result",
                    "id": chunk.tool_call_id,
                    "name": tool_name,
                    "args": args_str,
                    "content": display_content,
                }
                recorder.observe(event)
                yield event
        if checking_disabled_web_notice and disabled_web_notice_buffer:
            leading = disabled_web_notice_buffer.lstrip()
            if not any(leading.startswith(prefix) for prefix in disabled_web_notice_prefixes):
                limited_text = table_limiter.feed(disabled_web_notice_buffer)
                if limited_text:
                    event = {"type": "delta", "text": limited_text}
                    recorder.observe(event)
                    yield event
            disabled_web_notice_buffer = ""
        tail_text = table_limiter.flush()
        if tail_text:
            event = {"type": "delta", "text": tail_text}
            recorder.observe(event)
            yield event
        summary = recorder.finish()
        yield {
            "type": "run_summary",
            "runId": summary["run_id"],
            "durationMs": summary["duration_ms"],
            "toolCount": len(summary.get("tool_calls") or []),
            "status": summary.get("status"),
        }
        yield {"type": "done"}
    except Exception as e:
        error_text = str(e)
        if "Recursion limit" in error_text or "GRAPH_RECURSION_LIMIT" in error_text:
            message_text = (
                "本轮工具调用已达到安全上限，已停止继续检索。"
                "请基于上方已返回的工具结果和已生成图表查看当前结论；"
                "如需继续深挖，请缩小问题范围后再问。"
            )
        else:
            message_text = f"Agent 调用失败: {e}"
        event = {"type": "error", "text": message_text}
        recorder.observe(event)
        yield event
        recorder.finish()
        yield {"type": "done"}
    finally:
        SELECTED_DATASET_IDS.reset(dataset_token)
        SELECTED_SKILL_IDS.reset(skill_token)
        APPROVED_ACTION_IDS.reset(approved_token)
        CHART_RUN_STATE.reset(chart_token)
        TOOL_RUN_STATE.reset(tool_token)
