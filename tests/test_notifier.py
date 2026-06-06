"""Tests for the ntfy notifier module."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from src.config import Settings
from src.models import DocumentMetadata
from src.notifier import NtfyNotifier


@pytest.fixture
def metadata() -> DocumentMetadata:
    return DocumentMetadata(
        year="2024", month="01", day="01", title="Test",
        suggested_category="Finance", is_new_category=True,
        alternative_1="Alt1", alternative_2="Alt2",
    )


@pytest.fixture
def notifier(mock_settings) -> NtfyNotifier:
    return NtfyNotifier(mock_settings)


def test_action_url(notifier: NtfyNotifier) -> None:
    """Ensure action URLs contain token, action and filename."""
    url = notifier._action_url("create", "test.pdf")
    assert "token=test_secret" in url
    assert "action=create" in url
    assert "file=test.pdf" in url
    assert url.startswith("http://localhost:8000/action?")


def test_build_actions(notifier: NtfyNotifier, metadata: DocumentMetadata) -> None:
    """Ensure the actions list contains all four actions as JSON dicts."""
    actions = notifier._build_actions("test.pdf", metadata)

    assert len(actions) == 4

    # Check each action has the correct structure
    for action in actions:
        assert action["action"] == "http"
        assert action["method"] == "POST"
        assert action["clear"] is True
        assert "url" in action
        assert "label" in action

    # Check labels and action params
    assert "Erstellen" in actions[0]["label"]
    assert "action=create" in actions[0]["url"]
    assert "Alt1" in actions[1]["label"]
    assert "action=alt1" in actions[1]["url"]
    assert "Alt2" in actions[2]["label"]
    assert "action=alt2" in actions[2]["url"]
    assert "Ablehnen" in actions[3]["label"]
    assert "action=reject" in actions[3]["url"]


def test_sanitize_label() -> None:
    """Ensure commas and semicolons are stripped from labels."""
    assert NtfyNotifier._sanitize_label("Hello, World; Test") == "Hello  World  Test"


def test_topic_extraction(mock_settings) -> None:
    """Ensure topic is correctly extracted from ntfy URL."""
    notifier = NtfyNotifier(mock_settings)
    assert notifier._topic == "test_topic"
    assert notifier._ntfy_base_url == "http://ntfy.test"


@pytest.mark.asyncio
async def test_send_auto_filed(notifier: NtfyNotifier) -> None:
    """Ensure send_auto_filed posts JSON to the ntfy base URL."""
    mock_response = MagicMock(spec=httpx.Response)

    with patch("src.notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await notifier.send_auto_filed("test.pdf", "Finance/Taxes")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://ntfy.test"

        payload = call_args[1]["json"]
        assert payload["topic"] == "test_topic"
        assert payload["title"] == "✅ Automatisch abgelegt"
        assert "test.pdf" in payload["message"]
        assert "Finance/Taxes" in payload["message"]
        assert payload["tags"] == ["white_check_mark", "file_folder"]


@pytest.mark.asyncio
async def test_send_decision_request(notifier: NtfyNotifier, metadata: DocumentMetadata, tmp_path: Path) -> None:
    """Ensure send_decision_request posts JSON with attach URL and actions."""
    preview = tmp_path / "test.jpg"
    preview.write_bytes(b"\xff\xd8\xff\xe0fake_jpeg_data")

    mock_response = MagicMock(spec=httpx.Response)

    with patch("src.notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await notifier.send_decision_request("test.pdf", metadata, preview)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        payload = call_args[1]["json"]
        assert payload["topic"] == "test_topic"
        assert payload["title"] == "Neues Dokument einordnen"
        assert "test.pdf" in payload["message"]
        assert payload["attach"] == "http://localhost:8000/preview/test.jpg"

        # Verify actions are a JSON list
        actions = payload["actions"]
        assert len(actions) == 4
        assert actions[0]["action"] == "http"
        assert actions[0]["method"] == "POST"
        assert actions[0]["clear"] is True


@pytest.mark.asyncio
async def test_send_error(notifier: NtfyNotifier) -> None:
    """Ensure send_error posts JSON with high priority."""
    mock_response = MagicMock(spec=httpx.Response)

    with patch("src.notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await notifier.send_error("test.pdf", "Something went wrong")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        payload = call_args[1]["json"]
        assert payload["topic"] == "test_topic"
        assert payload["priority"] == 4
        assert "test.pdf" in payload["message"]
        assert "Something went wrong" in payload["message"]
