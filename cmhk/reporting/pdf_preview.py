"""Create browser preview PDFs for generated Word reports.

The Word document remains the downloadable source of record.  The PDF lives
under ``web/static/report-previews`` so the already-running web service can
serve it without adding a new route or reloading the process.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PREVIEW_DIR = ROOT / "web" / "static" / "report-previews"


def pdf_preview_path(docx_path: Path, preview_dir: Path = PREVIEW_DIR) -> Path:
    key = base64.urlsafe_b64encode(docx_path.stem.encode("utf-8")).decode("ascii").rstrip("=")
    return preview_dir / f"{key}.pdf"


def convert_docx_to_pdf_preview(
    docx_path: Path,
    *,
    preview_dir: Path = PREVIEW_DIR,
    timeout: int = 120,
) -> Path:
    """Convert one generated DOCX to an atomically-published PDF preview."""
    docx_path = Path(docx_path).resolve()
    if not docx_path.exists() or docx_path.suffix.lower() != ".docx":
        raise FileNotFoundError(f"Word报告不存在：{docx_path}")

    preview_dir.mkdir(parents=True, exist_ok=True)
    target = pdf_preview_path(docx_path, preview_dir)
    errors: list[str] = []
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            _convert_with_soffice(docx_path, target, soffice, timeout)
            return target
        except Exception as exc:
            errors.append(str(exc))

    word_app = Path("/Applications/Microsoft Word.app")
    if word_app.exists():
        try:
            _convert_with_microsoft_word(docx_path, target, timeout)
            return target
        except Exception as exc:
            errors.append(str(exc))

    raise RuntimeError("；".join(errors) or "未找到可用的 Word/PDF 转换器")


def _convert_with_soffice(docx_path: Path, target: Path, soffice: str, timeout: int) -> None:
    with tempfile.TemporaryDirectory(prefix="cmhk_report_pdf_") as temp_name:
        temp_dir = Path(temp_name)
        profile_dir = temp_dir / "profile"
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        command = [
            soffice,
            "--headless",
            f"-env:UserInstallation={profile_dir.as_uri()}",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(output_dir),
            str(docx_path),
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        converted = output_dir / f"{docx_path.stem}.pdf"
        if completed.returncode != 0 or not converted.exists():
            detail = (completed.stderr or completed.stdout or "转换未产出 PDF").strip()
            raise RuntimeError(f"PDF 预览转换失败：{detail}")
        pending = target.with_suffix(".pdf.tmp")
        shutil.copy2(converted, pending)
        pending.replace(target)


def _convert_with_microsoft_word(docx_path: Path, target: Path, timeout: int) -> None:
    """Use the installed Microsoft Word renderer when LibreOffice is absent."""
    target.parent.mkdir(parents=True, exist_ok=True)
    # Word's macOS sandbox can export to the user's Downloads container without
    # showing an interactive grant dialog; publish to the app directory only
    # after Word closes the temporary PDF.
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    converted = downloads / f".cmhk-report-preview-{uuid.uuid4().hex}.pdf"
    try:
        subprocess.run(
            ["open", "-gj", "-a", "Microsoft Word", str(docx_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        script = """
on run argv
  set documentName to item 1 of argv
  set outputPath to item 2 of argv
  tell application "Microsoft Word"
    repeat 100 times
      if exists document documentName then exit repeat
      delay 0.2
    end repeat
    if not (exists document documentName) then error "Word 未能打开报告"
    set reportDocument to document documentName
    save as reportDocument file name (POSIX file outputPath) file format format PDF
  end tell
end run
"""
        completed = subprocess.run(
            ["osascript", "-", docx_path.name, str(converted)],
            input=script,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if completed.returncode != 0 or not converted.exists():
            detail = (completed.stderr or completed.stdout or "Word 未产出 PDF").strip()
            raise RuntimeError(f"Microsoft Word PDF 转换失败：{detail}")
        # Word's current AppleScript dictionary exports reliably but does not
        # expose a working document close command. Close only the just-active
        # report window through the standard macOS shortcut; failure here is
        # non-fatal because the PDF has already been written.
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Microsoft Word" to activate',
                "-e",
                'tell application "System Events" to keystroke "w" using command down',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        pending = target.with_suffix(".pdf.tmp")
        shutil.copy2(converted, pending)
        pending.replace(target)
    finally:
        converted.unlink(missing_ok=True)
