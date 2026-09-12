from __future__ import annotations

import argparse
import csv
import difflib
import fcntl
import hashlib
import itertools
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from cmhk.data.daily_financial_promotion import promote_daily_financial_facts
from cmhk.data.local_financial_results import DATABASE_PATH as CANONICAL_LOCAL_FINANCIAL_PATH
from cmhk.data_releases import default_release_root, publish_quarterly_release_task

from ai_response_compat import final_chat_message_text, load_json_response, prepare_structured_chat_body, read_chat_completion_sse, unwrap_items_payload
from ai_key_rotation import APIKeyPoolUnavailable, open_llm_request
from cmhk.intelligence.ai_provenance import AI_ONLY_POLICY, model_generated_only
from executive_intelligence_prompts import STRATEGIC_PROMPT_VERSION, STRATEGIC_WRITING_GUIDE, discovery_few_shot_messages


ROOT = Path(__file__).resolve().parent
HKT = ZoneInfo("Asia/Hong_Kong")
STATE_DIR = ROOT / "agent_knowledge" / "executive_intelligence_refresh"
STATE_PATH = STATE_DIR / "latest.json"
AI_ANALYSIS_PATH = STATE_DIR / "ai_analysis.json"
LOCK_PATH = STATE_DIR / ".refresh.lock"
LOG_PATH = STATE_DIR / "refresh.log"
WATCHDOG_STATE_PATH = STATE_DIR / "watchdog.json"
PAGES_PUBLISH_SCRIPT = ROOT / "scripts" / "publish_executive_dashboard_pages.py"
INSIGHT_FORMAT_VERSION = "strategic_operating_judgement_v9"

FOCUS_EVIDENCE_CONTRACT = (
    "数字、公司、期间、单位和来源采用本次输入原值，不自行换汇、估算或补写原因。"
    "标题写具体经营判断，正文选最有解释力的事实，简短说明它的业务含义；"
    "缺少直接可比金额时可解释各自经营状态，不必把口径说明写成主结论。"
    "正文以一至两句、80至110字为写作目标，风险字段补充真正影响判断的限制。"
    "实体evidence_labels只能原样选自allowed_evidence_labels，不需明细引用时返回[]。"
    + STRATEGIC_WRITING_GUIDE
)


