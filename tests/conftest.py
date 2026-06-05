"""Shared pytest fixtures."""

from pathlib import Path
from unittest.mock import AsyncMock

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
        ntfy_url="http://ntfy.test/test_topic",
        ntfy_token="",
        secret_token="test_secret",
        callback_base_url="http://localhost:8000",
        inbox_dir=inbox,
        archive_dir=archive,
        pending_dir=pending,
        error_dir=error,
        user_blacklist=frozenset({"ignore_me"}),
        file_stable_seconds=0,  # Fast tests
        file_stable_checks=1,
    )
