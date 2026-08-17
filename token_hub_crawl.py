"""Public, isolated lead crawl for CMHK AI Token Hub.

It only reads explicitly configured public URLs and writes token_hub.sqlite3.
It does not invoke the existing CMHK full crawl, Feishu sync, or notifications.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from token_hub import DB_LOCK, _now, db_connection, init_db

ROOT = Path(__file__).resolve().parent
SOURCES = (
    {
        "name": "Cyberport Community CSV",
        "url": "https://istartup.hk/opendata/cc/cc.csv",
        "kind": "csv",
    },
)
PIONEER_PAGE_URL = "https://www.cyberport.hk/en/news/cyberport-ai-pioneers/"

CYBERPORT_AI_PIONEERS = (
    "AIFT", "Appreciator.io", "AT-Vibe Technology", "Aereve", "Alpha AI", "Bistrochat",
    "Bridge AI", "Butler", "China Year", "DAS-Security", "FundingReach", "5GnuMultiMedia",
    "Jumppoint", "iFLYTEK - Xunfei Healthcare", "Klook", "MateZLab", "Mediconcen", "Molekiu",
    "OWOWWW Creative", "Presslogic", "Pubrio", "R2C2", "SmartAge Intelligence", "Stellaris AI",
    "Threatbook", "Xonlabs", "YouToo Robot", "ZA Bank",
)


def _score(text: str) -> tuple[int, str]:
    lowered = text.lower()
    score = 0
    reasons = []
    for terms, points, reason in (
        (("ai", "人工智能", "machine learning", "llm", "chatbot", "data"), 3, "AI/数据信号"),
        (("fintech", "金融", "insurance", "保险", "health", "医疗"), 2, "受监管或高价值场景"),
        (("logistics", "物流", "trade", "贸易", "tourism", "旅游", "retail", "零售"), 2, "跨境/客服场景"),
    ):
        if any(term in lowered for term in terms):
            score += points
            reasons.append(reason)
    return min(100, 50 + score * 8), ", ".join(reasons) or "公开生态企业"


def crawl() -> dict:
    init_db()
    started = _now()
    total = 0
    details = []
    for source in SOURCES:
        try:
            request = urllib.request.Request(source["url"], headers={"User-Agent": "CMHK-TokenHub-LeadCrawler/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
            text = raw.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
            count = 0
            with DB_LOCK, db_connection() as conn:
                for row in rows:
                    company = str(row.get("company_name") or row.get("Company Name") or row.get("公司名称") or row.get("name") or "").strip()
                    if not company:
                        continue
                    industry = str(row.get("industry") or row.get("Industry") or row.get("行业") or "").strip()
                    website = str(row.get("website") or row.get("Website") or row.get("网址") or "").strip()
                    score, reason = _score(f"{company} {industry}")
                    now = _now()
                    conn.execute(
                        """INSERT INTO leads(company_name, source, industry, url, score, status, evidence, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, '新线索', ?, ?, ?)
                           ON CONFLICT(company_name, source) DO UPDATE SET industry=excluded.industry, url=excluded.url, score=excluded.score, evidence=excluded.evidence, updated_at=excluded.updated_at""",
                        (company[:180], source["name"], industry[:120], website[:500], score, reason, now, now),
                    )
                    count += 1
            total += count
            details.append({"source": source["name"], "records": count, "status": "success"})
        except Exception as exc:
            details.append({"source": source["name"], "records": 0, "status": "failed", "error": str(exc)[:240]})
    pioneer_source = "Cyberport AI Pioneers"
    page_fetched = False
    pioneer_detail = "公开页面快照；"
    try:
        page_request = urllib.request.Request(
            PIONEER_PAGE_URL,
            headers={"User-Agent": "CMHK-TokenHub-LeadCrawler/1.0"},
        )
        with urllib.request.urlopen(page_request, timeout=45) as response:
            page_text = response.read().decode("utf-8", errors="replace")
        page_lower = page_text.lower()
        discovered_pioneers = tuple(
            company for company in CYBERPORT_AI_PIONEERS if company.lower() in page_lower
        ) or CYBERPORT_AI_PIONEERS
        page_fetched = True
        pioneer_detail = "公开页面实时校验；"
    except Exception as exc:
        # Cyberport may reject non-browser requests. Keep the source explicit:
        # this is a public snapshot, not a claim that the live page was read.
        discovered_pioneers = CYBERPORT_AI_PIONEERS
        pioneer_detail = f"公开页面暂不可抓取（{str(exc)[:100]}）；使用已标注公开快照；"
    try:
        with DB_LOCK, db_connection() as conn:
            now = _now()
            for company in discovered_pioneers:
                score, reason = _score(company + " AI")
                conn.execute(
                    """INSERT INTO leads(company_name, source, industry, url, score, status, evidence, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, '新线索', ?, ?, ?)
                       ON CONFLICT(company_name, source) DO UPDATE SET score=excluded.score, evidence=excluded.evidence, updated_at=excluded.updated_at""",
                    (company, pioneer_source, "AI/科技", PIONEER_PAGE_URL, score, pioneer_detail + reason, now, now),
                )
        total += len(discovered_pioneers)
        details.append({"source": pioneer_source, "records": len(discovered_pioneers), "status": "success" if page_fetched else "partial", "page_fetched": page_fetched})
    except Exception as exc:
        details.append({"source": pioneer_source, "records": 0, "status": "failed", "error": str(exc)[:240]})
    statuses = {item["status"] for item in details}
    status = "success" if "success" in statuses and "partial" not in statuses else ("partial" if total else "failed")
    finished = _now()
    with DB_LOCK, db_connection() as conn:
        conn.execute("INSERT INTO crawl_runs(source, status, records, detail, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?)", ("token-hub-public-leads", status, total, json.dumps(details, ensure_ascii=False), started, finished))
    result = {"ok": status == "success", "status": status, "records": total, "details": details, "started_at": started, "finished_at": finished}
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    crawl()
