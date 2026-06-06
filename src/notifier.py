"""ntfy push-notification helpers.

The ``NtfyNotifier`` class wraps all outgoing notifications.  Each
notification is sent as an HTTP POST to the configured ntfy topic URL
using the header-based publishing API (plain text body + HTTP headers).
Decision requests reference a JPEG preview served by the local webhook
and include ``http`` action buttons that call back into the FastAPI server.
"""

import base64
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
        """Strip commas/semicolons that would break ntfy display."""
        return label.replace(",", " ").replace(";", " ")

    def _build_actions_header(
        self, filename: str, metadata: DocumentMetadata
    ) -> str:
        """Build the X-Actions header value for a decision notification.

        Each action is formatted as a semicolon-separated entry using
        ntfy's header action syntax:
        ``http, <label>, <url>, method=POST, clear=true``
        """
        suggested = self._sanitize_label(metadata.suggested_category)
        alt1 = self._sanitize_label(metadata.alternative_1)
        alt2 = self._sanitize_label(metadata.alternative_2)

        actions = [
            (f"📂 Erstellen → {suggested}", self._action_url("create", filename)),
            (f"➡️ {alt1}", self._action_url("alt1", filename)),
            (f"➡️ {alt2}", self._action_url("alt2", filename)),
            ("❌ Ablehnen", self._action_url("reject", filename)),
        ]

        parts = []
        for label, url in actions:
            parts.append(f"http, {label}, {url}, method=POST, clear=true")
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    async def send_auto_filed(self, filename: str, category: str) -> None:
        """Confirm that a file was automatically filed into an existing category."""
        message = (
            f"Datei {filename} erfolgreich nach "
            f"{category} verschoben."
        )
        headers = {
            **self._base_headers,
            "X-Title": self._encode_header("✅ Automatisch abgelegt"),
            "X-Tags": "white_check_mark,file_folder",
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._ntfy_url,
                    headers=headers,
                    content=message.encode("utf-8"),
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
        actions_header = self._build_actions_header(filename, metadata)
        message = (
            f"📄 Neuer Ordner vorgeschlagen\n\n"
            f"Datei: {filename}\n"
            f"Vorgeschlagener Ordner: {metadata.suggested_category}"
        )

        try:
            image_bytes = preview_path.read_bytes() if preview_path.exists() else b""
            if not image_bytes:
                raise FileNotFoundError(f"Preview not found: {preview_path}")

            headers = {
                **self._base_headers,
                "X-Title": self._encode_header("Neues Dokument einordnen"),
                "X-Tags": "page_facing_up",
                "X-Message": self._encode_header(message.replace("\n", "\\n")),
                "X-Filename": self._encode_header(preview_path.name),
                "X-Actions": self._encode_header(actions_header),
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._ntfy_url,
                    headers=headers,
                    content=image_bytes,
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.error("Error sending ntfy decision request: %s", exc)
            # Fallback: text-only notification without image.
            try:
                fallback_msg = (
                    message
                    + f"\n\n⚠️ Preview konnte nicht gesendet werden: {exc}"
                )
                fallback_headers = {
                    **self._base_headers,
                    "X-Title": self._encode_header("Neues Dokument einordnen"),
                    "X-Tags": "page_facing_up",
                    "X-Message": self._encode_header(fallback_msg.replace("\n", "\\n")),
                    "X-Actions": self._encode_header(actions_header),
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        self._ntfy_url,
                        headers=fallback_headers,
                    )
                    resp.raise_for_status()
            except Exception as exc2:
                logger.error("Fallback ntfy notification also failed: %s", exc2)

    async def send_error(self, filename: str, error_msg: str) -> None:
        """Notify the user about a processing error."""
        message = (
            f"Datei: {filename}\n"
            f"Fehler: {error_msg}\n\n"
            f"Die Datei wurde nach /app/error verschoben."
        )
        headers = {
            **self._base_headers,
            "X-Title": self._encode_header("❌ Fehler bei Verarbeitung"),
            "X-Priority": "4",
            "X-Tags": "rotating_light",
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._ntfy_url,
                    headers=headers,
                    content=message.encode("utf-8"),
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.error("Error sending ntfy error notification: %s", exc)
