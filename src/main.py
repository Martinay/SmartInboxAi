"""
SmartInboxAI – Automatisierte Dokumentenverwaltung (DMS)

Überwacht einen Inbox-Ordner auf PDFs, führt OCR durch,
lässt ein LLM Metadaten extrahieren und interagiert über
einen Telegram-Bot mit dem Nutzer.
"""

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
IGNORE_FOLDERS_ENV = os.getenv("IGNORE_FOLDERS", "")

INBOX_DIR = Path("/app/inbox")
ARCHIVE_DIR = Path("/app/archive")
PENDING_DIR = Path("/app/pending")
ERROR_DIR = Path("/app/error")

# System-Ordner, die immer ignoriert werden
SYSTEM_BLACKLIST = {"@eaDir", ".snapshot", "#recycle", ".DS_Store", "@tmp"}
# Benutzer-Blacklist aus Umgebungsvariable
USER_BLACKLIST = {
    f.strip() for f in IGNORE_FOLDERS_ENV.split(",") if f.strip()
}
BLACKLIST = SYSTEM_BLACKLIST | USER_BLACKLIST

# Stabilität: Datei muss diese Sekunden gleich groß bleiben
FILE_STABLE_SECONDS = 3
FILE_STABLE_CHECKS = 3

# LLM
LLM_MODEL = "gpt-4o-mini"
MAX_TEXT_PAGES = 3

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SmartInboxAI")

# In-Memory-Speicher für ausstehende Entscheidungen (filename → metadata)
pending_decisions: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def scan_categories(archive_path: Path) -> list[str]:
    """
    Scannt den Archive-Ordner rekursiv und gibt alle Unterordner-Pfade
    relativ zum Archive-Root zurück.  Blacklist-Ordner werden übersprungen.
    """
    categories: list[str] = []
    if not archive_path.exists():
        return categories

    for dirpath, dirnames, _ in os.walk(archive_path):
        # In-place-Filter: Ordner aus der Blacklist nicht betreten
        dirnames[:] = [d for d in dirnames if d not in BLACKLIST]

        rel = os.path.relpath(dirpath, archive_path)
        if rel != ".":
            categories.append(rel)

    categories.sort()
    return categories


async def wait_for_stable_file(filepath: Path) -> bool:
    """
    Wartet, bis die Dateigröße über mehrere Prüfungen konstant bleibt.
    Gibt False zurück, wenn die Datei zwischenzeitlich verschwindet.
    """
    last_size = -1
    stable_count = 0

    for _ in range(30):  # Max ~90 Sekunden warten
        if not filepath.exists():
            return False

        current_size = filepath.stat().st_size
        if current_size == last_size and current_size > 0:
            stable_count += 1
            if stable_count >= FILE_STABLE_CHECKS:
                return True
        else:
            stable_count = 0

        last_size = current_size
        await asyncio.sleep(FILE_STABLE_SECONDS)

    logger.warning("Datei %s wurde nicht stabil innerhalb des Zeitlimits.", filepath)
    return False


def has_text(pdf_path: Path) -> bool:
    """Prüft mit pypdf, ob mindestens eine Seite extrahierbaren Text enthält."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages[:MAX_TEXT_PAGES]:
            text = page.extract_text()
            if text and text.strip():
                return True
    except Exception as exc:
        logger.warning("Fehler beim Text-Check für %s: %s", pdf_path.name, exc)
    return False


async def run_ocr(pdf_path: Path) -> Path:
    """
    Führt OCRmyPDF asynchron aus.
    Gibt den Pfad zur OCR-verarbeiteten Datei zurück.
    """
    output_path = pdf_path.with_suffix(".ocr.pdf")

    process = await asyncio.create_subprocess_exec(
        "ocrmypdf",
        "-l", "eng+deu",
        "--skip-text",
        str(pdf_path),
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unbekannter OCR-Fehler"
        raise RuntimeError(f"OCR fehlgeschlagen für {pdf_path.name}: {error_msg}")

    # Originaldatei durch OCR-Version ersetzen
    shutil.move(str(output_path), str(pdf_path))
    logger.info("OCR abgeschlossen für %s", pdf_path.name)
    return pdf_path


def extract_text(pdf_path: Path, max_pages: int = MAX_TEXT_PAGES) -> str:
    """Extrahiert Text der ersten N Seiten mit pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    text_parts: list[str] = []

    for page in reader.pages[:max_pages]:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text.strip())

    return "\n\n".join(text_parts)


