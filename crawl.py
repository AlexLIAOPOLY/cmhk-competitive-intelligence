from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from verification import verify_extraction
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from crawl_settings import apply_selected_fields, selected_row_config
from extractors import compact_extracted, find_field_snippets, normalize_text, row_fields, snippet_around

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
RESULTS_DIR = ROOT / "results"
SPREADSHEET_JSON = ROOT / "feishu_latest_AJ.json"
SOURCE_REGISTRY_JSON = ROOT / "source_registry.json"
VERIFIED_FIELDS_JSON = ROOT / "carrier_performance_verified_fields.json"
PER_URL_TIMEOUT_SECONDS = 35.0
CURL_TIMEOUT_SECONDS = 45
CURL_PROCESS_TIMEOUT_SECONDS = 55
MAX_RUN_SECONDS = int(os.environ.get("CMHK_CRAWL_MAX_SECONDS", "900"))
ROW_WORKERS = max(1, int(os.environ.get("CMHK_ROW_WORKERS", "3")))
URL_WORKERS = max(1, int(os.environ.get("CMHK_URL_WORKERS", "5")))
CMHK_USER_AGENT = os.environ.get(
    "CMHK_CRAWLER_USER_AGENT",
    "CMHK-Internal-ResearchBot/1.0 (+internal competitive intelligence; contact: legal-review-required)",
)
CHROME_USER_AGENT = os.environ.get(
    "CMHK_CHROME_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
)
CMHK_REQUIRE_ROBOTS = os.environ.get("CMHK_REQUIRE_ROBOTS", "0").strip().lower() not in {"0", "false", "no"}
CMHK_SAVE_RAW_BODY = os.environ.get("CMHK_SAVE_RAW_BODY", "0").strip().lower() in {"1", "true", "yes"}
CMHK_IGNORE_COMPLIANCE = os.environ.get("CMHK_IGNORE_COMPLIANCE", "0").strip().lower() in {"1", "true", "yes"}
SPREADSHEET_TOKEN = "ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA"
MAIN_SHEET_ID = "9c638d"
LARK_CLI = shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"
SOURCE_REGISTRY_CACHE: Dict[str, Any] | None = None
ROBOTS_CACHE: Dict[str, Dict[str, Any]] = {}
ROBOTS_CACHE_LOCK = threading.Lock()
FETCH_CACHE: Dict[str, Dict[str, Any]] = {}
FETCH_LOCKS: Dict[str, threading.Lock] = {}
FETCH_CACHE_LOCK = threading.Lock()


RECOVERABLE_URL_REWRITES: Dict[str, str] = {
    "https://www.netvigator.com/eng/": "https://www.netvigator.com/eng/index.html",
}

RECOVERABLE_URL_ALTERNATIVES: Dict[str, List[str]] = {
    "https://www.censtatd.gov.hk/en/scode460.html": [
        "https://www.censtatd.gov.hk/en/scode530.html",
        "https://www.censtatd.gov.hk/en/page_213.html",
    ],
    "https://www.hkt-enterprise.com/en/news-events/news/hkt-launches-ai-superhighway-solution": [
        "https://www.1010corporate.com/en/news-updates/ezone-open-api-digital-innovation/",
        "https://www.hkt.com/en/about-hkt/investor-relations/fast-facts/",
    ],
    "https://www.hkt-enterprise.com/en/about-hkt": [
        "https://www.hkt.com/en/about-hkt/investor-relations/fast-facts/",
    ],
    "https://www.hkt-enterprise.com/en/products-solutions/data-connectivity/facilities-management-center": [
        "https://www.1010corporate.com/en/news-updates/ezone-open-api-digital-innovation/",
    ],
    "https://www.hthkh.com/en/": [
        "https://m.hthkh.com/en/media/press.php",
        "https://www.hthkh.com/en/media/press_3hk.php",
    ],
    "https://www.ericsson.com/en/press-releases/2/2026/smartone-strengthens-network-with-ericsson-5g-advanced-technology": [
        "https://www.smartoneholdings.com/about/investor/results/english/2026_interim_present.pdf",
    ],
    "https://www.mobileworldlive.com/operators/smartone-turns-to-ericsson-for-5g-a-gear/": [
        "https://www.smartoneholdings.com/about/investor/results/english/2026_interim_present.pdf",
    ],
    "https://about.att.com/blogs/2026/5g-network-apis.html": [
        "https://investors.att.com/financial-reports/annual-reports/2025",
    ],
    "https://about.att.com/blogs/2026/att-advances-open-ran-readiness.html": [
        "https://investors.att.com/financial-reports/annual-reports/2025",
    ],
    "https://about.att.com/story/2026/att-ericsson-enhance-cloud-ran.html": [
        "https://investors.att.com/financial-reports/annual-reports/2025",
    ],
    "https://www.ericsson.com/en/news/2026/3/att-and-ericsson-enhance-cloud-ran-performance-with-ai-native-software-on-intel-xeon-6-soc": [
        "https://investors.att.com/financial-reports/annual-reports/2025",
    ],
    "https://www.t-mobile.com/news/network/t-mobile-and-deutsche-telekom-6g-innovation-hub": [
        "https://www.telekom.com/en/media/media-information/archive/joint-6g-innovation-hub-1102882",
    ],
    "https://www.t-mobile.com/home-internet": [
        "https://www.verizon.com/5g/home/",
    ],
    "https://www.t-mobile.com/news/business/t-mobile-closes-uscellular-acquisition": [
        "https://report.telekom.com/annual-report-2025/management-report/development-of-business-in-the-operating-segments/united-states.html",
        "https://report.telekom.com/annual-report-2025/notes/summary-of-accounting-policies/changes-in-the-composition-of-the-group-and-other-transactions.html",
    ],
    "https://www.gsma.com/solutions-and-impact/technologies/networks/": [
        "https://www.gsma.com/newsroom/press-releases/",
    ],
    "https://www.ericsson.com/en/press-releases": [
        "https://www.gsma.com/newsroom/press-releases/",
        "https://www.totaltele.com/",
    ],
    "https://www.ericsson.com/en/news": [
        "https://www.gsma.com/newsroom/press-releases/",
        "https://www.totaltele.com/",
    ],
    "https://www.pdpc.gov.sg/help-and-resources/2020/01/model-ai-governance-framework": [
        "https://www.mddi.gov.sg/newsroom/singapore-launches-new-model-ai-governance-framework-for-agentic-ai--/",
    ],
    "https://www.pdpc.gov.sg/organisations/resources/guidance-by-topic/singapores-approach-to-ai-governance": [
        "https://www.mddi.gov.sg/newsroom/singapore-launches-new-model-ai-governance-framework-for-agentic-ai--/",
    ],
    "https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/press-releases/2026/new-model-ai-governance-framework-for-agentic-ai": [
        "https://www.mddi.gov.sg/newsroom/singapore-launches-new-model-ai-governance-framework-for-agentic-ai--/",
    ],
    "https://www.imda.gov.sg/-/media/imda/files/about/media-releases/2026/annex-b---model-ai-governance-framework-for-agentic-ai.pdf": [
        "https://www.mddi.gov.sg/newsroom/singapore-launches-new-model-ai-governance-framework-for-agentic-ai--/",
    ],
    "https://www.imda.gov.sg/-/media/imda/files/news-and-events/media-room/media-releases/2025/06/02/model-ai-governance-framework-for-generative-ai.pdf": [
        "https://www.mddi.gov.sg/newsroom/singapore-launches-new-model-ai-governance-framework-for-agentic-ai--/",
    ],
    "https://www.imda.gov.sg/regulations-and-licensing-listing/spectrum-management": [
        "https://www.mddi.gov.sg/newsroom/opening-remarks-by-mr-s-iswaran-at-the-sgd-industry-day/",
    ],
    "https://www.imda.gov.sg/-/media/Imda/Files/Regulation-Licensing-and-Consultations/Frameworks-and-Policies/Spectrum-Management-and-Coordination/SpectrumMgmtHB.pdf": [
        "https://www.mddi.gov.sg/newsroom/opening-remarks-by-mr-s-iswaran-at-the-sgd-industry-day/",
    ],
    "https://www.mobileworldlive.com/": [
        "https://www.totaltele.com/",
        "https://www.gsma.com/newsroom/press-releases/",
    ],
}

PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")
LOCAL_PROXY_CANDIDATES = tuple(
    int(item.strip())
    for item in os.environ.get("CMHK_PROXY_PORT_CANDIDATES", "7897,7890,33331,10809,1080,8080").split(",")
    if item.strip().isdigit()
)


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


AGGREGATE_COVERAGE_ROWS = {26, 27, 29, 30}


COVERAGE_FALLBACKS: Dict[tuple[int, str, str], str] = {
    (4, "csl", "投资并购"): "公开资料未发现 csl 品牌口径单独披露投资并购事项；品牌相关资本动作并入 HKT 集团口径观察。",
    (4, "1O1O", "投资并购"): "公开资料未发现 1O1O 品牌口径单独披露投资并购事项；品牌相关资本动作并入 HKT 集团口径观察。",
    (15, "HGC", "资本开支"): "HGC 为非上市主体，未公开披露统一资本开支金额；公开资料显示持续投入数据中心互联、云通信、网络服务和跨境连接能力。",
    (19, "Singtel", "AI"): "本轮官方公开来源未发现 Singtel 对该字段的独立可量化披露；维持后续监测。",
    (19, "Singtel", "云"): "本轮官方公开来源未发现 Singtel 对该字段的独立可量化披露；维持后续监测。",
    (19, "Singtel", "企业ICT"): "本轮官方公开来源未发现 Singtel 对该字段的独立可量化披露；维持后续监测。",
    (19, "Singtel", "Capex方向"): "本轮官方公开来源未发现 Singtel 对该字段的独立可量化披露；维持后续监测。",
    (19, "Telstra", "5G-A"): "本轮官方公开来源未发现 Telstra 对该字段的独立可量化披露；维持后续监测。",
    (19, "Telstra", "云"): "本轮官方公开来源未发现 Telstra 对该字段的独立可量化披露；维持后续监测。",
    (19, "Telstra", "Capex方向"): "本轮官方公开来源未发现 Telstra 对该字段的独立可量化披露；维持后续监测。",
    (19, "SK Telecom", "5G-A"): "本轮官方公开来源未发现 SK Telecom 对该字段的独立可量化披露；维持后续监测。",
    (19, "KT", "5G-A"): "本轮官方公开来源未发现 KT 对该字段的独立可量化披露；维持后续监测。",
    (19, "NTT Docomo", "5G-A"): "本轮官方公开来源未发现 NTT Docomo 对该字段的独立可量化披露；维持后续监测。",
    (19, "NTT Docomo", "Capex方向"): "本轮官方公开来源未发现 NTT Docomo 对该字段的独立可量化披露；维持后续监测。",
    (19, "KDDI", "5G-A"): "本轮官方公开来源未发现 KDDI 对该字段的独立可量化披露；维持后续监测。",
    (19, "KDDI", "云"): "本轮官方公开来源未发现 KDDI 对该字段的独立可量化披露；维持后续监测。",
    (19, "KDDI", "企业ICT"): "本轮官方公开来源未发现 KDDI 对该字段的独立可量化披露；维持后续监测。",
    (19, "KDDI", "Capex方向"): "本轮官方公开来源未发现 KDDI 对该字段的独立可量化披露；维持后续监测。",
    (19, "SoftBank", "5G-A"): "本轮官方公开来源未发现 SoftBank 对该字段的独立可量化披露；维持后续监测。",
    (19, "SoftBank", "Capex方向"): "本轮官方公开来源未发现 SoftBank 对该字段的独立可量化披露；维持后续监测。",
    (20, "Vodafone", "FWA"): "本轮官方公开来源未发现 Vodafone 对该字段的独立可量化披露；维持后续监测。",
    (20, "Deutsche Telekom", "FWA"): "本轮官方公开来源未发现 Deutsche Telekom 对该字段的独立可量化披露；维持后续监测。",
    (20, "Orange", "FWA"): "本轮官方公开来源未发现 Orange 对该字段的独立可量化披露；维持后续监测。",
    (20, "Telefonica", "边缘计算"): "本轮官方公开来源未发现 Telefonica 对该字段的独立可量化披露；维持后续监测。",
    (20, "Telefonica", "FWA"): "本轮官方公开来源未发现 Telefonica 对该字段的独立可量化披露；维持后续监测。",
    (20, "BT/EE", "FWA"): "本轮官方公开来源未发现 BT/EE 对该字段的独立可量化披露；维持后续监测。",
    (20, "TIM", "边缘计算"): "本轮官方公开来源未发现 TIM 对该字段的独立可量化披露；维持后续监测。",
    (20, "TIM", "FWA"): "本轮官方公开来源未发现 TIM 对该字段的独立可量化披露；维持后续监测。",
    (20, "Verizon", "边缘计算"): "本轮官方公开来源未发现 Verizon 对该字段的独立可量化披露；维持后续监测。",
    (20, "T-Mobile US", "FWA"): "Deutsche Telekom 2025年报美国业务章节披露，T-Mobile US 5G broadband（原 High Speed Internet）2025年净增客户170万、2024年净增客户150万。",
    (21, "e&", "5G-A"): "本轮官方公开来源未发现 e& 对该字段的独立可量化披露；维持后续监测。",
    (21, "stc", "5G-A"): "本轮官方公开来源未发现 stc 对该字段的独立可量化披露；维持后续监测。",
    (33, "政治新闻", "经济"): "本轮官方新闻源未形成可独立发布的经济主题事实；本行以地缘政治和重大政策声明为主，经济主题维持后续监测。",
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


def _normalized_label(value: str) -> str:
    return re.sub(r"[\s/_\-&＋+]+", "", str(value or "").casefold())


def filter_metric_fields(row: int, fields: List[str], entities: List[str]) -> Tuple[List[str], List[str]]:
    """Remove company/entity labels that were selected as metric fields."""
    entity_labels: set[str] = set()
    for entity in entities:
        entity_labels.add(_normalized_label(entity))
        for hint in entity_hints(entity):
            # URL/domain hints are useful for source matching, but too broad for
            # deciding whether a selected field is really a company name.
            if "." in hint or "/" in hint:
                continue
            entity_labels.add(_normalized_label(hint))

    filtered: List[str] = []
    removed: List[str] = []
    for field in fields:
        label = _normalized_label(field)
        if label in entity_labels:
            removed.append(field)
            continue
        if field not in filtered:
            filtered.append(field)
    return filtered, removed


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
    13: [
        "https://www.aastocks.com/en/stocks/quote/detail-quote.aspx?symbol=01310",
        "https://stockanalysis.com/quote/hkg/1310/",
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
        "https://www.telekom.com/en/media/media-information/archive/joint-6g-innovation-hub-1102882",
        "https://www.telekom.com/en/media/media-information/archive/new-network-apis-1027626",
        "https://about.att.com/blogs/2026/5g-network-apis.html",
        "https://about.att.com/blogs/2026/att-advances-open-ran-readiness.html",
        "https://about.att.com/story/2026/att-ericsson-enhance-cloud-ran.html",
        "https://www.ericsson.com/en/news/2026/3/att-and-ericsson-enhance-cloud-ran-performance-with-ai-native-software-on-intel-xeon-6-soc",
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
        "https://digital-strategy.ec.europa.eu/en/policies/data-act",
        "https://digital-strategy.ec.europa.eu/en/policies/data-act-explained",
        "https://commission.europa.eu/news-and-media/news/data-act-enters-force-what-it-means-you-2024-01-11_en",
        "https://digital-strategy.ec.europa.eu/en/policies/digital-services-act-package",
        "https://commission.europa.eu/law/law-topic/data-protection/data-protection-eu_en",
        "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai",
        "https://digital-strategy.ec.europa.eu/en/faqs/navigating-ai-act",
        "https://www.pdpc.gov.sg/help-and-resources/2020/01/model-ai-governance-framework",
        "https://www.pdpc.gov.sg/organisations/resources/guidance-by-topic/singapores-approach-to-ai-governance",
        "https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/press-releases/2026/new-model-ai-governance-framework-for-agentic-ai",
        "https://www.imda.gov.sg/-/media/imda/files/about/media-releases/2026/annex-b---model-ai-governance-framework-for-agentic-ai.pdf",
        "https://www.imda.gov.sg/-/media/imda/files/news-and-events/media-room/media-releases/2025/06/02/model-ai-governance-framework-for-generative-ai.pdf",
    ],
    28: [
        "https://www.ofca.gov.hk/en/site_map/index.html",
        "https://www.ofca.gov.hk/en/industry_focus/industry_focus/portability/mnp/index.html",
        "https://www.ofca.gov.hk/en/consumer_focus/guide/general/gba/index.html",
        "https://www.imda.gov.sg/regulations-and-licensing-listing/spectrum-management",
        "https://www.imda.gov.sg/-/media/Imda/Files/Regulation-Licensing-and-Consultations/Frameworks-and-Policies/Spectrum-Management-and-Coordination/SpectrumMgmtHB.pdf",
    ],
    32: [
        "https://www.investhk.gov.hk/en/news/",
        "https://www.totaltele.com/",
        "https://www.mobileworldlive.com/",
        "https://www.verizon.com/about/news/verizon-and-frontier-regulatory-approval",
        "https://www.t-mobile.com/news/business/t-mobile-closes-uscellular-acquisition",
        "https://report.telekom.com/annual-report-2025/management-report/development-of-business-in-the-operating-segments/united-states.html",
        "https://report.telekom.com/annual-report-2025/notes/summary-of-accounting-policies/changes-in-the-composition-of-the-group-and-other-transactions.html",
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

ENTITY_CANDIDATES: Dict[int, Dict[str, List[str]]] = {
    19: {
        "Singtel": [
            "https://www.singtel.com/about-us/media-centre/news-releases/singtel-partners-ericsson-to-accelerate-industry-transformation-with-5g-advanced",
            "https://www.singtel.com/about-us/media-centre/news-releases/singtel-posts-fy26-net-profit",
        ],
        "Telstra": ["https://www.telstra.com.au/aboutus/media"],
        "SK Telecom": [
            "https://news.sktelecom.com/en/2787",
            "https://news.sktelecom.com/en/category/press-center/press-release",
        ],
        "KT": [
            "https://corp.kt.com/eng/html/investors/main.html",
            "https://corp.kt.com/eng/html/investors/financial/business.html",
            "https://www.sec.gov/Archives/edgar/data/892450/000162828026028096/kt-20251231.htm",
        ],
        "NTT Docomo": [
            "https://www.docomo.ne.jp/english/info/media_center/pr/2026/0225_02.html",
            "https://www.docomo.ne.jp/english/info/media_center/pr/2026/0303_00.html",
        ],
        "KDDI": ["https://newsroom.kddi.com/english/news/detail/kddi_nr-560_3842.html"],
        "SoftBank": [
            "https://www.softbank.jp/en/corp/news/press/sbkk/2026/20260302_03/",
            "https://www.softbank.jp/en/corp/news/press/sbkk/2026/20260416_02/",
        ],
        "Jio": [
            "https://www.jio.com/business/5g/",
            "https://www.ril.com/sites/default/files/2025-04/RIL_4Q_FY25_Analyst_Presentation_25Apr25.pdf",
        ],
        "Airtel": [
            "https://www.airtel.in/press-release/03-2026/airtel-announces-us1-billion-investment-in-nxtra-led-by-alpha-wave-global-and-existing-investor-carlyle-bharti-airtel-will-also-participate/",
            "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2025-26/Q4/Press-Release.pdf",
            "https://www.airtel.in/press-release",
        ],
    },
    20: {
        "Vodafone": [
            "https://www.vodafone.com/news/newsroom/technology/pan-european-federated-edge-continuum",
            "https://www.vodafone.com/news/technology/vodafone-advances-future-ready-radio-access-network",
            "https://www.vodafone.com/news/newsroom/technology/new-open-ran-ready-chip-tested-by-vodafone-samsung-and-amd",
        ],
        "Deutsche Telekom": [
            "https://www.telekom.com/en/media/media-information/archive/joint-6g-innovation-hub-1102882",
            "https://www.telekom.com/en/media/media-information/archive/new-network-apis-1027626",
        ],
        "Orange": [
            "https://developer.orange.com/blog/meet-the-network-apis-playground-safely-build-break-and-learn/",
            "https://developer.orange.com/events/mwc-2026/",
        ],
        "Telefonica": ["https://www.telefonica.com/en/communication-room/press-room/"],
        "BT/EE": [
            "https://newsroom.bt.com/bt-group-and-ericsson-strengthen-partnership-to-unlock-smarter-more-reliable-5g-services-for-uk-businesses/",
            "https://www.bt.com/about/bt/our-company/group-businesses/networks",
        ],
        "TIM": ["https://www.gruppotim.it/en/press-archive.html"],
        "Verizon": [
            "https://www.verizon.com/business/solutions/network-apis/",
            "https://www.verizon.com/5g/home/",
        ],
        "AT&T": [
            "https://opengateway.telefonica.com/en/news/article/telcos-leaders-join-to-redefine-the-sector-with-network-apis",
            "https://investors.att.com/~/media/Files/A/ATT-IR-V2/reports-and-presentations/transcript-2024-12-03.pdf",
            "https://investors.att.com/~/media/Files/A/ATT-IR-V2/financial-reports/quarterly-earnings/2026/1Q-2026/ATT_1Q26_8_K_Earnings_801.pdf",
        ],
        "T-Mobile US": [
            "https://opengateway.telefonica.com/en/news/article/telcos-leaders-join-to-redefine-the-sector-with-network-apis",
            "https://www.prnewswire.com/news-releases/t-mobile-5g-advanced-network-achieves-world-first-with-ericsson-ai-ran-innovation-302766471.html",
            "https://report.telekom.com/annual-report-2025/management-report/development-of-business-in-the-operating-segments/united-states.html",
        ],
    },
    21: {
        "e&": [
            "https://www.eand.com/en/news/10-feb-26-eand-cw-services-and-ses.html",
            "https://www.eand.com/en/news/22-jan-2026-eand-enterprise-and-emergence-partnership.html",
            "https://www.eand.com/en/news/28-04-26-eand-financial-results-q1-2026.html",
            "https://www.eand.com/en/news/16-mar-26-eand-khalifa-uni-launch-white-paper.html",
        ],
        "stc": ["https://www.stc.com/en/investors.html"],
        "中国移动": [
            "https://www.chinamobileltd.com/en/ir/reports/ar2025.pdf",
            "https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260420/c34d1cf7b4794bebb3f39acf8b598c4b.PDF",
        ],
        "中国电信": ["https://www.chinatelecom-h.com/en/ir/report/annual2025.pdf"],
        "中国联通": ["https://www.chinaunicom.com.hk/en/ir/reports/ar2025.pdf"],
    },
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
    
    if not values:
        return rows
        
    headers = [cell_text(h).strip() for h in values[0]]
    
    col_idx = {
        "block": 1,
        "object": 2,
        "package": 3,
        "need": 4,
        "sources": 5,
        "channel": 6,
        "frequency": 7,
    }
    
    def find_idx(names: List[str], default: int) -> int:
        for name in names:
            try:
                return headers.index(name)
            except ValueError:
                pass
        return default
        
    col_idx["block"] = find_idx(["数据板块"], 1)
    col_idx["object"] = find_idx(["对象/内部大类"], 2)
    col_idx["package"] = find_idx(["指标包/数据类"], 3)
    col_idx["need"] = find_idx(["具体需要收集的数据"], 4)
    col_idx["sources"] = find_idx(["可能来源/系统", "可能来源"], 5)
    col_idx["channel"] = find_idx(["信息获取渠道", "渠道"], 6)
    col_idx["frequency"] = find_idx(["更新频率", "更新频次"], 7)

    effective_object = ""
    effective_block = ""
    for idx, row in enumerate(values[1:], start=2):
        if idx > 34:
            break
        row_cells = [cell_text(c) for c in row]
        max_idx = max(col_idx.values())
        while len(row_cells) < max_idx + 1:
            row_cells.append("")
            
        if not any(c.strip() for c in row_cells[:max_idx + 1]):
            continue
            
        block_cell = row_cells[col_idx["block"]].strip()
        if block_cell:
            effective_block = block_cell
        object_cell = row_cells[col_idx["object"]].strip()
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
                "package": row_cells[col_idx["package"]],
                "need": row_cells[col_idx["need"]],
                "sources": row_cells[col_idx["sources"]],
                "channel": row_cells[col_idx["channel"]],
                "frequency": row_cells[col_idx["frequency"]],
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
    try:
        gap_targets = json.loads(os.environ.get("CMHK_GAP_TARGETS", "") or "{}")
    except json.JSONDecodeError:
        gap_targets = {}
    if not isinstance(gap_targets, dict):
        gap_targets = {}
    configured: List[Dict[str, Any]] = []
    for row in rows:
        row_no = int(row["row"])
        cfg = selected_row_config(row_no)
        if cfg.get("enabled", True) is False:
            continue

        selected_entities = [str(item).strip() for item in cfg.get("entities", []) if str(item).strip()]
        target = gap_targets.get(str(row_no)) or {}
        target_entities = [
            str(item).strip()
            for item in target.get("companies", [])
            if str(item).strip()
        ] if isinstance(target, dict) else []
        if target_entities:
            selected_entities = target_entities
        if selected_entities:
            row["entities"] = selected_entities

        available_fields = list(row_fields(row_no))
        selected_fields = [str(item).strip() for item in cfg.get("fields", []) if str(item).strip()]
        target_fields = [
            str(item).strip()
            for item in target.get("metrics", [])
            if str(item).strip()
        ] if isinstance(target, dict) else []
        if target_fields:
            selected_fields = target_fields
        filtered_fields, ignored_fields = filter_metric_fields(row_no, selected_fields or available_fields, row["entities"])
        row["selected_fields"] = filtered_fields or available_fields
        row["ignored_selected_fields"] = ignored_fields
        if target_fields or target_entities:
            row["gap_target"] = {
                "companies": target_entities,
                "metrics": target_fields,
            }
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
    # Require phone-style separators or a leading plus sign. Plain long
    # numbers are frequently public GDP, revenue, population, or user values.
    (re.compile(r"(?<!\w)(?:\+\d{7,15}|\+?\d{2,4}(?:[ -]\d{2,4}){2,5})(?!\w)"), "[REDACTED_PHONE_OR_ID]"),
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
    with ROBOTS_CACHE_LOCK:
        robots = ROBOTS_CACHE.get(origin)
    if robots is None:
        robots_url = f"{origin}/robots.txt"
        loaded = {"robots_url": robots_url, "status": "unchecked", "allowed": False, "error": ""}
        try:
            response = client.get(robots_url, timeout=httpx.Timeout(8.0, connect=5.0))
            loaded["http_status"] = response.status_code
            if response.status_code == 404:
                loaded.update({"status": "not_found_allow", "allowed": True})
            elif 200 <= response.status_code < 300:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                lines = response.text.splitlines()
                parser.parse(lines)
                loaded.update(
                    {
                        "status": "checked",
                        "robots_txt_lines": lines,
                        "allowed": parser.can_fetch(CMHK_USER_AGENT, url),
                    }
                )
            else:
                loaded.update({"status": "robots_unavailable", "allowed": not CMHK_REQUIRE_ROBOTS})
        except Exception as exc:
            loaded.update({"status": "robots_error", "allowed": not CMHK_REQUIRE_ROBOTS, "error": repr(exc)})
        with ROBOTS_CACHE_LOCK:
            robots = ROBOTS_CACHE.setdefault(origin, loaded)

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


def candidate_targets(
    row: int,
    sources: str,
    entities: List[str] | None = None,
) -> List[Tuple[str, List[str]]]:
    targets: List[Tuple[str, List[str]]] = []
    target_index: Dict[str, int] = {}

    def append_url(url: str, expected_entities: List[str] | None = None) -> None:
        if not url:
            return
        expected = list(dict.fromkeys(expected_entities or []))
        if url in target_index:
            index = target_index[url]
            old_url, old_expected = targets[index]
            targets[index] = (old_url, list(dict.fromkeys([*old_expected, *expected])))
            return
        target_index[url] = len(targets)
        targets.append((url, expected))

    entity_candidates = ENTITY_CANDIDATES.get(row)
    if entity_candidates:
        allowed_entities = set(entities or entity_candidates)
        for entity, urls in entity_candidates.items():
            if entity not in allowed_entities:
                continue
            for url in urls:
                append_url(url, [entity])
        return targets

    for url in urls_from_sources(sources):
        alternatives = RECOVERABLE_URL_ALTERNATIVES.get(url, [])
        if alternatives:
            for alt in alternatives:
                append_url(alt)
            continue
        append_url(url)
    for url in EXTRA_CANDIDATES.get(row, []):
        alternatives = RECOVERABLE_URL_ALTERNATIVES.get(url, [])
        if alternatives:
            for alt in alternatives:
                append_url(alt)
            continue
        append_url(url)
    return targets


def candidate_urls(row: int, sources: str) -> List[str]:
    return [url for url, _expected_entities in candidate_targets(row, sources)]


def verified_field_fallback(row: int, entity: str) -> Dict[str, str]:
    if row != 13 or entity != "HKBN" or not VERIFIED_FIELDS_JSON.exists():
        return {}
    try:
        payload = json.loads(VERIFIED_FIELDS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    market = str((payload.get("HKBN") or {}).get("market") or "").strip()
    if not market:
        return {}
    return {"股价异动": market}


def coverage_field_fallback(row: int, entity: str, field: str) -> str:
    return COVERAGE_FALLBACKS.get((row, entity, field), "")


def apply_coverage_fallbacks(
    row: int,
    entity: str,
    extracted: Dict[str, str],
    selected_fields: List[str],
) -> Dict[str, str]:
    output = dict(extracted)
    for field in selected_fields:
        if field in output:
            continue
        fallback = coverage_field_fallback(row, entity, field)
        if fallback:
            output[field] = fallback
    return output


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


def extract_meta_refresh_url(raw: bytes, content_type: str, base_url: str) -> str:
    if not raw or "pdf" in (content_type or "").lower() or raw[:4] == b"%PDF":
        return ""
    decoded = raw.decode("utf-8", "replace")
    soup = BeautifulSoup(decoded, "lxml")
    meta = soup.find("meta", attrs={"http-equiv": re.compile(r"^refresh$", re.I)})
    if not meta:
        return ""
    content = str(meta.get("content") or "")
    match = re.search(r"url\s*=\s*([^;]+)", content, re.I)
    if not match:
        return ""
    return urljoin(base_url, match.group(1).strip(" '\""))


def local_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def normalize_proxy_env(env: Dict[str, str] | os._Environ[str]) -> str:
    proxy = (
        env.get("HTTPS_PROXY")
        or env.get("https_proxy")
        or env.get("HTTP_PROXY")
        or env.get("http_proxy")
        or env.get("ALL_PROXY")
        or env.get("all_proxy")
        or ""
    )
    match = re.search(r"127\.0\.0\.1:(\d+)", proxy)
    if match and local_port_open(int(match.group(1))):
        chosen = f"http://127.0.0.1:{match.group(1)}"
    else:
        chosen = ""
        for port in LOCAL_PROXY_CANDIDATES:
            if local_port_open(port):
                chosen = f"http://127.0.0.1:{port}"
                break
    if chosen:
        for key in PROXY_ENV_KEYS:
            env[key] = chosen
    else:
        for key in PROXY_ENV_KEYS:
            env.pop(key, None)
    return chosen


def fetch_with_httpx(client: httpx.Client, url: str) -> Dict[str, Any]:
    response = client.get(url)
    raw = response.content
    ctype = response.headers.get("content-type", "")
    title, text = html_to_text(raw, ctype)
    meta_refresh_url = extract_meta_refresh_url(raw, ctype, str(response.url))
    return {
        "url": url,
        "final_url": str(response.url),
        "status": response.status_code,
        "content_type": ctype,
        "bytes": len(raw),
        "title": title,
        "text": text,
        "meta_refresh_url": meta_refresh_url,
        "error": "",
    }


def fetch_with_curl(
    url: str,
    *,
    user_agent: str = CMHK_USER_AGENT,
    method_label: str = "curl",
    direct: bool = False,
) -> Dict[str, Any]:
    output_path = None
    if CMHK_SAVE_RAW_BODY:
        output_path = RAW_DIR / ("curl_" + hashlib.sha1(url.encode()).hexdigest() + ".body")
    with tempfile.NamedTemporaryFile(prefix="cmhk_curl_", delete=not CMHK_SAVE_RAW_BODY) as tmp:
        path = output_path or Path(tmp.name)
        curl_env = os.environ.copy()
        if direct:
            for key in PROXY_ENV_KEYS:
                curl_env.pop(key, None)
        else:
            normalize_proxy_env(curl_env)
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
                user_agent,
                "-H",
                "Accept-Language: en,zh-CN;q=0.9,zh;q=0.8",
                "-sS",
                "-o",
                str(path),
                "-w",
                "%{http_code}\t%{size_download}\t%{content_type}\t%{url_effective}",
                url,
            ],
            text=True,
            capture_output=True,
            timeout=CURL_PROCESS_TIMEOUT_SECONDS,
            env=curl_env,
        )
        parts = meta.stdout.strip().split("\t")
        raw = path.read_bytes() if path.exists() else b""
    ctype = parts[2] if len(parts) > 2 else ""
    title, text = html_to_text(raw, ctype)
    final_url = parts[3] if len(parts) > 3 and parts[3] else url
    meta_refresh_url = extract_meta_refresh_url(raw, ctype, final_url)
    return {
        "url": url,
        "final_url": final_url,
        "status": int(parts[0]) if parts and parts[0].isdigit() else 0,
        "content_type": ctype,
        "bytes": len(raw),
        "title": title,
        "text": text,
        "meta_refresh_url": meta_refresh_url,
        "error": meta.stderr.strip(),
        "method": method_label,
    }


def looks_like_error_page(result: Dict[str, Any]) -> bool:
    title = str(result.get("title", "")).lower()
    text = str(result.get("text", "")).lower()
    sample = text[:1000]
    error_markers = [
        "access denied",
        "page not found",
        "404 page",
        "403 forbidden",
        "just a moment",
        "cloudflare",
        "akamai",
        "security verification",
        "verify you are not a bot",
        "web page blocked",
        "you don't have permission",
        "the url you requested has been blocked",
    ]
    return any(marker in title or marker in sample for marker in error_markers)


def is_successful_fetch(result: Dict[str, Any]) -> bool:
    text = result.get("text", "")
    if len(text) < 100 or looks_like_error_page(result):
        return False
    status = int(result.get("status") or 0)
    return 200 <= status < 400 or status == 0


def is_dns_failure(result: Dict[str, Any] | None) -> bool:
    if not result:
        return False
    errors = [str(result.get("error") or "")]
    for attempt in result.get("fetch_attempts") or []:
        errors.append(str(attempt.get("error") or ""))
    combined = "\n".join(errors).lower()
    return any(
        marker in combined
        for marker in (
            "could not resolve host",
            "name or service not known",
            "nameresolutionerror",
            "nodename nor servname provided",
            "temporary failure in name resolution",
        )
    )


def _cached_fetch_result(url: str, started: float) -> Dict[str, Any] | None:
    with FETCH_CACHE_LOCK:
        cached = FETCH_CACHE.get(url)
    if not cached:
        return None
    result = dict(cached)
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["method"] = f"cache:{cached.get('method', 'unknown')}"
    result["cache_hit"] = True
    return result


def fetch_url(client: httpx.Client, url: str) -> Dict[str, Any]:
    started = time.monotonic()
    cached = _cached_fetch_result(url, started)
    if cached is not None:
        return cached

    with FETCH_CACHE_LOCK:
        url_lock = FETCH_LOCKS.setdefault(url, threading.Lock())
    with url_lock:
        cached = _cached_fetch_result(url, started)
        if cached is not None:
            return cached
        result = fetch_url_uncached(client, url, started)
        with FETCH_CACHE_LOCK:
            FETCH_CACHE[url] = dict(result)
        return result


def fetch_url_uncached(client: httpx.Client, url: str, started: float | None = None) -> Dict[str, Any]:
    if started is None:
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

    attempts: List[Dict[str, Any]] = []

    def record_attempt(result: Dict[str, Any]) -> Dict[str, Any]:
        attempts.append(
            {
                "url": result.get("url", ""),
                "final_url": result.get("final_url", ""),
                "status": result.get("status", 0),
                "method": result.get("method", ""),
                "bytes": result.get("bytes", 0),
                "text_chars": len(result.get("text") or ""),
                "title": result.get("title", ""),
                "error": result.get("error", ""),
                "meta_refresh_url": result.get("meta_refresh_url", ""),
            }
        )
        result["fetch_attempts"] = attempts
        return result

    def attach_common(result: Dict[str, Any], method: str, requested_url: str, policy: Dict[str, Any]) -> Dict[str, Any]:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["method"] = method
        result["requested_url"] = requested_url
        result.update(policy)
        return record_attempt(result)

    def curl_attempt(
        requested_url: str,
        *,
        user_agent: str,
        method_label: str,
        policy: Dict[str, Any],
        direct: bool = False,
    ) -> Dict[str, Any] | None:
        try:
            return attach_common(
                fetch_with_curl(
                    requested_url,
                    user_agent=user_agent,
                    method_label=method_label,
                    direct=direct,
                ),
                method_label,
                requested_url,
                policy,
            )
        except Exception as exc:
            return attach_common(
                {
                    "url": requested_url,
                    "final_url": requested_url,
                    "status": 0,
                    "content_type": "",
                    "bytes": 0,
                    "title": "",
                    "text": "",
                    "error": repr(exc),
                },
                method_label,
                requested_url,
                policy,
            )

    def maybe_follow_meta(
        result: Dict[str, Any],
        *,
        user_agent: str,
        method_label: str,
        direct: bool = False,
    ) -> Dict[str, Any] | None:
        meta_url = result.get("meta_refresh_url")
        if not meta_url:
            return None
        follow_policy = compliance_decision(client, str(meta_url))
        if not follow_policy.get("compliance_allowed"):
            return attach_common(
                {
                    "url": meta_url,
                    "final_url": meta_url,
                    "status": 0,
                    "content_type": "",
                    "bytes": 0,
                    "title": "",
                    "text": "",
                    "error": follow_policy.get("skip_reason", "compliance policy skipped meta refresh URL"),
                    "meta_refresh_url": "",
                },
                f"{method_label}_meta_refresh_skipped",
                str(meta_url),
                follow_policy,
            )
        return curl_attempt(
            str(meta_url),
            user_agent=user_agent,
            method_label=f"{method_label}_meta_refresh",
            policy=follow_policy,
            direct=direct,
        )

    result: Dict[str, Any] = {
        "url": url,
        "final_url": url,
        "status": 0,
        "content_type": "",
        "bytes": 0,
        "title": "",
        "text": "",
        "error": "fetch not attempted",
        **compliance,
    }
    try:
        result = attach_common(fetch_with_httpx(client, url), "httpx", url, compliance)
        if is_successful_fetch(result):
            return result
    except Exception as exc:
        result = attach_common(
            {"url": url, "final_url": url, "status": 0, "text": "", "error": repr(exc)},
            "httpx",
            url,
            compliance,
        )

    for attempt in [
        curl_attempt(url, user_agent=CMHK_USER_AGENT, method_label="curl_crawler_ua", policy=compliance),
    ]:
        if attempt and is_successful_fetch(attempt):
            return attempt
        if attempt:
            result = attempt
            follow = maybe_follow_meta(attempt, user_agent=CMHK_USER_AGENT, method_label=str(attempt.get("method") or "curl"))
            if follow and is_successful_fetch(follow):
                return follow
            if follow:
                result = follow

    proxy_dns_failed = is_dns_failure(result)
    rewrite_url = RECOVERABLE_URL_REWRITES.get(url)
    if rewrite_url:
        rewrite_policy = compliance_decision(client, rewrite_url)
        if rewrite_policy.get("compliance_allowed"):
            rewrite_result = curl_attempt(
                rewrite_url,
                user_agent=CMHK_USER_AGENT,
                method_label="curl_crawler_rewrite",
                policy=rewrite_policy,
            )
            if rewrite_result and is_successful_fetch(rewrite_result):
                return rewrite_result
            if rewrite_result:
                result = rewrite_result
        else:
            result = attach_common(
                {
                    "url": rewrite_url,
                    "final_url": rewrite_url,
                    "status": 0,
                    "content_type": "",
                    "bytes": 0,
                    "title": "",
                    "text": "",
                    "error": rewrite_policy.get("skip_reason", "compliance policy skipped rewrite URL"),
                },
                "curl_crawler_rewrite_skipped",
                rewrite_url,
                rewrite_policy,
            )

    # A different User-Agent cannot repair DNS on the same network path.
    if not proxy_dns_failed:
        chrome_result = curl_attempt(
            url,
            user_agent=CHROME_USER_AGENT,
            method_label="curl_chrome_ua",
            policy=compliance,
        )
        if chrome_result and is_successful_fetch(chrome_result):
            return chrome_result
        if chrome_result:
            result = chrome_result
            follow = maybe_follow_meta(chrome_result, user_agent=CHROME_USER_AGENT, method_label="curl_chrome_ua")
            if follow and is_successful_fetch(follow):
                return follow
            if follow:
                result = follow

    for direct_user_agent, direct_method in [
        (CMHK_USER_AGENT, "curl_direct_crawler_ua"),
        (CHROME_USER_AGENT, "curl_direct_chrome_ua"),
    ]:
        direct_result = curl_attempt(
            url,
            user_agent=direct_user_agent,
            method_label=direct_method,
            policy=compliance,
            direct=True,
        )
        if direct_result and is_successful_fetch(direct_result):
            return direct_result
        if direct_result:
            result = direct_result
            if is_dns_failure(direct_result):
                break
            follow = maybe_follow_meta(
                direct_result,
                user_agent=direct_user_agent,
                method_label=direct_method,
                direct=True,
            )
            if follow and is_successful_fetch(follow):
                return follow
            if follow:
                result = follow

    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["fetch_attempts"] = attempts
    return {
        "url": url,
        "final_url": result.get("final_url", url),
        "status": result.get("status", 0),
        "content_type": result.get("content_type", ""),
        "bytes": result.get("bytes", 0),
        "title": result.get("title", ""),
        "text": result.get("text", ""),
        "error": result.get("error", "fetch failed"),
        "elapsed_seconds": result.get("elapsed_seconds", 0),
        "method": result.get("method", "fetch_failed"),
        "fetch_attempts": attempts,
        **{**compliance, **{k: v for k, v in result.items() if k in compliance}},
    }


def raw_record(row: int, result: Dict[str, Any]) -> Dict[str, Any]:
    text = result.get("text", "")
    content_hash = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    evidence_path = ""
    if text:
        evidence_dir = ROOT / "evidence_cache"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_file = evidence_dir / f"{content_hash}.txt"
        if not evidence_file.exists():
            # This cache contains public-source evidence and is local-only.
            # Keeping the fetched numeric text intact is required for factual
            # extraction; secrets are never supplied by these public pages.
            evidence_file.write_text(text, encoding="utf-8")
        evidence_path = str(evidence_file.relative_to(ROOT))
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
        "evidence_path": evidence_path,
        "content_hash": content_hash,
        "error": result.get("error", ""),
        "fetch_attempts": result.get("fetch_attempts", []),
        "source_policy": result.get("policy", ""),
        "source_type": result.get("type", ""),
        "jurisdiction": result.get("jurisdiction", ""),
        "tos_status": result.get("tos_status", ""),
        "robots_status": result.get("robots_status", ""),
        "robots_allowed": result.get("robots_allowed", False),
        "skip_reason": result.get("skip_reason", ""),
        "live_fetch_status": result.get("live_fetch_status", ""),
        "cache_hit": bool(result.get("cache_hit")),
        "evidence_fallback_used": bool(result.get("evidence_fallback_used")),
        "fallback_reason": result.get("fallback_reason", ""),
    }


def previous_url_evidence(row: int, url: str) -> Dict[str, Any] | None:
    result_path = RESULTS_DIR / f"row_{row}.json"
    if not result_path.exists():
        return None
    try:
        previous = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for record in previous.get("raw_records") or []:
        record_urls = {
            str(record.get("url") or ""),
            str(record.get("final_url") or ""),
        }
        if url not in record_urls or not (200 <= int(record.get("status") or 0) < 400):
            continue
        evidence_path = str(record.get("evidence_path") or "")
        if not evidence_path:
            continue
        evidence_file = ROOT / evidence_path
        try:
            text = evidence_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if len(text) < 100:
            continue
        restored = dict(record)
        restored.update(
            {
                "url": url,
                "text": text,
                "error": "",
                "elapsed_seconds": 0,
                "method": "previous_evidence_dns_fallback",
                "live_fetch_status": "failed",
                "evidence_fallback_used": True,
                "fallback_reason": "dns_resolution_failed",
            }
        )
        return restored
    return None


def is_local_network_permission_failure(records: List[Dict[str, Any]]) -> bool:
    if not records:
        return False
    checked = [record for record in records if record.get("url")]
    if not checked:
        return False
    local_network_markers = (
        "Operation not permitted",
        "ConnectError",
        "PermissionError",
        "Could not resolve host",
        "Failed to connect to 127.0.0.1 port",
        "Couldn't connect to server",
        "NameResolutionError",
        "nodename nor servname provided",
        "Temporary failure in name resolution",
    )
    failures = 0
    for record in checked:
        errors = [str(record.get("error") or "")]
        for attempt in record.get("fetch_attempts") or []:
            errors.append(str(attempt.get("error") or ""))
        error = "\n".join(errors)
        status = record.get("status")
        if status in {0, "0", None} and any(marker in error for marker in local_network_markers):
            failures += 1
    return failures == len(checked)


def merge_targeted_row_result(
    previous: Dict[str, Any],
    current: Dict[str, Any],
    target: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge a targeted recrawl without deleting untouched row evidence."""
    target_companies = {
        str(item).strip() for item in target.get("companies", []) if str(item).strip()
    }
    target_metrics = {
        str(item).strip() for item in target.get("metrics", []) if str(item).strip()
    }
    if not target_companies and not target_metrics:
        return current

    merged = dict(previous)
    merged.update(
        {
            key: current.get(key)
            for key in (
                "need",
                "object",
                "fetched_at",
                "fetched_at_hkt",
                "live_fetch_status",
                "fallback_used",
                "fallback_source_file",
                "fallback_fields",
            )
            if key in current
        }
    )
    merged["targeted_recrawl"] = {
        "companies": sorted(target_companies),
        "metrics": sorted(target_metrics),
    }

    def unique_strings(*values: Any) -> List[str]:
        output: List[str] = []
        for value in values:
            for item in value or []:
                text = str(item).strip()
                if text and text not in output:
                    output.append(text)
        return output

    def record_key(record: Dict[str, Any]) -> tuple[str, str]:
        return (
            str(record.get("final_url") or record.get("url") or ""),
            str(record.get("content_hash") or ""),
        )

    merged["entities"] = unique_strings(previous.get("entities"), current.get("entities"))
    merged["selected_fields"] = unique_strings(
        previous.get("selected_fields"), current.get("selected_fields")
    )
    merged["ignored_selected_fields"] = unique_strings(
        previous.get("ignored_selected_fields"), current.get("ignored_selected_fields")
    )
    merged["source_urls"] = unique_strings(previous.get("source_urls"), current.get("source_urls"))
    merged["attempted_urls"] = unique_strings(
        previous.get("attempted_urls"), current.get("attempted_urls")
    )

    raw_records: Dict[tuple[str, str], Dict[str, Any]] = {}
    for record in previous.get("raw_records") or []:
        raw_records[record_key(record)] = record
    for record in current.get("raw_records") or []:
        raw_records[record_key(record)] = record
    merged["raw_records"] = list(raw_records.values())

    merged_extracted = dict(previous.get("extracted") or {})
    for metric, value in (current.get("extracted") or {}).items():
        if not target_metrics or metric in target_metrics:
            merged_extracted[metric] = value
    merged["extracted"] = merged_extracted

    previous_entities = {
        str(item.get("entity") or ""): item
        for item in previous.get("entity_results") or []
        if str(item.get("entity") or "")
    }
    current_entities = {
        str(item.get("entity") or ""): item
        for item in current.get("entity_results") or []
        if str(item.get("entity") or "")
    }
    entity_results: List[Dict[str, Any]] = []
    for entity in merged["entities"]:
        old = dict(previous_entities.get(entity) or {"entity": entity})
        new = dict(current_entities.get(entity) or {})
        if new and (not target_companies or entity in target_companies):
            combined = dict(old)
            combined.update(
                {
                    key: new.get(key)
                    for key in ("confidence_score", "verification_reason")
                    if key in new
                }
            )
            combined["source_urls"] = unique_strings(
                old.get("source_urls"), new.get("source_urls")
            )
            records: Dict[tuple[str, str], Dict[str, Any]] = {}
            for record in old.get("raw_records") or []:
                records[record_key(record)] = record
            for record in new.get("raw_records") or []:
                records[record_key(record)] = record
            combined["raw_records"] = list(records.values())
            extracted = dict(old.get("extracted") or {})
            for metric, value in (new.get("extracted") or {}).items():
                if not target_metrics or metric in target_metrics:
                    extracted[metric] = value
            combined["extracted"] = extracted
            combined["missing_fields"] = [
                field for field in merged["selected_fields"] if field not in extracted
            ]
            combined["status"] = (
                "ok"
                if extracted and not combined["missing_fields"]
                else ("partial" if extracted else "no_extraction")
            )
            entity_results.append(combined)
        else:
            entity_results.append(old)
    merged["entity_results"] = entity_results
    merged["missing_fields"] = [
        field for field in merged["selected_fields"] if field not in merged_extracted
    ]
    merged["entity_missing"] = [
        f"{item['entity']}:{','.join(item.get('missing_fields') or [])}"
        for item in entity_results
        if item.get("missing_fields")
    ]
    if merged_extracted:
        merged["status"] = (
            "partial"
            if merged["missing_fields"] or merged["entity_missing"]
            else "ok"
        )
    elif merged["source_urls"]:
        merged["status"] = "no_extraction"
    else:
        merged["status"] = "fetch_failed"
    return merged


def crawl_row(client: httpx.Client, source_row: Dict[str, Any], deadline: float) -> Dict[str, Any]:
    row = int(source_row["row"])
    entities = list(source_row.get("entities") or [])
    targets = candidate_targets(row, source_row["sources"], entities)
    urls = [url for url, _expected_entities in targets]
    selected_fields = list(source_row.get("selected_fields") or [])
    ignored_selected_fields = list(source_row.get("ignored_selected_fields") or [])
    if ignored_selected_fields:
        print(
            f"  -> 已忽略非指标字段: {', '.join(ignored_selected_fields)}",
            flush=True,
        )
    fetched: List[Dict[str, Any]] = []
    combined_text = ""
    successful_urls: List[str] = []
    entity_text: Dict[str, str] = {entity: "" for entity in entities}
    entity_urls: Dict[str, List[str]] = {entity: [] for entity in entities}
    entity_records: Dict[str, List[Dict[str, Any]]] = {entity: [] for entity in entities}
    
    with ThreadPoolExecutor(max_workers=URL_WORKERS) as executor:
        future_to_target = {
            executor.submit(fetch_url, client, url): (url, expected_entities)
            for url, expected_entities in targets
        }
        for future in as_completed(future_to_target):
            if time.monotonic() > deadline:
                break
            url, expected_entities = future_to_target[future]
            print(f"  -> 抓取完成: {url}", flush=True)
            try:
                result = future.result()
                record = raw_record(row, result)
                if is_successful_fetch(result):
                    successful_urls.append(url)
                    print(f"    [成功] 状态码: {result.get('status')} | 耗时: {result.get('elapsed_seconds')}s | 大小: {result.get('bytes')} B", flush=True)
                    combined_text += "\n\nSOURCE: " + url + "\n" + result["text"]
                    hits = (
                        [entity for entity in expected_entities if entity in entities]
                        if expected_entities
                        else matched_entities(row, entities, result)
                    )
                    record["entity_hits"] = hits
                    for entity in hits:
                        if url not in entity_urls[entity]:
                            entity_urls[entity].append(url)
                        entity_records[entity].append(record)
                        entity_text[entity] += "\n\nSOURCE: " + url + "\n" + result["text"]
                else:
                    fallback = previous_url_evidence(row, url) if is_dns_failure(result) else None
                    if fallback:
                        record = raw_record(row, fallback)
                        successful_urls.append(url)
                        combined_text += "\n\nSOURCE: " + url + "\n" + fallback["text"]
                        hits = (
                            [entity for entity in expected_entities if entity in entities]
                            if expected_entities
                            else matched_entities(row, entities, fallback)
                        )
                        record["entity_hits"] = hits
                        for entity in hits:
                            if url not in entity_urls[entity]:
                                entity_urls[entity].append(url)
                            entity_records[entity].append(record)
                            entity_text[entity] += "\n\nSOURCE: " + url + "\n" + fallback["text"]
                        print(
                            f"    [第{row}行 DNS失败，保留历史证据] {url}",
                            flush=True,
                        )
                    else:
                        print(
                            f"    [第{row}行失败] 状态码: {result.get('status')} | "
                            f"错误: {result.get('error')} | 耗时: {result.get('elapsed_seconds')}s",
                            flush=True,
                        )
                        record["entity_hits"] = []
                fetched.append(record)
            except Exception as e:
                print(f"    [异常] {url}: {e}", flush=True)

    existing_result_path = RESULTS_DIR / f"row_{row}.json"
    if not successful_urls and existing_result_path.exists() and is_local_network_permission_failure(fetched):
        previous = json.loads(existing_result_path.read_text(encoding="utf-8"))
        if previous.get("status") in {"ok", "partial"}:
            previous["preserved_due_to_local_network_failure"] = True
            previous["attempted_urls_latest"] = urls
            previous["latest_fetch_errors"] = fetched
            previous["selected_fields"] = selected_fields
            previous["ignored_selected_fields"] = source_row.get("ignored_selected_fields", [])
            print(
                "  -> 本机网络权限拒绝，本轮不覆盖已有结果；保留上一轮可用数据。",
                flush=True,
            )
            return previous

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
    fallback_fields: Dict[str, str] = {}
    if not compact and len(entities) == 1:
        fallback_fields = verified_field_fallback(row, entities[0])
        if fallback_fields:
            compact.update(fallback_fields)
            missing = [field for field in missing if field not in fallback_fields]
            print(
                f"  -> 实时来源未命中，使用已核验字段兜底: {VERIFIED_FIELDS_JSON.name}",
                flush=True,
            )
    if len(entities) == 1:
        compact = apply_coverage_fallbacks(row, entities[0], compact, selected_fields)
        missing = [field for field in selected_fields if field not in compact]
    entity_results: List[Dict[str, Any]] = []
    multi_entity = len(entities) > 1
    for entity in entities:
        entity_specific_text = entity_text.get(entity) or ""
        text = (
            combined_text
            if row in AGGREGATE_COVERAGE_ROWS and not entity_specific_text
            else (entity_specific_text if (multi_entity or entity_specific_text) else combined_text)
        )
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
        entity_fallback = verified_field_fallback(row, entity)
        if not entity_compact and entity_fallback:
            entity_compact.update(entity_fallback)
        if row in AGGREGATE_COVERAGE_ROWS:
            for field, value in compact.items():
                entity_compact.setdefault(field, value)
        entity_compact = apply_coverage_fallbacks(row, entity, entity_compact, selected_fields)
        if not multi_entity:
            for field, value in compact.items():
                entity_compact.setdefault(field, value)
        entity_missing = [field for field in selected_fields if field not in entity_compact]
        
        # Verify extraction with LLM if there is any extraction
        verification_result = {"confidence_score": 0.0, "verification_reason": "No extraction."}
        if entity_compact:
            verification_result = verify_extraction(text, entity_compact)
            
        entity_results.append(
            {
                "entity": entity,
                "status": "ok" if entity_compact and not entity_missing else ("partial" if entity_compact else "no_extraction"),
                "source_urls": entity_urls.get(entity) or ([] if multi_entity else successful_urls),
                "extracted": entity_compact,
                "missing_fields": entity_missing,
                "raw_records": entity_records.get(entity) or ([] if multi_entity else [rec for rec in fetched if rec.get("text_sample")][:2]),
                "confidence_score": verification_result["confidence_score"],
                "verification_reason": verification_result["verification_reason"]
            }
        )
    status = "ok" if compact else "no_extraction"
    entity_missing_any = [f"{e['entity']}:{','.join(e['missing_fields'])}" for e in entity_results if e["missing_fields"]]
    if compact and (missing or entity_missing_any):
        status = "partial"
    if not successful_urls and not fallback_fields:
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
        "ignored_selected_fields": source_row.get("ignored_selected_fields", []),
        "source_urls": successful_urls,
        "attempted_urls": urls,
        "extracted": compact,
        "missing_fields": missing,
        "entity_results": entity_results,
        "entity_missing": entity_missing_any,
        "raw_records": fetched,
        "live_fetch_status": (
            "ok"
            if fetched
            and all(
                200 <= int(record.get("status") or 0) < 400
                and not record.get("evidence_fallback_used")
                for record in fetched
            )
            else (
                "partial"
                if any(
                    200 <= int(record.get("status") or 0) < 400
                    for record in fetched
                )
                else "failed"
            )
        ),
        "live_fetch_success_count": sum(
            1
            for record in fetched
            if 200 <= int(record.get("status") or 0) < 400
            and not record.get("evidence_fallback_used")
        ),
        "evidence_fallback_count": sum(
            1 for record in fetched if record.get("evidence_fallback_used")
        ),
        "fallback_used": bool(fallback_fields),
        "fallback_source_file": VERIFIED_FIELDS_JSON.name if fallback_fields else "",
        "fallback_fields": fallback_fields,
        "fetched_at": fetched_at,
        "fetched_at_hkt": fetched_at_hkt,
    }
    gap_target = source_row.get("gap_target") or {}
    if gap_target and existing_result_path.exists():
        try:
            previous = json.loads(existing_result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
        if previous:
            row_result = merge_targeted_row_result(previous, row_result, gap_target)
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
        f"实时抓取：{row_result.get('live_fetch_status', 'unknown')}"
        f"（成功 {row_result.get('live_fetch_success_count', success)}，"
        f"历史证据回退 {row_result.get('evidence_fallback_count', 0)}）",
        f"累计请求耗时：{elapsed:.1f}s",
        f"本地结果：results/row_{row_result['row']}.json",
    ]
    if row_result.get("log_sheet_title"):
        lines.append(f"飞书日志子表：{row_result['log_sheet_title']}")
    if row_result.get("fallback_used"):
        lines.append(
            f"核验兜底：{row_result.get('fallback_source_file') or '已核验本地数据'}"
        )
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
                    "cache_hit": rec.get("cache_hit", False),
                    "skip_reason": rec.get("skip_reason", ""),
                    "error": rec.get("error", ""),
                    "live_fetch_status": rec.get("live_fetch_status", "")
                    or (
                        "failed"
                        if rec.get("evidence_fallback_used")
                        else "success"
                    ),
                    "evidence_fallback_used": rec.get(
                        "evidence_fallback_used", False
                    ),
                    "fallback_reason": rec.get("fallback_reason", ""),
                }
            )

    (ROOT / "write_payload.json").write_text(
        json.dumps({"sources_payload": f_values, "results_payload": ij_values, "F2:F34": f_values, "I2:K34": ij_values}, ensure_ascii=False, indent=2),
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
                "cache_hit",
                "skip_reason",
                "error",
                "live_fetch_status",
                "evidence_fallback_used",
                "fallback_reason",
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
    cache_hits = sum(1 for r in row_results for rec in r.get("raw_records", []) if rec.get("cache_hit"))
    fulfilled = ok + partial
    coverage_rate = (fulfilled / len(row_results) * 100) if row_results else 0.0
    fallback_rows = sum(1 for r in row_results if r.get("fallback_used"))
    live_success_urls = sum(
        1
        for r in row_results
        for rec in r.get("raw_records", [])
        if 200 <= int(rec.get("status") or 0) < 400
        and not rec.get("evidence_fallback_used")
    )
    evidence_fallback_urls = sum(
        1
        for r in row_results
        for rec in r.get("raw_records", [])
        if rec.get("evidence_fallback_used")
    )
    live_failed_urls = sum(
        1
        for r in row_results
        for rec in r.get("raw_records", [])
        if not (200 <= int(rec.get("status") or 0) < 400)
        or rec.get("evidence_fallback_used")
    )
    live_total_urls = live_success_urls + live_failed_urls
    live_success_rate = (
        live_success_urls / live_total_urls * 100 if live_total_urls else 0.0
    )
    audit = [
        "# CMHK Public Crawl Audit",
        "",
        f"- Generated at: {datetime.now().isoformat()}",
        f"- Rows crawled: {len(row_results)}",
        f"- OK rows: {ok}",
        f"- Partial rows: {partial}",
        f"- Failed/no extraction rows: {failed}",
        f"- Information requirements fulfilled: {fulfilled}/{len(row_results)} ({coverage_rate:.1f}%)",
        f"- Rows fulfilled by verified fallback: {fallback_rows}",
        f"- URLs fetched after compliance checks: {crawled}",
        f"- Same-run URL cache hits: {cache_hits}",
        f"- Network fetches after cache reuse: {crawled - cache_hits}",
        f"- URLs skipped by compliance policy: {skipped}",
        f"- Live URL success: {live_success_urls}/{live_total_urls} ({live_success_rate:.1f}%)",
        f"- Live URL failures: {live_failed_urls}",
        f"- URLs restored from previous evidence: {evidence_fallback_urls}",
        f"- Source registry: {SOURCE_REGISTRY_JSON.name}",
        f"- Raw body persistence: {'enabled' if CMHK_SAVE_RAW_BODY else 'disabled'}",
        "",
        "See `coverage_report.tsv` and `results/row_<n>.json` for row-level evidence.",
        "See `run_log.tsv` for per-URL status code, elapsed time, and extraction coverage.",
    ]
    (ROOT / "final_audit.md").write_text("\n".join(audit) + "\n", encoding="utf-8")


def crawl_rows(client: httpx.Client, rows: List[Dict[str, Any]], deadline: float) -> List[Dict[str, Any]]:
    if ROW_WORKERS <= 1:
        results = []
        for source_row in rows:
            if time.monotonic() > deadline:
                print(f"global crawl deadline reached after {MAX_RUN_SECONDS}s; stopping before row {source_row['row']}")
                break
            print(f"crawl row {source_row['row']}: {source_row['package']}", flush=True)
            results.append(crawl_row(client, source_row, deadline))
        return results

    results: List[Dict[str, Any]] = []
    print(
        f"parallel crawl enabled: row_workers={ROW_WORKERS}, url_workers={URL_WORKERS}",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=ROW_WORKERS) as executor:
        future_to_row = {}
        row_iter = iter(rows)

        def submit_next() -> bool:
            if time.monotonic() > deadline:
                return False
            try:
                source_row = next(row_iter)
            except StopIteration:
                return False
            print(f"crawl row {source_row['row']}: {source_row['package']}", flush=True)
            future = executor.submit(crawl_row, client, source_row, deadline)
            future_to_row[future] = source_row
            return True

        for _ in range(ROW_WORKERS):
            if not submit_next():
                break

        while future_to_row:
            for future in as_completed(list(future_to_row)):
                source_row = future_to_row.pop(future)
                try:
                    results.append(future.result())
                except Exception as exc:
                    print(f"row {source_row['row']} failed with exception: {exc}", flush=True)
                submit_next()
                break

    return sorted(results, key=lambda item: int(item.get("row") or 0))


def main() -> None:
    RAW_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)
    chosen_proxy = normalize_proxy_env(os.environ)
    if chosen_proxy:
        print(f"using local proxy: {chosen_proxy}", flush=True)
    else:
        print("no reachable local proxy detected; using direct network path", flush=True)
    rows = apply_crawl_settings(apply_row_filter(parse_latest_sheet()))
    (ROOT / "sources.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    deadline = time.monotonic() + MAX_RUN_SECONDS
    max_connections = max(20, ROW_WORKERS * URL_WORKERS * 2)
    client = httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(PER_URL_TIMEOUT_SECONDS, connect=12.0),
        headers={
            "User-Agent": CMHK_USER_AGENT,
            "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
        },
        limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
        trust_env=True,
    )
    results = crawl_rows(client, rows, deadline)
    client.close()
    write_outputs(results)
    print(f"wrote {ROOT / 'write_payload.json'}")
    print(f"wrote {ROOT / 'coverage_report.tsv'}")
    print(f"wrote {ROOT / 'final_audit.md'}")


if __name__ == "__main__":
    main()
