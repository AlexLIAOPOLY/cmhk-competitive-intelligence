from pathlib import Path
import subprocess
import tempfile
import unittest
import os
from unittest.mock import patch

from cmhk.reporting.pdf_preview import (
    convert_docx_to_pdf_preview,
    pdf_preview_path,
)


class ReportPdfPreviewTests(unittest.TestCase):
    def test_preview_path_keeps_word_stem(self):
        result = pdf_preview_path(Path("8月13日周报.docx"), Path("previews"))
        self.assertEqual(result.parent, Path("previews"))
        self.assertTrue(result.name.isascii())
        self.assertTrue(result.name.endswith(".pdf"))

    def test_conversion_publishes_atomically(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "sample.docx"
            preview_dir = root / "previews"
            source.write_bytes(b"word")

            def fake_run(command, **_kwargs):
                self.assertIn("--headless", command)
                self.assertIn("env", _kwargs)
                output_dir = Path(command[command.index("--outdir") + 1])
                (output_dir / "sample.pdf").write_bytes(b"%PDF-test")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("cmhk.reporting.pdf_preview.shutil.which", return_value="/opt/homebrew/bin/soffice"), patch(
                "cmhk.reporting.pdf_preview.subprocess.run", side_effect=fake_run
            ):
                result = convert_docx_to_pdf_preview(source, preview_dir=preview_dir)

            self.assertEqual(result.read_bytes(), b"%PDF-test")
            self.assertFalse(result.with_suffix(".pdf.tmp").exists())

    def test_missing_server_converter_never_opens_desktop_application(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.docx"
            source.write_bytes(b"word")
            with (patch("cmhk.reporting.pdf_preview.shutil.which", return_value=None),
                  patch("cmhk.reporting.pdf_preview.subprocess.run") as process):
                with self.assertRaisesRegex(RuntimeError, "服务器未配置"):
                    convert_docx_to_pdf_preview(source, preview_dir=Path(folder)/"pdf")
                process.assert_not_called()

    def test_server_deployment_includes_shared_headless_renderer(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("libreoffice-writer", (root/"Dockerfile").read_text())
        self.assertIn("runtime: docker", (root/"render.yaml").read_text())

    def test_word_fonts_are_available_to_both_retained_report_templates(self):
        from cmhk.reporting.pdf_preview import _convert_with_soffice
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            configs = []
            def convert(command, **kwargs):
                configs.append(Path(kwargs['env']['FONTCONFIG_FILE']).read_text())
                output = Path(command[command.index('--outdir')+1])
                (output/(Path(command[-1]).stem+'.pdf')).write_bytes(b'%PDF-test')
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch('cmhk.reporting.pdf_preview.sys.platform', 'darwin'), \
                 patch.dict(os.environ, {}, clear=True), \
                 patch('cmhk.reporting.pdf_preview.Path.is_dir', return_value=True), \
                 patch('cmhk.reporting.pdf_preview.subprocess.run', side_effect=convert):
                for name in ['业绩摘要', '9月11日周报 (1)', 'unrelated']:
                    _convert_with_soffice(root/(name+'.docx'),root/(name+'.pdf'),'test-soffice',30)
            self.assertIn('Microsoft Word.app/Contents/Resources/DFonts', configs[0])
            self.assertIn('Microsoft Word.app/Contents/Resources/DFonts', configs[1])
            self.assertNotIn('Microsoft Word.app', configs[2])


if __name__ == "__main__":
    unittest.main()
