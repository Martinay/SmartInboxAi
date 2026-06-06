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


def test_build_actions_header(notifier: NtfyNotifier, metadata: DocumentMetadata) -> None:
    """Ensure the actions header contains all four actions in ntfy header format."""
    header = notifier._build_actions_header("test.pdf", metadata)

    # Should contain three actions separated by "; "
    actions = header.split("; ")
    assert len(actions) == 3

    # Check each action starts with "http, " and has method=POST, clear=true
    for action in actions:
        assert action.startswith("http, ")
        assert "method=POST" in action
        assert "clear=true" in action

    # Check labels
    assert "Erstellen" in actions[0]
    assert "action=create" in actions[0]
    assert "Alt1" in actions[1]
    assert "action=alt1" in actions[1]
    assert "Ablehnen" in actions[2]
    assert "action=reject" in actions[2]


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
    """Ensure send_auto_filed posts to the ntfy topic URL with headers."""
    mock_response = MagicMock(spec=httpx.Response)

    with patch("src.notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await notifier.send_auto_filed("test.pdf", "Finance/Taxes")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://ntfy.test/test_topic"

        headers = call_args[1]["headers"]
        assert headers["X-Title"] == notifier._encode_header("✅ Automatisch abgelegt")
        assert headers["X-Tags"] == "white_check_mark,file_folder"

        body = call_args[1]["content"].decode("utf-8")
        assert "test.pdf" in body
        assert "Finance/Taxes" in body


@pytest.mark.asyncio
async def test_send_decision_request(notifier: NtfyNotifier, metadata: DocumentMetadata, tmp_path: Path) -> None:
    """Ensure send_decision_request posts with attach and actions headers."""
    preview_bytes = b"\xff\xd8\xff\xe0fake_jpeg_data"

    mock_response = MagicMock(spec=httpx.Response)

    with patch("src.notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await notifier.send_decision_request("test.pdf", metadata, preview_bytes)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        headers = call_args[1]["headers"]
        assert headers["X-Title"] == notifier._encode_header("Neues Dokument einordnen")
        assert headers["X-Tags"] == "page_facing_up"
        assert headers["X-Filename"] == notifier._encode_header("test.jpg")
        assert "X-Attach" not in headers
        
        import base64
        encoded_message = headers["X-Message"]
        b64_part_msg = encoded_message[len("=?utf-8?B?"):-len("?=")]
        decoded_message = base64.b64decode(b64_part_msg).decode("utf-8")
        assert "📄 Neuer Ordner vorgeschlagen" in decoded_message
        assert "X-Actions" in headers

        # Verify actions header contains three actions
        # First we need to decode the RFC 2047 string
        import base64
        encoded_actions = headers["X-Actions"]
        b64_part = encoded_actions[len("=?utf-8?B?"):-len("?=")]
        decoded_actions = base64.b64decode(b64_part).decode("utf-8")
        
        actions_parts = decoded_actions.split("; ")
        assert len(actions_parts) == 3

        body = call_args[1]["content"]
        assert body == b"\xff\xd8\xff\xe0fake_jpeg_data"


@pytest.mark.asyncio
async def test_send_error(notifier: NtfyNotifier) -> None:
    """Ensure send_error posts with high priority header."""
    mock_response = MagicMock(spec=httpx.Response)

    with patch("src.notifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await notifier.send_error("test.pdf", "Something went wrong")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        headers = call_args[1]["headers"]
        assert headers["X-Title"] == notifier._encode_header("❌ Fehler bei Verarbeitung")
        assert headers["X-Priority"] == "4"
        assert headers["X-Tags"] == "rotating_light"

        body = call_args[1]["content"].decode("utf-8")
        assert "test.pdf" in body
        assert "Something went wrong" in body


def test_encode_header(notifier: NtfyNotifier) -> None:
    """Verify that pure ASCII strings are not encoded, while Unicode is RFC 2047 base64 encoded."""
    ascii_str = "Clean ASCII string"
    assert notifier._encode_header(ascii_str) == ascii_str

    unicode_str = "📄 Neues Dokument"
    encoded = notifier._encode_header(unicode_str)
    assert encoded.startswith("=?utf-8?B?")
    assert encoded.endswith("?=")

    # Decoded value should match original
    import base64
    b64_part = encoded[len("=?utf-8?B?"):-len("?=")]
    assert base64.b64decode(b64_part).decode("utf-8") == unicode_str

