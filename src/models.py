"""Data models for SmartInboxAI.

Uses Pydantic for validated, typed representations of LLM output.
"""

from pydantic import BaseModel


class DocumentMetadata(BaseModel):
    """Structured metadata extracted from a document by the LLM.

    All eight fields are required by the JSON-schema enforced via
    ``response_format`` in the LLM call.
    """

    year: str
    month: str
    day: str
    title: str
    suggested_category: str
    is_new_category: bool
    alternative_1: str
    alternative_2: str
