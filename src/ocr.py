"""OCR and PDF processing functions.

Handles text detection, OCR via ``ocrmypdf``, text extraction with
``pypdf``, and JPEG preview generation with ``pdf2image``.
"""

import asyncio
import logging
import shutil
from pathlib import Path

from pdf2image import convert_from_path
from pypdf import PdfReader

logger = logging.getLogger("SmartInboxAI")


def has_text(pdf_path: Path, max_pages: int = 3) -> bool:
    """Check whether at least one of the first *max_pages* pages has text."""
    try:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages[:max_pages]:
            text = page.extract_text()
            if text and text.strip():
                return True
    except Exception as exc:
        logger.warning("Error checking text for %s: %s", pdf_path.name, exc)
    return False


async def run_ocr(pdf_path: Path) -> Path:
    """Run ``ocrmypdf`` asynchronously and replace the original in-place.

    Returns the path to the (now OCR'd) file.
    """
    output_path = pdf_path.with_suffix(".ocr.pdf")

    process = await asyncio.create_subprocess_exec(
        "ocrmypdf",
        "-l",
        "eng+deu",
        "--skip-text",
        str(pdf_path),
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown OCR error"
        raise RuntimeError(f"OCR failed for {pdf_path.name}: {error_msg}")

    # Replace original with OCR'd version.
    shutil.move(str(output_path), str(pdf_path))
    logger.info("OCR completed for %s", pdf_path.name)
    return pdf_path


def extract_text(pdf_path: Path, max_pages: int = 3) -> str:
    """Extract text from the first *max_pages* pages using ``pypdf``."""
    reader = PdfReader(str(pdf_path))
    text_parts: list[str] = []

    for page in reader.pages[:max_pages]:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text.strip())

    return "\n\n".join(text_parts)


def generate_preview(pdf_path: Path) -> Path:
    """Render page 1 as JPEG (150 DPI, quality 85) for Telegram previews."""
    images = convert_from_path(str(pdf_path), first_page=1, last_page=1, dpi=150)

    preview_path = pdf_path.with_suffix(".jpg")
    images[0].save(str(preview_path), "JPEG", quality=85)
    logger.info("Preview created: %s", preview_path.name)
    return preview_path
