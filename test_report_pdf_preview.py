from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from report_pdf_preview import convert_docx_to_pdf_preview, pdf_preview_path


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
                output_dir = Path(command[command.index("--outdir") + 1])
                (output_dir / "sample.pdf").write_bytes(b"%PDF-test")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("report_pdf_preview.shutil.which", return_value="/opt/homebrew/bin/soffice"), patch(
                "report_pdf_preview.subprocess.run", side_effect=fake_run
            ):
                result = convert_docx_to_pdf_preview(source, preview_dir=preview_dir)

            self.assertEqual(result.read_bytes(), b"%PDF-test")
            self.assertFalse(result.with_suffix(".pdf.tmp").exists())


if __name__ == "__main__":
    unittest.main()
