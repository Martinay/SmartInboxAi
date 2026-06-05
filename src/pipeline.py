"""Document processing pipeline.

Orchestrates the full lifecycle of a single PDF:
stability check → OCR → text extraction → preview → category scan →
LLM analysis → rename → route (auto-file or ask user).
"""

import logging
import shutil
from pathlib import Path

from src.config import Settings
from src.file_ops import (
    build_new_filename,
    cleanup_preview,
    move_file,
    scan_categories,
    wait_for_stable_file,
)
from src.llm import analyze_with_llm
from src.models import DocumentMetadata
from src.ocr import extract_text, generate_preview, has_text, run_ocr
from src.notifier import NtfyNotifier

logger = logging.getLogger("SmartInboxAI")


async def process_file(
    pdf_path: Path,
    settings: Settings,
    notifier: NtfyNotifier,
    pending_decisions: dict[str, DocumentMetadata],
) -> None:
    """Full processing pipeline for a single PDF file.

    All dependencies are passed as parameters so the function can be
    tested with mocks.
    """
    original_name = pdf_path.name
    logger.info("Starting processing: %s", original_name)

    try:
        # 1. Wait for file to stabilise
        stable = await wait_for_stable_file(
            pdf_path,
            stable_seconds=settings.file_stable_seconds,
            stable_checks=settings.file_stable_checks,
        )
        if not stable:
            logger.warning(
                "File %s is not stable or has disappeared.", original_name
            )
            return

        # 2. Check for text and OCR if needed
        if not has_text(pdf_path, max_pages=settings.max_text_pages):
            logger.info("No text found in %s, starting OCR…", original_name)
            await run_ocr(pdf_path)
        else:
            logger.info("Text already present in %s", original_name)

        # 3. Extract text
        text = extract_text(pdf_path, max_pages=settings.max_text_pages)
        if not text.strip():
            raise RuntimeError(
                f"No text extractable from {original_name} (even after OCR)."
            )

        # 4. Generate preview
        preview_path = generate_preview(pdf_path)

        # 5. Scan current categories
        categories = scan_categories(settings.archive_dir, settings.blacklist)
        logger.info("Found categories: %d", len(categories))

        # 6. LLM analysis
        metadata = await analyze_with_llm(
            text,
            categories,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_text_chars=settings.max_text_chars,
        )

        # 7. Rename file
        new_filename = build_new_filename(metadata)
        new_path = pdf_path.parent / new_filename
        if pdf_path != new_path:
            shutil.move(str(pdf_path), str(new_path))
            pdf_path = new_path
            logger.info("File renamed: %s → %s", original_name, new_filename)

            # Rename preview as well.
            new_preview = pdf_path.with_suffix(".jpg")
            if preview_path.exists() and preview_path != new_preview:
                shutil.move(str(preview_path), str(new_preview))
                preview_path = new_preview

        # 8. Route: auto-file or ask user
        if not metadata.is_new_category:
            # Existing category → move directly.
            target_dir = settings.archive_dir / metadata.suggested_category
            move_file(pdf_path, target_dir, new_filename)
            cleanup_preview(pdf_path)
            await notifier.send_auto_filed(
                new_filename, metadata.suggested_category
            )
            logger.info(
                "Auto-filed: %s → %s",
                new_filename,
                metadata.suggested_category,
            )
        else:
            # New category → move to pending and ask user.
            move_file(pdf_path, settings.pending_dir, new_filename)

            pending_decisions[new_filename] = metadata
            await notifier.send_decision_request(
                new_filename, metadata, preview_path
            )
            cleanup_preview(pdf_path)
            logger.info(
                "User decision requested for: %s (suggested: %s)",
                new_filename,
                metadata.suggested_category,
            )

    except Exception as exc:
        logger.error("Error processing %s: %s", original_name, exc)

        # Move to error directory.
        try:
            if pdf_path.exists():
                move_file(pdf_path, settings.error_dir, pdf_path.name)
                cleanup_preview(pdf_path)
        except Exception as move_exc:
            logger.error("Could not move file to /error: %s", move_exc)

        await notifier.send_error(original_name, str(exc))