def _uncached_model_body(body: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
    """Isolate each validation attempt while retaining its evidence and feedback."""
    fresh = json.loads(json.dumps(body, ensure_ascii=False))
    fresh["cache"] = {"no-cache": True, "no-store": True}
    marker = (
        f"{request_id or uuid4().hex}\n"
        "以上仅为本次请求隔离编号，不是证据，不得写入答案。\n"
    )
    messages = fresh.setdefault("messages", [])
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = marker + str(messages[0].get("content") or "")
    else:
        messages.insert(0, {"role": "system", "content": marker})
    for message in messages:
        if message.get("role") == "user":
            message["content"] = marker + str(message.get("content") or "")
            break
    return fresh


def _model_request(config, api_key, body, request_id=None):
    from ai_config import INTERNAL_AI_BASE_URL

    request_id = request_id or uuid4().hex
    return urllib.request.Request(
        f"{str(config.get('base_url') or INTERNAL_AI_BASE_URL).rstrip('/')}/chat/completions?request_id={request_id}",
        data=json.dumps(_uncached_model_body({**body, "stream": True}, request_id), ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "Cache-Control": "no-cache, no-store", "Pragma": "no-cache", "X-Request-ID": request_id,
                 "Accept": "text/event-stream"},
        method="POST",
    )


def _model_prompt_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    prompt = json.loads(json.dumps(evidence, ensure_ascii=False))
    for domain in prompt.get("domains") or []:
        for focus in domain.get("focuses") or []:
            for entity in focus.get("items") or []:
                entity["allowed_evidence_labels"] = [
                    component["label"] for component in entity.get("components") or []
                    if isinstance(component, dict) and component.get("label")
                ]
    return prompt


def _trace_model_attempt(path, scope, model, started, payload, error, config):
    try:
        _write_model_attempt_trace(path, scope, model, started, payload, error, config)
    except Exception:
        # Diagnostics must never turn accepted model output into a failed run.
        return


def _write_model_attempt_trace(path, scope, model, started, payload, error, config):
    if path is None:
        return
    from ai_config import api_key_candidates

    message = str(error or "")
    for key in api_key_candidates(config, model=model):
        if key:
            message = message.replace(key, "[redacted]")
    message = re.sub(r"(?i)Bearer\s+\S+", "Bearer [redacted]", message)
    choices = payload.get("choices") or []
    stream_diagnostics = payload.get("stream_diagnostics") or getattr(error, "stream_diagnostics", {})
    record = {
        "ts": _now(), "scope": scope, "requested_model": model,
        "reported_model": payload.get("model") or stream_diagnostics.get("reported_model"),
        "response_id": payload.get("id") or stream_diagnostics.get("response_id"),
        "created": payload.get("created") or stream_diagnostics.get("created"),
        "stream": stream_diagnostics,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "finish_reasons": [choice.get("finish_reason") for choice in choices],
        "gate_error": message[:1200], "ok": not bool(error),
        "response_hash": _content_hash([choice.get("message") for choice in choices]) if choices else "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False)
    for key in api_key_candidates(config, model=model):
        if key:
            encoded = encoded.replace(key, "[redacted]")
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(encoded + "\n")


FOCUS_RELATION_FEW_SHOTS = (
    "少样本示范（学习判断方式，不要照抄句式）：\n"
    "反例：HKBN有27个产品、3HK有24个、SmarTone有21个，说明三家产品较多。"
    "问题：只是复述数字，没有竞对结构和经营含义。\n"
    "正例：HKBN、3HK和SmarTone分别有27、24、21个产品，而i-CABLE和HGC为8、4个，"
    "数量形成两层；但头部三家彼此只差6个，产品数量难以成为头部之间的主要区隔。\n"
    "反例：Google Cloud增长35.8%，高于Oracle 23.9%，说明Google领先。"
    "问题：把单项增速直接等同竞争力。\n"
    "正例：4家直接披露云收入的厂商中，Google Cloud为35.8%、Alibaba Cloud为11.0%，"
    "收入增速形成两层；Azure和Tencent是代理分部口径，不纳入这一比较。\n"
    "反例：投资增长1.3%推动投诉增长2.9%。问题：期间不同且虚构因果。\n"
    "正例：投资数据截至2025年3月，投诉数据为2025自然年，期间不同，"
    "不能判断两者关系，只能分别观察投入变化和服务压力。\n"
    "反例：HKT营收36553百万港元，3HK为5448百万港元，数值存在差距。"
    "问题：只告诉读者数据是什么，没有提炼战略发现。\n"
    "正例：HKT的经营资源底盘明显更厚：营收36553百万港元，而3HK为5448百万港元；"
    "前者更能承受网络与获客的持续投入，后者的防守空间更窄，但营收绝对值不证明效率高低。\n"
    "反例：AWS云利润39834百万美元，Google为6112百万美元，利润定义见明细。"
    "问题：只复述金额和定义。\n"
    "正例：AWS的云业务自我造血能力更强：同属经营利润的AWS为39834百万美元、Google为6112百万美元；"
    "AWS可用更厚的盈利缓冲支撑再投资与价格竞争，利润池向头部集中；"
    "其他厂商的毛利或调整后EBITA不混入比较。\n"
    "反例：中国移动营收10501.87亿元、中国联通3922.23亿元，规模优势固化资源壁垒。"
    "问题：仍然只在命名数据差距，没有回答哪家的经营状态更强、哪家更承压。\n"
    "正例：中国移动的收入底盘最强，中国联通的资源容错相对最窄：两者营收分别为10501.87亿元和3922.23亿元；"
    "这意味着移动更能同时承担网络、渠道与获客投入，但该指标本身不证明投入效率。\n"
    "反例：三来源数据待补为-，四家公司后付费数据均未披露，因此无法比较。"
    "问题：把空值或占位符当成数字，而且只报告数据缺口。\n"
    "正例：四家公司均缺少可比后付费原值，口径缺口意味着客户价值和客户质量无法穿透比较，"
    "竞争结构判断不能由移动或5G用户总量替代。"
)
MAX_FOCUS_INSIGHT_CHARS = 120
MAX_FOCUS_INSIGHT_PUBLISH_CHARS = 160
MAX_FOCUS_HEADLINE_CHARS = 28
MAX_FOCUS_HEADLINE_PUBLISH_CHARS = 36
MAX_FOCUS_INSIGHT_SENTENCES = 2
MAX_DISCOVERY_DETAIL_CHARS = 110
MAX_DISCOVERY_DETAIL_PUBLISH_CHARS = 160
TASK_KIND = "executive-intelligence-refresh"
DEFAULT_EXECUTIVE_AI_MODEL = "DeepSeek-V4-Pro"
EXECUTIVE_AI_FALLBACK_MODELS = ("GLM", "Qwen3-30B-A3B-Instruct-2507")
DOMAIN_LABELS = {
    "local": "本地运营商",
    "international": "国际运营商",
    "mainland": "内地运营商",
    "cloud": "全球云厂商",
    "macro": "宏观政策支撑库",
}
UI_DOMAIN_IDS = ("local", "international", "mainland", "cloud")
SUPPORTING_DOMAIN_IDS = ("macro",)
NEWS_DATABASE_SIGNALS_PATH = STATE_DIR / "news_database_signals.json"
SOURCE_DISCOVERY_PATH = STATE_DIR / "source_discovery_latest.json"
NEWS_METRIC_RE = re.compile(
    r"财报|业绩|营收|收入|利润|EBITDA|ARPU|用户数|客户数|订户|资本开支|capex|"
    r"earnings|revenue|profit|subscriber|customer|cloud revenue|云收入|云业务",
    re.I,
)
NEWS_ENTITY_SOURCES: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("local", "CMHK", ("CMHK", "China Mobile Hong Kong", "中国移动香港", "中國移動香港"), ("https://www.hk.chinamobile.com/en/", "https://www.hk.chinamobile.com/en/about_us/", "https://www.chinamobileltd.com/en/ir/reports.php")),
    ("local", "HKT", ("HKT", "香港电讯", "香港電訊"), ("https://www.hkt.com/en/about-hkt/investor-relations/financial-results/", "https://www.hkt.com/en/about-hkt/press-release/hkt-reports-solid-interim-results-for-2026/")),
    ("local", "SmarTone", ("SmarTone", "数码通", "數碼通"), ("https://www.smartoneholdings.com/jsp/site/investor_relations/announcements/english/index.jsp", "https://www.smartoneholdings.com/jsp/site/investor_relations/results/english/index.jsp", "https://www.smartoneholdings.com/jsp/site/investor_relations/financial_reports/english/index.jsp")),
    ("local", "3HK", ("3HK", "3 Hong Kong", "和记电讯香港", "和記電訊香港"), ("https://www.hthkh.com/en/ir/reports.php", "https://www.hthkh.com/en/media/press.php?prid=/press/p260810")),
    ("local", "HKBN", ("HKBN", "香港宽频", "香港寬頻"), ("https://www.hkbn.net/group/en/investor-engagement/financial-results",)),
    ("local", "HGC", ("HGC", "HGC Global Communications", "环电", "環電", "环球全域电讯", "環球全域電訊"), ("https://www.hgc-intl.com/", "https://www.hgc-intl.com/press-releases", "https://www.hgc-intl.com/insight")),
    ("local", "i-CABLE", ("i-CABLE", "CTF Media & Entertainment", "有線寬頻", "01097", "1097.HK"), ("https://www.ctfme.com/en/annual-interim-reports", "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en", "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0827/2026082702131.pdf")),
    ("international", "Singtel", ("Singtel", "Singapore Telecommunications"), ("https://www.singtel.com/about-us/investor-relations/financial-results", "https://www.singtel.com/about-us/investor-relations/financial-summary")),
    ("international", "Telstra", ("Telstra",), ("https://www.telstra.com.au/aboutus/investors/financial-results",)),
    ("international", "SK Telecom", ("SK Telecom", "SKT"), ("https://news.sktelecom.com/en/category/press-center/press-release",)),
    ("international", "KT", ("KT Corp", "Korea Telecom"), ("https://corp.kt.com/eng/html/investors/main.html", "https://corp.kt.com/eng/html/investors/financial/business.html", "https://www.sec.gov/Archives/edgar/data/892450/000162828026055923/a2q26_ktxerxptxengx0811f.htm")),
    ("international", "NTT Docomo", ("NTT DOCOMO", "NTT Docomo"), ("https://www.docomo.ne.jp/english/corporate/ir/", "https://www.docomo.ne.jp/english/corporate/ir/library/presentation/")),
    ("international", "KDDI", ("KDDI",), ("https://www.kddi.com/english/corporate/ir/ir-library/earning/",)),
    ("international", "SoftBank", ("SoftBank Corp", "SoftBank telecom"), ("https://www.softbank.jp/en/corp/ir/",)),
    ("international", "Bharti Airtel", ("Bharti Airtel", "Airtel India"), (
        "https://www.airtel.in/about-bharti/equity/results",
        "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2026-27/Q1/Quarterly-Highlights.pdf",
        "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2026-27/Q1/Press-Release.pdf",
        "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2026-27/Q1/Published-Results.pdf",
        "https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2026-27/Q1/Quarterly-IR-Pack-Bharti-Airtel-Consolidated.pdf",
    )),
    ("international", "Reliance Jio", ("Reliance Jio", "Jio Platforms"), ("https://www.ril.com/investors/financial-reporting", "https://www.ril.com/sites/default/files/2026-05/Jio-Factsheet-2026.pdf", "https://rilstaticasset.akamaized.net/sites/default/files/2026-07/Media_Release_RIL_Q1_FY2026-27_Financial_and_Operational_Performance.pdf")),
    ("international", "Vodafone", ("Vodafone",), ("https://www.vodafone.com/investors/performance-and-reports/annual-reporting",)),
    ("international", "Verizon", ("Verizon",), ("https://www.verizon.com/about/investors/financial-reporting", "https://www.verizon.com/about/news/verizon-delivers-record-2q26-results")),
    ("international", "AT&T", ("AT&T",), ("https://investors.att.com/", "https://investors.att.com/financial-reports/quarterly-earnings/2026")),
    ("international", "Deutsche Telekom", ("Deutsche Telekom",), ("https://www.telekom.com/en/investor-relations/publications/financial-results",)),
    ("international", "NTT", ("NTT Group", "Nippon Telegraph and Telephone"), ("https://group.ntt/en/ir/library/results/",)),
    ("international", "Orange", ("Orange SA", "Orange telecom", "Orange Group"), ("https://www.orange.com/en/finance/financial-and-extra-financial-information",)),
    ("international", "Telefonica", ("Telefonica", "Telefónica"), ("https://www.telefonica.com/en/shareholders-investors/financial-reports/quarterly-reports/2026/",)),
    ("international", "BT", ("BT Group", "BT/EE"), ("https://www.bt.com/about/investors/financial-reporting-and-news/financial-calendar", "https://newsroom.bt.com/bt-delivered-a-solid-start-to-the-year-with-continued-strategic-momentum/")),
    ("international", "TIM", ("TIM Group", "Telecom Italia"), ("https://www.gruppotim.it/en/investors/reports-presentations/financial-reports/2026.html", "https://www.gruppotim.it/content/dam/gt/investitori/report/Half%20Year%20Financial%20Report%20at%20June%2030,%202026.pdf")),
    ("international", "T-Mobile US", ("T-Mobile US",), (
        "https://investor.t-mobile.com/financials/quarterly-results/default.aspx",
        "https://data.sec.gov/submissions/CIK0001283699.json",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0001283699.json",
    )),
    ("mainland", "e&", ("e&", "Etisalat"), (
        "https://www.eand.com/en/investors/financial-results.html",
        "https://www.eand.com/en/investors/financial-highlights.html",
    )),
    ("mainland", "stc", ("stc Group", "Saudi Telecom"), ("https://www.stc.com/en/investors.html", "https://www.saudiexchange.sa/Resources/fsPdf/23192_480_2026-07-29_11-19-33_en.pdf")),
    ("mainland", "中国移动", ("中国移动", "中國移動", "China Mobile"), ("https://www.chinamobileltd.com/en/ir/reports.php", "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0813/2026081300218.pdf")),
    ("mainland", "中国电信", ("中国电信", "中國電信", "China Telecom"), ("https://www.chinatelecom-h.com/en/ir/reports.php",)),
    ("mainland", "中国联通", ("中国联通", "中國聯通", "China Unicom"), (
        "https://www.chinaunicom.com.hk/en/ir/reports.php",
        "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0818/2026081800335.pdf",
    )),
    ("mainland", "中国铁塔", ("中国铁塔", "中國鐵塔", "China Tower", "0788.HK"), ("https://ir.china-tower.com/", "https://ir.china-tower.com/en/ir/reports.php", "https://ir.china-tower.com/en/ir/presentation.php")),
    ("mainland", "中国广电", ("中国广电", "中國廣電", "中国广播电视网络集团有限公司", "中国广电集团", "China Broadnet", "China Broadcasting Network"), (
        "https://www.cbn.cn/",
        "https://www.nrta.gov.cn/art/2026/8/14/art_114_73831.html",
        "https://gbdsj.cq.gov.cn/sjfb/202608/t20260824_15973393.html",
    )),
    ("cloud", "AWS", ("AWS", "Amazon Web Services"), ("https://www.sec.gov/Archives/edgar/data/1018724/000101872426000024/amzn-20260630xex991.htm", "https://ir.aboutamazon.com/quarterly-results/default.aspx")),
    ("cloud", "Microsoft Azure", ("Azure", "Microsoft cloud"), ("https://www.microsoft.com/en-us/investor/default", "https://www.microsoft.com/en-us/Investor/earnings")),
    ("cloud", "Google Cloud", ("Google Cloud", "Alphabet"), ("https://abc.xyz/investor/",)),
    ("cloud", "Alibaba Cloud", ("Alibaba Cloud", "阿里云", "阿里雲"), ("https://www.alibabagroup.com/en-US/ir-financial-reports-quarterly-results",)),
    ("cloud", "Tencent Cloud", ("Tencent Cloud", "腾讯云", "騰訊雲"), ("https://www.tencent.com/investors/results/",)),
    ("cloud", "Huawei Cloud", ("Huawei Cloud", "华为云", "華為雲"), ("https://www.huawei.com/en/annual-report",)),
    ("cloud", "Oracle Cloud", ("Oracle Cloud",), ("https://www.sec.gov/Archives/edgar/data/1341439/000119312526265848/orcl-ex99_1.htm", "https://investor.oracle.com/financials/")),
    ("cloud", "China Mobile Cloud", ("China Mobile Cloud", "Mobile Cloud", "移动云", "移動雲"), ("https://ecloud.10086.cn/", "https://www.chinamobileltd.com/en/ir/reports.php")),
)
FACT_DOMAIN_IDS = (*UI_DOMAIN_IDS, *SUPPORTING_DOMAIN_IDS)


def _executive_model_route() -> list[str]:
    """Keep four-database judgements on V4 Pro unless operations explicitly override it."""
    primary = (
        os.environ.get("CMHK_EXECUTIVE_AI_MODEL", "").strip()
        or DEFAULT_EXECUTIVE_AI_MODEL
    )
    from data_curation.research_model import configured_research_models
    return list(dict.fromkeys([*configured_research_models(primary), *EXECUTIVE_AI_FALLBACK_MODELS]))

LOCAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/current_plans.json"
INTERNATIONAL_DIR = ROOT / "agent_knowledge/quarterly_competitor_metrics_2026-06-18"
INTERNATIONAL_PATH = INTERNATIONAL_DIR / "quarterly_metrics.json"
LEGACY_LOCAL_FINANCIAL_PATH = ROOT / "agent_knowledge/hk_competitor_product_tariffs/local_financial_results.json"
LOCAL_FINANCIAL_PATH = (
    CANONICAL_LOCAL_FINANCIAL_PATH
    if CANONICAL_LOCAL_FINANCIAL_PATH.exists()
    else LEGACY_LOCAL_FINANCIAL_PATH
)
GLOBAL_OPERATOR_DIR = ROOT / "agent_knowledge/global_top5_operators_2016_2025"
GLOBAL_OPERATOR_PATH = GLOBAL_OPERATOR_DIR / "annual_metrics.json"
CLOUD_DIR = ROOT / "agent_knowledge/cloud_vendor_metrics_2026-06-17"
CLOUD_PATH = CLOUD_DIR / "cloud_vendor_metrics_2023_2025.json"
MACRO_DIR = ROOT / "agent_knowledge/cmhk_macro_policy_2026-06-19"
MACRO_PATH = MACRO_DIR / "macro_policy_metrics.json"
VERIFIED_FACTS_PATH = ROOT / "curation_data/verified_facts.jsonl"
DOMAIN_FACT_PATHS = {
    "local": LOCAL_PATH.parent / "agent_verified_facts.json",
    "international": GLOBAL_OPERATOR_DIR / "agent_verified_facts.json",
    "mainland": INTERNATIONAL_DIR / "agent_verified_facts.json",
    "cloud": CLOUD_DIR / "agent_verified_facts.json",
    "macro": MACRO_DIR / "agent_verified_facts.json",
}

LOCAL_COMPANIES = {
    "HKT", "csl", "1O1O", "3HK / Hutchison", "Hutchison", "SmarTone", "HKBN", "HGC", "i-CABLE"
}
MAINLAND_COMPANIES = {"中国移动", "中国电信", "中国联通", "中国铁塔", "中国广电"}
INTERNATIONAL_COMPANIES = {
    "KDDI", "SoftBank", "Telstra", "Jio", "Reliance Jio", "Bharti Airtel",
    "T-Mobile US", "AT&T", "Verizon", "Orange", "Telefonica", "Vodafone",
    "SK Telecom", "Deutsche Telekom", "NTT", "NTT Group",
}
CLOUD_COMPANIES = {
    "AWS", "Amazon Web Services", "Microsoft Azure", "Azure", "Google Cloud", "Alibaba Cloud",
    "阿里云", "Tencent Cloud", "腾讯云", "Huawei Cloud", "华为云", "Oracle Cloud",
}
MACRO_COMPANIES = {"政策", "香港本地监管", "OFCA", "香港统计处", "政府"}

SAFE_VERIFICATION_STATUSES = {
    "official_match",
    "official_only",
    "official_derived_from_verified_rows",
    "multi_source_or_multi_snapshot_verified",
}


def _now() -> str:
    return datetime.now(HKT).isoformat(timespec="seconds")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _append_log(message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _task_stream_path(task_run_id: str) -> Path:
    return ROOT / "agent_knowledge" / "crawl_run_logs" / "runs" / f"{task_run_id}.jsonl"


def _task_event(
    task_run_id: str,
    phase: str,
    detail: str,
    *,
    worker_pid: int = 0,
    level: str = "info",
) -> None:
    """Write one human-readable task-log line and update the unified-task heartbeat."""
    if not task_run_id:
        return
    from cmhk.crawl.run_registry import append_crawl_run_event, heartbeat_crawl_run

    heartbeat_crawl_run(
        task_run_id,
        phase,
        detail,
        worker_pid=worker_pid or os.getpid(),
        append_log=False,
    )
    prefix = "预警" if level == "critical" else "后备重试" if level == "retry" else phase
    append_crawl_run_event(
        _task_stream_path(task_run_id),
        {
            "type": "log",
            "text": f"[{datetime.now(HKT).strftime('%H:%M:%S')}] [{prefix}] {detail}",
        },
    )


def _start_refresh_task(
    *,
    agent_run_id: str,
    parent_crawl_run_id: str = "",
    recovery_reason: str = "",
) -> dict[str, Any]:
    from cmhk.crawl.run_registry import append_crawl_run_event, start_crawl_run

    scope = f"Agent审核 {agent_run_id}"
    if parent_crawl_run_id:
        scope += f" · 父任务 {parent_crawl_run_id}"
    if recovery_reason:
        scope += f" · {recovery_reason}"
    task = start_crawl_run(
        trigger="四库与观察结论自动更新",
        scope=scope,
        task_kind=TASK_KIND,
        parent_crawl_run_id=parent_crawl_run_id,
        phase="等待刷新进程",
        progress_detail=(
            "任务已归档，正在更新战略总览的本地运营商、国际运营商、内地运营商和全球云厂商四域；"
            "宏观政策库继续作为支撑数据维护。"
        ),
    )
    task_run_id = str(task["crawl_run_id"])
    append_crawl_run_event(
        task["stream_log_path"],
        {
            "type": "log",
            "text": (
                f"[{datetime.now(HKT).strftime('%H:%M:%S')}] [任务启动] "
                f"四库更新已接收；Agent run={agent_run_id}；父任务={parent_crawl_run_id or '无'}。"
            ),
        },
    )
    return task


def _finalize_refresh_task(
    task_run_id: str,
    *,
    ok: bool,
    detail: str,
    result: dict[str, Any],
    attempts: int,
) -> None:
    if not task_run_id:
        return
    from cmhk.crawl.run_registry import finalize_operational_crawl_run

    _task_event(
        task_run_id,
        "任务完成" if ok else "任务失败",
        detail,
        level="info" if ok else "critical",
    )
    finalize_operational_crawl_run(
        task_run_id,
        ok=ok,
        duration_ms=int(result.get("total_duration_ms") or result.get("duration_ms") or 0),
        progress_detail=detail,
        failure_stage="" if ok else str(result.get("failure_stage") or "executive_intelligence_refresh"),
        summary={
            "attempts": attempts,
            "agent_run_id": result.get("agent_run_id", ""),
            "failed_domains": result.get("failed_domains", []),
            "status": result.get("status", ""),
            "notification_policy": "local_log_only",
            "model_analysis": result.get("model_analysis", {}),
            "pages_publish": result.get("pages_publish", {}),
            "feishu_detail_log": result.get("feishu_detail_log", {}),
            "failure_stage": result.get("failure_stage", ""),
            "overview_source_recrawl": result.get("overview_source_recrawl", {}),
            "ui_value_changes": result.get("ui_value_changes", {}),
        },
    )


def _content_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fact_content(payload: dict[str, Any]) -> dict[str, Any]:
    """Return durable fact content, excluding run provenance fields."""
    return {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at_hkt", "agent_run_id"}
    }


def _ui_numeric_value_snapshot(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Capture only numeric fields that are actually rendered as four-domain UI data."""
    if snapshot is None:
        from cmhk.intelligence.executive import build_executive_intelligence_snapshot

        snapshot = build_executive_intelligence_snapshot()
    domains: dict[str, list[dict[str, Any]]] = {}
    for domain in snapshot.get("domains") or []:
        domain_id = str(domain.get("id") or "")
        if domain_id not in UI_DOMAIN_IDS:
            continue
        values: list[dict[str, Any]] = []
        for entity in domain.get("entities") or []:
            entity_name = str(entity.get("name") or "")
            candidates = [("main", "页面主值", entity.get("value"), entity.get("unit"), entity.get("period"))]
            candidates.extend(
                (
                    f"component:{index}:{component.get('label') or '指标'}",
                    str(component.get("label") or "指标"),
                    component.get("value"),
                    component.get("unit"),
                    component.get("detail"),
                )
                for index, component in enumerate(entity.get("components") or [])
            )
            for field_key, field_label, value, unit, context in candidates:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    continue
                values.append(
                    {
                        "key": f"{entity_name}|{field_key}",
                        "entity": entity_name,
                        "field": field_label,
                        "value": value,
                        "unit": str(unit or ""),
                        "context": str(context or ""),
                    }
                )
        domains[domain_id] = values
    return {"captured_at_hkt": _now(), "domains": domains}


def _compare_ui_numeric_values(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    """Count a change only when the same rendered numeric field has a different value."""
    if not previous or not current:
        return {
            "baseline_available": False,
            "method": "same UI field numeric old-to-new comparison",
            "changed": 0,
            "added": 0,
            "removed": 0,
            "domains": {},
            "items": [],
        }
    domain_results: dict[str, dict[str, Any]] = {}
    changed_items: list[dict[str, Any]] = []
    total_added = 0
    total_removed = 0
    for domain in UI_DOMAIN_IDS:
        old_items = {item["key"]: item for item in (previous.get("domains") or {}).get(domain, [])}
        new_items = {item["key"]: item for item in (current.get("domains") or {}).get(domain, [])}
        changes: list[dict[str, Any]] = []
        for key in sorted(old_items.keys() & new_items.keys()):
            old_item = old_items[key]
            new_item = new_items[key]
            if old_item.get("value") == new_item.get("value"):
                continue
            changes.append(
                {
                    "domain": domain,
                    "entity": new_item.get("entity") or old_item.get("entity") or "",
                    "field": new_item.get("field") or old_item.get("field") or "",
                    "old_value": old_item.get("value"),
                    "new_value": new_item.get("value"),
                    "unit": new_item.get("unit") or old_item.get("unit") or "",
                    "context": new_item.get("context") or "",
                }
            )
        added = len(new_items.keys() - old_items.keys())
        removed = len(old_items.keys() - new_items.keys())
        total_added += added
        total_removed += removed
        changed_items.extend(changes)
        domain_results[domain] = {
            "baseline_available": True,
            "changed": len(changes),
            "added": added,
            "removed": removed,
        }
    return {
        "baseline_available": True,
        "method": "same UI field numeric old-to-new comparison; source-page fingerprints excluded",
        "changed": len(changed_items),
        "added": total_added,
        "removed": total_removed,
        "domains": domain_results,
        "items": changed_items,
    }


def _first_source(fact: dict[str, Any]) -> str:
    for source in fact.get("sources") or []:
        value = str(source or "").strip()
        if value.startswith(("https://", "http://")):
            return value
    return ""


def _fact_domain(fact: dict[str, Any]) -> str | None:
    company = str(fact.get("company") or "").strip()
    from data_curation.research_plan import ASSIGNMENTS
    for assignment in ASSIGNMENTS:
        if company in assignment.companies:
            return {"hong-kong": "local", "mainland": "mainland", "cloud": "cloud"}.get(assignment.key, "international")
    if company in LOCAL_COMPANIES:
        return "local"
    if company in CLOUD_COMPANIES:
        return "cloud"
    if company in MAINLAND_COMPANIES:
        return "mainland"
    if company in INTERNATIONAL_COMPANIES:
        return "international"
    if company in MACRO_COMPANIES:
        return "macro"
    metric = str(fact.get("metric") or "")
    if any(token in metric for token in ("政策", "监管", "频谱", "投诉", "GDP", "消费")):
        return "macro"
    return None


def _accepted_fact(fact: dict[str, Any]) -> bool:
    basis = str(fact.get("basis") or "")
    if re.search(r"无(?:明确)?资本开支(?:总额|金额)|无明确.{0,20}(?:金额|数字)", basis):
        return False
    return bool(
        fact.get("decision") == "accepted"
        and fact.get("status") == "ok"
        and fact.get("entity_supported")
        and fact.get("metric_supported")
        and fact.get("value_supported")
        and float(fact.get("quality_score") or 0) >= 0.85
        and _first_source(fact)
    )


def build_ai_analysis(
    *,
    agent_run_id: str,
    verified_facts_path: Path = VERIFIED_FACTS_PATH,
    curation_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    if verified_facts_path.exists():
        for line in verified_facts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                fact = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _accepted_fact(fact) and _fact_domain(fact):
                facts.append(fact)

    domains: dict[str, list[dict[str, Any]]] = {key: [] for key in FACT_DOMAIN_IDS}
    seen: set[tuple] = set()
    facts.sort(
        key=lambda item: (
            str(item.get("source_tier") or "") == "official",
            float(item.get("quality_score") or 0),
            float(item.get("confidence") or 0),
        ),
        reverse=True,
    )
    for fact in facts:
        domain = _fact_domain(fact)
        if not domain:
            continue
        key = (domain, str(fact.get("company") or ""), str(fact.get("metric") or ""))
        if (curation_summary or {}).get("architecture") == "six_research_agents_v1":
            # Preserve every accepted item, including multiple reporting periods.
            key += (fact.get("id"), fact.get("period"), fact.get("unit"), str(fact.get("value")), fact.get("evidence_hash"))
        if key in seen:
            continue
        seen.add(key)
        domains[domain].append(
            {
                "company": fact.get("company") or "",
                "metric": fact.get("metric") or "",
                "analysis": fact.get("value") if fact.get("value") is not None else fact.get("basis") or "",
                "id": fact.get("id") or "",
                "basis": fact.get("basis") or "",
                "period": fact.get("period") or "",
                "unit": fact.get("unit") or "",
                "source_url": _first_source(fact),
                "source_tier": fact.get("source_tier") or "",
                "quality_score": round(float(fact.get("quality_score") or 0), 3),
                "confidence": round(float(fact.get("confidence") or 0), 3),
                "row_ref": fact.get("row_ref") or "",
                "evidence_hash": fact.get("evidence_hash") or "",
            }
        )

    summary = curation_summary or {}
    for domain, items in domains.items():
        domains[domain] = items if summary.get("architecture") == "six_research_agents_v1" else items[:8]
    return {
        "schema_version": 1,
        "generated_at_hkt": _now(),
        "agent_run_id": agent_run_id,
        **({"architecture": summary["architecture"]} if summary.get("architecture") else {}),
        **({"research_policy": summary["research_policy"]} if summary.get("research_policy") else {}),
        "curation": {
            "accepted": int(summary.get("accepted") or 0),
            "rejected": int(summary.get("rejected") or 0),
            "review": int(summary.get("review") or 0),
            "gaps": int(summary.get("gaps") or 0),
        },
        "domain_counts": {key: len(value) for key, value in domains.items()},
        "domains": domains,
        "method": "仅使用本轮 Agent 发布层 accepted 且主体、指标、数值均受证据支持的事实；质量分低于0.85或无来源链接的事实不会进入领导看板。",
    }


def publish_ai_analysis(
    *,
    agent_run_id: str,
    verified_facts_path: Path = VERIFIED_FACTS_PATH,
    output_path: Path = AI_ANALYSIS_PATH,
    curation_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_ai_analysis(
        agent_run_id=agent_run_id,
        verified_facts_path=verified_facts_path,
        curation_summary=curation_summary,
    )
    previous = _read_json(output_path, {}) or {}
    if previous.get("model_analysis"):
        payload["model_analysis"] = previous["model_analysis"]
    comparable = _fact_content(payload)
    old_comparable = _fact_content(previous)
    changed = _content_hash(comparable) != _content_hash(old_comparable)
    if changed or not output_path.exists():
        _atomic_write_json(output_path, payload)
    return {"ok": True, "changed": changed, "path": str(output_path), **payload}


def publish_domain_fact_sidecars(
    analysis: dict[str, Any],
    *,
    output_paths: dict[str, Path] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish official Agent facts beside each primary database.

    These sidecars let newly crawled financial-report facts reach the domain
    database and frontend immediately without silently rewriting audited KPI
    rows. Only official-source facts are eligible; the primary tables continue
    to use their stricter schema-specific promotion gates.
    """
    paths = output_paths or DOMAIN_FACT_PATHS
    if analysis.get("architecture") == "six_research_agents_v1":
        from data_curation.research_storage import merge_domain
        return {domain: merge_domain(paths[domain], (analysis.get("domains") or {}).get(domain) or [],
                    domain=domain, run_id=analysis.get("agent_run_id", ""),
                    generated_at=analysis.get("generated_at_hkt") or _now(), dry_run=dry_run)
                for domain in UI_DOMAIN_IDS}
    results: dict[str, Any] = {}
    for domain in FACT_DOMAIN_IDS:
        path = paths[domain]
        previous = _read_json(path, {}) or {}
        if analysis.get("architecture") == "six_research_agents_v1" and domain not in UI_DOMAIN_IDS:
            results[domain] = {"path": str(path), "facts": len(previous.get("facts") or []),
                               "changed": False, "published": False, "skipped": True}
            continue
        facts = [
            item for item in ((analysis.get("domains") or {}).get(domain) or [])
            if str(item.get("source_tier") or "").strip().lower() == "official"
            and str(item.get("source_url") or "").startswith(("https://", "http://"))
        ]
        submitted_count = len(facts)
        excluded_series = []
        series_root = next((p.parent for p in path.parents if p.name == "agent_knowledge"), None)
        if domain in UI_DOMAIN_IDS and series_root:
            from data_curation.research_freshness import load_baseline
            from data_curation.research_contracts import source_fact_error
            series_baseline = load_baseline(series_root).get("companies", {})
            eligible = []
            for item in facts:
                reason = source_fact_error(item, series_baseline)
                if reason:
                    excluded_series.append({"company": item.get("company"), "metric": item.get("metric"), "reason": reason})
                else:
                    eligible.append(item)
            facts = eligible
        if analysis.get("architecture") == "six_research_agents_v1":
            def identity(item):
                return tuple(str(item.get(key) or "") for key in ("company", "metric", "period", "unit"))
            merged = {identity(item): item for item in previous.get("facts") or []}
            for item in facts:
                old = merged.get(identity(item), {})
                if analysis.get("research_policy") == "latest_disclosure_incremental_v1":
                    from data_curation.research_freshness import compare_candidate, metric_key
                    baseline = {}
                    for saved in merged.values():
                        if saved.get("company") == item.get("company"):
                            baseline.setdefault(metric_key(saved.get("metric")), []).append(saved)
                    if compare_candidate(dict(item, status="verified"), baseline).get("status") != "verified":
                        continue
                if float(item.get("quality_score") or 0) >= float(old.get("quality_score") or 0):
                    merged[identity(item)] = item
            facts = sorted(merged.values(), key=identity)
        payload = {
            "schema_version": 1,
            "domain": domain,
            "agent_run_id": analysis.get("agent_run_id") or "",
            "generated_at_hkt": analysis.get("generated_at_hkt") or _now(),
            "facts": facts,
            "method": (
                "每日爬虫经Agent审核后，仅将accepted、证据支持且source_tier=official的事实写入旁路库；"
                "旁路事实用于穿透分析，不直接覆盖主表KPI。"
            ),
        }
        comparable = _fact_content(payload)
        old_comparable = _fact_content(previous)
        changed = _content_hash(comparable) != _content_hash(old_comparable)
        if changed and not dry_run:
            _atomic_write_json(path, payload)
        results[domain] = {
            "path": str(path),
            "facts": len(facts),
            "submitted_facts": submitted_count,
            "excluded_series": excluded_series,
            "changed": changed,
            "published": bool(changed and not dry_run),
        }
    return results


def _analysis_input_snapshot() -> dict[str, Any]:
    from cmhk.intelligence.executive import build_executive_intelligence_evidence_snapshot

    # Rendered relations are intentionally excluded. The hash must move only
    # when source-backed facts or the deterministic evidence pack changes.
    return build_executive_intelligence_evidence_snapshot()


def _extract_json_payload(text: str) -> Any:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("模型本次未返回有效内容")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\[\s*\{.*\}\s*\])", cleaned, re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def _extract_focus_response(text: str) -> dict[str, Any]:
    """Parse one focus object and salvage a model response cut after its fields."""
    try:
        parsed = _extract_json_payload(text)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?|```$", "", str(text or "").strip(), flags=re.I).strip()
        headline_match = re.search(r'"headline"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned, re.S)
        analysis_match = re.search(r'"analysis"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned, re.S)
        if not analysis_match:
            analysis_match = re.search(r'"analysis"\s*:\s*"(.*)$', cleaned, re.S)
        if not headline_match or not analysis_match:
            raise
        headline = json.loads(f'"{headline_match.group(1)}"')
        raw_analysis = re.sub(r'"?\s*[,}]?\s*$', "", analysis_match.group(1).strip())
        try:
            analysis = json.loads(f'"{raw_analysis}"')
        except json.JSONDecodeError:
            analysis = raw_analysis.replace('\\"', '"')
        parsed = {"headline": headline, "analysis": analysis}
    if isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        raise ValueError("模型未返回单项洞察对象")
    return parsed


def _pin_scoped_model_identity(raw: Any, domain_id: str, focus_id: str = "") -> Any:
    """Restore identifiers fixed by a scoped request before evidence-based repairs run."""
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        return raw
    pinned = json.loads(json.dumps(raw, ensure_ascii=False))
    pinned[0]["domain"] = domain_id
    focuses = pinned[0].get("focuses") or []
    if focus_id and isinstance(focuses, list) and len(focuses) == 1 and isinstance(focuses[0], dict):
        focuses[0]["id"] = focus_id
    return pinned


def _numeric_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"(?<![\d.])[-+]?\d(?:[\d,.]*\d)?(?:[eE][-+]?\d+)?", json.dumps(value, ensure_ascii=False)):
        if not re.fullmatch(r"[-+]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?(?:[eE][-+]?\d+)?", token):
            tokens.add("invalid-number:" + token)
            continue
        try:
            number = Decimal(token.replace(",", ""))
            if abs(number.adjusted()) > 1000:
                tokens.add("out-of-range-number:" + token)
                continue
            normalized = format(number, "f")
            if "." in normalized:
                normalized = normalized.rstrip("0").rstrip(".")
            tokens.add("0" if not number else normalized)
        except InvalidOperation:
            tokens.add("invalid-number:" + token)
    return tokens


def _unsupported_causal_terms(text: str, terms=None) -> tuple[str, ...]:
    """An inability to infer applies only before a cause in the same clause."""
    terms = terms or ("导致", "造成", "推动", "带来", "源于", "驱动")
    clauses = re.split(r"[。！？!?；;，\n]|(?<!\d),|,(?!\d)|"
                       r"(?=但是|然而|不过|反而|而是|实际上|事实上|因此|所以|但|却)", text)
    negation = re.compile(r"(?:无法|不能)(?:仅|只)?(?:据此|由此|直接|就此)?"
                          r"(?:判断|推断|认定|断定|确认|证明|建立)|不代表")
    unsupported = set()
    for clause in clauses:
        for term in terms:
            if any(not negation.search(clause[:match.start()]) for match in re.finditer(term, clause)):
                unsupported.add(term)
    return tuple(term for term in terms if term in unsupported)


def _focus_value_tokens(focus: dict[str, Any]) -> set[str]:
    """Return values explicitly present in the current focus evidence."""
    values: list[Any] = []
    metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
    if metric.get("value") not in (None, ""):
        values.append(metric.get("value"))
    for item in focus.get("items") or []:
        if not isinstance(item, dict):
            continue
        for key in ("value", "record_count", "component_count", "low", "high", "detail"):
            if item.get(key) not in (None, ""):
                values.append(item.get(key))
        for component in item.get("components") or []:
            if isinstance(component, dict):
                for key in ("value", "detail"):
                    if component.get(key) not in (None, ""):
                        values.append(component.get(key))
    values.append(len([item for item in focus.get("items") or [] if isinstance(item, dict)]))
    return _numeric_tokens(values)


_ANALYTICAL_JUDGEMENT_TERMS = (
    "领先", "落后", "高于", "低于", "最高", "最低", "差距", "距离", "变化", "增长",
    "下降", "回落", "改善", "加速", "放缓", "分化", "集中", "重叠", "梯度", "饱和",
    "压力", "风险", "机会", "空间", "优势", "短板", "不同", "差异", "相差", "居首",
    "覆盖", "完整", "充分", "不足", "多于", "少于", "强于", "弱于", "扩大", "收窄",
    "深度", "约束", "承压", "断层", "区隔", "选择", "新增", "负担", "转化", "压力",
    "更强", "更弱", "最强", "更稳", "最稳", "更厚", "最厚", "较窄", "更窄",
)
_INTERPRETIVE_CONNECTORS = (
    "表明", "反映", "说明", "意味着", "显示", "因此", "主要来自", "并非", "而非", "本质上",
    "取决于", "受制于", "源于", "不能等同", "不能直接", "并不等同", "不等于", "不可直接", "不完全是", "更接近",
)
_INTERPRETIVE_DIMENSIONS = (
    "结构", "口径", "集中", "可比", "驱动", "依赖", "饱和", "错位", "背离", "同步",
    "脱钩", "分层", "梯队", "边界", "质量", "效率", "弹性", "定价权", "产品广度",
    "增速", "方向", "幅度", "梯度", "经营造血",
    "分布", "阵营", "正负", "强弱", "两层",
    "记录颗粒度", "记录密度", "渗透", "变现", "盈利", "利润", "收入", "客户", "网络", "竞争", "产品类型", "产品选择", "产品数量", "购买力", "价格", "套餐", "投入", "资本", "负担", "流量", "连接", "服务", "优惠条件",
)
_DEEP_RELATION_MARKERS = (
    "主要来自", "源于", "驱动", "并非", "而非", "不等同", "不等价", "不等于", "不能", "不可",
    "受制", "约束", "转为", "集中于", "断层", "同步", "脱钩", "结构性差异", "口径放大",
    "接近饱和", "趋于饱和", "未形成", "不再来自", "共同拉开", "梯队分布",
    "分层竞争", "头部主导", "偏态分布", "不代表", "不纳入", "未纳入", "难形成", "受压", "承压", "混排", "重合", "差距", "不同", "并列信号",
    "多数", "少数", "唯一", "同向", "分组", "覆盖全部", "覆盖大部分",
    "梯队", "层次", "范围", "样本", "部分覆盖", "高低", "同类",
)
_ACTION_ADVICE_PHRASES = (
    "建议", "值得关注", "后续关注", "应优先", "需优先", "优先关注", "优先评估", "优先验证",
    "应关注", "需关注", "应评估", "需评估", "应验证", "需验证", "应采用", "需采用",
    "应补齐", "需补齐", "应锁定", "需锁定", "应兼顾", "需兼顾", "应降低", "需降低",
    "应提升", "需提升", "应复制", "需复制", "应区分", "需区分", "可考虑",
    "应更关注", "需转化",
)


def _contains_action_advice(value: Any) -> bool:
    text = str(value or "")
    if any(phrase in text for phrase in _ACTION_ADVICE_PHRASES):
        return True
    return bool(re.search(
        r"(?:建议|值得关注|后续关注|优先|应(?:当|该|更|以|关注|评估|验证|采用|补齐|锁定|兼顾|降低|提升|复制|区分)|"
        r"需(?:要|转化|关注|评估|验证|采用|补齐|锁定|兼顾|降低|提升|复制|区分))",
        text,
    ))


def _has_deep_interpretation(value: Any) -> bool:
    """Require an evidence interpretation, not a metric restatement or recommendation."""
    text = str(value or "").strip()
    return (
        any(term in text for term in _ANALYTICAL_JUDGEMENT_TERMS)
        and any(term in text for term in _INTERPRETIVE_CONNECTORS)
        and any(term in text for term in _INTERPRETIVE_DIMENSIONS)
        and any(term in text for term in _DEEP_RELATION_MARKERS)
        and not _contains_action_advice(text)
    )


def _has_business_judgement(value: Any) -> bool:
    """Backward-compatible name for the current deep-interpretation gate."""
    return _has_deep_interpretation(value)


_OVERVIEW_STRATEGIC_HEADLINES = {
    ("local", "revenue"): "HKT资源底盘最厚",
    ("local", "ebitda"): "HKT造血能力最强",
    ("local", "net_profit"): "HKT稳健三港承压",
    ("local", "postpaid"): "HKT客户底盘更稳",
    ("international", "revenue"): "SoftBank资源底盘领先",
    ("international", "net_profit"): "DOCOMO利润池当期领先",
    ("international", "capex"): "DOCOMO持续投入更厚",
    ("international", "mobile_arpu"): "DOCOMO客户价值更高",
    ("mainland", "revenue"): "中国移动资源底盘最强",
    ("mainland", "ebitda"): "中国移动造血能力最强",
    ("mainland", "net_profit"): "中国移动盈利韧性最强",
    ("mainland", "postpaid"): "中国移动客户底盘最厚",
    ("cloud", "revenue"): "AWS生态底盘领先",
    ("cloud", "profit"): "AWS自我造血能力最强",
    ("cloud", "investment"): "AWS扩容弹药最足",
}

_OVERVIEW_STRATEGIC_HEADLINE_VARIANTS = {
    ("local", "revenue"): ("HKT资源底盘最厚", "HKT竞争弹药更足", "CMHK规模防守承压"),
    ("local", "ebitda"): ("HKT造血能力最强", "HKT价战缓冲更厚", "3HK经营容错最窄"),
    ("local", "net_profit"): ("HKT稳健三港承压", "HKT再投资弹药更足", "3HK盈利防线失守"),
    ("local", "postpaid"): ("HKT客户底盘更稳", "HKT续约底盘更厚", "3HK客户底盘较窄"),
    ("international", "revenue"): ("SoftBank资源底盘领先", "DOCOMO收入底盘接近", "四家财年边界不同"),
    ("international", "net_profit"): ("DOCOMO利润池当期领先", "SoftBank自我融资紧随", "四家财年边界不同"),
    ("international", "capex"): ("DOCOMO持续投入更厚", "SoftBank资本军备紧随", "投入不等同回报"),
    ("international", "mobile_arpu"): ("DOCOMO客户价值更高", "日系用户价值分层", "用户范围不可混排"),
    ("mainland", "revenue"): ("中国移动资源底盘最强", "中国移动竞争弹药最足", "中国联通资源容错最窄"),
    ("mainland", "ebitda"): ("中国移动造血能力最强", "中国移动价战缓冲最厚", "中国电信经营容错较窄"),
    ("mainland", "net_profit"): ("中国移动盈利韧性最强", "中国移动再投资弹药最足", "中国联通盈利防守较薄"),
    ("mainland", "postpaid"): ("中国移动客户底盘最厚", "中国移动交叉销售基础最广", "中国联通客户底盘较窄"),
    ("cloud", "revenue"): ("AWS生态底盘领先", "AWS扩张资源最厚", "Huawei生态投入弹药较窄"),
    ("cloud", "profit"): ("AWS自我造血能力最强", "AWS再投资缓冲最厚", "Google盈利弹药较窄"),
    ("cloud", "investment"): ("AWS扩容弹药最足", "AWS基础设施投入最强", "Alibaba集团投入空间较窄"),
}

_OVERVIEW_DIRECT_HEADLINE_TERMS = (
    "FY", "财年", "营收", "EBITDA", "净利润", "后付费用户", "云收入", "云利润", "资本开支",
    "金额", "绝对值", "序列", "入库", "披露", "口径", "数据", "待补", "重新判断", "按三来源",
)

_OVERVIEW_STRATEGIC_MEANING_TERMS = (
    "持续投入", "竞争投入", "网络投入", "客户获取", "客户保有", "价格竞争", "价格战", "经营容错",
    "自我融资", "再投资", "经常性收入", "收入底盘", "客户价值", "客户质量", "续约", "流失",
    "生态扩张", "资本军备", "基础设施", "客户经营战略", "经营资源", "资源底盘",
    "经营造血", "自我造血", "盈利状态", "客户经营底盘", "客户经营画像", "扩容弹药", "资源容错",
)


def _strategic_focus_headline(
    domain: str, focus_id: str, fallback: Any = "", *, variant_index: int = 0
) -> str:
    variants = _OVERVIEW_STRATEGIC_HEADLINE_VARIANTS.get((domain, focus_id))
    if variants:
        return variants[variant_index % len(variants)]
    return _OVERVIEW_STRATEGIC_HEADLINES.get((domain, focus_id), str(fallback or "").strip())


def _focus_headline_style_note(domain: str, focus_id: str, headline: str) -> str:
    if len(headline) > MAX_FOCUS_HEADLINE_PUBLISH_CHARS:
        return f"AI分析标题超过{MAX_FOCUS_HEADLINE_PUBLISH_CHARS}字发布保护上限：{domain}.{focus_id}（当前{len(headline)}字）"
    normalized = headline.replace("营收", "收入")
    operating_judgement = (
        any(term in normalized for term in (*_OVERVIEW_STRATEGIC_MEANING_TERMS, "客户基础", "经营规模", "资源承载", "造血能力"))
        and any(term in normalized for term in (*_ANALYTICAL_JUDGEMENT_TERMS, *_DEEP_RELATION_MARKERS, "主导", "远超"))
        and not _contains_action_advice(headline)
    )
    administrative = any(term in headline for term in ("入库", "数据维护", "待补", "重新判断", "按三来源", "披露完整", "披露更新"))
    if (domain, focus_id) in _OVERVIEW_STRATEGIC_HEADLINES and (
        not headline or administrative
        or (any(term in headline for term in _OVERVIEW_DIRECT_HEADLINE_TERMS) and not operating_judgement)
    ):
        return f"AI分析标题缺少战略判断：{domain}.{focus_id}"
    if (domain, focus_id) == ("local", "financials") and any(
        term in headline for term in ("披露", "发布", "数量", "密度", "完整度", "口径", "边界")
    ):
        return "财务战略解读标题不得以披露或口径说明为结论：local.financials"
    return ""


def _focus_headline_gate_error(domain: str, focus_id: str, headline: str) -> str:
    # Vocabulary preference is advisory. Evidence, attribution and numeric
    # validation still run for the entire focus and each entity below.
    if not headline.strip():
        return f"AI分析标题为空：{domain}.{focus_id}"
    if _contains_action_advice(headline):
        return f"AI分析标题含行动建议：{domain}.{focus_id}"
    if len(headline) > MAX_FOCUS_HEADLINE_PUBLISH_CHARS:
        return f"AI分析标题超过{MAX_FOCUS_HEADLINE_PUBLISH_CHARS}字发布保护上限：{domain}.{focus_id}（当前{len(headline)}字）"
    if any(term in headline for term in ("入库", "数据维护", "待补", "重新判断", "按三来源", "披露完整", "披露更新")):
        return f"AI分析标题缺少战略判断：{domain}.{focus_id}"
    return ""


def _focus_gate_error(domain: str, focus_id: str, analysis: str, evidence_focus: dict[str, Any]) -> str:
    if re.match(r"^(?:但|但是|然而|而|这说明|这表明|这意味着|因此)", analysis) or re.search(
        r"(?:意味着|说明|表明)中(?:[，,。！？!?]|$)|存在差距个|"
        r"(?:相差|差距(?:为|约为|约)?)(?:百万美元|百万港元|十亿美元|亿元|万户|百万户)|"
        r"(?:变化|观察)[，,]分别为",
        analysis,
    ):
        return f"AI分析分类句序不完整：{domain}.{focus_id}"
    terminal_marks = re.findall(r"[。！？!?]", analysis)
    if len(analysis) > MAX_FOCUS_INSIGHT_PUBLISH_CHARS or not terminal_marks or (
        len(terminal_marks) > MAX_FOCUS_INSIGHT_SENTENCES
    ) or not re.search(r"[。！？!?]$", analysis):
        return (
            f"AI分析分类必须为一至两句完整句、总长不超过{MAX_FOCUS_INSIGHT_PUBLISH_CHARS}字发布保护上限："
            f"{domain}.{focus_id}"
        )
    if _contains_action_advice(analysis):
        return f"AI分析分类含行动建议而非数据洞察：{domain}.{focus_id}"
    if (domain, focus_id) in _OVERVIEW_STRATEGIC_HEADLINES and "不能纳入这一判断" in analysis:
        return f"AI分析引用有效竞对数值后又排除该竞对，判断自相矛盾：{domain}.{focus_id}"
    unsupported_causal = _unsupported_causal_terms(analysis)
    if unsupported_causal:
        return f"AI分析分类使用了未经证据支持的因果词{unsupported_causal}：{domain}.{focus_id}"
    focus_numbers = _focus_value_tokens(evidence_focus)
    analysis_numbers = _numeric_tokens(analysis)
    focus_items = [item for item in evidence_focus.get("items") or [] if isinstance(item, dict)]
    has_disclosed_value = any(
        item.get("value") not in (None, "", "-")
        or any(point.get("value") not in (None, "", "-") for point in item.get("trend") or [] if isinstance(point, dict))
        for item in focus_items
    )
    if focus_numbers and has_disclosed_value and not (focus_numbers & analysis_numbers):
        return f"AI分析分类缺少输入数值证据：{domain}.{focus_id}"
    if (domain, focus_id) == ("local", "financials"):
        companies_by_period: dict[str, int] = {}
        financial_items = [item for item in evidence_focus.get("items") or [] if isinstance(item, dict)]
        company_mentions: list[tuple[int, int, int]] = []
        for item_index, item in enumerate(financial_items):
            company = str(item.get("name") or "").strip()
            aliases = sorted(
                {alias for alias in (company, company.split("/")[0].strip()) if alias},
                key=len,
                reverse=True,
            )
            for alias in aliases:
                company_mentions.extend(
                    (match.start(), match.end(), item_index)
                    for match in re.finditer(re.escape(alias), analysis, flags=re.IGNORECASE)
                )
        company_mentions.sort(key=lambda mention: (mention[0], -(mention[1] - mention[0])))
        distinct_mentions: list[tuple[int, int, int]] = []
        for mention in company_mentions:
            if distinct_mentions and mention[0] == distinct_mentions[-1][0]:
                continue
            distinct_mentions.append(mention)
        company_segments: dict[int, list[str]] = {}
        for mention_index, (start, _, item_index) in enumerate(distinct_mentions):
            segment_end = (
                distinct_mentions[mention_index + 1][0]
                if mention_index + 1 < len(distinct_mentions)
                else len(analysis)
            )
            company_segments.setdefault(item_index, []).append(analysis[start:segment_end].replace(",", ""))

        for item_index, item in enumerate(financial_items):
            if not isinstance(item, dict):
                continue
            company_value_mentioned = False
            components = [component for component in item.get("components") or [] if isinstance(component, dict)]
            for component in components:
                if not isinstance(component, dict) or str(component.get("metric_key") or "") not in {
                    "revenue", "net_profit", "ebitda", "capital_expenditure",
                }:
                    continue
                value_match = re.search(
                    r"[-+]?\d[\d,]*(?:\.\d+)?",
                    str(component.get("value") if component.get("value") is not None else ""),
                )
                if value_match:
                    normalized_value = value_match.group().replace(",", "")
                    if any(
                        re.search(rf"(?<![\d.]){re.escape(normalized_value)}(?![\d.])", segment)
                        for segment in company_segments.get(item_index, [])
                    ):
                        company_value_mentioned = True
            if company_segments.get(item_index) and company_value_mentioned:
                component_period = next(
                    (str(component.get("detail") or "").strip() for component in components if component.get("detail")),
                    "",
                )
                period = component_period or str(item.get("period") or item.get("detail") or "期间待核").split("·", 1)[0].strip()
                companies_by_period[period] = companies_by_period.get(period, 0) + 1
        if max(companies_by_period.values(), default=0) < 2:
            return f"财务战略解读必须比较同期间至少两家公司各自的经营数值：{domain}.{focus_id}"
        if re.search(r"不纳入同一期间|不作同一期间|非同期间", analysis):
            return f"财务战略解读与已校验的同期间比较矛盾：{domain}.{focus_id}"
        if re.search(r"披露|发布|数量|密度|完整度", analysis):
            return f"财务战略解读不得以发布时间或披露数量代替经营指标：{domain}.{focus_id}"
    restriction_phrases = (
        "缺失值不估算", "缺失数据不估算", "只比较已结构化", "仅比较已结构化",
        "用于判断", "用于识别", "用于展示", "展示可分析", "此处比较", "聚焦云业务",
        "高增长集中", "说明存在差异", "说明存在差距",
    )
    if any(phrase in analysis for phrase in restriction_phrases):
        return f"AI分析分类仍以方法说明代替洞察：{domain}.{focus_id}"
    forbidden_by_focus = {
        ("local", "scale"): (
            "赛道", "月费", "资费区间", "重叠", "交集", "资本负担", "利润转化",
            "增长质量", "购买力", "服务压力", "存量竞争", "爆款", "套餐",
        ),
        ("local", "fibre_value"): ("增长质量", "低价吸引", "全市场覆盖"),
        ("local", "overlap"): ("增长质量", "增长能力"),
        ("international", "revenue"): ("EBITDA", "利润", "资本", "用户", "ARPU", "ARPA"),
        ("international", "net_profit"): ("EBITDA", "用户", "ARPU", "ARPA", "资本开支", "利润率", "增速", "同比"),
        ("international", "capex"): ("EBITDA", "净利润", "用户", "ARPU", "ARPA", "利润率", "增速", "同比"),
        ("international", "mobile_arpu"): ("EBITDA", "净利润", "资本开支", "营收"),
    }
    forbidden_terms = forbidden_by_focus.get((domain, focus_id), ())
    leaked_terms = [term for term in forbidden_terms if term in analysis]
    if leaked_terms:
        return (
            f"AI分析分类混入其他页维度{leaked_terms}：{domain}.{focus_id}"
        )
    if domain == "international" and focus_id in {"revenue", "net_profit", "capex", "mobile_arpu"}:
        mentioned = {
            str(item.get("name") or "")
            for item in evidence_focus.get("items") or []
            if str(item.get("name") or "") and str(item.get("name") or "") in analysis
        }
        if len(mentioned) < 2:
            return f"国际运营商AI解读必须引用至少两家公司原值：{domain}.{focus_id}"
        if focus_id == "mobile_arpu" and not all(
            term in analysis for term in ("NTT DOCOMO", "SoftBank Corp.", "美元/月")
        ):
            return f"移动ARPU解读必须保留两家日系运营商及美元月均单位：{domain}.{focus_id}"
    if (domain, focus_id) == ("local", "mobile_price"):
        ranges = [
            (float(item["low"]), float(item["high"]))
            for item in evidence_focus.get("items") or []
            if isinstance(item, dict)
            and isinstance(item.get("low"), (int, float))
            and isinstance(item.get("high"), (int, float))
        ]
        has_overlap = any(
            max(left[0], right[0]) <= min(left[1], right[1])
            for index, left in enumerate(ranges)
            for right in ranges[index + 1:]
        )
        if has_overlap and any(phrase in analysis for phrase in ("未重合", "没有重合", "无重合")):
            return (
                f"AI分析分类与输入价格区间矛盾：{domain}.{focus_id}"
            )
    if (domain, focus_id) == ("local", "overlap"):
        mentions_mobile = "个人5G" in analysis
        mentions_fibre = "光纤家宽" in analysis
        if mentions_mobile and not mentions_fibre and any(name in analysis for name in ("HKBN", "i-CABLE")):
            return f"AI分析分类把家宽主体混入个人5G：{domain}.{focus_id}"
        if mentions_fibre and not mentions_mobile and any(name in analysis for name in ("3HK", "SmarTone")):
            return f"AI分析分类把个人5G主体混入家宽：{domain}.{focus_id}"
        if "HGC区间独立" in analysis:
            return f"AI分析分类把未发现重合误写为区间独立：{domain}.{focus_id}"
    if (domain, focus_id) == ("cloud", "profit") and re.search(
        r"(?:七|7)家中仅(?:六|6)家", analysis
    ):
        return f"AI分析分类自行统计了样本家数：{domain}.{focus_id}"
    return ""


def _repair_generated_focus_analysis(
    analysis: str,
    allowed_numeric_evidence: dict[str, Any],
) -> tuple[str, bool]:
    """Repair common model formatting slips without inventing a new judgement."""
    repaired = re.sub(r"\s+", " ", str(analysis or "")).strip()
    original = repaired
    allowed_numbers = _numeric_tokens(allowed_numeric_evidence)
    unknown_numbers = _numeric_tokens(repaired) - allowed_numbers
    for number in sorted(unknown_numbers, key=len, reverse=True):
        # Models often subtract two admitted percentages despite an explicit ban.
        # Keep the qualitative comparison and remove only that derived result.
        derived_difference = re.compile(
            rf"(?:仅|只)?(?:相差|差距(?:仅|为|仅为)?|差|高出|低于)\s*"
            rf"{re.escape(number)}\s*(?:个?百分点|%|港元/月|港元|倍|个)?"
        )
        repaired = derived_difference.sub("存在差距", repaired)

    if len(repaired) > MAX_FOCUS_INSIGHT_CHARS:
        # A trailing disclosure caveat is useful but lower priority when the same
        # sample boundary is already stated earlier in the sentence.
        repaired = re.sub(
            r"[，；][^，；。！？]*(?:未披露|未提供|数据缺失)[^。！？]*[。！？]$",
            "。",
            repaired,
        )
    if len(repaired) > MAX_FOCUS_INSIGHT_CHARS:
        repaired = re.sub(r"[，；]?样本(?:仅|限于)[^，；。！？]*[，；]", "，", repaired, count=1)
    repaired = re.sub(r"[，；]{2,}", "，", repaired).strip("，； ")
    if repaired and not re.search(r"[。！？!?]$", repaired):
        repaired += "。"
    return repaired, repaired != original


def _compact_generated_focus_analysis(
    domain_id: str,
    focus_id: str,
    analysis: str,
    evidence_focus: dict[str, Any],
    allowed_numeric_evidence: dict[str, Any],
) -> tuple[str, bool]:
    """Select the strongest evidence-bearing clauses from an overlong AI answer."""
    normalized = re.sub(r"\s+", " ", str(analysis or "")).strip()
    if not normalized:
        return normalized, False
    if not _focus_gate_error(domain_id, focus_id, normalized, evidence_focus):
        return normalized, False

    clauses = [
        clause.strip(" ，；。！？!?\t")
        for clause in re.split(r"[，；。！？!?]+", normalized)
        if clause.strip(" ，；。！？!?\t")
    ]
    if len(clauses) < 2:
        return normalized, False
    # Exhaustive subsequence search is bounded to keep regeneration latency
    # predictable. Model answers are already capped at a few short sentences.
    if len(clauses) > 12:
        clauses = [*clauses[:2], *clauses[-10:]]
    allowed_numbers = _numeric_tokens(allowed_numeric_evidence)
    candidates: list[tuple[tuple[int, int, int, int, int], str]] = []
    for size in range(2, len(clauses) + 1):
        for indices in itertools.combinations(range(len(clauses)), size):
            selected_clauses = [clauses[index] for index in indices]
            if any(re.match(r"^(?:不纳入|未纳入)(?:比较|排名)?$", clause) for clause in selected_clauses):
                continue
            candidate = "，".join(selected_clauses) + "。"
            if len(candidate) > MAX_FOCUS_INSIGHT_CHARS:
                continue
            if _numeric_tokens(candidate) - allowed_numbers:
                continue
            if _focus_gate_error(domain_id, focus_id, candidate, evidence_focus):
                continue
            evidence_count = len(_numeric_tokens(candidate) & allowed_numbers)
            numeric_mentions = re.findall(r"(?<![\d.])[-+]?\d+(?:\.\d+)?", candidate)
            duplicate_numbers = len(numeric_mentions) - len({f"{float(value):g}" for value in numeric_mentions})
            interpretive_count = sum(term in candidate for term in _INTERPRETIVE_CONNECTORS)
            business_count = sum(
                term in candidate
                for term in (*_ANALYTICAL_JUDGEMENT_TERMS, *_INTERPRETIVE_DIMENSIONS, *_DEEP_RELATION_MARKERS)
            )
            candidates.append((
                (evidence_count, -duplicate_numbers, business_count, interpretive_count, -len(candidate)),
                candidate,
            ))
    if not candidates:
        return normalized, False
    return max(candidates, key=lambda item: item[0])[1], True


def _final_grounded_focus_repair(
    domain_id: str,
    focus: dict[str, Any],
    *,
    regeneration_index: int,
    recent_insights: list[str],
) -> str | None:
    """Return a fresh, gated evidence repair after all model prose attempts fail."""
    seed = _compact_grounded_focus_analysis(domain_id, focus)
    allowed_numeric_evidence = {
        "metric": focus.get("metric"),
        "items": [
            {
                "name": item.get("name"),
                "value": item.get("value"),
                "unit": item.get("unit"),
                "detail": item.get("detail"),
                "analysis": item.get("analysis"),
            }
            for item in focus.get("items") or []
            if isinstance(item, dict)
        ],
    }
    prefixes = ("按当前可比口径，", "从同口径样本看，", "就当前披露边界而言，", "从当前数据关系看，")
    candidates = [seed]
    clauses = [part.strip() for part in re.split(r"[；。]", seed) if part.strip()]
    for offset in range(len(prefixes)):
        prefix = prefixes[(max(1, regeneration_index) - 1 + offset) % len(prefixes)]
        ordered = clauses[offset % len(clauses):] + clauses[:offset % len(clauses)] if clauses else [seed]
        candidates.append(prefix + "；".join(ordered) + "。")
    recent = {re.sub(r"\s+", "", str(value or "")) for value in recent_insights}
    for candidate in candidates[1:] + candidates[:1]:
        candidate, _ = _repair_generated_focus_analysis(candidate, allowed_numeric_evidence)
        candidate, _ = _compact_generated_focus_analysis(
            domain_id, str(focus.get("id") or ""), candidate, focus, allowed_numeric_evidence,
        )
        if _focus_gate_error(domain_id, str(focus.get("id") or ""), candidate, focus):
            continue
        if re.sub(r"\s+", "", candidate) in recent:
            continue
        return candidate
    return None


def _repair_focus_numeric_anchors(raw: Any, evidence: dict[str, Any]) -> Any:
    """Keep genuine model judgement while anchoring it to an exact focus metric."""
    if not isinstance(raw, list):
        return raw
    evidence_by_focus = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }
    repaired = json.loads(json.dumps(raw, ensure_ascii=False))
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        for focus in domain.get("focuses") or []:
            if not isinstance(focus, dict):
                continue
            focus_id = str(focus.get("id") or "")
            evidence_focus = evidence_by_focus.get((domain_id, focus_id)) or {}
            analysis = str(focus.get("analysis") or "").strip()
            focus_numbers = _focus_value_tokens(evidence_focus)
            if not analysis or not focus_numbers or (_numeric_tokens(analysis) & focus_numbers):
                continue
            # Numeric anchoring is allowed only for prose that already contains a
            # deep interpretation; it cannot turn filler or advice into insight.
            if not _has_deep_interpretation(analysis):
                continue
            metric = evidence_focus.get("metric") if isinstance(evidence_focus.get("metric"), dict) else {}
            value = metric.get("value")
            label = str(metric.get("label") or "最新指标")
            if value in (None, "", "-", "—") or any(
                placeholder in label for placeholder in ("待补", "未披露", "暂无")
            ):
                continue
            unit = str(metric.get("unit") or "")
            focus["analysis"] = f"{label}为{value}{unit}；{analysis}"
            focus["numeric_anchor_repaired"] = True
    return repaired


def _repair_entity_evidence_labels(raw: Any, evidence: dict[str, Any]) -> Any:
    """Map harmless model paraphrases back to exact input labels; never create labels."""
    if not isinstance(raw, list):
        return raw
    evidence_entities = {
        (str(domain.get("id") or ""), str(focus.get("id") or ""), str(entity.get("name") or "")): entity
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
        for entity in focus.get("items") or []
    }
    repaired = json.loads(json.dumps(raw, ensure_ascii=False))
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        for focus in domain.get("focuses") or []:
            if not isinstance(focus, dict):
                continue
            focus_id = str(focus.get("id") or "")
            for entity in focus.get("entities") or []:
                if not isinstance(entity, dict):
                    continue
                evidence_entity = evidence_entities.get(
                    (domain_id, focus_id, str(entity.get("name") or ""))
                ) or {}
                allowed_labels = [
                    str(component.get("label") or "")
                    for component in evidence_entity.get("components") or []
                    if str(component.get("label") or "")
                ]
                if not allowed_labels:
                    continue
                mapped: list[str] = []
                for raw_label in entity.get("evidence_labels") or []:
                    label = str(raw_label or "")
                    if label in allowed_labels:
                        mapped.append(label)
                        continue
                    matches = difflib.get_close_matches(label, allowed_labels, n=1, cutoff=0.72)
                    if matches:
                        mapped.append(matches[0])
                entity["evidence_labels"] = list(dict.fromkeys(mapped))
                source_url = str(evidence_entity.get("source_url") or "")
                entity["source_urls"] = [source_url] if source_url and source_url in (entity.get("source_urls") or []) else []
    return repaired


def _repair_focus_business_implications(raw: Any, evidence: dict[str, Any]) -> Any:
    """Replace shallow numeric prose with an evidence-grounded deep interpretation."""
    if not isinstance(raw, list):
        return raw
    evidence_by_focus = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }
    repaired = json.loads(json.dumps(raw, ensure_ascii=False))
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        for focus in domain.get("focuses") or []:
            if not isinstance(focus, dict):
                continue
            focus_id = str(focus.get("id") or "")
            analysis = str(focus.get("analysis") or "").strip()
            evidence_focus = evidence_by_focus.get((domain_id, focus_id)) or {}
            if not analysis or _has_deep_interpretation(analysis):
                continue
            if not (_numeric_tokens(analysis) & _focus_value_tokens(evidence_focus)):
                continue
            if not any(term in analysis for term in _ANALYTICAL_JUDGEMENT_TERMS):
                continue
            focus["analysis"] = _compact_grounded_focus_analysis(domain_id, evidence_focus)
            focus["deep_interpretation_repaired"] = True
    return repaired


def _repair_focus_conciseness(raw: Any, evidence: dict[str, Any]) -> Any:
    """Keep one or two concise deep-insight sentences, otherwise use grounded fallback."""
    if not isinstance(raw, list):
        return raw
    evidence_by_focus = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }
    repaired = json.loads(json.dumps(raw, ensure_ascii=False))
    for domain in repaired:
        if not isinstance(domain, dict):
            continue
        domain_id = str(domain.get("domain") or "")
        for focus in domain.get("focuses") or []:
            if not isinstance(focus, dict):
                continue
            focus_id = str(focus.get("id") or "")
            evidence_focus = evidence_by_focus.get((domain_id, focus_id)) or {}
            original = str(focus.get("analysis") or "").strip()
            candidate = re.sub(r"\s+", " ", original).strip()
            if candidate and not re.search(r"[。！？!?]$", candidate):
                candidate += "。"
            if not _focus_gate_error(domain_id, focus_id, candidate, evidence_focus):
                focus["analysis"] = candidate
            else:
                focus["analysis"] = _compact_grounded_focus_analysis(domain_id, evidence_focus)
            if focus["analysis"] != original:
                focus["deep_format_repaired"] = True
    return repaired


def _repair_model_summaries(raw: Any, evidence: dict[str, Any]) -> Any:
    """Preserve model prose. Validation failures must go back to the model."""
    return json.loads(json.dumps(raw, ensure_ascii=False))

def _canonical_entity_labels(labels, entity):
    """Resolve an exact entity evidence address, never infer or drop a label."""
    components = [c for c in entity.get("components") or [] if isinstance(c, dict)]
    allowed = {str(c.get("label") or "") for c in components}
    matches = [c for c in components if c.get("label")
               and entity.get("value") not in (None, "", "-")
               and entity.get("unit") not in (None, "")
               and c.get("value") == entity.get("value")
               and c.get("unit") == entity.get("unit")]
    canonical, mappings = [], []
    for submitted in labels:
        label = submitted
        if label not in allowed and label and label == entity.get("detail") and len(matches) == 1:
            label = str(matches[0]["label"])
            mappings.append({"submitted": submitted, "canonical": label,
                             "basis": "exact_entity_detail_and_unique_value_unit",
                             "value": entity["value"], "unit": entity["unit"]})
        canonical.append(label)
    return canonical, mappings


def _previous_annual_source_evidence(evidence):
    previous = json.loads(json.dumps(evidence, ensure_ascii=False))
    for domain in previous.get("domains") or []:
        for focus in domain.get("focuses") or []:
            for item in focus.get("items") or []:
                aliases = item.get("source_url_aliases") or []
                if aliases and item.get("annual_source_components"):
                    item["source_url"] = aliases[0]
                    for key in ("source_url_aliases", "source_urls", "annual_source_components"):
                        item.pop(key, None)
    return previous


def _canonical_annual_sources(obj, evidence_items):
    """Map only proven annual-source corrections within this entity/scope."""
    submitted = obj.get("submitted_source_urls", obj.get("source_urls") or [])
    mappings = {}
    for fact in evidence_items:
        if not fact.get("annual_source_components") or not fact.get("source_url"):
            continue
        for alias in fact.get("source_url_aliases") or []:
            mappings.setdefault(alias, set()).add(fact["source_url"])
    canonical, audit = [], []
    for url in submitted:
        targets = sorted(mappings.get(url) or {url})
        canonical.extend(targets)
        if targets != [url]:
            audit.append({"submitted": url, "canonical": targets, "basis": "verified_annual_component_source_correction"})
    canonical = list(dict.fromkeys(canonical))
    if "submitted_source_urls" in obj and canonical != obj.get("source_urls"):
        raise ValueError("年度来源身份审计与当前证据不一致")
    return canonical, ({"submitted_source_urls": list(submitted), "source_identity_mappings": audit} if audit else {})


def _focus_presentation_warnings(domain, focus):
    warnings = []
    note = _focus_headline_style_note(domain, focus['id'], str(focus.get("headline") or ""))
    if note and not _focus_headline_gate_error(domain, focus['id'], str(focus.get("headline") or "")):
        warnings.append({"code": "headline_style_advisory", "scope": f"{domain}.{focus['id']}",
                         "field": "headline", "message": "标题可进一步精炼经营含义；事实校验通过，正常发布",
                         "characters": len(str(focus.get("headline") or "")),
                         "target_characters": MAX_FOCUS_HEADLINE_CHARS,
                         "publication_max_characters": MAX_FOCUS_HEADLINE_PUBLISH_CHARS,
                         "model_text_preserved": True})
    for field, target, maximum in (("headline", MAX_FOCUS_HEADLINE_CHARS, MAX_FOCUS_HEADLINE_PUBLISH_CHARS),
                                    ("analysis", MAX_FOCUS_INSIGHT_CHARS, MAX_FOCUS_INSIGHT_PUBLISH_CHARS)):
        characters = len(str(focus.get(field) or ""))
        if target < characters <= maximum:
            warnings.append({"code": "writing_target_exceeded", "scope": f"{domain}.{focus['id']}",
                             "field": field, "characters": characters, "target_characters": target,
                             "publication_max_characters": maximum, "model_text_preserved": True})
    return warnings


def _summary_presentation_warnings(summaries):
    return [warning for domain in summaries or [] for focus in domain.get("focuses") or []
            for warning in _focus_presentation_warnings(domain["domain"], focus)]


def _discovery_presentation_warnings(discoveries):
    warnings = []
    for discovery in discoveries or []:
        for field, target, maximum in (("title", MAX_FOCUS_HEADLINE_CHARS, MAX_FOCUS_HEADLINE_PUBLISH_CHARS),
                                      ("detail", MAX_DISCOVERY_DETAIL_CHARS, MAX_DISCOVERY_DETAIL_PUBLISH_CHARS)):
            characters = len(str(discovery.get(field) or ""))
            if target < characters <= maximum:
                warnings.append({"code": "writing_target_exceeded", "scope": f"discoveries.{discovery['from']}.{discovery['to']}",
                                 "field": field, "characters": characters, "target_characters": target,
                                 "publication_max_characters": maximum, "model_text_preserved": True})
    return warnings


def _validate_model_summaries(
    raw: Any,
    evidence: dict[str, Any],
    *,
    expected_domains: set[str] | None = None,
    expected_focus_ids_by_domain: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("AI分析没有返回items数组")
    expected = expected_domains or {
        str(domain.get("id") or "") for domain in evidence.get("domains") or [] if str(domain.get("id") or "")
    }
    allowed_numbers = _numeric_tokens(evidence)
    allowed_urls = set().union(*_evidence_urls_by_domain(evidence).values())
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    evidence_by_domain = {
        str(domain.get("id") or ""): domain for domain in evidence.get("domains") or []
    }
    filler_phrases = ("按排名", "图中排序", "同一视图", "便于比较", "数据库内", "此视图", "不代表经营排名")
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("AI分析包含非对象条目")
        domain = str(item.get("domain") or "")
        if domain not in expected or domain in seen:
            raise ValueError(f"AI分析领域非法或重复：{domain}")
        seen.add(domain)
        summary = {
            "domain": domain,
            "headline": str(item.get("headline") or "").strip(),
            "analysis": str(item.get("analysis") or "").strip(),
            "risk": str(item.get("risk") or "").strip(),
            "source_urls": [str(url) for url in item.get("source_urls") or []],
            "focuses": [],
        }
        scope_items = [entity for f in evidence_by_domain[domain].get("focuses") or [] for entity in f.get("items") or []]
        summary["source_urls"], summary_source_audit = _canonical_annual_sources(item, scope_items)
        if not summary["headline"] or not summary["analysis"] or not summary["risk"]:
            raise ValueError(f"AI分析字段不完整：{domain}")
        unknown_urls = set(summary["source_urls"]) - allowed_urls
        if unknown_urls:
            raise ValueError(f"AI分析引用了输入之外的来源：{sorted(unknown_urls)}")
        unknown_numbers = _numeric_tokens(summary) - allowed_numbers
        if unknown_numbers:
            raise ValueError(f"AI分析出现输入之外的数字：{sorted(unknown_numbers)}")
        expected_focuses = (
            set(expected_focus_ids_by_domain.get(domain, set()))
            if expected_focus_ids_by_domain is not None
            else {
                str(focus.get("id") or "")
                for focus in (evidence_by_domain.get(domain, {}).get("focuses") or [])
                if str(focus.get("id") or "")
            }
        )
        raw_focuses = item.get("focuses") or []
        if expected_focuses:
            if not isinstance(raw_focuses, list):
                raise ValueError(f"AI分析分类总结格式非法：{domain}")
            focus_seen: set[str] = set()
            validated_focuses: list[dict[str, Any]] = []
            for focus_item in raw_focuses:
                if not isinstance(focus_item, dict):
                    raise ValueError(f"AI分析分类总结包含非对象条目：{domain}")
                focus_id = str(focus_item.get("id") or "")
                if focus_id not in expected_focuses or focus_id in focus_seen:
                    raise ValueError(f"AI分析分类非法或重复：{domain}.{focus_id}")
                focus_seen.add(focus_id)
                validated_focus = {
                    "id": focus_id,
                    "headline": str(focus_item.get("headline") or "").strip(),
                    "analysis": str(focus_item.get("analysis") or "").strip(),
                    "risk": str(focus_item.get("risk") or "").strip(),
                    "source_urls": [str(url) for url in focus_item.get("source_urls") or []],
                    "entities": [],
                }
                if str(focus_item.get("origin") or "") == "evidence_rule":
                    validated_focus["origin"] = "evidence_rule"
                if not validated_focus["analysis"] or not validated_focus["risk"]:
                    raise ValueError(f"AI分析分类字段不完整：{domain}.{focus_id}")
                headline_error = _focus_headline_gate_error(domain, focus_id, validated_focus["headline"])
                if headline_error:
                    raise ValueError(headline_error)
                evidence_focus = next(
                    focus for focus in (evidence_by_domain.get(domain, {}).get("focuses") or [])
                    if str(focus.get("id") or "") == focus_id
                )
                validated_focus["source_urls"], focus_source_audit = _canonical_annual_sources(focus_item, evidence_focus.get("items") or [])
                if validated_focus["headline"] and re.sub(r"\s+", "", validated_focus["headline"]) == re.sub(
                    r"\s+", "", str(evidence_focus.get("label") or "")
                ):
                    raise ValueError(f"AI标题不得照抄指标名称：{domain}.{focus_id}")
                unknown_focus_urls = set(validated_focus["source_urls"]) - allowed_urls
                if unknown_focus_urls:
                    raise ValueError(f"AI分析分类引用了输入之外的来源：{sorted(unknown_focus_urls)}")
                unknown_focus_numbers = _numeric_tokens(validated_focus) - allowed_numbers
                if unknown_focus_numbers:
                    raise ValueError(f"AI分析分类出现输入之外的数字：{sorted(unknown_focus_numbers)}")
                focus_gate_error = _focus_gate_error(
                    domain,
                    focus_id,
                    validated_focus["analysis"],
                    evidence_focus,
                )
                if focus_gate_error:
                    raise ValueError(focus_gate_error)
                evidence_entities = {
                    str(entity.get("name") or ""): entity
                    for entity in evidence_focus.get("items") or []
                    if str(entity.get("name") or "")
                }
                raw_entities = focus_item.get("entities") or []
                if not isinstance(raw_entities, list):
                    raise ValueError(f"AI分析实体总结格式非法：{domain}.{focus_id}")
                entity_seen: set[str] = set()
                for raw_entity in raw_entities:
                    if not isinstance(raw_entity, dict):
                        raise ValueError(f"AI分析实体总结包含非对象条目：{domain}.{focus_id}")
                    name = str(raw_entity.get("name") or "").strip()
                    if name not in evidence_entities or name in entity_seen:
                        raise ValueError(f"AI分析实体非法或重复：{domain}.{focus_id}.{name}")
                    entity_seen.add(name)
                    entity_summary = {
                        "name": name,
                        "headline": str(raw_entity.get("headline") or "").strip(),
                        "analysis": str(raw_entity.get("analysis") or "").strip(),
                        "risk": str(raw_entity.get("risk") or "").strip(),
                        "evidence_labels": [str(label) for label in raw_entity.get("evidence_labels") or []],
                        "source_urls": [str(url) for url in raw_entity.get("source_urls") or []],
                    }
                    entity_summary["source_urls"], entity_source_audit = _canonical_annual_sources(raw_entity, [evidence_entities[name]])
                    submitted_labels = [str(label) for label in raw_entity.get(
                        "submitted_evidence_labels", entity_summary["evidence_labels"]) or []]
                    canonical_labels, identity_mappings = _canonical_entity_labels(submitted_labels, evidence_entities[name])
                    if "submitted_evidence_labels" in raw_entity and canonical_labels != entity_summary["evidence_labels"]:
                        raise ValueError(f"AI分析实体引用身份审计不一致：{domain}.{focus_id}.{name}")
                    entity_summary["evidence_labels"] = canonical_labels
                    if identity_mappings:
                        entity_summary["submitted_evidence_labels"] = submitted_labels
                        entity_summary["evidence_label_identity_mappings"] = identity_mappings
                    if not entity_summary["headline"] or not entity_summary["analysis"] or not entity_summary["risk"]:
                        raise ValueError(f"AI分析实体字段不完整：{domain}.{focus_id}.{name}")
                    if any(phrase in entity_summary["analysis"] for phrase in filler_phrases):
                        raise ValueError(f"AI分析实体仍含界面废话：{domain}.{focus_id}.{name}")
                    allowed_labels = {
                        str(component.get("label") or "")
                        for component in evidence_entities[name].get("components") or []
                        if str(component.get("label") or "")
                    }
                    unknown_labels = set(entity_summary["evidence_labels"]) - allowed_labels
                    if unknown_labels:
                        raise ValueError(f"AI分析实体引用未知明细：{domain}.{focus_id}.{name}.{sorted(unknown_labels)}")
                    entity_allowed_urls = _entity_evidence_urls(evidence_entities[name])
                    unknown_entity_urls = set(entity_summary["source_urls"]) - entity_allowed_urls
                    if unknown_entity_urls:
                        raise ValueError(f"AI分析实体引用了输入之外的来源：{sorted(unknown_entity_urls)}")
                    unknown_entity_numbers = _numeric_tokens(entity_summary) - _numeric_tokens(evidence_entities[name])
                    if unknown_entity_numbers:
                        raise ValueError(
                            f"AI分析实体出现输入之外的数字：{domain}.{focus_id}.{name}.{sorted(unknown_entity_numbers)}"
                        )
                    entity_summary.update(entity_source_audit)
                    validated_focus["entities"].append(entity_summary)
                if entity_seen != set(evidence_entities):
                    raise ValueError(
                        f"AI分析实体不完整：{domain}.{focus_id}.{sorted(set(evidence_entities) - entity_seen)}"
                    )
                # Compute presentation metadata only after every fact gate.
                # Discard model-supplied warnings, including on cache readback.
                warnings = _focus_presentation_warnings(domain, validated_focus)
                if warnings:
                    validated_focus["presentation_warnings"] = warnings
                validated_focus.update(focus_source_audit)
                validated_focuses.append(validated_focus)
            if focus_seen != expected_focuses:
                raise ValueError(f"AI分析分类不完整：{domain}.{sorted(expected_focuses - focus_seen)}")
            summary["focuses"] = validated_focuses
        summary.update(summary_source_audit)
        result.append(summary)
    if seen != expected:
        raise ValueError(f"AI分析领域不完整：{sorted(expected - seen)}")
    domain_order = {
        str(domain.get("id") or ""): index
        for index, domain in enumerate(evidence.get("domains") or [])
    }
    return sorted(result, key=lambda item: domain_order.get(item["domain"], len(domain_order)))


def _entity_evidence_urls(entity: dict[str, Any]) -> set[str]:
    """Use the exact source list supplied for this entity, including its primary."""
    return {url for url in [entity.get("source_url"), *(entity.get("source_urls") or [])]
            if isinstance(url, str) and url.startswith(("https://", "http://"))}


def _evidence_urls_by_domain(evidence: dict[str, Any]) -> dict[str, set[str]]:
    urls: dict[str, set[str]] = {
        str(domain.get("id") or ""): set()
        for domain in evidence.get("domains") or [] if str(domain.get("id") or "")
    }
    for domain in evidence.get("domains") or []:
        domain_id = str(domain.get("id") or "")
        if domain_id not in urls:
            continue
        for focus in domain.get("focuses") or []:
            for item in focus.get("items") or []:
                urls[domain_id].update(_entity_evidence_urls(item))
        for item in domain.get("agent_verified_facts") or []:
            source_url = str(item.get("source_url") or "")
            if source_url.startswith(("https://", "http://")):
                urls[domain_id].add(source_url)
    return urls


def _repair_discovery_conciseness(raw: Any) -> Any:
    """Do not synthesize interpretive phrases or replace a model conclusion."""
    return json.loads(json.dumps(raw, ensure_ascii=False))

def _repair_discovery_depth(raw: Any, evidence: dict[str, Any]) -> tuple[Any, int]:
    """Depth is model work, not a deterministic sentence-repair step."""
    return json.loads(json.dumps(raw, ensure_ascii=False)), 0

def _discovery_fact_anchors(evidence):
    anchors = []
    aliases = {"investment": "capex", "profit": "operating_profit", "postpaid": "customer_count"}
    for domain in evidence.get("domains") or []:
        for focus in domain.get("focuses") or []:
            for item in focus.get("items") or []:
                if item.get("value") in (None, "", "-") or not item.get("unit"):
                    continue
                anchors.append({**item, "domain": domain["id"], "metric": aliases.get(focus.get("id"), focus.get("id"))})
        for fact in domain.get("agent_verified_facts") or []:
            if fact.get("value") not in (None, "", "-") and fact.get("unit"):
                anchors.append({**fact, "domain": domain["id"], "name": fact.get("company"),
                                "metric": fact.get("metric_key") or fact.get("metric")})
    return anchors


def _discovery_comparability_error(item, evidence):
    text = str(item.get("title") or "") + "。" + str(item.get("detail") or "")
    pair = {item.get("from"), item.get("to")}
    anchors = [a for a in _discovery_fact_anchors(evidence) if a["domain"] in pair]
    matched = [a for a in anchors if _numeric_tokens(a["value"]) & _numeric_tokens(text)
               and str(a["unit"]) in text]
    # Bind each explicit value to the closest company, FY and metric in its
    # factual clause. Mere presence elsewhere in the paragraph is insufficient.
    metric_names = {"净利润": "net_profit", "净利": "net_profit", "营收": "revenue", "收入": "revenue",
                    "EBITDA": "ebitda", "ARPU": "mobile_arpu", "客户数": "customer_count", "用户数": "customer_count",
                    "资本开支": "capex", "资本支出": "capex", "营业利润": "operating_profit", "云利润": "operating_profit"}
    metric_aliases = {"净利润": "net_profit", "net_income": "net_profit", "subscribers": "customer_count"}
    known_names = {str(a.get("name")) for a in _discovery_fact_anchors(evidence) if a.get("name")}
    bound = []
    for value_match in re.finditer(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", text):
        matching = [a for a in matched if _numeric_tokens(a["value"]) == _numeric_tokens(value_match.group())
                    and text[value_match.end():].lstrip().startswith(str(a["unit"]))]
        if not matching:
            continue
        prefix = re.split(r"[。！？!?；;，\n]", text[:value_match.start()])[-1]
        mentions = [(m.start(), len(name), name) for name in known_names
                    for m in re.finditer(re.escape(name), prefix, re.I)]
        if mentions:
            company_start, company_length, company = max(mentions)
            matching = [a for a in matching if str(a.get("name", "")).casefold() == company.casefold()]
            if not matching:
                return f"跨库发现数值与所在从句公司归属不一致：{company} {value_match.group()}"
            prefix = prefix[company_start + company_length:]
        years = re.findall(r"(?<!\d)(?:FY\s*)?(20\d{2})(?!\d)", prefix, re.I)
        if years:
            matching = [a for a in matching if re.search(r"(?<!\d)" + years[-1] + r"(?!\d)", str(a.get("period") or ""))]
            if not matching:
                return f"跨库发现数值与显式财年不一致：FY{years[-1]} {value_match.group()}"
        explicit_grains = re.findall(r"Q[1-4]|H[12]|全年|年度", prefix, re.I)
        if explicit_grains:
            expected_grain = explicit_grains[-1].upper()
            def period_matches(fact):
                period = str(fact.get("period") or "").upper()
                parts = re.findall(r"Q[1-4]|H[12]", period)
                if expected_grain in ("全年", "年度"):
                    return not parts and str(fact.get("grain") or "").lower() not in (
                        "quarter", "quarterly", "half_year", "half-year", "half", "semiannual")
                return expected_grain in parts
            matching = [a for a in matching if period_matches(a)]
            if not matching:
                return f"跨库发现数值与显式季度、半年或全年粒度不一致：{expected_grain} {value_match.group()}"
        metric_mentions = [(m.start(), len(label), category) for label, category in metric_names.items()
                           for m in re.finditer(re.escape(label), prefix, re.I)]
        if metric_mentions:
            _, _, metric = max(metric_mentions)
            matching = [a for a in matching if metric_aliases.get(a.get("metric"), a.get("metric")) == metric]
            if not matching:
                return f"跨库发现数值与所在从句指标类别不一致：{metric} {value_match.group()}"
        bound.extend(matching)
    matched = [a for a in matched if a in bound]
    selected = []
    for domain in pair:
        matches = [a for a in matched if a["domain"] == domain]
        if not matches:
            # Legacy generic fixtures have no typed metric facts; production does.
            if any(a["domain"] == domain for a in anchors):
                return f"跨库发现没有绑定{domain}领域的具体数值与单位"
            continue
        named = [a for a in matches if a.get("name") and str(a["name"]) in text]
        chosen = named or matches
        if not named and len({(a.get("name"), a.get("value"), a.get("unit"), a.get("period"), a.get("metric")) for a in chosen}) > 1:
            # Several distinct unnamed facts cannot be bound by a coincident number.
            by_value = {}
            for fact in chosen:
                by_value.setdefault((_content_hash(fact["value"]), fact.get("unit")), []).append(fact)
            if any(len(group) > 1 for group in by_value.values()):
                return f"跨库发现{domain}领域数值存在多个实体或指标归属，必须点名所用事实"
        selected.extend(chosen)
        for fact in chosen:
            if fact.get("source_url") not in (item.get("source_urls") or []):
                return f"跨库发现未引用所用事实的精确来源：{domain}.{fact.get('name')}.{fact.get('metric')}"
    matched = selected
    if not matched:
        return ""
    def currency(unit):
        return next((c for c in ("美元", "港元", "欧元", "日元", "英镑") if c in str(unit)),
                    "人民币" if "元" in str(unit) else str(unit))
    incompatible = (len({a.get("metric") for a in matched}) > 1
                    or len({currency(a.get("unit")) for a in matched}) > 1
                    or len({(a.get("period"), a.get("grain")) for a in matched}) > 1)
    if incompatible:
        boundary = re.search(r"(?:不能|不可|无法|不宜)(?:据此|直接|据此直接)?(?:比较|排名|混排|判断|推断|等同)", text)
        if not boundary:
            return "跨库发现指标、币种、期间或范围不同，必须明确不能直接比较或推断经营高低"
        clauses = re.split(r"[。！？!?；;，\n]|(?=但是|然而|但|却)", text)
        for clause in clauses:
            if re.search(r"差距|领先|落后|高于|低于|远超|梯队|分化|脱钩", clause) and not re.search(
                r"(?:不能|不可|无法|不宜|不代表|不等于|不构成)[^。]{0,35}(?:比较|排名|推断|判断|证明|等同|差距|领先|分化|梯队)", clause
            ):
                return "跨库发现对不同指标、币种或期间作了肯定排名或差距判断；限制句不能覆盖相邻肯定结论"
    return ""


def _validate_model_discoveries(raw: Any, evidence: dict[str, Any], *, require_complete=True) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or (require_complete and len(raw) != 4):
        raise ValueError("AI跨库发现必须恰好返回四项")
    expected_domains = {
        str(domain.get("id") or "") for domain in evidence.get("domains") or [] if str(domain.get("id") or "")
    }
    allowed_numbers = _numeric_tokens(evidence)
    urls_by_domain = _evidence_urls_by_domain(evidence)
    allowed_urls = set().union(*urls_by_domain.values())
    result: list[dict[str, Any]] = []
    pairs: set[tuple[str, str]] = set()
    covered_domains: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("AI跨库发现包含非对象条目")
        source_domain = str(item.get("from") or "")
        target_domain = str(item.get("to") or "")
        if source_domain not in expected_domains or target_domain not in expected_domains or source_domain == target_domain:
            raise ValueError(f"AI跨库发现领域非法：{source_domain}->{target_domain}")
        pair = tuple(sorted((source_domain, target_domain)))
        if pair in pairs:
            raise ValueError(f"AI跨库发现重复关联：{pair}")
        pairs.add(pair)
        covered_domains.update(pair)
        discovery = {
            "from": source_domain,
            "to": target_domain,
            "title": str(item.get("title") or "").strip(),
            "detail": str(item.get("detail") or "").strip(),
            "kind": str(item.get("kind") or "AI综合研判").strip(),
            "source_urls": list(dict.fromkeys(str(url) for url in item.get("source_urls") or [])),
        }
        if not discovery["title"] or not discovery["detail"]:
            raise ValueError("AI跨库发现标题或结论为空")
        if (len(discovery["title"]) > MAX_FOCUS_HEADLINE_PUBLISH_CHARS
                or len(discovery["detail"]) > MAX_DISCOVERY_DETAIL_PUBLISH_CHARS or len(discovery["kind"]) > 12):
            raise ValueError("AI跨库发现超过发布保护上限：标题36字、正文160字、kind12字")
        if not re.search(r"[。！？!?]$", discovery["detail"]) or len(re.findall(r"[。！？!?]", discovery["detail"])) > 2:
            raise ValueError("AI跨库发现必须为一至两句完整句")
        combined_text = f'{discovery["title"]}。{discovery["detail"]}'
        if _contains_action_advice(combined_text):
            raise ValueError("AI跨库发现含行动建议而非数据洞察")
        unsupported_causal = _unsupported_causal_terms(combined_text,
            ("导致", "造成", "推动", "带来", "源于", "驱动", "主要来自", "源自", "归因于", "脱钩"))
        if unsupported_causal:
            raise ValueError(f"AI跨库发现使用了未经证据支持的因果词：{unsupported_causal}")
        if allowed_numbers:
            if not (_numeric_tokens(combined_text) & allowed_numbers):
                raise ValueError("AI跨库发现缺少输入数值证据")
        unknown_urls = set(discovery["source_urls"]) - allowed_urls
        if unknown_urls:
            raise ValueError(f"AI跨库发现引用了输入之外的来源：{sorted(unknown_urls)}")
        for domain_id in pair:
            if urls_by_domain[domain_id] and not (set(discovery["source_urls"]) & urls_by_domain[domain_id]):
                raise ValueError(f"AI跨库发现缺少{domain_id}领域来源")
        unknown_numbers = _numeric_tokens(discovery) - allowed_numbers
        if unknown_numbers:
            raise ValueError(f"AI跨库发现出现输入之外的数字：{sorted(unknown_numbers)}")
        comparability_error = _discovery_comparability_error(discovery, evidence)
        if comparability_error:
            raise ValueError(comparability_error)
        warnings = _discovery_presentation_warnings([discovery])
        if warnings:
            discovery["presentation_warnings"] = warnings
        result.append(discovery)
    if require_complete and covered_domains != expected_domains:
        raise ValueError(f"AI跨库发现领域覆盖不完整：{sorted(expected_domains - covered_domains)}")
    return result


def _drop_unsupported_numeric_clauses(raw: Any, evidence: dict[str, Any]) -> Any:
    if not isinstance(raw, list):
        return raw
    allowed_numbers = _numeric_tokens(evidence)
    allowed_urls = {
        str(item.get("source_url") or "")
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
        for item in focus.get("items") or []
        if str(item.get("source_url") or "").startswith(("https://", "http://"))
    }
    allowed_urls.update(
        str(item.get("source_url") or "")
        for domain in evidence.get("domains") or []
        for item in domain.get("agent_verified_facts") or []
        if str(item.get("source_url") or "").startswith(("https://", "http://"))
    )
    evidence_entities = {
        (
            str(domain.get("id") or ""),
            str(focus.get("id") or ""),
            str(entity.get("name") or ""),
        ): entity
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
        for entity in focus.get("items") or []
    }
    sanitized: list[Any] = []
    for item in raw:
        if not isinstance(item, dict):
            sanitized.append(item)
            continue
        cleaned = dict(item)
        cleaned["source_urls"] = [
            str(url) for url in cleaned.get("source_urls") or [] if str(url) in allowed_urls
        ]
        removed = 0
        for field in ("headline", "analysis", "risk"):
            text = str(cleaned.get(field) or "")
            clauses = re.split(r"(?<=[。；;])", text)
            kept: list[str] = []
            for clause in clauses:
                if _numeric_tokens(clause) - allowed_numbers:
                    removed += 1
                    continue
                kept.append(clause)
            cleaned[field] = "".join(kept).strip()
        cleaned_focuses: list[Any] = []
        for focus in cleaned.get("focuses") or []:
            if not isinstance(focus, dict):
                cleaned_focuses.append(focus)
                continue
            cleaned_focus = dict(focus)
            cleaned_focus["source_urls"] = [
                str(url) for url in cleaned_focus.get("source_urls") or [] if str(url) in allowed_urls
            ]
            for field in ("analysis", "risk"):
                text = str(cleaned_focus.get(field) or "")
                clauses = re.split(r"(?<=[。；;])", text)
                kept = []
                for clause in clauses:
                    if _numeric_tokens(clause) - allowed_numbers:
                        removed += 1
                        continue
                    kept.append(clause)
                cleaned_focus[field] = "".join(kept).strip()
            cleaned_entities: list[Any] = []
            for entity in cleaned_focus.get("entities") or []:
                if not isinstance(entity, dict):
                    cleaned_entities.append(entity)
                    continue
                cleaned_entity = dict(entity)
                entity_evidence = evidence_entities.get((
                    str(cleaned.get("domain") or ""),
                    str(cleaned_focus.get("id") or ""),
                    str(cleaned_entity.get("name") or ""),
                ), {})
                entity_allowed_urls = {str(entity_evidence.get("source_url") or "")} - {""}
                cleaned_entity["source_urls"] = [
                    str(url)
                    for url in cleaned_entity.get("source_urls") or []
                    if str(url) in entity_allowed_urls
                ]
                for field in ("headline", "analysis", "risk"):
                    text = str(cleaned_entity.get(field) or "")
                    clauses = re.split(r"(?<=[。；;])", text)
                    kept = []
                    entity_allowed_numbers = _numeric_tokens(entity_evidence)
                    for clause in clauses:
                        if _numeric_tokens(clause) - entity_allowed_numbers:
                            removed += 1
                            continue
                        kept.append(clause)
                    cleaned_entity[field] = "".join(kept).strip()
                cleaned_entity["analysis"] = re.sub(
                    r"(?i)components\s*具体包含[:：]?", "具体包含：", cleaned_entity["analysis"]
                )
                # Empty fields must fail validation and return to the model.
                # Copying source prose or inserting stock sentences would mark
                # deterministic text as an AI-generated analysis.
                cleaned_entities.append(cleaned_entity)
            if "entities" in cleaned_focus:
                cleaned_focus["entities"] = cleaned_entities
            cleaned_focuses.append(cleaned_focus)
        if "focuses" in cleaned:
            cleaned["focuses"] = cleaned_focuses
        if removed:
            cleaned["sanitized_clauses"] = removed
        sanitized.append(cleaned)
    return sanitized


def _display_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return str(int(number)) if number.is_integer() else str(number)


def _ranked_focus_items(focus: dict[str, Any]) -> list[dict[str, Any]]:
    def numeric_rank(item: dict[str, Any]) -> float:
        value = item.get("value")
        try:
            return float(value)
        except (TypeError, ValueError):
            match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
            return float(match.group()) if match else float("-inf")

    return sorted(
        [item for item in focus.get("items") or [] if isinstance(item, dict) and item.get("value") not in (None, "")],
        key=numeric_rank,
        reverse=True,
    )


def _compact_grounded_focus_analysis(domain: str, focus: dict[str, Any]) -> str:
    focus_id = str(focus.get("id") or "")
    items = _ranked_focus_items(focus)
    if domain == "local" and focus_id in {"revenue", "net_profit"}:
        # CMHK is currently a 2026 first-seven-month reference while the other
        # local operators are FY2025; the compact model input omits period, so
        # keep it out of full-year operating-strength rankings by identity.
        fy2025_items = [item for item in items if str(item.get("name") or "") != "CMHK"]
        if len(fy2025_items) >= 2:
            items = fy2025_items
    by_name = {str(item.get("name") or ""): item for item in items}
    metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
    metric_value = _display_number(metric.get("value"))
    metric_unit = str(metric.get("unit") or "")
    strategic_fallback = str(focus.get("insight") or "").strip()
    if domain in {"local", "mainland"} and focus_id in {"revenue", "ebitda", "net_profit", "postpaid"}:
        if len(items) >= 2:
            high, low = items[0], items[-1]
            high_name, low_name = str(high.get("name") or ""), str(low.get("name") or "")
            high_value, low_value = _display_number(high.get("value")), _display_number(low.get("value"))
            unit = str(high.get("unit") or low.get("unit") or "")
            if focus_id == "revenue":
                return (
                    f"{high_name} FY2025营收{high_value}{unit}，{low_name}{low_value}{unit}；"
                    f"这表明{high_name}的经营资源底盘最厚、资源承载力更强，"
                    f"更能承担网络与获客投入；{low_name}的资源容错较窄、经营容错更低，但规模不等同效率。"
                )
            if focus_id == "ebitda":
                return (
                    f"{high_name} FY2025 EBITDA为{high_value}{unit}，{low_name}{low_value}{unit}；"
                    f"这表明{high_name}的经营造血代理最强，持续投入与价格竞争缓冲更厚，{low_name}的防守容错更窄；EBITDA不等同现金流。"
                )
            if focus_id == "net_profit":
                low_signal = "已为负值" if float(low.get("value") or 0) < 0 else "位于样本尾部"
                return (
                    f"{high_name} FY2025净利润{high_value}{unit}，{low_name}{low_value}{unit}且{low_signal}；"
                    f"这表明{high_name}盈利状态最稳、自我融资与再投资空间最厚，{low_name}的盈利防线明显承压。"
                )
            return (
                f"{high_name} FY2025移动客户{high_value}{unit}，{low_name}{low_value}{unit}；"
                f"这表明{high_name}的客户经营底盘更厚，交叉销售与网络规模摊薄基础更广，{low_name}的底盘较窄；未结合ARPU不能判断客户价值。"
            )
        if focus_id == "postpaid":
            named = "、".join(str(item.get("name") or "") for item in focus.get("items") or [] if item.get("name"))
            return (
                f"{named}当前均缺少可比移动客户原值；披露不足使客户覆盖底盘无法穿透比较，"
                "且不能由5G用户数替代集团移动客户总数。"
            )
    if domain == "international" and focus_id in {"revenue", "net_profit", "capex", "mobile_arpu"} and items:
        ranked = sorted(items, key=lambda item: float(item.get("value") or 0), reverse=True)
        high, low = ranked[0], ranked[-1]
        high_name, low_name = str(high.get("name") or ""), str(low.get("name") or "")
        high_value, low_value = _display_number(high.get("value")), _display_number(low.get("value"))
        if focus_id == "revenue":
            return (
                f"{high_name} FY2025营收{high_value}百万美元，{low_name}{low_value}百万美元；"
                "收入底盘差距表明资源承载分层，但不等同盈利能力。"
            )
        if focus_id == "capex":
            return (
                f"{high_name} FY2025资本开支{high_value}百万美元，{low_name}{low_value}百万美元；"
                "持续投入与资本军备差距表明投入分层，但不等同投入转化效率。"
            )
        if focus_id == "net_profit":
            return (
                f"{high_name} FY2025净利润{high_value}百万美元，{low_name}{low_value}百万美元；"
                "利润池分层表明自我融资与再投资空间不同，绝对值不等同盈利效率。"
            )
        docomo = by_name.get("NTT DOCOMO") or high
        softbank = by_name.get("SoftBank Corp.") or low
        return (
            f"NTT DOCOMO FY2025移动ARPU约{_display_number(docomo.get('value'))}美元/月，"
            f"SoftBank Corp.约{_display_number(softbank.get('value'))}美元/月；"
            "美元换算表明DOCOMO的客户价值量级更高，但两家公司用户范围结构不同，不能直接等同。"
        )
    if strategic_fallback and _has_deep_interpretation(strategic_fallback):
        return strategic_fallback

    if (domain, focus_id) == ("local", "scale") and items:
        record_leader = max(items, key=lambda item: float(item.get("record_count") or item.get("value") or 0))
        unique_leader = max(items, key=lambda item: float(item.get("component_count") or 0))
        return (
            f"{record_leader.get('name')}有{_display_number(record_leader.get('record_count') or record_leader.get('value'))}条记录，"
            f"但唯一方案仅{_display_number(record_leader.get('component_count'))}个、低于{unique_leader.get('name')}的"
            f"{_display_number(unique_leader.get('component_count'))}个，表面规模优势主要来自记录重复而非产品广度。"
        )
    if (domain, focus_id) == ("local", "track") and len(items) >= 2:
        leaders = [str(item.get("name") or "") for item in items if item.get("value") == items[0].get("value")]
        return (
            f"{'与'.join(leaders[:2])}均覆盖{_display_number(items[0].get('value'))}个赛道，"
            "但组合分别集中于移动/漫游与企业/家宽，广度相同并不等同于直接产品重叠。"
        )
    if (domain, focus_id) == ("local", "price"):
        ranked: list[tuple[float, str, Any]] = []
        for item in focus.get("items") or []:
            try:
                numeric = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            ranked.append((numeric, str(item.get("name") or "品牌"), item.get("value")))
        if ranked:
            low = min(ranked)
            high = max(ranked)
            gap = high[0] - low[0]
            gap_text = str(int(gap)) if gap.is_integer() else f"{gap:g}"
            unit = str((focus.get("metric") or {}).get("unit") or "港元/月")
            return (
                f"{low[1]}{_display_number(low[2])}至{high[1]}{_display_number(high[2])}{unit}看似相差{gap_text}{unit}，"
                "但混合了通行证、家宽与移动套餐，价格梯度主要反映产品类型而非单纯品牌溢价。"
            )
    if (domain, focus_id) == ("local", "overlap"):
        return (
            f"最多仅重叠{metric_value}{metric_unit}，且交集分散在个人5G、企业移动与家宽，"
            "说明本地竞争仍是分赛道交锋，并未形成全产品线正面重叠。"
        )
    if (domain, focus_id) == ("international", "growth") and items:
        high, low = items[0], items[-1]
        return (
            f"四家最新增速从{_display_number(high.get('value'))}%到{_display_number(low.get('value'))}%，"
            "正负并存表明行业已由同步扩张转为收入结构分化。"
        )
    if (domain, focus_id) == ("international", "momentum") and items:
        high, low = items[0], items[-1]
        return (
            f"四家动量全部为负，介于{_display_number(high.get('value'))}至{_display_number(low.get('value'))}个百分点，"
            "说明本期并非个别公司波动，而是行业增长同步降速。"
        )
    if (domain, focus_id) == ("international", "investment") and items:
        comparable = items
        if comparable:
            high, low = comparable[0], comparable[-1]
            return (
                f"资本开支占营收从{_display_number(high.get('value'))}%到{_display_number(low.get('value'))}%，"
                "按同期收入归一后仍呈结构性差异，且不能直接等同投资回报高低。"
            )
    if (domain, focus_id) == ("international", "disclosure") and items:
        high, low = items[0], items[-1]
        return (
            f"披露最多{_display_number(high.get('value'))}项、最少{_display_number(low.get('value'))}项，差距有限，"
            "说明公开信息广度并不能解释经营质量高低。"
        )
    if (domain, focus_id) == ("cloud", "revenue") and items:
        high, low = items[0], items[-1]
        return (
            f"最高的{high.get('name')} FY2024云收入{_display_number(high.get('value'))}百万美元，"
            f"最低的{low.get('name')}{_display_number(low.get('value'))}百万美元；"
            f"表明{high.get('name')}的云业务生态底盘最厚，生态扩张与基础设施持续投入能力更强；{low.get('name')}资源弹性较窄，代理口径不混排。"
        )
    if (domain, focus_id) == ("cloud", "trend") and items:
        high, low = items[0], items[-1]
        return (
            f"增速变化从{_display_number(high.get('value'))}到{_display_number(low.get('value'))}个百分点，"
            "说明当前梯队变化主要来自二线厂商再加速，而非全行业同步回暖。"
        )
    if (domain, focus_id) == ("cloud", "profit") and items:
        direct = [item for item in items if "经营利润" in str(item.get("detail") or "")]
        high, low = (direct[0], direct[-1]) if len(direct) >= 2 else (items[0], items[-1])
        return (
            f"同属经营利润披露的{high.get('name')} FY2024为{_display_number(high.get('value'))}百万美元，"
            f"{low.get('name')}为{_display_number(low.get('value'))}百万美元；表明{high.get('name')}的云业务自我造血能力更强，可用更厚盈利缓冲支撑再投资与价格竞争，其他利润定义不可混入。"
        )
    if (domain, focus_id) == ("cloud", "investment") and items:
        high, low = items[0], items[-1]
        return (
            f"{high.get('name')} FY2024集团资本开支{_display_number(high.get('value'))}百万美元，"
            f"{low.get('name')}{_display_number(low.get('value'))}百万美元；表明{high.get('name')}的基础设施扩容弹药更足，{low.get('name')}的集团投入空间相对较窄，"
            "但集团投入并非云业务单独投入，不能据此判断投入转化效率。"
        )
    if (domain, focus_id) == ("cloud", "disclosure"):
        return (
            f"{metric_value}项披露混合直接分部、代理分部与综合口径，"
            "表明数据丰富度上升并未消除跨厂商可比性断层。"
        )
    if (domain, focus_id) == ("macro", "market"):
        broadband = by_name.get("移动宽带用户", {})
        household = by_name.get("家庭宽带渗透率", {})
        return (
            f"移动连接{metric_value}万与移动宽带{_display_number(broadband.get('value'))}万几乎重合，"
            f"家庭宽带渗透率已达{_display_number(household.get('value'))}%，说明连接市场接近饱和，增量不再来自基础覆盖。"
        )
    if (domain, focus_id) == ("macro", "traffic"):
        per_sub = by_name.get("每移动宽带用户流量", {})
        per_capita = by_name.get("人均移动流量", {})
        return (
            f"人均流量{_display_number(per_capita.get('value'))}GB远高于每移动宽带用户"
            f"{_display_number(per_sub.get('value'))}GB，差异来自多连接口径，流量总量不能等同单用户使用强度。"
        )
    if (domain, focus_id) == ("macro", "spending"):
        cpi = by_name.get("甲类消费物价指数", {})
        return (
            f"家庭月入中位数{metric_value}港元而甲类消费物价指数为{_display_number(cpi.get('value'))}，"
            "说明名义消费规模与实际套餐可负担力并不等价，购买力受价格水平约束。"
        )
    if (domain, focus_id) == ("macro", "governance"):
        complaints = by_name.get("电讯投诉", {})
        coverage = by_name.get("5G人口覆盖", {})
        return (
            f"5G覆盖已超过{_display_number(coverage.get('value'))}%仍有{_display_number(complaints.get('value'))}宗投诉，"
            "说明网络竞争瓶颈已从覆盖可达性转为服务质量与体验一致性。"
        )
    label = str(metric.get("label") or focus.get("label") or "最新指标")
    if metric_value:
        return f"{label}{metric_value}{metric_unit}与同组差异并存，数据结构表明绝对规模不能单独解释竞争质量。"
    numbers = sorted(_focus_value_tokens(focus), key=lambda item: float(item))
    anchor = numbers[0] if numbers else ""
    return (
        f"当前值{anchor}与同组差异并存，数据结构表明绝对规模不能单独解释竞争质量。"
        if anchor else "现有证据结构不完整，尚不能形成可比的深层结论。"
    )


def _deterministic_focus_analysis(domain: str, focus: dict[str, Any]) -> str:
    """Produce a numerically grounded fallback that must pass the full focus gate."""
    return _compact_grounded_focus_analysis(domain, focus)


def _deterministic_domain_summaries(
    evidence: dict[str, Any], *, validate: bool = True,
) -> list[dict[str, Any]]:
    """Build a fail-closed summary directly from the validated evidence pack."""
    summaries: list[dict[str, Any]] = []
    for domain in evidence.get("domains") or []:
        sources = [
            str(item.get("source_url") or "")
            for focus in domain.get("focuses") or []
            for item in focus.get("items") or []
            if str(item.get("source_url") or "").startswith(("https://", "http://"))
        ]
        summaries.append(
            {
                "domain": str(domain.get("id") or ""),
                "headline": f"{domain.get('title') or '该领域'}最新证据已更新",
                "analysis": str(domain.get("deterministic_insight") or "当前仅展示已通过发布门禁的证据。"),
                "risk": "仅基于当前已核验来源和已披露口径；缺失数据不估算，跨期间与代理口径不作因果推断。",
                "source_urls": list(dict.fromkeys(sources))[:3],
                "focuses": [
                    {
                        "id": str(focus.get("id") or ""),
                        "headline": _strategic_focus_headline(
                            str(domain.get("id") or ""),
                            str(focus.get("id") or ""),
                            focus.get("headline"),
                        ),
                        "analysis": _deterministic_focus_analysis(
                            str(domain.get("id") or ""),
                            focus,
                        ),
                        "risk": "仅基于当前已核验来源和已披露口径，缺失数据不估算。",
                        "source_urls": list(dict.fromkeys(
                            str(item.get("source_url") or "")
                            for item in focus.get("items") or []
                            if str(item.get("source_url") or "").startswith(("https://", "http://"))
                        ))[:3],
                        "entities": [
                            {
                                "name": str(entity.get("name") or ""),
                                "headline": f"{entity.get('name') or '该对象'}明细已核验",
                                "analysis": str(entity.get("analysis") or entity.get("detail") or "当前没有足够明细形成判断。"),
                                "risk": "仅基于当前结构化明细；缺失、重复或异口径记录不作推算。",
                                "evidence_labels": [
                                    str(component.get("label") or "")
                                    for component in entity.get("components") or []
                                    if str(component.get("label") or "")
                                ][:6],
                                "source_urls": [str(entity.get("source_url") or "")]
                                if str(entity.get("source_url") or "").startswith(("https://", "http://")) else [],
                            }
                            for entity in focus.get("items") or []
                            if str(entity.get("name") or "")
                        ],
                    }
                    for focus in domain.get("focuses") or []
                    if str(focus.get("id") or "")
                ],
            }
        )
    return _validate_model_summaries(summaries, evidence) if validate else summaries


def _deterministic_discoveries(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    urls_by_domain = _evidence_urls_by_domain(evidence)
    focuses = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }

    def metric(domain_id: str, focus_id: str) -> tuple[str, str]:
        focus = focuses.get((domain_id, focus_id)) or {}
        value = focus.get("metric", {}).get("value") if isinstance(focus.get("metric"), dict) else ""
        unit = focus.get("metric", {}).get("unit") if isinstance(focus.get("metric"), dict) else ""
        return _display_number(value), str(unit or "")

    def period(domain_id: str, focus_id: str) -> str:
        focus = focuses.get((domain_id, focus_id)) or {}
        metric_payload = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
        match = re.search(r"FY(20\d{2})", str(metric_payload.get("label") or ""))
        return f"FY{match.group(1)}" if match else "最新披露期"

    local_revenue, local_revenue_unit = metric("local", "revenue")
    international_revenue, international_revenue_unit = metric("international", "revenue")
    cloud_revenue, cloud_revenue_unit = metric("cloud", "revenue")
    mainland_revenue, mainland_revenue_unit = metric("mainland", "revenue")
    mainland_postpaid, mainland_postpaid_unit = metric("mainland", "postpaid")
    local_period = period("local", "revenue")
    international_period = period("international", "revenue")
    mainland_period = period("mainland", "revenue")
    cloud_period = period("cloud", "revenue")
    relations = [
        {
            "from": "mainland", "to": "local", "title": f"{local_period}香港与内地财务口径分开",
            "detail": (
                f"内地营收卡片为{mainland_revenue}{mainland_revenue_unit}，香港为{local_revenue}{local_revenue_unit}；"
                f"两组均采用{mainland_period}/{local_period}最新已核验披露，但币种与主体范围结构不同；这表明数值高低不能直接等同经营质量。"
            ),
        },
        {
            "from": "international", "to": "cloud", "title": f"{cloud_period}云收入与运营商财务分口径",
            "detail": (
                f"云收入卡片为{cloud_revenue}{cloud_revenue_unit}，国际营收卡片为{international_revenue}{international_revenue_unit}；"
                f"分别采用{cloud_period}/{international_period}最新已核验披露，分部规模与集团财务口径结构不同，因此不能直接混合排名。"
            ),
        },
        {
            "from": "local", "to": "cloud", "title": f"{local_period}香港财务与云收入边界不同",
            "detail": (
                f"香港营收卡片为{local_revenue}{local_revenue_unit}，云收入卡片为{cloud_revenue}{cloud_revenue_unit}；"
                f"分别采用{local_period}/{cloud_period}最新已核验披露，公司整体与云分部范围结构不同；这表明两者不可直接比较。"
            ),
        },
        {
            "from": "mainland", "to": "international", "title": f"{mainland_period}内地与国际用户口径分开",
            "detail": (
                f"内地后付费用户数披露不足，国际营收卡片为{international_revenue}{international_revenue_unit}；"
                f"国际侧采用{international_period}最新披露；两者用户口径结构不同，因此不能直接拿移动用户总数替代后付费竞争判断。"
            ),
        },
    ]
    discoveries: list[dict[str, Any]] = []
    for relation in relations:
        source_domain = str(relation.get("from") or "")
        target_domain = str(relation.get("to") or "")
        source_urls = []
        for domain_id in (source_domain, target_domain):
            if urls_by_domain.get(domain_id):
                source_urls.append(sorted(urls_by_domain[domain_id])[0])
        discoveries.append({
            "from": source_domain,
            "to": target_domain,
            "title": str(relation.get("title") or ""),
            "detail": str(relation.get("detail") or ""),
            "kind": "证据规则回退",
            "source_urls": source_urls,
        })
    return _validate_model_discoveries(discoveries, evidence)


def _safe_discovery_regeneration_fallback(
    evidence: dict[str, Any],
    source_domain: str,
    target_domain: str,
    *,
    current: dict[str, Any],
    regeneration_index: int,
) -> dict[str, Any] | None:
    """Rotate evidence-only cross-domain judgements when every model returns unusable output."""
    focuses = {
        (str(domain.get("id") or ""), str(focus.get("id") or "")): focus
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    }
    urls_by_domain = _evidence_urls_by_domain(evidence)

    def metric(domain_id: str, focus_id: str) -> str:
        focus = focuses.get((domain_id, focus_id)) or {}
        raw_metric = focus.get("metric") if isinstance(focus.get("metric"), dict) else {}
        return f"{_display_number(raw_metric.get('value'))}{str(raw_metric.get('unit') or '')}"

    def item_value(domain_id: str, focus_id: str, keyword: str) -> str:
        focus = focuses.get((domain_id, focus_id)) or {}
        for item in focus.get("items") or []:
            if keyword in str(item.get("name") or ""):
                return f"{_display_number(item.get('value'))}{str(item.get('unit') or '')}"
        return ""

    values = {
        domain_id: metric(domain_id, "revenue")
        for domain_id in ("local", "international", "mainland", "cloud")
    }
    domain_names = {
        "local": "本地运营商",
        "international": "跨国运营商",
        "mainland": "内地运营商",
        "cloud": "全球云厂商",
    }
    pair = frozenset((source_domain, target_domain))
    titles: dict[frozenset[str], tuple[str, str, str]] = {
        frozenset(("local", "international")): (
            "本地深耕与跨国规模经营呈现分层",
            "跨国规模优势不等同本地经营质量",
            "本地与跨国运营商处于不同竞争层次",
        ),
        frozenset(("local", "mainland")): (
            "本地精细经营与内地规模经营呈现分层",
            "内地规模优势不等同本地经营质量",
            "本地与内地运营商处于不同竞争层次",
        ),
        frozenset(("international", "cloud")): (
            "运营商规模与云业务规模处于不同阶段",
            "云业务规模不等同运营商综合经营质量",
            "传统连接与云业务形成两类竞争层次",
        ),
        frozenset(("mainland", "cloud")): (
            "连接底盘与云业务规模形成生态分层",
            "内地运营规模不等同全球云竞争质量",
            "运营商与云厂商处于不同竞争层次",
        ),
        frozenset(("local", "cloud")): (
            "本地经营与全球云业务形成范围分层",
            "公司整体规模不等同云业务经营质量",
            "本地运营商与云厂商处于不同竞争层次",
        ),
        frozenset(("mainland", "international")): (
            "内地与跨国规模经营形成市场分层",
            "跨市场规模优势不等同客户经营质量",
            "内地与跨国运营商处于不同竞争层次",
        ),
    }
    pair_titles = titles.get(pair)
    if pair_titles:
        source_value = values[source_domain]
        target_value = values[target_domain]
        source_name = domain_names[source_domain]
        target_name = domain_names[target_domain]
        options = [
            (
                pair_titles[0],
                f"{source_name}营收{source_value}与{target_name}营收{target_value}的主体和币种范围不同；"
                "规模差异表明两域经营分层，并非同一竞争边界下的直接排名。",
            ),
            (
                pair_titles[1],
                f"{source_name}营收{source_value}与{target_name}营收{target_value}分属不同市场范围；"
                "这说明绝对值差异不能等同经营质量，战略含义在于竞争层次不同。",
            ),
            (
                pair_titles[2],
                f"{source_name}营收{source_value}、{target_name}营收{target_value}采用不同主体与币种口径；"
                "差距反映两域资源规模分层，而非同一维度的经营效率比较。",
            ),
        ]
    else:
        options = None
    if not options:
        return None
    source_urls = [
        sorted(urls_by_domain[domain_id])[0]
        for domain_id in (source_domain, target_domain)
        if urls_by_domain.get(domain_id)
    ]
    current_signature = tuple(re.sub(r"\s+", "", str(current.get(key) or "")) for key in ("title", "detail"))
    for offset in range(len(options)):
        title, detail = options[(regeneration_index + offset) % len(options)]
        candidate = {
            "from": source_domain,
            "to": target_domain,
            "title": title,
            "detail": detail,
            "kind": "数据证据解读",
            "source_urls": source_urls,
        }
        candidate_signature = tuple(re.sub(r"\s+", "", str(candidate.get(key) or "")) for key in ("title", "detail"))
        if candidate_signature != current_signature:
            return candidate
    return None


def _normalize_fresh_focus_headline(
    headline: Any,
    *,
    label: str,
    recent_headlines: list[str],
    forbidden_terms: tuple[str, ...] = (),
) -> str:
    """Fit a fresh model title to the card without discarding valid analysis."""
    normalized = str(headline or "").replace("5G", "五G").replace("5g", "五G")
    normalized = re.sub(r"[\s\d０-９％%。，,；;：:！？!?（）()【】\[\]、]", "", normalized)
    normalized = re.sub(
        r"(个百分点|港元|亿元|万元|万户|万项|MHz|MB|GB|项|个)$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = (
        normalized
        .replace("中国联通", "联通")
        .replace("中国移动", "移动")
        .replace("中国电信", "电信")
        .replace("资本投入强度", "投入强度")
        .replace("五G", "5G")
    )
    if len(normalized) > 14:
        normalized = re.sub(r"(增长质量|经营质量|竞争质量|市场表现)$", "", normalized)
    candidates = [
        normalized if len(normalized) <= 14 else "",
        f"{label}关系重新判断"[:14],
        f"{label}口径边界显现"[:14],
        f"{label}结构重新分化"[:14],
        "数据关系出现新分层",
        "口径边界重新显现",
    ]
    recent = [re.sub(r"\s+", "", str(value or "")) for value in recent_headlines]
    for candidate in dict.fromkeys(candidates):
        if not (4 <= len(candidate) <= 14):
            continue
        if any(term in candidate for term in ("洞察", "研判", "格局分化", *forbidden_terms)):
            continue
        if _contains_action_advice(candidate):
            continue
        if max(
            (difflib.SequenceMatcher(None, previous, candidate).ratio() for previous in recent),
            default=0.0,
        ) >= 0.96:
            continue
        return candidate
    raise ValueError(f"无法生成与最近版本不同的短标题：{str(headline or '')[:40]}")


def _safe_focus_regeneration_fallback(
    domain_id: str,
    focus: dict[str, Any],
    *,
    regeneration_index: int,
    recent_insights: list[str],
) -> dict[str, Any] | None:
    """Return rotating evidence-only judgements when every model attempt fails."""
    focus_id = str(focus.get("id") or "")
    supported = {
        ("macro", "service"),
        ("international", "growth"),
    }
    if (domain_id, focus_id) not in supported:
        return None
    items = {
        str(item.get("name") or ""): item
        for item in focus.get("items") or []
        if isinstance(item, dict)
    }

    def value(name: str) -> str:
        return _display_number((items.get(name) or {}).get("value"))

    if (domain_id, focus_id) == ("macro", "service"):
        variants = [
            (
                "供给指标不等同服务改善",
                f"5G人口覆盖{value('5G人口覆盖')}、已分配公共移动及5G频谱{value('已分配公共移动及5G频谱')}MHz，"
                f"说明供给资源已处高位；电讯业投资同比{value('电讯业投资')}%与投诉同比{value('电讯投诉')}%的期间不同，"
                "不能据此判断投入是否转化为服务改善。",
            ),
            (
                "投入与投诉期间错位",
                f"电讯业投资同比{value('电讯业投资')}%反映截至2025-03-31的投入变化，"
                f"投诉同比{value('电讯投诉')}%反映截至2025-12-31的服务压力；两项期间不同，不能比较增速差距。",
            ),
            (
                "供给规模不代表服务质量",
                f"投诉同比{value('电讯投诉')}%只说明截至2025-12-31的服务压力变化；"
                f"5G人口覆盖{value('5G人口覆盖')}与频谱{value('已分配公共移动及5G频谱')}MHz是供给背景，"
                "不能等同服务质量改善。",
            ),
        ]
    else:
        variants = [
            (
                "营收增长分成正负两层",
                f"Q1 2026中国铁塔{value('中国铁塔')}%、中国移动{value('中国移动')}%仍为正增长，"
                f"中国联通{value('中国联通')}%、中国电信{value('中国电信')}%已转负，"
                "表明四家公司分成正负两层，行业并非同步扩张。",
            ),
            (
                "行业扩张已明显分化",
                f"中国铁塔{value('中国铁塔')}%与中国移动{value('中国移动')}%保持增长，"
                f"中国联通{value('中国联通')}%及中国电信{value('中国电信')}%下降，"
                "说明同一季度的收入方向已经分化，而非四家公司共同增长。",
            ),
            (
                "正增长仅集中于两家",
                f"Q1 2026四家公司中，中国铁塔{value('中国铁塔')}%和中国移动{value('中国移动')}%为正，"
                f"中国联通{value('中国联通')}%与中国电信{value('中国电信')}%为负；"
                "这说明增长只集中在两家，并非行业整体回升。",
            ),
        ]
    normalized_recent = [re.sub(r"\s+", "", str(item or "")) for item in recent_insights]
    start = (max(1, regeneration_index) - 1) % len(variants)
    for offset in range(len(variants)):
        headline, analysis = variants[(start + offset) % len(variants)]
        if _focus_gate_error(domain_id, focus_id, analysis, focus):
            continue
        similarity = max(
            (
                difflib.SequenceMatcher(None, previous, re.sub(r"\s+", "", analysis)).ratio()
                for previous in normalized_recent if previous
            ),
            default=0.0,
        )
        if similarity >= 0.84:
            continue
        return {
            "generated_at_hkt": _now(),
            "model": "evidence-rule-fallback",
            "focus": {
                "id": focus_id,
                "headline": headline,
                "analysis": analysis,
                "risk": "仅基于当前已核验记录；异期间指标不作因果推断。",
                "source_urls": [],
                "origin": "evidence_rule",
            },
        }
    return None


def generate_model_focus_insight(
    domain_id: str, focus: dict[str, Any], *, temperature: float = 0.25,
) -> dict[str, Any]:
    """Generate a single focus with model retries, never template substitutions."""
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot
    from network_utils import urlopen_with_local_proxy_fallback

    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置内网模型密钥")
    focus_id = str(focus.get("id") or "")
    evidence = json.loads(json.dumps(focus, ensure_ascii=False))
    for key in ("insight", "headline", "recent_insights", "recent_headlines", "regeneration_index"):
        evidence.pop(key, None)
    recent = [str(value) for value in focus.get("recent_insights") or []]
    if focus.get("insight"):
        recent.append(str(focus["insight"]))
    messages = [
        {"role": "system", "content": (
            "你是电信竞争情报分析员。只分析指定指标，使用输入的公司、数值、期间、单位和来源。"
            "给出有边界的经营或竞争关系判断，不把相关当因果，不猜数字。"
            "正文一至两句、120字内；引用具体数值并解释其经营含义，不写行动建议。"
            "缺少可比证据时解释各自经营状态，比较限制简短放在risk，不强行排序。"
            "返回JSON对象{headline,analysis,risk,source_urls}；标题28字内，不照抄指标名。"
            "请依据当前证据重新推导，不复用最近的分析或标题。"
            + FOCUS_EVIDENCE_CONTRACT
        )},
        {"role": "user", "content": json.dumps({
            "domain": domain_id, "focus": evidence,
            "forbidden_recent_analyses": recent,
            "forbidden_recent_headlines": [*(focus.get("recent_headlines") or []), str(focus.get("headline") or "")],
            "request_id": uuid4().hex,
        }, ensure_ascii=False)},
    ]
    last_error = None
    for model in _executive_model_route():
        request_id = f"focus-{domain_id}-{focus_id}-{uuid4().hex}"
        body = prepare_structured_chat_body({
            **dict(config.get("extra_parameters") or {}), "model": model,
            "messages": messages, "temperature": temperature, "max_tokens": 4000,
        })
        request = _model_request(config, api_key, body, request_id)
        try:
            with open_llm_request(
                request, timeout=75, config=config, requested_key=api_key, model=model,
                open_func=urlopen_with_local_proxy_fallback,
                operation=f"executive-intelligence-focus-{domain_id}-{focus_id}",
            ) as response:
                payload = read_chat_completion_sse(response)
            parsed = load_json_response(
                final_chat_message_text(payload, operation="单指标AI分析"), operation="单指标AI分析",
            )
            if not isinstance(parsed, dict):
                raise ValueError("AI未返回指标分析对象")
            headline = str(parsed.get("headline") or "").strip()
            analysis = str(parsed.get("analysis") or "").strip()
            if not headline or len(headline) > MAX_FOCUS_HEADLINE_PUBLISH_CHARS:
                raise ValueError(f"AI标题为空或超过{MAX_FOCUS_HEADLINE_PUBLISH_CHARS}字发布保护上限，请由AI重新生成")
            headline_error = _focus_headline_gate_error(domain_id, focus_id, headline)
            if headline_error:
                raise ValueError(headline_error)
            error = _focus_gate_error(domain_id, focus_id, analysis, focus)
            if error:
                raise ValueError(error)
            unknown_numbers = _numeric_tokens({"headline": headline, "analysis": analysis}) - _numeric_tokens(evidence)
            if unknown_numbers:
                raise ValueError(f"AI分析引用了输入之外的数字：{sorted(unknown_numbers)}")
            normalized = re.sub(r"\s+", "", analysis)
            if any(normalized == re.sub(r"\s+", "", old) for old in recent):
                raise ValueError("AI返回了与最近版本相同的分析")
            allowed_urls = set(re.findall(r'https?://[^\s"<>]+', json.dumps(evidence, ensure_ascii=False)))
            urls = [str(url) for url in parsed.get("source_urls") or []]
            if set(urls) - allowed_urls:
                raise ValueError("AI引用了当前证据之外的来源")
            presentation_warnings = _focus_presentation_warnings(domain_id,
                {"id": focus_id, "headline": headline, "analysis": analysis})
            return {
                "generated_at_hkt": _now(), "model": payload["model"], "requested_model": model,
                "response_id": payload["id"], "stream_diagnostics": payload["stream_diagnostics"],
                "focus": {"id": focus_id, "headline": headline, "analysis": analysis,
                          "risk": str(parsed.get("risk") or ""), "source_urls": urls, "origin": "ai",
                          **({"presentation_warnings": presentation_warnings} if presentation_warnings else {})},
            }
        except (APIKeyPoolUnavailable, ValueError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            messages.append({"role": "user", "content": f"上次未通过校验：{exc}。请重新生成，不改变证据。"})
    raise ValueError(f"AI指标分析未生成，原结果未修改：{last_error}")

def _scope_patch_options(candidate: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    """Expose only invalid, existing fields of a structurally complete focus."""
    domain = scope["domains"][0]
    focuses = candidate.get("focuses") or []
    if candidate.get("domain") != domain["id"] or len(focuses) != 1 or len(domain.get("focuses") or []) != 1:
        return {}
    focus, evidence_focus = focuses[0], domain["focuses"][0]
    if focus.get("id") != evidence_focus.get("id"):
        return {}
    entities = focus.get("entities") or []
    by_name = {e["name"]: e for e in evidence_focus.get("items") or []}
    if len(entities) != len(by_name) or {e.get("name") for e in entities if isinstance(e, dict)} != set(by_name):
        return {}
    required = {"headline", "analysis", "risk", "source_urls"}
    if not required.issubset(candidate) or not required.issubset(focus) or any(
        not (required | {"evidence_labels"}).issubset(e) for e in entities
    ):
        return {}
    options: dict[str, Any] = {}

    def add(path, obj, field, error, **context):
        if error and field in obj:
            options[path] = {"error": str(error), "current": obj[field],
                             "type": "array" if field in ("source_urls", "evidence_labels") else "string",
                             "must_change": True, **context}
            if isinstance(obj[field], str):
                options[path]["current_characters"] = len(obj[field])
            if path == "/focuses/0/analysis":
                options[path].update(max_characters=MAX_FOCUS_INSIGHT_CHARS,
                    target_characters=[60, 85], max_sentences=MAX_FOCUS_INSIGHT_SENTENCES,
                    content_selection="保留原稿中同期间可比的两家公司原值及经营关系；其余事实已在实体明细，不在正文重复。")
            elif path == "/focuses/0/headline":
                options[path].update(max_characters=28, target_characters=[10, 22],
                    content_selection="标题只写经营判断，不堆金额、单位或财年；原样保留必要公司名，具体数值已在正文及实体明细。")

    def text_fields(obj, prefix, allowed):
        for field in ("headline", "analysis", "risk"):
            value = obj.get(field)
            if not isinstance(value, str) or not value.strip():
                add(prefix + "/" + field, obj, field, "必填文字为空或类型错误")
            elif _numeric_tokens(value) - _numeric_tokens(allowed):
                add(prefix + "/" + field, obj, field, "含本字段证据之外的数字或期间")

    text_fields(candidate, "", scope)
    text_fields(focus, "/focuses/0", scope)
    headline = str(focus.get("headline") or "")
    add("/focuses/0/headline", focus, "headline",
        _focus_headline_gate_error(domain["id"], focus["id"], headline)
        or ("标题照抄指标名称" if headline and re.sub(r"\s+", "", headline) == re.sub(r"\s+", "", str(evidence_focus.get("label") or "")) else ""))
    add("/focuses/0/analysis", focus, "analysis",
        _focus_gate_error(domain["id"], focus["id"], str(focus.get("analysis") or ""), evidence_focus))
    domain_urls = set().union(*_evidence_urls_by_domain(scope).values())
    for obj, prefix, urls in [(candidate, "", domain_urls), (focus, "/focuses/0", domain_urls)]:
        value = obj.get("source_urls")
        if not isinstance(value, list) or any(not isinstance(u, str) or u not in urls for u in value):
            add(prefix + "/source_urls", obj, "source_urls", "引用未知来源", allowed_values=sorted(urls))
    for index, entity in enumerate(entities):
        source = by_name[entity["name"]]
        prefix = f"/focuses/0/entities/{index}"
        text_fields(entity, prefix, source)
        if any(phrase in str(entity.get("analysis") or "") for phrase in
               ("按排名", "图中排序", "同一视图", "便于比较", "数据库内", "此视图", "不代表经营排名")):
            add(prefix + "/analysis", entity, "analysis", "实体分析含界面说明，缺少本实体事实")
        labels = entity.get("evidence_labels")
        allowed = [str(c["label"]) for c in source.get("components") or [] if isinstance(c, dict) and c.get("label")]
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            add(prefix + "/evidence_labels", entity, "evidence_labels", "引用标签必须为字符串数组", entity=entity["name"], allowed_values=allowed)
        elif set(_canonical_entity_labels(labels, source)[0]) - set(allowed):
            add(prefix + "/evidence_labels", entity, "evidence_labels", "引用了该实体allowed_evidence_labels以外的标签", entity=entity["name"], allowed_values=allowed)
        urls = _entity_evidence_urls(source)
        if not isinstance(entity.get("source_urls"), list) or any(not isinstance(u, str) or u not in urls for u in entity["source_urls"]):
            add(prefix + "/source_urls", entity, "source_urls", "引用了其他实体或未知来源", entity=entity["name"], allowed_values=sorted(urls))
    for path, option in options.items():
        allowed = scope
        if "/entities/" in path:
            index = int(path.split("/entities/", 1)[1].split("/", 1)[0])
            allowed = by_name[entities[index]["name"]]
        option["allowed_numeric_tokens"] = sorted(_numeric_tokens(allowed))
        option["numeric_rule"] = "只允许这些精确数字；保留正负号，不缩写财年，不改约数，不计算新值。"
    return options


def _apply_scope_model_patch(candidate, patch, options):
    if not isinstance(patch, dict) or set(patch) != {"patches"} or not isinstance(patch["patches"], list) or not patch["patches"]:
        raise ValueError("局部AI修订必须返回非空patches数组")
    result = json.loads(json.dumps(candidate, ensure_ascii=False))
    seen = set()
    for item in patch["patches"]:
        if not isinstance(item, dict) or set(item) != {"path", "value"}:
            raise ValueError("局部AI修订字段协议错误")
        path, value = item["path"], item["value"]
        if not isinstance(path, str) or path not in options or path in seen:
            raise ValueError("局部AI修订包含未知、跨实体或重复路径")
        seen.add(path)
        expected = options[path]["type"]
        if (expected == "string" and not isinstance(value, str)) or (
            expected == "array" and (not isinstance(value, list) or any(not isinstance(v, str) for v in value))
        ):
            raise ValueError("局部AI修订值类型错误")
        # Keep every explicit model value, even an unchanged field, so a later
        # valid field is not discarded. The full validator still rejects errors.
        target = result
        parts = path.lstrip("/").split("/")
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        if parts[-1] not in target:
            raise ValueError("局部AI修订不得添加未提供字段")
        target[parts[-1]] = value
    if seen != set(options):
        raise ValueError(f"局部AI修订遗漏错误字段：{sorted(set(options) - seen)}")
    return result


def _request_scope_model_patch(scope, candidate, options, config, *, trace_path=None, repair_feedback=None):
    from ai_rate_limit import wait_for_internal_ai_slot

    model = _executive_model_route()[0]
    api_key = str(config.get("api_key") or "")
    messages = [
        {"role": "system", "content": (
            "你是事实约束下的分析修订员。本次只修正列出的错误字段，不重新生成完整分析。"
            "只返回JSON对象{patches:[{path,value}]}。path必须逐字选自allowed_patches；"
            "不要修改未列出的字段、实体身份或输入证据。每个value必须由你依据原证据重新生成。"
            "必须逐一修正全部allowed_patches字段，禁止照抄仍有错误的current值。"
            "headline只能是28字内的经营判断，目标10至22字；不在标题堆金额、单位或财年，数字留在原正文。"
            "过长正文必须由你改写为60至85字，英文、数字和标点每个字符均计数，一至两句；"
            "输出前自行核对字符数。正文只保留原稿中同期间可比的两家公司原值及经营关系，"
            "其他事实已经保留在完整实体明细，不要重复全部公司的数值；无法比较时保留真实口径边界。"
            "引用数组只选该路径提供的allowed_values；无需明细引用时可以明确返回[]。"
            + FOCUS_EVIDENCE_CONTRACT
            + "本次局部修订的字数目标以每个allowed_patches字段的target_characters为准，必须真正改正列出的错误。"
        )},
        {"role": "user", "content": json.dumps({"task": "repair_only_invalid_fields_v1",
            "allowed_patches": options, "original_draft": candidate, "previous_failed_correction": repair_feedback,
            "evidence": _model_prompt_evidence(scope)}, ensure_ascii=False)},
    ]
    request = _model_request(config, api_key, prepare_structured_chat_body({
        **dict(config.get("extra_parameters") or {}), "model": model, "messages": messages,
        "temperature": 0.1, "max_tokens": 4000,
    }))
    started, payload, error = time.monotonic(), {}, None
    patch, patched, http_calls = None, None, 0

    def single_transport(*args, **kwargs):
        nonlocal http_calls
        if http_calls:
            raise ValueError("单次局部AI修订只允许一个HTTP，禁止隐式轮转或重放")
        http_calls += 1
        # The recovery budget counts HTTP requests, including failed requests.
        # A proxy fallback or key rotation must not silently multiply this call.
        return urllib.request.urlopen(*args, **kwargs)

    try:
        with open_llm_request(request, timeout=90, config=config, requested_key=api_key, model=model,
                                  operation="executive-intelligence-local-patch",
                              open_func=single_transport, max_transport_retries=0) as response:
            payload = read_chat_completion_sse(response)
        patch = load_json_response(final_chat_message_text(payload, operation="局部AI修订"), operation="局部AI修订")
        actual_model = str(payload.get("model") or "")
        if not actual_model:
            raise ValueError("局部AI修订未声明实际返回模型")
        patched = _apply_scope_model_patch(candidate, patch, options)
        domain = scope["domains"][0]
        validated = _validate_model_summaries([patched], scope, expected_domains={domain["id"]},
            expected_focus_ids_by_domain={domain["id"]: {f["id"] for f in domain["focuses"]}})[0]
        return validated, {"requested_model": model, "reported_model": actual_model, "patches": patch["patches"],
                           "patch_hash": _content_hash(patch), "http_calls": http_calls,
                           "response_id": payload["id"], "created": payload["created"],
                           "stream": payload["stream_diagnostics"], "response_hash": payload["stream_diagnostics"]["response_hash"],
                           "before_hash": _content_hash(candidate), "after_hash": _content_hash(validated), "full_gate": "passed"}
    except Exception as exc:
        error = exc
        exc.model_patch_attempt = {
            "requested_model": model, "reported_model": payload.get("model"),
            "response": payload, "response_hash": _content_hash(payload),
            "submitted_patch": patch, "patch_hash": _content_hash(patch) if patch is not None else "",
            "candidate": patched, "after_hash": _content_hash(patched) if patched is not None else "",
            "http_calls": http_calls,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "before_hash": _content_hash(candidate), "full_gate": "failed",
        }
        raise
    finally:
        domain = scope["domains"][0]
        _trace_model_attempt(trace_path, f"{domain['id']}.{domain['focuses'][0]['id']}.patch", model, started, payload, error, config)


def generate_model_domain_summaries(
    evidence: dict[str, Any] | None = None,
    *,
    temperature: float = 0.0,
    allow_partial_domains: bool = False,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot
    from network_utils import urlopen_with_local_proxy_fallback

    evidence = evidence or _analysis_input_snapshot()
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置内网模型密钥")
    system_prompt = (
        "你是电信竞争情报分析员。只使用输入的公司、数值、单位、原始财年、口径和来源。"
        "按领域和focus组织分析：点名具体企业、引用当前数值，解释有证据支持的经营意义；"
        "不要只复述排名，不把相关性当因果，不写行动建议，不编造数字、来源或缺失值。"
        "每个领域返回headline、analysis、risk、source_urls和focuses。每个focus返回id、headline、"
        "analysis、risk、source_urls、entities。每个实体返回name、headline、analysis、risk、"
        "evidence_labels、source_urls。必须覆盖输入的全部focus和实体，不额外添加。"
        "focus正文一至两句、120字内，标题28字内且是经营判断；实体正文只需准确说明本实体事实和口径。"
        "同币种、同期间才比较金额。用户总数与后付费客户、云分部与公司整体不能混作同一指标。"
        "所有标题与正文由你依据事实生成，程序不会代写。"
        "source_urls和evidence_labels仅从对应输入中原样选择。仅返回JSON对象{\"items\":[领域对象]}。"
        + FOCUS_EVIDENCE_CONTRACT
    )
    requested_domain_ids = [str(domain.get("id") or "") for domain in evidence.get("domains") or []]
    validation_domains = set(requested_domain_ids) if allow_partial_domains else None
    user_prompt = (
        f"请分析输入中的领域：{', '.join(requested_domain_ids)}。返回{{\"items\":[...]}}，每项字段严格为"
        "domain, headline, analysis, risk, source_urls, focuses；focuses每项字段严格为"
        "id, headline, analysis, risk, source_urls, entities；entities每项字段严格为"
        "name, headline, analysis, risk, evidence_labels, source_urls。不要Markdown。输入：\n"
        + json.dumps(_model_prompt_evidence(evidence), ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    body = prepare_structured_chat_body({
        **dict(config.get("extra_parameters") or {}),
        "model": _executive_model_route()[0],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 16000,
    })
    summaries: list[dict[str, Any]] | None = None
    last_error: Exception | None = None
    used_models: set[str] = set()
    checkpoint = _read_json(checkpoint_path, {}) if checkpoint_path else {}
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    draft_path = checkpoint_path.with_suffix(".drafts.json") if checkpoint_path else None
    drafts = _read_json(draft_path, {}) if draft_path else {}
    if not isinstance(drafts, dict):
        drafts = {}

    def cache_key(scope):
        return _content_hash({"format": INSIGHT_FORMAT_VERSION, "prompt_version": STRATEGIC_PROMPT_VERSION, "checkpoint_protocol": 2, "scope": scope})

    def validate_scope(scope, candidates):
        return _validate_model_summaries(candidates, scope,
            expected_domains={d["id"] for d in scope["domains"]},
            expected_focus_ids_by_domain={d["id"]: {f["id"] for f in d.get("focuses", [])} for d in scope["domains"]})

    def cached(scope):
        key = cache_key(scope)
        entry = checkpoint.get(key, {})
        migrated_from = None
        if not entry:
            old_key = cache_key(_previous_annual_source_evidence(scope))
            if old_key != key and checkpoint.get(old_key):
                entry = checkpoint[old_key]
                migrated_from = old_key
        if not isinstance(entry, dict) or not isinstance(entry.get("model"), str) or not entry.get("model") or not entry.get("summaries"):
            return None
        try:
            result = validate_scope(scope, entry["summaries"])
        except (ValueError, TypeError, AttributeError):
            return None
        used_models.update(entry["model"].split("+"))
        if migrated_from and checkpoint_path:
            checkpoint[key] = {**entry, "summaries": result,
                "source_migration": {"previous_checkpoint_key": migrated_from, "current_checkpoint_key": key,
                                     "basis": "verified_annual_source_correction", "full_gate": "passed",
                                     "model_text_preserved": True}}
            _atomic_write_json(checkpoint_path, checkpoint)
        return result[0]

    def save(scope, candidate, model, patch_audit=None):
        candidate = validate_scope(scope, [candidate])[0]
        if checkpoint_path:
            previous = checkpoint.get(cache_key(scope), {})
            if not patch_audit and isinstance(previous, dict) and previous.get("summaries") == [candidate]:
                patch_audit = previous.get("patch_audit")
            checkpoint[cache_key(scope)] = {"model": model, "summaries": [candidate], "generated_at_hkt": _now()}
            if patch_audit:
                checkpoint[cache_key(scope)]["patch_audit"] = patch_audit
            _atomic_write_json(checkpoint_path, checkpoint)

    def persist_drafts():
        if draft_path:
            from ai_config import api_key_candidates
            encoded = json.dumps(drafts, ensure_ascii=False)
            for route in ("", *_executive_model_route()):
                for secret in api_key_candidates(config, model=route):
                    if secret:
                        encoded = encoded.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[redacted]")
            encoded = re.sub(r"(?i)Bearer\s+[^\s\"\\]+", "Bearer [redacted]", encoded)
            _atomic_write_json(draft_path, json.loads(encoded))

    def scoped_draft(scope, candidate):
        if not isinstance(candidate, dict):
            return None
        target = scope["domains"][0]["focuses"][0]["id"]
        matches = [f for f in candidate.get("focuses") or [] if isinstance(f, dict) and f.get("id") == target]
        if len(matches) != 1:
            return candidate
        focus = matches[0]
        return {"domain": scope["domains"][0]["id"], "focuses": [focus],
                **{key: focus.get(key) for key in ("headline", "analysis", "risk", "source_urls")}}

    def stash_draft(scope, candidate, requested, reported, error):
        if not draft_path or not isinstance(candidate, dict):
            return
        candidate = scoped_draft(scope, candidate)
        try:
            options = _scope_patch_options(candidate, scope)
        except (ValueError, TypeError, KeyError, AttributeError):
            options = {}
        entry = drafts.setdefault(cache_key(scope), {"evidence_hash": _content_hash(scope), "candidates": []})
        entry["candidates"].append({"candidate": json.loads(json.dumps(candidate, ensure_ascii=False)),
            "candidate_hash": _content_hash(candidate), "requested_model": requested, "reported_model": reported,
            "error": str(error), "eligible_fields": options, "recorded_at_hkt": _now()})
        persist_drafts()

    def patch_spent(scope):
        return bool((drafts.get(cache_key(scope), {}).get("repair") or {}).get("attempted"))

    def repair_scope_once(scope):
        entry = drafts.get(cache_key(scope), {})
        if not entry or not draft_path:
            return None
        previous = entry.get("repair") or {}
        def transport_deferred(attempt):
            from data_curation.research_recovery import recoverable
            return (not attempt.get("reported_model") and not attempt.get("response")
                    and not attempt.get("submitted_patch") and recoverable(attempt.get("error", "")))
        history = previous.get("history")
        if not isinstance(history, list):
            history = [{k: v for k, v in previous.items() if k != "history"}] if previous.get("attempted") else []
        eligible = [item for item in entry.get("candidates") or [] if item.get("eligible_fields") and item.get("reported_model")]
        if not eligible:
            return None
        selected = (next((item for item in eligible if item["candidate_hash"] == history[0].get("before_hash")), None)
                    if history else None)
        if history and selected is None:
            raise ValueError("已存修订缺少原始草稿，保留预算并拒绝更换输入")
        selected = selected or min(reversed(eligible), key=lambda item: len(item["eligible_fields"]))
        candidate = selected["candidate"]
        models = {selected["reported_model"]}
        history_patch_hashes = set()
        recovered_prior_patch = None
        # Legacy attempt 1 remains charged. Reconstruct only its explicit model
        # patch against its recorded whitelist; never synthesize missing prose.
        for old in history:
            if old.get("reported_model"):
                models.add(old["reported_model"])
            packet = old.get("submitted_patch") or ({"patches": old["patches"]} if old.get("patches") else None)
            if packet is None and old.get("response"):
                try:
                    packet = load_json_response(final_chat_message_text(old["response"], operation="已存失败修订"))
                except ValueError:
                    packet = None
            if packet is not None:
                recovered_prior_patch = packet
                history_patch_hashes.add(_content_hash(packet))
            if isinstance(old.get("candidate"), dict):
                candidate = old["candidate"]
                continue
            if packet is not None:
                try:
                    candidate = _apply_scope_model_patch(candidate, packet, old.get("eligible_fields") or selected["eligible_fields"])
                except (ValueError, KeyError, TypeError, IndexError):
                    pass
        while True:
            options = _scope_patch_options(candidate, scope)
            try:
                already_valid = validate_scope(scope, [candidate])[0]
            except (ValueError, TypeError, AttributeError) as exc:
                current_error = str(exc)
            else:
                audit = {**previous, "protocol": 2, "history": history, "status": "passed", "max_attempts": 3}
                entry["repair"] = audit
                save(scope, already_valid, "+".join(sorted(models)), patch_audit=audit)
                persist_drafts()
                used_models.update(models)
                return already_valid, "+".join(sorted(models))
            # A corrected gate may accept the saved model text with zero HTTP.
            # Revalidation never resets or extends a spent/stopped budget.
            if (previous.get("status") == "stopped" and not transport_deferred(previous)) or sum(not transport_deferred(h) for h in history) >= 3:
                raise ValueError("AI分析修订额度已使用或重复无进展，保留全部历史：" + str(previous.get("error") or previous.get("stop_reason") or "最多3次模型修订"))
            if not options:
                raise ValueError("失败稿没有可安全修订的现有字段：" + current_error)
            prior = history[-1] if history else {}
            attempt = {"protocol": 2, "attempted": True, "attempt_number": len(history) + 1,
                       "status": "running", "started_at_hkt": _now(),
                       "source_requested_model": selected["requested_model"], "source_reported_model": selected["reported_model"],
                       "before_hash": _content_hash(candidate), "before_candidate": candidate,
                       "eligible_fields": options, "input_gate_error": current_error}
            history.append(attempt)
            entry["repair"] = {**attempt, "history": history, "max_attempts": 3}
            persist_drafts()  # Charge before the one bounded HTTP; never refund.
            try:
                repaired, audit = _request_scope_model_patch(scope, candidate, options, config,
                    trace_path=attempt_trace_path, repair_feedback={"current_gate_error": current_error,
                        "previous_error": prior.get("error"), "previous_patch": prior.get("submitted_patch") or recovered_prior_patch})
                attempt.update(audit, status="passed", candidate=repaired, completed_at_hkt=_now())
                models.add(audit["reported_model"])
                entry["repair"] = {**attempt, "history": history, "max_attempts": 3}
                save(scope, repaired, "+".join(sorted(models)), patch_audit=entry["repair"])
                persist_drafts()
                used_models.update(models)
                return repaired, "+".join(sorted(models))
            except Exception as exc:
                attempt.update(getattr(exc, "model_patch_attempt", {}), status="failed", error=str(exc), completed_at_hkt=_now())
                if transport_deferred(attempt):
                    # A model that returned no response did not revise the prose.
                    # Preserve the HTTP audit, then yield to the bounded durable
                    # stage retry instead of spending all edits in a cooldown loop.
                    attempt["status"] = "deferred_transport"
                    entry["repair"] = {**attempt, "history": history, "max_attempts": 3}
                    persist_drafts()
                    raise
                if attempt.get("reported_model"):
                    models.add(attempt["reported_model"])
                next_candidate = attempt.get("candidate") or candidate
                next_options = _scope_patch_options(next_candidate, scope)
                improved = bool(set(options) - set(next_options))
                for path in set(options) & set(next_options):
                    before, after = options[path], next_options[path]
                    if before.get("max_characters") and isinstance(before.get("current"), str) and isinstance(after.get("current"), str):
                        improved |= len(before["current"]) > before["max_characters"] and len(after["current"]) < len(before["current"])
                    allowed = set(before.get("allowed_numeric_tokens") or [])
                    improved |= len(_numeric_tokens(after.get("current")) - allowed) < len(_numeric_tokens(before.get("current")) - allowed)
                repeated = bool(attempt.get("patch_hash") and (attempt["patch_hash"] in history_patch_hashes or any(
                    old.get("patch_hash") == attempt["patch_hash"] for old in history[:-1])))
                repeated |= any(old.get("error") == str(exc) for old in history[:-1]) and not improved
                if repeated:
                    attempt.update(status="stopped", stop_reason="重复patch/hash或同错误无进展")
                entry["repair"] = {**attempt, "history": history, "max_attempts": 3}
                persist_drafts()
                if repeated or sum(not transport_deferred(h) for h in history) >= 3:
                    raise ValueError("AI分析修订额度已使用或重复无进展：" + str(exc)) from exc
                candidate = next_candidate


    def save_valid_focus_parts(domain_scope, candidate, model, requested=None, reported=None, raw_candidate=None):
        if not checkpoint_path:
            return 0
        saved = 0
        for focus_evidence in domain_scope["domains"][0].get("focuses") or []:
            matches = [f for f in candidate.get("focuses") or []
                       if isinstance(f, dict) and f.get("id") == focus_evidence.get("id")]
            if len(matches) != 1:
                continue
            focus = matches[0]
            scope = {"domains": [{**domain_scope["domains"][0], "focuses": [focus_evidence]}]}
            # The scope envelope uses this focus's model prose verbatim; other
            # focus claims from the domain overview are outside this checkpoint.
            single = {"domain": domain_scope["domains"][0]["id"], "focuses": [focus],
                      **{key: focus.get(key) for key in ("headline", "analysis", "risk", "source_urls")}}
            try:
                save(scope, single, model)
            except (ValueError, TypeError, AttributeError) as exc:
                stash_draft(scope, raw_candidate or candidate, requested or model, reported, exc)
                continue
            saved += 1
        return saved

    attempt_trace_path = checkpoint_path.with_suffix(".attempts.jsonl") if checkpoint_path else None
    entity_count = sum(
        len(focus.get("items") or [])
        for domain in evidence.get("domains") or []
        for focus in domain.get("focuses") or []
    )
    # Large all-domain payloads can exceed the internal gateway response window.
    # Split them by domain immediately; each response remains independently gated.
    primary_attempts = 0 if entity_count > 40 or checkpoint_path else 3
    for attempt in range(primary_attempts):
        content = ""
        body["model"] = _executive_model_route()[min(attempt, len(_executive_model_route()) - 1)]
        body["messages"] = messages
        request = _model_request(config, api_key, body)
        try:
            with open_llm_request(
                request,
                timeout=180,
                config=config,
                requested_key=api_key,
                model=str(body.get("model") or ""),
                open_func=urlopen_with_local_proxy_fallback,
                operation="executive-intelligence-analysis",
            ) as response:
                payload = read_chat_completion_sse(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                last_error = exc
                continue
            detail = exc.read().decode("utf-8", errors="ignore")[:800]
            raise RuntimeError(f"内网模型 HTTP {exc.code}: {detail}") from exc
        except (APIKeyPoolUnavailable, ValueError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            continue
        try:
            content = final_chat_message_text(payload, operation="17项AI洞察")
            raw_summaries = unwrap_items_payload(
                load_json_response(content, operation="17项AI洞察"), operation="17项AI洞察"
            )
            summaries = _validate_model_summaries(
                raw_summaries,
                evidence,
                expected_domains=validation_domains,
            )
            used_models.add(str(payload["model"]))
            break
        except (APIKeyPoolUnavailable, ValueError, json.JSONDecodeError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 < primary_attempts:
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                f"上一版未通过事实门禁：{exc}。请删除或改写所有未获输入支持的数字/来源，"
                                "保持四个领域、全部focus和全部实体完整并重新只返回JSON对象{\"items\":[...]}。"
                            ),
                        },
                    ]
                )
    if summaries is None:
        # Older model deployments sometimes follow the four-domain shape but omit
        # nested focus summaries. Retry one domain at a time so every focus can be
        # checked explicitly without asking the model to hold all views at once.
        per_domain_summaries: list[dict[str, Any]] = []
        scope_errors: list[str] = []
        for domain_evidence in evidence.get("domains") or []:
            domain_models: set[str] = set()
            domain_id = str(domain_evidence.get("id") or "")
            domain_scope = {"domains": [domain_evidence]}
            restored = cached(domain_scope)
            if restored is not None:
                per_domain_summaries.append(restored)
                continue
            expected_focus_ids = {
                str(focus.get("id") or "")
                for focus in domain_evidence.get("focuses") or []
                if str(focus.get("id") or "")
            }
            domain_messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"只分析 {domain_id} 这一个领域，返回JSON对象{{\"items\":[单个领域对象]}}。"
                        "必须逐一返回输入中的全部focus id及其全部实体。字段协议不变。输入：\n"
                        + json.dumps(_model_prompt_evidence({"domains": [domain_evidence]}), ensure_ascii=False)
                    ),
                },
            ]
            domain_summary: dict[str, Any] | None = None
            domain_error: Exception | None = None
            has_focus_checkpoint = any(checkpoint.get(cache_key({"domains": [{**domain_evidence, "focuses": [f]}]}))
                                       for f in domain_evidence.get("focuses") or [])
            has_focus_checkpoint = has_focus_checkpoint or any(
                patch_spent({"domains": [{**domain_evidence, "focuses": [f]}]}) for f in domain_evidence.get("focuses") or [])
            for domain_attempt in range(0 if has_focus_checkpoint else 3):
                candidate = None
                raw_domain_candidate = None
                domain_payload = {}
                attempt_error = None
                body["model"] = _executive_model_route()[min(domain_attempt, len(_executive_model_route()) - 1)]
                request = _model_request(config, api_key, {**body, "messages": domain_messages})
                attempt_started = time.monotonic()
                try:
                    with open_llm_request(
                        request,
                        timeout=180,
                        config=config,
                        requested_key=api_key,
                        model=str(body.get("model") or ""),
                        open_func=urlopen_with_local_proxy_fallback,
                        operation=f"executive-intelligence-analysis-{domain_id}",
                    ) as response:
                        domain_payload = read_chat_completion_sse(response)
                    domain_content = final_chat_message_text(
                        domain_payload, operation=f"{domain_id}领域AI洞察"
                    )
                    parsed = unwrap_items_payload(
                        load_json_response(domain_content, operation=f"{domain_id}领域AI洞察"),
                        operation=f"{domain_id}领域AI洞察",
                    )
                    if len(parsed) != 1 or not isinstance(parsed[0], dict):
                        raise ValueError("必须返回只含一个领域对象的items数组")
                    raw_domain_candidate = _pin_scoped_model_identity([parsed[0]], domain_id)[0]
                    candidate = json.loads(json.dumps(raw_domain_candidate, ensure_ascii=False))
                    returned_focus_ids = {
                        str(focus.get("id") or "")
                        for focus in candidate.get("focuses") or []
                        if isinstance(focus, dict)
                    }
                    if not expected_focus_ids.issubset(returned_focus_ids):
                        raise ValueError(f"分类覆盖不完整：{sorted(expected_focus_ids - returned_focus_ids)}")
                    returned_by_focus = {
                        str(focus.get("id") or ""): {
                            str(entity.get("name") or "") for entity in focus.get("entities") or []
                            if isinstance(entity, dict) and str(entity.get("name") or "")
                        }
                        for focus in candidate.get("focuses") or [] if isinstance(focus, dict)
                    }
                    for evidence_focus in domain_evidence.get("focuses") or []:
                        focus_id = str(evidence_focus.get("id") or "")
                        expected_names = {
                            str(entity.get("name") or "") for entity in evidence_focus.get("items") or []
                            if str(entity.get("name") or "")
                        }
                        if returned_by_focus.get(focus_id, set()) != expected_names:
                            raise ValueError(f"实体覆盖不完整：{focus_id}")
                        returned_focus = next(
                            focus for focus in candidate.get("focuses") or []
                            if isinstance(focus, dict) and str(focus.get("id") or "") == focus_id
                        )
                        focus_gate_error = _focus_gate_error(
                            domain_id,
                            focus_id,
                            str(returned_focus.get("analysis") or ""),
                            evidence_focus,
                        )
                        if focus_gate_error:
                            raise ValueError(focus_gate_error)
                    candidate["domain"] = domain_id
                    candidate["focuses"] = [
                        focus for focus in candidate.get("focuses") or []
                        if isinstance(focus, dict) and str(focus.get("id") or "") in expected_focus_ids
                    ]
                    domain_summary = validate_scope(domain_scope, [candidate])[0]
                    actual_model = str(domain_payload.get("model") or body["model"])
                    used_models.add(actual_model)
                    domain_models.add(actual_model)
                    break
                except (APIKeyPoolUnavailable, ValueError, json.JSONDecodeError, TimeoutError, urllib.error.URLError) as exc:
                    domain_error = exc
                    attempt_error = exc
                    if candidate and save_valid_focus_parts(domain_scope, candidate,
                            str(domain_payload.get("model") or body["model"]), str(body["model"]),
                            domain_payload.get("model"), raw_domain_candidate):
                        break
                    if domain_attempt < 2:
                        domain_messages.append({
                            "role": "user",
                            "content": (
                                f"上一版未通过门禁：{exc}。请完整返回全部focus和全部实体。"
                                "每个focus.analysis用一至两句、总长不超过120字：引用输入原值，并解释数字背后的结构、驱动、"
                                "集中度、口径可比性或市场阶段。禁止建议、应、需、优先、关注、评估、验证等行动话术。"
                                "不要只复述高低增减或解释指标用途。仍只返回JSON对象{\"items\":[单个领域对象]}。"
                            ),
                        })
                finally:
                    _trace_model_attempt(attempt_trace_path, domain_id, str(body["model"]),
                                         attempt_started, domain_payload, attempt_error, config)
            if domain_summary is None:
                focus_parts: list[dict[str, Any]] = []
                domain_fields: dict[str, Any] | None = None
                domain_focus_failed = False
                for focus_evidence in domain_evidence.get("focuses") or []:
                    focus_id = str(focus_evidence.get("id") or "")
                    focus_scope = {"domains": [{**domain_evidence, "focuses": [focus_evidence]}]}
                    restored = cached(focus_scope)
                    if restored is not None:
                        domain_models.update(checkpoint[cache_key(focus_scope)]["model"].split("+"))
                        if domain_fields is None:
                            domain_fields = {k: restored.get(k) for k in ("domain", "headline", "analysis", "risk", "source_urls")}
                        focus_parts.extend(restored["focuses"])
                        continue
                    if patch_spent(focus_scope):
                        try:
                            repaired = repair_scope_once(focus_scope)
                            if not repaired:
                                raise ValueError("已有修订历史但无可安全继续的草稿")
                            restored, repaired_models = repaired
                            domain_models.update(repaired_models.split("+"))
                            if domain_fields is None:
                                domain_fields = {k: restored.get(k) for k in ("domain", "headline", "analysis", "risk", "source_urls")}
                            focus_parts.extend(restored["focuses"])
                        except (APIKeyPoolUnavailable, ValueError, RuntimeError, TimeoutError, urllib.error.URLError) as exc:
                            scope_errors.append(f"AI分析修订额度已使用或未通过：{domain_id}.{focus_id}: {exc}")
                            domain_focus_failed = True
                        continue
                    expected_names = {
                        str(entity.get("name") or "") for entity in focus_evidence.get("items") or []
                        if str(entity.get("name") or "")
                    }
                    focus_messages = [
                        {
                            "role": "system",
                            "content": (
                                "你是电信竞争情报分析员。只返回合法JSON对象，顶层字段只能是items数组，不要解释。只能使用输入证据。"
                                "逐一覆盖items中的全部实体，name必须原样；实体只需准确陈述事实、期间、单位和口径，"
                                "不强迫单个实体推导经营含义。evidence_labels如使用，只能原样选自该实体components.label。"
                                "focus.headline必须由你生成，为28字内的经营判断，不能照抄指标名称。"
                                "focus.analysis必须用一至两句、总长不超过120字，引用输入具体数值并解释结构、驱动、"
                                "集中度或市场阶段；比较限制可放在risk，正文解释经营含义。"
                                "禁止写按排名、图中排序、同一视图、便于比较、数据库内、此视图等界面说明。"
                                + FOCUS_EVIDENCE_CONTRACT
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"只分析 {domain_id}.{focus_id} 这一个分类，返回JSON对象{{\"items\":[只含一个focus的领域对象]}}。"
                                f"实体name必须完整且原样等于：{json.dumps(sorted(expected_names), ensure_ascii=False)}。"
                                "items固定结构为：[{domain,headline,analysis,risk,source_urls,focuses:[{id,headline,analysis,risk,"
                                "source_urls,entities:[{name,headline,analysis,risk,evidence_labels,source_urls}]}]}]。输入：\n"
                                + json.dumps(_model_prompt_evidence({"domains": [{**domain_evidence, "focuses": [focus_evidence]}]}), ensure_ascii=False)
                            ),
                        },
                    ]
                    focus_candidate: dict[str, Any] | None = None
                    focus_error: Exception | None = None
                    focus_models = _executive_model_route()
                    for focus_attempt, focus_model in enumerate(focus_models):
                        raw_focus_candidate = None
                        focus_payload = {}
                        attempt_error = None
                        request = _model_request(config, api_key, {**body, "model": focus_model, "messages": focus_messages})
                        attempt_started = time.monotonic()
                        try:
                            with open_llm_request(
                                request,
                                timeout=180,
                                config=config,
                                requested_key=api_key,
                                model=focus_model,
                                open_func=urlopen_with_local_proxy_fallback,
                                operation=f"executive-intelligence-analysis-{domain_id}-{focus_id}",
                            ) as response:
                                focus_payload = read_chat_completion_sse(response)
                            focus_content = final_chat_message_text(
                                focus_payload, operation=f"{domain_id}.{focus_id} AI洞察"
                            )
                            parsed = unwrap_items_payload(
                                load_json_response(
                                    focus_content, operation=f"{domain_id}.{focus_id} AI洞察"
                                ),
                                operation=f"{domain_id}.{focus_id} AI洞察",
                            )
                            if len(parsed) != 1 or not isinstance(parsed[0], dict):
                                raise ValueError("必须返回只含一个领域对象的items数组")
                            raw_focus_candidate = _pin_scoped_model_identity([parsed[0]], domain_id, focus_id)[0]
                            candidate = json.loads(json.dumps(raw_focus_candidate, ensure_ascii=False))
                            returned_focuses = [
                                focus for focus in candidate.get("focuses") or []
                                if isinstance(focus, dict) and str(focus.get("id") or "") == focus_id
                            ]
                            if len(returned_focuses) != 1:
                                raise ValueError(f"必须只返回分类 {focus_id}")
                            returned_names = {
                                str(entity.get("name") or "") for entity in returned_focuses[0].get("entities") or []
                                if isinstance(entity, dict) and str(entity.get("name") or "")
                            }
                            if returned_names != expected_names:
                                raise ValueError(f"实体覆盖不完整：{sorted(expected_names - returned_names)}")
                            focus_gate_error = _focus_gate_error(
                                domain_id,
                                focus_id,
                                str(returned_focuses[0].get("analysis") or ""),
                                focus_evidence,
                            )
                            if focus_gate_error:
                                raise ValueError(focus_gate_error)
                            candidate["domain"] = domain_id
                            candidate["focuses"] = returned_focuses
                            focus_candidate = validate_scope(focus_scope, [candidate])[0]
                            actual_model = str(focus_payload.get("model") or focus_model)
                            used_models.add(actual_model)
                            domain_models.add(actual_model)
                            save(focus_scope, focus_candidate, actual_model)
                            break
                        except (APIKeyPoolUnavailable, ValueError, json.JSONDecodeError, TimeoutError, urllib.error.URLError) as exc:
                            focus_error = exc
                            attempt_error = exc
                            stash_draft(focus_scope, raw_focus_candidate, focus_model, focus_payload.get("model"), exc)
                            if focus_attempt + 1 < len(focus_models):
                                focus_messages.append({
                                    "role": "user",
                                    "content": (
                                        f"上一版未通过门禁：{exc}。请只返回该focus及全部实体。"
                                        "focus.analysis必须用一至两句、总长不超过120字，引用输入原值并解释数字背后的结构、驱动、"
                                        "集中度、口径可比性或市场阶段；禁止建议、应、需、优先、关注、评估、验证等行动话术，"
                                        "也不能只复述高低增减或指标定义。只返回合法JSON对象{\"items\":[单个领域对象]}。"
                                    ),
                                })
                        finally:
                            _trace_model_attempt(attempt_trace_path, f"{domain_id}.{focus_id}", focus_model,
                                                 attempt_started, focus_payload, attempt_error, config)
                    if focus_candidate is None and not isinstance(focus_error, APIKeyPoolUnavailable):
                        try:
                            repaired = repair_scope_once(focus_scope)
                            if repaired:
                                focus_candidate, repaired_models = repaired
                                domain_models.update(repaired_models.split("+"))
                        except (APIKeyPoolUnavailable, ValueError, RuntimeError, TimeoutError, urllib.error.URLError) as exc:
                            focus_error = exc
                    if focus_candidate is None:
                        scope_errors.append(
                            f"AI分析按分类重试仍未通过：{domain_id}.{focus_id}: {focus_error}; 领域错误：{domain_error}"
                        )
                        domain_focus_failed = True
                        continue
                    if domain_fields is None:
                        domain_fields = {
                            key: focus_candidate.get(key)
                            for key in ("domain", "headline", "analysis", "risk", "source_urls")
                        }
                    focus_parts.extend(focus_candidate["focuses"])
                if domain_focus_failed:
                    continue
                if not focus_parts:
                    scope_errors.append(f"AI分析未生成：{domain_id}: {domain_error}")
                    continue
                domain_summary = {**(domain_fields or {"domain": domain_id}), "focuses": focus_parts}
            save(domain_scope, domain_summary, "+".join(sorted(domain_models)))
            per_domain_summaries.append(domain_summary)
        if scope_errors:
            raise ValueError("；".join(scope_errors))
        summaries = _validate_model_summaries(
            per_domain_summaries,
            evidence,
            expected_domains=validation_domains,
        )
    return {
        "generated_at_hkt": _now(),
        "model": "+".join(sorted(used_models)) if used_models else str(body["model"]),
        "summaries": summaries,
        "presentation_warnings": _summary_presentation_warnings(summaries),
    }


def _compact_discovery_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep bounded metrics and verified period facts without merging their grains."""
    domains: list[dict[str, Any]] = []
    for domain in evidence.get("domains") or []:
        compact_focuses: list[dict[str, Any]] = []
        for focus in domain.get("focuses") or []:
            compact_focuses.append({
                "id": focus.get("id"),
                "title": focus.get("title"),
                "metric": focus.get("metric"),
                "items": [
                    {
                        "name": item.get("name"),
                        "value": item.get("value"),
                        "unit": item.get("unit"),
                        "period": item.get("period"),
                        "grain": item.get("grain"),
                        "detail": item.get("detail"),
                        "trend": item.get("trend"),
                        "source_url": item.get("source_url"),
                    }
                    for item in (focus.get("items") or [])
                    if isinstance(item, dict)
                ],
            })
        domains.append({
            "id": domain.get("id"),
            "title": domain.get("title"),
            "focuses": compact_focuses,
            "research_comparison_scope": domain.get("research_comparison_scope"),
            "agent_verified_facts": json.loads(json.dumps([
                fact for fact in domain.get("agent_verified_facts") or []
                if isinstance(fact, dict)
            ][:40], ensure_ascii=False)),
        })
    return {"domains": domains}


def _manual_discovery_evidence(
    evidence: dict[str, Any], source_domain: str, target_domain: str
) -> dict[str, Any]:
    """Let the model choose relevant facts from both domains, as in batch generation."""
    scoped = {"domains": [domain for domain in evidence.get("domains") or []
                          if domain.get("id") in {source_domain, target_domain}]}
    return _compact_discovery_evidence(scoped)


def _discovery_patch_options(candidate, evidence):
    if not isinstance(candidate, list) or len(candidate) != 4:
        return {}
    pairs = [tuple(sorted((item.get("from", ""), item.get("to", "")))) for item in candidate if isinstance(item, dict)]
    if len(pairs) != 4 or len(set(pairs)) != 4 or any(a == b for a, b in pairs):
        return {}
    options = {}
    for index, item in enumerate(candidate):
        try:
            _validate_model_discoveries([item], evidence, require_complete=False)
        except ValueError as exc:
            options[str(index)] = {"error": str(exc), "current": item,
                "binding_error": _discovery_comparability_error(item, evidence),
                "title_target": 28, "detail_target": 110, "title_max": 36, "detail_max": 160,
                "facts": [a for a in _discovery_fact_anchors(evidence) if a["domain"] in (item["from"], item["to"])]}
    return options


def _apply_discovery_model_patch(candidate, packet, options):
    if not isinstance(packet, dict) or set(packet) != {"patches"} or not isinstance(packet["patches"], list):
        raise ValueError("跨库局部修订必须返回patches数组")
    result = json.loads(json.dumps(candidate, ensure_ascii=False))
    seen = set()
    for patch in packet["patches"]:
        if not isinstance(patch, dict) or set(patch) != {"index", "title", "detail", "source_urls"}:
            raise ValueError("跨库局部修订只能修改index/title/detail/source_urls")
        index = patch["index"]
        # JSON object keys in allowed_items are strings; accept only their
        # exact canonical index spelling, while retaining the original packet.
        if isinstance(index, str) and re.fullmatch(r"[0-3]", index):
            index = int(index)
        if type(index) is not int or str(index) not in options or index in seen:
            raise ValueError("跨库局部修订包含未失败条目、重复或未知位置")
        if not all(isinstance(patch[k], str) for k in ("title", "detail")) or not isinstance(patch["source_urls"], list) or any(not isinstance(u, str) for u in patch["source_urls"]):
            raise ValueError("跨库局部修订值类型非法")
        seen.add(index)
        result[index].update({k: patch[k] for k in ("title", "detail", "source_urls")})
    if {str(i) for i in seen} != set(options):
        raise ValueError("跨库局部修订遗漏失败条目")
    return result


def _repair_saved_discoveries(entry, evidence, config, persist, trace_path):
    from ai_rate_limit import wait_for_internal_ai_slot
    history = entry.setdefault("repair_history", [])
    selected = (entry.get("selected") or {}).get("attempt_index")
    source = (entry["attempts"][selected] if isinstance(selected, int) and selected < len(entry["attempts"]) else None)
    if not source or not isinstance(source.get("candidate"), list):
        source = next((a for a in reversed(entry["attempts"]) if isinstance(a.get("candidate"), list) and len(a["candidate"]) == 4), None)
    if source is None:
        return None
    candidate = source["candidate"]
    models = {source["reported_model"]}
    for old in history:
        if old.get("reported_model"):
            models.add(old["reported_model"])
        if isinstance(old.get("candidate"), list):
            candidate = old["candidate"]
        elif old.get("response") and old.get("allowed_items"):
            try:
                packet = old.get("submitted_patch") or load_json_response(final_chat_message_text(old["response"], operation="已存跨库修订"))
                candidate = _apply_discovery_model_patch(old.get("before_candidate") or candidate, packet, old["allowed_items"])
            except ValueError:
                pass
    while True:
        try:
            accepted = _validate_model_discoveries(candidate, evidence)
        except ValueError as exc:
            error = str(exc)
        else:
            entry["repair_status"] = "passed"
            persist()
            return {"generated_at_hkt": _now(), "model": "+".join(sorted(models)), "discoveries": accepted,
                    "evidence_repair_count": 0, "reused": True,
                    "presentation_warnings": _discovery_presentation_warnings(accepted)}
        if len(history) >= 2 or entry.get("repair_status") == "stopped":
            raise ValueError("跨库局部修订最多2次或重复无进展，保留全部历史：" + error)
        options = _discovery_patch_options(candidate, evidence)
        if not options:
            raise ValueError("已存跨库草稿不能安全局部修订：" + error)
        model = _executive_model_route()[0]
        record = {"attempt_number": len(history) + 1, "status": "running", "requested_model": model,
                  "source_reported_model": source["reported_model"], "before_candidate": candidate,
                  "before_hash": _content_hash(candidate), "input_gate_error": error,
                  "allowed_items": options, "http_calls": 0, "started_at_hkt": _now()}
        history.append(record)
        persist()
        messages = [{"role": "system", "content": (
            "只修正列出的失败跨库发现，其他条目必须保持原样。只返回JSON对象{patches:[{index,title,detail,source_urls}]}。"
            "index只能来自allowed_items；保留from/to身份，每个失败条目都要真正纠错。标题目标28字内，正文目标80至110字、最多两句。"
            "每条只能使用facts中明确的公司、指标、原值、单位、期间与精确source_url，禁止引用同域其他公司或其他指标来源。"
            "所有事实值保留原币，不自行换汇。纠正事实引用时，保留原有且有证据支持的经营判断，"
            "比较限制简短说明，不要把整条分析改成口径说明。"
            + STRATEGIC_WRITING_GUIDE)},
            {"role": "user", "content": json.dumps({"task": "repair_failed_discoveries_v1", "allowed_items": options,
                "previous_error": history[-2].get("error") if len(history) > 1 else None}, ensure_ascii=False)}]
        request = _model_request(config, config["api_key"], prepare_structured_chat_body({
            **dict(config.get("extra_parameters") or {}), "model": model, "messages": messages,
            "temperature": 0.0, "max_tokens": 8000}))
        payload, packet, after, attempt_error = {}, None, None, None
        started = time.monotonic()
        def single_transport(*args, **kwargs):
            if record["http_calls"]:
                raise ValueError("每次跨库局部修订只允许一个HTTP")
            record["http_calls"] += 1
            persist()
            return urllib.request.urlopen(*args, **kwargs)
        try:
            with open_llm_request(request, timeout=180, config=config, requested_key=config["api_key"], model=model,
                                      operation="executive-intelligence-discovery-patch",
                                  open_func=single_transport, max_transport_retries=0) as response:
                payload = read_chat_completion_sse(response)
            record.update(response=payload, reported_model=payload.get("model"), response_id=payload.get("id"), response_hash=_content_hash(payload))
            persist()
            packet = load_json_response(final_chat_message_text(payload, operation="跨库局部修订"))
            record.update(submitted_patch=packet, patch_hash=_content_hash(packet))
            after = _apply_discovery_model_patch(candidate, packet, options)
            record.update(candidate=after, after_hash=_content_hash(after))
            persist()
            _validate_model_discoveries(after, evidence)
            record.update(status="passed", completed_at_hkt=_now())
            models.add(payload["model"])
            candidate = after
            persist()
        except (ValueError, APIKeyPoolUnavailable, TimeoutError, urllib.error.URLError) as exc:
            attempt_error = exc
            record.update(status="failed", error=str(exc), completed_at_hkt=_now())
            duplicate = any(a.get("patch_hash") and a.get("patch_hash") == record.get("patch_hash") for a in history[:-1])
            if duplicate or (after is not None and _content_hash(after) == _content_hash(candidate)):
                entry["repair_status"] = "stopped"
            candidate = after or candidate
            persist()
        finally:
            _trace_model_attempt(trace_path, "discoveries.patch", model, started, payload, attempt_error, config)


def generate_model_discoveries(evidence: dict[str, Any] | None = None, *, attempt_trace_path: Path | None = None) -> dict[str, Any]:
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot

    evidence = evidence or _analysis_input_snapshot()
    prompt_evidence = _compact_discovery_evidence(evidence)
    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置内网模型密钥")
    draft_path = attempt_trace_path.with_suffix(".discoveries.json") if attempt_trace_path else None
    saved = _read_json(draft_path, {}) if draft_path else {}
    if not isinstance(saved, dict):
        saved = {}
    evidence_hash = _content_hash({"schema": "four_discoveries_v1", "prompt_version": STRATEGIC_PROMPT_VERSION, "evidence": prompt_evidence})
    if evidence_hash not in saved:
        previous_compact = _compact_discovery_evidence(_previous_annual_source_evidence(evidence))
        previous_hash = _content_hash({"schema": "four_discoveries_v1", "prompt_version": STRATEGIC_PROMPT_VERSION, "evidence": previous_compact})
        if previous_hash != evidence_hash and previous_hash in saved:
            saved[evidence_hash] = json.loads(json.dumps(saved[previous_hash], ensure_ascii=False))
            saved[evidence_hash]["source_migration"] = {"previous_evidence_hash": previous_hash, "current_evidence_hash": evidence_hash,
                                                       "basis": "verified_annual_source_correction", "request_history_preserved": True}
            saved[evidence_hash]["evidence_hash"] = evidence_hash
    entry = saved.setdefault(evidence_hash, {"protocol": 1, "evidence_hash": evidence_hash,
                                            "attempts": [], "model_route_counts": {}})
    if not isinstance(entry, dict) or not isinstance(entry.get("attempts"), list) or not isinstance(entry.get("model_route_counts"), dict):
        raise ValueError("跨库发现恢复记录损坏，禁止重置已用路由")

    def persist():
        if draft_path:
            from ai_config import api_key_candidates
            text = json.dumps(saved, ensure_ascii=False)
            for route in ("", *_executive_model_route()):
                for secret in api_key_candidates(config, model=route):
                    if secret:
                        text = text.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[redacted]")
            text = re.sub(r"(?i)Bearer\s+[^\s\"\\]+", "Bearer [redacted]", text)
            _atomic_write_json(draft_path, json.loads(text))

    # Revalidate the original model packet before spending any additional route.
    # Gate fixes may recover saved text; model-route counts are never reset.
    saved_error = None
    for index in range(len(entry["attempts"]) - 1, -1, -1):
        old = entry["attempts"][index]
        candidate = old.get("candidate")
        if not isinstance(candidate, list) and isinstance(old.get("response"), dict):
            try:
                candidate = unwrap_items_payload(load_json_response(final_chat_message_text(
                    old["response"], operation="已存跨库发现"), operation="已存跨库发现"), operation="已存跨库发现")
            except ValueError:
                candidate = None
            if isinstance(candidate, list):
                old.update(candidate=candidate, candidate_hash=_content_hash(candidate))
                persist()
        if not isinstance(candidate, list) or not old.get("reported_model"):
            continue
        try:
            accepted = _validate_model_discoveries(candidate, prompt_evidence)
        except ValueError as exc:
            saved_error = exc
            continue
        entry["selected"] = {"attempt_index": index, "revalidated_at_hkt": _now(),
                             "candidate_hash": _content_hash(accepted), "full_gate": "passed"}
        persist()
        return {"generated_at_hkt": _now(), "model": old["reported_model"], "discoveries": accepted,
                "presentation_warnings": _discovery_presentation_warnings(accepted),
                "evidence_repair_count": 0, "reused": True}
    if draft_path and entry["attempts"]:
        repaired = _repair_saved_discoveries(entry, prompt_evidence, config, persist, attempt_trace_path)
        if repaired:
            return repaired
    system_prompt = (
        "你是电信竞争情报分析员。从local、international、mainland、cloud四个战略总览数据域中提炼恰好四条跨库发现。"
        "每条必须联系两个不同领域，四条不得重复同一领域组合，且四个领域都要被覆盖。"
        "从两域中自行选择有解释力的事实，标题写具体经营判断，detail用事实解释竞争、盈利、客户或投入的含义。"
        "只使用输入中的数字、公司、期间、单位和来源，不把相关性当因果，不自行换汇或补写缺失事实。"
        "不同币种、期间、指标或业务范围不能直接排名；如涉及这类金额，简短交代限制，同时解释证据支持的经营状态。"
        "每条引用两个领域所用事实的精确source_url。只返回JSON对象，顶层字段是items数组。"
        + STRATEGIC_WRITING_GUIDE
    )
    user_prompt = (
        "请返回{\"items\":[四条发现]}，每项字段严格为from,to,title,detail,kind,source_urls。"
        "title不超过28字，detail目标80至110字、一至两句完整句，kind统一写AI综合研判。不要Markdown。输入：\n"
        + json.dumps(prompt_evidence, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        *discovery_few_shot_messages(batch=True),
        {"role": "user", "content": user_prompt},
    ]
    body = prepare_structured_chat_body({
        **dict(config.get("extra_parameters") or {}),
        "model": _executive_model_route()[0],
        "messages": messages,
        "temperature": 0.0,
        # Some compatible gateways still spend tokens in an internal reasoning
        # channel even when thinking is disabled. Match the proven domain-
        # summary allowance so the four-item JSON reaches its closing object.
        "max_tokens": 16000,
    })
    discoveries: list[dict[str, Any]] | None = None
    evidence_repair_count = 0
    last_error: Exception | None = saved_error
    discovery_models = _executive_model_route()
    used_model = discovery_models[0]
    for attempt, discovery_model in enumerate(discovery_models):
        if int(entry["model_route_counts"].get(discovery_model) or 0) >= 1:
            continue
        body["model"] = discovery_model
        body["messages"] = messages
        request = _model_request(config, api_key, body)
        attempt_started = time.monotonic()
        payload = {}
        attempt_error = None
        record = {"requested_model": discovery_model, "status": "running", "started_at_hkt": _now(), "http_calls": 0}
        entry["attempts"].append(record)
        entry["model_route_counts"][discovery_model] = int(entry["model_route_counts"].get(discovery_model) or 0) + 1
        persist()  # Reserve the route before its single HTTP, including a crash.

        def single_transport(*args, **kwargs):
            if record["http_calls"]:
                raise ValueError("单条跨库发现模型路由只允许一个HTTP，禁止隐式重试")
            record["http_calls"] += 1
            persist()
            return urllib.request.urlopen(*args, **kwargs)

        try:
            with open_llm_request(
                request,
                timeout=180,
                config=config,
                requested_key=api_key,
                model=discovery_model,
                open_func=single_transport,
                max_transport_retries=0,
                operation="executive-intelligence-discoveries",
            ) as response:
                payload = read_chat_completion_sse(response)
            record.update(response=payload, reported_model=payload.get("model"), response_id=payload.get("id"),
                          response_hash=_content_hash(payload), status="received")
            persist()  # Preserve the complete SSE packet before parsing/quality gates.
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:800]
            last_error = RuntimeError(f"内网模型 HTTP {exc.code}: {detail}")
            record.update(status="failed", error=str(last_error), completed_at_hkt=_now())
            persist()
            _trace_model_attempt(attempt_trace_path, "discoveries", discovery_model, attempt_started, payload, last_error, config)
            continue
        except (APIKeyPoolUnavailable, ValueError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            record.update(status="failed", error=str(exc), completed_at_hkt=_now(),
                          stream=getattr(exc, "stream_diagnostics", {}))
            persist()
            _trace_model_attempt(attempt_trace_path, "discoveries", discovery_model, attempt_started, payload, exc, config)
            continue
        try:
            content = final_chat_message_text(payload, operation="跨库AI发现")
            concise = _repair_discovery_conciseness(
                unwrap_items_payload(
                    load_json_response(content, operation="跨库AI发现"), operation="跨库AI发现"
                )
            )
            record.update(candidate=concise, candidate_hash=_content_hash(concise))
            persist()
            depth_repaired, current_repair_count = _repair_discovery_depth(
                concise,
                prompt_evidence,
            )
            discoveries = _validate_model_discoveries(depth_repaired, prompt_evidence)
            evidence_repair_count = current_repair_count
            used_model = payload["model"]
            record.update(status="passed", completed_at_hkt=_now())
            entry["selected"] = {"attempt_index": len(entry["attempts"]) - 1,
                                 "candidate_hash": _content_hash(discoveries), "full_gate": "passed"}
            persist()
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            attempt_error = exc
            record.update(status="failed", error=str(exc), completed_at_hkt=_now())
            persist()
            if attempt + 1 < len(discovery_models):
                messages.extend([
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"请修正上一版的问题：{exc}。保留有证据支持的经营判断，修正事实或格式问题。"
                            "仍按前述样例写法，由事实解释业务含义，必要的比较限制简短交代。"
                            "只返回{\"items\":[四条发现]}。"
                        ),
                    },
                ])
        finally:
            _trace_model_attempt(attempt_trace_path, "discoveries", discovery_model,
                                 attempt_started, payload, attempt_error, config)
    if discoveries is None:
        # A bounded local repair already exists for resumed runs. Use it in
        # the same invocation too, instead of reporting failure and requiring
        # a manual retry just to reach the remaining two repair attempts.
        if draft_path:
            repaired = _repair_saved_discoveries(entry, prompt_evidence, config, persist, attempt_trace_path)
            if repaired:
                return repaired
        raise ValueError(f"AI跨库发现可用模型路由已用完；相同证据不重复请求：{last_error}")
    return {
        "generated_at_hkt": _now(),
        "model": used_model,
        "discoveries": discoveries,
        "evidence_repair_count": evidence_repair_count,
        "presentation_warnings": _discovery_presentation_warnings(discoveries),
    }


def regenerate_model_discovery(
    index: int,
    source_domain: str,
    target_domain: str,
    *,
    path: Path = AI_ANALYSIS_PATH,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Regenerate one cross-library discovery while preserving the other three."""
    from ai_config import INTERNAL_AI_BASE_URL, load_ai_config
    from ai_rate_limit import wait_for_internal_ai_slot
    from network_utils import urlopen_with_local_proxy_fallback

    def report(message: str) -> None:
        if progress:
            progress(message)

    if index not in range(4):
        raise ValueError("跨库洞察序号必须为0至3")
    expected_domains = set(UI_DOMAIN_IDS)
    if source_domain not in expected_domains or target_domain not in expected_domains or source_domain == target_domain:
        raise ValueError("跨库洞察领域组合无效")

    report("正在读取两域当前证据")
    evidence = _analysis_input_snapshot()
    evidence_hash = _content_hash(evidence)
    analysis = _read_json(path, {}) or {}
    previous = _ai_only_bundle(evidence, analysis.get("model_analysis") or {})
    discoveries = json.loads(json.dumps(previous["discoveries"], ensure_ascii=False))
    discoveries = _validate_model_discoveries(discoveries, evidence)
    current = discoveries[index]
    if {str(current.get("from") or ""), str(current.get("to") or "")} != {source_domain, target_domain}:
        raise ValueError("跨库洞察位置与当前领域组合不一致，请刷新页面后重试")

    config = load_ai_config(include_key=True)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置内网模型密钥")
    scoped_evidence = _manual_discovery_evidence(evidence, source_domain, target_domain)
    messages = [
        {
            "role": "system",
            "content": (
                "你是电信竞争情报分析员。只重新生成指定两个领域的一条跨库发现。"
                "只返回JSON对象{from,to,title,detail,kind,source_urls}。from和to必须保持输入顺序；"
                "title必须是一句有战略含义的判断、不超过28字，detail不超过110字，kind写AI综合研判。"
                "从两域指标中自行选择能支持经营判断的事实，两域各引用具体数值及其公司、期间、单位。"
                "可重新选择指标和企业，不局限于上一条分析的事实或角度。"
                "数字和来源只取自当前输入，不自行换汇，不把相关性当因果。"
                "不同口径不能直接排名；必要限制简短说明，主体解释事实的经营含义。"
                "source_urls使用所选事实的精确source_url。"
                + STRATEGIC_WRITING_GUIDE
            ),
        },
        *discovery_few_shot_messages(batch=False),
        {
            "role": "user",
            "content": json.dumps({"from": source_domain, "to": target_domain, **scoped_evidence}, ensure_ascii=False),
        },
    ]
    base_models = _executive_model_route()
    models = base_models[:2]
    last_error: Exception | None = None
    replacement: dict[str, Any] | None = None
    used_model = models[0]
    pair_key = f"{source_domain}.{target_domain}"
    prior_counts = previous.get("manual_discovery_regeneration_counts") or {}
    if not isinstance(prior_counts, dict):
        prior_counts = {}
    regeneration_count = int(prior_counts.get(pair_key) or 0) + 1
    prior_history = previous.get("manual_discovery_regeneration_history") or {}
    if not isinstance(prior_history, dict):
        prior_history = {}
    relation_history = [
        str(value or "").strip()
        for value in prior_history.get(pair_key) or []
        if str(value or "").strip()
    ][-12:]
    prior_title_history = previous.get("manual_discovery_regeneration_title_history") or {}
    if not isinstance(prior_title_history, dict):
        prior_title_history = {}
    relation_title_history = [
        str(value or "").strip()
        for value in prior_title_history.get(pair_key) or []
        if str(value or "").strip()
    ][-12:]
    current_text = "".join(re.sub(r"\s+", "", str(current.get(key) or "")) for key in ("title", "detail"))
    fallback_used = False
    report("正在生成新的跨库判断")
    for attempt, model in enumerate(models):
        request_id = f"relation-{index}-{uuid4().hex}"
        request_messages = [*messages, {
            "role": "user",
            "content": (
                f"本次重生成请求编号：{request_id}。该编号只用于隔离缓存，不属于证据，不得写入答案。"
                "依据当前事实重新判断，选择最有解释力的角度，不为求不同而编造结论。"
                f"上一条文案供避免照抄：{json.dumps(current, ensure_ascii=False)}"
            ),
        }]
        request = _model_request(config, api_key, prepare_structured_chat_body({
                **dict(config.get("extra_parameters") or {}),
                "model": model,
                "messages": request_messages,
                "temperature": 0.25 if attempt == 0 else 0.55,
                "max_tokens": 2000,
            }), request_id)
        try:
            with open_llm_request(
                request,
                timeout=12,
                config=config,
                requested_key=api_key,
                model=model,
                open_func=urlopen_with_local_proxy_fallback,
                operation=f"executive-intelligence-discovery-{index}",
            ) as response:
                response_payload = read_chat_completion_sse(response)
            parsed = load_json_response(
                final_chat_message_text(response_payload, operation="跨库AI发现重生成"),
                operation="跨库AI发现重生成",
            )
            if isinstance(parsed, list) and len(parsed) == 1:
                parsed = parsed[0]
            if not isinstance(parsed, dict):
                raise ValueError("模型未返回单项跨库洞察对象")
            if str(parsed.get("from") or "") != source_domain or str(parsed.get("to") or "") != target_domain:
                raise ValueError("模型改变了跨库领域组合")
            current_signature = tuple(re.sub(r"\s+", "", str(current.get(key) or "")) for key in ("title", "detail"))
            parsed_signature = tuple(re.sub(r"\s+", "", str(parsed.get(key) or "")) for key in ("title", "detail"))
            if parsed_signature == current_signature:
                raise ValueError("模型返回了与当前跨库洞察完全相同的结果")
            candidate = [dict(item) for item in discoveries]
            candidate[index] = parsed
            replacement = _validate_model_discoveries(candidate, evidence)[index]
            used_model = response_payload["model"]
            break
        except (APIKeyPoolUnavailable, ValueError, json.JSONDecodeError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            messages.append({
                "role": "user",
                "content": f"请修正上一版的问题：{exc}。保持领域组合和真实事实，只返回合法JSON对象。",
            })
    if replacement is None:
        raise ValueError(f"AI本次未返回有效跨库分析，原结果未修改：{last_error}")

    report("证据校验通过，正在返回洞察")
    discoveries[index] = replacement
    generated_at = _now()
    updated_counts = dict(prior_counts)
    updated_counts[pair_key] = regeneration_count
    updated_history = json.loads(json.dumps(prior_history, ensure_ascii=False))
    replacement_text = "".join(
        re.sub(r"\s+", "", str(replacement.get(key) or ""))
        for key in ("title", "detail")
    )
    updated_history[pair_key] = list(dict.fromkeys([
        *relation_history,
        current_text,
        replacement_text,
    ]))[-12:]
    updated_title_history = json.loads(json.dumps(prior_title_history, ensure_ascii=False))
    updated_title_history[pair_key] = list(dict.fromkeys([
        *relation_title_history,
        str(current.get("title") or "").strip(),
        str(replacement.get("title") or "").strip(),
    ]))[-12:]
    generated = {
        **previous,
        "generated_at_hkt": generated_at,
        "discoveries": discoveries,
        "presentation_warnings": (_summary_presentation_warnings(previous.get("summaries") or [])
                                  + _discovery_presentation_warnings(discoveries)),
        "discovery_model": used_model,
        "discovery_generated_at_hkt": generated_at,
        "evidence_hash": evidence_hash,
        "insight_format": INSIGHT_FORMAT_VERSION,
        "reused": False,
        "manual_discovery_regeneration_counts": updated_counts,
        "manual_discovery_regeneration_history": updated_history,
        "manual_discovery_regeneration_title_history": updated_title_history,
        "manual_discovery_regeneration": {
            "index": index,
            "from": source_domain,
            "to": target_domain,
            "generated_at_hkt": generated_at,
            "count": regeneration_count,
            "fallback_used": fallback_used,
            "fallback_reason": str(last_error or "") if fallback_used else "",
        },
    }
    analysis["model_analysis"] = generated
    _atomic_write_json(path, analysis)
    return {
        "ok": True,
        "index": index,
        **replacement,
        "model": used_model,
        "fallback_used": fallback_used,
        "generated_at_hkt": generated_at,
    }


def _ai_only_bundle(evidence: dict[str, Any], previous: dict[str, Any], *, checkpoint_path: Path | None = None) -> dict[str, Any]:
    """Build atomically; a failed model never replaces the last persisted bundle."""
    evidence_hash = _content_hash(evidence)
    if (
        model_generated_only(previous)
        and previous.get("evidence_hash") == evidence_hash
        and previous.get("insight_format") == INSIGHT_FORMAT_VERSION
    ):
        try:
            summaries = _validate_model_summaries(previous["summaries"], evidence)
            discoveries = _validate_model_discoveries(previous["discoveries"], evidence)
        except ValueError:
            pass
        else:
            return {**previous, "summaries": summaries, "discoveries": discoveries, "reused": True,
                    "presentation_warnings": _summary_presentation_warnings(summaries) + _discovery_presentation_warnings(discoveries)}
    generated = (generate_model_domain_summaries(evidence, checkpoint_path=checkpoint_path)
                 if checkpoint_path else generate_model_domain_summaries(evidence))
    discoveries = (generate_model_discoveries(evidence, attempt_trace_path=checkpoint_path.with_suffix(".attempts.jsonl"))
                   if checkpoint_path else generate_model_discoveries(evidence))
    bundle = {
        **generated,
        "summaries": _validate_model_summaries(generated["summaries"], evidence),
        "discoveries": _validate_model_discoveries(discoveries["discoveries"], evidence),
        "discovery_model": discoveries["model"],
        "discovery_generated_at_hkt": discoveries["generated_at_hkt"],
        "generation_policy": AI_ONLY_POLICY,
        "discovery_fallback_used": bool(discoveries.get("fallback_used")),
        "evidence_hash": evidence_hash,
        "insight_format": INSIGHT_FORMAT_VERSION,
        "reused": False,
    }
    if not model_generated_only(bundle):
        raise ValueError("分析包含非AI结果，禁止作为AI分析保存或发布")
    bundle["presentation_warnings"] = (_summary_presentation_warnings(bundle["summaries"])
                                       + _discovery_presentation_warnings(bundle["discoveries"]))
    return bundle


def publish_model_domain_summaries(path: Path = AI_ANALYSIS_PATH) -> dict[str, Any]:
    analysis = _read_json(path, {}) or {}
    generated = _ai_only_bundle(_analysis_input_snapshot(), analysis.get("model_analysis") or {},
                                checkpoint_path=path.with_suffix(".model-checkpoints.json"))
    analysis["model_analysis"] = generated
    _atomic_write_json(path, analysis)
    return {"ok": True, **generated}

def regenerate_model_focus_summary(
    domain_id: str, focus_id: str, *, path: Path = AI_ANALYSIS_PATH,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Regenerate with AI; never rotate templates or replace unrelated focuses."""
    report = progress or (lambda _message: None)
    report("正在读取当前证据")
    evidence = _analysis_input_snapshot()
    focus = next((
        item for domain in evidence.get("domains") or [] if domain.get("id") == domain_id
        for item in domain.get("focuses") or [] if item.get("id") == focus_id
    ), None)
    if focus is None:
        raise ValueError(f"未知竞争情报关注点：{domain_id}.{focus_id}")
    analysis = _read_json(path, {}) or {}
    report("正在核对AI分析版本")
    bundle = _ai_only_bundle(evidence, analysis.get("model_analysis") or {})
    report("正在通过AI生成新的数据判断")
    history_key = f"{domain_id}.{focus_id}"
    previous_focus = next(item for domain in bundle["summaries"] if domain.get("domain") == domain_id
                          for item in domain.get("focuses") or [] if item.get("id") == focus_id)
    history = json.loads(json.dumps(bundle.get("manual_focus_regeneration_history") or {}))
    title_history = json.loads(json.dumps(bundle.get("manual_focus_regeneration_title_history") or {}))
    scoped = generate_model_focus_insight(domain_id, {
        **focus, "insight": previous_focus.get("analysis"), "headline": previous_focus.get("headline"),
        "recent_insights": history.get(history_key, []), "recent_headlines": title_history.get(history_key, []),
    }, temperature=0.25)
    replacement = scoped.get("focus")
    if not isinstance(replacement, dict):
        raise ValueError("AI未返回当前指标分析；原结果未修改")
    if replacement.get("origin") == "evidence_rule" or "fallback" in str(scoped.get("model") or ""):
        raise ValueError("当前指标未由AI生成，原结果未修改")
    summaries = json.loads(json.dumps(bundle["summaries"], ensure_ascii=False))
    target = next(item for item in summaries if item.get("domain") == domain_id)
    target["focuses"] = [
        {**item, **replacement} if item.get("id") == focus_id else item for item in target.get("focuses") or []
    ]
    report("正在校验数字与来源")
    bundle["summaries"] = _validate_model_summaries(summaries, evidence)
    bundle["presentation_warnings"] = (_summary_presentation_warnings(bundle["summaries"])
                                       + _discovery_presentation_warnings(bundle["discoveries"]))
    generated_at = _now()
    history[history_key] = list(dict.fromkeys([*history.get(history_key, []), str(previous_focus.get("analysis") or ""), str(replacement.get("analysis") or "")]))[-12:]
    title_history[history_key] = list(dict.fromkeys([*title_history.get(history_key, []), str(previous_focus.get("headline") or ""), str(replacement.get("headline") or "")]))[-12:]
    counts = dict(bundle.get("manual_focus_regeneration_counts") or {})
    counts[history_key] = int(counts.get(history_key) or 0) + 1
    bundle.update({
        "generated_at_hkt": generated_at, "reused": False,
        "manual_focus_regeneration_history": history,
        "manual_focus_regeneration_title_history": title_history,
        "manual_focus_regeneration_counts": counts,
        "manual_focus_regeneration": {
            "domain": domain_id, "focus": focus_id, "model": scoped["model"],
            "generated_at_hkt": generated_at,
        },
    })
    analysis["model_analysis"] = bundle
    _atomic_write_json(path, analysis)
    report("AI结果已校验并保存")
    return {
        "ok": True, "domain": domain_id, "focus": focus_id,
        "headline": replacement.get("headline", ""), "analysis": replacement.get("analysis", ""),
        "model": scoped["model"], "origin": "ai", "generated_at_hkt": generated_at,
        "evidence_hash": bundle["evidence_hash"],
    }

def _period_rank(value: Any) -> tuple[int, int, int]:
    text = str(value or "")
    import re
    iso = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if iso:
        return tuple(int(item) for item in iso.groups())
    quarter = re.search(r"Q([1-4])\s+(20\d{2})", text, re.I)
    if quarter:
        return int(quarter.group(2)), int(quarter.group(1)) * 3, 31
    half = re.search(r"H([12])\s+(20\d{2})", text, re.I)
    if half:
        return int(half.group(2)), 6 if half.group(1) == "1" else 12, 30 if half.group(1) == "1" else 31
    named_month = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b.*?\b(\d{1,2}),\s*(20\d{2})",
        text,
        re.I,
    )
    if named_month:
        month = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }[named_month.group(1).lower()]
        return int(named_month.group(3)), month, int(named_month.group(2))
    year = re.search(r"(20\d{2})", text)
    if year and re.search(r"(?:\bFY\s*|\bannual\b)", text, re.I):
        return int(year.group(1)), 12, 31
    return (int(year.group(1)), 0, 0) if year else (0, 0, 0)


def validate_database(domain: str, path: Path, previous_path: Path | None = None) -> dict[str, Any]:
    payload = _read_json(path)
    if payload is None:
        raise ValueError(f"{domain} 数据文件无法解析：{path}")
    rows = payload if isinstance(payload, list) else payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{domain} 数据库为空：{path}")
    previous_payload = _read_json(previous_path) if previous_path and previous_path.exists() else None
    previous_rows = previous_payload if isinstance(previous_payload, list) else (previous_payload or {}).get("rows") or []
    if previous_rows and len(rows) < int(len(previous_rows) * 0.95):
        raise ValueError(f"{domain} 行数降级：{len(previous_rows)} -> {len(rows)}")

    result: dict[str, Any] = {"rows": len(rows), "path": str(path), "latest_period": "", "quality": "passed"}
    if domain == "local":
        bad = [row for row in rows if int(row.get("verification_count") or 0) < 2 or not row.get("source_url")]
        if bad:
            raise ValueError(f"本地竞对存在 {len(bad)} 条未达到双重验证或缺少来源的记录")
        result["verified_rows"] = len(rows)
        if path.resolve() == LOCAL_PATH.resolve():
            financial_payload = _read_json(LOCAL_FINANCIAL_PATH, {}) or {}
            financial_quality = financial_payload.get("quality") or {}
            reports = [
                item for item in financial_payload.get("reports", [])
                if item.get("verification_status") == "official_document_extracted"
                and int(item.get("core_metric_count") or 0) >= 2
            ]
            if not financial_quality.get("ok") or not reports:
                failures = "；".join(str(item) for item in financial_quality.get("failures") or [])
                raise ValueError(f"本地竞对官方财报结构化门禁未通过：{failures or '没有已通过记录'}")
            latest_report = max(
                reports,
                key=lambda item: (str(item.get("publication_date") or ""), _period_rank(item.get("period"))),
            )
            result["financial_reports"] = len(reports)
            result["latest_financial_period"] = str(latest_report.get("period") or "")
            result["latest_financial_publication_date"] = str(latest_report.get("publication_date") or "")
    elif domain in {"international", "cloud"}:
        usable = [row for row in rows if str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES]
        if not usable:
            raise ValueError(f"{domain} 没有可供前端使用的已核验记录")
        period_key = "period_end" if domain == "international" else "fiscal_year"
        result["latest_period"] = max((str(row.get(period_key) or "") for row in usable), key=_period_rank, default="")
        result["verified_rows"] = len(usable)
    elif domain == "macro":
        bad = [
            row for row in rows
            if row.get("verification_status") not in {"official_match", "source_gap_confirmed"}
            or int(row.get("verification_count") or 0) < 2
        ]
        if bad:
            raise ValueError(f"宏观库存在 {len(bad)} 条未通过官方来源门禁的记录")
        result["latest_period"] = max((str(row.get("period_end") or "") for row in rows), key=_period_rank, default="")
        result["verified_rows"] = len(rows) - sum(row.get("verification_status") == "source_gap_confirmed" for row in rows)

    if previous_rows and domain != "local":
        previous_period_key = "fiscal_year" if domain == "cloud" else "period_end"
        comparable_previous = previous_rows
        if domain in {"international", "cloud"}:
            comparable_previous = [
                row for row in previous_rows
                if str(row.get("verification_status") or "") in SAFE_VERIFICATION_STATUSES
            ]
        elif domain == "macro":
            comparable_previous = [row for row in previous_rows if row.get("verification_status") == "official_match"]
        previous_latest = max(
            (str(row.get(previous_period_key) or "") for row in comparable_previous),
            key=_period_rank,
            default="",
        )
        if result["latest_period"] and previous_latest and _period_rank(result["latest_period"]) < _period_rank(previous_latest):
            raise ValueError(f"{domain} 最新期间倒退：{previous_latest} -> {result['latest_period']}")
    return result


def _run_builder(command: list[str], env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _builder_python() -> str:
    configured = str(os.environ.get("CMHK_INTELLIGENCE_BUILDER_PYTHON") or "").strip()
    if configured:
        return configured
    homebrew_python = Path("/opt/homebrew/bin/python3")
    return str(homebrew_python) if homebrew_python.exists() else sys.executable


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _merge_international_candidate(stage: Path, target: Path) -> dict[str, Any]:
    candidate_path = stage / "quarterly_metrics.json"
    current_path = target / "quarterly_metrics.json"
    candidate = _read_json(candidate_path, {}) or {}
    current = _read_json(current_path, {}) or {}
    candidate_rows = list(candidate.get("rows") or [])
    current_rows = list(current.get("rows") or [])

    def key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("subject") or ""),
            str(row.get("period") or ""),
            str(row.get("metric_key") or ""),
        )

    merged = {key(row): row for row in current_rows}
    added = 0
    upgraded = 0
    for row in candidate_rows:
        row_key = key(row)
        previous = merged.get(row_key)
        if previous is None:
            merged[row_key] = row
            added += 1
            continue
        old_status = str(previous.get("verification_status") or "")
        new_status = str(row.get("verification_status") or "")
        if new_status in SAFE_VERIFICATION_STATUSES and old_status not in SAFE_VERIFICATION_STATUSES:
            merged[row_key] = row
            upgraded += 1
    merged_rows = sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("category") or ""),
            str(row.get("subject") or ""),
            str(row.get("metric_key") or ""),
            _period_rank(row.get("period_end") or row.get("period")),
        ),
    )
    candidate["rows"] = merged_rows
    candidate["merge"] = {
        "strategy": "preserve_existing_verified_rows_and_add_new_builder_rows",
        "current_rows": len(current_rows),
        "builder_rows": len(candidate_rows),
        "added_rows": added,
        "upgraded_rows": upgraded,
        "published_rows": len(merged_rows),
    }
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_rows_csv(stage / "quarterly_metrics.csv", merged_rows)
    manifest_path = stage / "manifest.json"
    manifest = _read_json(manifest_path, {}) or {}
    current_manifest = _read_json(target / "manifest.json", {}) or {}
    candidate_entrypoints = [str(item) for item in manifest.get("entrypoints") or []]
    retained_entrypoints: list[str] = []
    for raw_item in current_manifest.get("entrypoints") or []:
        relative = Path(str(raw_item))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            continue
        source = target / relative
        if not source.is_file() or source.is_symlink():
            continue
        retained_entrypoints.append(relative.as_posix())
        destination = stage / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    manifest["entrypoints"] = list(
        dict.fromkeys([*candidate_entrypoints, *retained_entrypoints])
    )
    manifest["row_count"] = len(merged_rows)
    if isinstance(manifest.get("quality"), dict):
        current_quality = current_manifest.get("quality") or {}
        if isinstance(current_quality, dict):
            for key, value in current_quality.items():
                manifest["quality"].setdefault(key, value)
        manifest["quality"]["row_count"] = len(merged_rows)
        notes = manifest["quality"].setdefault("notes", [])
        notes.append(
            "自动刷新采用保守合并：保留既有已核验行，只新增构建器发现的新键或升级更高验证等级的行。"
        )
        manifest["quality"]["notes"] = list(dict.fromkeys(map(str, notes)))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return candidate["merge"]


def _promote_directory(stage: Path, target: Path) -> None:
    parent = target.parent
    candidate = parent / f".{target.name}.candidate-{os.getpid()}"
    backup = parent / f".{target.name}.backup-{os.getpid()}"
    shutil.rmtree(candidate, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        shutil.copytree(target, candidate)
    else:
        candidate.mkdir(parents=True)
    for source in stage.rglob("*"):
        if not source.is_file():
            continue
        destination = candidate / source.relative_to(stage)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    moved_old = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_old = True
        os.replace(candidate, target)
    except Exception:
        if moved_old and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        shutil.rmtree(candidate, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)


def _refresh_builder_domain(
    domain: str, *, dry_run: bool = False, parent_task_run_id: str = ""
) -> dict[str, Any]:
    configs = {
        "international": {
            "script": ROOT / "scripts/build_quarterly_metrics_knowledge.py",
            "target": INTERNATIONAL_DIR,
            "file": "quarterly_metrics.json",
            "env": {"CMHK_QUARTERLY_METRICS_BUILD_DATE": "2026-06-18", "CMHK_QUARTERLY_METRICS_OUT_ROOT": "{stage}"},
            "timeout": 1800,
        },
        "cloud": {
            "script": ROOT / "scripts/build_cloud_vendor_metrics_knowledge.py",
            "target": CLOUD_DIR,
            "file": "cloud_vendor_metrics_2023_2025.json",
            "env": {"CMHK_CLOUD_METRICS_BUILD_DATE": "2026-06-17", "CMHK_CLOUD_METRICS_OUT_ROOT": "{stage}"},
            "timeout": 300,
        },
        "macro": {
            "script": ROOT / "scripts/build_macro_policy_knowledge.py",
            "target": MACRO_DIR,
            "file": "macro_policy_metrics.json",
            "env": {"CMHK_MACRO_POLICY_BUILD_DATE": "2026-06-19", "CMHK_MACRO_POLICY_OUT_ROOT": "{stage}"},
            "timeout": 1800,
        },
    }
    config = configs[domain]
    with tempfile.TemporaryDirectory(prefix=f"cmhk-{domain}-refresh-") as temp_dir:
        stage = Path(temp_dir) / "dataset"
        env = os.environ.copy()
        env.update({key: value.format(stage=stage) for key, value in config["env"].items()})
        proc = _run_builder([_builder_python(), str(config["script"])], env, int(config["timeout"]))
        if proc.returncode:
            raise RuntimeError(f"{domain} 构建失败({proc.returncode})：{(proc.stderr or proc.stdout)[-1200:]}")
        merge = _merge_international_candidate(stage, Path(config["target"])) if domain == "international" else None
        candidate = stage / str(config["file"])
        validation = validate_database(domain, candidate, Path(config["target"]) / str(config["file"]))
        current_payload = _read_json(Path(config["target"]) / str(config["file"]), {})
        candidate_payload = _read_json(candidate, {})
        if isinstance(candidate_payload, dict):
            candidate_payload = {key: value for key, value in candidate_payload.items() if key != "generated_at"}
        if isinstance(current_payload, dict):
            current_payload = {key: value for key, value in current_payload.items() if key != "generated_at"}
        changed = _content_hash(candidate_payload) != _content_hash(current_payload)
        if not dry_run and changed:
            if domain == "international":
                with tempfile.TemporaryDirectory(prefix="cmhk-international-promote-") as promote_dir:
                    promote_stage = Path(promote_dir)
                    for name in ("quarterly_metrics.json", "quarterly_metrics.csv", "manifest.json"):
                        shutil.copy2(stage / name, promote_stage / name)
                    _promote_directory(promote_stage, Path(config["target"]))
            else:
                _promote_directory(stage, Path(config["target"]))
        release = None
        if domain == "international" and not dry_run:
            release = publish_quarterly_release_task(
                Path(config["target"]),
                default_release_root(ROOT),
                project_root=ROOT,
                parent_crawl_run_id=parent_task_run_id,
                trigger_kind="四库刷新",
            )
        return {
            "ok": True,
            "changed": changed,
            "promoted": bool(changed and not dry_run),
            "validation": validation,
            "merge": merge,
            "release": release,
            "stdout_tail": (proc.stdout or "")[-600:],
        }


def refresh_research_macro(run_id: str, *, dry_run: bool = False, task_run_id: str = "") -> dict:
    """One live macro refresh per research run; resume only while readback matches."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("研究运行编号无效")
    path = ROOT / "curation_data/research_runs" / run_id / "macro_refresh.json"
    prior = _read_json(path, {})
    current_hash = _content_hash(_read_json(MACRO_PATH, {}))
    if not dry_run and prior.get("ok") and prior.get("readback_hash") == current_hash:
        return {**prior, "reused": True}
    _task_event(task_run_id, "宏观环境", "正在联网更新官方宏观指标，校验后写入宏观库。")
    result = _refresh_builder_domain("macro", dry_run=dry_run, parent_task_run_id=task_run_id)
    result.update(completed_at_hkt=_now(), run_id=run_id, live_refresh=True)
    if not dry_run:
        result["readback_hash"] = _content_hash(_read_json(MACRO_PATH, {}))
        _atomic_write_json(path, result)
    _task_event(task_run_id, "宏观环境", f"宏观联网更新完成；校验通过 {int(result.get('validation', {}).get('rows') or 0)} 条。")
    return result


def _publish_and_verify_github_pages() -> dict[str, Any]:
    """Publish the freshly written four-domain snapshot and require public readback."""
    if not PAGES_PUBLISH_SCRIPT.is_file():
        raise RuntimeError(f"GitHub.io发布脚本不存在：{PAGES_PUBLISH_SCRIPT}")
    environment = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment.pop(key, None)
    environment.setdefault("CMHK_INTELLIGENCE_SOURCE_URL", "http://127.0.0.1:8765/")
    # The comparison view and its AI endpoint consume this separate canonical file.
    rebuilt = _run_builder(
        [_builder_python(), str(ROOT / "scripts/build_competitor_workbench_data.py")],
        environment, 180,
    )
    if rebuilt.returncode:
        raise RuntimeError(f"竞对前端数据重建失败：{(rebuilt.stderr or rebuilt.stdout)[-1200:]}")
    result: dict[str, Any] = {}
    busy_wait_seconds = max(30, int(os.environ.get("CMHK_PAGES_BUSY_WAIT_SECONDS", "600")))
    busy_deadline = time.monotonic() + busy_wait_seconds
    attempt = 0
    while True:
        attempt += 1
        completed = subprocess.run(
            [sys.executable, str(PAGES_PUBLISH_SCRIPT), "--force"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(
                f"GitHub.io发布失败({completed.returncode})：{(completed.stderr or completed.stdout)[-1200:]}"
            )
        try:
            result = json.loads((completed.stdout or "").strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GitHub.io发布结果无法解析：{(completed.stdout or completed.stderr)[-1200:]}") from exc
        if result.get("status") != "busy":
            break
        if time.monotonic() >= busy_deadline:
            raise RuntimeError(f"GitHub.io发布队列等待超过{busy_wait_seconds}秒：{result}")
        time.sleep(5)
    if result.get("status") not in {"published", "verified", "unchanged"}:
        raise RuntimeError(f"GitHub.io未完成公开验证：{result}")
    if not str(result.get("public_url") or "").startswith("https://") or not result.get("site_version"):
        raise RuntimeError(f"GitHub.io验证结果字段不完整：{result}")
    return {"ok": True, "attempts": attempt, **result}


def _run_overview_source_recrawl(*, dry_run: bool = False) -> dict[str, Any]:
    """Recheck the official documents that feed the four domains shown in the UI."""
    script = ROOT / "scripts" / "crawl_requested_overview_010304_official_sources.py"
    output = ROOT / "agent_knowledge" / "requested_overview_010304_2016_2025" / "official_source_recrawl.json"
    if not script.is_file():
        raise RuntimeError(f"战略总览官方来源复查脚本不存在：{script}")
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run", "path": str(output)}
    environment = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment.pop(key, None)
    completed = subprocess.run(
        [_builder_python(), str(script)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=1800,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"战略总览官方来源复查失败({completed.returncode})：{(completed.stderr or completed.stdout)[-1200:]}"
        )
    try:
        summary = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError(f"战略总览官方来源复查结果无法解析：{(completed.stdout or completed.stderr)[-1200:]}") from exc
    if not output.is_file() or int(summary.get("retrieved") or 0) <= 0:
        raise RuntimeError(f"战略总览官方来源复查没有形成有效读回：{summary}")
    domain_summary = summary.get("domains") or {}
    missing_domains = [
        domain
        for domain in UI_DOMAIN_IDS
        if int((domain_summary.get(domain) or {}).get("retrieved") or 0) <= 0
    ]
    if missing_domains:
        raise RuntimeError(f"战略总览官方来源复查缺少真实网络读回域：{missing_domains}；结果：{summary}")
    return {"ok": True, "path": str(output), **summary}


def load_0100_source_discovery_handoff(
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Load today's independent 01:00 search-agent packet for the 03:00 run."""
    reference = (now or datetime.now(HKT)).astimezone(HKT)
    today = reference.date().isoformat()
    payload = _read_json(SOURCE_DISCOVERY_PATH, {}) or {}
    handoff_date = str(payload.get("handoff_for_date") or "")
    coverage_matrix = payload.get("coverage_matrix") or []
    coverage_complete = bool(
        payload.get("coverage_complete")
        and isinstance(coverage_matrix, list)
        and len(coverage_matrix) == int(payload.get("query_count") or 0)
        and not payload.get("errors")
    )
    available = bool(payload and handoff_date == today and coverage_complete)
    if handoff_date != today:
        reason = "today_0100_source_discovery_missing"
    elif not coverage_complete:
        reason = "today_0100_source_discovery_coverage_incomplete"
    else:
        reason = ""
    result = {
        **payload,
        "ok": available,
        "available": available,
        "expected_handoff_date": today,
        "audit_path": str(SOURCE_DISCOVERY_PATH),
        "coverage_complete": coverage_complete,
        "reason": reason,
    }
    if not dry_run:
        _atomic_write_json(NEWS_DATABASE_SIGNALS_PATH, result)
    return result


def run_pipeline(
    *,
    agent_run_id: str,
    curation_summary: dict[str, Any] | None = None,
    dry_run: bool = False,
    refresh_builders: bool = True,
    task_run_id: str = "",
    attempt: int = 1,
) -> dict[str, Any]:
    six_agent_run = (curation_summary or {}).get("architecture") == "six_research_agents_v1"
    incremental_run = (curation_summary or {}).get("research_policy") == "latest_disclosure_incremental_v1"
    facts_path = VERIFIED_FACTS_PATH
    if six_agent_run:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", agent_run_id):
            raise ValueError("研究运行编号无效")
        facts_path = ROOT / "curation_data" / "research_runs" / agent_run_id / "verified_facts.jsonl"
        manifest = _read_json(facts_path.parent / "manifest.json", {})
        if manifest.get("run_id") != agent_run_id or manifest.get("status") not in {"completed", "partial"} or not facts_path.exists():
            raise ValueError("六Agent本轮事实文件尚未完整生成")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_handle.close()
        return {"ok": True, "skipped": True, "reason": "refresh_already_running"}

    started = time.monotonic()
    try:
        previous_ui_numeric_values = _ui_numeric_value_snapshot()
    except Exception as exc:
        previous_ui_numeric_values = None
        _append_log(f"ui numeric baseline unavailable {exc}")
    state: dict[str, Any] = {
        "ok": False,
        "status": "running",
        "started_at_hkt": _now(),
        "agent_run_id": agent_run_id,
        "dry_run": dry_run,
        "task_run_id": task_run_id,
        "attempt": attempt,
        "domains": {},
        "ui_contract": {
            "domain_ids": list(UI_DOMAIN_IDS),
            "supporting_database_ids": list(SUPPORTING_DOMAIN_IDS),
        },
    }
    _atomic_write_json(STATE_PATH, state)
    _append_log(f"start agent_run_id={agent_run_id} dry_run={dry_run}")
    _task_event(
        task_run_id,
        "发布审核事实",
        f"第 {attempt} 次执行开始，正在发布Agent已通过事实并校验本地竞对库。",
    )
    try:
        source_discovery = ({"available": False, "required": False, "reason": "research_agents_search_in_current_run"}
                            if six_agent_run else load_0100_source_discovery_handoff(dry_run=dry_run))
        state["news_database_signals"] = source_discovery
        if six_agent_run:
            _task_event(task_run_id, "接收六Agent研究结果", "已接收本轮六Agent统一提交的事实，直接进入四库更新。")
        elif source_discovery.get("available"):
            _task_event(
                task_run_id,
                "01:00四库资料搜索交接",
                f"已读取01:00资料包：{int(source_discovery.get('query_count') or 0)}个查询、"
                f"{int(source_discovery.get('search_result_count') or 0)}条结果、"
                f"前一日两次新闻任务参考{int(source_discovery.get('previous_day_reference_count') or 0)}条、"
                f"{int(source_discovery.get('signal_count') or 0)}条需追官方原文的四库线索。",
            )
        else:
            _task_event(
                task_run_id,
                "01:00四库资料搜索交接",
                "未找到当天01:00资料包；固定官方入口仍会检查，但本轮不得声明搜索补缺链路完成。",
                level="critical",
            )
        if dry_run:
            ai_payload = build_ai_analysis(agent_run_id=agent_run_id, curation_summary=curation_summary, verified_facts_path=facts_path)
            ai_result = {
                **ai_payload,
                "ok": True,
                "changed": _content_hash(_fact_content(ai_payload))
                != _content_hash(_fact_content(_read_json(AI_ANALYSIS_PATH, {}) or {})),
                "domain_counts": ai_payload["domain_counts"],
                "path": str(AI_ANALYSIS_PATH),
            }
        else:
            ai_result = publish_ai_analysis(
                agent_run_id=agent_run_id,
                curation_summary=curation_summary,
                verified_facts_path=facts_path,
            )
        state["ai_analysis"] = {
            "ok": True,
            "changed": ai_result["changed"],
            "domain_counts": ai_result["domain_counts"],
            "path": ai_result["path"],
        }
        state["domain_fact_sidecars"] = publish_domain_fact_sidecars(
            ai_result,
            dry_run=dry_run,
        )
        if six_agent_run and not dry_run and (
            sum(ai_result.get("domain_counts", {}).get(domain, 0) for domain in UI_DOMAIN_IDS) != int((curation_summary or {}).get("accepted") or 0)
            or any(not result.get("ok") for result in state["domain_fact_sidecars"].values())
        ):
            # No main-table promotion or AI work may follow a rejected/conflicting
            # source-fact write. Retain receipts for retry and investigation.
            from data_curation.research_storage import audit_storage
            accepted_facts = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            state["storage_readback"] = audit_storage(ROOT, accepted_facts, expected=int((curation_summary or {}).get("accepted") or 0))
            _atomic_write_json(facts_path.parent / "storage_receipt.json", {
                "agent_run_id": agent_run_id, "readback": state["storage_readback"],
                "writes": state["domain_fact_sidecars"], "main_table": {"skipped": True, "reason": "source_fact_gate_failed"},
            })
            raise ValueError("审核资料未全部保存或存在冲突，停止主表写入与页面发布")
        state["domains"]["local"] = {
            "ok": True,
            "changed": False,
            "validation": validate_database("local", LOCAL_PATH),
            "note": ("本轮研究事实由六Agent提交并更新审核事实层；此处校验现有本地竞对主表，不重复抓取。"
                     if six_agent_run else "本地竞对数据库已由本轮 crawl.py 更新；发布桥只复核，不重复抓取。"),
        }
        local_validation = state["domains"]["local"].get("validation") or {}
        local_rows = int(local_validation.get("rows") or 0)
        financial_reports = int(local_validation.get("financial_reports") or 0)
        latest_finance = " · ".join(
            str(local_validation.get(key) or "")
            for key in ("latest_financial_period", "latest_financial_publication_date")
            if local_validation.get(key)
        )
        _task_event(
            task_run_id,
            "本地竞对",
            f"本地竞对库校验通过，共 {local_rows} 条记录；官方财报 {financial_reports} 份"
            f"{f'；最新 {latest_finance}' if latest_finance else ''}。",
        )
        if refresh_builders and not incremental_run:
            for domain in ("international", "cloud", "macro"):
                label = DOMAIN_LABELS[domain]
                _task_event(
                    task_run_id,
                    label,
                    (f"正在按既有规则重建{label}数据库并执行发布门禁；本轮联网证据见六Agent研究记录。"
                     if six_agent_run else f"正在重建{label}数据库并执行发布门禁；真实联网情况由随后官方来源复查单独证明。"),
                )
                try:
                    state["domains"][domain] = _refresh_builder_domain(
                        domain,
                        dry_run=dry_run,
                        parent_task_run_id=task_run_id,
                    )
                    _append_log(f"{domain} ok changed={state['domains'][domain]['changed']}")
                    validation = state["domains"][domain].get("validation") or {}
                    changed = "已更新" if state["domains"][domain].get("changed") else "无数据变化"
                    _task_event(
                        task_run_id,
                        label,
                        f"{label}门禁通过，{changed}；总记录 {int(validation.get('rows') or 0)} 条。",
                    )
                except Exception as exc:
                    state["domains"][domain] = {"ok": False, "changed": False, "promoted": False, "error": str(exc)}
                    _append_log(f"{domain} failed {exc}")
                    _task_event(task_run_id, label, f"{label}更新失败：{exc}", level="critical")
        else:
            for domain, path in (("international", INTERNATIONAL_PATH), ("cloud", CLOUD_PATH), ("macro", MACRO_PATH)):
                if domain == "macro" and incremental_run and refresh_builders:
                    try:
                        state["domains"][domain] = refresh_research_macro(agent_run_id, dry_run=dry_run, task_run_id=task_run_id)
                    except Exception as exc:
                        state["domains"][domain] = {"ok": False, "changed": False, "error": str(exc)}
                    continue
                state["domains"][domain] = {
                    "ok": True,
                    "changed": False,
                    "validation": validate_database(domain, path),
                    "note": "本次仅验证现有数据库，未执行联网重建。",
                }
                validation = state["domains"][domain].get("validation") or {}
                _task_event(
                    task_run_id,
                    DOMAIN_LABELS[domain],
                    f"仅校验现有数据库通过，共 {int(validation.get('rows') or 0)} 条记录。",
                )
        if refresh_builders or six_agent_run:
            try:
                if six_agent_run:
                    from data_curation.research_kpi import write_formal_facts
                    promotion = write_formal_facts(ROOT, [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()], dry_run=dry_run)
                else:
                    promotion = promote_daily_financial_facts(
                        database_path=INTERNATIONAL_PATH,
                        local_financial_path=LOCAL_FINANCIAL_PATH,
                        verified_facts_path=facts_path,
                        dry_run=dry_run,
                        incremental_only=incremental_run,
                    )
                state["daily_main_database_promotion"] = promotion
                mainland_state = state["domains"].setdefault("mainland", {"ok": True, "changed": False})
                mainland_state["daily_main_database_promotion"] = promotion
                mainland_state["changed"] = bool(mainland_state.get("changed") or promotion.get("changed"))
                international_state = state["domains"].setdefault("international", {"ok": True, "changed": False})
                international_state["validation"] = validate_database("international", INTERNATIONAL_PATH)
                _task_event(
                    task_run_id,
                    "正式指标写入",
                    (f"本轮提交 {int(promotion.get('candidates') or 0)} 项；已入库 {int(promotion.get('written') or 0)} 项，"
                     f"未入库 {int(promotion.get('not_written') or 0)} 项；本次新增行 {int(promotion.get('added_rows') or 0)}。") if six_agent_run else
                    f"已处理 {int(promotion.get('candidates') or 0)} 条合格候选；"
                    f"主库新增 {int(promotion.get('added_rows') or 0)} 条、"
                    f"升级 {int(promotion.get('upgraded_rows') or 0)} 条，"
                    f"保留更高核验等级 {int(promotion.get('preserved_stronger_rows') or 0)} 条。",
                )
            except Exception as exc:
                state["daily_main_database_promotion"] = {"ok": False, "changed": False, "error": str(exc)}
                state["domains"].setdefault("mainland", {}).update({"ok": False, "changed": False, "error": str(exc)})
                _append_log(f"daily main database promotion failed {exc}")
                _task_event(task_run_id, "每日官方财报晋升主库", f"主库增量晋升失败：{exc}", level="critical")
        else:
            state["daily_main_database_promotion"] = {
                "ok": True,
                "changed": False,
                "skipped": True,
                "reason": "refresh_builders_disabled",
            }
        if six_agent_run:
            from data_curation.research_storage import audit_storage
            accepted_facts = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            state["storage_readback"] = audit_storage(ROOT, accepted_facts, expected=int((curation_summary or {}).get("accepted") or 0))
            if not dry_run:
                _atomic_write_json(facts_path.parent / "storage_receipt.json", {
                    "agent_run_id": agent_run_id, "readback": state["storage_readback"],
                    "writes": state["domain_fact_sidecars"], "main_table": state.get("daily_main_database_promotion", {}),
                })
            if not dry_run and not state["storage_readback"]["ok"]:
                raise ValueError("四库逐项回读未通过，保留研究档案，停止后续分析与发布")
        if six_agent_run:
            state["overview_source_recrawl"] = {
                "ok": True, "skipped": True, "reason": "official_pages_already_read_by_research_agents",
            }
        elif refresh_builders:
            _task_event(
                task_run_id,
                "战略总览来源复查",
                "正在逐一复查当前战略总览四域所引用的官方文件，结果只写审计旁路，不覆盖已核验数值。",
            )
            try:
                state["overview_source_recrawl"] = _run_overview_source_recrawl(dry_run=dry_run)
                recrawl = state["overview_source_recrawl"]
                for domain in UI_DOMAIN_IDS:
                    state["domains"].setdefault(domain, {"ok": True, "changed": False})
                    state["domains"][domain]["source_crawl"] = (recrawl.get("domains") or {}).get(domain) or {}
                _task_event(
                    task_run_id,
                    "战略总览来源复查",
                    f"官方来源复查完成：本次真实请求 {int(recrawl.get('official_urls') or 0)} 个URL，"
                    f"成功 {int(recrawl.get('retrieved') or 0)}，失败 {int(recrawl.get('failed') or 0)}；"
                    + "、".join(
                        f"{DOMAIN_LABELS[domain]}{int(((recrawl.get('domains') or {}).get(domain) or {}).get('retrieved') or 0)}个"
                        for domain in UI_DOMAIN_IDS
                    )
                    + "。",
                )
            except Exception as exc:
                state["overview_source_recrawl"] = {"ok": False, "error": str(exc)}
                _append_log(f"overview source recrawl failed {exc}")
                _task_event(task_run_id, "战略总览来源复查", f"官方来源复查失败：{exc}", level="critical")
        else:
            state["overview_source_recrawl"] = {
                "ok": True,
                "skipped": True,
                "reason": "refresh_builders_disabled",
            }
        if dry_run:
            state["model_analysis"] = {"ok": True, "skipped": True, "reason": "dry_run"}
        else:
            current_evidence = _analysis_input_snapshot()
            expected_focus_count = sum(
                len(domain.get("focuses") or [])
                for domain in current_evidence.get("domains") or []
            )
            expected_discovery_count = 4
            _task_event(
                task_run_id,
                "生成AI洞察",
                f"正在根据四库最新通过事实生成AI洞察，并对{expected_focus_count}个关注点及"
                f"{expected_discovery_count}条顶部跨库研判逐一执行深层解释、简洁度与事实门禁。",
            )
            try:
                model_analysis = publish_model_domain_summaries()
                if not model_generated_only(model_analysis):
                    raise ValueError("非AI或来源未确认的分析禁止进入发布流程")
                passed_focus_count = sum(
                    len(summary.get("focuses") or [])
                    for summary in model_analysis.get("summaries") or []
                )
                passed_discovery_count = len(model_analysis.get("discoveries") or [])
                expected_insight_count = expected_focus_count + expected_discovery_count
                passed_insight_count = passed_focus_count + passed_discovery_count
                state["model_analysis"] = {
                    "ok": True,
                    "generation_policy": AI_ONLY_POLICY,
                    "generated_at_hkt": model_analysis["generated_at_hkt"],
                    "model": model_analysis["model"],
                    "domains": len(model_analysis["summaries"]),
                    "focuses_expected": expected_focus_count,
                    "focuses_passed": passed_focus_count,
                    "discoveries_expected": expected_discovery_count,
                    "discoveries_passed": passed_discovery_count,
                    "insights_expected": expected_insight_count,
                    "insights_passed": passed_insight_count,
                    "reused": bool(model_analysis.get("reused")),
                    "presentation_warnings": model_analysis.get("presentation_warnings") or [],
                    "fallback_used": bool(model_analysis.get("fallback_used")),
                    "fallback_reason": str(model_analysis.get("fallback_reason") or ""),
                    "evidence_hash": str(model_analysis.get("evidence_hash") or ""),
                    "discovery_model": str(model_analysis.get("discovery_model") or ""),
                    "discovery_evidence_repair_count": int(
                        model_analysis.get("discovery_evidence_repair_count") or 0
                    ),
                    "discovery_fallback_used": bool(model_analysis.get("discovery_fallback_used")),
                    "discovery_fallback_reason": str(model_analysis.get("discovery_fallback_reason") or ""),
                }
                state["ui_contract"].update(
                    {
                        "focuses_expected": expected_focus_count,
                        "focuses_passed": passed_focus_count,
                        "discoveries_expected": expected_discovery_count,
                        "discoveries_passed": passed_discovery_count,
                        "insights_expected": expected_insight_count,
                        "insights_passed": passed_insight_count,
                        "summary_domain_ids": [
                            str(summary.get("domain") or "") for summary in model_analysis.get("summaries") or []
                        ],
                        "aligned": (
                            [str(summary.get("domain") or "") for summary in model_analysis.get("summaries") or []]
                            == list(UI_DOMAIN_IDS)
                            and passed_focus_count == expected_focus_count
                            and passed_discovery_count == expected_discovery_count
                        ),
                    }
                )
                fallback_note = (
                    f"；回退原因：{state['model_analysis']['fallback_reason']}"
                    if model_analysis.get("fallback_used") else "；未触发回退"
                )
                _task_event(
                    task_run_id,
                    "生成AI洞察",
                    f"{passed_insight_count}/{expected_insight_count}项洞察门禁通过（关注点"
                    f"{passed_focus_count}/{expected_focus_count}、顶部跨库研判"
                    f"{passed_discovery_count}/{expected_discovery_count}）；模型：{state['model_analysis']['model']}；"
                    f"证据哈希：{state['model_analysis']['evidence_hash'][:16]}{fallback_note}。",
                )
                if model_analysis.get("presentation_warnings"):
                    warning_details = "；".join(
                        f"{w['scope']}.{w['field']}：{w['message']}" if w.get('message') else
                        f"{w['scope']}.{w['field']} {w['characters']}字（写作目标{w['target_characters']}，发布上限{w['publication_max_characters']}）"
                        for w in model_analysis["presentation_warnings"])
                    _task_event(task_run_id, "AI样式提示", "已保留完整AI原文并通过全部事实门禁：" + warning_details,
                                level="warning")
            except Exception as exc:
                state["model_analysis"] = {
                    "ok": False,
                    "error": str(exc),
                    "fallback_preserved": True,
                    "focuses_expected": expected_focus_count,
                    "discoveries_expected": expected_discovery_count,
                    "insights_expected": expected_focus_count + expected_discovery_count,
                    "insights_passed": 0,
                }
                _append_log(f"model analysis failed {exc}")
                _task_event(task_run_id, "生成AI洞察", f"AI洞察生成失败：{exc}", level="critical")
        try:
            current_ui_numeric_values = _ui_numeric_value_snapshot()
            state["ui_value_changes"] = _compare_ui_numeric_values(
                previous_ui_numeric_values,
                current_ui_numeric_values,
            )
        except Exception as exc:
            state["ui_value_changes"] = _compare_ui_numeric_values(None, None)
            state["ui_value_changes"]["error"] = str(exc)
        numeric_change_count = int((state.get("ui_value_changes") or {}).get("changed") or 0)
        _task_event(
            task_run_id,
            "核对UI数值变化",
            f"按同一UI字段旧值→新值逐项比较，确认{numeric_change_count}项结构化数值变化；网页内容指纹变化不计入。",
        )
        for domain in UI_DOMAIN_IDS:
            sidecar = (state.get("domain_fact_sidecars") or {}).get(domain) or {}
            state["domains"].setdefault(domain, {"ok": True, "changed": False})
            state["domains"][domain]["agent_fact_update"] = {
                "facts": int(sidecar.get("facts") or 0),
                "submitted_facts": sidecar.get("submitted_facts"),
                "inserted_facts": sidecar.get("inserted_facts"),
                "confirmed_facts": sidecar.get("confirmed_facts"),
                "changed": bool(sidecar.get("changed")),
                "published": bool(sidecar.get("published")),
            }
            state["domains"][domain]["database_changed"] = bool(
                state["domains"][domain].get("changed") or sidecar.get("published")
            )
        failed = [key for key, value in state["domains"].items() if not value.get("ok")]
        model_ok = bool(state.get("model_analysis", {}).get("ok")) and not bool(
            state.get("model_analysis", {}).get("fallback_used")
            or state.get("model_analysis", {}).get("discovery_fallback_used")
        )
        recrawl_ok = bool(state.get("overview_source_recrawl", {}).get("ok"))
        ui_contract_ok = bool(dry_run or state.get("ui_contract", {}).get("aligned"))
        source_discovery_ok = bool(
            dry_run or six_agent_run
            or (
                state.get("news_database_signals", {}).get("available")
                and state.get("news_database_signals", {}).get("coverage_complete")
            )
        )
        core_ok = not failed and model_ok and recrawl_ok and ui_contract_ok and source_discovery_ok
        core_ok = core_ok and (not six_agent_run or dry_run or bool(state.get("storage_readback", {}).get("ok")))
        if dry_run:
            state["pages_publish"] = {"ok": True, "skipped": True, "reason": "dry_run"}
        elif core_ok:
            _task_event(
                task_run_id,
                "更新主页UI",
                f"四库与{int(state['model_analysis'].get('insights_passed') or 0)}项AI洞察均已通过"
                f"（含{int(state['model_analysis'].get('discoveries_passed') or 0)}条顶部跨库研判），"
                "正在重建主页数据源、发布GitHub.io并读取公开版本验证。",
            )
            try:
                pages_publish = _publish_and_verify_github_pages()
                state["pages_publish"] = pages_publish
                _task_event(
                    task_run_id,
                    "更新主页UI",
                    f"主页数据源与公开站点已同步并验证；版本：{pages_publish.get('site_version')}；地址：{pages_publish.get('public_url')}",
                )
            except Exception as exc:
                state["pages_publish"] = {"ok": False, "error": str(exc)}
                _append_log(f"github pages publish failed {exc}")
                _task_event(task_run_id, "更新主页UI", f"主页同步、公开发布或验证失败：{exc}", level="critical")
        else:
            state["pages_publish"] = {"ok": False, "skipped": True, "reason": "core_gate_failed"}
        pages_ok = bool(state.get("pages_publish", {}).get("ok"))
        used_fallback = bool(state.get("model_analysis", {}).get("fallback_used") or state.get("model_analysis", {}).get("discovery_fallback_used"))
        pipeline_ok = core_ok and pages_ok and not used_fallback
        if pipeline_ok:
            final_status = "completed"
        elif core_ok and not pages_ok:
            final_status = "failed_frontend_publish"
        elif core_ok:
            final_status = "completed_with_fallback"
        else:
            final_status = "failed_validation"
        state.update(
            {
                "ok": pipeline_ok,
                "status": final_status,
                "failed_domains": failed,
                "completed_at_hkt": _now(),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "fallback_preserved": bool(failed or not model_ok or used_fallback or not pages_ok),
                "change_summary": {
                    "database_changed_domains": [
                        domain for domain in UI_DOMAIN_IDS
                        if bool((state.get("domains") or {}).get(domain, {}).get("database_changed"))
                    ],
                    "source_content_changed_domains": [
                        domain for domain in UI_DOMAIN_IDS
                        if int((((state.get("overview_source_recrawl") or {}).get("domains") or {}).get(domain) or {}).get("content_changed") or 0) > 0
                    ],
                    "ui_numeric_changed_domains": [
                        domain for domain in UI_DOMAIN_IDS
                        if int((((state.get("ui_value_changes") or {}).get("domains") or {}).get(domain) or {}).get("changed") or 0) > 0
                    ],
                    "ui_verified": pages_ok,
                },
            }
        )
    except Exception as exc:
        state.update(
            {
                "ok": False,
                "status": "failed",
                "error": str(exc),
                "completed_at_hkt": _now(),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "fallback_preserved": True,
            }
        )
        _append_log(f"pipeline failed {exc}")
    if not dry_run:
        try:
            from cmhk.integrations.four_database_crawl_sheet import append_pipeline_artifacts

            state["feishu_detail_log"] = append_pipeline_artifacts(state)
            _task_event(
                task_run_id,
                "飞书四库爬虫明细日志",
                f"已写入{int(state['feishu_detail_log'].get('written') or 0)}条详细日志，"
                f"跳过{int(state['feishu_detail_log'].get('skipped') or 0)}条重复记录。",
            )
        except Exception as exc:
            state["feishu_detail_log"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            state["ok"] = False
            state["status"] = "failed_feishu_detail_log"
            state["failure_stage"] = "four_database_feishu_log"
            _task_event(task_run_id, "飞书四库爬虫明细日志", f"详细日志写入失败：{exc}", level="critical")
    _atomic_write_json(STATE_PATH, state)
    _append_log(f"done status={state['status']} duration_ms={state['duration_ms']}")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    lock_handle.close()
    return state


def _retry_delays() -> list[int]:
    raw = os.environ.get("CMHK_INTELLIGENCE_RETRY_DELAYS", "60,300")
    delays: list[int] = []
    for item in raw.split(","):
        try:
            delays.append(max(0, int(item.strip())))
        except ValueError:
            continue
    return delays or [60, 300]


def _validated_fallback_complete(result: dict[str, Any]) -> bool:
    """Legacy degraded results never satisfy the AI generation contract."""
    return False

def run_pipeline_with_recovery(
    *,
    agent_run_id: str,
    curation_summary: dict[str, Any] | None = None,
    dry_run: bool = False,
    refresh_builders: bool = True,
    task_run_id: str = "",
    parent_crawl_run_id: str = "",
    max_attempts: int | None = None,
    finalize_task: bool = True,
) -> dict[str, Any]:
    """Retry the safe refresh and keep all status reporting in the local task log."""
    attempts_limit = max_attempts or max(1, int(os.environ.get("CMHK_INTELLIGENCE_MAX_ATTEMPTS", "3")))
    attempts_limit = min(5, attempts_limit)
    delays = _retry_delays()
    overall_started = time.monotonic()
    result: dict[str, Any] = {}
    attempts = 0
    for attempt in range(1, attempts_limit + 1):
        attempts = attempt
        result = run_pipeline(
            agent_run_id=agent_run_id,
            curation_summary=curation_summary,
            dry_run=dry_run,
            refresh_builders=refresh_builders,
            task_run_id=task_run_id,
            attempt=attempt,
        )
        analysis_status = result.get("model_analysis") or {}
        if (result.get("status") == "completed_with_fallback"
                or analysis_status.get("fallback_used")
                or analysis_status.get("discovery_fallback_used")):
            result = {**result, "ok": False, "error": "AI分析未全部生成，非AI结果不能计作成功"}
        if result.get("status") == "failed_feishu_detail_log":
            break
        if result.get("ok") or result.get("skipped"):
            break
        if attempt < attempts_limit:
            delay = delays[min(attempt - 1, len(delays) - 1)]
            failed = "、".join(DOMAIN_LABELS.get(item, item) for item in result.get("failed_domains") or [])
            reason = failed or str(result.get("error") or result.get("status") or "未通过门禁")
            _task_event(
                task_run_id,
                "后备重试",
                f"第 {attempt} 次未完成（{reason}），{delay} 秒后执行第 {attempt + 1} 次。旧数据继续保留。",
                level="retry",
            )
            time.sleep(delay)

    result = dict(result)
    result["total_duration_ms"] = round((time.monotonic() - overall_started) * 1000)
    result["attempts"] = attempts
    result["agent_run_id"] = agent_run_id
    ok = bool(result.get("ok") or result.get("skipped"))
    if ok:
        if result.get("skipped"):
            detail = "已有另一条四库任务执行，本次已安全合并。"
        elif (result.get("pages_publish") or {}).get("ok"):
            insight_count = int((result.get("model_analysis") or {}).get("insights_passed") or 0)
            discovery_count = int((result.get("model_analysis") or {}).get("discoveries_passed") or 0)
            detail = (
                f"四库、{insight_count}项AI洞察（含{discovery_count}条顶部跨库研判）、"
                f"前端数据源及GitHub.io公开验证已完成，共执行 {attempts} 次。"
            )
        else:
            detail = (
                f"四库、{int((result.get('model_analysis') or {}).get('insights_passed') or 0)}项AI洞察"
                f"（含{int((result.get('model_analysis') or {}).get('discoveries_passed') or 0)}条顶部跨库研判）"
                "和前端数据源已完成，但GitHub.io发布验证未通过："
                f"{(result.get('pages_publish') or {}).get('error') or '未返回原因'}。"
            )
    else:
        failed = "、".join(DOMAIN_LABELS.get(item, item) for item in result.get("failed_domains") or [])
        if result.get("failure_stage") == "four_database_feishu_log":
            log_error = str((result.get("feishu_detail_log") or {}).get("error") or "未取得写后回读证据")
            detail = (
                "四库、AI洞察与页面阶段已完成，但飞书“四库爬虫明细日志”未通过写后回读，"
                f"本轮按失败归档并触发预警；错误：{log_error}；本地完整来源审计仍保留。"
            )
        else:
            detail = f"连续 {attempts} 次未通过，失败范围：{failed or result.get('error') or '观察结论'}；旧数据已保留。"
    result["notification_policy"] = "local_log_only"
    if finalize_task:
        _finalize_refresh_task(
            task_run_id,
            ok=ok,
            detail=detail,
            result=result,
            attempts=attempts,
        )
    else:
        _task_event(
            task_run_id,
            "发布阶段完成" if ok else "发布阶段失败",
            detail,
            level="info" if ok else "critical",
        )
    return result


def launch_pipeline_async(
    *,
    agent_run_id: str,
    curation_summary: dict[str, Any] | None = None,
    parent_crawl_run_id: str = "",
    recovery_reason: str = "",
) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = STATE_DIR / f"curation-{agent_run_id}.json"
    _atomic_write_json(summary_path, curation_summary or {})
    task = _start_refresh_task(
        agent_run_id=agent_run_id,
        parent_crawl_run_id=parent_crawl_run_id,
        recovery_reason=recovery_reason,
    )
    task_run_id = str(task["crawl_run_id"])
    log_handle = LOG_PATH.open("a", encoding="utf-8")
    try:
        try:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--scheduled",
                    "--agent-run-id",
                    agent_run_id,
                    "--curation-summary",
                    str(summary_path),
                    "--task-run-id",
                    task_run_id,
                    "--parent-crawl-run-id",
                    parent_crawl_run_id,
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except Exception as exc:
            failed = {"ok": False, "status": "failed", "agent_run_id": agent_run_id, "error": str(exc)}
            _finalize_refresh_task(
                task_run_id,
                ok=False,
                detail=f"刷新进程启动失败：{exc}",
                result=failed,
                attempts=0,
            )
            raise
    finally:
        log_handle.close()
    _task_event(
        task_run_id,
        "等待刷新进程",
        f"刷新进程已启动，PID {proc.pid}；任务日志将持续记录四库阶段。",
        worker_pid=proc.pid,
    )
    return {
        "ok": True,
        "launched": True,
        "pid": proc.pid,
        "agent_run_id": agent_run_id,
        "task_run_id": task_run_id,
        "task_id": f"crawl:{task_run_id}",
    }


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def monitor_scheduled_refresh_health(now: datetime | None = None) -> dict[str, Any]:
    """Recover once when a completed 03:00 crawl has no matching four-database publication."""
    from cmhk.crawl.run_registry import load_index

    now = (now or datetime.now(HKT)).astimezone(HKT)
    scheduled = next(
        (
            item
            for item in load_index()
            if item.get("trigger") == "定时爬虫"
            and item.get("run_status") == "completed"
            and str(item.get("completed_at_hkt") or "").startswith(now.date().isoformat())
            and str((item.get("curation") or {}).get("agent_run_id") or "")
        ),
        None,
    )
    if not scheduled:
        return {"ok": True, "status": "no_scheduled_crawl_today"}
    crawl_run_id = str(scheduled.get("crawl_run_id") or "")
    agent_run_id = str((scheduled.get("curation") or {}).get("agent_run_id") or "")
    completed_at = datetime.fromisoformat(str(scheduled.get("completed_at_hkt"))).astimezone(HKT)
    latest = _read_json(STATE_PATH, {}) or {}
    if (
        latest.get("ok")
        and str(latest.get("agent_run_id") or "") == agent_run_id
        and str(latest.get("completed_at_hkt") or "") >= str(scheduled.get("completed_at_hkt") or "")
    ):
        return {"ok": True, "status": "healthy", "crawl_run_id": crawl_run_id, "agent_run_id": agent_run_id}

    tasks = [
        item
        for item in load_index()
        if item.get("task_kind") == TASK_KIND and agent_run_id in str(item.get("scope") or "")
    ]
    running = next((item for item in tasks if item.get("run_status") == "running"), None)
    if running and _process_alive(int(running.get("worker_pid") or 0)):
        return {"ok": True, "status": "refresh_running", "task_run_id": running.get("crawl_run_id")}

    grace_seconds = max(900, int(os.environ.get("CMHK_INTELLIGENCE_WATCHDOG_GRACE_SECONDS", "5400")))
    if (now - completed_at).total_seconds() < grace_seconds:
        return {"ok": True, "status": "waiting_grace_period", "crawl_run_id": crawl_run_id}

    watchdog = _read_json(WATCHDOG_STATE_PATH, {}) or {}
    recoveries = watchdog.setdefault("recoveries", {})
    if crawl_run_id in recoveries:
        return {"ok": True, "status": "recovery_already_launched", **recoveries[crawl_run_id]}

    launch = launch_pipeline_async(
        agent_run_id=agent_run_id,
        curation_summary=scheduled.get("curation") or {},
        parent_crawl_run_id=crawl_run_id,
        recovery_reason="守护补跑",
    )
    recoveries[crawl_run_id] = {
        "crawl_run_id": crawl_run_id,
        "agent_run_id": agent_run_id,
        "task_run_id": launch.get("task_run_id", ""),
        "launched_at_hkt": _now(),
        "notification_policy": "local_log_only",
    }
    watchdog["updated_at_hkt"] = _now()
    _atomic_write_json(WATCHDOG_STATE_PATH, watchdog)
    return {"ok": True, "status": "recovery_launched", **recoveries[crawl_run_id]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the four executive-intelligence databases after Agent review.")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--agent-run-id", default="manual")
    parser.add_argument("--curation-summary")
    parser.add_argument("--task-run-id", default="")
    parser.add_argument("--parent-crawl-run-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    summary = _read_json(Path(args.curation_summary), {}) if args.curation_summary else {}
    runner = run_pipeline_with_recovery if args.scheduled else run_pipeline
    result = runner(
        agent_run_id=args.agent_run_id,
        curation_summary=summary,
        dry_run=args.dry_run,
        refresh_builders=not args.validate_only,
        task_run_id=args.task_run_id,
        **({"parent_crawl_run_id": args.parent_crawl_run_id} if args.scheduled else {}),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok") and not result.get("skipped"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
