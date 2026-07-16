from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.shared import RGBColor

import generate_weekly_report as report


def detailed_text(prefix: str, event_date: str = "2026年7月12日") -> str:
    return report.ensure_detailed_paragraph(
        f"据测试来源于{event_date}发布的信息，{prefix}"
        + "公开资料说明事项的业务背景、当前进展及可核验边界。"
        + "相关变化需要结合后续正式披露持续跟踪，本报告不对来源以外的信息作确定性推断。",
        min_chars=120,
        max_chars=300,
    )


def make_item(item_id: str, index: int, *, title: str | None = None) -> dict:
    return {
        "id": item_id,
        "row": f"row-{index}",
        "index": index,
        "localIndex": index,
        "section": "行业资讯",
        "subject": f"测试主体{index}",
        "tag": "业务动态",
        "title": title or f"测试事件{index}",
        "detail": detailed_text(f"测试主体{index}公布一项最新业务进展。"),
        "rawDetail": f"测试主体{index}公布一项最新业务进展。",
        "eventAt": "2026-07-12",
        "sourceIds": [f"S{index}"],
        "sourceName": "测试来源",
    }


def make_model(item: dict | None = None) -> dict:
    value = item or make_item("W001", 1)
    source_id = value["sourceIds"][0]
    return {
        "company": "中国移动香港公司",
        "department": "中国移动香港公司战略部",
        "generatedDate": "2026年7月15日",
        "title": "战略内参",
        "range": {"start": "2026-07-02", "end": "2026-07-15"},
        "toc": [
            {
                "index": value["index"],
                "section": "行业资讯",
                "tag": value["tag"],
                "title": value["title"],
            }
        ],
        "sections": [{"name": "行业资讯", "narrative": "", "items": [value]}],
        "sources": [
            {
                "sourceId": source_id,
                "row": value["row"],
                "section": "行业资讯",
                "title": value["title"],
                "url": f"https://example.test/{source_id}",
                "sourceName": "测试来源",
                "object": value["subject"],
                "tag": value["tag"],
                "publishedAt": value["eventAt"],
            }
        ],
    }


