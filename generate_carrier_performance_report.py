from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.text.paragraph import Paragraph

from company_metrics import build_company_metrics_payload


ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "carrier_performance_template.docx"
DATA_PATH = ROOT / "carrier_performance_data.json"
SOURCE_PATH = ROOT / "carrier_performance_sources.json"
CACHE_PATH = ROOT / "carrier_performance_cache.json"
MARKET_CACHE_PATH = ROOT / "carrier_market_cache.json"
FEISHU_MIRROR_PATH = ROOT / "carrier_performance_feishu.json"
FEISHU_SYNC_SCRIPT = ROOT / "sync_carrier_performance_feishu.py"
VERIFIED_FIELDS_PATH = ROOT / "carrier_performance_verified_fields.json"
PERFORMANCE_USAGE_AUDIT_PATH = ROOT / "carrier_performance_fact_usage.json"
RESULTS_DIR = ROOT / "results"
COMPANIES = ["中国移动", "中国电信", "中国联通", "中国铁塔"]
FIELD_ORDER = [
    ("dividend", "派息"),
    ("capex", "资本开支"),
    ("strategy", "战略升级"),
    ("broker", "券商观点"),
    ("market", "市场反应"),
]
METRICS = [
    "营业收入（亿元）",
    "主营业务收入（亿元）",
    "EBITDA(亿元)",
    "归母净利润（亿元）",
    "净利率",
    "资本开支（亿元）",
    "资本开支2026年计划（亿元）",
    "移动用户数（亿户）",
    "5G网络用户数（亿户）",
    "5G网络渗透率",
]
SUMMARY_TABLE_HEADERS = ["主体", "最新披露", "收益", "EBITDA / 利润", "资本开支", "派息"]
COMPANY_FACT_ALIASES = {
    "HKT / csl / 1O1O": {"HKT", "csl", "1O1O"},
    "3HK / Hutchison": {"3HK", "Hutchison"},
    "i-CABLE": {"i-CABLE", "iCable"},
}
MAINLAND_SUMMARY_ROWS = {
    "中国移动": ["中国移动", "2026Q1", "2665亿元", "归母净利润293亿元", "2025年1509亿元；2026年计划1366亿元", "全年每股5.27港元"],
    "中国电信": ["中国电信", "2026Q1", "2025年5296亿元", "2025年EBITDA 1439亿元", "2025年804亿元", "全年每股0.2720元"],
    "中国联通": ["中国联通", "2026Q1", "2026Q1经营收入1028.24亿元", "2026Q1归母净利润48.85亿元", "2025年542亿元；2026年计划约500亿元", "全年每股0.417元"],
    "中国铁塔": ["中国铁塔", "2026Q1 KPI", "2025年1004.11亿元", "2025年归母净利润116亿元", "2025年294.86亿元", "全年每股0.45789元"],
}


def dated_output_path(now: datetime | None = None) -> Path:
    value = now or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    base_name = f"{value.month}月{value.day}日运营商业绩摘要"
    candidate = ROOT / f"{base_name}.docx"
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = ROOT / f"{base_name} ({counter}).docx"
        if not candidate.exists():
            return candidate
        counter += 1


def remove_paragraph(paragraph) -> None:
    element = paragraph._element
    element.getparent().remove(element)


