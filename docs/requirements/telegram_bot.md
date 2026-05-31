# Telegram Bot

Uses `python-telegram-bot` v21+ (async-native). Runs via long-polling alongside the file watcher in the same event loop.

## Security
Every callback query is checked against `TELEGRAM_CHAT_ID` before processing. Unauthorized users receive `⛔ Nicht autorisiert.` and are logged. There is no way to bypass this – the check wraps the actual handler function.

## Notifications

### Auto-filed (existing category)
Text-only message:
```
✅ Datei `2025-03-15_Steuerbescheid.pdf` erfolgreich nach `Finanzen/Steuern` verschoben.
```

### New category proposed
Photo message (page 1 JPEG preview) with caption and 4 inline buttons:
```
📄 Neuer Ordner vorgeschlagen

Datei: `2025-03-15_Mietvertrag.pdf`
Vorgeschlagener Ordner: `Wohnung/Mietverträge`

Was soll ich tun?

[ 📂 Erstellen & Verschieben → Wohnung/Mietverträge ]
[ ➡️ Finanzen/Verträge ]
[ ➡️ Versicherungen ]
[ ❌ Ablehnen (→ Error) ]
```

### Error
Text message with filename and exception details.

## Callback Actions
| `callback_data` prefix | Action |
|---|---|
| `create:{filename}` | Create suggested folder in `/app/archive`, move file there |
| `alt1:{filename}` | Move to `alternative_1` path |
| `alt2:{filename}` | Move to `alternative_2` path |
| `reject:{filename}` | Move to `/app/error` |

After any action the message caption is edited to show the result. Pending metadata is cleaned up from memory.

## State
Pending decisions are stored in a `dict[str, dict]` mapping filename → LLM metadata. This is in-memory only – a container restart loses pending decisions (files remain in `/app/pending`).
