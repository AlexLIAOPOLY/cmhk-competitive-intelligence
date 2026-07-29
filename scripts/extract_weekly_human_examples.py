#!/usr/bin/env python3
"""Extract complete title/body examples from the two approved human PDF reports."""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

import pdfplumber


NUMBERED_TITLE = re.compile(r"^([一二三四五六七八九十百]+)、\s*(.+)")
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


def toc_titles(pdf) -> list[str]:
    titles: list[str] = []
    current = ""
    for page in pdf.pages[:3]:
        for top, size, text in page_lines(page):
            match = NUMBERED_TITLE.match(str(text).strip())
            if match and float(size) >= 15:
                if current:
                    titles.append(current)
                current = match.group(2).strip()
            elif (
                current
                and float(size) >= 15
                and not str(text).startswith("【")
                and float(top) < 730
                and not any(token in str(text) for token in IGNORED_TEXT)
            ):
                current += f" {str(text).strip()}"
    if current:
        titles.append(current)
    titles[-1] = re.sub(r"\s+政治资讯\s+经济资讯$", "", titles[-1])
    return titles


def extract_pdf(path: Path, issue: int) -> list[dict]:
    with pdfplumber.open(path) as pdf:
        titles = toc_titles(pdf)
        pages = {
            page_number: page_lines(page)
            for page_number, page in enumerate(pdf.pages[2:], start=3)
        }
        locations = []
        for title in titles:
            target = normalized(title)
            best = None
            for page_number, lines in pages.items():
                for line_index, (_top, size, _text) in enumerate(lines):
                    if float(size) < 13:
                        continue
                    for line_count in (1, 2, 3):
                        candidate = " ".join(
                            str(line[2]) for line in lines[line_index : line_index + line_count]
                        )
                        score = difflib.SequenceMatcher(
                            None,
                            target,
                            normalized(candidate),
                        ).ratio()
                        if best is None or score > best[0]:
                            best = (score, page_number, line_index, line_count)
            if best is None or best[0] < 0.85:
                raise RuntimeError(f"未能定位人工样本标题：{title}")
            locations.append(best)

        examples = []
        for title_index, title in enumerate(titles):
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

            # The next article's subject label sits after a large vertical gap.
            cut = None
            for index in range(1, len(collected)):
                same_page = collected[index][0] == collected[index - 1][0]
                if same_page and collected[index][1] - collected[index - 1][1] > 48:
                    cut = index
            if cut is not None and len(collected) - cut <= 2:
                trailing = "".join(value[2] for value in collected[cut:])
                if len(trailing) < 40:
                    collected = collected[:cut]

            detail = "".join(value[2] for value in collected).replace(" ", "")
            detail = re.sub(r"(?:终端产品|人工智能)$", "", detail)
            if len(detail) < 100:
                raise RuntimeError(f"人工样本正文提取不完整：{title}（{len(detail)}字）")
            examples.append(
                {
                    "issue": issue,
                    "title": title.replace(" ", ""),
                    "detail": detail,
                }
            )
        return examples


def main() -> int:
    if len(sys.argv) != 4:
        print("用法：extract_weekly_human_examples.py 第九期.pdf 第十期.pdf 输出.json")
        return 2
    first, second, output = map(Path, sys.argv[1:])
    examples = extract_pdf(first, 9) + extract_pdf(second, 10)
    if len(examples) != 38:
        raise RuntimeError(f"应提取38条人工样本，实际{len(examples)}条")
    output.write_text(
        json.dumps(
            {
                "description": "香港公司人工《战略资讯内参》第九期和第十期完整标题正文样本",
                "examples": examples,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"已提取{len(examples)}条 -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
