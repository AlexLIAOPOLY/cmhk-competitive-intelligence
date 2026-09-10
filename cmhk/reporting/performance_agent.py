"""On-demand performance report research; reads formal data and writes only its run.

This module has no scheduler, database writer, subscription sender or daily-crawl
hook. A report owns its evidence snapshot, searches and editorial audit.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from data_curation.research_freshness import load_baseline, period_key

FIELDS = {"dividend": "派息", "capex": "资本开支", "strategy": "战略升级",
          "broker": "券商观点", "market": "市场反应", "revenue": "收入", "profit": "EBITDA / 利润"}
METRICS = {"dividend": ["派息", "股息"], "capex": ["资本开支"],
           "strategy": ["收入", "净利润", "后付费用户数", "移动客户数"],
           "broker": ["券商观点"], "market": ["市场反应"],
           "revenue": ["收入"], "profit": ["EBITDA", "净利润"]}
ALIASES = {"HKT / csl / 1O1O": "HKT", "3HK / Hutchison": "3HK"}
SEARCH_NAMES = {"HKT / csl / 1O1O": "香港電訊 HKT", "3HK / Hutchison": "和記電訊香港 3HK",
                "SmarTone": "數碼通 SmarTone", "HKBN": "香港寬頻 HKBN",
                "HGC": "環球全域電訊 HGC", "i-CABLE": "有線寬頻 i-CABLE"}
TERMS = {"dividend": "interim final dividend per share 股息 派息",
         "capex": "interim results capital expenditure 资本开支",
         "strategy": "interim results business outlook 战略 业绩",
         "broker": "analyst rating target price 大行 评级 目标价",
         "market": "stock price market reaction 股价 市场反应",
         "revenue": "interim results revenue 收入",
         "profit": "interim results EBITDA net profit 净利润"}
UNCONFIRMED = "截至本次检索，未取得可核实的该项最新信息。"


def report_search(query: str, limit: int = 3) -> dict:
    from data_curation.workflow import _public_web_search
    rows, provider = _public_web_search(query, limit=limit, timeout=12)
    return {"results": rows, "provider": provider, "error": "" if rows else "本次搜索未返回可用结果"}


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def latest_rows(metrics: dict, field: str) -> list[dict]:
    selected = []
    for metric in METRICS[field]:
        rows = [row for row in metrics.get(metric, []) if row.get("value") not in (None, "")]
        if rows:
            newest = max((period_key(row.get("period")) or (0, 0, "")) for row in rows)
            selected.extend({**row, "metric": metric, "origin": "database"} for row in rows
                            if (period_key(row.get("period")) or (0, 0, "")) == newest)
    return selected


def fresh_rows(rows: list[dict], field: str, today) -> bool:
    if not rows:
        return False
    # Opinions and prices need a dated observation, not an accounting year.
    if field in {"broker", "market"}:
        for row in rows:
            try:
                observed = datetime.fromisoformat(str(row.get("publication_date") or row.get("period"))).date()
                if 0 <= (today - observed).days <= 14:
                    return True
            except ValueError:
                pass
        return False
    ranks = [period_key(row.get("period")) for row in rows]
    # Keep fiscal labels intact. A fiscal year may end before December.
    threshold = (today.year, 6) if today.month >= 9 else (today.year - 1, 12) if today.month >= 4 else (today.year - 1, 6)
    return all(rank and rank[:2] >= threshold for rank in ranks)


def read_public_page(url: str) -> dict:
    import httpx
    from bs4 import BeautifulSoup
    from io import BytesIO
    response = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 CMHK-PerformanceReport/1.0"})
    response.raise_for_status()
    if "pdf" in response.headers.get("content-type", "").lower() or url.split("?")[0].endswith(".pdf"):
        from pypdf import PdfReader
        text = " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages)
        return {"opened": True, "text": text}
    soup = BeautifulSoup(response.text, "html.parser")
    date_tag = soup.select_one('meta[property="article:published_time"], meta[name="date"], time[datetime]')
    published = (date_tag.get("content") or date_tag.get("datetime")) if date_tag else ""
    for tag in soup.select("script, style, nav, header, footer"):
        tag.decompose()
    return {"opened": True, "text": soup.get_text(" ", strip=True), "publication_date": published}


def company_matches(company: str, text: str) -> bool:
    from opencc import OpenCC
    normal = OpenCC("t2s").convert(text).casefold()
    terms = {"HKT / csl / 1O1O": ["香港电讯", "hkt trust", "hkt limited"],
             "HKT": ["香港电讯", "hkt trust", "hkt limited"],
             "3HK / Hutchison": ["和记电讯", "3hk", "hutchison telecommunications"],
             "HGC": ["环球全域电讯", "hgc", "hutchison global"],
             "HKBN": ["香港宽频", "hkbn"], "SmarTone": ["数码通", "smartone"],
             "i-CABLE": ["有线宽频", "i-cable", "i cable"]}.get(company, [company.casefold()])
    return any(term in normal for term in terms)


def publication_date(result: dict, page: dict):
    text = " ".join(str(v or "") for v in [page.get("publication_date"), page.get("published_at"),
                         result.get("published_date"), result.get("title"), result.get("snippet"),
                         result.get("url"), str(page.get("text", ""))[:1200]])
    for match in re.finditer(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})", text):
        try:
            return datetime(*map(int, match.groups())).date()
        except ValueError:
            continue
    for pattern in (r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})", r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d{2})"):
        for match in re.finditer(pattern, text):
            value = match.group(0)
            for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    pass
    return None


def research_missing_fields(packs: list[dict], *, today, search_client, page_reader, progress) -> list[dict]:
    requests = []
    for pack in packs:
        financial = [f for f in pack["missing"] if f not in {"broker", "market"}]
        groups = ([financial] if financial else []) + [[f] for f in ["broker", "market"] if f in pack["missing"]]
        for fields in groups:
            recent = fields[0] in {"broker", "market"}
            start = today - timedelta(days=30 if recent else 210)
            terms = TERMS[fields[0]] if len(fields) == 1 else "interim results financial report dividend capex 中期业绩 股息 资本开支"
            subject = SEARCH_NAMES.get(pack["company"], pack["company"]).split()[0]
            requests.append({"id": f"{pack['company']}:{','.join(fields)}", "company": pack["company"], "fields": fields,
                "query": f'"{subject}" {today.year} {terms} after:{start.isoformat()} before:{(today + timedelta(days=1)).isoformat()}'})
    progress(f"[业绩摘要 Agent] 缺项按公司合并为 {len(requests)} 次搜索，近期观点单独查询。")
    collected = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(search_client, request["query"], 3): request for request in requests}
        for future in as_completed(futures):
            request = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"results": [], "error": str(exc)[:180]}
            collected[request["id"]] = {**request, **result}
            progress(f"[业绩摘要 Agent] 搜索 {len(collected)}/{len(requests)}：{request['company']} / {'、'.join(FIELDS[f] for f in request['fields'])}")
    rows = [{**collected[request["id"]], "field": field} for request in requests for field in request["fields"]]
    for row in rows:
        candidates = row.get("results", [])
        row["discardedSearchResults"] = [r for r in candidates if not company_matches(row["company"], str(r.get("title", "")) + " " + str(r.get("snippet", "")))]
        row["results"] = [r for r in candidates if r not in row["discardedSearchResults"]]
    urls = list(dict.fromkeys(str(r["url"]) for row in rows for r in row.get("results", [])))
    progress(f"[业绩摘要 Agent] 已筛除无关公司，读取 {len(urls)} 篇原文并检查日期。")
    def read(url):
        try:
            page = page_reader(url)
            return url, {**page, "text": str(page.get("text", ""))[:24000]}
        except Exception as exc:
            return url, {"opened": False, "error": str(exc)[:180]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        pages = dict(pool.map(read, urls))
    for row in rows:
        accepted, rejected = [], []
        for result in row.get("results", []):
            page = pages.get(result["url"], {})
            date = publication_date(result, page)
            reason = ""
            if not company_matches(row["company"], str(result.get("title", "")) + " " + str(page.get("text", ""))):
                reason = "来源未对应目标公司"
            elif not page.get("opened") or not page.get("text"):
                reason = "原文未能读取"
            elif not date:
                reason = "未确认来源发布日期"
            elif date > today:
                reason = "发布日期晚于报告截止日"
            elif (today - date).days > (30 if row["field"] in {"broker", "market"} else 210):
                reason = "来源已超出本次检索时效范围"
            entry = {**result, "publishedAt": date.isoformat() if date else "", "checkedAt": today.isoformat(),
                     "text": page.get("text", "")[:10000], "field": row["field"]}
            if reason:
                rejected.append({**entry, "reason": reason})
            else:
                accepted.append(entry)
        row["results"], row["rejected"] = accepted, rejected
    progress(f"[业绩摘要 Agent] 原文核验通过 {sum(bool(r['results']) for r in rows)}/{len(rows)} 个待补字段。")
    return rows


def field_text(rows: list[dict]) -> str:
    return "；".join(dict.fromkeys(f"{r.get('period', '')} {r['metric']} {r['value']} {r.get('unit', '')} {r.get('scope', '')}".strip() for r in rows))


def build_model(root: Path, companies: list[str], *, ai_client, validator, progress=print,
                search_client=report_search, page_reader=read_public_page, baseline_loader=load_baseline,
                now=None, run_dir: Path | None = None) -> dict:
    clock = now or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    run_dir = run_dir or root / "var/performance_reports" / (clock.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    progress("[业绩摘要 Agent] 读取正式数据库快照；本次补查和审计仅归属于本份摘要。")
    baseline = baseline_loader(root)
    save_json(run_dir / "database.json", baseline)
    packs = []
    for company in companies:
        metrics = baseline["companies"].get(ALIASES.get(company, company), {})
        rows = {field: latest_rows(metrics, field) for field in FIELDS}
        packs.append({"company": company, "asOf": clock.date().isoformat(), "evidence": {f: field_text(r) for f, r in rows.items()},
                      "database": rows, "missing": [f for f, r in rows.items() if not fresh_rows(r, f, clock.date())]})
    searches = research_missing_fields(packs, today=clock.date(), search_client=search_client,
                                      page_reader=page_reader, progress=progress)
    save_json(run_dir / "searches.json", {"searches": searches})
    for pack in packs:
        pack["web_research"] = {"results": [r for row in searches if row["company"] == pack["company"] for r in row["results"]]}
        # Undated/stale opinions never become the fallback for a current opinion.
        for field in {"broker", "market"}.intersection(pack["missing"]):
            pack["evidence"][field] = ""
    save_json(run_dir / "inputs.json", {"companies": packs})
    returned, errors = {}, []
    # One report Agent, bounded company batches, independent of six daily Agents.
    for start in range(0, len(packs), 2):
        batch = packs[start:start + 2]
        progress(f"[业绩摘要 Agent] 整理 {start + 1}–{min(start + 2, len(packs))}/{len(packs)} 家公司并核对来源。")
        try:
            response, _model = ai_client(batch)
            returned.update({item["company"]: item for item in response.get("companies", [])})
        except Exception as exc:
            errors.append({"stage": "report_agent", "reason": str(exc)[:200], "companies": [p["company"] for p in batch]})
    sections, table, audit = [], [["主体", "报告期间", "收入", "EBITDA / 利润", "资本开支", "派息"]], []
    for pack in packs:
        company = pack["company"]
        result = returned.get(company, {})
        fields, states = {}, {}
        for field in FIELDS:
            candidate = (result.get("fields") or {}).get(field, "")
            supplied = (result.get("sources") or {}).get(field, [])
            sources = supplied if isinstance(supplied, list) else []
            matched = [r for r in pack["web_research"]["results"] if r["field"] == field and r["url"] in sources]
            evidence = {"database": pack["evidence"][field], "pages": matched}
            valid, text, reason = validator(field, candidate, evidence)
            # New facts require a cited page for that exact company/field.
            if field in pack["missing"] and not matched:
                valid, reason = False, "缺项补查未获得可追溯的近期原文"
            if field in {"revenue", "profit", "capex", "dividend"} and field not in pack["missing"]:
                # Database amounts, signs, currencies and periods are locked.
                valid, text, reason = True, pack["evidence"][field], "采用数据库原值"
            fields[field] = text if valid else pack["evidence"][field] or UNCONFIRMED
            states[field] = {"accepted": valid, "reason": reason, "sources": [r["url"] for r in matched],
                             "databaseRows": pack["database"][field], "needsResearch": field in pack["missing"]}
        periods = list(dict.fromkeys(r["period"] for f in ["revenue", "profit", "capex"] for r in pack["database"][f]))
        # Keep the actual period on each numeric field; avoid declaring all fields current.
        table.append([company, "；".join(periods) or "见各项披露", *[fields[f] for f in ["revenue", "profit", "capex", "dividend"]]])
        sections.append({"company": company, "title": f"{company}关键摘要",
                         "items": [f"{label}：{fields[f]}" for f, label in list(FIELDS.items())[:5]]})
        audit.append({"company": company, "fields": states})
    unresolved = [{"company": c["company"], "field": f, "reason": state["reason"]}
                  for c in audit for f, state in c["fields"].items() if state["needsResearch"] and not state["accepted"]]
    proof = {"agent": "performance-report-agent", "trigger": "report_generation_only", "runDirectory": str(run_dir),
             "generatedAt": clock.isoformat(), "databaseSources": baseline["sources"], "searchCount": len({r["query"] for r in searches}),
             "companies": audit, "unresolved": unresolved, "errors": errors,
             "databaseSnapshotSha256": hashlib.sha256((run_dir / "database.json").read_bytes()).hexdigest()}
    save_json(run_dir / "audit.json", proof)
    progress(f"[业绩摘要 Agent] 核验完成；{len(unresolved)} 项未取得可确认的新信息，按真实状态保留。")
    model = {"title": "内地运营商及香港主要竞对关键业绩摘要", "subtitle": "战略部（智库）对标分析简报",
             "intro": f"本摘要截至{clock.year}年{clock.month}月{clock.day}日，汇总正式数据库的最近已保存业绩，并补查缺项及近期券商观点。各项保留原报告期间、币种与主体口径；未取得可核实信息的项目明确标注。",
             "table_caption": "表 内地运营商及香港主要竞对关键业绩", "table": table, "sections": sections,
             "generationMode": "limited" if unresolved or errors else "normal", "generationLimitations": errors,
             "researchAudit": proof}
    save_json(run_dir / "model.json", model)
    return model
