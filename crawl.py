from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from crawl_settings import apply_selected_fields, selected_row_config
from extractors import compact_extracted, find_field_snippets, normalize_text, row_fields, snippet_around

import socket
for _port in (7897, 7890, 10809):
    try:
        with socket.create_connection(("127.0.0.1", _port), timeout=0.1):
            _proxy = f"http://127.0.0.1:{_port}"
            os.environ["HTTP_PROXY"] = _proxy
            os.environ["HTTPS_PROXY"] = _proxy
            os.environ["http_proxy"] = _proxy
            os.environ["https_proxy"] = _proxy
            break
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
RESULTS_DIR = ROOT / "results"
SPREADSHEET_JSON = ROOT / "feishu_latest_AJ.json"
SOURCE_REGISTRY_JSON = ROOT / "source_registry.json"
PER_URL_TIMEOUT_SECONDS = 35.0
CURL_TIMEOUT_SECONDS = 45
CURL_PROCESS_TIMEOUT_SECONDS = 55
MAX_RUN_SECONDS = int(os.environ.get("CMHK_CRAWL_MAX_SECONDS", "900"))
CMHK_USER_AGENT = os.environ.get(
    "CMHK_CRAWLER_USER_AGENT",
    "CMHK-Internal-ResearchBot/1.0 (+internal competitive intelligence; contact: legal-review-required)",
)
CMHK_REQUIRE_ROBOTS = os.environ.get("CMHK_REQUIRE_ROBOTS", "0").strip().lower() not in {"0", "false", "no"}
CMHK_SAVE_RAW_BODY = os.environ.get("CMHK_SAVE_RAW_BODY", "0").strip().lower() in {"1", "true", "yes"}
CMHK_IGNORE_COMPLIANCE = os.environ.get("CMHK_IGNORE_COMPLIANCE", "0").strip().lower() in {"1", "true", "yes"}
SPREADSHEET_TOKEN = "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
MAIN_SHEET_ID = "9c638d"
import shutil
LARK_CLI = shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"
SOURCE_REGISTRY_CACHE: Dict[str, Any] | None = None
ROBOTS_CACHE: Dict[str, Dict[str, Any]] = {}


ROW_ENTITY_OVERRIDES: Dict[int, List[str]] = {
    2: ["HKT", "csl", "1O1O"],
    3: ["HKT", "csl", "1O1O"],
    4: ["HKT", "csl", "1O1O"],
    5: ["3HK", "Hutchison"],
    6: ["3HK", "Hutchison"],
    7: ["3HK", "Hutchison"],
    19: ["Singtel", "Telstra", "SK Telecom", "KT", "NTT Docomo", "KDDI", "SoftBank", "Jio", "Airtel"],
    20: ["Vodafone", "Deutsche Telekom", "Orange", "Telefonica", "BT/EE", "TIM", "Verizon", "AT&T", "T-Mobile US"],
    21: ["e&", "stc", "中国移动", "中国电信", "中国联通"],
}


ENTITY_HINTS: Dict[str, List[str]] = {
    "HKT": ["hkt.com", "hkt ", "hkt-", "hkt enterprise", "pccw", "6823"],
    "csl": ["hkcsl", "csl", "hkt.com/on-the-go/csl", "1o1o and csl"],
    "1O1O": ["1010", "1o1o", "csl1010"],
    "3HK": ["three.com.hk", "3hk", "3business", "sosim", "three hong kong"],
    "Hutchison": ["hutchison", "hthkh", "hutchison telecommunications", "215"],
    "SmarTone": ["smartone", "00315"],
    "HKBN": ["hkbn", "01310"],
    "HGC": ["hgc"],
    "iCable": ["i-cable", "icable", "01097", "cable"],
    "Singtel": ["singtel"],
    "Telstra": ["telstra"],
    "SK Telecom": ["sk telecom", "skt"],
    "KT": ["kt corp", " kt ", "corp.kt.com"],
    "NTT Docomo": ["ntt docomo", "docomo"],
    "KDDI": ["kddi"],
    "SoftBank": ["softbank"],
    "Jio": ["jio", "reliance jio"],
    "Airtel": ["airtel"],
    "Vodafone": ["vodafone"],
    "Deutsche Telekom": ["deutsche telekom", "telekom.com"],
    "Orange": ["orange"],
    "Telefonica": ["telefonica", "telefónica"],
    "BT/EE": ["bt.com", " bt ", " ee ", "bt/ee"],
    "TIM": ["tim", "gruppotim"],
    "Verizon": ["verizon"],
    "AT&T": ["at&t", "att.com"],
    "T-Mobile US": ["t-mobile", "tmobile"],
    "e&": ["e&", "etisalat", "eand.com"],
    "stc": ["stc"],
    "中国移动": ["china mobile", "chinamobile"],
    "中国电信": ["china telecom", "chinatelecom"],
    "中国联通": ["china unicom", "chinaunicom"],
}


def display_source_urls(urls: List[str]) -> List[str]:
    non_pdf = [url for url in urls if not url.lower().split("?", 1)[0].endswith(".pdf")]
    return non_pdf or urls


def split_entities(value: str) -> List[str]:
    parts = re.split(r"\s*/\s*|、|，|,", value or "")
    entities: List[str] = []
    for part in parts:
        item = normalize_text(part)
        if item and item not in entities:
            entities.append(item)
    return entities


def row_entities(row: int, effective_object: str) -> List[str]:
    if row in ROW_ENTITY_OVERRIDES:
        return ROW_ENTITY_OVERRIDES[row]
    if "/" in (effective_object or ""):
        return split_entities(effective_object)
    return [effective_object.strip()] if effective_object.strip() else []


def entity_hints(entity: str) -> List[str]:
    hints = ENTITY_HINTS.get(entity, [])
    base = entity.lower()
    return list(dict.fromkeys([base, *[hint.lower() for hint in hints]]))


