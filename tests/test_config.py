"""Tests for configuration loading."""

import os
from unittest import mock

from src.config import load_settings


@mock.patch.dict(
    os.environ,
    {
        "OPENAI_API_KEY": "test_openai",
        "TELEGRAM_BOT_TOKEN": "test_bot",
        "TELEGRAM_CHAT_ID": "54321",
        "IGNORE_FOLDERS": "foo, bar , baz",
    },
)
def test_load_settings() -> None:
    """Ensure settings are correctly loaded from environment."""
    settings = load_settings()

    assert settings.openai_api_key == "test_openai"
    assert settings.telegram_bot_token == "test_bot"
    assert settings.telegram_chat_id == "54321"
    assert settings.user_blacklist == frozenset({"foo", "bar", "baz"})
    assert "foo" in settings.blacklist
    assert ".DS_Store" in settings.blacklist  # From system blacklist
