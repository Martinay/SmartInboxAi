"""ntfy push-notification helpers.

The ``NtfyNotifier`` class wraps all outgoing notifications.  Each
notification is sent as an HTTP POST to the configured ntfy topic URL.
Decision requests include a JPEG preview as attachment and ``http``
action buttons that call back into the local FastAPI webhook server.
"""

import base64
import logging
from pathlib import Path
from urllib.parse import urlencode

import httpx

from src.config import Settings
from src.models import DocumentMetadata

logger = logging.getLogger("SmartInboxAI")


class NtfyNotifier:
    """Sends push notifications via a local ntfy server."""

    def __init__(self, settings: Settings) -> None:
        self._ntfy_url = settings.ntfy_url
        self._callback_base_url = settings.callback_base_url.rstrip("/")
        self._secret_token = settings.secret_token

        # Optional ntfy authentication header.
        self._base_headers: dict[str, str] = {}
        if settings.ntfy_token:
            self._base_headers["Authorization"] = f"Bearer {settings.ntfy_token}"

    @staticmethod
    def _encode_header(val: str) -> str:
        """Encode header values to RFC 2047 base64 if they contain non-ASCII characters."""
        try:
            val.encode("ascii")
            return val
        except UnicodeEncodeError:
            encoded = base64.b64encode(val.encode("utf-8")).decode("ascii")
            return f"=?utf-8?B?{encoded}?="

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _action_url(self, action: str, filename: str) -> str:
        """Build a callback URL for an ntfy action button."""
        params = urlencode({
            "token": self._secret_token,
            "action": action,
            "file": filename,
        })
        return f"{self._callback_base_url}/action?{params}"

    @staticmethod
    def _sanitize_label(label: str) -> str:
        """Strip commas/semicolons that would break the ntfy header format."""
        return label.replace(",", " ").replace(";", " ")

    def _build_actions_header(
        self, filename: str, metadata: DocumentMetadata
    ) -> str:
        """Build the ``X-Actions`` header value with four action buttons.

        Each button triggers an HTTP POST to the local webhook server.
        ``clear=true`` dismisses the notification after the tap.
        """
        suggested = self._sanitize_label(metadata.suggested_category)
        alt1 = self._sanitize_label(metadata.alternative_1)
        alt2 = self._sanitize_label(metadata.alternative_2)

        actions = [
            (
                f"http, 📂 Erstellen → {suggested}, "
                f"{self._action_url('create', filename)}, "
                f"method=POST, clear=true"
            ),
            (
                f"http, ➡️ {alt1}, "
                f"{self._action_url('alt1', filename)}, "
                f"method=POST, clear=true"
            ),
            (
                f"http, ➡️ {alt2}, "
                f"{self._action_url('alt2', filename)}, "
                f"method=POST, clear=true"
            ),
            (
                f"http, ❌ Ablehnen, "
                f"{self._action_url('reject', filename)}, "
                f"method=POST, clear=true"
            ),
        ]
        return "; ".join(actions)

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    async def send_auto_filed(self, filename: str, category: str) -> None:
        """Confirm that a file was automatically filed into an existing category."""
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    self._ntfy_url,
                    headers={
                        **self._base_headers,
                        "X-Title": self._encode_header("✅ Automatisch abgelegt"),
                        "X-Tags": "white_check_mark,file_folder",
                    },
                    content=(
                        f"Datei {filename} erfolgreich nach "
                        f"{category} verschoben."
                    ),
                )
        except Exception as exc:
            logger.error("Error sending ntfy notification: %s", exc)

    async def send_decision_request(
        self,
        filename: str,
        metadata: DocumentMetadata,
        preview_path: Path,
    ) -> None:
        """Send a preview image with action buttons for user decision."""
        actions = self._build_actions_header(filename, metadata)
        message = (
            f"📄 Neuer Ordner vorgeschlagen\n\n"
            f"Datei: {filename}\n"
            f"Vorgeschlagener Ordner: {metadata.suggested_category}"
        )

        headers = {
            **self._base_headers,
            "X-Title": self._encode_header("Neues Dokument einordnen"),
            "X-Message": self._encode_header(message),
            "X-Filename": self._encode_header(preview_path.name),
            "X-Actions": self._encode_header(actions),
            "X-Tags": "page_facing_up",
        }

        try:
            async with httpx.AsyncClient() as client:
                with open(preview_path, "rb") as f:
                    await client.post(
                        self._ntfy_url,
                        headers=headers,
                        content=f.read(),
                    )
        except Exception as exc:
            logger.error("Error sending ntfy decision request: %s", exc)
            # Fallback: text-only notification without image.
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        self._ntfy_url,
                        headers={
                            **self._base_headers,
                            "X-Title": self._encode_header("Neues Dokument einordnen"),
                            "X-Actions": self._encode_header(actions),
                            "X-Tags": "page_facing_up",
                        },
                        content=(
                            message
                            + f"\n\n⚠️ Preview konnte nicht gesendet werden: {exc}"
                        ),
                    )
            except Exception as exc2:
                logger.error("Fallback ntfy notification also failed: %s", exc2)

    async def send_error(self, filename: str, error_msg: str) -> None:
        """Notify the user about a processing error."""
        text = (
            f"Datei: {filename}\n"
            f"Fehler: {error_msg}\n\n"
            f"Die Datei wurde nach /app/error verschoben."
        )
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    self._ntfy_url,
                    headers={
                        **self._base_headers,
                        "X-Title": self._encode_header("❌ Fehler bei Verarbeitung"),
                        "X-Priority": "high",
                        "X-Tags": "rotating_light",
                    },
                    content=text,
                )
        except Exception as exc:
            logger.error("Error sending ntfy error notification: %s", exc)