def matched_entities(row: int, entities: List[str], result: Dict[str, Any]) -> List[str]:
    haystack = " ".join(
        [
            str(result.get("url", "")),
            str(result.get("final_url", "")),
            str(result.get("title", "")),
            str(result.get("text", ""))[:120000],
        ]
    ).lower()
    hits = []
    for entity in entities:
        if any(hint and hint in haystack for hint in entity_hints(entity)):
            hits.append(entity)
    if not hits and len(entities) == 1:
        hits = entities[:]
    return hits


def urls_for_entity(entity_result: Dict[str, Any]) -> List[str]:
    return display_source_urls(entity_result.get("source_urls", []))


EXTRA_CANDIDATES: Dict[int, List[str]] = {
    3: [
        "https://www.hkcsl-5g.com/en/5g-tariff-plan/",
        "https://www.hkcsl.com/en/csl-local-prepaid-sim-card",
        "https://www.1010.com.hk/",
        "https://www.netvigator.com/eng/",
        "https://www.hkt-enterprise.com/en/news-events/news/hkt-launches-ai-superhighway-solution",
    ],
    2: [
        "https://www.hkt.com/en/about-hkt/investor-relations/fast-facts/",
        "https://www.hkt.com/en/about-hkt/investor-relations/financial-results/",
        "https://www.hkcsl.com/en/csl-local-prepaid-sim-card",
        "https://www.1010.com.hk/",
        "https://stockanalysis.com/quote/hkg/6823/revenue/",
        "https://stockanalysis.com/quote/hkg/6823/financials/",
        "https://financialreports.eu/filings/hkt-management-limited-and-hkt-limited/annual-report/2025/32579946/",
    ],
    5: [
        "https://www.hthkh.com/en/ir/reports.php",
        "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040102176.pdf",
    ],
    8: [
        "https://www.smartoneholdings.com/about/investor/results/english/2025_annual_present.pdf",
        "https://www.smartoneholdings.com/about/investor/results/english/2026_interim_present.pdf",
        "https://financialreports.eu/filings/smartone-telecommunications-holdings-limited/interim-quarterly-report/2026/33085922/",
        "https://financialreports.eu/filings/smartone-telecommunications-holdings-limited/interim-quarterly-report/2025/17900712/",
    ],
    9: [
        "https://5g.smartone.com/en/mobile_and_price_plans/subscription-offers/",
        "https://5g.smartone.com/en/mobile_and_price_plans/roaming/apac_worldwide_roaming_data_pack/charges.jsp",
    ],
    10: [
        "https://www.aastocks.com/en/stocks/analysis/stock-aafn/00315/0/all/1",
        "https://www.smartoneholdings.com/about/investor/results/english/2026_interim_present.pdf",
        "https://www.mobileworldlive.com/operators/smartone-turns-to-ericsson-for-5g-a-gear/",
        "https://www.ericsson.com/en/press-releases/2/2026/smartone-strengthens-network-with-ericsson-5g-advanced-technology",
    ],
    11: [
        "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf",
        "https://www.hkbn.net/group/en/newsroom/press-releases/20251031_FY25_Annual_Results",
    ],
    12: [
        "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf",
        "https://www.hkbn.net/group/en/newsroom/press-releases/20251031_FY25_Annual_Results",
        "https://www.hkbn.net/group/en/investor-engagement/announcement-circulars",
    ],
    4: [
        "https://www.hkt-enterprise.com/en/news-events/news/hkt-launches-ai-superhighway-solution",
        "https://www.hkt-enterprise.com/en/about-hkt",
        "https://www.hkt-enterprise.com/en/products-solutions/data-connectivity/facilities-management-center",
        "https://www.1010corporate.com/en/news-updates/ezone-open-api-digital-innovation/",
        "https://www.hkcsl.com/en/csl-local-prepaid-sim-card",
        "https://www.1010.com.hk/",
    ],
    7: ["https://m.hthkh.com/en/media/press.php", "https://www.hthkh.com/en/media/press_3hk.php"],
    6: [
        "https://web.three.com.hk/plans/3business5g/index-en.html",
        "https://web.three.com.hk/plans/apac/index2-en.html",
        "https://www.hthkh.com/en/",
    ],
    17: [
        "https://www.aastocks.com/en/stocks/analysis/stock-aafn/01097/0/all/1",
        "https://www.i-cablecomm.com/annual-interim-reports?lang=en",
        "https://financialreports.eu/filings/i-cable-communications-limited/annual-report/2025/24023514/",
        "https://stockanalysis.com/quote/hkg/1097/financials/",
        "https://dataxis.com/actor-profile/357941/i-cable-television-and-telecom/",
    ],
    18: [
        "https://www.i-cablebroadband-offer.com/",
        "https://www.i-cablecomm.com/annual-interim-reports?lang=en",
        "https://financialreports.eu/filings/i-cable-communications-limited/annual-report/2025/24023514/",
    ],
    22: ["https://www.policyaddress.gov.hk/2025/en/index.html", "https://www.policyaddress.gov.hk/2024/en/index.html"],
    23: [
        "https://data.gov.hk/en-data/dataset/hk-censtatd-commonidds-common-idds",
        "https://apidocs.hkma.gov.hk/abouthkmasapi/",
        "https://www.censtatd.gov.hk/en/scode460.html",
        "https://www.censtatd.gov.hk/en/scode200.html",
        "https://www.pmi.spglobal.com/Public/Home/PressRelease/a8f02e53a64c42c7bed05c6df7b1a487",
    ],
    24: ["https://www.policyaddress.gov.hk/2025/en/index.html", "https://www.digitalpolicy.gov.hk/en/"],
    26: ["https://www.ofca.gov.hk/en/home/index.html", "https://www.pcpd.org.hk/english/artificial_intelligence/index.html"],
    27: [
        "https://digital-strategy.ec.europa.eu/en/policies/data-act",
        "https://digital-strategy.ec.europa.eu/en/policies/data-act-explained",
        "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai",
    ],
    28: ["https://www.ofca.gov.hk/en/home/index.html", "https://www.enisa.europa.eu/news", "https://www.imda.gov.sg/regulations-and-licensing-listing"],
    29: [
        "https://api.worldbank.org/v2/country/HKG/indicator/NY.GDP.MKTP.CD?format=json&per_page=5",
        "https://www.itu.int/",
        "https://oecd.ai/",
    ],
    30: [
        "https://api.worldbank.org/v2/country/HKG/indicator/NY.GDP.MKTP.CD?format=json&per_page=5",
        "https://apidocs.hkma.gov.hk/abouthkmasapi/",
        "https://www.censtatd.gov.hk/en/scode460.html",
        "https://www.censtatd.gov.hk/en/scode200.html",
        "https://www.info.gov.hk/gia/general/202601/22/P2026012200447p.htm",
        "https://www.hkma.gov.hk/eng/data-publications-and-research/data-and-statistics/monthly-statistical-bulletin/",
    ],
    19: [
        "https://www.singtel.com/about-us/media-centre/news-releases/singtel-partners-ericsson-to-accelerate-industry-transformation-with-5g-advanced",
        "https://www.singtel.com/about-us/media-centre/news-releases/singtel-posts-fy26-net-profit",
        "https://www.telstra.com.au/aboutus/media",
        "https://news.sktelecom.com/en/2787",
        "https://news.sktelecom.com/en/category/press-center/press-release",
        "https://corp.kt.com/eng/",
        "https://www.docomo.ne.jp/english/info/media_center/pr/2026/0225_02.html",
        "https://www.docomo.ne.jp/english/info/media_center/pr/2026/0303_00.html",
        "https://newsroom.kddi.com/english/news/detail/kddi_nr-560_3842.html",
        "https://www.softbank.jp/en/corp/news/press/sbkk/2026/20260302_03/",
        "https://www.softbank.jp/en/corp/news/press/sbkk/2026/20260416_02/",
        "https://www.jio.com/",
        "https://www.airtel.in/press-release/03-2026/airtel-announces-us1-billion-investment-in-nxtra-led-by-alpha-wave-global-and-existing-investor-carlyle-bharti-airtel-will-also-participate/",
        "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2025-26/Q4/Press-Release.pdf",
        "https://www.airtel.in/press-release",
    ],
    20: [
        "https://www.vodafone.com/news/newsroom/technology/pan-european-federated-edge-continuum",
        "https://www.vodafone.com/news/technology/vodafone-advances-future-ready-radio-access-network",
        "https://www.vodafone.com/news/newsroom/technology/new-open-ran-ready-chip-tested-by-vodafone-samsung-and-amd",
        "https://developer.orange.com/blog/meet-the-network-apis-playground-safely-build-break-and-learn/",
        "https://developer.orange.com/events/mwc-2026/",
        "https://about.att.com/blogs/2026/5g-network-apis.html",
        "https://about.att.com/blogs/2026/att-advances-open-ran-readiness.html",
        "https://about.att.com/story/2026/att-ericsson-enhance-cloud-ran.html",
        "https://www.t-mobile.com/news/network/t-mobile-and-deutsche-telekom-6g-innovation-hub",
        "https://investors.att.com/financial-reports/annual-reports/2025",
        "https://www.verizon.com/5g/home/",
        "https://www.t-mobile.com/home-internet",
        "https://www.telekom.com/en/media/media-information",
        "https://www.telefonica.com/en/communication-room/press-room/",
        "https://newsroom.bt.com/bt-group-and-ericsson-strengthen-partnership-to-unlock-smarter-more-reliable-5g-services-for-uk-businesses/",
        "https://www.bt.com/about/bt/our-company/group-businesses/networks",
        "https://www.gruppotim.it/en/press-archive.html",
    ],
    21: [
        "https://www.stc.com/en/investors.html",
        "https://www.chinamobileltd.com/en/ir/reports.php",
        "https://www.chinatelecom-h.com/en/ir/report/annual2025.pdf",
        "https://www.chinaunicom.com.hk/en/ir/reports/ar2025.pdf",
        "https://en.c114.com.cn/576/a1307257.html",
        "https://www.gsma.com/about-us/regions/greater-china/wp-content/uploads/2025/04/Mobile-Economy-Report-2025-China-EN.pdf",
        "https://www.eand.com/en/news/news-overview.html",
        "https://www.eand.com/en/news/28-04-26-eand-financial-results-q1-2026.html",
        "https://www.eand.com/en/news/16-mar-26-eand-khalifa-uni-launch-white-paper.html",
    ],
    15: ["https://www.hgc-intl.com/insight/hgc-sets-out-for-full-scale-transformation/"],
    24: [
        "https://www.policyaddress.gov.hk/2025/en/highlight.html",
        "https://www.investhk.gov.hk/en/news/",
        "https://www.info.gov.hk/gia/general/202506/26/P2025062600269.htm",
        "https://www.digitalpolicy.gov.hk/en/",
    ],
    27: [
        "https://commission.europa.eu/news-and-media/news/data-act-enters-force-what-it-means-you-2024-01-11_en",
        "https://digital-strategy.ec.europa.eu/en/policies/digital-services-act-package",
        "https://commission.europa.eu/law/law-topic/data-protection/data-protection-eu_en",
        "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai",
        "https://digital-strategy.ec.europa.eu/en/faqs/navigating-ai-act",
        "https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/press-releases/2026/new-model-ai-governance-framework-for-agentic-ai",
    ],
    28: [
        "https://www.ofca.gov.hk/en/site_map/index.html",
        "https://www.ofca.gov.hk/en/industry_focus/industry_focus/portability/mnp/index.html",
        "https://www.ofca.gov.hk/en/consumer_focus/guide/general/gba/index.html",
        "https://www.imda.gov.sg/regulations-and-licensing-listing/spectrum-management",
    ],
    32: [
        "https://www.investhk.gov.hk/en/news/",
        "https://www.totaltele.com/",
        "https://www.mobileworldlive.com/",
        "https://www.verizon.com/about/news/verizon-and-frontier-regulatory-approval",
        "https://www.t-mobile.com/news/business/t-mobile-closes-uscellular-acquisition",
    ],
    31: ["https://www.mobileworldlive.com/", "https://www.totaltele.com/"],
    31: [
        "https://www.gsma.com/newsroom/press-releases/",
        "https://www.gsma.com/solutions-and-impact/technologies/networks/",
        "https://www.ericsson.com/en/press-releases",
        "https://www.mobileworldlive.com/",
        "https://www.totaltele.com/",
    ],
    34: ["https://api.worldbank.org/v2/country/HKG/indicator/NY.GDP.MKTP.CD?format=json&per_page=5"],
    34: [
        "https://api.worldbank.org/v2/country/HKG/indicator/NY.GDP.MKTP.CD?format=json&per_page=5",
        "https://www.censtatd.gov.hk/en/scode200.html",
    ],
}


