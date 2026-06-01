from __future__ import annotations

import json
import re
import shutil
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


def build_dynamic_sections(corpus: dict[str, list[str]]) -> list[dict]:
    sections = []
    date_note = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y年%-m月%-d日")
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
        items = [
            f"核心业绩：营业收入为{revenue}，主营业务收入为{service_revenue}，EBITDA为{ebitda}，归母净利润为{profit}，净利率为{net_margin}。",
            f"资本开支：2025年资本开支为{capex}，2026年计划为{capex_plan}；后续需持续关注投资结构是否继续向算力、AI和网络能力升级倾斜。",
            f"用户与网络：移动用户数为{mobile_users}，5G网络用户数为{fiveg_users}，5G网络渗透率为{fiveg_penetration}。",
        ]
        if snippets:
            items.append(f"本轮监测补充：{snippets[0]}")
        else:
            items.append(f"本轮监测补充：截至{date_note}，当前爬取结果中未取得新的可复核补充片段，需补充该公司的财报公告、业绩演示材料或交易所披露链接。")
        items.append("后续关注：建议按同一口径持续跟踪派息政策、资本开支变化、AI/算力投入、5G用户渗透和资本市场反馈，避免仅看单一收入指标。")
        sections.append({"title": f"{company}关键摘要", "items": items})
    return sections


def build_dynamic_model() -> dict:
    results = load_result_records()
    corpus = company_corpus(results)
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    return {
        "title": "各家运营商关键业绩摘要",
        "subtitle": "战略部（智库）对标分析简报",
        "intro": (
            f"截至{now.year}年{now.month}月{now.day}日，本报告基于系统最新公开信息监测结果自动生成。"
            "报告沿用参考模板版式，以结构化业绩基线数据为表格基础，并结合本轮爬取结果补充AI、算力、5G和资本开支相关动态；"
            "未在当前监测结果中取得新证据的部分会明确提示后续补充方向。"
        ),
        "table_caption": "表：各家运营商关键业绩数据汇总（结构化基线）",
        "table": build_dynamic_table(corpus),
        "sections": build_dynamic_sections(corpus),
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
