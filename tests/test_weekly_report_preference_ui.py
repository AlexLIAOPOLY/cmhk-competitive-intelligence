import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WeeklyReportPreferenceUiTests(unittest.TestCase):
    def test_weekly_tab_selects_the_next_push_version_and_syncs_subscription_page(self):
        app = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("data-weekly-push-path", app)
        self.assertIn("/api/weekly-report-preference", app)
        self.assertIn('action: "setWeeklyReportPreference"', app)
        self.assertIn('type: "cmhk-weekly-report-preference"', app)
        self.assertIn(".weekly-push-choice", styles)
        self.assertIn("下次推送", app)

    def test_performance_tab_selects_the_next_push_version_and_syncs_subscription_page(self):
        app = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("data-performance-push-path", app)
        self.assertIn("/api/performance-report-preference", app)
        self.assertIn('action: "setPerformanceReportPreference"', app)
        self.assertIn('type: "cmhk-performance-report-preference"', app)
        self.assertIn("业绩摘要推送版本保存失败", app)


if __name__ == "__main__":
    unittest.main()