def cell_text(value: Any) -> str:
    if isinstance(value, list):
        parts = []
        for part in value:
            if isinstance(part, dict):
                parts.append(part.get("text") or part.get("link") or "")
            else:
                parts.append(str(part))
        return "".join(parts)
    if value is None:
        return ""
    return str(value)


def parse_latest_sheet() -> List[Dict[str, Any]]:
    data = json.loads(SPREADSHEET_JSON.read_text(encoding="utf-8"))
    values = data["data"]["valueRange"]["values"]
    rows: List[Dict[str, Any]] = []
    effective_object = ""
    effective_block = ""
    for idx, row in enumerate(values[1:], start=2):
        if idx > 34:
            break
        cols = [cell_text(row[i]) if i < len(row) else "" for i in range(8)]
        if not any(c.strip() for c in cols[:8]):
            continue
        block_cell = cols[1].strip()
        if block_cell:
            effective_block = block_cell
        object_cell = cols[2].strip()
        if object_cell:
            effective_object = object_cell
        entities = row_entities(idx, effective_object)
        rows.append(
            {
                "row": str(idx),
                "block": effective_block,
                "object": effective_object,
                "object_cell": object_cell,
                "entities": entities,
                "package": cols[3],
                "need": cols[4],
                "sources": cols[5],
                "channel": cols[6],
                "frequency": cols[7],
            }
        )
    return rows