def generate_preview(pdf_path: Path) -> Path:
    """Erzeugt ein JPEG-Vorschaubild der ersten Seite."""
    from pdf2image import convert_from_path

    images = convert_from_path(str(pdf_path), first_page=1, last_page=1, dpi=150)

    preview_path = pdf_path.with_suffix(".jpg")
    images[0].save(str(preview_path), "JPEG", quality=85)
    logger.info("Vorschaubild erstellt: %s", preview_path.name)
    return preview_path


# ---------------------------------------------------------------------------
# LLM-Analyse
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
Du bist ein Dokumentenmanagement-Assistent. Analysiere den folgenden Dokumenttext \
und extrahiere Metadaten. Antworte ausschließlich im vorgegebenen JSON-Format.

Regeln:
- "year", "month", "day": Datum des Dokuments im Format YYYY, MM, DD. \
Falls nicht erkennbar, verwende das heutige Datum.
- "title": Kurzer, beschreibender Titel (maximal 4 Wörter, keine Sonderzeichen, \
Leerzeichen durch Unterstriche ersetzen).
- "suggested_category": Der am besten passende Ordnerpfad aus der Kategorie-Liste. \
Falls keine passt, schlage einen NEUEN, sinnvollen Pfad vor.
- "is_new_category": true, wenn "suggested_category" NICHT in der Liste existiert; \
false, wenn er existiert.
- "alternative_1": Ein bestehender Ordnerpfad als erste Alternative (muss aus der Liste stammen).
- "alternative_2": Ein anderer bestehender Ordnerpfad als zweite Alternative (muss aus der Liste stammen).

Falls weniger als 2 Kategorien existieren, verwende den am besten passenden für beide Alternativen.\
"""


async def analyze_with_llm(text: str, categories: list[str]) -> dict:
    """
    Sendet den Dokumenttext und die aktuelle Kategorie-Liste an das LLM
    und erwartet strukturierte Metadaten zurück.
    """
    import litellm

    categories_str = "\n".join(f"- {c}" for c in categories) if categories else "- (keine Kategorien vorhanden)"

    user_message = (
        f"Dokumenttext:\n{text[:4000]}\n\n"
        f"Verfügbare Kategorien:\n{categories_str}"
    )

    response = await litellm.acompletion(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "document_metadata",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "year": {"type": "string", "description": "Jahr im Format YYYY"},
                        "month": {"type": "string", "description": "Monat im Format MM"},
                        "day": {"type": "string", "description": "Tag im Format DD"},
                        "title": {
                            "type": "string",
                            "description": "Kurztitel, max 4 Wörter, Unterstriche statt Leerzeichen",
                        },
                        "suggested_category": {
                            "type": "string",
                            "description": "Vorgeschlagener Ordnerpfad",
                        },
                        "is_new_category": {
                            "type": "boolean",
                            "description": "True wenn Kategorie neu erstellt werden soll",
                        },
                        "alternative_1": {
                            "type": "string",
                            "description": "Erste alternative bestehende Kategorie",
                        },
                        "alternative_2": {
                            "type": "string",
                            "description": "Zweite alternative bestehende Kategorie",
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
                },
            },
        },
        temperature=0.2,
    )

    content = response.choices[0].message.content
    metadata = json.loads(content)
    logger.info("LLM-Analyse abgeschlossen: %s", metadata)
    return metadata


# ---------------------------------------------------------------------------
# Dateiverwaltung
# ---------------------------------------------------------------------------


def build_new_filename(metadata: dict) -> str:
    """Erzeugt den neuen Dateinamen aus den Metadaten."""
    year = metadata.get("year", "0000")
    month = metadata.get("month", "00")
    day = metadata.get("day", "00")
    title = metadata.get("title", "Unbenannt")
    # Sonderzeichen entfernen, nur Buchstaben, Ziffern, Unterstriche
    safe_title = "".join(
        c if c.isalnum() or c == "_" else "_" for c in title
    ).strip("_")
    return f"{year}-{month}-{day}_{safe_title}.pdf"


def move_file(src: Path, dest_dir: Path, filename: str) -> Path:
    """Verschiebt eine Datei sicher in den Zielordner."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename

    # Falls Datei bereits existiert, Suffix anhängen
    counter = 1
    while dest.exists():
        stem = dest.stem
        dest = dest_dir / f"{stem}_{counter}.pdf"
        counter += 1

    shutil.move(str(src), str(dest))
    logger.info("Datei verschoben: %s → %s", src.name, dest)
    return dest


