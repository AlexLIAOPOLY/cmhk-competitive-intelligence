#!/usr/bin/env python3
"""Check live reachability of unique source URLs used by CMHK knowledge packages."""

from __future__ import annotations

import csv
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DATE = date.today().isoformat()
OUT_ROOT = ROOT / "agent_knowledge" / "source_url_reachability_audits"
TIMEOUT_SECONDS = 8
MAX_WORKERS = 24

DATASETS = [
    {
        "id": "cmhk_macro_policy_2026-06-19",
        "csv": ROOT / "agent_knowledge" / "cmhk_macro_policy_2026-06-19" / "macro_policy_metrics.csv",
    },
    {
        "id": "quarterly_competitor_metrics_2026-06-18",
        "csv": ROOT / "agent_knowledge" / "quarterly_competitor_metrics_2026-06-18" / "quarterly_metrics.csv",
    },
    {
        "id": "cloud_vendor_metrics_2026-06-17",
        "csv": ROOT / "agent_knowledge" / "cloud_vendor_metrics_2026-06-17" / "cloud_vendor_metrics_2023_2025.csv",
    },
]

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 CMHK-source-audit/1.0",
    "Accept": "text/html,application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

RESTRICTED_STATUS = {401, 403, 405, 406, 418, 429, 503}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def collect_urls() -> dict[str, dict[str, Any]]:
    urls: dict[str, dict[str, Any]] = {}
    for dataset in DATASETS:
        dataset_id = dataset["id"]
        for row in read_rows(dataset["csv"]):
            row_urls: list[tuple[str, str]] = []
            for field in ("official_source_url", "primary_source_url"):
                url = str(row.get(field) or "").strip()
                if url.startswith(("http://", "https://")):
                    row_urls.append((field, url))
            try:
                sources = json.loads(row.get("verification_sources") or "[]")
            except Exception:
                sources = []
            for item in sources:
                if isinstance(item, dict):
                    url = str(item.get("url") or "").strip()
                    if url.startswith(("http://", "https://")):
                        row_urls.append(("verification_sources", url))
            for field, url in row_urls:
                item = urls.setdefault(
                    url,
                    {
                        "url": url,
                        "host": urlparse(url).netloc.lower(),
                        "datasets": set(),
                        "field_types": set(),
                        "row_ref_count": 0,
                    },
                )
                item["datasets"].add(dataset_id)
                item["field_types"].add(field)
                item["row_ref_count"] += 1
    return urls


def request_once(url: str, method: str) -> tuple[int | None, str, int]:
    headers = dict(REQUEST_HEADERS)
    if method == "GET":
        headers["Range"] = "bytes=0-1023"
    request = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        length = 0
        if method == "GET":
            length = len(response.read(1024))
        return response.getcode(), response.headers.get("content-type", ""), length


def classify_status(status_code: int | None, error: str) -> str:
    if status_code is not None:
        if 200 <= status_code < 400:
            return "ok"
        if status_code in RESTRICTED_STATUS:
            return "reachable_restricted"
        return "http_error"
    if "timed out" in error.lower() or "timeout" in error.lower():
        return "timeout"
    if "certificate" in error.lower() or "ssl" in error.lower():
        return "ssl_error"
    return "network_error"