def apply_row_filter(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    raw = os.environ.get("CMHK_ROWS", "").strip()
    if not raw:
        return rows
    wanted = {item.strip() for item in raw.split(",") if item.strip()}
    return [row for row in rows if row["row"] in wanted]


def apply_crawl_settings(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    configured: List[Dict[str, Any]] = []
    for row in rows:
        row_no = int(row["row"])
        cfg = selected_row_config(row_no)
        if cfg.get("enabled", True) is False:
            continue

        selected_entities = [str(item).strip() for item in cfg.get("entities", []) if str(item).strip()]
        if selected_entities:
            row["entities"] = selected_entities

        available_fields = list(row_fields(row_no))
        selected_fields = [str(item).strip() for item in cfg.get("fields", []) if str(item).strip()]
        row["selected_fields"] = selected_fields or available_fields
        extra_urls = [str(item).strip() for item in cfg.get("sourceUrls", []) if str(item).strip()]
        if extra_urls:
            row["sources"] = "\n".join([str(row.get("sources") or ""), *extra_urls]).strip()
        configured.append(row)
    return configured


def urls_from_sources(source_text: str) -> List[str]:
    urls = re.findall(r"https?://[^\s]+", source_text or "")
    clean: List[str] = []
    for url in urls:
        url = url.strip().rstrip("。；;,")
        if url not in clean:
            clean.append(url)
    return clean


SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?i)\b(?:bearer|token|api[_-]?key|authorization|cookie|session)\s*[:=]\s*[^\s,;]+"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(?:\+?\d[\d -]{7,}\d)\b"), "[REDACTED_PHONE_OR_ID]"),
]


def redact_sensitive(text: str) -> str:
    value = text or ""
    for pattern, replacement in SENSITIVE_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def load_source_registry() -> Dict[str, Any]:
    global SOURCE_REGISTRY_CACHE
    if SOURCE_REGISTRY_CACHE is None:
        SOURCE_REGISTRY_CACHE = json.loads(SOURCE_REGISTRY_JSON.read_text(encoding="utf-8"))
    return SOURCE_REGISTRY_CACHE


def source_policy(url: str) -> Dict[str, Any]:
    registry = load_source_registry()
    domain = urlparse(url).netloc.lower()
    entry = dict(registry.get("domains", {}).get(domain) or {})
    if not entry:
        entry = {
            "policy": registry.get("default_policy", "deny"),
            "type": "unregistered",
            "jurisdiction": "unknown",
            "tos_status": "unreviewed",
            "notes": "Domain is not registered in source_registry.json.",
        }
    entry["domain"] = domain
    return entry


def robots_policy(client: httpx.Client, url: str) -> Dict[str, Any]:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc.lower()}"
    if origin in ROBOTS_CACHE:
        robots = ROBOTS_CACHE[origin]
    else:
        robots_url = f"{origin}/robots.txt"
        robots = {"robots_url": robots_url, "status": "unchecked", "allowed": False, "error": ""}
        try:
            response = client.get(robots_url, timeout=httpx.Timeout(8.0, connect=5.0))
            robots["http_status"] = response.status_code
            if response.status_code == 404:
                robots.update({"status": "not_found_allow", "allowed": True})
            elif 200 <= response.status_code < 300:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                lines = response.text.splitlines()
                parser.parse(lines)
                robots.update(
                    {
                        "status": "checked",
                        "robots_txt_lines": lines,
                        "allowed": parser.can_fetch(CMHK_USER_AGENT, url),
                    }
                )
            else:
                robots.update({"status": "robots_unavailable", "allowed": not CMHK_REQUIRE_ROBOTS})
        except Exception as exc:
            robots.update({"status": "robots_error", "allowed": not CMHK_REQUIRE_ROBOTS, "error": repr(exc)})
        ROBOTS_CACHE[origin] = robots

    result = dict(robots)
    if result.get("status") == "checked" and "robots_txt_lines" in result:
        parser = RobotFileParser()
        parser.set_url(result["robots_url"])
        parser.parse(result["robots_txt_lines"])
        result["allowed"] = parser.can_fetch(CMHK_USER_AGENT, url)

    return result


