from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request

from bs4 import BeautifulSoup

from network_utils import urlopen_with_local_proxy_fallback


SearchResult = dict[str, object]
SearchClient = Callable[[str, int], SearchResult]


def _clean_text(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:limit].strip()


def _unwrap_redirect(url: object) -> str:
    value = _clean_text(url, 800)
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    for key in ("uddg", "url", "u"):
        if query.get(key):
            return unquote(query[key][0])
    if "search.yahoo.com" in parsed.netloc and "/RU=" in parsed.path:
        return unquote(parsed.path.split("/RU=", 1)[1].split("/RK=", 1)[0])
    return value


def _normalize_results(rows: object, limit: int) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict):
            continue
        title = _clean_text(raw.get("title") or raw.get("heading") or raw.get("name"), 180)
        url = _unwrap_redirect(raw.get("url") or raw.get("href") or raw.get("link"))
        snippet = _clean_text(
            raw.get("snippet") or raw.get("body") or raw.get("content") or raw.get("description"),
            600,
        )
        if not title or not url.startswith(("http://", "https://")) or url in seen_urls:
            continue
        seen_urls.add(url)
        normalized.append({"title": title, "url": url, "snippet": snippet})
        if len(normalized) >= limit:
            break
    return normalized


def _search_searxng(query: str, limit: int) -> list[dict[str, str]]:
    base_url = (
        os.environ.get("SEARXNG_URL") or os.environ.get("CMHK_SEARXNG_URL") or ""
    ).strip().rstrip("/")
    if not base_url:
        return []
    request = Request(
        f"{base_url}/search?"
        + urlencode({"q": query, "format": "json", "language": "all", "categories": "general,news"}),
        headers={"User-Agent": "CMHK-Report-Web-Research/1.0"},
    )
    with urlopen_with_local_proxy_fallback(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    return _normalize_results(payload.get("results") if isinstance(payload, dict) else [], limit)


def _search_ddgs(query: str, limit: int) -> list[dict[str, str]]:
    from ddgs import DDGS  # type: ignore

    with DDGS(timeout=12) as ddgs:
        return _normalize_results(list(ddgs.text(query, max_results=limit)), limit)


def _search_html(query: str, limit: int, provider: str) -> list[dict[str, str]]:
    if provider == "yahoo_html":
        url = "https://search.yahoo.com/search?" + urlencode({"p": query})
        block_selector = "div.dd.algo"
        link_selector = "h3 a[href], a[href]"
        snippet_selector = ".compText, p"
    else:
        url = "https://search.brave.com/search?" + urlencode({"q": query, "source": "web"})
        block_selector = ".snippet"
        link_selector = 'a[href^="http"]'
        snippet_selector = ".snippet-description, .description, .snippet-content"
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) CMHK-Report-Web-Research/1.0",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urlopen_with_local_proxy_fallback(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for block in soup.select(block_selector):
        link = block.select_one(link_selector)
        if not link:
            continue
        snippet = block.select_one(snippet_selector)
        rows.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": link.get("href") or "",
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            }
        )
    return _normalize_results(rows, limit)


def public_web_search(query: str, limit: int = 3) -> SearchResult:
    clean_query = _clean_text(query, 260)
    bounded_limit = max(1, min(int(limit or 3), 5))
    failures: list[str] = []
    providers = (
        ("searxng", _search_searxng),
        ("ddgs", _search_ddgs),
        ("yahoo_html", lambda value, count: _search_html(value, count, "yahoo_html")),
        ("brave_html", lambda value, count: _search_html(value, count, "brave_html")),
    )
    for provider, searcher in providers:
        try:
            results = searcher(clean_query, bounded_limit)
        except Exception as exc:
            failures.append(f"{provider}:{type(exc).__name__}:{_clean_text(exc, 120)}")
            continue
        if results:
            return {
                "query": clean_query,
                "provider": provider,
                "results": results,
                "error": "",
            }
    return {
        "query": clean_query,
        "provider": "",
        "results": [],
        "error": "；".join(failures[-4:]) or "所有搜索源均未返回结果",
    }


def run_web_research(
    requests: list[dict[str, str]],
    *,
    search_client: SearchClient = public_web_search,
    limit: int = 3,
    workers: int = 4,
) -> list[dict[str, object]]:
    if not requests:
        return []
    output: list[dict[str, object] | None] = [None] * len(requests)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(requests)))) as executor:
        futures = {
            executor.submit(search_client, request["query"], limit): index
            for index, request in enumerate(requests)
        }
        for future in as_completed(futures):
            index = futures[future]
            request = requests[index]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "query": request["query"],
                    "provider": "",
                    "results": [],
                    "error": f"{type(exc).__name__}: {_clean_text(exc, 180)}",
                }
            output[index] = {**request, **result}
    return [entry for entry in output if isinstance(entry, dict)]
