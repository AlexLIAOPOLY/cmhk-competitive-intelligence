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
from urllib.parse import urlparse, urljoin
from functools import lru_cache
from zoneinfo import ZoneInfo

from data_curation.research_freshness import load_baseline, period_key

FIELDS = {"dividend": "派息", "capex": "资本开支", "strategy": "战略升级",
          "broker": "券商观点", "market": "市场反应", "revenue": "收入", "profit": "EBITDA / 利润"}
METRICS = {"dividend": ["派息", "股息"], "capex": ["资本开支"],
           "strategy": ["战略升级"],
           "broker": ["券商观点"], "market": ["市场反应"],
           "revenue": ["收入"], "profit": ["EBITDA", "净利润"]}
ALIASES = {"HKT / csl / 1O1O": "HKT", "3HK / Hutchison": "3HK"}
SEARCH_NAMES = {"HKT / csl / 1O1O": "香港電訊 HKT", "3HK / Hutchison": "和記電訊香港 3HK",
                "SmarTone": "數碼通 SmarTone", "HKBN": "香港寬頻 HKBN",
                "HGC": "環球全域電訊 HGC", "i-CABLE": "有線寬頻 i-CABLE"}
TERMS = {"dividend": "interim final dividend per share 股息 派息",
         "capex": "interim results capital expenditure 资本开支",
         "strategy": "interim results business outlook 战略 业绩",
         "broker": "业绩 评级 分析 评论",
         "market": "stock price market reaction 股价 市场反应",
         "revenue": "interim results revenue 收入",
         "profit": "interim results EBITDA net profit 净利润"}
UNCONFIRMED = "-"
TICKERS = {"中国移动": "0941", "中国电信": "0728", "中国联通": "0762", "中国铁塔": "0788",
           "HKT / csl / 1O1O": "6823", "HKT": "6823", "3HK / Hutchison": "0215",
           "SmarTone": "0315", "HKBN": "1310", "i-CABLE": "1097"}
FIELD_PATTERNS = {
    "dividend": r"dividend|distribution|股息|派息|分红|分紅|分派",
    "capex": r"capex|capital expend|capital invest|资本开支|資本開支|资本支出|資本支出",
    "strategy": r"strategy|strategic|outlook|artificial intelligence|data centre|business review|computing|digital|intelligent|cloud|transformation|战略|戰略|人工智能|算力|展望|转型|轉型|数智|数字",
    "broker": r"analyst|rating|price target|forecast|大行|券商|评级|評級|目标价|目標價|观点|觀點|分析",
    "market": r"price|stock|share|market|股价|股價|市场|市場|成交|收市",
    "revenue": r"revenue|turnover|收入|收益",
    "profit": r"EBITDA|profit|earnings|净利|淨利|溢利|亏损|虧損",
}


def market_source_urls(company: str, field: str) -> list[str]:
    ticker = TICKERS.get(company)
    if not ticker or field not in {"broker", "market"}:
        return []
    urls = [f"https://stockanalysis.com/quote/hkg/{ticker}/" + ("forecast/" if field == "broker" else "")]
    if field == "broker":
        urls.append(f"https://www.etnet.com.hk/www/tc/stocks/realtime/quote_profit.php?code={ticker.zfill(5)}")
    return urls