def compliance_decision(client: httpx.Client, url: str) -> Dict[str, Any]:
    policy = source_policy(url)
    if CMHK_IGNORE_COMPLIANCE:
        return {
            **policy,
            "robots_status": "ignored",
            "robots_allowed": True,
            "compliance_allowed": True,
            "skip_reason": "",
        }
    if policy.get("policy") != "allow":
        return {
            **policy,
            "robots_status": "not_checked",
            "robots_allowed": False,
            "compliance_allowed": False,
            "skip_reason": f"source policy is {policy.get('policy')}",
        }
    if policy.get("tos_status") in {"not_approved", "prohibited", "unreviewed"}:
        return {
            **policy,
            "robots_status": "not_checked",
            "robots_allowed": False,
            "compliance_allowed": False,
            "skip_reason": f"tos_status is {policy.get('tos_status')}",
        }
    robots = robots_policy(client, url)
    if not robots.get("allowed"):
        return {
            **policy,
            "robots_status": robots.get("status"),
            "robots_allowed": False,
            "robots_url": robots.get("robots_url"),
            "compliance_allowed": False,
            "skip_reason": "robots.txt does not allow this URL or robots could not be verified",
        }
    return {
        **policy,
        "robots_status": robots.get("status"),
        "robots_allowed": True,
        "robots_url": robots.get("robots_url"),
        "compliance_allowed": True,
        "skip_reason": "",
    }


def candidate_urls(row: int, sources: str) -> List[str]:
    urls = urls_from_sources(sources)
    for url in EXTRA_CANDIDATES.get(row, []):
        if url not in urls:
            urls.append(url)
    return urls


