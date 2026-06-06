"""Tests for LLM module."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.llm import analyze_with_llm
from src.models import DocumentMetadata


@pytest.mark.asyncio
@patch("src.llm.litellm.acompletion")
async def test_analyze_with_llm(mock_acompletion) -> None:
    """Ensure LLM analysis parses JSON output into a DocumentMetadata."""
    
    # Mock LLM response
    mock_response = AsyncMock()
    mock_response.choices = [MagicMock()]
    
    expected_data = {
        "year": "2024",
        "month": "01",
        "day": "15",
        "title": "Test_Doc",
        "suggested_category": "Taxes",
        "is_new_category": True,
        "alternative_1": "Misc",
        "alternative_2": "Archive",
    }
    
    mock_response.choices[0].message.content = json.dumps(expected_data)
    mock_acompletion.return_value = mock_response

    metadata = await analyze_with_llm(
        text="Test text", 
        categories=["Misc", "Archive"],
        api_key="test-key",
        model="gpt-test",
    )

    assert isinstance(metadata, DocumentMetadata)
    assert metadata.year == "2024"
    assert metadata.title == "Test_Doc"
    
    # Verify acompletion was called with correct arguments
    mock_acompletion.assert_called_once()
    kwargs = mock_acompletion.call_args.kwargs
    assert kwargs["model"] == "gpt-test"
    assert kwargs["response_format"]["type"] == "json_schema"


# Inline MagicMock since we need it in test
from unittest.mock import MagicMock
