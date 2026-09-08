from pathlib import Path
import subprocess
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
