"""Tests for the FastAPI webhook module."""

import pytest
from pathlib import Path

from fastapi.testclient import TestClient

from src.models import DocumentMetadata
from src.webhook import create_webhook_app


@pytest.fixture
def metadata() -> DocumentMetadata:
    return DocumentMetadata(
        year="2024", month="01", day="01", title="Test",
        suggested_category="Finance", is_new_category=True,
        alternative_1="Insurance", alternative_2="Banking",
    )


@pytest.fixture
def pending_with_file(mock_settings, metadata, tmp_path) -> tuple:
    """Set up a pending decision with an actual file in pending_dir."""
    filename = "2024-01-01_Test.pdf"
    pending_file = mock_settings.pending_dir / filename
    pending_file.write_text("pdf content")
    pending_decisions = {filename: metadata}
    return pending_decisions, filename


@pytest.fixture
def client(mock_settings, pending_with_file) -> TestClient:
    """FastAPI TestClient wired to mock settings and pending state."""
    pending_decisions, _ = pending_with_file
    app = create_webhook_app(mock_settings, pending_decisions)
    return TestClient(app)


# ---------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------

def test_health(mock_settings) -> None:
    """Health endpoint returns OK and pending count."""
    pending = {"a.pdf": None, "b.pdf": None}
    app = create_webhook_app(mock_settings, pending)
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "pending": 2}


# ---------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------

def test_invalid_token_returns_403(client) -> None:
    """Request with wrong token is rejected."""
    resp = client.post("/action?token=WRONG&action=create&file=2024-01-01_Test.pdf")
    assert resp.status_code == 403


# ---------------------------------------------------------------
# Validation
# ---------------------------------------------------------------

def test_unknown_action_returns_400(client) -> None:
    """Unknown action name is rejected."""
    resp = client.post("/action?token=test_secret&action=delete&file=2024-01-01_Test.pdf")
    assert resp.status_code == 400


def test_missing_pending_returns_404(mock_settings) -> None:
    """File not in pending_decisions returns 404."""
    app = create_webhook_app(mock_settings, {})
    c = TestClient(app)
    resp = c.post("/action?token=test_secret&action=create&file=unknown.pdf")
    assert resp.status_code == 404


# ---------------------------------------------------------------
# Successful actions
# ---------------------------------------------------------------

def test_create_action_moves_file(client, mock_settings, pending_with_file) -> None:
    """'create' moves file to archive/suggested_category."""
    pending_decisions, filename = pending_with_file

    resp = client.post(f"/action?token=test_secret&action=create&file={filename}")
    assert resp.status_code == 200
    assert "✅" in resp.json()["message"]

    # File moved to archive
    dest = mock_settings.archive_dir / "Finance" / filename
    assert dest.exists()

    # Removed from pending_decisions
    assert filename not in pending_decisions


def test_alt1_action_moves_file(client, mock_settings, pending_with_file) -> None:
    """'alt1' moves file to archive/alternative_1."""
    pending_decisions, filename = pending_with_file

    resp = client.post(f"/action?token=test_secret&action=alt1&file={filename}")
    assert resp.status_code == 200

    dest = mock_settings.archive_dir / "Insurance" / filename
    assert dest.exists()
    assert filename not in pending_decisions


def test_alt2_action_moves_file(client, mock_settings, pending_with_file) -> None:
    """'alt2' moves file to archive/alternative_2."""
    pending_decisions, filename = pending_with_file

    resp = client.post(f"/action?token=test_secret&action=alt2&file={filename}")
    assert resp.status_code == 200

    dest = mock_settings.archive_dir / "Banking" / filename
    assert dest.exists()
    assert filename not in pending_decisions


def test_reject_action_moves_to_error(client, mock_settings, pending_with_file) -> None:
    """'reject' moves file to error directory."""
    pending_decisions, filename = pending_with_file

    resp = client.post(f"/action?token=test_secret&action=reject&file={filename}")
    assert resp.status_code == 200
    assert "❌" in resp.json()["message"]

    dest = mock_settings.error_dir / filename
    assert dest.exists()
    assert filename not in pending_decisions


# ---------------------------------------------------------------
# State cleanup
# ---------------------------------------------------------------

def test_pending_cleaned_on_missing_file(mock_settings, metadata) -> None:
    """If file is in pending_decisions but not on disk, state is cleaned."""
    filename = "ghost.pdf"
    pending = {filename: metadata}
    app = create_webhook_app(mock_settings, pending)
    c = TestClient(app)

    resp = c.post(f"/action?token=test_secret&action=create&file={filename}")
    assert resp.status_code == 404
    assert filename not in pending
