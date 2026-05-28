from __future__ import annotations

import html
import json
import re
from copy import deepcopy
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from crawl_settings import enabled_rows


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"

WEEKLY_MD = ROOT / "weekly_report.md"
WEEKLY_HTML = ROOT / "weekly_report.html"
def dated_weekly_docx_path(now: datetime | None = None) -> Path:
    value = now or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    base_name = f"{value.month}月{value.day}日周报"
    path = ROOT / f"{base_name}.docx"
    if not path.exists():
        return path
    counter = 1
    while True:
        path = ROOT / f"{base_name} ({counter}).docx"
        if not path.exists():
            return path
        counter += 1


WEEKLY_DOCX = dated_weekly_docx_path()
TEMPLATE_MD = ROOT / "weekly_report_template.md"
TEMPLATE_DOCX = ROOT / "weekly_report_template.docx"
LOCAL_WORD_TEMPLATE = Path("/Users/liaowang/Downloads/模板.docx")
REPO_WORD_TEMPLATE = ROOT / "weekly_report_template.docx"
SOURCE_WORD_TEMPLATE = LOCAL_WORD_TEMPLATE if LOCAL_WORD_TEMPLATE.exists() else REPO_WORD_TEMPLATE

# Keep these aliases so older automation does not keep serving the wrong
# "agent run" report format.
AGENT_MD_ALIAS = ROOT / "agent_report.md"
AGENT_HTML_ALIAS = ROOT / "agent_report.html"

SECTION_ORDER = ["政治资讯", "行业资讯", "社会资讯", "国际资讯"]
WEEKLY_MAX_PER_SECTION = 4

TAG_BY_ROW = {
    2: "运营商财报",
    3: "友商动态",
    4: "友商动态",
    5: "运营商财报",
    6: "友商动态",
    7: "友商动态",
    8: "运营商财报",
    9: "友商动态",
    10: "人工智能",
    11: "运营商财报",
    12: "公告披露",
    13: "资本市场",
    14: "友商动态",
    15: "友商动态",
    16: "友商动态",
    17: "运营商财报",
    18: "友商动态",
    19: "国际运营商",
    20: "国际运营商",
    21: "国际运营商",
    22: "政策动向",
    23: "宏观经济",
    24: "科创政策",
    25: "社会民生",
    26: "监管政策",
    27: "数据监管",
    28: "监管政策",
    29: "国际组织",
    30: "宏观经济",
    31: "行业资讯",
    32: "投融资",
    33: "政治新闻",
    34: "宏观经济",
}

SECTION_BY_ROW = {
    22: "政治资讯",
    24: "政治资讯",
    26: "政治资讯",
    27: "政治资讯",
    28: "政治资讯",
    33: "政治资讯",
    4: "行业资讯",
    7: "行业资讯",
    10: "行业资讯",
    14: "行业资讯",
    16: "行业资讯",
    18: "行业资讯",
    24: "行业资讯",
    31: "行业资讯",
    32: "行业资讯",
    2: "社会资讯",
    3: "社会资讯",
    5: "社会资讯",
    6: "社会资讯",
    8: "社会资讯",
    9: "社会资讯",
    11: "社会资讯",
    12: "社会资讯",
    13: "社会资讯",
    15: "社会资讯",
    17: "社会资讯",
    23: "社会资讯",
    25: "社会资讯",
    30: "社会资讯",
    34: "社会资讯",
    19: "国际资讯",
    20: "国际资讯",
    21: "国际资讯",
    29: "国际资讯",
}


