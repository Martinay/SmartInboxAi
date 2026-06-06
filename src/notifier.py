"""ntfy push-notification helpers.

The ``NtfyNotifier`` class wraps all outgoing notifications.  Each
notification is sent as an HTTP JSON POST to the configured ntfy topic URL.
Decision requests reference a JPEG preview served by the local webhook
and include ``http`` action buttons that call back into the FastAPI server.
"""

import logging
from pathlib import Path
from urllib.parse import urlencode, urlparse

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

        # Extract the topic from the ntfy URL (last path segment).
        self._topic = urlparse(settings.ntfy_url).path.rstrip("/").split("/")[-1]
        # Base URL of the ntfy server (without topic).
        self._ntfy_base_url = settings.ntfy_url.rstrip("/").removesuffix(
            f"/{self._topic}"
        )

        # Optional ntfy authentication header.
        self._base_headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if settings.ntfy_token:
            self._base_headers["Authorization"] = f"Bearer {settings.ntfy_token}"

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
        """Strip commas/semicolons that would break ntfy display."""
        return label.replace(",", " ").replace(";", " ")

    def _build_actions(
        self, filename: str, metadata: DocumentMetadata
    ) -> list[dict]:
        """Build the actions list for a decision notification (JSON format).

        Each action triggers an HTTP POST to the local webhook server.
        ``clear=true`` dismisses the notification after the tap.
        """
        suggested = self._sanitize_label(metadata.suggested_category)
        alt1 = self._sanitize_label(metadata.alternative_1)
        alt2 = self._sanitize_label(metadata.alternative_2)

        return [
            {
                "action": "http",
                "label": f"📂 Erstellen → {suggested}",
                "url": self._action_url("create", filename),
                "method": "POST",
                "clear": True,
            },
            {
                "action": "http",
                "label": f"➡️ {alt1}",
                "url": self._action_url("alt1", filename),
                "method": "POST",
                "clear": True,
            },
            {
                "action": "http",
                "label": f"➡️ {alt2}",
                "url": self._action_url("alt2", filename),
                "method": "POST",
                "clear": True,
            },
            {
                "action": "http",
                "label": "❌ Ablehnen",
                "url": self._action_url("reject", filename),
                "method": "POST",
                "clear": True,
            },
        ]

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    async def send_auto_filed(self, filename: str, category: str) -> None:
        """Confirm that a file was automatically filed into an existing category."""
        payload = {
            "topic": self._topic,
            "title": "✅ Automatisch abgelegt",
            "message": (
                f"Datei {filename} erfolgreich nach "
                f"{category} verschoben."
            ),
            "tags": ["white_check_mark", "file_folder"],
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._ntfy_base_url,
                    headers=self._base_headers,
                    json=payload,
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.error("Error sending ntfy notification: %s", exc)

    async def send_decision_request(
        self,
        filename: str,
        metadata: DocumentMetadata,
        preview_path: Path,
    ) -> None:
        """Send a preview image with action buttons for user decision."""
        actions = self._build_actions(filename, metadata)
        message = (
            f"📄 Neuer Ordner vorgeschlagen\n\n"
            f"Datei: {filename}\n"
            f"Vorgeschlagener Ordner: {metadata.suggested_category}"
        )

        # Build a URL to the preview image served by the webhook server.
        preview_url = f"{self._callback_base_url}/preview/{preview_path.name}"

        payload = {
            "topic": self._topic,
            "title": "Neues Dokument einordnen",
            "message": message,
            "tags": ["page_facing_up"],
            "attach": preview_url,
            "actions": actions,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._ntfy_base_url,
                    headers=self._base_headers,
                    json=payload,
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.error("Error sending ntfy decision request: %s", exc)
            # Fallback: text-only notification without image.
            try:
                fallback_payload = {
                    "topic": self._topic,
                    "title": "Neues Dokument einordnen",
                    "message": (
                        message
                        + f"\n\n⚠️ Preview konnte nicht gesendet werden: {exc}"
                    ),
                    "tags": ["page_facing_up"],
                    "actions": actions,
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        self._ntfy_base_url,
                        headers=self._base_headers,
                        json=fallback_payload,
                    )
                    resp.raise_for_status()
            except Exception as exc2:
                logger.error("Fallback ntfy notification also failed: %s", exc2)

    async def send_error(self, filename: str, error_msg: str) -> None:
        """Notify the user about a processing error."""
        payload = {
            "topic": self._topic,
            "title": "❌ Fehler bei Verarbeitung",
            "message": (
                f"Datei: {filename}\n"
                f"Fehler: {error_msg}\n\n"
                f"Die Datei wurde nach /app/error verschoben."
            ),
            "priority": 4,
            "tags": ["rotating_light"],
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._ntfy_base_url,
                    headers=self._base_headers,
                    json=payload,
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.error("Error sending ntfy error notification: %s", exc)
