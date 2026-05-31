# OCR Pipeline

## Processing Steps

Each PDF entering `/app/inbox` goes through this pipeline (as an async task):

1. **Stability check** – Poll file size every 3s, require 3 consecutive identical readings before proceeding. Prevents processing partially-written files from NAS transfers.

2. **Text detection** – `pypdf.PdfReader` checks the first 3 pages for extractable text.

3. **OCR (if needed)** – Invoked via `asyncio.create_subprocess_exec`:
   ```
   ocrmypdf -l eng+deu --skip-text <input> <output>
   ```
   `--skip-text` preserves existing text layers. The OCR'd file replaces the original in-place.

4. **Text extraction** – `pypdf` reads text from the first 3 pages (configurable via `MAX_TEXT_PAGES`). The text is truncated to 4000 chars before sending to the LLM.

5. **Preview generation** – `pdf2image.convert_from_path` renders page 1 as JPEG (150 DPI, quality 85). Used for Telegram decision messages.

6. **Category scan** – `os.walk(/app/archive)` builds a fresh list of all subfolder paths (relative), excluding blacklisted names. This runs before every LLM call to pick up any changes.

7. **LLM analysis** – See `llm_logic.md`.

8. **Rename** – File is renamed to `{YYYY}-{MM}-{DD}_{Title}.pdf`. Title is sanitized (alphanumeric + underscores only).

9. **Route** – Based on `is_new_category`:
   - `false` → move directly to `/app/archive/{suggested_category}/`, send ✅ text notification
   - `true` → move to `/app/pending/`, send photo + inline keyboard to Telegram

## Error Handling
Any exception during processing:
- Moves the file to `/app/error/`
- Sends a Telegram error notification with the exception message
- Never crashes the main loop
