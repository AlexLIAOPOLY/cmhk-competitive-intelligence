from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class WorkspaceReportPreviewTests(unittest.TestCase):
    def test_report_pages_open_with_pdf_preview_instead_of_info_cards(self):
        script = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")

        self.assertIn('if (latest) showReportPreview(latest.path_str);', script)
        self.assertIn('previewRequest: { weekly: 0, performance: 0 }', script)
        self.assertNotIn('function subscriptionPanel()', script)
        self.assertNotIn('function performancePanel()', script)

    def test_pdf_preview_keeps_word_download_fallback(self):
        script = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")

        self.assertIn('class="report-preview-pdf"', script)
        self.assertIn('下载原始 Word', script)


if __name__ == "__main__":
    unittest.main()
