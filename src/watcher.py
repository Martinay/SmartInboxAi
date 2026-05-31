"""File-system watcher for incoming PDFs.

Uses ``watchfiles.awatch`` to monitor the inbox directory and spawns
a processing task for each new or modified PDF.
"""

import asyncio
import logging
from pathlib import Path

from watchfiles import Change, awatch

from src.config import Settings
from src.models import DocumentMetadata
from src.pipeline import process_file
from src.telegram_bot import TelegramNotifier

logger = logging.getLogger("SmartInboxAI")


async def watch_inbox(
    settings: Settings,
    notifier: TelegramNotifier,
    pending_decisions: dict[str, DocumentMetadata],
    stop_event: asyncio.Event,
) -> None:
    """Watch ``settings.inbox_dir`` for new PDF files and process them."""
    logger.info("Starting monitoring of %s …", settings.inbox_dir)

    # Ensure all working directories exist.
    for d in (
        settings.inbox_dir,
        settings.archive_dir,
        settings.pending_dir,
        settings.error_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    async for changes in awatch(settings.inbox_dir, stop_event=stop_event):
        for change_type, filepath in changes:
            filepath = Path(filepath)

            # Only process new / modified PDFs.
            if change_type not in (Change.added, Change.modified):
                continue
            if filepath.suffix.lower() != ".pdf":
                continue
            if not filepath.exists():
                continue

            logger.info(
                "New file detected: %s (%s)", filepath.name, change_type.name
            )
            asyncio.create_task(
                process_file(filepath, settings, notifier, pending_decisions)
            )
