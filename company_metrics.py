from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
FEISHU_CACHE_PATH = ROOT / "carrier_performance_feishu.json"
PERFORMANCE_SOURCES_PATH = ROOT / "carrier_performance_sources.json"
AI_CACHE_PATH = ROOT / "company_metrics_ai_cache.json"
VERIFIED_FACTS_PATH = ROOT / "curation_data" / "verified_facts.jsonl"
AI_CACHE_SCHEMA_VERSION = 3

CORE_METRICS = ["派息", "资本开支", "战略升级", "券商观点", "市场反应"]
DISCLOSURE_FIELDS = ["最新披露", "披露日期", "股票代码"]
SUMMARY_METRICS = ["收益", "EBITDA / 利润"]
MAINLAND_SUMMARY_ROWS = {
    "中国移动": ["中国移动", "2026Q1", "2665亿元", "归母净利润293亿元", "2025年1509亿元；2026年计划1366亿元", "全年每股5.27港元"],
    "中国电信": ["中国电信", "2026Q1", "2025年5296亿元", "2025年EBITDA 1439亿元", "2025年804亿元", "全年每股0.2720元"],
    "中国联通": ["中国联通", "2026Q1", "2026Q1经营收入1028.24亿元", "2026Q1归母净利润48.85亿元", "2025年542亿元；2026年计划约500亿元", "全年每股0.417元"],
    "中国铁塔": ["中国铁塔", "2026Q1 KPI", "2025年1004.11亿元", "2025年归母净利润116亿元", "2025年294.86亿元", "全年每股0.45789元"],
}
QUALITATIVE_METRIC_RE = re.compile(
    r"战略|观点|反应|合作|中标|人事|AI|云|ICT|API|Open RAN|网络|规划|政策|"
    r"安全|跨境|低空|Web3|动态|收购|交易|地缘|经济|声明|IoT|融合|区域|公告|董事会|股东大会|关联交易|"
    r"Capex方向|资本开支方向|投资方向",
    re.IGNORECASE,
)
DIRTY_SOURCE_LABEL_TERMS = [
    "Financials & Income Statement",
    "Skip to main content",
    "Skip to content",
    "Log In Sign Up",
    "Home Watchlist",
    "Stock Screener",
    "Markdown filings API",
    "Policy sets out standards",
    "SOURCE:",
    "http://",
    "https://",
    "www.",
    "Read More",
    "Load More",
    "Play Previous Next",
    "Previous Slide Next Slide",
    "Cookies Policy",
    "Accept & Close",
    "Privacy Policy",
    "Legal notice",
    "Sitemap",
    "Configure Cookies",
    "Family Friendly",
    "Search Telstra",
    "Access to save data",
    "Today's Press Releases",
    "Back to top",
    "Last Review Date",
    "Career@",
    "About Us Governance",
    "Brand Site",
    "FAQ",
    "your music deserves",
]
KNOWN_COMPANY_NAMES = {
    "HKT", "csl", "1O1O", "3HK", "Hutchison", "SmarTone", "HKBN", "HGC", "iCable", "i-CABLE",
    "Singtel", "Telstra", "SK Telecom", "KT", "NTT Docomo", "KDDI", "SoftBank", "Jio", "Airtel",
    "Vodafone", "Deutsche Telekom", "Orange", "Telefonica", "BT/EE", "TIM", "Verizon", "AT&T",
    "T-Mobile US", "e&", "stc", "中国移动", "中国电信", "中国联通", "中国铁塔",
}
DISPLAY_COMPANY_ALIASES = {
    "3HK": "3HK / Hutchison",
    "iCable": "i-CABLE",
}
NON_COMPANY_SUBJECTS = {
    "行业资讯",
    "政治新闻",
    "政治资讯",
    "经济资讯",
    "社会资讯",
}
VALUE_UNIT_RE = re.compile(
    r"(?:HK\$|US\$|RMB|人民币|港币|港元|\$)?\s*[-+]?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:亿港元|亿人民币|亿美元|亿元|万港元|百万港元|亿|港元|港仙|元|美元|%|个百分点|pp|pps|"
    r"HKD|CNY|RMB|million|billion|bn|B|M|m|GB|GHz|MHz|Mbps|G|户|人|customers|subscribers)?",
    re.IGNORECASE,
)


