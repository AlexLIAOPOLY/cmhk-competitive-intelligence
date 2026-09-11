"""Create browser preview PDFs for generated Word reports.

The Word document remains the downloadable source of record.  The PDF lives
under ``web/static/report-previews`` so the already-running web service can
serve it without adding a new route or reloading the process.
"""

from __future__ import annotations

import base64
import os
import sys
import shutil
import subprocess
import tempfile
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

    raise RuntimeError("；".join(errors) or "服务器未配置 PDF 转换器，请使用包含 libreoffice-writer 的部署镜像")


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
        environment = os.environ.copy()
        if sys.platform == "darwin" and not environment.get("FONTCONFIG_FILE"):
            # Recent headless builds use fontconfig rather than CoreText. Expose
            # the host's existing fonts; do not install or modify user fonts.
            from xml.sax.saxutils import escape
            font_dirs = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home()/"Library/Fonts"]
            if "业绩摘要" in docx_path.stem:
                # Word's installed FangSong is outside macOS's system font
                # directories. Use the existing font for this report only.
                font_dirs.append(Path("/Applications/Microsoft Word.app/Contents/Resources/DFonts"))
            config = temp_dir / "fonts.conf"
            config.write_text('<fontconfig>' + ''.join(f'<dir>{escape(str(path))}</dir>' for path in font_dirs if path.is_dir())
                              + f'<cachedir>{escape(str(temp_dir / "font-cache"))}</cachedir></fontconfig>', encoding="utf-8")
            environment["FONTCONFIG_FILE"] = str(config)
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
        converted = output_dir / f"{docx_path.stem}.pdf"
        if completed.returncode != 0 or not converted.exists():
            detail = (completed.stderr or completed.stdout or "转换未产出 PDF").strip()
            raise RuntimeError(f"PDF 预览转换失败：{detail}")
        pending = target.with_suffix(".pdf.tmp")
        shutil.copy2(converted, pending)
        pending.replace(target)
