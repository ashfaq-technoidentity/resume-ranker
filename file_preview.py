"""Browser previews for stored resume files.

PDF files are served as-is. DOCX files are converted to PDF with LibreOffice
headless (browsers have no built-in DOCX viewer); converted PDFs are cached
on disk keyed by the file's content hash, so each unique document is
converted at most once.
"""

import os
import shutil
import subprocess
import tempfile

DEFAULT_CACHE_DIR = "resume_previews"
_SOFFICE_TIMEOUT_SECONDS = 60


def _safe_name(name: str) -> str:
    """Make a stored file name safe to embed in a Content-Disposition header."""
    return name.replace("\\", "_").replace('"', "'").replace("\r", "").replace("\n", "")


def _as_pdf_name(file_name: str) -> str:
    return os.path.splitext(file_name)[0] + ".pdf"


def _inline_disposition(file_name: str) -> str:
    return f'inline; filename="{_safe_name(file_name)}"'


def _soffice_binary() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_docx_to_pdf(docx_bytes: bytes, cache_path: str | None) -> bytes:
    """Convert DOCX bytes to a PDF via LibreOffice headless.

    When ``cache_path`` is given, the converted PDF is also written there
    (atomically, so concurrent requests never see a half-written file).
    Raises RuntimeError when LibreOffice is unavailable or the conversion
    fails.
    """
    binary = _soffice_binary()
    if binary is None:
        raise RuntimeError(
            "LibreOffice (soffice) is not installed; install it to preview"
            " DOCX resumes (e.g. apt install libreoffice-writer)"
        )
    work_dir = tempfile.mkdtemp(prefix="docx-preview-")
    try:
        # fixed names: the output PDF path must stay predictable
        source = os.path.join(work_dir, "resume.docx")
        with open(source, "wb") as f:
            f.write(docx_bytes)
        # a private user profile per conversion avoids LibreOffice's
        # profile lock blocking concurrent requests
        profile = os.path.join(work_dir, "profile")
        try:
            result = subprocess.run(
                [
                    binary,
                    "--headless",
                    "--norestore",
                    f"-env:UserInstallation=file://{profile}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    work_dir,
                    source,
                ],
                capture_output=True,
                timeout=_SOFFICE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"LibreOffice DOCX conversion timed out after"
                f" {_SOFFICE_TIMEOUT_SECONDS}s"
            ) from error
        pdf_path = os.path.join(work_dir, "resume.pdf")
        if result.returncode != 0 or not os.path.exists(pdf_path):
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()
            raise RuntimeError(
                "LibreOffice DOCX conversion failed:"
                f" {detail or f'exit code {result.returncode}'}"
            )
        with open(pdf_path, "rb") as f:
            pdf = f.read()
        if cache_path:
            os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
            temp_path = f"{cache_path}.{os.getpid()}.tmp"
            with open(temp_path, "wb") as f:
                f.write(pdf)
            os.replace(temp_path, cache_path)
        return pdf
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_preview(file_blob: bytes, record: dict) -> tuple[bytes, str, str]:
    """Return ``(body, media_type, content_disposition)`` for a browser preview.

    ``record`` is a row from ``db.get_resume`` (uses ``file_name``,
    ``file_ext`` and ``file_hash``). PDF files pass through unchanged; DOCX
    files are converted to PDF (cached by content hash); anything else is
    served as an attachment download.
    """
    file_name = record.get("file_name") or f"resume_{record.get('id', 'file')}"
    extension = (record.get("file_ext") or "").lower()
    if extension == "pdf":
        return file_blob, "application/pdf", _inline_disposition(file_name)
    if extension == "docx":
        file_hash = record.get("file_hash")
        cache_path = (
            os.path.join(
                os.environ.get("RESUME_PREVIEW_CACHE_DIR", DEFAULT_CACHE_DIR),
                f"{file_hash}.pdf",
            )
            if file_hash
            else None
        )
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return f.read(), "application/pdf", _inline_disposition(
                    _as_pdf_name(file_name)
                )
        pdf = convert_docx_to_pdf(file_blob, cache_path)
        return pdf, "application/pdf", _inline_disposition(_as_pdf_name(file_name))
    return (
        file_blob,
        "application/octet-stream",
        f'attachment; filename="{_safe_name(file_name)}"',
    )
