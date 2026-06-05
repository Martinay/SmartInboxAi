"""SmartInboxAI – Entry point.

Loads configuration, wires dependencies, and runs the ntfy-backed
notifier alongside the FastAPI webhook server and file watcher in a
single asyncio event loop.
"""

import asyncio
import logging
import sys

import uvicorn

from src.config import load_settings
from src.models import DocumentMetadata
from src.notifier import NtfyNotifier
from src.watcher import watch_inbox
from src.webhook import create_webhook_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SmartInboxAI")


async def main() -> None:
    """Start the webhook server and file watcher concurrently."""
    settings = load_settings()

    # Validate critical configuration.
    if not settings.ntfy_url:
        logger.error("NTFY_URL is not set!")
        sys.exit(1)
    if not settings.secret_token:
        logger.error("SECRET_TOKEN is not set!")
        sys.exit(1)
    if not settings.callback_base_url:
        logger.error("CALLBACK_BASE_URL is not set!")
        sys.exit(1)
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY is not set – LLM calls will fail.")

    logger.info("SmartInboxAI starting…")
    logger.info("Inbox:     %s", settings.inbox_dir)
    logger.info("Archive:   %s", settings.archive_dir)
    logger.info("Pending:   %s", settings.pending_dir)
    logger.info("Error:     %s", settings.error_dir)
    logger.info("ntfy:      %s", settings.ntfy_url)
    logger.info("Webhook:   :%d", settings.webhook_port)
    logger.info("Blacklist: %s", settings.blacklist)

    # Shared mutable state for pending user decisions.
    pending_decisions: dict[str, DocumentMetadata] = {}

    # Build the notifier and webhook app.
    notifier = NtfyNotifier(settings)
    app = create_webhook_app(settings, pending_decisions)

    # Configure uvicorn to run inside the existing event loop.
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.webhook_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    stop_event = asyncio.Event()

    try:
        await asyncio.gather(
            server.serve(),
            watch_inbox(settings, notifier, pending_decisions, stop_event),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down SmartInboxAI…")
    finally:
        stop_event.set()
        server.should_exit = True

    logger.info("SmartInboxAI stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