def field_excerpt(text: str, field: str, limit: int = 4200) -> str:
    """Read relevant passages throughout a filing, including late dividend notes."""
    intervals = [(0, min(500, len(text)))]
    for match in re.finditer(FIELD_PATTERNS[field], text, re.I):
        start, end = max(0, match.start() - 160), min(len(text), match.end() + 800)
        if start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
        else:
            intervals.append((start, end))
        if sum(b - a for a, b in intervals) >= limit:
            break
    return "\n…\n".join(text[a:b] for a, b in intervals)[:limit]


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
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages)
        return {"opened": True, "text": text, "document_type": "pdf"}
    soup = BeautifulSoup(response.text, "html.parser")
    date_tag = soup.select_one('meta[property="article:published_time"], meta[name="date"], time[datetime]')
    published = (date_tag.get("content") or date_tag.get("datetime")) if date_tag else ""
    structured_links = []
    next_data = soup.select_one('script#__NEXT_DATA__')
    if next_data and (urlparse(url).hostname or '').endswith('hkbn.net'):
        # These are public page contents embedded by HKBN's financial-results page.
        try:
            data = json.loads(next_data.get_text())['props']['pageProps']['initialState']['initData']['data']['data']
            for group in data.get('queryPageFinancialResultContents', []):
                for item in group['data']['financialResultList']['iv']:
                    row = item['data']
                    for button in row['docBtnList'].get('en_US', []):
                        structured_links.append({'url': button['docLink'], 'title': row['docTitleText']['en_US'],
                                                 'published_date': row['docDate']['iv']})
        except (KeyError, TypeError, ValueError):
            pass
    for tag in soup.select("script, style, nav, header, footer"):
        tag.decompose()
    links = [{"url": urljoin(str(response.url), a.get("href", "")), "title": a.get_text(" ", strip=True)}
             for a in soup.select("a[href]") if re.search(r"20\d{2}|interim|中期|半年|results|业绩|業績", a.get_text(" ", strip=True) + a.get("href", ""), re.I)]
    text = soup.get_text(" ", strip=True)
    if 'etnet.com.hk' in (urlparse(url).hostname or ''):
        quote_date = re.search(r'即時報價更新時間為\s*(\d{2})/(\d{2})/(20\d{2})', text)
        if quote_date:
            day, month, year = quote_date.groups()
            published = f'{year}-{month}-{day}'
    return {"opened": True, "text": text, "publication_date": published,
            "title": soup.title.get_text(" ", strip=True) if soup.title else "", "disclosure_links": links + structured_links}


@lru_cache(maxsize=20)
def company_profile(company: str) -> dict:
    from data_curation.workflow import _company_research_profile
    profile = _company_research_profile(ALIASES.get(company, company))
    if company == 'HGC':
        return {**profile, 'official_hosts': list(dict.fromkeys([*profile['official_hosts'], 'hgc.com.hk'])),
                'seed_urls': ['https://www.hgc.com.hk/cn/', 'https://www.hgc.com.hk/press-releases', *profile['seed_urls']]}
    return profile


def trusted_source(company: str, url: str, field: str) -> bool:
    host = urlparse(url).hostname or ""
    # The company's own financial reports page links to this hosted archive.
    if company == '中国铁塔' and host == 'doc.irasia.com' and urlparse(url).path.startswith('/listco/hk/chinatower/'):
        return True
    domains = company_profile(company)["official_hosts"] + ["hkexnews.hk", "cninfo.com.cn"]
    if field in {"broker", "market"}:
        # Public commentary can be used with explicit publisher/date attribution.
        # Company identity, readable original text and date are checked below.
        import ipaddress
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            return urlparse(url).scheme in {"http", "https"} and "." in host and not host.endswith((".local", ".localhost"))
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def company_matches(company: str, text: str) -> bool:
    from opencc import OpenCC
    normal = OpenCC("t2s").convert(text).casefold()
    terms = {"中国移动": ["中国移动", "china mobile"], "中国电信": ["中国电信", "china telecom"],
             "中国联通": ["中国联通", "china unicom"], "中国铁塔": ["中国铁塔", "china tower"],
             "HKT / csl / 1O1O": ["香港电讯", "hkt trust", "hkt limited"],
             "HKT": ["香港电讯", "hkt trust", "hkt limited"],
             "3HK / Hutchison": ["和记电讯", "3hk", "hutchison telecommunications"],
             "HGC": ["环球全域电讯", "hgc", "hutchison global"],
             "HKBN": ["香港宽频", "hkbn"], "SmarTone": ["数码通", "smartone"],
             "i-CABLE": ["有线宽频", "i-cable", "i cable", "ctf media & entertainment", "周大福媒体娱乐"]}.get(company, [company.casefold()])
    return any(term in normal for term in terms)


