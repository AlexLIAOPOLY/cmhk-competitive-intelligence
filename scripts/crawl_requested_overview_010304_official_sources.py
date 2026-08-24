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


def collect() -> tuple[list[str], list[dict[str, Any]]]:
    urls: list[str] = []
    coverage: list[dict[str, Any]] = []
    financial_rows = read(FINANCIAL).get("rows", [])
    financial_subjects = (
        "HKT / csl / 1O1O", "SmarTone", "3HK / Hutchison",
        "中国移动", "中国电信", "中国联通", "中国广电",
    )
    for row in financial_rows:
        year = year_from_period(row.get("period"))
        if (
            row.get("subject") in financial_subjects
            and row.get("metric_key") in {"revenue", "ebitda", "net_income"}
            and year in YEARS
            and row.get("verification_status") in SAFE
            and row.get("value") not in (None, "")
        ):
            urls.extend(source_urls(row))

    local_rows = read(LOCAL).get("rows", [])
    local_registry = registry(LOCAL_SOURCES)
    for operator in ("CMHK", "HKT", "SmarTone", "3HK"):
        for year in YEARS:
            row = next((item for item in local_rows if item.get("operator") == operator and item.get("metric_key") == "mobile_postpaid_customers" and int(item.get("year") or 0) == year), {})
            row_urls = source_urls(row, local_registry)
            urls.extend(row_urls)
            coverage.append({
                "domain": "01", "entity": operator, "year": year, "metric": "postpaid_subscribers",
                "value": row.get("value"), "unit": row.get("unit") or "million_subscribers",
                "status": row.get("verification_status") or "source_gap_confirmed",
                "source_count": len(row_urls), "source_urls": row_urls,
            })

    global_rows = read(GLOBAL).get("rows", [])
    global_registry = registry(GLOBAL_SOURCES)
    for operator in ("中国移动", "中国电信", "中国联通", "中国广电"):
        for year in YEARS:
            postpaid = next((item for item in global_rows if item.get("operator") == operator and item.get("metric_key") == "mobile_postpaid_customers" and int(item.get("year") or 0) == year), None)
            evidence_rows = [item for item in global_rows if item.get("operator") == operator and int(item.get("year") or 0) == year]
            row_urls = list(dict.fromkeys(url for item in evidence_rows for url in source_urls(item, global_registry)))[:6]
            urls.extend(row_urls)
            coverage.append({
                "domain": "03", "entity": operator, "year": year, "metric": "postpaid_subscribers",
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
            urls.extend(source_urls(row))

    return list(dict.fromkeys(urls)), coverage


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
            return {
                "url": url, "ok": True, "status": int(response.status),
                "content_type": str(response.headers.get("Content-Type") or ""),
                "bytes_sampled": len(body), "sha256_sample": hashlib.sha256(body).hexdigest(),
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
    urls, coverage = collect()
    if args.limit > 0:
        urls = urls[: args.limit]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        crawled = list(pool.map(fetch, urls))
    payload = {
        "dataset_id": "requested_overview_010304_official_recrawl_2016_2025",
        "generated_at": datetime.now().astimezone().isoformat(),
        "period": {"start_year": 2016, "end_year": 2025},
        "policy": "official documents only; absolute values only; missing postpaid disclosures remain gaps",
        "summary": {
            "official_urls": len(urls), "retrieved": sum(1 for item in crawled if item["ok"]),
            "failed": sum(1 for item in crawled if not item["ok"]),
            "postpaid_rows": len(coverage), "postpaid_values": sum(1 for item in coverage if item.get("value") not in (None, "")),
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
