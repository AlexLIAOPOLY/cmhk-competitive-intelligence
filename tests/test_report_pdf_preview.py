from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cmhk.reporting.pdf_preview import (
    _convert_with_microsoft_word,
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
                output_dir = Path(command[command.index("--outdir") + 1])
                (output_dir / "sample.pdf").write_bytes(b"%PDF-test")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("cmhk.reporting.pdf_preview.shutil.which", return_value="/opt/homebrew/bin/soffice"), patch(
                "cmhk.reporting.pdf_preview.subprocess.run", side_effect=fake_run
            ):
                result = convert_docx_to_pdf_preview(source, preview_dir=preview_dir)

            self.assertEqual(result.read_bytes(), b"%PDF-test")
            self.assertFalse(result.with_suffix(".pdf.tmp").exists())

    def test_word_close_timeout_does_not_discard_exported_pdf(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "sample.docx"
            target = root / "previews" / "sample.pdf"
            source.write_bytes(b"word")

            def fake_run(command, **_kwargs):
                if command[:2] == ["osascript", "-"]:
                    Path(command[-1]).write_bytes(b"%PDF-word")
                    return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                if command[:2] == ["osascript", "-e"]:
                    raise subprocess.TimeoutExpired(command, 10)
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("cmhk.reporting.pdf_preview.subprocess.run", side_effect=fake_run):
                _convert_with_microsoft_word(source, target, timeout=120)

            self.assertEqual(target.read_bytes(), b"%PDF-word")
            self.assertFalse(target.with_suffix(".pdf.tmp").exists())


if __name__ == "__main__":
    unittest.main()
