from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from docx import Document


ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "carrier_performance_template.docx"
DATA_PATH = ROOT / "carrier_performance_data.json"


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


def render_report() -> Path:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"模板不存在：{TEMPLATE_PATH}")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
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
    if len(body) != len(body_slots):
        raise ValueError(f"正文模板槽位不匹配：模板 {len(body_slots)} 段，数据 {len(body)} 段")
    for paragraph, text in zip(body_slots, body):
        replace_paragraph_text(paragraph, text)

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
