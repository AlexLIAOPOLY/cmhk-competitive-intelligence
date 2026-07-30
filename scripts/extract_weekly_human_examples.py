#!/usr/bin/env python3
"""Extract complete article content from approved human PDF reports.

The reports used two TOC/body layouts in 2026.  This extractor intentionally
keeps every article's section, subject label, title and body while excluding
the cover, table of contents, distribution list and contact details.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber


NUMBERED_TITLE = re.compile(
    r"^(?P<number>[一二三四五六七八九十百]+、|\d+\s*[.．、])\s*(?P<title>.+)"
)
CHINESE_BODY_TITLE = re.compile(
    r"^(?P<number>[一二三四五六七八九十百]+、)\s*(?P<title>.+)"
)
SUBJECT_PREFIX = re.compile(r"^【(?P<subject>[^】]+)】\s*(?P<title>.+)$")
REPORT_DATE = re.compile(r"战略资讯内参(?P<date>\d{8})")
SECTION_TEXT = {
    "政治资讯",
    "经济资讯",
    "行业资讯",
    "本地运营商资讯",
    "社会资讯",
    "科技资讯",
    "国际资讯",
}
IGNORED_TEXT = (
    "内参资料",
    "商业保密",
    "香港公司战略部",
    "报送：",
    "抄送：",
    "请与战略部",
)


def normalized(value: str) -> str:
    return re.sub(r'[\s“”「」《》【】\-—–，,。:：；;（）()]', "", value).lower()


def clean_text(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", value)
    value = re.sub(r"\s+([，。；：！？、%])", r"\1", value)
    value = re.sub(r"([（“「《【])\s+", r"\1", value)
    value = re.sub(r"\s+([）”」》】])", r"\1", value)
    return value


def page_lines(page) -> list[list[object]]:
    words = page.extract_words(extra_attrs=["size"])
    lines: list[list[object]] = []
    for word in words:
        top = round(word["top"], 1)
        if not lines or abs(float(lines[-1][0]) - top) > 1:
            lines.append([top, float(word["size"]), word["text"]])
        else:
            lines[-1][1] = max(float(lines[-1][1]), float(word["size"]))
            lines[-1][2] = f"{lines[-1][2]} {word['text']}"
    return lines


def toc_entries(pdf) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    section = ""
    for page in pdf.pages[:3]:
        for top, size, text in page_lines(page):
            value = clean_text(str(text))
            section_candidate = value.strip("【】 ")
            if float(size) >= 16 and section_candidate in SECTION_TEXT:
                if current:
                    entries.append(current)
                    current = None
                section = section_candidate
                continue
            match = NUMBERED_TITLE.match(value)
            if match and 15 <= float(size) < 16.5:
                if current:
                    entries.append(current)
                raw_title = match.group("title")
                subject_match = SUBJECT_PREFIX.match(raw_title)
                current = {
                    "section": section,
                    "subject": clean_text(subject_match.group("subject"))
                    if subject_match
                    else "",
                    "title": clean_text(
                        subject_match.group("title") if subject_match else raw_title
                    ),
                }
            elif (
                current
                and 15 <= float(size) < 16.5
                and section_candidate not in SECTION_TEXT
                and float(top) < 730
                and not any(token in str(text) for token in IGNORED_TEXT)
            ):
                current["title"] = clean_text(f"{current['title']} {value}")
    if current:
        entries.append(current)
    if not entries:
        raise RuntimeError("目录中没有识别到文章标题")
    return entries


def extract_pdf(path: Path, issue: int | None = None) -> dict:
    with pdfplumber.open(path) as pdf:
        entries = toc_entries(pdf)
        pages = {
            page_number: page_lines(page)
            for page_number, page in enumerate(pdf.pages, start=1)
        }
        numbered_body_starts = [
            (page_number, line_index)
            for page_number, lines in pages.items()
            for line_index, (_top, size, text) in enumerate(lines)
            if 13 <= float(size) < 15
            and CHINESE_BODY_TITLE.match(clean_text(str(text)))
        ]
        locations = []
        if len(numbered_body_starts) == len(entries):
            # In issues 2-8 every body title is numbered.  Prefer positional
            # matching because a few TOC titles were editorially shortened.
            for entry, (page_number, line_index) in zip(entries, numbered_body_starts):
                lines = pages[page_number]
                target = normalized(entry["title"])
                choices = []
                for line_count in (1, 2, 3):
                    candidate = " ".join(
                        str(line[2]) for line in lines[line_index : line_index + line_count]
                    )
                    choices.append(
                        (
                            difflib.SequenceMatcher(
                                None, target, normalized(candidate)
                            ).ratio(),
                            page_number,
                            line_index,
                            line_count,
                        )
                    )
                locations.append(max(choices))
        else:
            # Issues 9-10 removed body numbering, so locate their headings by
            # title similarity while preserving report order.
            previous_location = (0, 0)
            for entry in entries:
                target = normalized(entry["title"])
                best = None
                for page_number, lines in pages.items():
                    if page_number < previous_location[0]:
                        continue
                    for line_index, (_top, size, _text) in enumerate(lines):
                        if (page_number, line_index) <= previous_location:
                            continue
                        # Body copy/headings are 14pt; TOC titles are 15.5pt.
                        if not 13 <= float(size) < 15:
                            continue
                        for line_count in (1, 2, 3):
                            candidate = " ".join(
                                str(line[2])
                                for line in lines[line_index : line_index + line_count]
                            )
                            score = difflib.SequenceMatcher(
                                None,
                                target,
                                normalized(candidate),
                            ).ratio()
                            if best is None or score > best[0]:
                                best = (score, page_number, line_index, line_count)
                if best is None or best[0] < 0.72:
                    raise RuntimeError(
                        f"未能定位人工样本标题：{entry['title']}（最佳匹配：{best}）"
                    )
                locations.append(best)
                previous_location = (best[1], best[2])

        body_label_set: set[str] = set()
        for lines in pages.values():
            for line_index, (top, size, text) in enumerate(lines):
                candidate = clean_text(str(text)).strip("【】 ")
                previous_top = float(lines[line_index - 1][0]) if line_index else -100.0
                previous_size = float(lines[line_index - 1][1]) if line_index else 0.0
                if (
                    13 <= float(size) < 15
                    and len(candidate) <= 24
                    and not re.search(r"[，。；：！？,.!?%]", candidate)
                    and (
                        float(top) - previous_top > 45
                        or previous_size >= 20
                    )
                ):
                    body_label_set.add(candidate)

        body_subjects: list[str] = []
        for _score, page_number, line_index, _line_count in locations:
            lines = pages[page_number]
            subject = ""
            if line_index:
                _top, _size, text = lines[line_index - 1]
                candidate = clean_text(str(text)).strip("【】 ")
                if candidate in body_label_set:
                    subject = candidate
            body_subjects.append(subject)

        examples = []
        for title_index, entry in enumerate(entries):
            _score, page_number, line_index, line_count = locations[title_index]
            next_location = (
                locations[title_index + 1] if title_index + 1 < len(locations) else None
            )
            end_page = next_location[1] if next_location else max(pages)
            collected: list[tuple[int, float, str]] = []
            for current_page in range(page_number, end_page + 1):
                lines = pages[current_page]
                start = line_index + line_count if current_page == page_number else 0
                end = (
                    next_location[2]
                    if next_location and current_page == next_location[1]
                    else len(lines)
                )
                for top, size, text in lines[start:end]:
                    if float(top) < 70 or float(top) >= 730 or float(size) < 12:
                        continue
                    if any(token in str(text) for token in IGNORED_TEXT):
                        continue
                    collected.append((current_page, float(top), str(text).strip()))

            # The next article's subject label appears immediately before its
            # title and therefore falls inside the previous article's range.
            if next_location and collected:
                next_entry = entries[title_index + 1]
                removable_labels = SECTION_TEXT | body_label_set | {
                    clean_text(next_entry.get("section", "")).strip("【】 "),
                    clean_text(next_entry.get("subject", "")).strip("【】 "),
                    body_subjects[title_index + 1],
                } - {""}
                while collected:
                    trailing = clean_text(collected[-1][2]).strip("【】 ")
                    if trailing not in removable_labels:
                        break
                    collected.pop()

            detail = clean_text(" ".join(value[2] for value in collected))
            detail = re.sub(r"(?:终端产品|人工智能)$", "", detail)
            if len(detail) < 100:
                raise RuntimeError(
                    f"人工样本正文提取不完整：{entry['title']}（{len(detail)}字）"
                )
            title_lines = " ".join(
                str(line[2])
                for line in pages[page_number][line_index : line_index + line_count]
            )
            body_title = clean_text(title_lines)
            numbered_match = CHINESE_BODY_TITLE.match(body_title)
            if numbered_match:
                body_title = clean_text(numbered_match.group("title"))
            subject_match = SUBJECT_PREFIX.match(body_title)
            if subject_match:
                body_title = clean_text(subject_match.group("title"))
            if (
                len(body_title) > 150
                or difflib.SequenceMatcher(
                    None, normalized(entry["title"]), normalized(body_title)
                ).ratio()
                < 0.5
            ):
                body_title = entry["title"]
            examples.append(
                {
                    "section": entry["section"],
                    "subject": entry["subject"] or body_subjects[title_index],
                    "title": body_title,
                    "detail": detail,
                }
            )
        source_date = REPORT_DATE.search(path.name)
        return {
            "issue": issue,
            "source_file": path.name,
            "report_date": (
                datetime.strptime(source_date.group("date"), "%Y%m%d")
                .date()
                .isoformat()
                if source_date
                else ""
            ),
            "articles": examples,
        }


def report_fingerprint(report: dict) -> str:
    content = "\n".join(
        normalized(
            f"{article.get('section', '')}{article.get('subject', '')}"
            f"{article.get('title', '')}{article.get('detail', '')}"
        )
        for article in report.get("articles") or []
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def deduplicate_reports(reports: list[dict]) -> tuple[list[dict], list[dict]]:
    unique: list[dict] = []
    duplicates: list[dict] = []
    fingerprints: dict[str, str] = {}
    for report in reports:
        fingerprint = report_fingerprint(report)
        source_file = report["source_file"]
        if fingerprint in fingerprints:
            duplicates.append(
                {
                    "source_file": source_file,
                    "duplicate_of": fingerprints[fingerprint],
                    "content_sha256": fingerprint,
                }
            )
            continue
        report["content_sha256"] = fingerprint
        fingerprints[fingerprint] = source_file
        unique.append(report)
    return unique, duplicates


def main() -> int:
    if len(sys.argv) < 3:
        print("用法：extract_weekly_human_examples.py 输入1.pdf [输入2.pdf ...] 输出.json")
        return 2
    paths = [Path(value) for value in sys.argv[1:-1]]
    output = Path(sys.argv[-1])
    reports = [extract_pdf(path) for path in paths]
    unique, duplicates = deduplicate_reports(reports)
    examples = [
        {
            **article,
            "report_date": report["report_date"],
            "source_file": report["source_file"],
        }
        for report in unique
        for article in report["articles"]
    ]
    output.write_text(
        json.dumps(
            {
                "description": "香港公司人工《战略资讯内参》非重复期完整文章内容",
                "source_file_count": len(paths),
                "unique_report_count": len(unique),
                "duplicate_report_count": len(duplicates),
                "duplicates": duplicates,
                "reports": [
                    {
                        key: value
                        for key, value in report.items()
                        if key != "articles"
                    }
                    | {"article_count": len(report["articles"])}
                    for report in unique
                ],
                "examples": examples,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"已从{len(paths)}个文件提取{len(unique)}期、{len(examples)}篇完整文章；"
        f"整期重复{len(duplicates)}个 -> {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
