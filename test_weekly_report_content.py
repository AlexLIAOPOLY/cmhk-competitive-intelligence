from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document

from generate_weekly_report import curated_section, localized_weekly_value
from tts_service import build_audio_summary


class WeeklyReportContentTests(unittest.TestCase):
    def test_political_english_fact_is_localized_to_concrete_chinese(self):
        row = {
            "company": "政治新闻",
            "metric": "重大政策/声明",
            "value": "166 foreign-invested enterprises approved for value-added telecom services",
            "detail": "片段中明确提到'166家外资企业获增值电信业务经营试点批复'",
        }
        value = localized_weekly_value(row, limit=120)
        self.assertIn("166家", value)
        self.assertIn("增值电信业务", value)
        self.assertNotIn("相关动态更新", value)

    def test_regulator_fact_is_classified_as_political(self):
        self.assertEqual(
            curated_section(
                {
                    "company": "通信监管机构",
                    "group": "",
                    "metricCategory": "客户经营",
                }
            ),
            "政治资讯",
        )

    def test_offline_audio_summary_covers_multiple_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.docx"
            doc = Document()
            doc.add_paragraph("政治资讯")
            doc.add_paragraph("一、政策事件")
            doc.add_paragraph("工信部批准166家外资企业开展增值电信业务经营试点。")
            doc.add_paragraph("行业资讯")
            doc.add_paragraph("二、友商业绩")
            doc.add_paragraph("香港友商公布最新经营收入及网络投资安排。")
            doc.add_paragraph("国际资讯")
            doc.add_paragraph("三、国际运营商动态")
            doc.add_paragraph("国际运营商继续推进人工智能云和网络基础设施投资。")
            doc.save(path)

            with patch("tts_service._generate_audio_summary_with_llm", return_value=None):
                summary = build_audio_summary(path)

        self.assertIn("政治资讯方面", summary)
        self.assertIn("行业资讯方面", summary)
        self.assertIn("国际资讯方面", summary)
        self.assertGreater(len(summary), 120)


if __name__ == "__main__":
    unittest.main()
