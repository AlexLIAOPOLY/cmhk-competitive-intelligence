import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from cmhk.reporting.docx_editor import load_docx_for_editor, save_editor_document, sha256_file
import web_app


ROOT = Path(__file__).resolve().parents[1]


class ReportEditorRoundTripTests(unittest.TestCase):
    def test_docx_round_trip_preserves_page_header_table_and_writes_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "8月30日周报.docx"
            target = root / "8月30日周报（编辑稿）.docx"
            document = Document()
            section = document.sections[0]
            section.header.paragraphs[0].text = "CMHK 战略竞对中心"
            title = document.add_heading("战略双周报", level=1)
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph = document.add_paragraph()
            paragraph.add_run("原始内容").bold = True
            table = document.add_table(rows=2, cols=2)
            table.style = "Table Grid"
            table.cell(0, 0).text = "指标"
            table.cell(0, 1).text = "结果"
            table.cell(1, 0).text = "收入"
            table.cell(1, 1).text = "100"
            document.save(source)

            payload = load_docx_for_editor(source)
            payload["document"]["content"][1]["content"][0]["text"] = "页面编辑后的真实内容"
            result = save_editor_document(source, target, payload["document"])
            reopened = Document(target)

            self.assertEqual(reopened.sections[0].header.paragraphs[0].text, "CMHK 战略竞对中心")
            self.assertEqual(reopened.sections[0].page_width, section.page_width)
            self.assertIn("页面编辑后的真实内容", "\n".join(item.text for item in reopened.paragraphs))
            self.assertEqual(len(reopened.tables), 1)
            self.assertEqual(reopened.tables[0].cell(1, 1).text, "100")
            self.assertEqual(result["sha256"], sha256_file(target))
            self.assertNotEqual(sha256_file(source), sha256_file(target))

    def test_editor_payload_exposes_page_and_revision_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "业绩摘要.docx"
            document = Document()
            document.add_paragraph("摘要正文")
            document.save(source)

            payload = load_docx_for_editor(source)

            self.assertEqual(payload["name"], source.name)
            self.assertEqual(payload["sourceSha256"], sha256_file(source))
            self.assertGreater(payload["page"]["widthIn"], 7)
            self.assertEqual(payload["document"]["type"], "doc")


class ReportEditorServiceTests(unittest.TestCase):
    def test_generated_report_saves_as_edit_copy_then_updates_with_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data" / "reporting").mkdir(parents=True)
            source = root / "8月30日周报.docx"
            document = Document()
            document.add_paragraph("正式生成内容")
            document.save(source)

            def fake_preview(report_path):
                preview = root / "web" / "static" / "report-previews" / f"{report_path.stem}.pdf"
                preview.parent.mkdir(parents=True, exist_ok=True)
                preview.write_bytes(b"%PDF-test")
                return preview

            with (
                mock.patch.object(web_app, "ROOT", root),
                mock.patch.object(web_app, "REPORT_METADATA_PATH", root / "data" / "reporting" / "report_file_metadata.json"),
                mock.patch.object(web_app, "build_status", return_value={"outputs": []}),
                mock.patch.object(web_app, "delete_audio_for_report"),
                mock.patch.object(web_app, "report_audio_metadata", return_value={"exists": False}),
                mock.patch("cmhk.reporting.pdf_preview.convert_docx_to_pdf_preview", side_effect=fake_preview),
            ):
                opened = web_app.load_report_editor_payload(source.name)
                opened["document"]["content"][0]["content"][0]["text"] = "第一次页面编辑"
                first = web_app.save_report_editor_payload({
                    "path": source.name,
                    "sourceSha256": opened["sourceSha256"],
                    "saveMode": "update",
                    "document": opened["document"],
                }, actor={"display_name": "测试编辑者"})
                reopened = web_app.load_report_editor_payload(first["path"])
                reopened["document"]["content"][0]["content"][0]["text"] = "第二次页面编辑"
                second = web_app.save_report_editor_payload({
                    "path": first["path"],
                    "sourceSha256": reopened["sourceSha256"],
                    "saveMode": "update",
                    "document": reopened["document"],
                }, actor={"display_name": "测试编辑者"})

            self.assertEqual(Document(source).paragraphs[0].text, "正式生成内容")
            self.assertEqual(first["path"], "8月30日周报（编辑稿）.docx")
            self.assertEqual(second["path"], first["path"])
            self.assertEqual(Document(root / second["path"]).paragraphs[0].text, "第二次页面编辑")
            metadata = web_app.json.loads((root / "data" / "reporting" / "report_file_metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata[first["path"]]["isEdited"])
            self.assertEqual(metadata[first["path"]]["editorRevision"], 2)
            self.assertEqual(metadata[first["path"]]["sourcePath"], source.name)
            self.assertEqual(len(list((root / "archives" / "report_edits").rglob("*.docx"))), 1)


class ReportEditorUiTests(unittest.TestCase):
    def test_word_like_editor_is_local_full_screen_and_available_from_both_report_surfaces(self):
        index = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
        app = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
        workspace = (ROOT / "web/static/workspace-tabs.js").read_text(encoding="utf-8")
        source = (ROOT / "web/static/report-editor-source.js").read_text(encoding="utf-8")
        style = (ROOT / "web/static/report-editor.css").read_text(encoding="utf-8")
        bundle = ROOT / "web/static/vendor/tiptap-report-editor-3.30.5.min.js"
        bundle_source = bundle.read_text(encoding="utf-8")

        self.assertIn('id="reportEditorModal"', index)
        self.assertIn('id="reportEditorRibbon"', index)
        self.assertIn('class="report-editor-modal"', index)
        self.assertIn("position: fixed; inset: 0; z-index: 4000", style)
        self.assertIn("EditorTable", source)
        self.assertIn("replaceAll", source)
        self.assertIn("cmhk-report-editor-draft", source)
        self.assertEqual(source.count('data-custom-select="native"'), 4)
        self.assertEqual(bundle_source.count('data-custom-select="native"'), 4)
        self.assertNotIn("underline: false", source)
        self.assertIn("preferredZoom", source)
        self.assertIn('id="reportEditorZoom" type="range" min="35"', index)
        self.assertIn('class="row-icon-button edit-report-button"', app)
        self.assertIn("data-report-editor-path", workspace)
        self.assertIn("/api/report-editor", source)
        self.assertTrue(bundle.is_file())
        self.assertGreater(bundle.stat().st_size, 300_000)
        self.assertIn("tiptap-report-editor-3.30.5.min.js?v=3", index)
        self.assertNotIn("cdn.jsdelivr", index)
        self.assertNotIn("unpkg.com", index)

    def test_subscription_page_selects_weekly_version_and_shows_day_hour_countdown(self):
        script = (ROOT / "web/static/subscription-admin.js").read_text(encoding="utf-8")
        style = (ROOT / "web/static/subscription-admin.css").read_text(encoding="utf-8")

        self.assertIn("手动推送周报版本", script)
        self.assertIn("自动选择最新正式版", script)
        self.assertIn("weeklyReportPath: state.manualWeeklyPath", script)
        self.assertIn("data-weekly-picker-search", script)
        self.assertIn('action: "setWeeklyReportPreference"', script)
        self.assertIn("weekly-picker-options", style)
        self.assertIn("max-height: 224px", style)
        self.assertIn("距离下一次自动发送还有 ${days} 天 ${hours} 小时", script)
        self.assertIn("data-report-schedule-countdown", script)
        self.assertIn(".report-schedule-countdown", style)
        self.assertIn("color: #7c8d94", style)


if __name__ == "__main__":
    unittest.main()