def html_to_text(raw: bytes, content_type: str) -> Tuple[str, str]:
    if "pdf" in content_type.lower() or raw[:4] == b"%PDF":
        with tempfile.TemporaryDirectory(prefix="cmhk_pdf_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            pdf_path = tmp_root / ("tmp_" + hashlib.sha1(raw[:4096]).hexdigest() + ".pdf")
            txt_path = tmp_root / (pdf_path.stem + ".txt")
            pdf_path.write_bytes(raw)
            import shutil
            pdftotext_path = shutil.which("pdftotext") or "/opt/homebrew/bin/pdftotext"
            subprocess.run(
                [pdftotext_path, "-layout", "-l", "120", str(pdf_path), str(txt_path)],
                timeout=45,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else ""
            return "PDF extracted by pdftotext", normalize_text(text)
    decoded = raw.decode("utf-8", "replace")
    if "json" in content_type.lower() or decoded.lstrip().startswith(("{", "[")):
        return "", normalize_text(decoded)
    soup = BeautifulSoup(decoded, "lxml")
    title = normalize_text(soup.title.get_text(" ")) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = normalize_text(soup.get_text(" "))
    return title, text


def fetch_with_httpx(client: httpx.Client, url: str) -> Dict[str, Any]:
    response = client.get(url)
    raw = response.content
    ctype = response.headers.get("content-type", "")
    title, text = html_to_text(raw, ctype)
    return {
        "url": url,
        "final_url": str(response.url),
        "status": response.status_code,
        "content_type": ctype,
        "bytes": len(raw),
        "title": title,
        "text": text,
        "error": "",
    }


def fetch_with_curl(url: str) -> Dict[str, Any]:
    output_path = None
    if CMHK_SAVE_RAW_BODY:
        output_path = RAW_DIR / ("curl_" + hashlib.sha1(url.encode()).hexdigest() + ".body")
    with tempfile.NamedTemporaryFile(prefix="cmhk_curl_", delete=not CMHK_SAVE_RAW_BODY) as tmp:
        path = output_path or Path(tmp.name)
        meta = subprocess.run(
            [
                "/usr/bin/curl",
                "--http1.1",
                "-L",
                "--retry",
                "1",
                "--connect-timeout",
                "12",
                "--max-time",
                str(CURL_TIMEOUT_SECONDS),
                "-A",
                CMHK_USER_AGENT,
                "-s",
                "-o",
                str(path),
                "-w",
                "%{http_code}\t%{size_download}\t%{content_type}\t%{url_effective}",
                url,
            ],
            text=True,
            capture_output=True,
            timeout=CURL_PROCESS_TIMEOUT_SECONDS,
        )
        parts = meta.stdout.strip().split("\t")
        raw = path.read_bytes() if path.exists() else b""
    ctype = parts[2] if len(parts) > 2 else ""
    title, text = html_to_text(raw, ctype)
    return {
        "url": url,
        "final_url": parts[3] if len(parts) > 3 else url,
        "status": int(parts[0]) if parts and parts[0].isdigit() else 0,
        "content_type": ctype,
        "bytes": len(raw),
        "title": title,
        "text": text,
        "error": meta.stderr.strip(),
    }


def looks_like_error_page(result: Dict[str, Any]) -> bool:
    title = str(result.get("title", "")).lower()
    text = str(result.get("text", "")).lower()
    sample = text[:1000]
    error_markers = [
        "access denied",
        "page not found",
        "404 page",
        "just a moment",
        "you don't have permission",
    ]
    return any(marker in title or marker in sample for marker in error_markers)


def is_successful_fetch(result: Dict[str, Any]) -> bool:
    text = result.get("text", "")
    if len(text) < 100 or looks_like_error_page(result):
        return False
    status = int(result.get("status") or 0)
    return 200 <= status < 400 or status == 0


def fetch_url(client: httpx.Client, url: str) -> Dict[str, Any]:
    started = time.monotonic()
    compliance = compliance_decision(client, url)
    if not compliance.get("compliance_allowed"):
        return {
            "url": url,
            "final_url": url,
            "status": 0,
            "content_type": "",
            "bytes": 0,
            "title": "",
            "text": "",
            "error": compliance.get("skip_reason", "compliance policy skipped URL"),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "method": "skipped",
            **compliance,
        }
    method = "httpx"
    try:
        result = fetch_with_httpx(client, url)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["method"] = method
        result.update(compliance)
        if result["status"] and result["text"]:
            return result
    except Exception as exc:
        result = {"url": url, "status": 0, "text": "", "error": repr(exc), **compliance}
    try:
        method = "curl"
        curl_started = time.monotonic()
        curl_result = fetch_with_curl(url)
        curl_result["elapsed_seconds"] = round(time.monotonic() - curl_started, 3)
        curl_result["method"] = method
        curl_result.update(compliance)
        if curl_result["status"] or curl_result["text"]:
            return curl_result
    except Exception as exc:
        result["error"] = (result.get("error", "") + " | curl: " + repr(exc)).strip()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["method"] = method
    return {
        "url": url,
        "final_url": url,
        "status": 0,
        "content_type": "",
        "bytes": 0,
        "title": "",
        "text": "",
        "error": result.get("error", "fetch failed"),
        "elapsed_seconds": result.get("elapsed_seconds", 0),
        "method": result.get("method", method),
        **compliance,
    }


def raw_record(row: int, result: Dict[str, Any]) -> Dict[str, Any]:
    text = result.get("text", "")
    content_hash = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    return {
        "row": row,
        "url": result.get("url"),
        "final_url": result.get("final_url"),
        "status": result.get("status"),
        "content_type": result.get("content_type"),
        "title": result.get("title"),
        "bytes": result.get("bytes"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "method": result.get("method"),
        "text_sample": redact_sensitive(text[:900]),
        "content_hash": content_hash,
        "error": result.get("error", ""),
        "source_policy": result.get("policy", ""),
        "source_type": result.get("type", ""),
        "jurisdiction": result.get("jurisdiction", ""),
        "tos_status": result.get("tos_status", ""),
        "robots_status": result.get("robots_status", ""),
        "robots_allowed": result.get("robots_allowed", False),
        "skip_reason": result.get("skip_reason", ""),
    }


def crawl_row(client: httpx.Client, source_row: Dict[str, Any], deadline: float) -> Dict[str, Any]:
    row = int(source_row["row"])
    entities = list(source_row.get("entities") or [])
    urls = candidate_urls(row, source_row["sources"])
    fetched: List[Dict[str, Any]] = []
    combined_text = ""
    successful_urls: List[str] = []
    entity_text: Dict[str, str] = {entity: "" for entity in entities}
    entity_urls: Dict[str, List[str]] = {entity: [] for entity in entities}
    entity_records: Dict[str, List[Dict[str, Any]]] = {entity: [] for entity in entities}
    for url in urls:
        if time.monotonic() > deadline:
            break
        print(f"  -> 正在抓取: {url}", flush=True)
        result = fetch_url(client, url)
        record = raw_record(row, result)
        if is_successful_fetch(result):
            successful_urls.append(url)
            print(f"    [成功] 状态码: {result.get('status')} | 耗时: {result.get('elapsed_seconds')}s | 大小: {result.get('bytes')} B", flush=True)
            combined_text += "\n\nSOURCE: " + url + "\n" + result["text"]
            hits = matched_entities(row, entities, result)
            record["entity_hits"] = hits
            for entity in hits:
                if url not in entity_urls[entity]:
                    entity_urls[entity].append(url)
                entity_records[entity].append(record)
                entity_text[entity] += "\n\nSOURCE: " + url + "\n" + result["text"]
        else:
            print(f"    [失败] 状态码: {result.get('status')} | 错误: {result.get('error')} | 耗时: {result.get('elapsed_seconds')}s", flush=True)
            record["entity_hits"] = []
        fetched.append(record)

    selected_fields = list(source_row.get("selected_fields") or [])
    extracted, missing = find_field_snippets(row, combined_text)
    known_fields = set(row_fields(row))
    for field in selected_fields:
        if field in known_fields or field in extracted:
            continue
        snip = snippet_around(combined_text, field)
        if snip:
            extracted[field] = [snip]
        elif field not in missing:
            missing.append(field)
    extracted, missing = apply_selected_fields(extracted, missing, selected_fields)
    compact = compact_extracted(extracted)
    entity_results: List[Dict[str, Any]] = []
    for entity in entities:
        text = entity_text.get(entity) or combined_text
        entity_extracted, entity_missing = find_field_snippets(row, text)
        for field in selected_fields:
            if field in known_fields or field in entity_extracted:
                continue
            snip = snippet_around(text, field)
            if snip:
                entity_extracted[field] = [snip]
            elif field not in entity_missing:
                entity_missing.append(field)
        entity_extracted, entity_missing = apply_selected_fields(entity_extracted, entity_missing, selected_fields)
        entity_compact = compact_extracted(entity_extracted)
        for field, value in compact.items():
            entity_compact.setdefault(field, value)
        entity_missing = [field for field in missing if field not in entity_compact]
        entity_results.append(
            {
                "entity": entity,
                "status": "ok" if entity_compact and not entity_missing else ("partial" if entity_compact else "no_extraction"),
                "source_urls": entity_urls.get(entity) or successful_urls,
                "extracted": entity_compact,
                "missing_fields": entity_missing,
                "raw_records": entity_records.get(entity) or [rec for rec in fetched if rec.get("text_sample")][:2],
            }
        )
    status = "ok" if compact else "no_extraction"
    entity_missing_any = [f"{e['entity']}:{','.join(e['missing_fields'])}" for e in entity_results if e["missing_fields"]]
    if compact and (missing or entity_missing_any):
        status = "partial"
    if not successful_urls:
        status = "fetch_failed"

    fetched_at = datetime.now(timezone.utc).isoformat()
    fetched_at_hkt = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat()
    row_result = {
        "row": row,
        "need": source_row["need"],
        "status": status,
        "object": source_row.get("object", ""),
        "entities": entities,
        "selected_fields": selected_fields,
        "source_urls": successful_urls,
        "attempted_urls": urls,
        "extracted": compact,
        "missing_fields": missing,
        "entity_results": entity_results,
        "entity_missing": entity_missing_any,
        "raw_records": fetched,
        "fetched_at": fetched_at,
        "fetched_at_hkt": fetched_at_hkt,
    }
    (RESULTS_DIR / f"row_{row}.json").write_text(
        json.dumps(row_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return row_result


def compact_i_cell(row_result: Dict[str, Any]) -> str:
    lines = [
        f"抓取状态：{row_result['status']}",
        f"抓取时间（香港）：{row_result.get('fetched_at_hkt', row_result['fetched_at'])}",
    ]
    entity_results = row_result.get("entity_results") or []
    if entity_results:
        entity_names = {item["entity"] for item in entity_results}
        compact_many = len(entity_results) > 5
        for entity_result in entity_results:
            lines.append("")
            lines.append(f"【{entity_result['entity']}】")
            lines.append("来源链接：")
            for url in urls_for_entity(entity_result)[: (2 if compact_many else 4)]:
                lines.append(f"- {url}")
            if entity_result["extracted"]:
                lines.append("提取到的数据/证据：")
                display_items = [
                    (field, value)
                    for field, value in entity_result["extracted"].items()
                    if field not in entity_names
                ] or list(entity_result["extracted"].items())
                for field, value in display_items:
                    value = redact_sensitive(value)
                    value_limit = 140 if compact_many else 190
                    lines.append(f"- {field}：{value[:value_limit]}")
            else:
                lines.append("提取到的数据/证据：未从成功返回内容中提取到匹配字段。")
            if entity_result["missing_fields"]:
                lines.append("未命中字段：")
                lines.append("、".join(entity_result["missing_fields"][:16]))
    else:
        lines.append("来源链接：")
        for url in display_source_urls(row_result["source_urls"])[:5]:
            lines.append(f"- {url}")
        if row_result["extracted"]:
            lines.append("提取到的数据/证据：")
            for field, value in row_result["extracted"].items():
                value = redact_sensitive(value)
                lines.append(f"- {field}：{value}")
        else:
            lines.append("提取到的数据/证据：未从成功返回内容中提取到匹配字段。")
    if row_result["missing_fields"] or row_result.get("entity_missing"):
        lines.append("未命中字段：")
        missing_text = "、".join(row_result["missing_fields"][:16])
        if row_result.get("entity_missing"):
            missing_text = (missing_text + "；" if missing_text else "") + "；".join(row_result["entity_missing"])
        lines.append(missing_text)
    return "\n".join(lines)[:30000]


def compact_j_cell(row_result: Dict[str, Any]) -> str:
    if row_result.get("entity_results"):
        grouped = []
        for entity_result in row_result["entity_results"]:
            records = []
            for rec in entity_result.get("raw_records", []):
                if int(rec.get("status") or 0) >= 200 and rec.get("text_sample"):
                    records.append(
                        {
                            "url": rec["url"],
                            "status": rec["status"],
                            "title": rec["title"],
                            "elapsed_seconds": rec.get("elapsed_seconds"),
                            "method": rec.get("method"),
                            "text_sample": rec["text_sample"][:360],
                            "content_hash": rec["content_hash"],
                        }
                    )
                if len(records) >= 2:
                    break
            grouped.append(
                {
                    "entity": entity_result["entity"],
                    "status": entity_result["status"],
                    "records": records,
                }
            )
        return json.dumps(grouped, ensure_ascii=False, separators=(",", ":"))[:18000]
    records = []
    for rec in row_result["raw_records"]:
        if int(rec.get("status") or 0) >= 200 and rec.get("text_sample"):
            records.append(
                {
                    "url": rec["url"],
                    "status": rec["status"],
                    "title": rec["title"],
                    "elapsed_seconds": rec.get("elapsed_seconds"),
                    "method": rec.get("method"),
                    "text_sample": rec["text_sample"][:700],
                    "content_hash": rec["content_hash"],
                }
            )
        if len(records) >= 3:
            break
    if not records and row_result["raw_records"]:
        rec = row_result["raw_records"][0]
        records.append(
            {
                "url": rec["url"],
                "status": rec["status"],
                "title": rec.get("title", ""),
                "elapsed_seconds": rec.get("elapsed_seconds"),
                "method": rec.get("method"),
                "text_sample": rec.get("text_sample", "")[:700],
                "content_hash": rec.get("content_hash", ""),
                "error": rec.get("error", ""),
            }
        )
    return json.dumps(records, ensure_ascii=False, separators=(",", ":"))[:4800]


def compact_log_cell(row_result: Dict[str, Any]) -> str:
    attempted = len(row_result.get("attempted_urls", []))
    success = len(row_result.get("source_urls", []))
    elapsed = 0.0
    for rec in row_result.get("raw_records", []):
        try:
            elapsed += float(rec.get("elapsed_seconds") or 0)
        except (TypeError, ValueError):
            pass
    lines = [
        f"本轮状态：{row_result['status']}",
        f"抓取时间（香港）：{row_result.get('fetched_at_hkt', row_result['fetched_at'])}",
        f"URL成功/尝试：{success}/{attempted}",
        f"累计请求耗时：{elapsed:.1f}s",
        f"本地结果：results/row_{row_result['row']}.json",
    ]
    if row_result.get("log_sheet_title"):
        lines.append(f"飞书日志子表：{row_result['log_sheet_title']}")
    entity_results = row_result.get("entity_results") or []
    if entity_results:
        lines.append("公司覆盖：")
        for item in entity_results:
            lines.append(f"- {item['entity']}：{item['status']}，URL {len(item.get('source_urls', []))}，字段 {len(item.get('extracted', {}))}")
    if row_result.get("missing_fields") or row_result.get("entity_missing"):
        lines.append("缺口：")
        lines.append("、".join(row_result.get("missing_fields", [])) or "；".join(row_result.get("entity_missing", [])))
    return "\n".join(lines)[:4800]


def compact_f_cell(row_result: Dict[str, Any]) -> str:
    entity_results = row_result.get("entity_results") or []
    if entity_results:
        lines = []
        for entity_result in entity_results:
            lines.append(f"【{entity_result['entity']}】")
            urls = urls_for_entity(entity_result) or display_source_urls(row_result.get("source_urls", []))
            for url in urls[:5]:
                lines.append(f"- {url}")
        return "\n".join(lines)[:12000]
    display_urls = display_source_urls(row_result["source_urls"])
    return "\n".join(display_urls) if display_urls else "\n".join(row_result["attempted_urls"])


def write_outputs(row_results: List[Dict[str, Any]]) -> None:
    f_values = []
    ij_values = []
    report_rows = []
    log_rows = []
    for result in row_results:
        row = result["row"]
        f_value = compact_f_cell(result)
        i_value = compact_i_cell(result)
        log_value = compact_log_cell(result)
        j_value = compact_j_cell(result)
        f_values.append([f_value])
        ij_values.append([i_value, log_value, j_value])
        report_rows.append(
            {
                "row": row,
                "status": result["status"],
                "entities": ",".join(result.get("entities", [])),
                "source_urls": f_value,
                "extracted_fields": ",".join(result["extracted"].keys()),
                "missing_fields": ",".join(result["missing_fields"] + result.get("entity_missing", [])),
                "result_file": str(RESULTS_DIR / f"row_{row}.json"),
            }
        )
        for rec in result["raw_records"]:
            log_rows.append(
                {
                    "run_time": result["fetched_at"],
                    "run_time_hkt": result.get("fetched_at_hkt", ""),
                    "row": result["row"],
                    "row_status": result["status"],
                    "url": rec.get("url", ""),
                    "final_url": rec.get("final_url", ""),
                    "http_status": rec.get("status", ""),
                    "method": rec.get("method", ""),
                    "elapsed_seconds": rec.get("elapsed_seconds", ""),
                    "bytes": rec.get("bytes", ""),
                    "title": rec.get("title", ""),
                    "extracted_fields": ",".join(result["extracted"].keys()),
                    "missing_fields": ",".join(result["missing_fields"] + result.get("entity_missing", [])),
                    "content_hash": rec.get("content_hash", ""),
                    "source_policy": rec.get("source_policy", ""),
                    "source_type": rec.get("source_type", ""),
                    "jurisdiction": rec.get("jurisdiction", ""),
                    "tos_status": rec.get("tos_status", ""),
                    "robots_status": rec.get("robots_status", ""),
                    "robots_allowed": rec.get("robots_allowed", ""),
                    "skip_reason": rec.get("skip_reason", ""),
                    "error": rec.get("error", ""),
                }
            )

    (ROOT / "write_payload.json").write_text(
        json.dumps({"F2:F34": f_values, "I2:K34": ij_values}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (ROOT / "coverage_report.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            delimiter="\t",
            fieldnames=["row", "status", "entities", "source_urls", "extracted_fields", "missing_fields", "result_file"],
        )
        writer.writeheader()
        writer.writerows(report_rows)
    with (ROOT / "run_log.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            delimiter="\t",
            fieldnames=[
                "run_time",
                "run_time_hkt",
                "row",
                "row_status",
                "url",
                "final_url",
                "http_status",
                "method",
                "elapsed_seconds",
                "bytes",
                "title",
                "extracted_fields",
                "missing_fields",
                "content_hash",
                "source_policy",
                "source_type",
                "jurisdiction",
                "tos_status",
                "robots_status",
                "robots_allowed",
                "skip_reason",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(log_rows)
    (ROOT / "run_log.json").write_text(json.dumps(log_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for r in row_results if r["status"] == "ok")
    partial = sum(1 for r in row_results if r["status"] == "partial")
    failed = sum(1 for r in row_results if r["status"] not in {"ok", "partial"})
    skipped = sum(1 for r in row_results for rec in r.get("raw_records", []) if rec.get("method") == "skipped")
    crawled = sum(1 for r in row_results for rec in r.get("raw_records", []) if rec.get("method") != "skipped")
    audit = [
        "# CMHK Public Crawl Audit",
        "",
        f"- Generated at: {datetime.now().isoformat()}",
        f"- Rows crawled: {len(row_results)}",
        f"- OK rows: {ok}",
        f"- Partial rows: {partial}",
        f"- Failed/no extraction rows: {failed}",
        f"- URLs fetched after compliance checks: {crawled}",
        f"- URLs skipped by compliance policy: {skipped}",
        f"- Source registry: {SOURCE_REGISTRY_JSON.name}",
        f"- Raw body persistence: {'enabled' if CMHK_SAVE_RAW_BODY else 'disabled'}",
        "",
        "See `coverage_report.tsv` and `results/row_<n>.json` for row-level evidence.",
        "See `run_log.tsv` for per-URL status code, elapsed time, and extraction coverage.",
    ]
    (ROOT / "final_audit.md").write_text("\n".join(audit) + "\n", encoding="utf-8")


def main() -> None:
    RAW_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)
    rows = apply_crawl_settings(apply_row_filter(parse_latest_sheet()))
    (ROOT / "sources.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    deadline = time.monotonic() + MAX_RUN_SECONDS
    client = httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(PER_URL_TIMEOUT_SECONDS, connect=12.0),
        headers={
            "User-Agent": CMHK_USER_AGENT,
            "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
        },
        trust_env=True,
    )
    results = []
    for source_row in rows:
        if time.monotonic() > deadline:
            print(f"global crawl deadline reached after {MAX_RUN_SECONDS}s; stopping before row {source_row['row']}")
            break
        print(f"crawl row {source_row['row']}: {source_row['package']}", flush=True)
        results.append(crawl_row(client, source_row, deadline))
    write_outputs(results)
    print(f"wrote {ROOT / 'write_payload.json'}")
    print(f"wrote {ROOT / 'coverage_report.tsv'}")
    print(f"wrote {ROOT / 'final_audit.md'}")


if __name__ == "__main__":
    main()
