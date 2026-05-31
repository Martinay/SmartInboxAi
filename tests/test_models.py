"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from src.models import DocumentMetadata


def test_document_metadata_valid() -> None:
    """Test successful instantiation with valid data."""
    data = {
        "year": "2023",
        "month": "10",
        "day": "25",
        "title": "Test_Title",
        "suggested_category": "Finance",
        "is_new_category": False,
        "alternative_1": "Bills",
        "alternative_2": "Misc",
    }
    doc = DocumentMetadata(**data)
    assert doc.year == "2023"
    assert doc.title == "Test_Title"
    assert not doc.is_new_category


def test_document_metadata_missing_fields() -> None:
    """Test validation error when fields are missing."""
    with pytest.raises(ValidationError):
        DocumentMetadata(year="2023", title="Incomplete")