def clean_text(value: object, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("SOURCE:", "来源：")
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip("，。；,. ") + "…"
    return text


def clean_object(value: object, limit: int = 40) -> str:
    text = clean_text(value)
    text = re.sub(r"（和\d+行可能存在重合，请Alex考虑是否合并）", "", text)
    aliases = {
        "政治资讯": "香港本地政策资讯",
        "经济资讯": "香港宏观经济资讯",
        "行业资讯": "行业资讯",
        "社会资讯": "社会资讯",
        "重点国家/地区AI与数据监管": "重点国家及地区AI与数据监管",
    }
    return clean_text(aliases.get(text, text), limit)


def load_results() -> list[dict]:
    enabled = enabled_rows()
    results: list[dict] = []
    for path in sorted(RESULTS_DIR.glob("row_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        row_no = int(path.stem.split("_")[1])
        if enabled is not None and row_no not in enabled:
            continue
        results.append(json.loads(path.read_text(encoding="utf-8")))
    return results


def format_date_cn(value: datetime) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def format_date_compact(value: datetime) -> str:
    return f"{value.year}-{value.month:02d}-{value.day:02d}"


def format_event_time(value: str | None) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Hong_Kong"))
    except Exception:
        return value
    return f"{parsed.year}/{parsed.month}/{parsed.day} {parsed.hour:02d}:{parsed.minute:02d}:{parsed.second:02d}"


def chinese_order(value: int) -> str:
    chars = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if value <= 10:
        return chars[value]
    if value < 20:
        return "十" + (chars[value - 10] if value > 10 else "")
    tens, ones = divmod(value, 10)
    return f"{chars[tens]}十{chars[ones] if ones else ''}"


def pick_evidence(result: dict) -> tuple[str, str]:
    extracted = result.get("extracted") or {}
    if not extracted:
        return "公开来源", "未从成功返回内容中提取到可复核字段。"
    field, snippet = next(iter(extracted.items()))
    return clean_text(field, 24), clean_text(snippet, 180)


def build_title(result: dict) -> str:
    row = int(result.get("row") or 0)
    obj = clean_object(result.get("object"), 36) or "相关主体"
    field, snippet = pick_evidence(result)
    if row in {2, 5, 8, 11, 17}:
        return f"{obj}披露{field}等经营指标"
    if row in {3, 6, 9, 14, 18}:
        return f"{obj}更新产品与资费信息"
    if row in {19, 20, 21}:
        return f"{obj}围绕{field}发布国际动态"
    if row in {22, 26, 27, 28, 33}:
        return f"{obj}发布{field}相关政策信息"
    if row in {23, 30, 34}:
        return f"{obj}更新{field}相关宏观数据"
    if row == 32:
        return f"{obj}出现投融资与交易动态"
    return f"{obj}更新{field}相关信息"


def build_detail(result: dict, _source_id: str) -> str:
    row = int(result.get("row") or 0)
    obj = clean_object(result.get("object"), 40) or "相关主体"
    tag = TAG_BY_ROW.get(row, "行业动态")
    source_count = len(result.get("source_urls") or [])
    fields = list((result.get("extracted") or {}).keys())
    field_text = "、".join(fields[:6]) if fields else "公开信息"
    miss = result.get("missing_fields") or []
    miss_text = f"；待补充字段包括{'、'.join(miss[:3])}" if miss else ""
    return (
        f"{obj}在{tag}领域形成公开信息更新，本轮成功来源{source_count}个，"
        f"可复核字段覆盖{field_text}{miss_text}。"
    )


def make_sources(results: list[dict]) -> list[dict]:
    sources = []
    index = 1
    for result in results:
        urls = result.get("source_urls") or []
        if not urls:
            continue
        sources.append(
            {
                "sourceId": f"S{index}",
                "row": int(result.get("row") or 0),
                "section": SECTION_BY_ROW.get(int(result.get("row") or 0), "行业资讯"),
                "title": build_title(result),
                "url": urls[0],
                "object": clean_object(result.get("object"), 40),
                "tag": TAG_BY_ROW.get(int(result.get("row") or 0), "行业动态"),
                "publishedAt": result.get("fetched_at_hkt") or result.get("fetched_at"),
            }
        )
        index += 1
    return sources


def build_weekly_model(results: list[dict]) -> dict:
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    start = now - timedelta(days=7)
    sources = make_sources(results)
    source_by_row = {source["row"]: source for source in sources}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        row = int(result.get("row") or 0)
        if result.get("status") not in {"ok", "partial"}:
            continue
        section = SECTION_BY_ROW.get(row, "行业资讯")
        if len(grouped[section]) >= WEEKLY_MAX_PER_SECTION:
            continue
        source = source_by_row.get(row)
        grouped[section].append(
            {
                "row": row,
                "tag": TAG_BY_ROW.get(row, "行业动态"),
                "title": build_title(result),
                "detail": build_detail(result, source["sourceId"] if source else ""),
                "eventAt": result.get("fetched_at_hkt") or result.get("fetched_at"),
                "sourceIds": [source["sourceId"]] if source else [],
            }
        )

    toc = []
    global_index = 1
    sections = []
    for section_name in SECTION_ORDER:
        items = []
        for local_index, item in enumerate(grouped.get(section_name, []), start=1):
            item = dict(item)
            item["index"] = global_index
            item["localIndex"] = local_index
            items.append(item)
            toc.append(
                {
                    "index": global_index,
                    "section": section_name,
                    "tag": item["tag"],
                    "title": item["title"],
                }
            )
            global_index += 1
        tag_names = "、".join(sorted({item["tag"] for item in items}))
        if items:
            event_times = [format_date_compact(now)] * len(items)
            narrative = (
                f"统计区间为{format_date_compact(start)}至{format_date_compact(now)}。"
                f"本期{section_name}共收录{len(items)}条事件，涉及主题：{tag_names}，"
                f"事件时间范围为{event_times[0]}至{event_times[-1]}。"
            )
        else:
            narrative = f"统计区间为{format_date_compact(start)}至{format_date_compact(now)}。{section_name}暂无纳入条目。"
        sections.append({"name": section_name, "narrative": narrative, "items": items})

    return {
        "company": "中国移动香港公司",
        "department": "中国移动香港公司战略部",
        "generatedDate": format_date_cn(now),
        "title": "战略内参",
        "range": {"start": format_date_compact(start), "end": format_date_compact(now)},
        "toc": toc,
        "sections": sections,
        "sources": sources,
    }


def weekly_to_markdown(model: dict) -> str:
    lines = [
        model["company"],
        "",
        f"{model['department']}    {model['generatedDate']}",
        "",
        "目 录",
        "",
    ]
    for section in model["sections"]:
        lines.append(section["name"])
        if section["items"]:
            for item in section["items"]:
                lines.append(f"{item['index']}.【{item['tag']}】{item['title']}")
        else:
            lines.append("（本期暂无更新）")
        lines.append("")

    for section in model["sections"]:
        lines.append(section["name"])
        if not section["items"]:
            lines.extend(["（本期暂无更新）", ""])
            continue
        for item in section["items"]:
            lines.append(item["tag"])
            lines.append(f"{chinese_order(item['index'])}、{item['title']}")
            lines.append(item["detail"])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def weekly_template_markdown() -> str:
    return """中国移动香港公司

中国移动香港公司战略部    YYYY年M月D日

目 录

政治资讯
1.【标签】一句话事件标题
（本期暂无更新）

行业资讯
1.【标签】一句话事件标题
（本期暂无更新）

社会资讯
1.【标签】一句话事件标题
（本期暂无更新）

国际资讯
1.【标签】一句话事件标题
（本期暂无更新）

政治资讯
标签
一、一句话事件标题
事件事实正文。只写公开来源可复核事实，不写爬虫运行过程。

行业资讯
标签
二、一句话事件标题
事件事实正文。

社会资讯
标签
三、一句话事件标题
事件事实正文。

国际资讯
标签
四、一句话事件标题
事件事实正文。
"""


def build_template_model() -> dict:
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    sections = []
    toc = []
    for idx, section_name in enumerate(SECTION_ORDER, start=1):
        item = {
            "index": idx,
            "localIndex": 1,
            "tag": "标签",
            "title": "一句话事件标题",
            "detail": "事件事实正文。只写公开来源可复核事实，不写爬虫运行过程。",
            "eventAt": "YYYY/M/D HH:MM:SS",
            "sourceIds": [f"S{idx}"],
        }
        toc.append({"index": idx, "section": section_name, "tag": item["tag"], "title": item["title"]})
        sections.append(
            {
                "name": section_name,
                "narrative": (
                    f"统计区间为YYYY-MM-DD至YYYY-MM-DD。本期{section_name}共收录N条事件，"
                    "涉及主题：主题A、主题B，事件时间范围为YYYY-MM-DD至YYYY-MM-DD。"
                ),
                "items": [item],
            }
        )
    return {
        "company": "中国移动香港公司",
        "department": "中国移动香港公司战略部",
        "generatedDate": "YYYY年M月D日",
        "title": "战略内参",
        "range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
        "toc": toc,
        "sections": sections,
        "sources": [
            {
                "sourceId": f"S{idx}",
                "row": idx,
                "section": section_name,
                "title": "一句话事件标题",
                "url": "URL",
                "object": "主体",
                "tag": "标签",
                "publishedAt": "YYYY/M/D HH:MM:SS",
            }
            for idx, section_name in enumerate(SECTION_ORDER, start=1)
        ],
    }


def weekly_to_html(model: dict) -> str:
    toc_html = []
    for section in model["sections"]:
        items = "".join(
            f"<div class='weekly-toc__item'>{item['index']}.【{html.escape(item['tag'])}】{html.escape(item['title'])}</div>"
            for item in section["items"]
        )
        toc_html.append(
            f"<div class='weekly-toc__group'><div class='weekly-toc__group-title'>{html.escape(section['name'])}</div>"
            f"{items or '<div class=\"weekly-toc__empty\">（本期暂无更新）</div>'}</div>"
        )

    sections_html = []
    for section in model["sections"]:
        items_html = []
        for item in section["items"]:
            items_html.append(
                "<article class='weekly-item'>"
                f"<p class='weekly-item__tag'>{html.escape(item['tag'])}</p>"
                f"<h4>{chinese_order(item['index'])}、{html.escape(item['title'])}</h4>"
                f"<p>{html.escape(item['detail'])}</p>"
                "</article>"
            )
        sections_html.append(
            f"<section class='weekly-section'><h3>{html.escape(section['name'])}</h3>"
            f"{''.join(items_html) if items_html else '<article class=\"weekly-item\"><p>（本期暂无更新）</p></article>'}</section>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(model['title'])}</title>
  <style>
    body {{ margin: 36px auto; max-width: 920px; font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; color: #172033; line-height: 1.65; }}
    .cover-company {{ text-align: center; font-size: 25px; font-weight: 700; margin-bottom: 8px; }}
    .cover-dept {{ text-align: center; font-size: 16px; margin-bottom: 14px; }}
    h1 {{ text-align: center; font-size: 24px; margin: 0 0 22px; }}
    h2, h3 {{ font-size: 19px; margin: 24px 0 8px; }}
    .weekly-toc__group-title {{ font-weight: 700; margin-top: 12px; }}
    .weekly-toc__item, .weekly-toc__empty {{ margin-left: 24px; margin-top: 4px; }}
    .weekly-section {{ margin-top: 26px; }}
    .weekly-item {{ margin: 14px 0 22px; }}
    .weekly-item h4 {{ font-size: 16px; margin: 0 0 8px; }}
    .weekly-item__tag {{ font-weight: 700; margin: 0 0 4px; }}
    a {{ color: #1d4ed8; }}
  </style>
</head>
<body>
  <div class="cover-company">{html.escape(model['company'])}</div>
  <div class="cover-dept">{html.escape(model['department'])}    {html.escape(model['generatedDate'])}</div>
  <h1>{html.escape(model['title'])}</h1>
  <section class="weekly-section weekly-section--toc"><h2>目 录</h2>{''.join(toc_html)}</section>
  {''.join(sections_html)}
</body>
</html>
"""


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_text(cell, text: str, bold: bool = False) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    para = cell.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = para.add_run(clean_text(text))
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    run.font.size = Pt(10)
    run.bold = bold


def add_p(doc: Document, text: str, *, size: int = 11, bold: bool = False, align=None, before=0, after=6, indent=0):
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(before)
    para.paragraph_format.space_after = Pt(after)
    if indent:
        para.paragraph_format.left_indent = Pt(indent / 20)
    if align is not None:
        para.alignment = align
    run = para.add_run(text)
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    run.font.size = Pt(size)
    run.bold = bold
    return para


def weekly_to_docx(model: dict, path: Path) -> None:
    doc = render_into_source_template(model)
    doc.save(path)


def has_drawing(paragraph) -> bool:
    return bool(
        paragraph._p.xpath(".//*[local-name()='drawing']")
        or paragraph._p.xpath(".//*[local-name()='pict']")
    )


def clear_paragraph(paragraph) -> None:
    for child in list(paragraph._p):
        if child.tag == qn("w:pPr"):
            continue
        paragraph._p.remove(child)


def paragraph_format_snapshot(paragraph):
    p_pr = paragraph._p.pPr
    r_pr = paragraph.runs[0]._r.rPr if paragraph.runs and paragraph.runs[0]._r.rPr is not None else None
    return deepcopy(p_pr) if p_pr is not None else None, deepcopy(r_pr) if r_pr is not None else None


def apply_snapshot(paragraph, snapshot) -> None:
    p_pr, _ = snapshot
    existing_p_pr = paragraph._p.pPr
    if existing_p_pr is not None:
        paragraph._p.remove(existing_p_pr)
    if p_pr is not None:
        paragraph._p.insert(0, deepcopy(p_pr))


def set_template_paragraph(paragraph, text: str, snapshot) -> None:
    clear_paragraph(paragraph)
    apply_snapshot(paragraph, snapshot)
    if text:
        run = paragraph.add_run(text)
        _, r_pr = snapshot
        if r_pr is not None:
            existing = run._r.rPr
            if existing is not None:
                run._r.remove(existing)
            run._r.insert(0, deepcopy(r_pr))


def find_paragraph_index(doc: Document, text: str) -> int:
    for index, paragraph in enumerate(doc.paragraphs):
        if paragraph.text.strip() == text:
            return index
    raise ValueError(f"Template paragraph not found: {text}")


def template_slots(doc: Document, start: int, end: int | None = None) -> list:
    paragraphs = doc.paragraphs[start:end]
    return [paragraph for paragraph in paragraphs if not has_drawing(paragraph)]


def add_or_reuse(slot_iter, doc: Document, text: str, snapshot):
    try:
        paragraph = next(slot_iter)
    except StopIteration:
        paragraph = doc.add_paragraph()
    set_template_paragraph(paragraph, text, snapshot)
    return paragraph


def render_into_source_template(model: dict) -> Document:
    if not SOURCE_WORD_TEMPLATE.exists():
        raise FileNotFoundError(f"Word template not found: {SOURCE_WORD_TEMPLATE}")

    doc = Document(str(SOURCE_WORD_TEMPLATE))
    company_idx = find_paragraph_index(doc, "中国移动香港公司")
    dept_idx = find_paragraph_index(doc, "中国移动香港公司战略部                                                    2026年3月16日")
    toc_idx = find_paragraph_index(doc, "目 录")
    body_idx = find_paragraph_index(doc, "政治资讯")
    body_idx = next(
        index
        for index in range(body_idx + 1, len(doc.paragraphs))
        if doc.paragraphs[index].text.strip() == "政治资讯"
    )

    snapshots = {
        "company": paragraph_format_snapshot(doc.paragraphs[company_idx]),
        "dept": paragraph_format_snapshot(doc.paragraphs[dept_idx]),
        "toc_title": paragraph_format_snapshot(doc.paragraphs[toc_idx]),
        "toc_section": paragraph_format_snapshot(doc.paragraphs[find_paragraph_index(doc, "行业资讯")]),
        "toc_item": paragraph_format_snapshot(doc.paragraphs[find_paragraph_index(doc, "1.【香港施政治理】李家超：今年内完成首份“香港五年规划”，全面对接国家“十五五”规划")]),
        "body_section": paragraph_format_snapshot(doc.paragraphs[body_idx]),
        "body_tag": paragraph_format_snapshot(doc.paragraphs[body_idx + 1]),
        "body_title": paragraph_format_snapshot(doc.paragraphs[body_idx + 2]),
        "body_text": paragraph_format_snapshot(doc.paragraphs[body_idx + 3]),
    }

    for paragraph in doc.paragraphs:
        if not has_drawing(paragraph):
            clear_paragraph(paragraph)

    set_template_paragraph(doc.paragraphs[company_idx], model["company"], snapshots["company"])
    set_template_paragraph(
        doc.paragraphs[dept_idx],
        f"{model['department']}                                                    {model['generatedDate']}",
        snapshots["dept"],
    )
    set_template_paragraph(doc.paragraphs[toc_idx], "目 录", snapshots["toc_title"])

    toc_slots = iter(template_slots(doc, toc_idx + 2, body_idx))
    for section_model in model["sections"]:
        add_or_reuse(toc_slots, doc, section_model["name"], snapshots["toc_section"])
        for item in section_model["items"]:
            add_or_reuse(toc_slots, doc, f"{item['index']}.【{item['tag']}】{item['title']}", snapshots["toc_item"])
        add_or_reuse(toc_slots, doc, "", snapshots["body_text"])

    body_slots = iter(template_slots(doc, body_idx, None))
    for section_model in model["sections"]:
        add_or_reuse(body_slots, doc, section_model["name"], snapshots["body_section"])
        for item in section_model["items"]:
            add_or_reuse(body_slots, doc, item["tag"], snapshots["body_tag"])
            add_or_reuse(body_slots, doc, f"{chinese_order(item['index'])}、{item['title']}", snapshots["body_title"])
            add_or_reuse(body_slots, doc, item["detail"], snapshots["body_text"])
            add_or_reuse(body_slots, doc, "", snapshots["body_text"])

    for paragraph in body_slots:
        clear_paragraph(paragraph)
    return doc


def main() -> None:
    print("============== 开始生成战略内参周报 ==============")
    results = load_results()
    print(f"已加载 {len(results)} 条底层爬取数据。")
    model = build_weekly_model(results)
    
    print("\n--- 报告内容统计 ---")
    for section in model["sections"]:
        print(f"[{section['name']}]: 收录 {len(section['items'])} 条事件")
        
    print("\n--- 正在渲染并导出各格式文件 ---")
    markdown = weekly_to_markdown(model)
    WEEKLY_MD.write_text(markdown, encoding="utf-8")
    TEMPLATE_MD.write_text(weekly_template_markdown(), encoding="utf-8")
    html_text = weekly_to_html(model)
    WEEKLY_HTML.write_text(html_text, encoding="utf-8")
    AGENT_MD_ALIAS.write_text(markdown, encoding="utf-8")
    AGENT_HTML_ALIAS.write_text(html_text, encoding="utf-8")
    weekly_to_docx(model, WEEKLY_DOCX)
    weekly_to_docx(build_template_model(), TEMPLATE_DOCX)
    
    print("\n[生成成功] 最终输出文件：")
    print(" ->", WEEKLY_MD)
    print(" ->", WEEKLY_HTML)
    print(" ->", WEEKLY_DOCX)
    print(" ->", TEMPLATE_MD)
    print(" ->", TEMPLATE_DOCX)
    
    # Archiving logic
    import shutil
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = ROOT / "archives" / timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    shutil.copy2(WEEKLY_MD, archive_dir / WEEKLY_MD.name)
    shutil.copy2(WEEKLY_HTML, archive_dir / WEEKLY_HTML.name)
    shutil.copy2(WEEKLY_DOCX, archive_dir / WEEKLY_DOCX.name)
    
    print(f"\n[归档成功] 已自动备份此次报告至: archives/{timestamp}/")
    print("==================================================")


if __name__ == "__main__":
    main()
