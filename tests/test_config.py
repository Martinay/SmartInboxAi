"""Tests for configuration loading."""

import os
from unittest import mock

from src.config import load_settings


@mock.patch.dict(
    os.environ,
    {
        "OPENAI_API_KEY": "test_openai",
        "NTFY_URL": "http://ntfy.local/topic",
        "NTFY_TOKEN": "tk_abc123",
        "SECRET_TOKEN": "my_secret",
        "CALLBACK_BASE_URL": "http://192.168.1.100:8000",
        "WEBHOOK_PORT": "9000",
        "IGNORE_FOLDERS": "foo, bar , baz",
    },
)
def test_load_settings() -> None:
    """Ensure settings are correctly loaded from environment."""
    settings = load_settings()

    assert settings.openai_api_key == "test_openai"
    assert settings.ntfy_url == "http://ntfy.local/topic"
    assert settings.ntfy_token == "tk_abc123"
    assert settings.secret_token == "my_secret"
    assert settings.callback_base_url == "http://192.168.1.100:8000"
    assert settings.webhook_port == 9000
    assert settings.user_blacklist == frozenset({"foo", "bar", "baz"})
    assert "foo" in settings.blacklist
    assert ".DS_Store" in settings.blacklist  # From system blacklist