def replace_paragraph_text(paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def replace_body_text(paragraph, text: str) -> None:
    field_labels = {label for _, label in FIELD_ORDER}
    label = text.split("：", 1)[0] if "：" in text else ""
    if label not in field_labels:
        replace_paragraph_text(paragraph, text)
        return

    content = text[len(label) + 1 :]
    if not paragraph.runs:
        paragraph.add_run(f"{label}：").bold = True
        paragraph.add_run(content)
        return

    paragraph.runs[0].text = f"{label}："
    paragraph.runs[0].bold = True
    if len(paragraph.runs) == 1:
        paragraph.add_run(content)
    else:
        paragraph.runs[1].text = content
        paragraph.runs[1].bold = False
        for run in paragraph.runs[2:]:
            run.text = ""


def cloned_paragraph_after(paragraph) -> Paragraph:
    new_p = deepcopy(paragraph._p)
    paragraph._p.addnext(new_p)
    return Paragraph(new_p, paragraph._parent)


def run_at(paragraph, index: int):
    while len(paragraph.runs) <= index:
        paragraph.add_run("")
    return paragraph.runs[index]


def copy_run_font(target, source=None, *, bold=None) -> None:
    if source is not None:
        target.font.name = source.font.name
        target.font.size = source.font.size
    if bold is not None:
        target.bold = bold


def clear_paragraph_numbering(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    if p_pr.numPr is not None:
        p_pr.remove(p_pr.numPr)


def set_plain_paragraph(paragraph, text: str, *, bold: bool | None = None) -> None:
    base = paragraph.runs[0] if paragraph.runs else None
    first = run_at(paragraph, 0)
    first.text = text
    copy_run_font(first, base, bold=bold)
    for run in paragraph.runs[1:]:
        run.text = ""


def set_template_item(paragraph, index: int, label: str, content: str, *, broker_header: bool = False) -> None:
    clear_paragraph_numbering(paragraph)
    base = paragraph.runs[0] if paragraph.runs else None
    if broker_header:
        set_plain_paragraph(paragraph, f"{index}. {label}：{content}", bold=True)
        return

    label_run = run_at(paragraph, 0)
    label_run.text = f"{index}. {label}："
    copy_run_font(label_run, base, bold=True)
    content_run = run_at(paragraph, 1)
    content_run.text = content
    copy_run_font(content_run, base, bold=False)
    for run in paragraph.runs[2:]:
        run.text = ""


def flatten_body(data: dict) -> list[str]:
    body: list[str] = []
    for section in data.get("sections", []):
        title = str(section.get("title") or "").strip()
        if title:
            body.append(title)
        body.extend(str(item).strip() for item in section.get("items", []) if str(item).strip())
    return body


def split_item(item: str) -> tuple[str, str]:
    if "：" not in item:
        return item, ""
    label, content = item.split("：", 1)
    return label.strip(), content.strip()


def clean_text(value: object, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("SOURCE:", "来源：")
    text = normalize_hkd_units(text)
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip("，。；,. ") + "…"
    return text


def compact_market_reaction_text(value: str) -> str:
    text = clean_text(value)
    match = re.search(
        r"前一交易日(\d+月\d+日)收盘价为([0-9.]+港元)，后一交易日(\d+月\d+日)收盘价为([0-9.]+港元)，(上涨|下跌)([0-9.]+%)",
        text,
    )
    if match:
        return f"业绩发布前后股价由{match.group(2)}变动至{match.group(4)}，{match.group(5)}{match.group(6)}。"
    return text


def normalize_hkd_units(value: str) -> str:
    def replace_cents(match: re.Match[str]) -> str:
        amount = Decimal(match.group(1)) / Decimal("100")
        normalized = format(amount.normalize(), "f")
        if normalized.startswith("."):
            normalized = f"0{normalized}"
        return f"{normalized}港元"

    text = re.sub(r"(\d+(?:\.\d+)?)\s*港仙", replace_cents, value)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*HK\s*cents?", replace_cents, text, flags=re.I)
    return text


def strip_raw_fact_text(value: object) -> str:
    text = clean_text(value, 260)
    text = re.sub(
        r"^(?:片段中明确提到|片段中明确列出|片段明确提到|片段明确说明|片段提到|片段列出|新闻标题明确提及)[：:'“” ]*",
        "",
        text,
    )
    text = re.sub(r"\b(\d+(?:\.\d+)?亿港元)\s+loss\b", r"亏损\1", text, flags=re.I)
    text = re.sub(r"\s*\((?:final|interim)\)\s*", "", text, flags=re.I)
    return text.strip(" ：，。'“”")


def is_publishable_fact_text(value: object) -> bool:
    text = strip_raw_fact_text(value)
    if not text:
        return False
    blocked = (
        "片段中",
        "公开信息已更新",
        "Skip to main content",
        "Log In Sign Up",
        "Stock Screener",
        "Final dividend per share",
        "Net customer service revenue",
        "Total revenue",
        "Profit attributable",
    )
    if any(token.lower() in text.lower() for token in blocked):
        return False
    has_cn = len(re.findall(r"[\u4e00-\u9fff]", text)) >= 2
    has_value = bool(re.search(r"\d(?:[\d,.]*)\s*(?:亿港元|百万港元|万港元|港元|亿元|元|%|GB|万|亿|栋|个|户|条)", text))
    return has_cn or has_value


def has_inline_content(paragraph: Paragraph) -> bool:
    xml = paragraph._p.xml
    return bool(
        paragraph.text.strip()
        or "<w:drawing" in xml
        or "<w:pict" in xml
        or "<w:object" in xml
        or "<w:tbl" in xml
        or "<w:sectPr" in xml
    )


def prune_trailing_empty_paragraphs(doc: Document) -> None:
    for paragraph in reversed(doc.paragraphs):
        if has_inline_content(paragraph):
            break
        remove_paragraph(paragraph)


def load_verified_fields() -> dict:
    if not VERIFIED_FIELDS_PATH.exists():
        return {}
    data = json.loads(VERIFIED_FIELDS_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def is_publishable_field(value: object) -> bool:
    text = clean_text(value)
    if len(text) < 8:
        return False
    blocked = (
        "Skip to main content",
        "Log In Sign Up",
        "Full Chart Watchlist",
        "Income Statement",
        "Annual Results Presentation",
        "Investor Relations Department",
        "Corporate Governance Report",
        "SOURCE:",
        "| --- |",
        "2024 final dividend:",
        "本轮行情抓取失败",
    )
    if any(token.lower() in text.lower() for token in blocked):
        return False
    if text[0].islower() and re.match(r"^[a-z]{1,12}\s", text):
        return False
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    if chinese_chars < 4 and "不适用" not in text:
        return False
    return True


def load_result_records() -> list[dict]:
    records = []
    for path in sorted(RESULTS_DIR.glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        records.append(data)
    return records


def company_corpus(results: list[dict]) -> dict[str, list[str]]:
    corpus = {company: [] for company in COMPANIES}
    for result in results:
        extracted = result.get("extracted") or {}
        for company in COMPANIES:
            if extracted.get(company):
                corpus[company].append(clean_text(extracted.get(company), 600))
            for key, value in extracted.items():
                text = clean_text(value, 600)
                if company in str(key) or company in text:
                    corpus[company].append(text)
            for record in result.get("raw_records") or []:
                if not isinstance(record, dict):
                    continue
                text = clean_text(" ".join(str(record.get(field) or "") for field in ["title", "text", "url"]), 600)
                if company in text:
                    corpus[company].append(text)
    return corpus


def extract_metric(texts: list[str], patterns: list[str]) -> str:
    text = "\n".join(texts)
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return clean_text(match.group(1), 80)
    return "待补充"


def build_dynamic_table(corpus: dict[str, list[str]]) -> list[list[str]]:
    baseline = json.loads(DATA_PATH.read_text(encoding="utf-8")).get("table", [])
    return baseline


def summary_table(config: dict, companies: list[str]) -> list[list[str]]:
    rows = [SUMMARY_TABLE_HEADERS]
    for company in companies:
        company_cfg = config["companies"].get(company) or {}
        row = company_cfg.get("table_row") or MAINLAND_SUMMARY_ROWS.get(company)
        if not row:
            raise ValueError(f"业绩摘要缺少表格行配置：{company}")
        rows.append([clean_text(value, 80) for value in row])
    return rows


def load_market_cache() -> dict:
    if not MARKET_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(MARKET_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_market_cache(data: dict) -> None:
    MARKET_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stockanalysis_market_points(ticker: str) -> list[tuple[datetime.date, float]]:
    symbol = ticker.split(".", 1)[0]
    response = httpx.get(
        f"https://stockanalysis.com/quote/hkg/{symbol}/history/",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
        follow_redirects=True,
    )
    response.raise_for_status()
    points = []
    for close, raw_date in re.findall(r'c:([0-9.]+),h:[^}]+?t:"([0-9]{4}-[0-9]{2}-[0-9]{2})"', response.text):
        points.append((datetime.strptime(raw_date, "%Y-%m-%d").date(), float(close)))
    return sorted(points, key=lambda point: point[0])


def market_reaction(company_cfg: dict) -> str:
    ticker = clean_text(company_cfg.get("ticker"), 20)
    raw_event_date = clean_text(company_cfg.get("market_event_date"), 20)
    if not ticker or not raw_event_date:
        return ""
    cache = load_market_cache()
    cache_key = f"{ticker}|{raw_event_date}"
    try:
        event_date = datetime.strptime(raw_event_date, "%Y-%m-%d")
        points = stockanalysis_market_points(ticker)
        before = [point for point in points if point[0] < event_date.date()]
        after = [point for point in points if point[0] > event_date.date()]
        if not before or not after:
            return ""
        before_date, before_close = before[-1]
        after_date, after_close = after[0]
        change = (after_close / before_close - 1) * 100
        direction = "上涨" if change >= 0 else "下跌"
        text = (
            f"按公开交易数据，业绩发布前一交易日{before_date.month}月{before_date.day}日收盘价为"
            f"{before_close:.2f}港元，后一交易日{after_date.month}月{after_date.day}日收盘价为"
            f"{after_close:.2f}港元，{direction}{abs(change):.1f}%。"
        )
        cache[cache_key] = {
            "updated_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds"),
            "text": text,
        }
        save_market_cache(cache)
        return text
    except Exception as exc:
        cached = cache.get(cache_key) or {}
        if cached.get("text"):
            return clean_text(cached["text"], 360)
        return f"本轮行情抓取失败，已登记补采任务（{clean_text(type(exc).__name__, 32)}）。"


def load_source_config() -> dict:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(f"业绩摘要来源配置不存在：{SOURCE_PATH}")
    data = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data.get("companies"), dict):
        raise ValueError("carrier_performance_sources.json 缺少 companies 配置")
    if FEISHU_MIRROR_PATH.exists():
        mirror = json.loads(FEISHU_MIRROR_PATH.read_text(encoding="utf-8"))
        for row in mirror.get("rows") or []:
            company = clean_text(row.get("主体"), 80)
            if not company or company not in data["companies"]:
                continue
            company_cfg = data["companies"][company]
            fields = company_cfg.setdefault("fields", {})
            for field_key, column in [
                ("dividend", "派息"),
                ("capex", "资本开支"),
                ("strategy", "战略升级"),
                ("broker", "券商观点"),
                ("market", "市场反应"),
            ]:
                if is_publishable_field(row.get(column)):
                    fields[field_key] = str(row[column])
            latest_event = company_cfg.setdefault("latest_event", {})
            if clean_text(row.get("最新披露")):
                latest_event["label"] = str(row["最新披露"])
            if clean_text(row.get("披露日期")):
                latest_event["date"] = str(row["披露日期"])
            if clean_text(row.get("主体说明")):
                latest_event["note"] = str(row["主体说明"])
            if clean_text(row.get("股票代码")):
                company_cfg["ticker"] = str(row["股票代码"])
    # Verified fields are the publication layer. They are applied last so a
    # raw extraction fragment in Feishu cannot overwrite client-ready text.
    for company, fields in load_verified_fields().items():
        if company not in data["companies"] or not isinstance(fields, dict):
            continue
        target = data["companies"][company].setdefault("fields", {})
        for field_key, value in fields.items():
            if is_publishable_field(value):
                target[field_key] = value
    return data


def refresh_feishu_mirror() -> None:
    if not FEISHU_SYNC_SCRIPT.exists():
        return
    env = os.environ.copy()
    for key in ["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"]:
        env.pop(key, None)
    env["LARK_CLI_NO_PROXY"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, str(FEISHU_SYNC_SCRIPT), "--pull-only"],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=90,
        )
    except Exception as exc:
        if not FEISHU_MIRROR_PATH.exists():
            raise RuntimeError(f"飞书业绩摘要补充页同步失败：{exc}") from exc
        print(f"[飞书同步提示] 暂时无法刷新补充页，使用上次镜像：{type(exc).__name__}")
        return
    if proc.returncode != 0:
        if not FEISHU_MIRROR_PATH.exists():
            raise RuntimeError(f"飞书业绩摘要补充页同步失败：{proc.stderr.strip()}")
        print("[飞书同步提示] 暂时无法刷新补充页，使用上次镜像。")
        return
    print("[飞书同步完成] 已读取运营商业绩摘要补充页。")


def get_all_companies(config: dict) -> list[str]:
    groups = config.get("groups") or {}
    order = []
    for group_name in ["mainland", "hong-kong"]:
        order.extend(groups.get(group_name) or [])
    return order or list(config.get("companies") or {})


def decode_response_text(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    raw = response.content
    if "pdf" in content_type.lower() or raw[:4] == b"%PDF":
        with tempfile.TemporaryDirectory(prefix="carrier_perf_pdf_") as tmp_dir:
            tmp = Path(tmp_dir)
            pdf_path = tmp / "source.pdf"
            txt_path = tmp / "source.txt"
            pdf_path.write_bytes(raw)
            pdftotext = shutil.which("pdftotext") or "/opt/homebrew/bin/pdftotext"
            if not Path(pdftotext).exists():
                return ""
            subprocess.run(
                [pdftotext, "-layout", "-l", "80", str(pdf_path), str(txt_path)],
                check=True,
                timeout=45,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return txt_path.read_text(encoding="utf-8", errors="ignore")

    response.encoding = response.encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def crawl_carrier_sources(config: dict) -> dict:
    cached = {}
    if CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            cached = {}
    cached_sources = cached.get("sources", {}) if isinstance(cached, dict) else {}
    next_cache = {
        "updated_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds"),
        "sources": {},
    }
    headers = {
        "User-Agent": "CMHK-CarrierPerformanceBot/1.0 (+internal research; public sources only)",
        "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(headers=headers, follow_redirects=True, timeout=httpx.Timeout(25.0, connect=8.0)) as client:
        for company, company_cfg in config.get("companies", {}).items():
            for source in company_cfg.get("sources", []):
                url = str(source.get("url") or "").strip()
                if not url:
                    continue
                key = f"{company}|{url}"
                item = {
                    "company": company,
                    "label": source.get("label", ""),
                    "source_type": source.get("type", ""),
                    "url": url,
                    "ok": False,
                    "text": "",
                    "error": "",
                }
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    item["text"] = clean_text(decode_response_text(response), 16000)
                    item["ok"] = bool(item["text"])
                    item["status_code"] = response.status_code
                except Exception as exc:
                    previous = cached_sources.get(key, {}) if isinstance(cached_sources, dict) else {}
                    item["text"] = previous.get("text", "")
                    item["ok"] = bool(item["text"])
                    item["error"] = str(exc)
                    item["from_cache"] = bool(item["text"])
                next_cache["sources"][key] = item
    CACHE_PATH.write_text(json.dumps(next_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return next_cache


def evidence_for_field(company: str, field_key: str, cache: dict) -> str:
    keywords = {
        "dividend": ["dividend", "派息", "股息", "payout", "shareholder returns"],
        "capex": ["capex", "capital expenditure", "资本开支", "算力", "computing"],
        "strategy": ["AI", "人工智能", "strategy", "strategic", "云", "算力", "一体两翼"],
        "broker": ["rating", "target price", "评级", "目标价", "买入", "中性", "券商", "公允价值"],
        "market": ["share price", "股价", "市场", "market", "reaction", "investor"],
    }.get(field_key, [])
    preferred_types = {
        "dividend": ["official_dividend", "annual_results", "official_news"],
        "capex": ["annual_results", "official_news"],
        "strategy": ["annual_results", "official_news"],
        "broker": ["broker_view"],
        "market": ["broker_view", "annual_results", "official_news"],
    }.get(field_key, [])
    sources = [
        source
        for source in (cache.get("sources") or {}).values()
        if source.get("company") == company and source.get("text")
    ]
    sources.sort(
        key=lambda source: preferred_types.index(source.get("source_type"))
        if source.get("source_type") in preferred_types
        else len(preferred_types)
    )
    for source in sources:
        text = str(source.get("text") or "")
        for raw in re.split(r"(?<=[。.!?])\s+", text):
            sentence = clean_text(raw, 170)
            lowered = sentence.lower()
            if len(sentence) < 20:
                continue
            if any(keyword.lower() in lowered for keyword in keywords):
                label = clean_text(source.get("label"), 28)
                return f"来源：{label}"
    return ""


def company_evidence(company: str, texts: list[str]) -> list[str]:
    snippets = []
    def has_keyword(sentence: str) -> bool:
        lowered = sentence.lower()
        return (
            any(keyword in sentence for keyword in ["收入", "资本开支", "人工智能", "算力", "派息"])
            or any(keyword in lowered for keyword in ["revenue", "capex", "capital expenditure", "5g", "dividend", "profit"])
            or re.search(r"\bai\b", lowered) is not None
        )

    for text in texts:
        for raw in re.split(r"(?<=[。.!?])\s+", text):
            sentence = clean_text(raw, 170)
            if not sentence or "emergence-partnership" in sentence or "©" in sentence:
                continue
            if company in sentence and has_keyword(sentence):
                if sentence not in snippets:
                    snippets.append(sentence)
            elif has_keyword(sentence) and len(sentence) > 24:
                if sentence not in snippets:
                    snippets.append(sentence)
            if len(snippets) >= 4:
                return snippets
    return snippets


def table_lookup(table: list[list[str]], company: str, metric: str) -> str:
    if not table:
        return "待补充"
    try:
        company_index = table[0].index(company)
    except ValueError:
        return "待补充"
    for row in table[1:]:
        if row and row[0] == metric and company_index < len(row):
            return clean_text(row[company_index]) or "待补充"
    return "待补充"


def confirmed_facts_by_report_company(companies: list[str]) -> dict[str, list[dict]]:
    payload = build_company_metrics_payload()
    public_rows = [
        row
        for row in payload.get("rows") or []
        if row.get("sourceType") == "public-crawl" and row.get("aiStatus") == "ok"
    ]
    output: dict[str, list[dict]] = {}
    for company in companies:
        aliases = COMPANY_FACT_ALIASES.get(company, {company})
        output[company] = [row for row in public_rows if row.get("company") in aliases]
    return output


def fact_field(metric: str) -> str:
    if re.search(r"派息|股息|分派", metric, re.IGNORECASE):
        return "dividend"
    if re.search(r"资本开支|Capex|投资方向", metric, re.IGNORECASE):
        return "capex"
    if re.search(r"券商观点|评级|目标价", metric, re.IGNORECASE):
        return "broker"
    if re.search(r"市场反应|股价", metric, re.IGNORECASE):
        return "market"
    return "strategy"


def enrich_field_with_confirmed_facts(base: str, field_key: str, facts: list[dict]) -> tuple[str, list[str]]:
    additions: list[str] = []
    used_ids: list[str] = []
    normalized_base = re.sub(r"\s+", "", base).casefold()

    def market_value_signature(text: str) -> set[str]:
        return {f"{amount}{unit}" for amount, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(港元|%)", text)}

    base_market_signature = market_value_signature(base) if field_key == "market" else set()
    for fact in facts:
        if fact_field(str(fact.get("metric") or "")) != field_key:
            continue
        raw_value = fact.get("value")
        raw_detail = fact.get("detail")
        value = strip_raw_fact_text(raw_value)
        if not is_publishable_fact_text(value):
            value = strip_raw_fact_text(raw_detail)
        if not is_publishable_fact_text(value):
            continue
        normalized_value = re.sub(r"\s+", "", value).casefold()
        if normalized_value in normalized_base:
            used_ids.append(str(fact.get("id") or ""))
            continue
        if field_key == "market":
            value_signature = market_value_signature(value)
            if value_signature and value_signature.issubset(base_market_signature):
                used_ids.append(str(fact.get("id") or ""))
                continue
        addition = f"{clean_text(fact.get('metric'), 32)}：{value}"
        if addition not in additions:
            additions.append(addition)
        used_ids.append(str(fact.get("id") or ""))
    if not additions:
        return base, [item for item in used_ids if item]
    enriched = f"{base.rstrip('。')}；另，" + "；".join(additions) + "。"
    return enriched, [item for item in used_ids if item]


def build_performance_sections(config: dict, cache: dict, companies: list[str]) -> list[dict]:
    sections = []
    confirmed_facts = confirmed_facts_by_report_company(companies)
    used_fact_ids: set[str] = set()
    for company in companies:
        company_cfg = config["companies"].get(company)
        if not company_cfg:
            raise ValueError(f"业绩摘要来源配置缺少公司：{company}")
        latest_event = company_cfg.get("latest_event") or {}
        latest_label = clean_text(latest_event.get("label"), 80)
        latest_date = clean_text(latest_event.get("date"), 40)
        annual_event = clean_text(company_cfg.get("event_date"), 40)
        short_latest = (
            latest_label.replace("2026年一季度", "2026Q1")
            .replace("经营与财务问答", "FAQ")
            .replace("未经审核关键绩效指标", "KPI")
        )
        short_latest_date = latest_date.replace("2026年", "").replace("月后", "月后")
        short_annual = annual_event.replace("业绩说明会", "").replace("2026年", "")
        if latest_label and latest_date and "业绩说明会" in annual_event:
            section_title = f"{company}（{short_latest}{short_latest_date}；年度会{short_annual}）关键摘要"
        elif latest_label and latest_date:
            section_title = f"{company}（{short_latest}{short_latest_date}）关键摘要"
        elif annual_event:
            section_title = f"{company}（年度说明会：{annual_event}）关键摘要"
        else:
            section_title = f"{company}关键摘要"
        fields = company_cfg.get("fields") or {}
        items = []
        for field_key, label in FIELD_ORDER:
            content = clean_text(fields.get(field_key), 360)
            if field_key == "market" and not is_publishable_field(content):
                content = market_reaction(company_cfg) or content
            if field_key == "market":
                content = compact_market_reaction_text(content)
            if not content:
                content = "公开资料未单独披露该项口径。"
            if not is_publishable_field(content):
                raise ValueError(f"业绩摘要字段未通过发布质量校验：{company} / {label}")
            content, field_fact_ids = enrich_field_with_confirmed_facts(
                content,
                field_key,
                confirmed_facts.get(company, []),
            )
            used_fact_ids.update(field_fact_ids)
            items.append(f"{label}：{content}")
        sections.append({"title": section_title, "items": items})
    all_relevant_ids = {
        str(fact.get("id") or "")
        for facts in confirmed_facts.values()
        for fact in facts
        if fact.get("id")
    }
    PERFORMANCE_USAGE_AUDIT_PATH.write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds"),
                "reportCompanies": companies,
                "acceptedRelevantFacts": len(all_relevant_ids),
                "usedFacts": len(used_fact_ids),
                "omittedFacts": len(all_relevant_ids - used_fact_ids),
                "usedFactIds": sorted(used_fact_ids),
                "omittedFactIds": sorted(all_relevant_ids - used_fact_ids),
                "policy": "保持五点结构；派息、资本开支、券商观点和市场反应按字段合并，其余确认经营事实并入战略升级。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return sections


def build_dynamic_model() -> dict:
    refresh_feishu_mirror()
    config = load_source_config()
    cache = crawl_carrier_sources(config)
    companies = get_all_companies(config)
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    return {
        "title": "内地运营商及香港主要竞对关键业绩摘要",
        "subtitle": "战略部（智库）对标分析简报",
        "intro": (
            f"截至{now.year}年{now.month}月{now.day}日，本摘要同步核对内地运营商及香港主要竞对最新可获取的"
            "年度或中期业绩、后续经营披露、业绩公告及资本市场观点。上市主体与品牌口径分别列示；"
            "未公开或不适用的项目明确标注，供内部决策参考。"
        ),
        "table_caption": "表：内地运营商及香港主要竞对最新关键业绩数据汇总",
        "table": summary_table(config, companies),
        "sections": build_performance_sections(config, cache, companies),
    }


def render_body_sections(doc: Document, sections: list[dict]) -> None:
    body_slots = [paragraph for paragraph in doc.paragraphs[4:] if paragraph.text.strip()]
    if len(body_slots) < 2:
        raise ValueError("运营商业绩摘要模板缺少正文样式段落")

    title_anchor = body_slots[0]
    title_template = deepcopy(title_anchor._p)
    item_template = deepcopy(body_slots[1]._p)
    for paragraph in body_slots[1:]:
        remove_paragraph(paragraph)

    current = title_anchor
    for section_index, section in enumerate(sections):
        if section_index:
            new_title = deepcopy(title_template)
            current._p.addnext(new_title)
            current = Paragraph(new_title, current._parent)
        clear_paragraph_numbering(current)
        set_plain_paragraph(current, str(section.get("title") or ""), bold=True)
        current.alignment = WD_ALIGN_PARAGRAPH.LEFT
        current.paragraph_format.left_indent = Pt(0)
        current.paragraph_format.first_line_indent = Pt(0)
        current.paragraph_format.keep_with_next = True

        items = [split_item(str(item)) for item in section.get("items", [])]
        item_map = {label: content for label, content in items}
        for item_index, (_, label) in enumerate(FIELD_ORDER, start=1):
            new_item = deepcopy(item_template)
            current._p.addnext(new_item)
            current = Paragraph(new_item, current._parent)
            set_template_item(
                current,
                item_index,
                label,
                item_map.get(label, ""),
                broker_header=(label == "券商观点"),
            )


def render_report() -> Path:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"模板不存在：{TEMPLATE_PATH}")
    data = build_dynamic_model()
    doc = Document(str(TEMPLATE_PATH))
    if len(doc.paragraphs) < 4 or not doc.tables:
        raise ValueError("运营商业绩摘要模板结构不完整")

    replacements = [
        data["title"],
        data["subtitle"],
        data["intro"],
        data["table_caption"],
    ]
    for paragraph, text in zip(doc.paragraphs[:4], replacements):
        replace_paragraph_text(paragraph, str(text))

    rows = data.get("table", [])
    table = doc.tables[0]
    while len(table.columns) < len(rows[0]):
        table.add_column(table.columns[-1].width)
    while len(table.rows) < len(rows):
        table.add_row()
    while len(table.rows) > len(rows):
        table._tbl.remove(table.rows[-1]._tr)
    for row_cells, values in zip(table.rows, rows):
        for cell, value in zip(row_cells.cells, values):
            cell.text = str(value)

    render_body_sections(doc, data.get("sections", []))
    prune_trailing_empty_paragraphs(doc)

    output_path = dated_output_path()
    doc.save(str(output_path))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = ROOT / "archives" / timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, archive_dir / output_path.name)
    return output_path


def main() -> None:
    print("==================================================")
    print("开始生成运营商业绩摘要...")
    print("模板：", TEMPLATE_PATH.name)
    print("数据：", DATA_PATH.name)
    output_path = render_report()
    print("[生成成功] 最终输出文件：")
    print(" ->", output_path)
    print("==================================================")


if __name__ == "__main__":
    main()
