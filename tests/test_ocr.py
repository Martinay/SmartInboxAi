"""Tests for OCR module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.ocr import has_text, run_ocr, extract_text, generate_preview


@patch("src.ocr.PdfReader")
def test_has_text(mock_pdf_reader) -> None:
    """Ensure has_text correctly identifies extractable text."""
    # Setup mock reader with one page returning text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Hello World"
    mock_reader_instance = mock_pdf_reader.return_value
    mock_reader_instance.pages = [mock_page]

    assert has_text(Path("dummy.pdf")) is True

    # Setup mock reader returning empty text
    mock_page.extract_text.return_value = "   \n"
    assert has_text(Path("dummy.pdf")) is False

    # Setup mock reader raising exception
    mock_pdf_reader.side_effect = Exception("Corrupt PDF")
    assert has_text(Path("dummy.pdf")) is False


@patch("src.ocr.PdfReader")
def test_extract_text(mock_pdf_reader) -> None:
    """Ensure extract_text concatenates page texts."""
    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "Page 1 Text"
    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = "Page 2 Text"
    
    mock_reader_instance = mock_pdf_reader.return_value
    mock_reader_instance.pages = [mock_page1, mock_page2]

    text = extract_text(Path("dummy.pdf"))
    assert text == "Page 1 Text\n\nPage 2 Text"


@pytest.mark.asyncio
@patch("src.ocr.asyncio.create_subprocess_exec")
@patch("src.ocr.shutil.move")
async def test_run_ocr_success(mock_move, mock_exec) -> None:
    """Ensure run_ocr handles successful execution."""
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"")
    mock_process.returncode = 0
    mock_exec.return_value = mock_process

    pdf_path = Path("test.pdf")
    result = await run_ocr(pdf_path)

    assert result == pdf_path
    mock_exec.assert_called_once()
    mock_move.assert_called_once()


@pytest.mark.asyncio
@patch("src.ocr.asyncio.create_subprocess_exec")
async def test_run_ocr_failure(mock_exec) -> None:
    """Ensure run_ocr raises RuntimeError on failure."""
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"ocr error")
    mock_process.returncode = 1
    mock_exec.return_value = mock_process

    with pytest.raises(RuntimeError, match="OCR failed"):
        await run_ocr(Path("test.pdf"))


@patch("src.ocr.convert_from_path")
def test_generate_preview(mock_convert) -> None:
    """Ensure generate_preview calls pdf2image and saves jpeg."""
    mock_image = MagicMock()
    mock_convert.return_value = [mock_image]

    pdf_path = Path("test.pdf")
    preview_path = generate_preview(pdf_path)

    assert preview_path.name == "test.jpg"
    mock_convert.assert_called_once_with(str(pdf_path), first_page=1, last_page=1, dpi=150)
    mock_image.save.assert_called_once_with(str(preview_path), "JPEG", quality=85)