def cleanup_preview(pdf_path: Path) -> None:
    """Entfernt das zugehörige Vorschaubild, falls vorhanden."""
    preview = pdf_path.with_suffix(".jpg")
    if preview.exists():
        preview.unlink()


# ---------------------------------------------------------------------------
# Telegram-Bot
# ---------------------------------------------------------------------------


def _build_keyboard(metadata: dict, filename: str):
    """Erzeugt das Inline-Keyboard für eine ausstehende Entscheidung."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    suggested = metadata["suggested_category"]
    alt1 = metadata["alternative_1"]
    alt2 = metadata["alternative_2"]

    keyboard = [
        [InlineKeyboardButton(
            f"📂 Erstellen & Verschieben → {suggested}",
            callback_data=f"create:{filename}",
        )],
        [InlineKeyboardButton(
            f"➡️ {alt1}",
            callback_data=f"alt1:{filename}",
        )],
        [InlineKeyboardButton(
            f"➡️ {alt2}",
            callback_data=f"alt2:{filename}",
        )],
        [InlineKeyboardButton(
            "❌ Ablehnen (→ Error)",
            callback_data=f"reject:{filename}",
        )],
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_callback(update, context) -> None:
    """Verarbeitet Button-Klicks des Telegram Inline-Keyboards."""
    from telegram import Update

    query = update.callback_query
    await query.answer()

    data = query.data
    if ":" not in data:
        return

    action, filename = data.split(":", 1)

    if filename not in pending_decisions:
        await query.edit_message_caption(
            caption=f"⚠️ Keine ausstehende Entscheidung für {filename} gefunden."
        )
        return

    metadata = pending_decisions[filename]
    pending_file = PENDING_DIR / filename

    if not pending_file.exists():
        await query.edit_message_caption(
            caption=f"⚠️ Datei {filename} nicht mehr in /app/pending gefunden."
        )
        del pending_decisions[filename]
        return

    try:
        if action == "create":
            # Neuen Ordner erstellen und Datei verschieben
            target_dir = ARCHIVE_DIR / metadata["suggested_category"]
            dest = move_file(pending_file, target_dir, filename)
            await query.edit_message_caption(
                caption=f"✅ Ordner erstellt & Datei verschoben nach {dest.parent.relative_to(ARCHIVE_DIR)}/{filename}"
            )

        elif action == "alt1":
            target_dir = ARCHIVE_DIR / metadata["alternative_1"]
            dest = move_file(pending_file, target_dir, filename)
            await query.edit_message_caption(
                caption=f"✅ Datei verschoben nach {dest.parent.relative_to(ARCHIVE_DIR)}/{filename}"
            )

        elif action == "alt2":
            target_dir = ARCHIVE_DIR / metadata["alternative_2"]
            dest = move_file(pending_file, target_dir, filename)
            await query.edit_message_caption(
                caption=f"✅ Datei verschoben nach {dest.parent.relative_to(ARCHIVE_DIR)}/{filename}"
            )

        elif action == "reject":
            dest = move_file(pending_file, ERROR_DIR, filename)
            await query.edit_message_caption(
                caption=f"❌ Datei abgelehnt und nach /app/error verschoben: {filename}"
            )

        else:
            await query.edit_message_caption(caption="⚠️ Unbekannte Aktion.")
            return

    except Exception as exc:
        logger.error("Fehler bei Callback-Verarbeitung: %s", exc)
        await query.edit_message_caption(
            caption=f"❌ Fehler bei Verarbeitung: {exc}"
        )
    finally:
        # Aufräumen
        pending_decisions.pop(filename, None)
        cleanup_preview(PENDING_DIR / filename)


async def send_auto_filed_notification(bot, filename: str, category: str) -> None:
    """Sendet eine einfache Bestätigung für automatisch einsortierte Dateien."""
    chat_id = int(TELEGRAM_CHAT_ID)
    text = f"✅ Datei `{filename}` erfolgreich nach `{category}` verschoben."
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Fehler beim Senden der Telegram-Nachricht: %s", exc)


async def send_decision_request(
    bot, filename: str, metadata: dict, preview_path: Path
) -> None:
    """Sendet das Vorschaubild mit Inline-Keyboard an den Nutzer."""
    chat_id = int(TELEGRAM_CHAT_ID)
    suggested = metadata["suggested_category"]

    caption = (
        f"📄 **Neuer Ordner vorgeschlagen**\n\n"
        f"Datei: `{filename}`\n"
        f"Vorgeschlagener Ordner: `{suggested}`\n\n"
        f"Was soll ich tun?"
    )

    keyboard = _build_keyboard(metadata, filename)

    try:
        with open(preview_path, "rb") as photo:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
    except Exception as exc:
        logger.error("Fehler beim Senden der Entscheidungsanfrage: %s", exc)
        # Fallback: Nur Text senden
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=caption + f"\n\n⚠️ Vorschaubild konnte nicht gesendet werden: {exc}",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception as exc2:
            logger.error("Auch Fallback-Nachricht fehlgeschlagen: %s", exc2)


async def send_error_notification(bot, filename: str, error_msg: str) -> None:
    """Sendet eine Fehlermeldung über Telegram."""
    chat_id = int(TELEGRAM_CHAT_ID)
    text = (
        f"❌ **Fehler bei Verarbeitung**\n\n"
        f"Datei: `{filename}`\n"
        f"Fehler: `{error_msg}`\n\n"
        f"Die Datei wurde nach `/app/error` verschoben."
    )
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Fehler beim Senden der Fehler-Nachricht: %s", exc)


# ---------------------------------------------------------------------------
# Dateiverarbeitungs-Pipeline
# ---------------------------------------------------------------------------


async def process_file(pdf_path: Path, bot) -> None:
    """
    Vollständige Verarbeitungspipeline für eine einzelne PDF-Datei.

    1. Stabilität prüfen
    2. Text-Check / OCR
    3. Textextraktion
    4. Vorschaubild erstellen
    5. Kategorien scannen
    6. LLM-Analyse
    7. Umbenennen
    8. Verschieben oder Telegram-Entscheidung
    """
    original_name = pdf_path.name
    logger.info("Starte Verarbeitung: %s", original_name)

    try:
        # 1. Warten bis Datei stabil ist
        stable = await wait_for_stable_file(pdf_path)
        if not stable:
            logger.warning("Datei %s ist nicht stabil oder verschwunden.", original_name)
            return

        # 2. Text-Check und ggf. OCR
        if not has_text(pdf_path):
            logger.info("Kein Text gefunden in %s, starte OCR...", original_name)
            await run_ocr(pdf_path)
        else:
            logger.info("Text bereits vorhanden in %s", original_name)

        # 3. Text extrahieren
        text = extract_text(pdf_path)
        if not text.strip():
            raise RuntimeError(
                f"Kein Text extrahierbar aus {original_name} (auch nach OCR)."
            )

        # 4. Vorschaubild erstellen
        preview_path = generate_preview(pdf_path)

        # 5. Aktuelle Kategorien scannen
        categories = scan_categories(ARCHIVE_DIR)
        logger.info("Gefundene Kategorien: %d", len(categories))

        # 6. LLM-Analyse
        metadata = await analyze_with_llm(text, categories)

        # 7. Datei umbenennen
        new_filename = build_new_filename(metadata)
        new_path = pdf_path.parent / new_filename
        if pdf_path != new_path:
            shutil.move(str(pdf_path), str(new_path))
            pdf_path = new_path
            logger.info("Datei umbenannt: %s → %s", original_name, new_filename)

            # Vorschaubild ebenfalls umbenennen
            new_preview = pdf_path.with_suffix(".jpg")
            if preview_path.exists() and preview_path != new_preview:
                shutil.move(str(preview_path), str(new_preview))
                preview_path = new_preview

        # 8. Entscheidung: Automatisch oder manuell?
        if not metadata.get("is_new_category", False):
            # Fall A: Bestehende Kategorie → automatisch verschieben
            target_dir = ARCHIVE_DIR / metadata["suggested_category"]
            move_file(pdf_path, target_dir, new_filename)
            cleanup_preview(pdf_path)  # Vorschau löschen
            await send_auto_filed_notification(
                bot, new_filename, metadata["suggested_category"]
            )
            logger.info(
                "Automatisch einsortiert: %s → %s",
                new_filename,
                metadata["suggested_category"],
            )
        else:
            # Fall B: Neue Kategorie → Nutzer fragen
            move_file(pdf_path, PENDING_DIR, new_filename)

            # Vorschaubild auch nach pending verschieben
            pending_preview = PENDING_DIR / f"{Path(new_filename).stem}.jpg"
            if preview_path.exists():
                shutil.move(str(preview_path), str(pending_preview))
                preview_path = pending_preview

            # Metadata für Callback speichern
            pending_decisions[new_filename] = metadata

            await send_decision_request(bot, new_filename, metadata, preview_path)
            logger.info(
                "Nutzer-Entscheidung angefragt für: %s (Vorschlag: %s)",
                new_filename,
                metadata["suggested_category"],
            )

    except Exception as exc:
        logger.error("Fehler bei Verarbeitung von %s: %s", original_name, exc)

        # Datei nach Error verschieben
        try:
            error_file = pdf_path if pdf_path.exists() else None
            if error_file:
                move_file(error_file, ERROR_DIR, pdf_path.name)
                cleanup_preview(error_file)
        except Exception as move_exc:
            logger.error("Konnte Datei nicht nach /error verschieben: %s", move_exc)

        # Telegram-Fehlermeldung senden
        await send_error_notification(bot, original_name, str(exc))


# ---------------------------------------------------------------------------
# Dateiüberwachung
# ---------------------------------------------------------------------------


async def watch_inbox(bot, stop_event: asyncio.Event) -> None:
    """Überwacht den Inbox-Ordner asynchron auf neue PDF-Dateien."""
    from watchfiles import awatch, Change

    logger.info("Starte Überwachung von %s ...", INBOX_DIR)

    # Sicherstellen, dass alle Verzeichnisse existieren
    for d in (INBOX_DIR, ARCHIVE_DIR, PENDING_DIR, ERROR_DIR):
        d.mkdir(parents=True, exist_ok=True)

    async for changes in awatch(INBOX_DIR, stop_event=stop_event):
        for change_type, filepath in changes:
            filepath = Path(filepath)

            # Nur neue/geänderte PDFs verarbeiten
            if change_type not in (Change.added, Change.modified):
                continue
            if filepath.suffix.lower() != ".pdf":
                continue
            if not filepath.exists():
                continue

            logger.info("Neue Datei erkannt: %s (%s)", filepath.name, change_type.name)
            asyncio.create_task(process_file(filepath, bot))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """Hauptfunktion: Startet Bot und Dateiüberwachung parallel."""
    from telegram.ext import Application, CallbackQueryHandler, filters

    # Konfiguration validieren
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN ist nicht gesetzt!")
        sys.exit(1)
    if not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_CHAT_ID ist nicht gesetzt!")
        sys.exit(1)
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY ist nicht gesetzt – LLM-Aufrufe werden fehlschlagen.")

    logger.info("SmartInboxAI startet...")
    logger.info("Inbox:   %s", INBOX_DIR)
    logger.info("Archiv:  %s", ARCHIVE_DIR)
    logger.info("Pending: %s", PENDING_DIR)
    logger.info("Error:   %s", ERROR_DIR)
    logger.info("Blacklist: %s", BLACKLIST)

    # Telegram-Bot erstellen
    authorized_user = int(TELEGRAM_CHAT_ID)
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Sicherheits-Wrapper: Nur autorisierte Nutzer dürfen interagieren.
    # CallbackQueryHandler unterstützt keinen User-Filter direkt,
    # daher prüfen wir die User-ID im Handler selbst.
    async def secured_callback(update, context):
        """Wrapper, der nur autorisierte Nutzer durchlässt."""
        if update.callback_query.from_user.id != authorized_user:
            logger.warning(
                "Unautorisierter Callback-Versuch von User-ID: %s",
                update.callback_query.from_user.id,
            )
            await update.callback_query.answer("⛔ Nicht autorisiert.", show_alert=True)
            return
        await handle_callback(update, context)

    application.add_handler(
        CallbackQueryHandler(
            secured_callback,
            pattern=r"^(create|alt1|alt2|reject):",
        )
    )

    stop_event = asyncio.Event()

    async with application:
        await application.start()
        await application.updater.start_polling(
            allowed_updates=["callback_query"],
        )
        logger.info("Telegram-Bot gestartet (Polling).")

        try:
            await watch_inbox(application.bot, stop_event)
        except KeyboardInterrupt:
            logger.info("Beende SmartInboxAI...")
        finally:
            stop_event.set()
            await application.updater.stop()
            await application.stop()

    logger.info("SmartInboxAI beendet.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
