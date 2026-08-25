#!/usr/bin/env python3
"""Isolated official-source recrawl for strategic overview domains 01/03/04.

The crawler never invokes the shared scheduler.  It re-fetches the official
documents already attached to the 2016-2025 metric rows, records retrieval
evidence, and produces a coverage audit for the absolute-value dashboard.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "agent_knowledge/requested_overview_010304_2016_2025"
YEARS = tuple(range(2016, 2026))
SAFE = {
    "official_match",
    "official_only",
    "official_derived_from_verified_rows",
    "multi_source_or_multi_snapshot_verified",
    "official_three_distinct_sources_verified",
}
FINANCIAL = ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18/quarterly_metrics.json"
LOCAL = ROOT / "agent_knowledge/local_hk_operator_operating_metrics_2016_2025/annual_metrics.json"
LOCAL_SOURCES = ROOT / "agent_knowledge/local_hk_operator_operating_metrics_2016_2025/sources.json"
GLOBAL = ROOT / "agent_knowledge/global_top5_operators_2016_2025/annual_metrics.json"
GLOBAL_SOURCES = ROOT / "agent_knowledge/global_top5_operators_2016_2025/sources.json"
CLOUD = ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17/cloud_vendor_metrics_2016_2025.json"
SOURCE_DISCOVERY = ROOT / "agent_knowledge/executive_intelligence_refresh/source_discovery_latest.json"


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_urls(row: dict[str, Any], registry: dict[str, str] | None = None) -> list[str]:
    raw = row.get("verification_sources") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    urls: list[str] = []
    for source in raw if isinstance(raw, list) else []:
        url = str(source.get("url") or "") if isinstance(source, dict) else str((registry or {}).get(str(source), ""))
        if url.startswith(("https://", "http://")):
            urls.append(url)
    for key in ("primary_source_url", "official_source_url"):
        url = str(row.get(key) or "")
        if url.startswith(("https://", "http://")):
            urls.append(url)
    return list(dict.fromkeys(urls))


def registry(path: Path) -> dict[str, str]:
    payload = read(path)
    return {
        str(item.get("source_id") or item.get("id") or ""): str(item.get("url") or "")
        for item in payload.get("sources", [])
    }


def year_from_period(value: Any) -> int | None:
    match = re.search(r"20\d{2}", str(value or ""))
    return int(match.group()) if match else None


def collect() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    url_domains: dict[str, set[str]] = {}
    coverage: list[dict[str, Any]] = []

    def add(urls: list[str], domain: str) -> None:
        for url in urls:
            if url.startswith(("https://", "http://")):
                url_domains.setdefault(url, set()).add(domain)

    financial_rows = read(FINANCIAL).get("rows", [])
    financial_subjects = {
        "HKT / csl / 1O1O", "SmarTone", "3HK / Hutchison",
        "中国移动", "中国电信", "中国联通", "中国广电",
    }
    for row in financial_rows:
        year = year_from_period(row.get("period"))
        if (
            row.get("subject") in financial_subjects
            and row.get("metric_key") in {"revenue", "ebitda", "net_income"}
            and year in YEARS
            and row.get("verification_status") in SAFE
            and row.get("value") not in (None, "")
        ):
            domain = "local" if row.get("subject") in {"HKT / csl / 1O1O", "SmarTone", "3HK / Hutchison"} else "mainland"
            add(source_urls(row), domain)

    local_rows = read(LOCAL).get("rows", [])
    local_registry = registry(LOCAL_SOURCES)
    for operator in ("CMHK", "HKT", "SmarTone", "3HK"):
        for year in YEARS:
            row = next((item for item in local_rows if item.get("operator") == operator and item.get("metric_key") == "mobile_postpaid_customers" and int(item.get("year") or 0) == year), {})
            row_urls = source_urls(row, local_registry)
            add(row_urls, "local")
            coverage.append({
                "domain": "01", "entity": operator, "year": year, "metric": "postpaid_subscribers",
                "value": row.get("value"), "unit": row.get("unit") or "million_subscribers",
                "status": row.get("verification_status") or "source_gap_confirmed",
                "source_count": len(row_urls), "source_urls": row_urls,
            })

    global_rows = read(GLOBAL).get("rows", [])
    global_registry = registry(GLOBAL_SOURCES)
    mainland_operators = {"中国移动", "中国电信", "中国联通", "中国广电"}
    international_operators = {"Bharti Airtel", "Reliance Jio", "Verizon", "Deutsche Telekom", "AT&T", "NTT Group"}
    for operator in sorted(mainland_operators | international_operators):
        for year in YEARS:
            postpaid = next((item for item in global_rows if item.get("operator") == operator and item.get("metric_key") == "mobile_postpaid_customers" and int(item.get("year") or 0) == year), None)
            evidence_rows = [item for item in global_rows if item.get("operator") == operator and int(item.get("year") or 0) == year]
            row_urls = list(dict.fromkeys(url for item in evidence_rows for url in source_urls(item, global_registry)))[:6]
            domain = "mainland" if operator in mainland_operators else "international"
            add(row_urls, domain)
            coverage.append({
                "domain": "03" if domain == "mainland" else "02", "entity": operator, "year": year, "metric": "postpaid_subscribers",
                "value": (postpaid or {}).get("value"), "unit": (postpaid or {}).get("unit") or "million_subscribers",
                "status": (postpaid or {}).get("verification_status") or "official_not_separately_disclosed",
                "source_count": len(row_urls), "source_urls": row_urls,
                "note": "移动用户总数、5G用户或mobile billing subscribers不替代后付费用户数。",
            })

    cloud_rows = read(CLOUD).get("rows", [])
    cloud_keys = {
        "cloud_revenue", "proxy_segment_revenue", "cloud_operating_profit", "operating_income",
        "adjusted_ebita", "proxy_segment_gross_profit", "cloud_and_license_margin", "group_capex",
    }
    for row in cloud_rows:
        if str(row.get("fiscal_year") or "") in {str(year) for year in YEARS} and row.get("metric_key") in cloud_keys:
            add(source_urls(row), "cloud")

    try:
        discovery = read(SOURCE_DISCOVERY)
    except (OSError, json.JSONDecodeError):
        discovery = {}
    for signal in discovery.get("signals", []) if isinstance(discovery, dict) else []:
        if not isinstance(signal, dict) or signal.get("domain") not in {"local", "international", "mainland", "cloud"}:
            continue
        add(
            [str(url) for url in signal.get("official_followup_urls", []) if str(url).startswith(("https://", "http://"))],
            str(signal["domain"]),
        )

    return [
        {"url": url, "domains": sorted(domains)}
        for url, domains in url_domains.items()
    ], coverage


class VisibleTextParser(HTMLParser):
    """Extract stable visible text while ignoring script/style/session attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            clean = " ".join(data.split())
            if clean:
                self.parts.append(clean)


