"""Tests for file system operations."""

import asyncio
import pytest
from pathlib import Path

from src.config import Settings
from src.file_ops import (
    build_new_filename,
    cleanup_preview,
    move_file,
    scan_categories,
    wait_for_stable_file,
)
from src.models import DocumentMetadata


def test_scan_categories(tmp_path: Path) -> None:
    """Ensure scan_categories finds folders and respects the blacklist."""
    archive = tmp_path / "archive"
    archive.mkdir()

    # Create directories
    (archive / "Finance").mkdir()
    (archive / "Finance" / "Taxes").mkdir()
    (archive / "Health").mkdir()
    
    # Create blacklisted directories
    (archive / ".DS_Store").mkdir()
    (archive / "Health" / "ignore_me").mkdir()
    (archive / "Health" / "ignore_me" / "nested").mkdir()

    blacklist = {".DS_Store", "ignore_me"}
    
    categories = scan_categories(archive, blacklist)
    
    assert categories == [
        "Finance",
        "Finance/Taxes",
        "Health",
    ]
    # Ensure ignore_me and its nested contents are skipped
    assert "Health/ignore_me" not in categories
    assert "Health/ignore_me/nested" not in categories


@pytest.mark.asyncio
async def test_wait_for_stable_file(tmp_path: Path) -> None:
    """Ensure wait_for_stable_file works correctly."""
    filepath = tmp_path / "test.txt"
    filepath.write_text("hello")

    # Should stabilise immediately with checks=1 and stable_seconds=0
    is_stable = await wait_for_stable_file(filepath, stable_seconds=0, stable_checks=1)
    assert is_stable is True

    # Should return False if file doesn't exist
    is_stable = await wait_for_stable_file(tmp_path / "missing.txt", 0, 1)
    assert is_stable is False


def test_build_new_filename() -> None:
    """Ensure safe filenames are generated from metadata."""
    metadata = DocumentMetadata(
        year="2024",
        month="05",
        day="31",
        title="My_Special@Doc!",
        suggested_category="Misc",
        is_new_category=False,
        alternative_1="A",
        alternative_2="B",
    )
    # Special chars are replaced by _
    filename = build_new_filename(metadata)
    assert filename == "2024-05-31_My_Special_Doc.pdf"


def test_move_file(tmp_path: Path) -> None:
    """Ensure move_file moves the file and handles name collisions."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    src_file = src_dir / "test.pdf"
    src_file.write_text("content")

    # First move
    dest1 = move_file(src_file, dest_dir, "test.pdf")
    assert dest1.name == "test.pdf"
    assert dest1.read_text() == "content"
    assert not src_file.exists()

    # Second move (collision)
    src_file.write_text("new content")
    dest2 = move_file(src_file, dest_dir, "test.pdf")
    assert dest2.name == "test_1.pdf"
    assert dest2.read_text() == "new content"


def test_cleanup_preview(tmp_path: Path) -> None:
    """Ensure cleanup_preview deletes the .jpg file if it exists."""
    pdf_path = tmp_path / "doc.pdf"
    jpg_path = tmp_path / "doc.jpg"
    
    jpg_path.write_text("image data")
    assert jpg_path.exists()
    
    cleanup_preview(pdf_path)
    assert not jpg_path.exists()