def check_url(url: str, meta: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    status_code: int | None = None
    content_type = ""
    bytes_read = 0
    method_used = "HEAD"
    error = ""
    try:
        status_code, content_type, bytes_read = request_once(url, "HEAD")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        content_type = exc.headers.get("content-type", "") if exc.headers else ""
        if status_code in {403, 405, 406, 429}:
            method_used = "GET"
            try:
                status_code, content_type, bytes_read = request_once(url, "GET")
            except urllib.error.HTTPError as get_exc:
                status_code = get_exc.code
                content_type = get_exc.headers.get("content-type", "") if get_exc.headers else content_type
                error = f"GET HTTPError: {get_exc.code}"
            except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as get_exc:
                error = f"GET {type(get_exc).__name__}: {get_exc}"
        else:
            error = f"HEAD HTTPError: {exc.code}"
    except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
        method_used = "GET"
        try:
            status_code, content_type, bytes_read = request_once(url, "GET")
        except urllib.error.HTTPError as get_exc:
            status_code = get_exc.code
            content_type = get_exc.headers.get("content-type", "") if get_exc.headers else ""
            error = f"GET HTTPError: {get_exc.code}"
        except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as get_exc:
            error = f"GET {type(get_exc).__name__}: {get_exc}"
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    status = classify_status(status_code, error)
    return {
        "url": url,
        "host": meta["host"],
        "datasets": ";".join(sorted(meta["datasets"])),
        "field_types": ";".join(sorted(meta["field_types"])),
        "row_ref_count": meta["row_ref_count"],
        "status": status,
        "http_status": "" if status_code is None else status_code,
        "method_used": method_used,
        "content_type": content_type,
        "bytes_read": bytes_read,
        "elapsed_ms": elapsed_ms,
        "error": error[:500],
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "url",
        "host",
        "datasets",
        "field_types",
        "row_ref_count",
        "status",
        "http_status",
        "method_used",
        "content_type",
        "bytes_read",
        "elapsed_ms",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    status_counts = Counter(row["status"] for row in rows)
    host_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        host_counts[row["host"]][row["status"]] += 1
    lines = [
        f"# Source URL Reachability Audit ({AUDIT_DATE})",
        "",
        f"- Unique URLs checked: {len(rows)}",
        f"- OK: {status_counts.get('ok', 0)}",
        f"- Reachable/restricted: {status_counts.get('reachable_restricted', 0)}",
        f"- HTTP errors: {status_counts.get('http_error', 0)}",
        f"- Timeouts: {status_counts.get('timeout', 0)}",
        f"- SSL errors: {status_counts.get('ssl_error', 0)}",
        f"- Network errors: {status_counts.get('network_error', 0)}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Hosts With Non-OK Results", ""])
    for host, counts in sorted(host_counts.items()):
        non_ok = sum(count for status, count in counts.items() if status != "ok")
        if not non_ok:
            continue
        lines.append(f"- {host}: " + ", ".join(f"{status}={count}" for status, count in sorted(counts.items())))
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- Checks each unique URL referenced by official_source_url, primary_source_url, and verification_sources across the three main packages.",
            "- `ok` means HTTP 2xx/3xx was returned by HEAD or small-range GET.",
            "- `reachable_restricted` means the host responded with an access-control status such as 401/403/405/429; these require browser/manual review when adding or refreshing data, but still indicate the URL host is live.",
            "- This audit does not re-validate every numeric value; it verifies that preserved source links remain machine-checkable or explicitly flagged.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(rows: list[dict[str, Any]], path: Path, csv_path: Path, md_path: Path) -> None:
    counts = Counter(row["status"] for row in rows)
    hard_failures = counts.get("http_error", 0) + counts.get("timeout", 0) + counts.get("ssl_error", 0) + counts.get("network_error", 0)
    manifest = {
        "id": "source_url_reachability_audits",
        "title": "小竞AI来源URL可达性审计",
        "summary": "去重检查三类主数据包中 official_source_url、primary_source_url 和 verification_sources 的唯一 URL 当前是否可访问或返回受限状态。",
        "source_type": "live_url_audit",
        "scope": "official/public source URL reachability for preserved evidence links.",
        "updated_at": AUDIT_DATE,
        "tags": ["audit", "source-url", "reachability", "evidence"],
        "keywords": ["source_url_reachability_audits", "official_source_url", "primary_source_url", "verification_sources", "reachable_restricted"],
        "entrypoints": [md_path.name, csv_path.name],
        "quality": {
            "status": "pass" if hard_failures == 0 else "pass_with_external_warnings",
            "row_count": len(rows),
            "unique_urls_checked": len(rows),
            "ok": counts.get("ok", 0),
            "reachable_restricted": counts.get("reachable_restricted", 0),
            "hard_failures": hard_failures,
            "notes": [
                "网络审计结果会随外部网站访问策略变化；新增数据仍需逐条打开来源人工核实。",
                "reachable_restricted 表示 URL 主机响应但限制自动请求，不等同于来源失效。",
                "hard_failures 需要后续复核是否为临时网络问题、迁移链接或来源失效。",
            ],
        },
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    urls = collect_urls()
    print(f"checking {len(urls)} unique source URLs with {MAX_WORKERS} workers")
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_url, url, meta): url for url, meta in urls.items()}
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: (row["status"], row["host"], row["url"]))
    csv_path = OUT_ROOT / f"source_url_reachability_{AUDIT_DATE}.csv"
    md_path = OUT_ROOT / f"source_url_reachability_{AUDIT_DATE}.md"
    manifest_path = OUT_ROOT / "manifest.json"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path)
    write_manifest(rows, manifest_path, csv_path, md_path)
    counts = Counter(row["status"] for row in rows)
    print(f"wrote {csv_path.relative_to(ROOT)}")
    print(f"wrote {md_path.relative_to(ROOT)}")
    print(f"wrote {manifest_path.relative_to(ROOT)}")
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
