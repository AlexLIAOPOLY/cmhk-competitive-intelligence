from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceReportPreviewTests(unittest.TestCase):
    def test_report_pages_open_with_guidance_before_a_report_is_selected(self):
        script = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")

        self.assertIn('选择一份报告预览', script)
        self.assertIn('点击左侧报告行，在这里阅读和编辑正文', script)
        self.assertNotIn('if (latest) showReportPreview(latest.path_str);', script)
        self.assertIn('previewRequest: { weekly: 0, performance: 0 }', script)
        self.assertIn('activeReportPreview: { weekly: "", performance: "" }', script)
        self.assertNotIn('function subscriptionPanel()', script)
        self.assertNotIn('function performancePanel()', script)

    def test_preview_opens_inline_body_and_preserves_library_on_rebuild(self):
        script = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")

        self.assertIn('CMHKReportEditor?.preview(path, side)', script)
        function = script.split('function renderReports(kind)', 1)[1].split('function reportPreviewPlaceholder', 1)[0]
        self.assertLess(function.index('outputBlock?.remove()'), function.index('panel.innerHTML'))
        self.assertIn('appendChild(outputBlock)', function)

    def test_clicking_the_active_report_again_returns_to_the_preview_guide(self):
        script = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")

        self.assertIn('if (state.activeReportPreview[kind] === path)', script)
        self.assertIn('clearReportPreview(kind);', script)
        self.assertIn('if (side) side.innerHTML = reportPreviewPlaceholder();', script)
        self.assertIn('row.setAttribute("aria-pressed", String(active));', script)
        self.assertIn('取消预览', script)

    def test_only_the_filename_content_opens_the_rename_editor(self):
        app = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
        style = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn('<span class="file-name-cell">${pushChoice}${typeInfo.icon}<i class="report-file-new-dot"', app)
        self.assertIn('<span class="file-name-editable" data-path="${safePath}" title="点击编辑文件名与备注">${file.name}</span>', app)
        self.assertNotIn('class="file-name-cell file-name-editable"', app)
        self.assertIn(".file-name-editable {\n  display: inline-flex;", style)

    def test_all_four_report_row_actions_fit_without_clipping(self):
        style = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn("150px 114px;", style)
        self.assertIn("min-width: 114px;", style)
        self.assertIn("overflow: visible !important;", style)
        self.assertIn("text-overflow: clip !important;", style)

    def test_maximized_preview_overrides_the_report_panel_layout(self):
        style = (ROOT / "web/static/workspace-tabs.css").read_text(encoding="utf-8")

        self.assertIn(".workspace-report-side > .report-preview.is-maximized", style)
        self.assertIn("position: fixed !important", style)
        self.assertIn("height: auto !important", style)
        self.assertIn("max-height: none !important", style)


if __name__ == "__main__":
    unittest.main()
