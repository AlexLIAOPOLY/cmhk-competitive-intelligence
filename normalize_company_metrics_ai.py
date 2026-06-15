from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ai_config import load_ai_config
from network_utils import urlopen_with_local_proxy_fallback
from company_metrics import (
    AI_CACHE_PATH,
    AI_CACHE_SCHEMA_VERSION,
    DIRTY_SOURCE_LABEL_TERMS,
    KNOWN_COMPANY_NAMES,
    QUALITATIVE_METRIC_RE,
    _passes_metric_gate,
    build_company_metrics_payload,
)


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
STAGING_CACHE_PATH = AI_CACHE_PATH.with_name(f"{AI_CACHE_PATH.stem}.staging.json")
VERIFIED_FIELDS_PATH = ROOT / "carrier_performance_verified_fields.json"
VERIFIED_SOURCES_PATH = ROOT / "carrier_performance_sources.json"

DIRTY_PATTERNS = [
    "Skip to main content",
    "Log In Sign Up",
    "Home Watchlist",
    "Stock Screener",
    "Financials & Income Statement",
    "Policy sets out standards",
    "Family Friendly",
    "Search Telstra",
    "Markdown filings API",
    "Attention Required",
    "Cloudflare",
    "Careers Home",
    "Investor Relations Fast Facts",
    "Service Plan Chinese Mainland",
    "Asia Pacific 5G Service Plan",
]

NUMERIC_REQUIRED_RE = re.compile(
    r"派息|股息|分派|资本开支|收入|收益|EBITDA|利润|用户|客户|ARPU|宽频|家宽|5G|套餐|资费|频谱|GDP|CPI|人口|投资",
    re.IGNORECASE,
)

COMPANY_SOURCE_HINTS = {
    "HKT": ["hkt", "pccw"],
    "csl": ["csl", "hkt", "pccw"],
    "1O1O": ["1010", "hkt", "pccw"],
    "3HK": ["three", "hthkh", "hutchison"],
    "Hutchison": ["hutchison", "hthkh", "three"],
    "SmarTone": ["smartone"],
    "HKBN": ["hkbn"],
    "HGC": ["hgc"],
    "iCable": ["i-cable", "i-cablecomm"],
    "i-CABLE": ["i-cable", "i-cablecomm"],
    "Singtel": ["singtel"],
    "Telstra": ["telstra"],
    "SK Telecom": ["sktelecom", "skt"],
    "KT": ["kt.com"],
    "NTT Docomo": ["docomo", "ntt"],
    "KDDI": ["kddi"],
    "SoftBank": ["softbank"],
    "Airtel": ["airtel"],
    "Vodafone": ["vodafone"],
    "Deutsche Telekom": ["deutsche telekom", "telekom"],
    "Orange": ["orange"],
    "Telefonica": ["telefonica", "telefónica"],
    "BT/EE": ["bt group", "ee"],
    "TIM": ["tim group", "gruppotim"],
    "Verizon": ["verizon"],
    "AT&T": ["at&t"],
    "T-Mobile US": ["t-mobile us", "t-mobile"],
    "e&": ["e&", "etisalat"],
    "stc": ["stc group", "stc"],
    "中国移动": ["chinamobile", "china-mobile"],
    "中国电信": ["chinatelecom", "china-telecom"],
    "中国联通": ["chinaunicom", "china-unicom"],
}

OFFICIAL_DOMAIN_OWNERS: dict[str, set[str]] = {
    "chinamobileltd.com": {"中国移动"},
    "chinamobile.com": {"中国移动"},
    "chinatelecom-h.com": {"中国电信"},
    "chinaunicom.com.hk": {"中国联通"},
    "hkt.com": {"HKT"},
    "pccw.com": {"HKT"},
    "hkcsl.com": {"csl"},
    "hkcsl-5g.com": {"csl"},
    "1010.com.hk": {"1O1O"},
    "1010corporate.com": {"1O1O"},
    "netvigator.com": {"HKT"},
    "hkt-enterprise.com": {"HKT"},
    "hthkh.com": {"3HK", "Hutchison"},
    "three.com.hk": {"3HK", "Hutchison"},
    "smartone.com": {"SmarTone"},
    "hkbn.net": {"HKBN"},
    "hgc.com.hk": {"HGC"},
    "i-cablecomm.com": {"iCable", "i-CABLE"},
    "singtel.com": {"Singtel"},
    "telstra.com": {"Telstra"},
    "sktelecom.com": {"SK Telecom"},
    "kt.com": {"KT"},
    "docomo.ne.jp": {"NTT Docomo"},
    "kddi.com": {"KDDI"},
    "softbank.jp": {"SoftBank"},
    "airtel.in": {"Airtel"},
    "vodafone.com": {"Vodafone"},
    "verizon.com": {"Verizon"},
    "telekom.com": {"Deutsche Telekom"},
    "report.telekom.com": {"Deutsche Telekom"},
}

OFFICIAL_URL_OWNER_OVERRIDES = {
    (
        "report.telekom.com",
        "/annual-report-2025/management-report/"
        "development-of-business-in-the-operating-segments/united-states",
    ): {"T-Mobile US"},
}

METRIC_EVIDENCE_TERMS = {
    "派息": ["派息", "股息", "分派", "dividend", "distribution", "per share"],
    "股息": ["派息", "股息", "分派", "dividend", "distribution", "per share"],
    "资本开支": ["资本开支", "capex", "capital expenditure", "capital investment"],
    "收入": ["收入", "收益", "revenue", "turnover"],
    "收益": ["收入", "收益", "revenue", "turnover"],
    "EBITDA": ["EBITDA", "adjusted EBITDA"],
    "利润": ["利润", "溢利", "profit", "earnings", "net income"],
    "用户": ["用户", "客户", "subscriber", "customer", "customer base"],
    "客户": ["用户", "客户", "subscriber", "customer", "customer base"],
    "ARPU": ["ARPU", "average revenue per user"],
    "宽频": ["宽频", "宽带", "broadband", "fixed line"],
    "家宽": ["家宽", "家庭宽带", "home broadband", "fixed broadband"],
    "套餐": ["套餐", "月费", "plan", "tariff", "monthly fee"],
    "资费": ["资费", "月费", "plan", "tariff", "monthly fee"],
    "合约期": ["合约期", "承诺期", "commitment period", "contract period"],
    "促销折扣": [
        "促销",
        "折扣",
        "优惠",
        "礼遇",
        "权益",
        "promotion",
        "discount",
        "welcome offers",
        "rebate",
        "privileges",
    ],
    "董事会": ["董事会", "board", "board of directors", "board has resolved"],
    "股东大会": ["股东大会", "annual general meeting", "AGM", "shareholders"],
    "持续性关联交易": [
        "持续性关联交易",
        "continuing connected transaction",
        "connected persons",
        "Chapter 14A",
    ],
    "漫游": ["漫游", "roaming"],
    "战略": ["战略", "转型", "strategy", "strategic", "transformation"],
    "合作": ["合作", "伙伴", "partner", "partnership", "collaboration"],
    "中标": ["中标", "合同", "contract", "tender", "award"],
    "投资并购": ["投资", "并购", "收购", "investment", "acquisition", "merger"],
    "数据中心": ["数据中心", "data centre", "data center"],
    "DICT": [
        "DICT",
        "产业数字化",
        "industrial digitalisation",
        "industrial digitalization",
        "industry digital intelligence services",
        "digital intelligence e-commerce",
        "strategic emerging industries",
        "computing power business revenue",
    ],
    "企业ICT": [
        "企业ICT",
        "KT AX platform",
        "digital transformation services",
        "Internet data centers and cloud services",
    ],
    "Capex方向": [
        "Capex方向",
        "Expanding 5G and broadband adoption",
        "AirFiber subscribers",
        "Deployment of Private 5G",
        "investing in growth opportunities",
    ],
    "算力网络": [
        "算力网络",
        "算力",
        "intelligent computing",
        "computing power",
        "EFLOPS",
        "cloud pools",
        "backbone optical",
    ],
    "边缘计算": ["边缘计算", "edge computing", "edge cloud"],
    "5G-A": ["5G-A", "5.5G", "5G Advanced", "5G-Advanced"],
    "AI": ["人工智能", "AI", "artificial intelligence", "generative AI"],
    "云": ["云", "cloud"],
    "网络API": ["网络API", "network API", "Open Gateway", "CAMARA"],
    "Open RAN": ["Open RAN", "O-RAN"],
    "FWA": [
        "FWA",
        "fixed wireless",
        "fixed wireless access",
        "5G broadband",
        "High Speed Internet",
    ],
    "市场反应": ["股价", "收盘", "上涨", "下跌", "share price", "closed at", "rating", "target price"],
    "券商观点": ["券商", "分析师", "评级", "目标价", "broker", "analyst", "rating", "target price"],
    "融资": ["融资", "债务", "利息", "finance cost", "financing", "debt"],
    "商誉": ["商誉", "goodwill", "impairment of goodwill"],
    "资产负债率": [
        "资产负债率",
        "gearing",
        "gearing ratio",
        "net debt",
        "net debt to EBITDA",
        "leverage",
    ],
    "人口": ["人口", "population"],
    "GDP": ["GDP", "gross domestic product", "本地生产总值", "国内生产总值"],
    "CPI": ["CPI", "consumer price", "消费物价"],
}


