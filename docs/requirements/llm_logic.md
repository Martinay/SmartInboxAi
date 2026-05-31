# LLM Logic

## Provider
All calls go through `litellm.acompletion` with model `gpt-4o-mini` (temperature 0.2).

## Input
The LLM receives:
- A system prompt defining extraction rules
- The document text (first 3 pages, max 4000 chars)
- The current list of archive subfolder paths

## Structured Output Schema
Enforced via `response_format` with `json_schema` (strict mode, `additionalProperties: false`):

```json
{
  "year": "YYYY",
  "month": "MM",
  "day": "DD",
  "title": "Max_Four_Words",
  "suggested_category": "path/to/folder",
  "is_new_category": false,
  "alternative_1": "existing/path",
  "alternative_2": "another/existing/path"
}
```

All 8 fields are required.

## Key Rules (from system prompt)
- Date defaults to today if not recognizable
- Title: max 4 words, underscores instead of spaces, no special chars
- `suggested_category`: best-matching existing path, or a new path if none fits
- `is_new_category`: `true` only when the suggested path does not exist in the list
- `alternative_1` / `alternative_2`: must be existing paths from the list
- If fewer than 2 categories exist, the best match is used for both alternatives
