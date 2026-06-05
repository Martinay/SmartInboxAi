"""FastAPI webhook receiver for ntfy action-button callbacks.

Provides a ``POST /action`` endpoint that is triggered when the user
taps an action button in the ntfy push notification.  The token query
parameter protects against unauthorised calls.
"""

import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from src.config import Settings
from src.file_ops import move_file
from src.models import DocumentMetadata

logger = logging.getLogger("SmartInboxAI")

_VALID_ACTIONS = frozenset({"create", "alt1", "alt2", "reject"})


def create_webhook_app(
    settings: Settings,
    pending_decisions: dict[str, DocumentMetadata],
) -> FastAPI:
    """Create and return the FastAPI application.

    ``settings`` and ``pending_decisions`` are captured by the endpoint
    closures so that no global state is needed.
    """
    app = FastAPI(
        title="SmartInboxAI Webhook",
        docs_url=None,
        redoc_url=None,
    )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict:
        """Simple health / readiness probe."""
        return {"status": "ok", "pending": len(pending_decisions)}

    # ------------------------------------------------------------------
    # Action callback
    # ------------------------------------------------------------------

    @app.post("/action")
    async def handle_action(
        token: str = Query(..., description="Secret token for authorisation"),
        action: str = Query(..., description="Action to perform"),
        file: str = Query(..., description="Filename in /app/pending"),
    ) -> JSONResponse:
        """Process an ntfy action-button callback.

        Flow: validate token → validate action → look up pending
        decision → perform file operation → clean up state.
        """
        # 1. Token validation
        if token != settings.secret_token:
            logger.warning("Unauthorised callback attempt (invalid token).")
            raise HTTPException(status_code=403, detail="⛔ Nicht autorisiert.")

        # 2. Action validation
        if action not in _VALID_ACTIONS:
            raise HTTPException(
                status_code=400, detail=f"Unbekannte Aktion: {action}"
            )

        # 3. Pending-decisions lookup
        if file not in pending_decisions:
            raise HTTPException(
                status_code=404,
                detail=f"Keine ausstehende Entscheidung für {file} gefunden.",
            )

        metadata = pending_decisions[file]
        pending_file = settings.pending_dir / file

        if not pending_file.exists():
            pending_decisions.pop(file, None)
            raise HTTPException(
                status_code=404,
                detail=f"Datei {file} nicht mehr in /app/pending gefunden.",
            )

        # 4. File operation
        try:
            if action == "create":
                target_dir = settings.archive_dir / metadata.suggested_category
                dest = move_file(pending_file, target_dir, file)
                msg = (
                    f"✅ Ordner erstellt & Datei verschoben nach "
                    f"{dest.parent.relative_to(settings.archive_dir)}/{file}"
                )

            elif action == "alt1":
                target_dir = settings.archive_dir / metadata.alternative_1
                dest = move_file(pending_file, target_dir, file)
                msg = (
                    f"✅ Datei verschoben nach "
                    f"{dest.parent.relative_to(settings.archive_dir)}/{file}"
                )

            elif action == "alt2":
                target_dir = settings.archive_dir / metadata.alternative_2
                dest = move_file(pending_file, target_dir, file)
                msg = (
                    f"✅ Datei verschoben nach "
                    f"{dest.parent.relative_to(settings.archive_dir)}/{file}"
                )

            else:  # reject
                move_file(pending_file, settings.error_dir, file)
                msg = (
                    f"❌ Datei abgelehnt und nach /app/error verschoben: {file}"
                )

            logger.info("Action '%s' completed for %s", action, file)
            return JSONResponse(content={"message": msg})

        except Exception as exc:
            logger.error(
                "Error processing action '%s' for %s: %s", action, file, exc
            )
            raise HTTPException(
                status_code=500, detail=f"Fehler bei Verarbeitung: {exc}"
            )
        finally:
            pending_decisions.pop(file, None)

    return app
