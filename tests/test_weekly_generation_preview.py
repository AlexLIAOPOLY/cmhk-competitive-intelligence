from datetime import datetime
from pathlib import Path
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

import web_app


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web" / "static" / "styles.css").read_text(encoding="utf-8")


class WeeklyGenerationPreviewTests(TestCase):
    def test_backend_preview_uses_exact_generation_window_and_selected_rows(self) -> None:
        now = datetime(2026, 8, 19, 15, 30, tzinfo=ZoneInfo("Asia/Hong_Kong"))
        rows = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
        audit = {
            "selectionSource": "feishu_review_sheet",
            "acceptedRows": 8,
            "excludedRows": 5,
        }

        with mock.patch(
            "cmhk.intelligence.news_review_sheet.load_weekly_report_candidates",
            return_value=(rows, audit),
        ) as load_candidates:
            preview = web_app.build_weekly_report_generation_preview(now)

        load_candidates.assert_called_once_with("2026-08-06", "2026-08-19")
        self.assertEqual(preview["windowStart"], "2026-08-06")
        self.assertEqual(preview["windowEnd"], "2026-08-19")
        self.assertEqual(preview["newsCount"], 3)
        self.assertEqual(preview["acceptedRows"], 8)
        self.assertEqual(preview["excludedRows"], 5)

    def test_frontend_refreshes_preview_on_each_weekly_tab_entry(self) -> None:
        self.assertIn('fetch("/api/weekly-report-preview"', APP)
        self.assertIn('cache: "no-store"', APP)
        self.assertIn('if (reportType === "weekly") refreshWeeklyGenerationPreview();', APP)
        self.assertIn('preview.id = "weeklyGenerationPreview"', APP)
        self.assertIn('`${Number(data.newsCount || 0)} 条入报新闻`', APP)
        self.assertIn("本次生成范围", APP)
        self.assertIn("actions.insertBefore(preview, els.generateButtonSecondary)", APP)

    def test_preview_is_immediately_before_generate_button(self) -> None:
        self.assertIn(".weekly-generation-preview", STYLES)
        self.assertIn("order: -2", STYLES)
        self.assertIn("#generateButtonSecondary", STYLES)
        self.assertIn("order: -1", STYLES)


if __name__ == "__main__":
    import unittest

    unittest.main()
