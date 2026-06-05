"""Tests for the processing pipeline."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.models import DocumentMetadata
from src.pipeline import process_file
from src.notifier import NtfyNotifier


@pytest.fixture
def mock_metadata() -> DocumentMetadata:
    return DocumentMetadata(
        year="2024",
        month="01",
        day="01",
        title="Test",
        suggested_category="Finance",
        is_new_category=False,
        alternative_1="Alt1",
        alternative_2="Alt2",
    )


@pytest.fixture
def mock_notifier(mock_settings) -> NtfyNotifier:
    """NtfyNotifier with all send methods mocked."""
    notifier = NtfyNotifier(mock_settings)
    notifier.send_auto_filed = AsyncMock()
    notifier.send_decision_request = AsyncMock()
    notifier.send_error = AsyncMock()
    return notifier


@pytest.mark.asyncio
@patch("src.pipeline.wait_for_stable_file", return_value=True)
@patch("src.pipeline.has_text", return_value=True)
@patch("src.pipeline.extract_text", return_value="Some text")
@patch("src.pipeline.generate_preview")
@patch("src.pipeline.scan_categories", return_value=[])
@patch("src.pipeline.analyze_with_llm")
async def test_process_file_existing_category(
    mock_llm, mock_scan, mock_preview, mock_extract, mock_has_text, mock_wait,
    mock_settings, mock_notifier, mock_metadata, tmp_path
):
    """Ensure process_file handles existing categories correctly."""
    mock_llm.return_value = mock_metadata

    # Setup test file
    pdf_path = tmp_path / "inbox" / "original.pdf"
    pdf_path.write_text("pdf content")

    # Fake preview
    mock_preview.return_value = tmp_path / "inbox" / "original.jpg"
    (tmp_path / "inbox" / "original.jpg").write_text("img")

    pending_decisions = {}

    await process_file(pdf_path, mock_settings, mock_notifier, pending_decisions)

    # 1. File was renamed and moved to archive/Finance
    dest_path = tmp_path / "archive" / "Finance" / "2024-01-01_Test.pdf"
    assert dest_path.exists()

    # 2. Original is gone
    assert not pdf_path.exists()

    # 3. Notification sent
    mock_notifier.send_auto_filed.assert_called_once_with("2024-01-01_Test.pdf", "Finance")


@pytest.mark.asyncio
@patch("src.pipeline.wait_for_stable_file", return_value=True)
@patch("src.pipeline.has_text", return_value=True)
@patch("src.pipeline.extract_text", return_value="Some text")
@patch("src.pipeline.generate_preview")
@patch("src.pipeline.scan_categories", return_value=[])
@patch("src.pipeline.analyze_with_llm")
async def test_process_file_new_category(
    mock_llm, mock_scan, mock_preview, mock_extract, mock_has_text, mock_wait,
    mock_settings, mock_notifier, mock_metadata, tmp_path
):
    """Ensure process_file handles new categories by moving to pending."""
    mock_metadata.is_new_category = True
    mock_llm.return_value = mock_metadata

    pdf_path = tmp_path / "inbox" / "original.pdf"
    pdf_path.write_text("pdf content")
    mock_preview.return_value = tmp_path / "inbox" / "original.jpg"
    (tmp_path / "inbox" / "original.jpg").write_text("img")

    pending_decisions = {}

    await process_file(pdf_path, mock_settings, mock_notifier, pending_decisions)

    # 1. File moved to pending
    pending_path = tmp_path / "pending" / "2024-01-01_Test.pdf"
    assert pending_path.exists()

    # 2. Added to pending_decisions dict
    assert "2024-01-01_Test.pdf" in pending_decisions

    # 3. Decision requested
    mock_notifier.send_decision_request.assert_called_once()
