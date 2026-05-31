"""Tests for Telegram bot module."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.models import DocumentMetadata
from src.telegram_bot import TelegramNotifier, build_keyboard, create_callback_handler


@pytest.mark.asyncio
async def test_notifier_send_auto_filed(mock_telegram_bot) -> None:
    """Ensure auto_filed message is sent correctly."""
    notifier = TelegramNotifier(mock_telegram_bot, chat_id=123)
    await notifier.send_auto_filed("test.pdf", "Finance/Taxes")
    
    mock_telegram_bot.send_message.assert_called_once()
    args, kwargs = mock_telegram_bot.send_message.call_args
    assert kwargs["chat_id"] == 123
    assert "test.pdf" in kwargs["text"]
    assert "Finance/Taxes" in kwargs["text"]


def test_build_keyboard() -> None:
    """Ensure keyboard generates correct callback data."""
    metadata = DocumentMetadata(
        year="2024", month="01", day="01", title="Test",
        suggested_category="Finance", is_new_category=False,
        alternative_1="Alt1", alternative_2="Alt2"
    )
    keyboard = build_keyboard(metadata, "test.pdf")
    
    assert len(keyboard.inline_keyboard) == 4
    assert keyboard.inline_keyboard[0][0].callback_data == "create:test.pdf"
    assert keyboard.inline_keyboard[1][0].callback_data == "alt1:test.pdf"
    assert keyboard.inline_keyboard[2][0].callback_data == "alt2:test.pdf"
    assert keyboard.inline_keyboard[3][0].callback_data == "reject:test.pdf"


@pytest.mark.asyncio
async def test_callback_handler_auth(mock_settings) -> None:
    """Ensure unauthorized users are blocked."""
    pending = {}
    handler = create_callback_handler(mock_settings, pending)
    
    # Mock update from unauthorized user
    mock_update = MagicMock()
    mock_update.callback_query.from_user.id = 99999  # Not 12345
    mock_update.callback_query.answer = AsyncMock()
    
    await handler(mock_update, MagicMock())
    
    mock_update.callback_query.answer.assert_called_once_with(
        "⛔ Nicht autorisiert.", show_alert=True
    )
    assert not mock_update.callback_query.edit_message_caption.called
