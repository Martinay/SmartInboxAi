"""File-system operations for SmartInboxAI.

All functions accept their configuration as parameters so they can be
tested in isolation with ``tmp_path`` fixtures.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path

from src.models import DocumentMetadata

logger = logging.getLogger("SmartInboxAI")


def scan_categories(
    archive_path: Path,
    blacklist: set[str] | frozenset[str],
) -> list[str]:
    """Return sorted subfolder paths relative to *archive_path*.

    Blacklisted directory names are pruned in-place so their entire
    subtree is skipped.
    """
    categories: list[str] = []
    if not archive_path.exists():
        return categories

    for dirpath, dirnames, _ in os.walk(archive_path):
        # In-place filter — prevents os.walk from descending.
        dirnames[:] = [d for d in dirnames if d not in blacklist]

        rel = os.path.relpath(dirpath, archive_path)
        if rel != ".":
            categories.append(rel)

    categories.sort()
    return categories


async def wait_for_stable_file(
    filepath: Path,
    stable_seconds: int = 3,
    stable_checks: int = 3,
) -> bool:
    """Poll file size and return ``True`` once it is constant.

    Returns ``False`` if the file disappears or never stabilises within
    ~30 iterations.
    """
    last_size = -1
    stable_count = 0

    for _ in range(30):  # Max ~90 s at 3 s intervals.
        if not filepath.exists():
            return False

        current_size = filepath.stat().st_size
        if current_size == last_size and current_size > 0:
            stable_count += 1
            if stable_count >= stable_checks:
                return True
        else:
            stable_count = 0

        last_size = current_size
        await asyncio.sleep(stable_seconds)

    logger.warning("File %s did not stabilise within time limit.", filepath)
    return False


def build_new_filename(metadata: DocumentMetadata) -> str:
    """Build ``{YYYY}-{MM}-{DD}_{Title}.pdf`` from *metadata*."""
    safe_title = "".join(
        c if c.isalnum() or c == "_" else "_" for c in metadata.title
    ).strip("_")
    return f"{metadata.year}-{metadata.month}-{metadata.day}_{safe_title}.pdf"


def move_file(src: Path, dest_dir: Path, filename: str) -> Path:
    """Move *src* into *dest_dir* / *filename*, handling name collisions."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        dest_dir.chmod(0o777)
    except Exception as e:
        logger.warning("Failed to chmod directory %s: %s", dest_dir, e)

    dest = dest_dir / filename

    counter = 1
    while dest.exists():
        stem = dest.stem
        dest = dest_dir / f"{stem}_{counter}.pdf"
        counter += 1

    shutil.move(str(src), str(dest))
    try:
        dest.chmod(0o666)
    except Exception as e:
        logger.warning("Failed to chmod file %s: %s", dest, e)

    logger.info("File moved: %s → %s", src.name, dest)
    return dest


def cleanup_preview(pdf_path: Path) -> None:
    """Remove the ``.jpg`` preview associated with *pdf_path*."""
    preview = pdf_path.with_suffix(".jpg")
    if preview.exists():
        preview.unlink()
