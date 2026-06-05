# SmartInboxAI

Automatisierte Dokumentenverwaltung (DMS) für NAS-Systeme. Überwacht einen Inbox-Ordner auf neue PDFs, führt OCR durch, extrahiert Metadaten via KI und sortiert Dokumente automatisch ein – mit ntfy-Push-Benachrichtigungen für manuelle Entscheidungen.

## Features

- **Asynchrone Dateiüberwachung** – Reagiert sofort auf neue PDFs im Inbox-Ordner
- **OCR (Deutsch & Englisch)** – Erkennt Text in gescannten Dokumenten via OCRmyPDF
- **KI-gestützte Analyse** – Extrahiert Datum, Titel und Kategorie mit GPT-4o-mini
- **Dynamische Kategorien** – Liest Ordnerstruktur automatisch aus dem Archiv
- **ntfy-Benachrichtigungen** – Push-Nachrichten mit Vorschaubild und Action Buttons via lokalen ntfy-Server
- **FastAPI Webhook** – Empfängt Entscheidungen per HTTP-Callback, abgesichert mit Secret Token

## Schnellstart

### 1. Umgebungsvariablen einrichten

```bash
cp .env.example .env
# .env bearbeiten und eigene Werte eintragen
```

### 2. Docker-Image bauen

```bash
docker build -t smartinboxai .
```

### 3. Container starten

```bash
docker run -d \
  --name smartinboxai \
  --env-file .env \
  -p 8000:8000 \
  -v /pfad/zu/inbox:/app/inbox \
  -v /pfad/zu/archiv:/app/archive \
  -v /pfad/zu/pending:/app/pending \
  -v /pfad/zu/error:/app/error \
  --restart unless-stopped \
  smartinboxai
```

### 4. Docker Compose (Alternative)

Erstelle eine `docker-compose.yml`:

```yaml
services:
  smartinboxai:
    build: .
    container_name: smartinboxai
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - /pfad/zu/inbox:/app/inbox
      - /pfad/zu/archiv:/app/archive
      - /pfad/zu/pending:/app/pending
      - /pfad/zu/error:/app/error
    restart: unless-stopped
```

```bash
docker compose up -d
```

## Verzeichnisstruktur

| Verzeichnis | Beschreibung |
|---|---|
| `/app/inbox` | Überwachter Eingangsordner – hier landen neue Scans |
| `/app/archive` | Zielarchiv mit Kategorie-Unterordnern |
| `/app/pending` | Zwischenspeicher bei ausstehenden Nutzer-Entscheidungen |
| `/app/error` | Fehlerhafte oder abgelehnte Dokumente |

## Umgebungsvariablen

| Variable | Beschreibung |
|---|---|
| `OPENAI_API_KEY` | OpenAI API-Schlüssel für GPT-4o-mini |
| `NTFY_URL` | Vollständige URL zum ntfy-Topic (z.B. `http://ntfy.local/mein_topic`) |
| `NTFY_TOKEN` | Optionaler ntfy Access-Token für geschützte Topics |
| `SECRET_TOKEN` | Geheimer Token zur Absicherung der Callback-URLs |
| `CALLBACK_BASE_URL` | Basis-URL für Action-Button-Callbacks (z.B. `http://192.168.1.100:8000`) |
| `WEBHOOK_PORT` | Port für den FastAPI-Server (Standard: `8000`) |
| `IGNORE_FOLDERS` | Kommaseparierte Liste zu ignorierender Ordnernamen |

## Workflow

```
Neue PDF in /inbox
       │
       ▼
  Text vorhanden? ──Nein──▶ OCR (eng+deu)
       │                         │
       ▼                         ▼
  Textextraktion ◀───────────────┘
       │
       ▼
  Vorschaubild erstellen
       │
       ▼
  Kategorien scannen (/archive)
       │
       ▼
  LLM-Analyse (gpt-4o-mini)
       │
       ▼
  Datei umbenennen (YYYY-MM-DD_Titel.pdf)
       │
        ├── Kategorie existiert ──▶ Auto-Verschieben + ntfy ✅
        │
        └── Neue Kategorie ──▶ /pending + ntfy-Entscheidung
                                    │
                                    ├── 📂 Erstellen & Verschieben
                                    ├── ➡️ Alternative 1
                                    ├── ➡️ Alternative 2
                                    └── ❌ Ablehnen (→ /error)
```

## Lizenz

Privates Projekt.