def content_fingerprint(body: bytes, content_type: str) -> tuple[str, str]:
    if body.startswith(b"%PDF") or "application/pdf" in content_type.lower():
        return hashlib.sha256(body).hexdigest(), "raw_pdf_sample"
    parser = VisibleTextParser()
    parser.feed(body.decode("utf-8", "ignore"))
    visible_text = "\n".join(parser.parts)
    return hashlib.sha256(visible_text.encode("utf-8")).hexdigest(), "visible_text"


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={
        "User-Agent": "CMHK-Competitive-Intelligence/1.0 official-source-audit",
        "Range": "bytes=0-131071",
        "Accept": "text/html,application/pdf,*/*;q=0.8",
    })
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=18, context=context) as response:
            body = response.read(131072)
            content_type = str(response.headers.get("Content-Type") or "")
            fingerprint, fingerprint_kind = content_fingerprint(body, content_type)
            return {
                "url": url, "ok": True, "status": int(response.status),
                "content_type": content_type,
                "bytes_sampled": len(body), "sha256_sample": hashlib.sha256(body).hexdigest(),
                "content_fingerprint": fingerprint, "fingerprint_kind": fingerprint_kind,
                "retrieved_at": datetime.now().astimezone().isoformat(),
            }
    except urllib.error.HTTPError as exc:
        return {"url": url, "ok": False, "status": int(exc.code), "error": str(exc.reason)}
    except Exception as exc:  # network audit must retain per-source failures
        return {"url": url, "ok": False, "status": None, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="0 means all collected official URLs")
    args = parser.parse_args()
    targets, coverage = collect()
    if args.limit > 0:
        targets = targets[: args.limit]
    previous_path = OUT_DIR / "official_source_recrawl.json"
    try:
        previous = read(previous_path)
    except (OSError, json.JSONDecodeError):
        previous = {}
    previous_items = {
        str(item.get("url") or ""): item
        for item in previous.get("source_crawl", [])
        if item.get("ok") and item.get("url")
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        crawled = list(pool.map(fetch, [item["url"] for item in targets]))
    domains_by_url = {item["url"]: item["domains"] for item in targets}
    for item in crawled:
        item["domains"] = domains_by_url.get(item["url"], [])
        previous_item = previous_items.get(item["url"]) or {}
        old_fingerprint = str(previous_item.get("content_fingerprint") or "")
        item["content_changed"] = bool(
            item.get("ok") and old_fingerprint and old_fingerprint != item.get("content_fingerprint")
        )
        item["first_observation"] = bool(item.get("ok") and not previous_item)
        item["fingerprint_baseline_upgraded"] = bool(item.get("ok") and previous_item and not old_fingerprint)
    domain_summary: dict[str, dict[str, int]] = {}
    for domain in ("local", "international", "mainland", "cloud"):
        items = [item for item in crawled if domain in item.get("domains", [])]
        domain_summary[domain] = {
            "official_urls": len(items),
            "retrieved": sum(1 for item in items if item.get("ok")),
            "failed": sum(1 for item in items if not item.get("ok")),
            "content_changed": sum(1 for item in items if item.get("content_changed")),
            "first_observation": sum(1 for item in items if item.get("first_observation")),
            "fingerprint_baseline_upgraded": sum(1 for item in items if item.get("fingerprint_baseline_upgraded")),
        }
    payload = {
        "dataset_id": "requested_overview_010304_official_recrawl_2016_2025",
        "generated_at": datetime.now().astimezone().isoformat(),
        "period": {"start_year": 2016, "end_year": 2025},
        "policy": "official documents only; absolute values only; missing postpaid disclosures remain gaps",
        "summary": {
            "official_urls": len(targets), "retrieved": sum(1 for item in crawled if item["ok"]),
            "failed": sum(1 for item in crawled if not item["ok"]),
            "postpaid_rows": len(coverage), "postpaid_values": sum(1 for item in coverage if item.get("value") not in (None, "")),
            "content_changed": sum(1 for item in crawled if item.get("content_changed")),
            "first_observation": sum(1 for item in crawled if item.get("first_observation")),
            "fingerprint_baseline_upgraded": sum(1 for item in crawled if item.get("fingerprint_baseline_upgraded")),
            "domains": domain_summary,
        },
        "postpaid_coverage": coverage,
        "source_crawl": crawled,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "official_source_recrawl.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0 if payload["summary"]["retrieved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
