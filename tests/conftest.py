"""Shared pytest fixtures."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Settings


@pytest.fixture
def mock_settings(tmp_path: Path) -> Settings:
    """Provides a Settings instance pointing to temporary directories."""
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    pending = tmp_path / "pending"
    error = tmp_path / "error"

    for d in (inbox, archive, pending, error):
        d.mkdir(parents=True, exist_ok=True)

    return Settings(
        openai_api_key="test_key",
        telegram_bot_token="test_token",
        telegram_chat_id="12345",
        inbox_dir=inbox,
        archive_dir=archive,
        pending_dir=pending,
        error_dir=error,
        user_blacklist=frozenset({"ignore_me"}),
        file_stable_seconds=0,  # Fast tests
        file_stable_checks=1,
    )


@pytest.fixture
def mock_telegram_bot() -> MagicMock:
    """Mock Telegram bot instance with async methods."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    return bot