def clean_text(value: object, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip()


def _metric_search_terms(metric: str, company: str) -> list[str]:
    terms = [metric]
    matched_alias = False
    for key, aliases in METRIC_EVIDENCE_TERMS.items():
        if key.lower() in metric.lower() or metric.lower() in key.lower():
            terms.extend(aliases)
            matched_alias = True
    if not matched_alias:
        terms.extend(COMPANY_SOURCE_HINTS.get(company, []))
    return list(dict.fromkeys(term.strip() for term in terms if term and term.strip()))


def _focused_evidence(text: str, metric: str, company: str, limit: int = 6000) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return ""
    matches: list[tuple[int, int]] = []
    lowered = normalized.lower()
    for term in _metric_search_terms(metric, company):
        start = 0
        needle = term.lower()
        term_hits = 0
        while needle and term_hits < 160:
            index = lowered.find(needle, start)
            if index < 0:
                break
            matches.append((max(0, index - 360), min(len(normalized), index + len(term) + 760)))
            start = index + len(needle)
            term_hits += 1
    if not matches:
        return clean_text(normalized, min(limit, 1600))

    def score_window(start: int, end: int) -> tuple[int, int]:
        window = normalized[start:end]
        window_lower = window.lower()
        score = 0
        for term in _metric_search_terms(metric, company):
            count = window_lower.count(term.lower())
            score += min(count, 5) * 5
        if _evidence_mentions_company(window, company):
            score += 8
        if re.search(r"\d", window):
            score += 4
        if re.search(
            r"HK\$|US\$|RMB|港元|亿元|亿|万|million|billion|%|客户|用户|"
            r"subscribers?|customers?|ARPU|EBITDA|CAPEX|EFLOPS|Gbps|MHz",
            window,
            re.IGNORECASE,
        ):
            score += 8
        dirty_hits = sum(window_lower.count(pattern.lower()) for pattern in DIRTY_PATTERNS)
        score -= min(dirty_hits, 8) * 3
        return score, -start

    ranked = sorted(set(matches), key=lambda item: score_window(*item), reverse=True)
    selected: list[tuple[int, int]] = []
    for start, end in ranked:
        if any(max(start, existing_start) < min(end, existing_end) - 240 for existing_start, existing_end in selected):
            continue
        selected.append((start, end))
        if len(selected) >= 12:
            break

    windows: list[str] = []
    total = 0
    for start, end in selected:
        remaining = limit - total
        if remaining <= 0:
            break
        window = normalized[start:end].strip()[:remaining]
        if window:
            windows.append(window)
            total += len(window)
    return "\n...\n".join(windows)


def _record_evidence(record: dict[str, Any], metric: str, company: str) -> str:
    evidence_path = str(record.get("evidence_path") or "").strip()
    full_text = ""
    if evidence_path:
        path = ROOT / evidence_path
        try:
            resolved = path.resolve()
            if resolved.is_file() and ROOT in resolved.parents:
                full_text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            full_text = ""
    if not full_text:
        full_text = str(record.get("text_sample") or "")
    return _focused_evidence(full_text, metric, company)


def _official_domain_owners(url: str) -> set[str]:
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower().split(":", 1)[0]
    path = parsed.path.lower().rstrip("/")
    for (override_host, path_prefix), owners in OFFICIAL_URL_OWNER_OVERRIDES.items():
        if host == override_host and path.startswith(path_prefix):
            return owners
    for domain, owners in sorted(
        OFFICIAL_DOMAIN_OWNERS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if host == domain or host.endswith(f".{domain}"):
            return owners
    return set()


def _record_allowed_for_company(record: dict[str, Any], company: str) -> bool:
    url = str(record.get("final_url") or record.get("url") or "")
    owners = _official_domain_owners(url)
    return not owners or company in owners


def _neutral_record_has_verified_entity(record: dict[str, Any], company: str) -> bool:
    entity_hits = {str(item) for item in record.get("entity_hits") or []}
    if company not in entity_hits:
        return False
    source_url = str(record.get("final_url") or record.get("url") or "")
    return (
        str(record.get("source_type") or "") == "exchange_public_disclosure"
        or not _official_domain_owners(source_url)
    )


def _evidence_mentions_company(text: str, company: str) -> bool:
    lowered = str(text or "").lower()
    aliases = [company, *COMPANY_SOURCE_HINTS.get(company, [])]
    return any(alias and alias.lower() in lowered for alias in aliases)


def _evidence_relevance(text: str, metric: str, company: str) -> int:
    lowered = str(text or "").lower()
    score = sum(lowered.count(term.lower()) for term in _metric_search_terms(metric, company))
    if any(hint.lower() in lowered for hint in COMPANY_SOURCE_HINTS.get(company, [])):
        score += 1
    if re.search(r"\d", lowered):
        score += 2
    if re.search(r"HK\$|US\$|RMB|港元|亿元|million|billion|%|客户|用户|subscriber|customer", lowered, re.I):
        score += 3
    return score


def needs_ai(row: dict[str, Any]) -> bool:
    # All public-crawl facts must pass the same extraction and quality gates.
    # Keeping this explicit avoids the previous unreachable heuristic block.
    return row.get("sourceType") == "public-crawl"


def entity_supported_offline(task: dict[str, Any]) -> bool:
    company = str(task.get("company") or "")
    if company not in KNOWN_COMPANY_NAMES:
        return True
    sources = [str(url) for url in task.get("sources") or []]
    owned_sources = [owners for url in sources if (owners := _official_domain_owners(url))]
    if owned_sources and not any(company in owners for owners in owned_sources):
        return False
    haystack = f"{task.get('raw_text', '')} {' '.join(sources)}".lower()
    hints = COMPANY_SOURCE_HINTS.get(company, [company.lower()])
    if any(hint.lower() in haystack for hint in hints):
        return True
    return company.lower() in haystack


def _looks_like_complete_qualitative_value(value: str, task: dict[str, Any]) -> bool:
    text = clean_text(value, 260)
    if not text:
        return False
    if any(pattern.lower() in text.lower() for pattern in DIRTY_PATTERNS):
        return False
    if re.search(r"\s\|\s|suggestions found|\b\d+/\d+\b|Skip to|Log In|Search Close", text, re.IGNORECASE):
        return False
    if re.match(r"^[a-z]{2,}[,;:\s-]", text):
        return False
    if re.match(r"^[a-z]{2,}\s+[A-Z]", text):
        return False
    # English qualitative snippets without Chinese punctuation are only accepted
    # when they explicitly mention the company or the metric keyword; otherwise
    # they are usually mid-page fragments cut out by snippet extraction.
    if not re.search(r"[\u4e00-\u9fff]", text):
        company = str(task.get("company") or "").lower()
        metric = str(task.get("metric") or "").lower()
        haystack = text.lower()
        metric_terms = [term for term in re.split(r"[\s/|、，,]+", metric) if len(term) >= 2]
        company_terms = [term for term in COMPANY_SOURCE_HINTS.get(str(task.get("company") or ""), []) if len(term) >= 2]
        if company and company not in haystack and not any(term in haystack for term in company_terms + metric_terms):
            return False
    return True


def fallback_clean_task(task: dict[str, Any]) -> dict[str, Any]:
    metric = str(task.get("metric") or "")
    value = clean_text(task.get("current_value"), 220)
    raw = clean_text(task.get("raw_text"), 1200)
    entity_ok = entity_supported_offline(task)
    dirty = any(pattern.lower() in f"{value} {raw}".lower() for pattern in DIRTY_SOURCE_LABEL_TERMS)
    metric_ok = metric not in KNOWN_COMPANY_NAMES and not dirty
    if str(task.get("company")) in {"csl", "1O1O"} and re.search(
        r"收入|收益|EBITDA|利润|资本开支|派息|用户数|ARPU", metric, re.IGNORECASE
    ):
        metric_ok = False
    if re.search(r"运营收入/总收益", metric) and re.search(r"服务收入|service revenue", raw, re.IGNORECASE):
        metric_ok = False
    if re.search(r"资费", metric) and re.search(r"屏幕|更换|消费赚|reward", raw, re.IGNORECASE):
        metric_ok = False
    if re.search(r"World Bank|IMF|GDP|CPI", metric, re.IGNORECASE) and re.search(r"\d+\s*(?:条|records?)", value, re.IGNORECASE):
        metric_ok = False
    if QUALITATIVE_METRIC_RE.search(metric):
        value_ok = bool(value) and not dirty and len(value) <= 220 and _looks_like_complete_qualitative_value(value, task)
    else:
        value_ok = _passes_metric_gate(metric, value)
    status = "ok" if entity_ok and metric_ok and value_ok else "unavailable"
    return {
        "id": task["id"],
        "status": status,
        "value": value if status == "ok" else "未提取到有效数据",
        "basis": raw[:600] if status == "ok" else "本地严格校验未能确认公司归属、指标语义或数值依据。",
        "note": "AI不可用，本地严格校验兜底。",
        "entity_supported": entity_ok,
        "metric_supported": metric_ok,
        "value_supported": value_ok,
        "confidence": 0.82 if status == "ok" else 0.0,
    }


def fallback_clean_batch(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [fallback_clean_task(task) for task in tasks]


def _load_json_dict(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _verified_company_group(company: str) -> str:
    if company == "HKT":
        return "HKT / csl / 1O1O"
    if company in {"3HK", "Hutchison"}:
        return "3HK / Hutchison"
    if company in {"iCable", "i-CABLE"}:
        return "i-CABLE"
    return company


def _verified_field_key(metric: str) -> str:
    if re.search(r"派息|股息|分派", metric, re.IGNORECASE):
        return "dividend"
    if re.search(r"资本开支|capex", metric, re.IGNORECASE):
        return "capex"
    if metric == "战略升级":
        return "strategy"
    if metric == "券商观点":
        return "broker"
    if metric == "市场反应":
        return "market"
    return ""


def _verified_metric_context(company: str, metric: str) -> tuple[str, list[str]]:
    group = _verified_company_group(company)
    key = _verified_field_key(metric)
    if not key:
        return "", []
    # csl and 1O1O are brands rather than separately listed issuers. Group
    # financial disclosures must not silently become brand-level facts.
    if company in {"csl", "1O1O"}:
        return "", []
    fields = _load_json_dict(VERIFIED_FIELDS_PATH)
    sources_data = _load_json_dict(VERIFIED_SOURCES_PATH)
    company_data = ((sources_data.get("companies") or {}).get(group) or {})
    value = str((fields.get(group) or {}).get(key) or "").strip()
    if not value:
        value = str((company_data.get("fields") or {}).get(key) or "").strip()
    urls = [
        str(item.get("url") or "").strip()
        for item in company_data.get("sources") or []
        if isinstance(item, dict) and str(item.get("url") or "").strip()
    ]
    return value, list(dict.fromkeys(urls))


def _deterministic_result(task: dict[str, Any], value: str, basis: str, note: str) -> dict[str, Any]:
    return {
        "id": task["id"],
        "status": "ok",
        "value": clean_text(value, 220),
        "basis": clean_text(basis, 600),
        "note": clean_text(note, 160),
        "entity_supported": True,
        "metric_supported": True,
        "value_supported": True,
        "confidence": 0.96,
    }


def _millions_to_ten_thousands(value: str) -> str:
    number = float(value) * 100
    return f"{number:.1f}".rstrip("0").rstrip(".")


def _thousands_to_ten_thousands(value: str) -> str:
    number = float(value.replace(",", "")) / 10
    return f"{number:.1f}".rstrip("0").rstrip(".")


def deterministic_extract_task(task: dict[str, Any]) -> dict[str, Any] | None:
    company = str(task.get("company") or "")
    metric = str(task.get("metric") or "")
    text = str(task.get("raw_text") or "")

    if metric == "市场反应" and company in {"csl", "1O1O", "3HK"}:
        return _deterministic_result(
            task,
            "不适用（品牌非独立上市主体）",
            f"{company}为品牌口径，不存在独立上市股票交易表现。",
            "依据主体上市口径确定",
        )
    if company == "HGC" and metric in {"派息", "券商观点", "市场反应"}:
        return _deterministic_result(
            task,
            "不适用（非上市主体）",
            "HGC为非上市主体，不存在独立公开派息、券商评级或股票交易口径。",
            "依据主体上市状态确定",
        )

    verified_value, _urls = _verified_metric_context(company, metric)
    if verified_value and (
        metric == "市场反应"
        or (company == "HGC" and metric in {"资本开支", "战略升级"})
        or (company in {"中国移动", "中国电信", "中国联通"} and metric == "资本开支")
    ):
        return _deterministic_result(
            task,
            verified_value,
            verified_value,
            "采用已核验公开来源字段",
        )

    if company == "中国移动" and metric == "AI":
        capex, _ = _verified_metric_context(company, "资本开支")
        strategy_data = _load_json_dict(VERIFIED_SOURCES_PATH)
        strategy = str(
            (
                (
                    (strategy_data.get("companies") or {}).get(company) or {}
                ).get("fields")
                or {}
            ).get("strategy")
            or ""
        )
        if "AI网络投资增长19.8%" in capex and "AI服务" in strategy:
            value = "AI网络投资同比增长19.8%；战略向通信服务、算力服务、AI服务协同推进"
            return _deterministic_result(
                task,
                value,
                f"{capex} {strategy}",
                "采用已核验年度业绩字段",
            )

    if company == "中国移动" and metric == "算力网络":
        capex, _ = _verified_metric_context(company, "资本开支")
        if "算力网络投资增长62.4%" in capex:
            return _deterministic_result(
                task,
                "算力网络投资同比增长62.4%",
                capex,
                "采用已核验年度业绩字段",
            )

    if company == "中国移动" and metric == "DICT" and re.search(
        r"AI services include data algorithms.{0,260}?industry digital intelligence services",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        value = "AI服务覆盖数据算法、具身智能、数智文娱、数智电商及行业数智服务"
        return _deterministic_result(
            task,
            value,
            (
                "AI services include data algorithms, embodied intelligence, "
                "digital intelligence culture, digital intelligence e-commerce "
                "and industry digital intelligence services."
            ),
            "从中国移动2025年年报业务口径精确提取",
        )

    if company == "中国电信" and metric == "算力网络":
        capex, _ = _verified_metric_context(company, "资本开支")
        if "资本开支804亿元" in capex and "AIDC" in capex:
            return _deterministic_result(
                task,
                "2025年资本开支804亿元，持续投入AIDC、算力和AI基础设施",
                capex,
                "采用已核验年度业绩字段",
            )

    if company == "中国电信" and metric == "5G-A":
        base_stations = re.search(
            r"over\s+([0-9,]+)\s+5G-A carrier.{0,100}?aggregation base stations",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        cities = re.search(
            r"RedCap.{0,100}?base stations in more than\s+([0-9,]+)\s+cities",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if base_stations and cities:
            value = (
                f"部署超过{base_stations.group(1)}个5G-A载波聚合基站，"
                f"覆盖超过{cities.group(1)}个城市"
            )
            return _deterministic_result(
                task,
                value,
                f"{base_stations.group(0)}；{cities.group(0)}",
                "从中国电信2025年报精确提取",
            )

    if company == "中国联通" and metric == "算力网络":
        computing = re.search(
            r"intelligent computing reached\s+([0-9.]+)\s+EFLOPS",
            text,
            re.IGNORECASE,
        )
        cloud_pools = re.search(
            r"cloud pools covering\s+([0-9,]+)\s+cities",
            text,
            re.IGNORECASE,
        )
        fibre = re.search(
            r"adding more than\s+([0-9,]+)\s+kilometres"
            r"[^.]{0,180}?computing power hub nodes",
            text,
            re.IGNORECASE,
        )
        if computing and cloud_pools:
            value = (
                f"智能算力规模{computing.group(1)} EFLOPS；"
                f"骨干云池覆盖{cloud_pools.group(1)}个城市"
            )
            if fibre:
                value += f"；新增骨干光缆超过{fibre.group(1)}公里"
            return _deterministic_result(
                task,
                value,
                " ".join(item.group(0) for item in (computing, cloud_pools, fibre) if item),
                "从中国联通2025年报精确提取",
            )

    if company == "中国联通" and metric == "AI":
        ai_revenue = re.search(
            r"AI revenue\d*\s+grew by over\s+([0-9.]+)%\s+year-on-year",
            text,
            re.IGNORECASE,
        )
        cloud_ai = re.search(
            r"cloud-AI products[^.]{0,120}?served over\s+([0-9.]+)\s+million users"
            r"[^.]{0,120}?revenue increasing by more than\s+([0-9.]+)%",
            text,
            re.IGNORECASE,
        )
        if ai_revenue or cloud_ai:
            values = []
            if ai_revenue:
                values.append(f"AI收入同比增长超过{ai_revenue.group(1)}%")
            if cloud_ai:
                values.append(
                    f"云智产品服务用户超过{cloud_ai.group(1)}百万，"
                    f"收入同比增长超过{cloud_ai.group(2)}%"
                )
            return _deterministic_result(
                task,
                "；".join(values),
                " ".join(item.group(0) for item in (ai_revenue, cloud_ai) if item),
                "从中国联通2025年报精确提取",
            )

    if company == "中国联通" and metric == "5G-A":
        cities = re.search(
            r"5G-A base stations were deployed in more than\s+([0-9,]+)\s+cities",
            text,
            re.IGNORECASE,
        )
        if cities:
            value = f"5G-A基站已部署至超过{cities.group(1)}个城市"
            return _deterministic_result(
                task,
                value,
                cities.group(0),
                "从中国联通2025年报精确提取",
            )

    if company == "中国电信" and metric == "DICT":
        industrial_table = re.search(
            r"Industrial Digitalisation service revenues\s+"
            r"([0-9,]+)\s+[0-9,]+\s+([0-9.]+)%",
            text,
            re.IGNORECASE,
        )
        industrial_narrative = re.search(
            r"revenue from Industrial Digitalisation business\s+"
            r"(?:rea\s*ched|reached)\s+R\s*M\s*B\s*([0-9,]+)\s*"
            r"(million|billion)[^.]{0,100}?(?:increase|growth) of\s*([0-9.]+)%",
            text,
            re.IGNORECASE,
        )
        if industrial_table:
            revenue_yi = float(industrial_table.group(1).replace(",", "")) / 100
            revenue_text = f"{revenue_yi:.2f}".rstrip("0").rstrip(".")
            value = (
                f"2025年产业数字化业务收入{revenue_text}亿元，"
                f"同比增长{industrial_table.group(2)}%"
            )
            return _deterministic_result(
                task,
                value,
                industrial_table.group(0),
                "从中国电信2025年报精确提取",
            )
        if industrial_narrative:
            revenue = float(industrial_narrative.group(1).replace(",", ""))
            if industrial_narrative.group(2).lower() == "billion":
                revenue *= 10
            else:
                revenue /= 100
            revenue_text = f"{revenue:.2f}".rstrip("0").rstrip(".")
            value = (
                f"2025年产业数字化业务收入{revenue_text}亿元，"
                f"同比增长{industrial_narrative.group(3)}%"
            )
            return _deterministic_result(
                task,
                value,
                industrial_narrative.group(0),
                "从中国电信2025年报精确提取",
            )

    if company == "中国联通" and metric == "DICT":
        emerging = re.search(
            r"Revenue contribution from strategic emerging industries reached over\s+"
            r"([0-9.]+)%",
            text,
            re.IGNORECASE,
        )
        computing = re.search(
            r"computing power business revenue\d*\s+ratio reached over\s+([0-9.]+)%",
            text,
            re.IGNORECASE,
        )
        ai_revenue = re.search(
            r"AI revenue\d*\s+grew by over\s+([0-9.]+)%\s+year-on-year",
            text,
            re.IGNORECASE,
        )
        if emerging and computing and ai_revenue:
            value = (
                f"战略性新兴产业收入占比超过{emerging.group(1)}%；"
                f"算力业务收入占比超过{computing.group(1)}%；"
                f"AI收入同比增长超过{ai_revenue.group(1)}%"
            )
            return _deterministic_result(
                task,
                value,
                "；".join(item.group(0) for item in (emerging, computing, ai_revenue)),
                "从中国联通2025年报精确提取",
            )

    if company == "HKT" and metric == "客户数/用户数":
        postpaid = re.search(
            r"Post-?Paid Customer Base\s+([0-9.]+)\s*M",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"post-?paid customer base[^.]{0,80}?reach(?:ed)?\s+([0-9.]+)\s+million",
            text,
            re.IGNORECASE,
        )
        five_g = re.search(
            r"5G Customer Base\s+([0-9.]+)\s*M",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"5G customer base[^.]{0,80}?reach(?:ed|ing)?\s+([0-9.]+)\s+million",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"(?:5G\s+cus)?tomer base reaching\s+([0-9.]+)\s+million"
            r"[^.]{0,80}?increase of\s+25%",
            text,
            re.IGNORECASE,
        )
        if postpaid and five_g:
            value = (
                f"后付费客户{_millions_to_ten_thousands(postpaid.group(1))}万；"
                f"5G客户{_millions_to_ten_thousands(five_g.group(1))}万"
            )
            return _deterministic_result(task, value, value, "从HKT年报结构化指标精确提取")

    if company == "HKT" and metric == "5G用户数":
        five_g = re.search(
            r"5G Customer Base\s+([0-9.]+)\s*M",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"(?:5G\s+cus)?tomer base reaching\s+([0-9.]+)\s+million"
            r"[^.]{0,80}?increase of\s+25%",
            text,
            re.IGNORECASE,
        )
        if five_g:
            value = f"5G客户{_millions_to_ten_thousands(five_g.group(1))}万"
            return _deterministic_result(task, value, value, "从HKT年报结构化指标精确提取")

    if company == "HKT" and metric == "宽频线数/家宽用户数":
        ftth = re.search(
            r"FTTH Connections\s+([0-9.]+)\s*M",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"FTTH connections[^.]{0,60}?(?:total|reaching)\s+([0-9.]+)\s+million",
            text,
            re.IGNORECASE,
        )
        consumer = re.search(
            r"consumer broadband base(?:\s+of)?\s+([0-9.]+)\s*million",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"Retail consumer broadband access lines\s*\(['’]?000\)"
            r"(?:\s+[0-9,]+){3}\s+([0-9,]+)",
            text,
            re.IGNORECASE,
        )
        if ftth and consumer:
            consumer_value = consumer.group(1)
            if "," in consumer_value:
                consumer_value = f"{_thousands_to_ten_thousands(consumer_value)}万"
            else:
                consumer_value = f"{_millions_to_ten_thousands(consumer_value)}万"
            value = (
                f"FTTH连接{_millions_to_ten_thousands(ftth.group(1))}万；"
                f"消费宽频用户{consumer_value}"
            )
            return _deterministic_result(task, value, value, "从HKT年报结构化指标精确提取")

    if company == "HKT" and metric == "家宽套餐":
        plan = re.search(
            r"(1000M[^。；\n]{0,180}?(?:HK\$|港币|港元)\s*108\s*/?\s*(?:月|month))",
            text,
            re.IGNORECASE,
        )
        if plan:
            return _deterministic_result(
                task,
                "1000M光纤入屋宽频连家居Wi-Fi低至每月108港元",
                plan.group(1),
                "从HKT旗下NETVIGATOR官方套餐页精确提取",
            )
        if re.search(r"Choose from 1G to 10G", text, re.IGNORECASE):
            return _deterministic_result(
                task,
                "HKT旗下NETVIGATOR家宽用户可选1G至10G光纤入屋产品",
                "Choose from 1G to 10G",
                "从HKT旗下NETVIGATOR官方产品页精确提取",
            )

    if company == "HKT" and metric == "资费":
        one_g = re.search(
            r"1000M\s*(?:Fibre-to-the-Home|光纖入屋寬頻)"
            r"[^.。]{0,120}?(?:From|低至)\s*HK\$\s*108\s*/(?:month|月)"
            r"[^.。]{0,80}?36\s*(?:-?\s*month commitment|個月承諾期)",
            text,
            re.IGNORECASE,
        )
        home_5g = re.search(
            r"5G\s*(?:Home Internet|私家寬頻服務)\s+"
            r"(?:From|低至)\s*HK\$\s*168\s*/(?:month|月)"
            r"[^.。]{0,80}?36\s*(?:-?\s*month commitment|個月承諾期)",
            text,
            re.IGNORECASE,
        )
        if one_g and home_5g:
            value = (
                "NETVIGATOR 1000M光纤家宽月费低至108港元，"
                "5G家居宽频月费低至168港元，均为36个月合约"
            )
            return _deterministic_result(
                task,
                value,
                f"{one_g.group(0)}；{home_5g.group(0)}",
                "从HKT旗下NETVIGATOR官方套餐页精确提取",
            )

    if company == "HKT" and metric == "产品规格" and re.search(
        r"Choose from 1G to 10G|10,000M Fibre-to-the-Home|"
        r"1000M Fibre-to-the-Home.{0,100}?HK\$\s*108|"
        r"提供\s*1G\s*至\s*10G的選擇|10,000M\s*光纖入屋寬頻",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        value = "HKT旗下NETVIGATOR提供1000M及10,000M光纤入屋产品，家宽速度选择覆盖1G至10G"
        return _deterministic_result(
            task,
            value,
            "1000M Fibre-to-the-Home；Choose from 1G to 10G；10,000M Fibre-to-the-Home",
            "从HKT旗下NETVIGATOR官方产品页精确提取",
        )

    if company == "HKT" and metric == "5G套餐":
        home_5g = re.search(
            r"5G\s*(?:Home Internet|私家寬頻服務)\s+"
            r"(?:From|低至)\s*HK\$\s*168\s*/(?:month|月)"
            r"[^.。]{0,80}?36\s*(?:-?\s*month commitment|個月承諾期)",
            text,
            re.IGNORECASE,
        )
        if home_5g:
            return _deterministic_result(
                task,
                "HKT旗下NETVIGATOR 5G家居宽频月费低至168港元，合约期36个月",
                home_5g.group(0),
                "从HKT旗下NETVIGATOR官方5G家宽套餐精确提取",
            )

    if company == "HKT" and metric == "合约期":
        commitments = re.findall(
            r"36\s*(?:-?\s*month commitment|個月承諾期)",
            text,
            re.IGNORECASE,
        )
        if len(commitments) >= 2 and re.search(r"1000M|5G\s*私家寬頻", text, re.IGNORECASE):
            return _deterministic_result(
                task,
                "NETVIGATOR 1000M光纤家宽及5G家居宽频优惠均采用36个月合约期",
                "；".join(commitments[:3]),
                "从HKT旗下NETVIGATOR官方套餐页精确提取",
            )

    if company == "HKT" and metric == "促销折扣":
        if (
            re.search(r"1000M[^.。]{0,120}?低至\s*HK\$\s*108\s*/月", text, re.IGNORECASE)
            and re.search(r"2500M[^.。]{0,120}?低至\s*HK\$\s*58\s*/月", text, re.IGNORECASE)
        ):
            return _deterministic_result(
                task,
                "NETVIGATOR新客优惠包括1000M光纤家宽低至每月108港元、2500M超级宽频升级低至每月58港元",
                "1000M低至HK$108/月；2500M升级低至HK$58/月",
                "从HKT旗下NETVIGATOR官方优惠页精确提取",
            )

    if company == "HKT" and metric == "增值服务":
        services = [
            label
            for label in (
                "Home Wi-Fi",
                "Google Workspace with Gemini",
                "NETVIGATOR SHiELD",
                "Cyber Security Service",
                "Surfshark ONE",
                "Gamer Pack",
                "Microsoft 365",
                "Now TV",
            )
            if label.lower() in text.lower()
        ]
        if len(services) >= 3:
            value = "NETVIGATOR增值服务包括" + "、".join(services)
            return _deterministic_result(
                task,
                value,
                "；".join(services),
                "从HKT旗下NETVIGATOR官方服务清单精确提取",
            )

    if company == "csl" and metric == "产品规格" and re.search(
        r"5G Home internet service plan",
        text,
        re.IGNORECASE,
    ):
        value = "csl产品线包括5G家居宽频、5G多用户及中港澳5G服务计划"
        return _deterministic_result(
            task,
            value,
            "5G Home internet service plan；5G Multi-User Service Plan；"
            "Chinese Mainland-Hong Kong-Macao 5G service plan",
            "从csl官方服务计划清单精确提取",
        )

    if company == "csl" and metric == "资费":
        entitlements = re.search(
            r"local data entitlement\s+(60GB/100GB/150GB/250GB/500GB)",
            text,
            re.IGNORECASE,
        )
        admin_fee = re.search(
            r"monthly administrative fee of HKD\s*([0-9.]+)",
            text,
            re.IGNORECASE,
        )
        if entitlements and admin_fee:
            value = (
                f"csl 5G计划本地数据量包括{entitlements.group(1)}；"
                f"月费计划另收每月{admin_fee.group(1)}港元行政费"
            )
            return _deterministic_result(
                task,
                value,
                f"{entitlements.group(0)}；{admin_fee.group(0)}",
                "从csl官方5G计划条款精确提取",
            )

    if company == "csl" and metric == "5G套餐":
        plan_100 = re.search(
            r"Monthly Plan Fee[^$]{0,20}\$348[^.]{0,100}?Local data usage.{0,40}?100GB",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        plan_150 = re.search(
            r"Monthly Plan Fee[^$]{0,20}\$398[^.]{0,100}?Local data usage.{0,40}?150GB",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if plan_100 and plan_150:
            return _deterministic_result(
                task,
                "csl 5G月费计划包括348港元100GB及398港元150GB本地数据方案",
                f"{plan_100.group(0)}；{plan_150.group(0)}",
                "从csl官方5G套餐页精确提取",
            )

    if company == "csl" and metric == "合约期":
        commitment = re.search(
            r"commitment period of 24 or 36 months",
            text,
            re.IGNORECASE,
        )
        if commitment:
            return _deterministic_result(
                task,
                "csl指定5G月费计划合约期为24个月或36个月",
                commitment.group(0),
                "从csl官方5G套餐条款精确提取",
            )

    if company == "csl" and metric == "促销折扣":
        welcome = re.search(
            r"Enjoy welcome offers worth over \$2,000",
            text,
            re.IGNORECASE,
        )
        if welcome:
            return _deterministic_result(
                task,
                "csl指定服务计划提供价值超过2,000港元的迎新优惠",
                welcome.group(0),
                "从csl官方网站优惠说明精确提取",
            )

    if company == "csl" and metric == "家宽套餐" and re.search(
        r"5G Home internet service plan",
        text,
        re.IGNORECASE,
    ):
        return _deterministic_result(
            task,
            "csl官方列有5G家居宽频服务计划",
            "5G Home internet service plan",
            "从csl官方服务计划清单精确提取",
        )

    if company == "csl" and metric == "增值服务":
        services = [
            label
            for label in (
                "csl Wi-Fi",
                "csl Direct Carrier Billing",
                "HKT AR Lens",
                "Blacknut Cloud Gaming",
                "Surfshark ONE",
                "Norton 360",
            )
            if label.lower() in text.lower()
        ]
        if len(services) >= 3:
            value = "csl增值服务包括" + "、".join(services)
            return _deterministic_result(
                task,
                value,
                "；".join(services),
                "从csl官方增值服务清单精确提取",
            )

    if company == "csl" and metric == "漫游" and re.search(
        r"Golden Roaming",
        text,
        re.IGNORECASE,
    ):
        value = "csl漫游服务包括Golden Roaming、数据漫游通行证、机上及邮轮漫游"
        return _deterministic_result(
            task,
            value,
            "Golden Roaming；Data Roaming Pass；First In-Flight Data Roaming Pass；"
            "First Cruise Data Roaming Pass",
            "从csl官方漫游服务清单精确提取",
        )

    if company == "1O1O" and metric == "产品规格" and re.search(
        r"Enterprise 5G/5\.5G & Wireless Solutions",
        text,
        re.IGNORECASE,
    ):
        value = "1O1O企业产品包括5G/5.5G无线方案、5G专网及办公室和工业5G路由器"
        return _deterministic_result(
            task,
            value,
            "Enterprise 5G/5.5G & Wireless Solutions；5G Private Network；"
            "Office 5G Router；Industrial 5G Router",
            "从1O1O企业官方方案页精确提取",
        )
    if company == "1O1O" and metric == "产品规格" and re.search(
        r"provides Open API services on the 1O1O 5G mobile network",
        text,
        re.IGNORECASE,
    ):
        value = "1O1O 5G移动网络提供Open API服务，支持企业移动号码验证等应用"
        return _deterministic_result(
            task,
            value,
            "provides Open API services on the 1O1O 5G mobile network；"
            "modernise mobile-number verification",
            "从1O1O企业官方网站Open API介绍精确提取",
        )

    if company == "1O1O" and metric == "5G套餐" and all(
        label.lower() in text.lower()
        for label in (
            "Global 5G Prestige Service",
            "Asia Pacific 5G Prestige Service",
            "China-HK-Macau 5G Prestige Service",
        )
    ):
        value = "1O1O 5G Prestige套餐包括全球、亚太及中港澳服务方案"
        return _deterministic_result(
            task,
            value,
            "Global 5G Prestige Service；Asia Pacific 5G Prestige Service；"
            "China-HK-Macau 5G Prestige Service",
            "从1O1O官方网站套餐清单精确提取",
        )

    if company == "1O1O" and metric == "增值服务":
        services = [
            label
            for label in (
                "MOOV",
                "HKT AR Lens",
                "csl Wi-Fi",
                "Netflix",
                "Now Player",
                "Viu Premium",
                "1O1O Direct Carrier Billing",
            )
            if label.lower() in text.lower()
        ]
        if len(services) >= 3:
            value = "1O1O增值服务包括" + "、".join(services)
            return _deterministic_result(
                task,
                value,
                "；".join(services),
                "从1O1O官方增值服务清单精确提取",
            )

    if company == "1O1O" and metric == "漫游" and re.search(
        r"Golden Roaming",
        text,
        re.IGNORECASE,
    ):
        value = "1O1O漫游服务包括Golden Roaming、中港一卡两号、数据及机上邮轮漫游"
        return _deterministic_result(
            task,
            value,
            "Golden Roaming；1O1O China HK 1-Card-2-Number；Data Roaming Pass；"
            "First In-Flight Data Roaming Pass；First Cruise Roaming Day Pass",
            "从1O1O官方漫游服务清单精确提取",
        )

    if company == "1O1O" and metric == "战略合作" and re.search(
        r"Open APIs Powering Hong Kong.s Digital Innovation",
        text,
        re.IGNORECASE,
    ):
        value = "1O1O企业网站于2025年9月发布HKT Open API方案，支持企业数字化及跨行业协作"
        return _deterministic_result(
            task,
            value,
            "22 SEP 2025 HKT Enterprise Solutions: Open APIs Powering Hong Kong’s "
            "Digital Innovation and Enterprise Efficiency",
            "从1O1O企业官方网站新闻条目精确提取",
        )

    if company == "1O1O" and metric == "5G-A" and re.search(
        r"Enterprise 5G/5\.5G & Wireless Solutions",
        text,
        re.IGNORECASE,
    ):
        value = "1O1O企业方案已提供5G/5.5G无线方案、5G专网及管理式5G路由器"
        return _deterministic_result(
            task,
            value,
            "Enterprise 5G/5.5G & Wireless Solutions；5G Private Network；"
            "Managed 5G Router Solutions",
            "从1O1O企业官方方案页精确提取",
        )

    if company in {"3HK", "Hutchison"} and metric == "客户数/用户数":
        postpaid = re.search(
            r"Number of postpaid customers\s*\(‘?000\)?\s*([0-9,]+)",
            text,
            re.IGNORECASE,
        )
        prepaid = re.search(
            r"Number of prepaid customers\s*\(‘?000\)?\s*([0-9,]+)",
            text,
            re.IGNORECASE,
        )
        total = re.search(
            r"Total customers\s*\(‘?000\)?\s*([0-9,]+)",
            text,
            re.IGNORECASE,
        )
        if postpaid and prepaid and total:
            value = (
                f"后付费客户{_thousands_to_ten_thousands(postpaid.group(1))}万；"
                f"预付费客户{_thousands_to_ten_thousands(prepaid.group(1))}万；"
                f"客户总数{_thousands_to_ten_thousands(total.group(1))}万"
            )
            return _deterministic_result(task, value, value, "从和记电讯香港年报客户表精确提取")

    if company in {"3HK", "Hutchison"} and metric == "5G用户数":
        penetration = re.search(
            r"5G penetration rate[^.。]{0,100}?(?:to|reached|at)\s+(\d+(?:\.\d+)?)%",
            text,
            re.IGNORECASE,
        )
        if penetration:
            value = f"5G渗透率{penetration.group(1)}%"
            return _deterministic_result(task, value, value, "年报仅披露5G渗透率，未披露绝对用户数")

    if company in {"3HK", "Hutchison"} and metric == "ARPU":
        gross = re.search(
            r"Postpaid gross ARPU\s*\(HK\$\)\s*([0-9.]+)\s+([0-9.]+)\s+"
            r"([–—-]?[0-9.]+%)",
            text,
            re.IGNORECASE,
        )
        net = re.search(
            r"Postpaid net ARPU\s*\(HK\$\)\s*([0-9.]+)\s+([0-9.]+)\s+"
            r"([+–—-]?[0-9.]+%)",
            text,
            re.IGNORECASE,
        )
        if gross and net:
            value = (
                f"后付费毛ARPU每月{gross.group(1)}港元，同比{gross.group(3)}；"
                f"后付费净ARPU每月{net.group(1)}港元，同比{net.group(3)}"
            )
            return _deterministic_result(
                task,
                value,
                f"{gross.group(0)}；{net.group(0)}",
                "从港交所披露的和记电讯香港年度报告精确提取",
            )

    if company == "3HK" and metric == "促销折扣":
        plan = re.search(
            r"\$188\s*/month.{0,100}?Local Data\s+60GB",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        referral = re.search(
            r"MoneyBack points worth \$400.{0,300}?cash discounts",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if plan and referral:
            value = "3HK月费188港元计划含60GB本地数据；成功推荐可获价值400港元MoneyBack积分"
            return _deterministic_result(
                task,
                value,
                f"{plan.group(0)}；{referral.group(0)}",
                "从3HK官方套餐页精确提取",
            )

    if company == "Hutchison" and metric == "促销折扣":
        privilege = re.search(
            r"3 for You.{0,180}?Backup Phone Service and 100\+ Global Privileges",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if privilege:
            value = "HTHKH推出“3 for You”品牌权益，提供备用手机服务及100多项全球礼遇"
            return _deterministic_result(
                task,
                value,
                privilege.group(0),
                "从和记电讯香港官方新闻列表精确提取",
            )

    if company == "HKBN" and metric == "董事会":
        dividend = re.search(
            r"Board has resolved to declare a final dividend of\s+"
            r"([0-9.]+)\s+cents per share",
            text,
            re.IGNORECASE,
        )
        if dividend:
            value = f"董事会决议宣派2025财年末期股息每股{dividend.group(1)}港仙"
            return _deterministic_result(
                task,
                value,
                dividend.group(0),
                "从HKBN官方2025财年业绩公告精确提取",
            )

    if company == "HKBN" and metric == "股东大会":
        agm = re.search(
            r"Subject to the approval by the Shareholders at the 2025 annual general meeting"
            r".{0,220}?paid in cash on or around Tuesday,\s*6 January 2026",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if agm:
            value = "2025财年末期股息须经2025年股东周年大会批准，预计于2026年1月6日前后现金派付"
            return _deterministic_result(
                task,
                value,
                agm.group(0),
                "从HKBN官方2025年年报精确提取",
            )

    if company == "HKBN" and metric == "持续性关联交易":
        ratio = re.search(
            r"all applicable ratios were less than 5%",
            text,
            re.IGNORECASE,
        )
        announcement = re.search(
            r"announcement was made by the Company on 30 October 2025.{0,160}?"
            r"Partially-exempt CCTs",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        connected_person = re.search(
            r"China Mobile Group.{0,80}?became connected persons",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if ratio and announcement and connected_person:
            value = (
                "中国移动集团自2025年5月7日起成为HKBN关联人士；"
                "部分获豁免持续性关联交易于2025年10月30日公告，适用百分比率低于5%"
            )
            return _deterministic_result(
                task,
                value,
                f"{connected_person.group(0)}；{announcement.group(0)}；{ratio.group(0)}",
                "从HKBN官方2025年年报精确提取",
            )

    if company == "SmarTone" and metric == "5G用户数":
        penetration = re.search(
            r"5G penetration at about\s+([0-9.]+)%",
            text,
            re.IGNORECASE,
        )
        if penetration:
            value = f"5G渗透率约{penetration.group(1)}%（公司未披露绝对用户数）"
            return _deterministic_result(
                task,
                value,
                penetration.group(0),
                "从SmarTone业绩材料精确提取5G渗透率",
            )

    if company == "SmarTone" and metric == "家宽":
        home_plan = re.search(
            r"SmarTone Home 5G Broadband[^.]{0,120}?Free Upgrade to Wi-Fi 7"
            r"[^.]{0,80}?12-month Flexible Short Contract",
            text,
            re.IGNORECASE,
        )
        if home_plan:
            value = "SmarTone家宽用户可选Home 5G Broadband，免费升级Wi-Fi 7及12个月灵活短合约"
            return _deterministic_result(
                task,
                value,
                home_plan.group(0),
                "从SmarTone官方网站家宽产品页精确提取",
            )

    if company == "通信监管机构" and metric == "覆盖义务":
        fibre = "Subsidy Scheme to Extend Fibre-based Networks to Villages in Remote Areas"
        five_g = "Subsidy Scheme to Extend 5G Coverage in Rural and Remote Areas"
        if fibre.lower() in text.lower() and five_g.lower() in text.lower():
            value = "OFCA实施偏远乡村光纤网络延伸资助计划及乡郊和偏远地区5G覆盖资助计划"
            return _deterministic_result(
                task,
                value,
                f"{fibre}；{five_g}",
                "从OFCA官方网站计划清单精确提取",
            )

    if company == "政治新闻" and metric == "重大政策/声明" and re.search(
        r"Announcement on the Implementation of Electronic Border Management Area Permit Policy",
        text,
        re.IGNORECASE,
    ):
        value = "中国政府网发布关于实施边境管理区通行证电子化政策的公告"
        return _deterministic_result(
            task,
            value,
            "Announcement on the Implementation of Electronic Border Management Area Permit Policy",
            "从中国政府网英文版政策公告标题精确提取",
        )

    if company == "KT" and metric == "企业ICT":
        products = [
            label
            for label in (
                "Enterprise LTE Service",
                "IoTMakers",
                "ucloud biz",
                "AMI",
                "BEMS",
                "Fintech",
            )
            if label.lower() in text.lower()
        ]
        if len(products) >= 4:
            value = "KT企业ICT能力包括" + "、".join(products)
            return _deterministic_result(
                task,
                value,
                "；".join(products),
                "从KT官方网站业务清单精确提取",
            )
        if re.search(
            r"KT AX platform.{0,360}?customized and integrated digital transformation services",
            text,
            re.IGNORECASE | re.DOTALL,
        ) and re.search(
            r"Internet data centers and cloud services",
            text,
            re.IGNORECASE,
        ):
            value = (
                "KT面向企业及机构客户提供KT AX平台定制化数字化转型服务，"
                "并运营互联网数据中心、云、服务器、存储和专线服务"
            )
            return _deterministic_result(
                task,
                value,
                (
                    "KT AX platform services provide customized and integrated "
                    "digital transformation services; KT also operates Internet "
                    "data centers and cloud services."
                ),
                "从KT 2025年Form 20-F业务说明精确提取",
            )

    if company == "Jio" and metric == "Capex方向" and re.search(
        r"Expanding 5G and broadband adoption across mobility, homes and enterprises",
        text,
        re.IGNORECASE,
    ) and re.search(
        r"Deployment of Private 5G|AirFiber subscribers crossed",
        text,
        re.IGNORECASE,
    ):
        value = "网络投入方向聚焦5G、AirFiber家宽及企业Private 5G能力"
        return _deterministic_result(
            task,
            value,
            (
                "Jio is expanding 5G and broadband adoption across mobility, "
                "homes and enterprises; AirFiber subscribers crossed 5.6 million "
                "and Private 5G was deployed for enterprise connectivity."
            ),
            "从Reliance FY2025业绩演示材料精确提取",
        )

    if company == "Vodafone" and metric == "边缘计算" and re.search(
        r"pan-European federated edge continuum",
        text,
        re.IGNORECASE,
    ):
        value = "参与建设泛欧洲联邦式边缘计算连续体，推动跨运营商边缘服务互联"
        return _deterministic_result(
            task,
            value,
            "Vodafone announced work on a pan-European federated edge continuum.",
            "从Vodafone官方技术新闻精确提取",
        )

    if company == "T-Mobile US" and metric == "FWA" and re.search(
        r"T.?Mobile US.{0,260}?fixed wireless broadband access via FWA",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        value = "利用中频段频谱优势，通过FWA向客户提供固定无线宽带接入"
        return _deterministic_result(
            task,
            value,
            (
                "T-Mobile US is leveraging its leading position in mid-band "
                "spectrum to offer fixed wireless broadband access via FWA."
            ),
            "从Deutsche Telekom 2025年年报美国业务章节精确提取",
        )

    if company == "T-Mobile US" and metric == "FWA":
        match = re.search(
            r"5G broadband\s*\(formerly High Speed Internet\)"
            r".{0,260}?were\s+([0-9.]+)\s+million\s+and\s+([0-9.]+)\s+million"
            r"\s+in\s+2025\s+and\s+2024",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            value = (
                f"5G宽带净增客户2025年为{match.group(1)}百万，"
                f"2024年为{match.group(2)}百万"
            )
            return _deterministic_result(
                task,
                value,
                (
                    "5G broadband (formerly High Speed Internet) net customer "
                    f"additions were {match.group(1)} million and {match.group(2)} "
                    "million in 2025 and 2024, respectively."
                ),
                "从Deutsche Telekom 2025年年报美国业务章节精确提取",
            )

    if company == "T-Mobile US" and metric == "网络API" and re.search(
        r"T-Mobile",
        text,
        re.IGNORECASE,
    ) and re.search(
        r"global venture.{0,500}?network APIs|network APIs.{0,500}?global venture",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        value = "参与全球运营商网络API合资平台，推动通用网络API规模化应用"
        return _deterministic_result(
            task,
            value,
            (
                "T-Mobile joined the global operator venture created to aggregate "
                "and commercialize network APIs."
            ),
            "从Ericsson官方网络API联合公告精确提取",
        )

    if company == "HKBN" and metric == "资产负债率":
        gearing = re.search(
            r"gearing ratio[^.]{0,180}?was\s+([0-9.]+x)\s+as at\s+([^.(]+)",
            text,
            re.IGNORECASE,
        )
        if gearing:
            value = f"总债务/总权益比率{gearing.group(1)}（截至{clean_text(gearing.group(2), 40)}）"
            return _deterministic_result(task, value, gearing.group(0), "从HKBN年报精确提取")

    if company == "HGC" and metric == "数据中心" and re.search(
        r"HGC Expands the Data Center Interconnect to Malaysia",
        text,
        re.IGNORECASE,
    ):
        value = "HGC于2025年5月宣布将数据中心互联服务扩展至马来西亚"
        return _deterministic_result(
            task,
            value,
            "06 May 2025 HGC Expands the Data Center Interconnect to Malaysia",
            "从HGC官方网站新闻条目精确提取",
        )

    if company == "HGC" and metric == "云网产品":
        products = [
            product
            for product in (
                "AWS Direct Connect",
                "Azure ExpressRoute",
                "Google Cloud Partner Interconnect",
                "Alibaba Cloud Express Connect",
            )
            if product.lower() in text.lower()
        ]
        if len(products) >= 3:
            value = "云连接产品包括" + "、".join(products)
            return _deterministic_result(task, value, value, "从HGC官方网站产品清单精确提取")
    return None


def build_tasks(limit: int | None = None) -> list[dict[str, Any]]:
    payload = build_company_metrics_payload(apply_ai_cache=False)
    rows = [row for row in payload["rows"] if needs_ai(row)]
    tasks = []
    for row in rows[:limit]:
        row_ref = str(row.get("rowRef") or "")
        company = str(row.get("company") or "")
        metric = str(row.get("metric") or "")
        evidence_parts: list[str] = []
        evidence_sources: list[str] = []
        result_path = RESULTS_DIR / f"{row_ref}.json"
        if row_ref and result_path.exists():
            try:
                result_data = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                result_data = {}
            for entity_result in result_data.get("entity_results") or []:
                if str(entity_result.get("entity") or "") != company:
                    continue
                focused_records = []
                for record in entity_result.get("raw_records") or []:
                    if not _record_allowed_for_company(record, company):
                        continue
                    sample = _record_evidence(record, metric, company)
                    source_url = str(record.get("final_url") or record.get("url") or "").strip()
                    # Neutral/third-party pages can discuss several operators.
                    # Only retain their metric window when the target company is
                    # named in that same focused evidence.
                    if (
                        not _official_domain_owners(source_url)
                        and not _neutral_record_has_verified_entity(record, company)
                        and not _evidence_mentions_company(sample, company)
                    ):
                        continue
                    focused_records.append((_evidence_relevance(sample, metric, company), sample, source_url))
                for _score, sample, source_url in sorted(focused_records, key=lambda item: item[0], reverse=True):
                    if sample and sample not in evidence_parts:
                        evidence_parts.append(sample)
                    if source_url and source_url not in evidence_sources:
                        evidence_sources.append(source_url)
                    if sum(len(part) for part in evidence_parts) >= 20000:
                        break
                break
        if not evidence_parts:
            fallback_detail = clean_text(row.get("detail") or row.get("value"), 1600)
            if fallback_detail:
                evidence_parts.append(fallback_detail)
        verified_context, verified_sources = _verified_metric_context(company, metric)
        if verified_context and verified_context not in evidence_parts:
            evidence_parts.insert(0, f"已核验公开字段：{verified_context}")
        for source_url in verified_sources:
            if source_url and source_url not in evidence_sources:
                evidence_sources.append(source_url)
        if not evidence_sources:
            evidence_sources = [
                str(source.get("url") or "")
                for source in row.get("sources", [])
                if str(source.get("url") or "") and (
                    not _official_domain_owners(str(source.get("url") or ""))
                    or company in _official_domain_owners(str(source.get("url") or ""))
                )
            ]
        task = {
                "id": row["id"],
                "company": company,
                "metric": metric,
                "current_value": row.get("value", ""),
                "raw_text": clean_text("\n\n".join(evidence_parts), 20000),
                "sources": evidence_sources[:8],
                "row_ref": row_ref,
            }
        task["evidence_hash"] = hashlib.sha256(
            json.dumps(task, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        tasks.append(task)
    return tasks


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[\s*\{.*\}\s*\])", text, flags=re.S)
        if match:
            return json.loads(match.group(1))
        raise


def call_deepseek(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("未配置 DeepSeek API Key")
    base_url = str(config.get("base_url") or "https://api.deepseek.com").rstrip("/")
    model = str(config.get("model") or "deepseek-chat")

    system_prompt = (
        "你是电信行业数据清洗助手。你的任务是把网页抓取片段整理成可直接放入表格的短数据。"
        "不要编造。不要输出网页导航、菜单、登录、广告、版权或无关文本。"
        "如果片段无法支持该指标，status 写 unavailable，value 写“未提取到有效数据”。"
        "必须分别检查三件事：entity_supported 表示片段或来源URL确实属于该公司；"
        "metric_supported 表示片段确实在讲输入的指标；value_supported 表示输出值可由片段直接支持。"
        "如果片段明显属于另一家公司，或指标名本身是另一家公司名，entity_supported 或 metric_supported 必须为 false。"
        "例如把净利润当作ARPU、把折旧当作资本开支、把股息变化当作市场反应，均必须判定 metric_supported=false。"
        "总收益不能用服务收入替代；套餐资费不能用屏幕更换价值、积分奖励或附加权益金额替代；"
        "接口返回记录条数不能作为GDP、CPI等宏观指标值；品牌csl和1O1O不能直接承接HKT集团EBITDA等集团财务指标。"
        "市场反应必须有股价、收盘价、交易日涨跌、评级或明确市场关注表述；不能只输出利润及同比。"
        "对派息、股息、资本开支、收入、收益、EBITDA、利润、用户数、ARPU、资费、频谱等量化指标，"
        "必须有明确数字和单位才能 status=ok；只有描述但没有数字时必须 unavailable。"
        "对战略升级、券商观点、市场反应等非量化指标，可以用一句中文事实概括，但必须来自片段。"
        "对合作、5G-A、边缘计算、数据中心、AI、云、网络API等定性指标，不要求一定有数字；"
        "只要片段明确给出目标公司的具体发布、部署、合作对象、产品、项目或行动，即可 status=ok。"
        "只有栏目名称、菜单词或没有具体动作的泛泛描述仍应 unavailable。"
        "value 必须短，优先保留数字、单位、比例、金额、用户数、日期、评级或一句战略事实。"
        "basis 用一句话说明依据来自片段中的哪部分。"
        "只返回 JSON 数组，不要 Markdown。"
    )
    user_prompt = (
        "请清洗以下公司指标记录。每个输入对象有 id/company/metric/current_value/raw_text/sources。\n"
        "返回数组，每项字段必须为：id, status, value, basis, note, "
        "entity_supported, metric_supported, value_supported, confidence。\n"
        "status 只能是 ok 或 unavailable。\n\n"
        f"{json.dumps(tasks, ensure_ascii=False)}"
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_with_local_proxy_fallback(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:1000]
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
    content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    cleaned = extract_json(content)
    if not isinstance(cleaned, list):
        raise RuntimeError("模型没有返回 JSON 数组")
    return cleaned


def load_cache() -> dict[str, Any]:
    if not AI_CACHE_PATH.exists():
        return {"schemaVersion": AI_CACHE_SCHEMA_VERSION, "updatedAt": "", "items": {}}
    try:
        data = json.loads(AI_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"schemaVersion": AI_CACHE_SCHEMA_VERSION, "updatedAt": "", "items": {}}
    if not isinstance(data, dict):
        return {"schemaVersion": AI_CACHE_SCHEMA_VERSION, "updatedAt": "", "items": {}}
    data.setdefault("items", {})
    return data


def write_cache(path: Path, cache: dict[str, Any]) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    limit = None
    batch_size = int(os.environ.get("COMPANY_METRICS_AI_BATCH", "25"))
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])
    tasks = build_tasks(limit=limit)
    cache = load_cache()
    if cache.get("schemaVersion") != AI_CACHE_SCHEMA_VERSION:
        cache = {"schemaVersion": AI_CACHE_SCHEMA_VERSION, "updatedAt": "", "items": {}}
    existing = cache.get("items", {})
    current_ids = {task["id"] for task in tasks}
    existing = {
        row_id: item
        for row_id, item in existing.items()
        if row_id in current_ids and item.get("schemaVersion") == AI_CACHE_SCHEMA_VERSION
    }
    tasks = [task for task in tasks if task["id"] not in existing]
    if not tasks:
        cache["schemaVersion"] = AI_CACHE_SCHEMA_VERSION
        cache["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cache["items"] = existing
        write_cache(AI_CACHE_PATH, cache)
        print(f"AI指标整理检查完成：当前 {len(existing)} 条均为最新，无新增记录。")
        return 0
    print(f"准备清洗 {len(tasks)} 条指标，批大小 {batch_size}。")
    by_id = {task["id"]: task for task in tasks}
    offline_mode = False
    for start in range(0, len(tasks), batch_size):
        batch = tasks[start : start + batch_size]
        print(f"清洗 {start + 1}-{start + len(batch)} / {len(tasks)} ...")
        if offline_mode:
            cleaned = fallback_clean_batch(batch)
        else:
            try:
                cleaned = call_deepseek(batch)
            except Exception as exc:
                offline_mode = True
                print(f"⚠️ AI在线清洗不可用，切换本地严格校验兜底：{exc}")
                cleaned = fallback_clean_batch(batch)
        for item in cleaned:
            if not isinstance(item, dict) or item.get("id") not in by_id:
                continue
            value = clean_text(item.get("value"), 220)
            if not value:
                continue
            existing[item["id"]] = {
                "schemaVersion": AI_CACHE_SCHEMA_VERSION,
                "company": by_id[item["id"]]["company"],
                "metric": by_id[item["id"]]["metric"],
                "status": item.get("status") or "ok",
                "value": value,
                "basis": clean_text(item.get("basis"), 600),
                "note": clean_text(item.get("note"), 160),
                "entity_supported": bool(item.get("entity_supported")),
                "metric_supported": bool(item.get("metric_supported")),
                "value_supported": bool(item.get("value_supported")),
                "confidence": item.get("confidence"),
            }
        cache["schemaVersion"] = AI_CACHE_SCHEMA_VERSION
        cache["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cache["items"] = existing
        write_cache(STAGING_CACHE_PATH, cache)
    STAGING_CACHE_PATH.replace(AI_CACHE_PATH)
    print(f"已写入 {AI_CACHE_PATH.name}，累计 {len(existing)} 条。")
    return 0


if __name__ == "__main__":
    from run_data_curation import main as run_curation_main

    raise SystemExit(run_curation_main())
