from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class WorkspaceReportPreviewTests(unittest.TestCase):
    def test_report_pages_open_with_guidance_before_a_report_is_selected(self):
        script = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")

        self.assertIn('选择一份报告预览', script)
        self.assertIn('点击左侧报告行，在这里查看对应的 PDF 文件', script)
        self.assertNotIn('if (latest) showReportPreview(latest.path_str);', script)
        self.assertIn('previewRequest: { weekly: 0, performance: 0 }', script)
        self.assertNotIn('function subscriptionPanel()', script)
        self.assertNotIn('function performancePanel()', script)

    def test_pdf_preview_keeps_word_download_fallback(self):
        script = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")

        self.assertIn('class="report-preview-pdf"', script)
        self.assertIn('下载原始 Word', script)

    def test_only_the_filename_content_opens_the_rename_editor(self):
        app = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
        style = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn('<span class="file-name-cell"><span class="file-name-editable"', app)
        self.assertNotIn('class="file-name-cell file-name-editable"', app)
        self.assertIn(".file-name-editable {\n  display: inline-flex;", style)

    def test_maximized_preview_overrides_the_report_panel_layout(self):
        style = (ROOT / "web/static/workspace-tabs.css").read_text(encoding="utf-8")

        self.assertIn(".workspace-report-side > .report-preview.is-maximized", style)
        self.assertIn("position: fixed !important", style)
        self.assertIn("height: auto !important", style)
        self.assertIn("max-height: none !important", style)


if __name__ == "__main__":
    unittest.main()
