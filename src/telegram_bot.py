"""Telegram bot setup, handlers, and notification helpers.

The ``TelegramNotifier`` class wraps all outgoing messages so the bot
instance and chat-ID are injected once at construction.
``create_callback_handler`` returns a closure that captures the
``Settings`` and ``pending_decisions`` dict, keeping all state explicit.
"""

import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import Settings
from src.file_ops import move_file
from src.models import DocumentMetadata

logger = logging.getLogger("SmartInboxAI")


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------


class TelegramNotifier:
    """Sends notifications to the authorised Telegram user."""

    def __init__(self, bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send_auto_filed(self, filename: str, category: str) -> None:
        """Confirm that a file was automatically filed into an existing category."""
        text = f"✅ Datei `{filename}` erfolgreich nach `{category}` verschoben."
        try:
            await self._bot.send_message(
                chat_id=self._chat_id, text=text, parse_mode="Markdown"
            )
        except Exception as exc:
            logger.error("Error sending Telegram message: %s", exc)

    async def send_decision_request(
        self,
        filename: str,
        metadata: DocumentMetadata,
        preview_path: Path,
    ) -> None:
        """Send a photo preview with inline-keyboard for user decision."""
        caption = (
            f"📄 **Neuer Ordner vorgeschlagen**\n\n"
            f"Datei: `{filename}`\n"
            f"Vorgeschlagener Ordner: `{metadata.suggested_category}`\n\n"
            f"Was soll ich tun?"
        )
        keyboard = build_keyboard(metadata, filename)

        try:
            with open(preview_path, "rb") as photo:
                await self._bot.send_photo(
                    chat_id=self._chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
        except Exception as exc:
            logger.error("Error sending decision request: %s", exc)
            # Fallback: text-only message.
            try:
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    text=caption + f"\n\n⚠️ Preview could not be sent: {exc}",
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            except Exception as exc2:
                logger.error("Fallback message also failed: %s", exc2)

    async def send_error(self, filename: str, error_msg: str) -> None:
        """Notify the user about a processing error."""
        text = (
            f"❌ **Fehler bei Verarbeitung**\n\n"
            f"Datei: `{filename}`\n"
            f"Fehler: `{error_msg}`\n\n"
            f"Die Datei wurde nach `/app/error` verschoben."
        )
        try:
            await self._bot.send_message(
                chat_id=self._chat_id, text=text, parse_mode="Markdown"
            )
        except Exception as exc:
            logger.error("Error sending error notification: %s", exc)


# ---------------------------------------------------------------------------
# Keyboard builder
# ---------------------------------------------------------------------------


def build_keyboard(
    metadata: DocumentMetadata,
    filename: str,
) -> InlineKeyboardMarkup:
    """Build the inline keyboard for a pending decision."""
    keyboard = [
        [
            InlineKeyboardButton(
                f"📂 Erstellen & Verschieben → {metadata.suggested_category}",
                callback_data=f"create:{filename}",
            )
        ],
        [
            InlineKeyboardButton(
                f"➡️ {metadata.alternative_1}",
                callback_data=f"alt1:{filename}",
            )
        ],
        [
            InlineKeyboardButton(
                f"➡️ {metadata.alternative_2}",
                callback_data=f"alt2:{filename}",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Ablehnen (→ Error)",
                callback_data=f"reject:{filename}",
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------------
# Callback handler factory
# ---------------------------------------------------------------------------


def create_callback_handler(
    settings: Settings,
    pending_decisions: dict[str, DocumentMetadata],
):
    """Return an async handler closure that processes inline-keyboard presses.

    Security: every callback is checked against ``settings.telegram_chat_id``.
    """
    authorized_user = int(settings.telegram_chat_id)

    async def _secured_callback(update, context) -> None:
        query = update.callback_query

        # -- Access control --
        if query.from_user.id != authorized_user:
            logger.warning(
                "Unauthorised callback attempt from user ID: %s",
                query.from_user.id,
            )
            await query.answer("⛔ Nicht autorisiert.", show_alert=True)
            return

        await query.answer()

        data: str = query.data
        if ":" not in data:
            return

        action, filename = data.split(":", 1)

        if filename not in pending_decisions:
            await query.edit_message_caption(
                caption=f"⚠️ Keine ausstehende Entscheidung für {filename} gefunden."
            )
            return

        metadata = pending_decisions[filename]
        pending_file = settings.pending_dir / filename

        if not pending_file.exists():
            await query.edit_message_caption(
                caption=f"⚠️ Datei {filename} nicht mehr in /app/pending gefunden."
            )
            del pending_decisions[filename]
            return

        try:
            if action == "create":
                target_dir = settings.archive_dir / metadata.suggested_category
                dest = move_file(pending_file, target_dir, filename)
                await query.edit_message_caption(
                    caption=(
                        f"✅ Ordner erstellt & Datei verschoben nach "
                        f"{dest.parent.relative_to(settings.archive_dir)}/{filename}"
                    )
                )

            elif action == "alt1":
                target_dir = settings.archive_dir / metadata.alternative_1
                dest = move_file(pending_file, target_dir, filename)
                await query.edit_message_caption(
                    caption=(
                        f"✅ Datei verschoben nach "
                        f"{dest.parent.relative_to(settings.archive_dir)}/{filename}"
                    )
                )

            elif action == "alt2":
                target_dir = settings.archive_dir / metadata.alternative_2
                dest = move_file(pending_file, target_dir, filename)
                await query.edit_message_caption(
                    caption=(
                        f"✅ Datei verschoben nach "
                        f"{dest.parent.relative_to(settings.archive_dir)}/{filename}"
                    )
                )

            elif action == "reject":
                move_file(pending_file, settings.error_dir, filename)
                await query.edit_message_caption(
                    caption=f"❌ Datei abgelehnt und nach /app/error verschoben: {filename}"
                )

            else:
                await query.edit_message_caption(caption="⚠️ Unbekannte Aktion.")
                return

        except Exception as exc:
            logger.error("Error processing callback: %s", exc)
            await query.edit_message_caption(
                caption=f"❌ Fehler bei Verarbeitung: {exc}"
            )
        finally:
            pending_decisions.pop(filename, None)

    return _secured_callback