def write_small_template(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("中国移动香港公司")
    doc.add_paragraph("中国移动香港公司战略部    YYYY年M月D日")
    doc.add_paragraph("目 录")
    doc.add_paragraph("")
    for section_name in report.SECTION_ORDER:
        doc.add_paragraph(section_name)
        doc.add_paragraph("1.【标签】一句话事件标题")
    doc.add_paragraph("")
    doc.add_paragraph("政治资讯")
    tag = doc.add_paragraph()
    tag_run = tag.add_run("标签")
    tag_run.font.color.rgb = RGBColor(0xA6, 0xA6, 0xA6)
    doc.add_paragraph("一、一句话事件标题")
    doc.add_paragraph("事件事实正文。")
    doc.add_paragraph("")
    doc.save(path)


class PublicationLabelTests(unittest.TestCase):
    def test_each_event_label_uses_publication_date_not_generation_or_crawl_time(self) -> None:
        row = {
            "id": "row-publication-date",
            "company": "测试主体",
            "metric": "业务动态",
            "value": "测试事实",
            "generatedAt": "2026-07-15T09:30:00+08:00",
            "fetched_at_hkt": "2026-07-15T09:31:00+08:00",
            "sources": [
                {
                    "url": "https://example.test/article",
                    "publishedAt": "2026-07-12T18:20:00+08:00",
                }
            ],
        }
        included, _ = report.filter_biweekly_rows(
            [row],
            now=report.parse_report_date("2026-07-15T10:00:00+08:00"),
        )
        self.assertEqual(included[0]["publicationDate"], "2026-07-12")

        item = make_item("W001", 1)
        item["eventAt"] = included[0]["publicationDate"]
        item["generatedAt"] = row["generatedAt"]
        item["reviewDecision"] = "approve"
        model = make_model(item)
        markdown = report.weekly_to_markdown(model)

        self.assertIn("发布时间：2026年7月12日", markdown)
        self.assertNotIn("发布时间：2026年7月15日", markdown)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            template_path = temp_path / "template.docx"
            output_path = temp_path / "report.docx"
            write_small_template(template_path)
            with patch.object(report, "SOURCE_WORD_TEMPLATE", template_path):
                report.weekly_to_docx(model, output_path)
            rendered = Document(output_path)
            rendered_text = "\n".join(paragraph.text for paragraph in rendered.paragraphs)

        self.assertIn("发布时间：2026年7月12日", rendered_text)
        self.assertNotIn("发布时间：2026年7月15日", rendered_text)

    def test_each_detail_must_put_the_locked_publication_date_in_the_first_sentence(self) -> None:
        valid = detailed_text("测试主体公布一项新进展。")
        misplaced = report.ensure_detailed_paragraph(
            "测试主体公布一项新进展。"
            "据测试来源于2026年7月12日发布的信息，相关部署已经开始。"
            "公开资料说明了当前进展与可核验边界。"
        )

        self.assertTrue(report.detail_mentions_publication_date(valid, "2026-07-12"))
        self.assertFalse(report.detail_mentions_publication_date(misplaced, "2026-07-12"))

        item = make_item("W001", 1)
        item["detail"] = misplaced
        item["reviewDecision"] = "approve"
        model = make_model(item)
        with self.assertRaisesRegex(ValueError, "首句未写明公开发布时间"):
            report.validate_report_model(model)

        item["detail"] = valid
        report.validate_report_model(model)

    def test_overlong_detail_is_trimmed_only_at_a_complete_sentence(self) -> None:
        detail = (
            "据测试来源于2026年7月12日发布的信息，测试主体公布第一项可核验进展。"
            + "第二句补充实施背景、参与主体和当前执行安排。" * 3
            + "第三部分继续列出后续计划、业务范围和正式披露中的事实。" * 3
            + "最后一句提供仍需持续观察的公开指标与进度。" * 3
        )

        trimmed = report.trim_weekly_detail(detail, max_chars=180)

        self.assertLessEqual(len(re.sub(r"\s+", "", trimmed)), 180)
        self.assertGreaterEqual(len(re.findall(r"[。！？!?]", trimmed)), 3)
        self.assertTrue(trimmed.endswith("。"))
        self.assertNotIn("…", trimmed)

        item = make_item("W001", 1)
        item["detail"] = detailed_text("测试主体公布一项新进展。")[:-1] + "…"
        item["reviewDecision"] = "approve"
        with self.assertRaisesRegex(ValueError, "截断省略号"):
            report.validate_report_model(make_model(item))


class StrategicReferenceDocxStructureTests(unittest.TestCase):
    def test_body_order_and_gray_tag_match_the_strategic_reference_format(self) -> None:
        item = make_item("W001", 1, title="测试主体推进新一轮业务部署")
        model = make_model(item)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            template_path = temp_path / "template.docx"
            output_path = temp_path / "report.docx"
            write_small_template(template_path)
            with patch.object(report, "SOURCE_WORD_TEMPLATE", template_path):
                report.weekly_to_docx(model, output_path)
            rendered = Document(output_path)

        texts = [paragraph.text.strip() for paragraph in rendered.paragraphs]
        body_start = texts.index("行业资讯")
        self.assertEqual(
            texts[body_start : body_start + 5],
            [
                "行业资讯",
                "业务动态",
                item["title"],
                item["detail"],
                "发布时间：2026年7月12日　来源：[S1] 测试来源",
            ],
        )
        self.assertFalse(re.match(r"^(?:\d+|[一二三四五六七八九十]+)、", texts[body_start + 2]))

        tag_paragraph = rendered.paragraphs[body_start + 1]
        self.assertTrue(tag_paragraph.runs)
        self.assertEqual(tag_paragraph.runs[0].font.color.rgb, RGBColor(0xA6, 0xA6, 0xA6))


class IndependentReviewerTests(unittest.TestCase):
    def test_independent_reviewer_approves_revises_and_rejects_per_item(self) -> None:
        items = [make_item(f"W00{index}", index) for index in range(1, 4)]
        revised_detail = detailed_text("独立审核模型根据原始事实修订了第二条的表述。")
        reviewer_response = {
            "items": [
                {
                    "id": "W001",
                    "decision": "approve",
                    "scores": {"factuality": 5, "detail": 5, "relevance": 5, "language": 5},
                    "reason": "事实、日期与来源一致",
                },
                {
                    "id": "W002",
                    "decision": "revise",
                    "scores": {"factuality": 5, "detail": 5, "relevance": 4, "language": 5},
                    "title": "独立审核后的修订标题",
                    "detail": revised_detail,
                    "reason": "原文需要弱化确定性结论",
                },
                {
                    "id": "W003",
                    "decision": "reject",
                    "scores": {"factuality": 2, "detail": 3, "relevance": 3, "language": 4},
                    "reason": "证据不足以支持正文",
                },
            ]
        }
        progress_events: list[tuple[tuple, dict]] = []

        def progress(*args, **kwargs) -> None:
            progress_events.append((args, kwargs))

        with tempfile.TemporaryDirectory() as temp_dir:
            review_cache = Path(temp_dir) / "review-cache.json"
            with (
                patch.object(report, "WEEKLY_REVIEW_CACHE", review_cache, create=True),
                patch.object(
                    report,
                    "_call_weekly_quality_reviewer_llm",
                    return_value=reviewer_response,
                ) as reviewer_call,
                patch.object(
                    report,
                    "_call_weekly_writer_llm",
                    side_effect=AssertionError("审核不得复用写作模型调用"),
                ) as writer_call,
            ):
                reviewed, audit = report.review_weekly_items_with_ai(
                    items,
                    progress=progress,
                    bypass_cache=True,
                )

        reviewer_call.assert_called()
        writer_call.assert_not_called()
        self.assertEqual([item["id"] for item in reviewed], ["W001", "W002"])
        self.assertEqual(reviewed[0]["reviewDecision"], "approve")
        self.assertEqual(reviewed[1]["reviewDecision"], "revise")
        self.assertEqual(reviewed[1]["title"], "独立审核后的修订标题")
        self.assertEqual(reviewed[1]["detail"], revised_detail)
        self.assertEqual(reviewed[1]["sourceIds"], items[1]["sourceIds"])
        self.assertEqual(reviewed[1]["eventAt"], items[1]["eventAt"])
        self.assertEqual(audit["approvedItems"], 1)
        self.assertEqual(audit["revisedItems"], 1)
        self.assertEqual(audit["rejectedItems"], 1)
        rejected = [entry for entry in audit["items"] if entry["decision"] == "reject"]
        self.assertEqual([entry["id"] for entry in rejected], ["W003"])
        self.assertTrue(progress_events)

    def test_unreviewed_or_writer_only_item_cannot_pass_quality_gate(self) -> None:
        item = make_item("W001", 1)
        item["writerStatus"] = "llm"
        item["qualityStatus"] = "passed"
        model = make_model(item)

        with self.assertRaisesRegex(ValueError, "审核"):
            report.validate_review_gate(model)
        with self.assertRaisesRegex(ValueError, "审核"):
            report.validate_report_model(model)

        item["reviewDecision"] = "approve"
        report.validate_review_gate(model)
        report.validate_report_model(model)


class QualitySidecarTests(unittest.TestCase):
    def test_every_written_docx_gets_a_bound_quality_sidecar(self) -> None:
        item = make_item("W001", 1)
        item.update(
            {
                "reviewDecision": "approve",
                "reviewReason": "日期、事实与来源一致",
            }
        )
        model = make_model(item)
        model.update(
            {
                "range": {"start": "2026-07-07", "end": "2026-07-15"},
                "plannedRange": {"start": "2026-07-07", "end": "2026-07-17"},
                "periodStatus": "draft",
                "issueDate": "2026-07-17",
                "asOf": "2026-07-15T10:00:00+08:00",
            }
        )
        model["reviewAudit"] = {
            "reviewStatus": "passed",
            "approved": 1,
            "revised": 0,
            "rejected": 0,
            "items": [
                {
                    "id": "W001",
                    "reviewDecision": "approve",
                    "reason": item["reviewReason"],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            template_path = temp_path / "template.docx"
            output_path = temp_path / "report.docx"
            write_small_template(template_path)
            with patch.object(report, "SOURCE_WORD_TEMPLATE", template_path):
                report.weekly_to_docx(model, output_path)

            expected_sidecar = Path(str(output_path) + ".quality.json")
            self.assertEqual(report.weekly_quality_sidecar_path(output_path), expected_sidecar)
            self.assertTrue(expected_sidecar.exists())
            payload = json.loads(expected_sidecar.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportFile"], "report.docx")
        self.assertEqual(payload["reviewStatus"], "passed")
        self.assertEqual(payload["window"], {"start": "2026-07-07", "end": "2026-07-15"})
        self.assertEqual(payload["plannedWindow"], {"start": "2026-07-07", "end": "2026-07-17"})
        self.assertEqual(payload["periodStatus"], "draft")
        self.assertEqual(payload["issueDate"], "2026-07-17")
        self.assertEqual(payload["items"][0]["reviewDecision"], "approve")


class LlmCacheBypassTests(unittest.TestCase):
    def test_writer_cache_can_be_bypassed_for_a_fresh_llm_review_cycle(self) -> None:
        item = make_item("W001", 1, title="原始标题")
        cached_detail = detailed_text("这是写作缓存中的旧段落。")
        fresh_detail = detailed_text("这是强制绕过缓存后由模型重新生成的段落。")
        cached_result = {"status": "ok", "title": "缓存中的旧标题", "detail": cached_detail}
        fresh_result = {
            "items": [
                {
                    "id": "W001",
                    "status": "ok",
                    "title": "绕过缓存后的新标题",
                    "detail": fresh_detail,
                    "used_fact_ids": ["F001"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "writer-cache.json"
            cache_path.write_text(json.dumps({"known-key": cached_result}, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(report, "WEEKLY_LLM_CACHE", cache_path),
                patch.object(report, "_weekly_writer_cache_key", return_value="known-key"),
                patch.object(report, "load_ai_config", return_value={"model": "deepseek-v4"}),
                patch.object(report, "_call_weekly_writer_llm", return_value=fresh_result) as llm_call,
            ):
                cached = report.enrich_weekly_items_with_llm([item], progress=lambda *args, **kwargs: None)
                llm_call.assert_not_called()
                self.assertEqual(cached[0]["writerStatus"], "cache")
                self.assertEqual(cached[0]["title"], "缓存中的旧标题")

                fresh = report.enrich_weekly_items_with_llm(
                    [item],
                    progress=lambda *args, **kwargs: None,
                    bypass_cache=True,
                )

        llm_call.assert_called()
        self.assertEqual(fresh[0]["writerStatus"], "llm")
        self.assertEqual(fresh[0]["title"], "绕过缓存后的新标题")
        self.assertNotEqual(fresh[0]["detail"], cached[0]["detail"])


if __name__ == "__main__":
    unittest.main()