def publication_date(result: dict, page: dict):
    # Dated URL/metadata precede report-period dates embedded in the body.
    dated_url = re.sub(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?=\d|\.)", r"\1-\2-\3 ", str(result.get("url", "")))
    explicit = " ".join(str(v or "") for v in [page.get("publication_date"), page.get("published_at"), result.get("published_date"), dated_url])
    for match in re.finditer(r"(20\d{2})[-/年._](\d{1,2})[-/月._](\d{1,2})", explicit):
        try:
            return datetime(*map(int, match.groups())).date()
        except ValueError:
            pass
    if page.get('document_type') == 'pdf':
        # Incorporation dates and reporting-period ends are not publication dates.
        return None
    text = " ".join(str(v or "") for v in [page.get("publication_date"), page.get("published_at"),
                         result.get("published_date"), result.get("title"), result.get("snippet"),
                         result.get("url"), str(page.get("text", ""))[:1200]])
    text += " " + re.sub(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?=\d|\.)", r"\1-\2-\3 ", str(result.get("url", "")))
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
            start = today - timedelta(days=180 if recent else 370)
            terms = TERMS[fields[0]] if len(fields) == 1 else "interim results financial report dividend capex 中期业绩 股息 资本开支"
            subject = SEARCH_NAMES.get(pack["company"], pack["company"]).split()[0]
            query = (f'{subject} {today.year} {terms}' if fields == ['broker']
                     else f'"{subject}" {today.year} {terms} after:{start.isoformat()} before:{(today + timedelta(days=1)).isoformat()}')
            requests.append({"id": f"{pack['company']}:{','.join(fields)}", "company": pack["company"], "fields": fields, "query": query})
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
    for row in rows:
        if row["field"] not in {"broker", "market"}:
            for url in company_profile(row["company"])["seed_urls"][:4]:
                row["results"].append({"url": url, "title": row["company"] + " 官方业绩披露入口", "snippet": ""})
        else:
            for url in market_source_urls(row["company"], row["field"]):
                row["results"].append({"url": url, "title": row["company"] + " 公开市场资料", "snippet": ""})
        row["results"] = [r for r in row["results"] if trusted_source(row["company"], r["url"], row["field"])]
    urls = list(dict.fromkeys(str(r["url"]) for row in rows for r in row.get("results", [])))
    progress(f"[业绩摘要 Agent] 已筛除无关公司，读取 {len(urls)} 篇原文并检查日期。")
    def read(url):
        try:
            page = page_reader(url)
            return url, {**page, "text": str(page.get("text", ""))[:500000]}
        except Exception as exc:
            return url, {"opened": False, "error": str(exc)[:180]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        pages = dict(pool.map(read, urls))
    children = {}
    for row in rows:
        if row["field"] in {"broker", "market"}:
            continue
        links = [link for result in row["results"] for link in pages.get(result["url"], {}).get("disclosure_links", [])
                 if trusted_source(row["company"], link["url"], row["field"]) and str(today.year) in str(link)]
        links = sorted({link["url"]: link for link in links}.values(), key=lambda link: (
            "pdf" in link["url"].lower(), bool(re.search(r"interim|中期|半年|results", str(link), re.I))), reverse=True)
        for link in links[:4]:
            row["results"].append(link)
            if link["url"] not in pages:
                children[link["url"]] = link
    with ThreadPoolExecutor(max_workers=3) as pool:
        pages.update(dict(pool.map(read, children)))
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
            elif not date and (row["field"] in {"broker", "market"} or str(today.year) not in page.get("text", "")):
                reason = "未确认来源发布日期"
            elif date and date > today:
                reason = "发布日期晚于报告截止日"
            elif date and (today - date).days > (180 if row["field"] in {"broker", "market"} else 370):
                reason = "来源已超出本次检索时效范围"
            entry = {**result, "title": page.get("title") or result.get("title", ""),
                     "publishedAt": date.isoformat() if date else "", "checkedAt": today.isoformat(),
                     "text": field_excerpt(page.get("text", ""), row["field"]), "field": row["field"]}
            if reason:
                rejected.append({**entry, "reason": reason})
            else:
                accepted.append(entry)
        row["results"], row["rejected"] = sorted({r["url"]: r for r in accepted}.values(),
            key=lambda r: (r["publishedAt"], len(r["text"])), reverse=True)[:3], rejected
    progress(f"[业绩摘要 Agent] 原文核验通过 {sum(bool(r['results']) for r in rows)}/{len(rows)} 个待补字段。")
    return rows


def field_text(rows: list[dict]) -> str:
    from decimal import Decimal, InvalidOperation
    selected = {}
    for row in rows:
        key = (row.get("period", ""), row["metric"])
        # Prefer the numeric row when two stores contain the same disclosed value.
        if key not in selected or isinstance(row["value"], (int, float)):
            selected[key] = row
    values = []
    for row in selected.values():
        unit = str(row.get("unit", ""))
        for old, new in {"millions HKD": "百万港元", "HKD million": "百万港元", "millions CNY": "百万元人民币", "CNY million": "百万元人民币", "millions USD": "百万美元"}.items():
            unit = unit.replace(old, new)
        period = re.sub(r"H1\s*(20\d{2})", r"\1年上半年", str(row.get("period", "")))
        period = re.sub(r"FY\s*(20\d{2})", r"\1财年", period)
        label = row["metric"]
        try:
            if label == "资本开支" and Decimal(str(row['value']).replace(',', '')) < 0:
                label = "资本开支现金流（负值表示流出）"
        except InvalidOperation:
            pass
        values.append(f"{period} {label} {row['value']} {unit}".strip())
    return "；".join(values)


def assess_field(pack: dict, result: dict, field: str, validator):
    candidate = (result.get("fields") or {}).get(field, "")
    supplied = (result.get("sources") or {}).get(field, [])
    sources = supplied if isinstance(supplied, list) else []
    matched = [r for r in pack["web_research"]["results"] if r["field"] == field and r["url"] in sources]
    evidence = {"database": pack["evidence"][field] if field not in pack['missing'] else '', "pages": [{"title": r["title"], "text": r["text"], "publishedAt": r["publishedAt"]} for r in matched]}
    valid, text, reason = validator(field, candidate, evidence)
    if valid and field in pack['missing'] and field in {'revenue', 'profit'}:
        metric = r'收入|收益|revenue' if field == 'revenue' else r'EBITDA|净利|淨利|溢利|亏损|虧損'
        if not re.search(metric, text, re.I) or not re.search(r'\d[\d,.]*\s*(?:[百千万亿]+)?(?:港元|美元|元|HKD|RMB|CNY|USD)', text, re.I):
            valid, reason = False, '缺少该主体收入或利润的金额，不能以增长率或客户数替代'
    if field in pack["missing"] and not matched:
        valid, reason = False, "补查内容未引用对应公司的原文"
    if field in {"revenue", "profit", "capex", "dividend"} and field not in pack["missing"]:
        valid, text, reason = True, pack["evidence"][field], "采用数据库原值"
    return valid, text, reason, matched


def compact_table_value(text: str, field: str) -> str:
    if not text or text == '-':
        return '-'
    text = re.sub(r'[（(]来源[：:].*?[）)]', '', text)
    text = re.split(r'来源[：:]', text)[0]
    text = re.sub(r'(20\d{2})年上半年', r'\1H1', text)
    text = re.sub(r'(20\d{2})财年', r'FY\1', text)
    text = text.replace('百万元人民币', '百万元').replace('（负值表示流出）', '')
    if field == 'revenue':
        text = text.replace('收入 ', '')
    if field == 'capex':
        text = text.replace('资本开支现金流', '投资现金流').replace('资本开支 ', '')
    return text.strip().rstrip('。；')


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
    # One report Agent; each company has a bounded input and at most one repair.
    for start, pack in enumerate(packs):
        batch = [pack]
        progress(f"[业绩摘要 Agent] 整理 {start + 1}/{len(packs)}：{pack['company']}，核对来源。")
        try:
            editor_batch = []
            for pack in batch:
                documents = {}
                for page in pack["web_research"]["results"]:
                    document = documents.setdefault(page["url"], {**page, "fields": [], "excerpts": {}})
                    if page["field"] not in document["fields"]:
                        document["fields"].append(page["field"])
                    document["excerpts"][page["field"]] = page["text"]
                for document in documents.values():
                    # Truncating this joined value dropped the later revenue and
                    # profit evidence entirely. Keep each field's bounded excerpt.
                    document["text"] = "\n".join(f"{field}: {value}" for field, value in document.pop("excerpts").items())
                editor_batch.append({"company": pack["company"], "asOf": pack["asOf"],
                    "evidence": {f: value if f not in pack['missing'] else '' for f, value in pack["evidence"].items()}, "missing": pack["missing"],
                    "web_research": {"results": list(documents.values())}})
            try:
                response, _model = ai_client(editor_batch)
            except (TimeoutError, ValueError):
                progress(f"[业绩摘要 Agent] {pack['company']} 整理输出不完整，重试一次。")
                response, _model = ai_client(editor_batch)
            returned.update({item["company"]: item for item in response.get("companies", [])})
            draft = returned.get(pack["company"], {})
            feedback = {}
            for field in FIELDS:
                valid, _text, reason, _matched = assess_field(pack, draft, field, validator)
                if not valid and any(page["field"] == field for page in pack["web_research"]["results"]):
                    feedback[field] = reason
            if feedback:
                progress(f"[业绩摘要 Agent] 复核 {pack['company']} 的 {len(feedback)} 个字段，按原文修正。")
                retry_pack = {**editor_batch[0], "previousDraft": draft, "revisionFeedback": feedback}
                try:
                    response, _model = ai_client([retry_pack])
                    revised = next((item for item in response.get("companies", []) if item.get("company") == pack["company"]), {})
                    for field in feedback:
                        if assess_field(pack, revised, field, validator)[0]:
                            draft.setdefault("fields", {})[field] = revised["fields"][field]
                            draft.setdefault("sources", {})[field] = revised.get("sources", {}).get(field, [])
                    returned[pack["company"]] = draft
                except Exception as exc:
                    errors.append({"stage": "report_revision", "reason": str(exc)[:200], "companies": [pack["company"]]})
        except Exception as exc:
            progress("[业绩摘要局限][report_agent] 该批整理暂未完成，保留已核实的数据与缺项状态。")
            errors.append({"stage": "report_agent", "reason": str(exc)[:200], "companies": [p["company"] for p in batch]})
        save_json(run_dir / "drafts.json", returned)
        save_json(run_dir / "errors.json", {"errors": errors})
    save_json(run_dir / "drafts.json", returned)
    sections, table, audit = [], [["主体", "最新披露", "收益", "EBITDA / 利润", "资本开支", "派息"]], []
    for pack in packs:
        company = pack["company"]
        result = returned.get(company, {})
        fields, states = {}, {}
        for field in FIELDS:
            valid, text, reason, matched = assess_field(pack, result, field, validator)
            fields[field] = text if valid else pack["evidence"][field] or UNCONFIRMED
            states[field] = {"accepted": valid, "reason": reason, "sources": [r["url"] for r in matched],
                             "databaseRows": pack["database"][field], "needsResearch": field in pack["missing"]}
        periods = list(dict.fromkeys(r["period"] for f in ["revenue", "profit", "capex"] for r in pack["database"][f]))
        # Keep the actual period on each numeric field; avoid declaring all fields current.
        cells = []
        for field in ['revenue', 'profit', 'capex', 'dividend']:
            compact = (result.get('tableFields') or {}).get(field, '')
            # A compact cell is a second presentation of the already accepted fact.
            ok = (states[field]['accepted'] and 0 < len(compact) <= 70
                  and validator(field, compact, fields[field])[0])
            cells.append(compact_table_value(compact if ok else fields[field], field))
        period_label = re.sub(r'(H[12]|Q[1-4])\s*(20\d{2})', r'\2\1', '；'.join(periods))
        table.append([company, period_label or "见正文", *cells])
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
             "intro": f"本摘要截至{clock.year}年{clock.month}月{clock.day}日，汇总内地运营商及香港主要竞对最近已披露业绩、资本配置与公开市场观点。各项保留原报告期间、币种与主体口径；观点注明原来源及日期，缺项以“-”表示。",
             "table_caption": "表：内地运营商及香港主要竞对最新关键业绩数据汇总", "table": table, "sections": sections,
             "generationMode": "limited" if unresolved or errors else "normal", "generationLimitations": errors,
             "researchAudit": proof}
    save_json(run_dir / "model.json", model)
    return model
