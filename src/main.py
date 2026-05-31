"""SmartInboxAI – Entry point.

Loads configuration, wires dependencies, and runs the Telegram bot
alongside the file watcher in a single asyncio event loop.
"""

import asyncio
import logging
import sys

from telegram.ext import Application, CallbackQueryHandler

from src.config import load_settings
from src.models import DocumentMetadata
from src.telegram_bot import TelegramNotifier, create_callback_handler
from src.watcher import watch_inbox

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SmartInboxAI")


async def main() -> None:
    """Start the Telegram bot and file watcher concurrently."""
    settings = load_settings()

    # Validate critical configuration.
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set!")
        sys.exit(1)
    if not settings.telegram_chat_id:
        logger.error("TELEGRAM_CHAT_ID is not set!")
        sys.exit(1)
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY is not set – LLM calls will fail.")

    logger.info("SmartInboxAI starting…")
    logger.info("Inbox:     %s", settings.inbox_dir)
    logger.info("Archive:   %s", settings.archive_dir)
    logger.info("Pending:   %s", settings.pending_dir)
    logger.info("Error:     %s", settings.error_dir)
    logger.info("Blacklist: %s", settings.blacklist)

    # Shared mutable state for pending user decisions.
    pending_decisions: dict[str, DocumentMetadata] = {}

    # Build the Telegram application.
    application = Application.builder().token(settings.telegram_bot_token).build()

    callback_handler = create_callback_handler(settings, pending_decisions)
    application.add_handler(
        CallbackQueryHandler(
            callback_handler,
            pattern=r"^(create|alt1|alt2|reject):",
        )
    )

    notifier = TelegramNotifier(
        bot=application.bot,
        chat_id=int(settings.telegram_chat_id),
    )

    stop_event = asyncio.Event()

    async with application:
        await application.start()
        await application.updater.start_polling(
            allowed_updates=["callback_query"],
        )
        logger.info("Telegram bot started (polling).")

        try:
            await watch_inbox(settings, notifier, pending_decisions, stop_event)
        except KeyboardInterrupt:
            logger.info("Shutting down SmartInboxAI…")
        finally:
            stop_event.set()
            await application.updater.stop()
            await application.stop()

    logger.info("SmartInboxAI stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