def _metric_category(metric: str) -> str:
    text = str(metric or "")
    if text in DISCLOSURE_FIELDS:
        return "披露信息"
    if re.search(r"收入|收益|EBITDA|利润|派息|股息|分派|资本开支|Capex|融资|商誉", text, re.IGNORECASE):
        return "财务业绩"
    if re.search(r"用户|客户|ARPU|覆盖|宽频|家宽|5G用户|区域布局", text, re.IGNORECASE):
        return "客户经营"
    if re.search(r"套餐|资费|产品|漫游|促销|增值服务|SoSIM|融合", text, re.IGNORECASE):
        return "产品资费"
    if re.search(r"战略|AI|云|ICT|API|Open RAN|5G-A|网络|算力|合作|中标|IoT|人事", text, re.IGNORECASE):
        return "技术战略"
    if re.search(r"政策|监管|频谱|GDP|CPI|人口|汇率|低空|Web3|地缘|经济|声明|跨境", text, re.IGNORECASE):
        return "政策宏观"
    return "其他"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _clean_text(value: object, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _normalize_company_name(value: object) -> str:
    company = _clean_text(value, 80)
    return DISPLAY_COMPANY_ALIASES.get(company, company)


def _is_publishable_company(company: str) -> bool:
    if not company:
        return False
    if company in NON_COMPANY_SUBJECTS:
        return False
    if re.search(r"(?:资讯|新闻)$", company):
        return False
    return True


def _normalize_row_company(row: dict) -> dict | None:
    original_company = str(row.get("company") or "").strip()
    normalized_company = _normalize_company_name(original_company)
    if not _is_publishable_company(normalized_company):
        return None
    if original_company == "3HK" and row.get("metric") == "市场反应":
        return None
    row["company"] = normalized_company
    return row


def _fact_publish_signature(company: str, metric: str, value: object) -> tuple[str, str, str]:
    return (
        _normalize_company_name(company),
        _clean_text(metric, 120),
        re.sub(r"\s+", "", _normalize_verified_value(value)).casefold(),
    )


def _normalize_verified_value(value: object) -> str:
    text = _clean_text(value, 600)
    text = re.sub(
        r"CAPEX \(excluding telecommunications licences\) \(433；资本开支\.\.\.稳定在HK\$433 million",
        "资本开支4.33亿港元",
        text,
        flags=re.IGNORECASE,
    )

    def million_hkd(match: re.Match[str]) -> str:
        amount = float(match.group(1).replace(",", "")) / 100
        return f"{amount:.2f}亿港元"

    def hk_cents(match: re.Match[str]) -> str:
        amount = float(match.group(1)) / 100
        return f"{amount:.4f}".rstrip("0").rstrip(".") + "港元/股"

    text = re.sub(r"HK\$\s*([\d,]+(?:\.\d+)?)\s*million", million_hkd, text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*HK\s*cents?(?:\s*per share)?", hk_cents, text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*港仙(?:/股)?", hk_cents, text)
    return text


def _verified_fact_publish_issue(fact: dict) -> str:
    company = str(fact.get("company") or "")
    metric = str(fact.get("metric") or "")
    value = str(fact.get("value") or "")
    if "无资费信息" in value or "无家宽套餐信息" in value:
        return "来源未提供该项数据"
    if company == "iCable" and metric == "派息" and "FY2024" in value:
        return "披露期早于当前FY2025业绩口径"
    if re.search(r"公开信息已更新|未提取到有效数据", value):
        return "缺少可直接发布的事实值"
    return ""


def _value_has_unit(token: str) -> bool:
    return bool(
        re.search(
            r"HK\$|US\$|RMB|人民币|港币|港元|HKD|CNY|\$|亿|万|百万|元|美元|%|百分点|pp|million|billion|bn|\bB\b|GB|GHz|MHz|Mbps|户|人",
            token,
            re.IGNORECASE,
        )
    )


def _is_likely_year_or_date(token: str) -> bool:
    compact = re.sub(r"[^\d.]", "", token)
    if compact in {"2023", "2024", "2025", "2026"}:
        return True
    return bool(re.fullmatch(r"20\d{2}", compact))


def _focused_match(metric: str, text: str) -> str:
    metric_lower = metric.lower()
    metric_patterns: list[tuple[str, str]] = [
        ("收入|收益|revenue", r"(?:Revenue|Total revenue|annual revenue|收益|总收益|收入)[^\d]{0,36}([A-Z$HKDRMB\s]*\d[\d,]*(?:\.\d+)?\s*(?:B\s*HKD|B\s*USD|亿港元|亿元|亿美元|亿|HKD|CNY|RMB|million|billion|bn|B|%|港元|元)?)"),
        ("服务收入|service", r"(?:service revenue|services revenue|服务收入|主营业务收入)[^\d]{0,42}([A-Z$HKDRMB\s]*\d[\d,]*(?:\.\d+)?\s*(?:B\s*HKD|B\s*USD|亿港元|亿元|亿美元|亿|HKD|CNY|RMB|million|billion|bn|B|%|港元|元)?)"),
        ("ebitda", r"EBITDA[^\d]{0,36}([A-Z$HKDRMB\s]*\d[\d,]*(?:\.\d+)?\s*(?:B\s*HKD|B\s*USD|亿港元|亿元|亿美元|亿|HKD|CNY|RMB|million|billion|bn|B|%|港元|元)?)"),
        (
            "净利润|profit|溢利",
            r"(?:净利润|归母净利润|net profit|net income|net loss|profit attributable|loss attributable|"
            r"股东应占溢利|本公司拥有人应占(?:溢利|亏损)|本公司擁有人應佔(?:溢利|虧損))"
            r"[^\d-]{0,42}([-+]?\s*[A-Z$HKDRMB\s]*\d[\d,]*(?:\.\d+)?\s*"
            r"(?:B\s*HKD|B\s*USD|亿港元|亿元|亿美元|亿|HKD|CNY|RMB|million|billion|bn|m|M|B|%|港元|元)?)",
        ),
        ("资本开支|capex|capital expenditure", r"(?:资本开支|capital expenditure|capex)[^\d]{0,42}([A-Z$HKDRMB\s]*\d[\d,]*(?:\.\d+)?\s*(?:B\s*HKD|B\s*USD|亿港元|亿元|亿美元|亿|HKD|CNY|RMB|million|billion|bn|B|%|港元|元|美元)?)"),
        ("派息|股息|dividend|分派", r"(?:派息|股息|分派|dividend)[^\d]{0,42}([A-Z$HKRMB\s]*\d[\d,]*(?:\.\d+)?\s*(?:港元|港仙|元|%|cents|cent)?)"),
        ("用户|客户|customer|subscriber", r"(?:用户|客户|customer|subscriber|base)[^\d]{0,42}(\d[\d,]*(?:\.\d+)?\s*(?:million|M|m|亿户|万户|户|%))"),
        ("5g", r"5G[^\d]{0,48}(\d[\d,]*(?:\.\d+)?\s*(?:million|M|m|亿户|万户|户|%|个百分点|pp)?)"),
        ("arpu", r"ARPU[^\d]{0,30}([A-Z$HKRMB\s]*\d[\d,]*(?:\.\d+)?\s*(?:港元|元|HKD|RMB|\$)?)"),
    ]
    values: list[str] = []
    for keyword_re, pattern in metric_patterns:
        if not re.search(keyword_re, metric_lower, re.IGNORECASE):
            continue
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            full = _clean_text(match.group(0), 90)
            if re.search(r"\b(?:net loss|loss attributable)\b|(?:亏损|虧損)", full, re.IGNORECASE):
                full = re.sub(
                    r"((?:HK\$|US\$|HKD|USD|RMB|CNY)?\s*)(\d[\d,]*(?:\.\d+)?)",
                    lambda m: f"{m.group(1)}-{m.group(2)}",
                    full,
                    count=1,
                )
            if full and full not in values:
                values.append(full)
            if len(values) >= 3:
                break
        if values:
            break
    return "；".join(values)


def _direct_value(metric: str, value: object) -> str:
    text = _clean_text(value, 1200)
    if not text:
        return ""
    if metric in SUMMARY_METRICS:
        return _clean_text(text, 180)

    if QUALITATIVE_METRIC_RE.search(metric):
        if re.search(r"市场反应", metric, re.IGNORECASE):
            price_match = re.search(
                r"前一交易日[^。；]*?收盘价为?([0-9.]+\s*港元).*?"
                r"后一交易日[^。；]*?收盘价为?([0-9.]+\s*港元).*?"
                r"(上涨|下跌)([0-9.]+%)",
                text,
            )
            if price_match:
                direction = "+" if price_match.group(3) == "上涨" else "-"
                return f"{price_match.group(1)} → {price_match.group(2)}（{direction}{price_match.group(4)}）"
            focus_match = re.search(r"(市场(?:关注点|主要担忧|继续关注|反应重点)[^。]*。?)", text)
            if focus_match:
                return _clean_text(focus_match.group(1), 220)
        return _clean_text(text, 220)
    if re.search(r"资本开支|capex|capital expenditure", metric, re.IGNORECASE) and re.search(
        r"未公开|未单列|未单独列示|不适用", text
    ):
        return _clean_text(text, 220)

    focused = _focused_match(metric, text)
    if focused:
        return focused

    tokens: list[str] = []
    for match in VALUE_UNIT_RE.finditer(text):
        token = _clean_text(match.group(0), 40)
        if not token or _is_likely_year_or_date(token):
            continue
        if not _value_has_unit(token):
            continue
        if token not in tokens:
            tokens.append(token)
        if len(tokens) >= 4:
            break
    if tokens:
        return "；".join(tokens)

    return _clean_text(text, 120)


def _source_label(url: str) -> str:
    host = urlparse(url).netloc or url
    return host.replace("www.", "")


def _clean_source_label(label: object, url: str) -> str:
    text = _clean_text(label, 80)
    if not text or any(term.lower() in text.lower() for term in DIRTY_SOURCE_LABEL_TERMS):
        return _source_label(url)
    return text


def _split_links(value: object) -> list[dict]:
    links: list[dict] = []
    for raw in re.split(r"[\n,，\s]+", str(value or "")):
        url = raw.strip()
        if not url.startswith(("http://", "https://")):
            continue
        if any(item["url"] == url for item in links):
            continue
        links.append({"label": _source_label(url), "url": url})
    return links


def _performance_source_links() -> dict[str, list[dict]]:
    data = _read_json(PERFORMANCE_SOURCES_PATH, {})
    companies = data.get("companies", {}) if isinstance(data, dict) else {}
    output: dict[str, list[dict]] = {}
    for company, config in companies.items():
        links: list[dict] = []
        for source in config.get("sources", []) if isinstance(config, dict) else []:
            url = str(source.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            label = str(source.get("label") or "").strip() or _source_label(url)
            if not any(item["url"] == url for item in links):
                links.append({"label": label, "url": url, "type": source.get("type", "")})
        output[str(company)] = links
    return output


def _performance_summary_rows() -> dict[str, list[str]]:
    data = _read_json(PERFORMANCE_SOURCES_PATH, {})
    companies = data.get("companies", {}) if isinstance(data, dict) else {}
    output = dict(MAINLAND_SUMMARY_ROWS)
    for company, config in companies.items():
        row = config.get("table_row") if isinstance(config, dict) else None
        if isinstance(row, list) and len(row) >= 6:
            output[str(company)] = [_clean_text(value, 160) for value in row[:6]]
    return output


def _make_row(
    *,
    company: str,
    metric: str,
    value: str,
    group: str = "",
    disclosure: str = "",
    disclosure_date: str = "",
    stock_code: str = "",
    source_type: str = "verified-performance",
    sources: list[dict] | None = None,
    confidence: object = None,
    row_ref: str = "",
) -> dict:
    detail = _clean_text(value)
    source_fingerprint = "|".join(source.get("url", "") for source in (sources or [])[:4])
    row_id_raw = "|".join([company, metric, row_ref, source_type, detail[:260], source_fingerprint])
    row_id = hashlib.sha1(row_id_raw.encode("utf-8")).hexdigest()[:16]
    detail = _clean_text(value)
    return {
        "id": row_id,
        "company": company,
        "metric": metric,
        "value": _direct_value(metric, value),
        "detail": detail,
        "group": group,
        "disclosure": disclosure,
        "disclosureDate": disclosure_date,
        "stockCode": stock_code,
        "sourceType": source_type,
        "sources": sources or [],
        "confidence": confidence,
        "rowRef": row_ref,
    }


def _apply_ai_cache(rows: list[dict]) -> list[dict]:
    cache = _read_json(AI_CACHE_PATH, {})
    for row in rows:
        if row.get("sourceType") == "public-crawl":
            row["aiStatus"] = "unavailable"
            row["aiNote"] = "等待AI归属与指标语义校验"
    if cache.get("schemaVersion") != AI_CACHE_SCHEMA_VERSION:
        return rows
    items = cache.get("items", {}) if isinstance(cache, dict) else {}
    if not isinstance(items, dict) or not items:
        return rows
    semantic_items: dict[tuple[str, str, str], dict] = {}
    for item in items.values():
        if (
            not isinstance(item, dict)
            or item.get("status") != "ok"
            or not _cache_item_brand_consistent(item)
        ):
            continue
        key = (
            str(item.get("company") or ""),
            str(item.get("metric") or ""),
            str(item.get("row_ref") or ""),
        )
        if all(key):
            semantic_items.setdefault(key, item)
    for row in rows:
        if _apply_brand_market_reaction_not_applicable(row):
            continue
        item = items.get(row.get("id"))
        if (
            not isinstance(item, dict)
            or item.get("status") != "ok"
            or not _cache_item_brand_consistent(item)
        ):
            item = semantic_items.get(
                (
                    str(row.get("company") or ""),
                    str(row.get("metric") or ""),
                    str(row.get("rowRef") or ""),
                )
            )
        if not isinstance(item, dict):
            continue
        if not _cache_item_brand_consistent(item):
            continue
        cleaned_value = _clean_text(item.get("value"), 220)
        if not cleaned_value:
            continue
        row["value"] = cleaned_value
        row["detail"] = _clean_text(item.get("basis") or row.get("detail") or "", 600)
        row["aiCleaned"] = True
        row["aiStatus"] = item.get("status") or "ok"
        row["aiNote"] = _clean_text(item.get("note") or "", 120)
        row["aiConfidence"] = item.get("confidence")
        row["entitySupported"] = bool(item.get("entity_supported"))
        row["metricSupported"] = bool(item.get("metric_supported"))
        row["valueSupported"] = bool(item.get("value_supported"))
        if not all(
            [
                row["entitySupported"],
                row["metricSupported"],
                row["valueSupported"],
            ]
        ):
            row["aiStatus"] = "unavailable"
            row["aiNote"] = "公司归属、指标语义或数值依据未通过校验"
        if row["aiStatus"] == "ok" and not _passes_metric_gate(row.get("metric", ""), cleaned_value):
            row["aiStatus"] = "unavailable"
            row["aiNote"] = "AI清洗值未通过指标单位门禁"
    return rows


def _apply_brand_market_reaction_not_applicable(row: dict) -> bool:
    if row.get("company") not in {"csl", "1O1O", "3HK"} or row.get("metric") != "市场反应":
        return False
    row["value"] = "不适用（品牌非独立上市主体）"
    row["detail"] = "该品牌没有独立上市证券，不能单独计算业绩发布前后的股票市场反应。"
    row["aiCleaned"] = True
    row["aiStatus"] = "ok"
    row["aiNote"] = "依据品牌上市口径确认不适用"
    row["aiConfidence"] = 0.95
    row["entitySupported"] = True
    row["metricSupported"] = True
    row["valueSupported"] = True
    return True


def _cache_item_brand_consistent(item: dict) -> bool:
    company = str(item.get("company") or "")
    if company not in {"csl", "1O1O"}:
        return True
    evidence = f"{item.get('value', '')} {item.get('basis', '')}"
    if company == "csl":
        return "csl" in evidence.lower()
    return "1o1o" in evidence.lower()


def _passes_metric_gate(metric: str, value: str) -> bool:
    metric_text = str(metric or "")
    value_text = str(value or "")
    if not value_text or "未提取到有效数据" in value_text:
        return False
    if any(term.lower() in value_text.lower() for term in DIRTY_SOURCE_LABEL_TERMS):
        return False
    if re.search(r"本轮公开来源未发现.+可核验披露；维持后续监测", value_text):
        return True
    if re.search(r"不适用（?(?:非上市主体|品牌非独立上市主体)）?", value_text):
        return bool(re.search(r"派息|股息|分派|券商观点|市场反应", metric_text, re.IGNORECASE))
    if re.search(r"市场反应", metric_text, re.IGNORECASE):
        return bool(
            re.search(
                r"股价|收盘|上涨|下跌|升|跌|市场关注|市场担忧|市场反应|交易日|目标价|评级|"
                r"\d+(?:\.\d+)?\s*港元\s*→\s*\d+(?:\.\d+)?\s*港元",
                value_text,
                re.IGNORECASE,
            )
        )
    if re.search(r"券商观点", metric_text, re.IGNORECASE):
        return bool(
            re.search(
                r"券商|分析师|评级|买入|增持|中性|持有|跑赢|跑输|目标价|公允价值|broker|analyst",
                value_text,
                re.IGNORECASE,
            )
        )
    if re.search(r"ARPU", metric_text, re.IGNORECASE):
        return bool(re.search(r"\d", value_text)) and not bool(
            re.search(r"利润|溢利|EBITDA|收入|资本开支|折旧", value_text, re.IGNORECASE)
        )
    if re.search(r"EBITDA", metric_text, re.IGNORECASE):
        return bool(re.search(r"\d", value_text)) and bool(
            re.search(
                r"港元|人民币|亿元|亿|万元|百万|million|billion|bn|HK\$|US\$|RMB|增长|下降|上升|减少|同比|按年",
                value_text,
                re.IGNORECASE,
            )
        ) and not bool(
            re.search(r"运营成本|营运成本|资本开支|折旧及摊销", value_text, re.IGNORECASE)
        )
    if re.search(r"派息|股息|分派|dividend", metric_text, re.IGNORECASE):
        return bool(re.search(r"\d", value_text)) and bool(
            re.search(r"港元|港仙|人民币|每股|股息|派息|分派|dividend|cent|cents", value_text, re.IGNORECASE)
        ) or bool(re.search(r"不派|不建议派发|不适用", value_text))
    if re.search(r"Capex方向|资本开支方向|投资方向", metric_text, re.IGNORECASE):
        return len(value_text.strip()) >= 8 and bool(
            re.search(
                r"资本开支|capex|投资|基础设施|网络|算力|AI|数据中心|云|频谱",
                value_text,
                re.IGNORECASE,
            )
        )
    if re.search(r"资本开支|capex|capital expenditure", metric_text, re.IGNORECASE):
        return bool(re.search(r"资本开支|capex|capital expenditure", value_text, re.IGNORECASE)) or (
            bool(
                re.search(
                    r"亿|万|百万|港元|元|美元|HK\\$|US\\$|Rs\.?|₹|crore|lakh",
                    value_text,
                    re.IGNORECASE,
                )
            )
            and not bool(re.search(r"折旧|摊销", value_text))
        )
    if re.search(r"GDPR|DSA|AI与数据监管|数据监管", metric_text, re.IGNORECASE):
        return len(value_text.strip()) >= 6 and bool(
            re.search(
                r"GDPR|DSA|Data Act|AI Act|数据|监管|合规|compliant|protection|rules",
                value_text,
                re.IGNORECASE,
            )
        )
    if re.search(r"收入|收益|EBITDA|利润|ARPU|用户|客户|宽频|家宽|套餐|资费|频谱|GDP|CPI", metric_text, re.IGNORECASE):
        if not re.search(r"\d", value_text):
            return False
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?%", value_text.strip()):
            return False
        if re.search(r"收入|收益|EBITDA|利润", metric_text, re.IGNORECASE):
            return bool(
                re.search(
                    r"港元|港仙|人民币|亿元|亿|万元|百万|million|billion|bn|\bB\b|\d\s*M\b|HKD|CNY|HK\$|US\$|RMB|"
                    r"增长|下降|上升|减少|同比|按年",
                    value_text,
                    re.IGNORECASE,
                )
            )
        if re.search(r"套餐|资费", metric_text, re.IGNORECASE):
            return bool(re.search(r"\d", value_text))
        if re.search(r"用户|客户|宽频|家宽", metric_text, re.IGNORECASE):
            return bool(
                re.search(
                    r"户|人|用户|客户|million|\bM\b|万|亿|%|月费|港元|HK\$|Mbps|Gbps|Wi-?Fi",
                    value_text,
                    re.IGNORECASE,
                )
            )
        return True
    return True


def _row_quality_issues(row: dict) -> list[str]:
    issues: list[str] = []
    if not row.get("value"):
        issues.append("缺少展示值")
    if not row.get("sources"):
        issues.append("缺少可点击来源")
    text = f"{row.get('value', '')} {row.get('detail', '')}"
    if row.get("sourceType") == "public-crawl" and any(term.lower() in text.lower() for term in DIRTY_SOURCE_LABEL_TERMS):
        issues.append("包含网页导航或无关文本")
    if row.get("metric") in KNOWN_COMPANY_NAMES:
        issues.append("指标名疑似串入公司名称")
    if row.get("sourceType") == "public-crawl":
        if row.get("aiStatus") != "ok":
            issues.append("AI校验未通过")
        if not all([row.get("entitySupported"), row.get("metricSupported"), row.get("valueSupported")]):
            issues.append("公司归属或指标语义不成立")
        confidence = row.get("aiConfidence")
        try:
            confidence_number = float(confidence)
        except (TypeError, ValueError):
            confidence_number = 0.0
        if confidence_number < 0.8:
            issues.append("AI校验置信度不足80%")
        if not _passes_metric_gate(row.get("metric", ""), row.get("value", "")):
            issues.append("未通过指标格式门禁")
        metric = str(row.get("metric") or "")
        detail = str(row.get("detail") or "")
        company = str(row.get("company") or "")
        if "AI不可用" in str(row.get("aiNote") or ""):
            issues.append("在线AI不可用时不展示公开监测记录")
            if row.get("valueType") == "text":
                issues.append("离线兜底不展示文本型公开监测记录")
            if len(str(row.get("value") or "")) > 120:
                issues.append("离线兜底值过长")
        if company in {"csl", "1O1O"} and re.search(
            r"收入|收益|EBITDA|利润|资本开支|派息|用户数|ARPU", metric, re.IGNORECASE
        ):
            issues.append("品牌口径不能直接承接集团财务指标")
        if re.search(r"利润|净利润", metric, re.IGNORECASE) and re.search(
            r"Non-controlling|少数股东|minority", detail, re.IGNORECASE
        ):
            issues.append("少数股东损益不能替代净利润")
        if re.search(r"运营收入/总收益", metric) and re.search(r"服务收入|service revenue", detail, re.IGNORECASE):
            issues.append("服务收入不能替代总收益")
        if re.search(r"资费", metric) and re.search(r"屏幕|更换|消费赚|reward", detail, re.IGNORECASE):
            issues.append("权益或奖励金额不能替代套餐资费")
        if re.search(r"World Bank|IMF|GDP|CPI", metric, re.IGNORECASE) and re.search(
            r"\d+\s*(?:条|records?)", row.get("value", ""), re.IGNORECASE
        ):
            issues.append("接口记录数不能替代宏观指标值")
    return issues


def _looks_like_fragment_value(metric: str, value: str) -> bool:
    text = _clean_text(value, 260)
    if not text:
        return True
    if any(term.lower() in text.lower() for term in DIRTY_SOURCE_LABEL_TERMS):
        return True
    if re.search(r"\s\|\s|suggestions found|\b\d+/\d+\b|Search Close", text, re.IGNORECASE):
        return True
    if QUALITATIVE_METRIC_RE.search(metric) and (
        re.match(r"^[a-z]{2,}[,;:\s-]", text)
        or re.match(r"^[a-z]{2,}\s+[A-Z]", text)
    ):
        return True
    return False


def _suppress_public_candidate(company: str, metric: str, value: str, row_ref: str) -> str:
    if metric in KNOWN_COMPANY_NAMES:
        return "指标名是公司名"
    if _looks_like_fragment_value(metric, value):
        return "抽取值是网页残片"
    if company in {"csl", "1O1O"} and row_ref == "row_2" and re.search(
        r"收入|收益|EBITDA|利润|资本开支|派息|用户数|ARPU|宽频|家宽",
        metric,
        re.IGNORECASE,
    ):
        return "品牌口径不能直接继承HKT集团财务指标"
    if re.search(r"收入|收益|EBITDA|利润|资本开支", metric, re.IGNORECASE) and re.fullmatch(
        r"[-+]?\d+(?:\.\d+)?%", value.strip()
    ):
        return "百分比不能替代财务金额"
    return ""


def _performance_rows() -> list[dict]:
    data = _read_json(FEISHU_CACHE_PATH, {})
    source_links = _performance_source_links()
    summary_rows = _performance_summary_rows()
    rows = data.get("rows", []) if isinstance(data, dict) else []
    output: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        company = str(item.get("主体") or "").strip()
        if not company:
            continue
        links = _split_links(item.get("来源链接")) or source_links.get(company, [])
        common = {
            "company": company,
            "group": str(item.get("范围") or "").strip(),
            "disclosure": str(item.get("最新披露") or "").strip(),
            "disclosure_date": str(item.get("披露日期") or "").strip(),
            "stock_code": str(item.get("股票代码") or "").strip(),
            "sources": links,
        }
        for metric in DISCLOSURE_FIELDS:
            value = str(item.get(metric) or "").strip()
            if value:
                output.append(_make_row(metric=metric, value=value, **common))
        summary_row = summary_rows.get(company)
        if summary_row:
            for metric, value in zip(SUMMARY_METRICS, summary_row[2:4]):
                if value:
                    output.append(_make_row(metric=metric, value=value, **common))
        for metric in CORE_METRICS:
            value = str(item.get(metric) or "").strip()
            if value:
                output.append(_make_row(metric=metric, value=value, **common))
    return output


def _record_sources(entity_result: dict, result_data: dict) -> list[dict]:
    links: list[dict] = []
    for record in entity_result.get("raw_records") or result_data.get("raw_records") or []:
        if not isinstance(record, dict):
            continue
        url = str(record.get("final_url") or record.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        title = _clean_source_label(record.get("title") or _source_label(url), url)
        if not any(item["url"] == url for item in links):
            links.append(
                {
                    "label": title or _source_label(url),
                    "url": url,
                    "status": record.get("status"),
                    "sourceType": record.get("source_type", ""),
                }
            )
    for url in entity_result.get("source_urls") or result_data.get("source_urls") or []:
        url = str(url).strip()
        if url.startswith(("http://", "https://")) and not any(item["url"] == url for item in links):
            links.append({"label": _source_label(url), "url": url})
    return links


def _crawl_rows() -> list[dict]:
    output: list[dict] = []
    for path in sorted(RESULTS_DIR.glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        data = _read_json(path, {})
        if not isinstance(data, dict):
            continue
        entity_results = data.get("entity_results") or []
        if not entity_results and data.get("extracted"):
            entity_results = [
                {
                    "entity": data.get("object") or f"第{data.get('row')}行",
                    "extracted": data.get("extracted") or {},
                    "source_urls": data.get("source_urls") or [],
                    "raw_records": data.get("raw_records") or [],
                    "confidence_score": None,
                }
            ]
        for entity_result in entity_results:
            if not isinstance(entity_result, dict):
                continue
            company = str(entity_result.get("entity") or "").strip()
            extracted = entity_result.get("extracted") or {}
            if not company or not isinstance(extracted, dict):
                continue
            sources = _record_sources(entity_result, data)
            for metric, value in extracted.items():
                value_text = _clean_text(value)
                if not value_text:
                    continue
                row_ref = f"row_{data.get('row')}"
                suppress_reason = _suppress_public_candidate(company, str(metric), value_text, row_ref)
                if suppress_reason:
                    continue
                output.append(
                    _make_row(
                        company=company,
                        metric=str(metric),
                        value=value_text,
                        group=str(data.get("object") or ""),
                        source_type="public-crawl",
                        sources=sources,
                        confidence=entity_result.get("confidence_score"),
                        row_ref=row_ref,
                    )
                )
    return output


def _verified_fact_rows() -> list[dict]:
    if not VERIFIED_FACTS_PATH.exists():
        return []

    result_context: dict[str, dict] = {}
    for path in RESULTS_DIR.glob("row_*.json"):
        data = _read_json(path, {})
        if isinstance(data, dict):
            result_context[path.stem] = data

    output: list[dict] = []
    for line in VERIFIED_FACTS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            fact = json.loads(line)
        except json.JSONDecodeError:
            continue
        if fact.get("status") != "ok" or fact.get("decision") != "accepted":
            continue
        if not all(
            [
                fact.get("entity_supported"),
                fact.get("metric_supported"),
                fact.get("value_supported"),
            ]
        ):
            continue
        if _verified_fact_publish_issue(fact):
            continue

        row_ref = str(fact.get("row_ref") or "")
        context = result_context.get(row_ref, {})
        sources = [
            {"label": _source_label(str(url)), "url": str(url)}
            for url in fact.get("sources") or []
            if str(url).startswith(("http://", "https://"))
        ]
        row = _make_row(
            company=str(fact.get("company") or "").strip(),
            metric=str(fact.get("metric") or "").strip(),
            value=_normalize_verified_value(fact.get("value")),
            group=str(context.get("object") or "").strip(),
            source_type="public-crawl",
            sources=sources,
            confidence=fact.get("confidence"),
            row_ref=row_ref,
        )
        row["id"] = str(fact.get("id") or row["id"])
        row["value"] = _normalize_verified_value(fact.get("value"))
        row["detail"] = _normalize_verified_value(fact.get("basis") or fact.get("value"))
        row["aiCleaned"] = True
        row["aiStatus"] = "ok"
        row["aiNote"] = _clean_text(fact.get("note") or "", 120)
        row["aiConfidence"] = fact.get("confidence")
        row["entitySupported"] = True
        row["metricSupported"] = True
        row["valueSupported"] = True
        row["qualityScore"] = fact.get("quality_score")
        row["sourceTier"] = fact.get("source_tier")
        output.append(row)
    return output


def build_company_metrics_payload(apply_ai_cache: bool = True) -> dict:
    rows = _performance_rows()
    verified_fact_rows = _verified_fact_rows() if apply_ai_cache else []
    rows.extend(verified_fact_rows or _crawl_rows())
    candidate_count = len(rows)
    rows = [row for row in (_normalize_row_company(row) for row in rows) if row is not None]
    if apply_ai_cache and not verified_fact_rows:
        rows = _apply_ai_cache(rows)
        rows = [
            row
            for row in rows
            if not (row.get("sourceType") == "public-crawl" and row.get("aiStatus") == "unavailable")
        ]

    if apply_ai_cache:
        for row in rows:
            row["qualityIssues"] = _row_quality_issues(row)
        rows = [row for row in rows if not row["qualityIssues"]]

        duplicate_groups: dict[tuple[str, str, str], set[str]] = {}
        for row in rows:
            if row.get("sourceType") != "public-crawl":
                continue
            fingerprint = (
                row.get("rowRef", ""),
                row.get("metric", ""),
                re.sub(r"\s+", "", row.get("value", "")).lower(),
            )
            duplicate_groups.setdefault(fingerprint, set()).add(row.get("company", ""))
        suspicious_duplicates = {key for key, companies in duplicate_groups.items() if len(companies) >= 4}
        rows = [
            row
            for row in rows
            if (
                row.get("sourceType") != "public-crawl"
                or (
                    row.get("rowRef", ""),
                    row.get("metric", ""),
                    re.sub(r"\s+", "", row.get("value", "")).lower(),
                )
                not in suspicious_duplicates
            )
        ]

        unique_rows: list[dict] = []
        seen_facts: set[tuple[str, str, str, str]] = set()
        for row in rows:
            fingerprint = (
                str(row.get("company") or ""),
                str(row.get("metric") or ""),
                re.sub(r"\s+", "", str(row.get("value") or "")).casefold(),
                str(row.get("sourceType") or ""),
            )
            if fingerprint in seen_facts:
                continue
            seen_facts.add(fingerprint)
            unique_rows.append(row)
        rows = unique_rows
    else:
        for row in rows:
            row["qualityIssues"] = []
    for row in rows:
        row["value"] = _normalize_verified_value(row.get("value"))
        row["detail"] = _normalize_verified_value(row.get("detail"))
        row["qualityStatus"] = "verified" if row.get("sourceType") == "verified-performance" else "ai-verified"
        row["valueType"] = "text" if QUALITATIVE_METRIC_RE.search(row.get("metric", "")) else "numeric"
        row["metricCategory"] = _metric_category(row.get("metric", ""))
        row["hasSources"] = bool(row.get("sources"))

    companies = sorted({row["company"] for row in rows if row.get("company")})
    metrics = sorted({row["metric"] for row in rows if row.get("metric")})
    source_types = sorted({row["sourceType"] for row in rows if row.get("sourceType")})
    groups = sorted({row["group"] for row in rows if row.get("group")})
    metric_categories = sorted({row["metricCategory"] for row in rows if row.get("metricCategory")})
    companies_summary = []
    for company in companies:
        company_rows = [row for row in rows if row["company"] == company]
        companies_summary.append(
            {
                "company": company,
                "metricCount": len({row["metric"] for row in company_rows}),
                "recordCount": len(company_rows),
                "sourceCount": len({source["url"] for row in company_rows for source in row.get("sources", [])}),
            }
        )

    ai_cache = _read_json(AI_CACHE_PATH, {})
    accepted_fact_items: list[dict] = []
    if VERIFIED_FACTS_PATH.exists():
        for line in VERIFIED_FACTS_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                fact = json.loads(line)
            except json.JSONDecodeError:
                continue
            if fact.get("status") == "ok" and fact.get("decision") == "accepted":
                accepted_fact_items.append(fact)
    accepted_ai_facts = len(accepted_fact_items)
    published_public_rows = [row for row in rows if row.get("sourceType") == "public-crawl"]
    published_signatures = {
        _fact_publish_signature(row.get("company", ""), row.get("metric", ""), row.get("value", ""))
        for row in published_public_rows
    }
    accepted_publishable_signatures: set[tuple[str, str, str]] = set()
    excluded_out_of_scope = 0
    excluded_non_facts = 0
    deduplicated_ai_facts = 0
    for fact in accepted_fact_items:
        if not all([fact.get("entity_supported"), fact.get("metric_supported"), fact.get("value_supported")]):
            excluded_non_facts += 1
            continue
        company = _normalize_company_name(fact.get("company"))
        if not _is_publishable_company(company):
            excluded_out_of_scope += 1
            continue
        if _verified_fact_publish_issue(fact):
            excluded_non_facts += 1
            continue
        if str(fact.get("company") or "").strip() == "3HK" and fact.get("metric") == "市场反应":
            deduplicated_ai_facts += 1
            continue
        signature = _fact_publish_signature(company, fact.get("metric", ""), fact.get("value", ""))
        if signature in accepted_publishable_signatures:
            deduplicated_ai_facts += 1
            continue
        accepted_publishable_signatures.add(signature)
    suppressed_publishable = len(accepted_publishable_signatures - published_signatures)
    return {
        "generatedAt": _clean_text(
            ai_cache.get("updatedAt")
            or _read_json(FEISHU_CACHE_PATH, {}).get("synced_at", "")
        ),
        "summary": {
            "companies": len(companies),
            "metrics": len(metrics),
            "records": len(rows),
            "verifiedRecords": sum(1 for row in rows if row.get("sourceType") == "verified-performance"),
            "crawlRecords": len(published_public_rows),
            "acceptedAiFacts": accepted_ai_facts,
            "publishableAiFacts": len(accepted_publishable_signatures),
            "publishedAiFacts": len(published_public_rows),
            "aiCleanedRecords": sum(1 for row in rows if row.get("aiCleaned")),
            "qualityPassedRecords": len(rows),
            "suppressedRecords": suppressed_publishable,
            "excludedOutOfScopeFacts": excluded_out_of_scope,
            "excludedNonFacts": excluded_non_facts,
            "deduplicatedAiFacts": deduplicated_ai_facts,
        },
        "companies": companies,
        "metrics": metrics,
        "groups": groups,
        "metricCategories": metric_categories,
        "sourceTypes": source_types,
        "companySummary": companies_summary,
        "rows": rows,
    }
