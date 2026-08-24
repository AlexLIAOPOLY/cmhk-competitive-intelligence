from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReportFileEditThemeTests(unittest.TestCase):
    def test_shared_editor_uses_dark_workspace_palette(self):
        style = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn(".dashboard-page #fileEditModal", style)
        self.assertIn("background: rgba(1, 10, 17, .78)", style)
        self.assertIn("#fileEditModal .file-edit-modal", style)
        self.assertIn("background: linear-gradient(145deg", style)

    def test_editor_title_matches_weekly_or_performance_report(self):
        index = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "web/static/app.js").read_text(encoding="utf-8")

        self.assertIn('id="fileEditTitle"', index)
        self.assertIn('file.reportType === "carrier-performance" ? "业绩摘要" : "周报"', script)
        self.assertIn("`编辑${reportLabel}信息`", script)


if __name__ == "__main__":
    unittest.main()
