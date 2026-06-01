from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from docx import Document


ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "carrier_performance_template.docx"
DATA_PATH = ROOT / "carrier_performance_data.json"
RESULTS_DIR = ROOT / "results"
COMPANIES = ["中国移动", "中国电信", "中国联通", "中国铁塔"]
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


def flatten_body(data: dict) -> list[str]:
    body: list[str] = []
    for section in data.get("sections", []):
        title = str(section.get("title") or "").strip()
        if title:
            body.append(title)
        body.extend(str(item).strip() for item in section.get("items", []) if str(item).strip())
    return body


def clean_text(value: object, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("SOURCE:", "来源：")
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip("，。；,. ") + "…"
    return text


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


def result_topic(result: dict) -> str:
    return clean_text(result.get("need") or result.get("block") or result.get("object") or "未分类", 90)


def result_entities(result: dict) -> str:
    entities = [clean_text(item, 24) for item in result.get("entities") or [] if clean_text(item)]
    return "、".join(entities[:4]) or "未标注主体"


def result_evidence(result: dict) -> str:
    extracted = result.get("extracted") or {}
    for key, value in extracted.items():
        text = clean_text(value, 180)
        if text:
            return f"{clean_text(key, 24)}：{text}"
    for record in result.get("raw_records") or []:
        if not isinstance(record, dict):
            continue
        title = clean_text(record.get("title"), 90)
        source_type = clean_text(record.get("source_type"), 36)
        if title:
            return f"{source_type or '公开来源'}：{title}"
    return "当前行未抽取到可直接引用的正文片段，需后续复核原始链接。"


def collect_monitoring_sections(results: list[dict]) -> list[dict]:
    ok_count = sum(1 for item in results if item.get("status") == "ok")
    partial_count = sum(1 for item in results if item.get("status") == "partial")
    failed_count = len(results) - ok_count - partial_count
    entity_counter: Counter[str] = Counter()
    topic_counter: Counter[str] = Counter()
    missing_total = 0
    for item in results:
        for entity in item.get("entities") or []:
            if clean_text(entity):
                entity_counter[clean_text(entity, 32)] += 1
        for token in re.split(r"[、,，/ ]+", result_topic(item)):
            token = clean_text(token, 24)
            if token:
                topic_counter[token] += 1
        missing = item.get("missing_fields") or []
        if isinstance(missing, list):
            missing_total += len(missing)

    top_entities = "、".join(name for name, _ in entity_counter.most_common(8)) or "未形成主体统计"
    top_topics = "、".join(name for name, _ in topic_counter.most_common(8)) or "未形成主题统计"

    local_keywords = ["HKBN", "SmarTone", "HGC", "iCable", "i-CABLE", "HKT", "csl", "1O1O", "香港"]
    metric_keywords = ["收入", "EBITDA", "净利润", "资本开支", "ARPU", "用户", "宽频", "5G"]
    strategy_keywords = ["AI", "人工智能", "算力", "云", "安全", "数据中心", "合作", "中标", "跨境"]

    def pick_rows(keywords: list[str], limit: int = 4) -> list[dict]:
        picked: list[dict] = []
        for item in results:
            text = clean_text(
                " ".join(
                    [
                        result_topic(item),
                        result_entities(item),
                        " ".join(str(key) for key in (item.get("extracted") or {}).keys()),
                    ]
                )
            )
            if any(keyword.lower() in text.lower() for keyword in keywords):
                picked.append(item)
            if len(picked) >= limit:
                break
        return picked

    def row_items(rows: list[dict], fallback: str) -> list[str]:
        if not rows:
            return [fallback]
        items = []
        for item in rows:
            row_no = clean_text(item.get("row"), 12)
            entities = result_entities(item)
            topic = result_topic(item)
            evidence = result_evidence(item)
            status = clean_text(item.get("status"), 18)
            items.append(f"第{row_no}行（{entities}，{status}）：{topic}。{evidence}")
        return items

    quality_items = [
        f"本轮共载入{len(results)}行公开信息监测结果，其中完整成功{ok_count}行、部分成功{partial_count}行、异常或无抽取{failed_count}行。",
        f"主体覆盖：{top_entities}。",
        f"高频主题：{top_topics}。",
        f"字段完整性：当前仍有{missing_total}个字段需要补充或人工复核，后续应优先补齐经营指标、资本开支、用户数和派息等可量化字段。",
    ]

    return [
        {"title": "一、本轮监测总体判断", "items": quality_items},
        {
            "title": "二、香港本地运营商动态",
            "items": row_items(
                pick_rows(local_keywords),
                "本轮结果未命中明确的香港本地运营商片段，建议检查飞书配置中的主体与来源链接。",
            ),
        },
        {
            "title": "三、经营指标与资本开支线索",
            "items": row_items(
                pick_rows(metric_keywords),
                "本轮结果未命中可量化经营指标，建议补充年报、业绩公告或投资者材料链接。",
            ),
        },
        {
            "title": "四、AI、算力及政企能力变化",
            "items": row_items(
                pick_rows(strategy_keywords),
                "本轮结果未命中AI、算力或政企能力相关片段，建议扩大关键词和官网新闻源范围。",
            ),
        },
    ]


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


def build_company_baseline_notes(corpus: dict[str, list[str]]) -> list[str]:
    notes = []
    table = build_dynamic_table(corpus)
    for company in COMPANIES:
        snippets = company_evidence(company, corpus.get(company, []))
        revenue = table_lookup(table, company, "营业收入（亿元）")
        service_revenue = table_lookup(table, company, "主营业务收入（亿元）")
        ebitda = table_lookup(table, company, "EBITDA(亿元)")
        profit = table_lookup(table, company, "归母净利润（亿元）")
        net_margin = table_lookup(table, company, "净利率")
        capex = table_lookup(table, company, "资本开支（亿元）")
        capex_plan = table_lookup(table, company, "资本开支2026年计划（亿元）")
        mobile_users = table_lookup(table, company, "移动用户数（亿户）")
        fiveg_users = table_lookup(table, company, "5G网络用户数（亿户）")
        fiveg_penetration = table_lookup(table, company, "5G网络渗透率")
        note = (
            f"{company}：营业收入{revenue}，主营业务收入{service_revenue}，EBITDA{ebitda}，"
            f"归母净利润{profit}，净利率{net_margin}；资本开支{capex}，2026年计划{capex_plan}；"
            f"移动用户{mobile_users}，5G用户{fiveg_users}，5G渗透率{fiveg_penetration}。"
        )
        if snippets:
            note += f" 本轮补充片段：{snippets[0]}"
        notes.append(note)
    return notes


def build_dynamic_sections(results: list[dict], corpus: dict[str, list[str]]) -> list[dict]:
    sections = collect_monitoring_sections(results)
    sections.append(
        {
            "title": "五、运营商业绩基线对照",
            "items": build_company_baseline_notes(corpus)
            + ["后续建议：在下一轮爬取中补充各公司财报公告、业绩演示材料、交易所披露与券商观点链接，形成可追溯的指标更新链路。"],
        }
    )
    return sections


def build_dynamic_model() -> dict:
    results = load_result_records()
    corpus = company_corpus(results)
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    return {
        "title": "运营商业绩与竞对动态摘要",
        "subtitle": "战略部（智库）对标分析简报",
        "intro": (
            f"截至{now.year}年{now.month}月{now.day}日，本报告基于系统最新公开信息监测结果自动生成。"
            f"本轮共读取{len(results)}行爬取结果，正文优先引用本轮监测中的主体、字段和公开来源线索；"
            "表格保留运营商业绩模板的结构化基线，用于和后续新披露数据持续对照。"
        ),
        "table_caption": "表：运营商业绩基线数据汇总（用于后续滚动对照）",
        "table": build_dynamic_table(corpus),
        "sections": build_dynamic_sections(results, corpus),
    }


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
    if len(rows) != len(table.rows) or any(len(row) != len(table.columns) for row in rows):
        raise ValueError("运营商业绩摘要表格数据与模板行列数不一致")
    for row_cells, values in zip(table.rows, rows):
        for cell, value in zip(row_cells.cells, values):
            cell.text = str(value)

    body = flatten_body(data)
    body_slots = [paragraph for paragraph in doc.paragraphs[4:] if paragraph.text.strip()]
    if len(body) > len(body_slots):
        raise ValueError(f"正文模板槽位不足：模板 {len(body_slots)} 段，数据 {len(body)} 段")
    for paragraph, text in zip(body_slots, body):
        replace_paragraph_text(paragraph, text)
    for paragraph in body_slots[len(body):]:
        remove_paragraph(paragraph)

    for paragraph in list(doc.paragraphs[4:]):
        if not paragraph.text.strip():
            remove_paragraph(paragraph)

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
