"""File-system watcher for incoming PDFs.

Uses ``watchfiles.awatch`` to monitor the inbox directory, discovers existing
PDFs at startup, and spawns processing tasks for supported files.
"""

import asyncio
import logging
import os
from pathlib import Path

from watchfiles import Change, DefaultFilter, awatch

from src.config import Settings
from src.models import DocumentMetadata
from src.pipeline import process_file
from src.notifier import NtfyNotifier

logger = logging.getLogger("SmartInboxAI")


async def watch_inbox(
    settings: Settings,
    notifier: NtfyNotifier,
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

    # Docker bind-mounts (especially macOS → Linux) don't propagate
    # inotify events.  Honour the WATCHFILES_FORCE_POLLING env var
    # (also respected natively by watchfiles) and log the mode.
    force_polling = os.getenv("WATCHFILES_FORCE_POLLING", "").lower() in (
        "true",
        "1",
        "yes",
    )
    if force_polling:
        logger.info("File monitoring mode: polling (WATCHFILES_FORCE_POLLING is set)")
    else:
        logger.info("File monitoring mode: native OS notifications")

    watch_kwargs = {
        "stop_event": stop_event,
        "force_polling": force_polling,
        # The first yield confirms the underlying watcher is running, even
        # for an empty inbox. Scan only then so arrivals cannot fall in a gap.
        "yield_on_timeout": True,
    }
    if force_polling:
        watch_kwargs["step"] = 10000
        watch_kwargs["poll_delay_ms"] = 10000

    in_flight: set[Path] = set()
    completed: dict[Path, tuple[int, int, int, int]] = {}
    tasks: set[asyncio.Task] = set()
    watch_filter = DefaultFilter()

    def fingerprint(path: Path) -> tuple[int, int, int, int] | None:
        try:
            stat = path.stat()
            if not path.is_file():
                return None
            return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
        except FileNotFoundError:
            return None

    async def process(path: Path, original: tuple[int, int, int, int]) -> None:
        try:
            await process_file(path, settings, notifier, pending_decisions)
        finally:
            in_flight.discard(path)
            # Usually the pipeline moves the source out of the inbox. If it
            # remains, ignore delayed events for the same unchanged file.
            signature = fingerprint(path)
            if signature is not None and signature[:2] != original[:2]:
                # A different file can arrive at the same name after the
                # pipeline moves the original, while its task still runs.
                completed.pop(path, None)
                schedule(path)
            elif signature is not None:
                completed[path] = signature
            else:
                completed.pop(path, None)

    def schedule(path: Path) -> None:
        path = path.absolute()
        if path.suffix.lower() != ".pdf":
            return
        signature = fingerprint(path)
        if signature is None or path in in_flight:
            return
        if completed.get(path) == signature:
            return
        in_flight.add(path)
        logger.info("PDF detected: %s", path)
        task = asyncio.create_task(process(path, signature))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    scanned = False
    async for changes in awatch(settings.inbox_dir, **watch_kwargs):
        if not scanned:
            scanned = True
            # Match awatch's recursive default and its ignored paths.
            for path in settings.inbox_dir.rglob("*"):
                if watch_filter(Change.added, str(path)):
                    schedule(path)

        for change_type, filepath in changes:
            filepath = Path(filepath)
            if change_type in (Change.added, Change.modified):
                schedule(filepath)
            elif change_type == Change.deleted:
                completed.pop(filepath.absolute(), None)
