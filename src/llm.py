"""LLM analysis for document metadata extraction.

Uses ``litellm.acompletion`` with a strict JSON-schema response format
to enforce structured output.
"""

import json
import logging

import litellm

from src.models import DocumentMetadata

logger = logging.getLogger("SmartInboxAI")

SYSTEM_PROMPT = """\
Du bist ein Dokumentenmanagement-Assistent. Analysiere den folgenden Dokumenttext \
und extrahiere Metadaten. Antworte ausschließlich im vorgegebenen JSON-Format.

Regeln:
- "year", "month", "day": Datum des Dokuments im Format YYYY, MM, DD. \
Falls nicht erkennbar, verwende das heutige Datum.
- "title": Kurzer, beschreibender Titel (maximal 4 Wörter, keine Sonderzeichen, \
Leerzeichen durch Unterstriche ersetzen).
- "suggested_category": Der am besten passende Ordnerpfad aus der Kategorie-Liste. \
Falls keine passt, schlage einen NEUEN, sinnvollen Pfad vor. \
WICHTIG: Wenn ein existierender Ordner gewählt wird, muss der Pfad EXAKT so geschrieben \
werden, wie er in der Liste steht – gleiche Groß-/Kleinschreibung, gleiche Leerzeichen, \
keine Unterstriche einfügen oder entfernen.
- "is_new_category": true, wenn "suggested_category" NICHT in der Liste existiert; \
false, wenn er existiert.
- "alternative_1": Ein bestehender Ordnerpfad als erste Alternative. \
Muss EXAKT so geschrieben werden, wie er in der Kategorie-Liste steht.
- "alternative_2": Ein anderer bestehender Ordnerpfad als zweite Alternative. \
Muss EXAKT so geschrieben werden, wie er in der Kategorie-Liste steht.

Falls weniger als 2 Kategorien existieren, verwende den am besten passenden für beide Alternativen.\
"""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "year": {"type": "string", "description": "Year in YYYY format"},
        "month": {"type": "string", "description": "Month in MM format"},
        "day": {"type": "string", "description": "Day in DD format"},
        "title": {
            "type": "string",
            "description": "Short title, max 4 words, underscores instead of spaces",
        },
        "suggested_category": {
            "type": "string",
            "description": "Suggested folder path",
        },
        "is_new_category": {
            "type": "boolean",
            "description": "True if the category should be newly created",
        },
        "alternative_1": {
            "type": "string",
            "description": "First alternative existing category",
        },
        "alternative_2": {
            "type": "string",
            "description": "Second alternative existing category",
        },
    },
    "required": [
        "year",
        "month",
        "day",
        "title",
        "suggested_category",
        "is_new_category",
        "alternative_1",
        "alternative_2",
    ],
    "additionalProperties": False,
}


def _match_category(value: str, categories: list[str]) -> str:
    """Return the exact category from *categories* that best matches *value*.

    Uses case-insensitive + whitespace/underscore-normalised comparison so
    that LLM variations like ``TC_Mörsch`` still resolve to the real folder
    name ``Tc Mörsch``.  Returns *value* unchanged if no match is found
    (e.g. genuinely new category).
    """
    if not categories:
        return value

    def _normalise(s: str) -> str:
        return s.lower().replace("_", " ").replace("-", " ").strip()

    norm_value = _normalise(value)

    # 1. Exact match (fast path).
    if value in categories:
        return value

    # 2. Normalised match.
    for cat in categories:
        if _normalise(cat) == norm_value:
            logger.debug(
                "Corrected LLM category %r → %r (normalised match)",
                value,
                cat,
            )
            return cat

    return value


async def analyze_with_llm(
    text: str,
    categories: list[str],
    *,
    model: str = "gpt-5.4-nano",
    temperature: float = 0.2,
    max_text_chars: int = 4000,
) -> DocumentMetadata:
    """Send document text and category list to the LLM.

    Returns a validated :class:`DocumentMetadata` instance.
    """
    categories_str = (
        "\n".join(f"- {c}" for c in categories)
        if categories
        else "- (keine Kategorien vorhanden)"
    )

    user_message = (
        f"Dokumenttext:\n{text[:max_text_chars]}\n\n"
        f"Verfügbare Kategorien:\n{categories_str}"
    )

    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "document_metadata",
                "strict": True,
                "schema": JSON_SCHEMA,
            },
        },
        temperature=temperature,
    )

    content = response.choices[0].message.content
    metadata = DocumentMetadata(**json.loads(content))

    # Correct category fields to match real folder names exactly.
    metadata.suggested_category = _match_category(
        metadata.suggested_category, categories
    )
    metadata.alternative_1 = _match_category(metadata.alternative_1, categories)
    metadata.alternative_2 = _match_category(metadata.alternative_2, categories)

    logger.info("LLM analysis completed: %s", metadata.model_dump())
    return metadata
