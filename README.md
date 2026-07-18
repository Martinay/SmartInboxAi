# SmartInboxAI

Automated Document Management System (DMS) for NAS systems. Monitors an inbox folder for new PDFs, performs OCR, extracts metadata via AI, and automatically sorts documents – with ntfy push notifications for manual decisions.

## Features

- **Asynchronous File Monitoring** – Reacts immediately to new PDFs in the inbox folder
- **OCR (German & English)** – Recognizes text in scanned documents via OCRmyPDF
- **AI-Powered Analysis** – Extracts date, title, and category using GPT-4o-mini
- **Dynamic Categories** – Automatically reads folder structure from the archive
- **ntfy Notifications** – Push messages with preview images and action buttons via a local ntfy server
- **FastAPI Webhook** – Receives decisions via HTTP callback, secured with a Secret Token

## Quick Start

### 1. Set Up Environment Variables

```bash
cp .env.example .env
# Edit .env and enter your own values
```

### 2. Build Docker Image

```bash
docker build -t smartinboxai .
```

### 3. Start Container

```bash
docker run -d \
  --name smartinboxai \
  --env-file .env \
  -p 8000:8000 \
  -v /path/to/inbox:/app/inbox \
  -v /path/to/archive:/app/archive \
  -v /path/to/pending:/app/pending \
  -v /path/to/error:/app/error \
  --restart unless-stopped \
  smartinboxai
```

### 4. Docker Compose (Alternative)

Create a `docker-compose.yml`:

```yaml
services:
  smartinboxai:
    build: .
    container_name: smartinboxai
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - /path/to/inbox:/app/inbox
      - /path/to/archive:/app/archive
      - /path/to/pending:/app/pending
      - /path/to/error:/app/error
    restart: unless-stopped
```

```bash
docker compose up -d
```

## Directory Structure

| Directory | Description |
|---|---|
| `/app/inbox` | Monitored input folder – new scans land here |
| `/app/archive` | Target archive with category subfolders |
| `/app/pending` | Temporary storage for pending user decisions |
| `/app/error` | Failed or rejected documents |

## Environment Variables

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o-mini |
| `NTFY_URL` | Full URL to the ntfy topic (e.g., `http://ntfy.local/my_topic`) |
| `NTFY_TOKEN` | Optional ntfy access token for protected topics |
| `SECRET_TOKEN` | Secret token to secure callback URLs |
| `CALLBACK_BASE_URL` | Base URL for action button callbacks (e.g., `http://192.168.1.100:8000`) |
| `WEBHOOK_PORT` | Port for the FastAPI server (default: `8000`) |
| `IGNORE_FOLDERS` | Comma-separated list of folder names to ignore |

## Workflow

```
New PDF in /inbox
       │
       ▼
  Text exists? ──No──▶ OCR (eng+ger)
       │                         │
       ▼                         ▼
  Text Extraction ◀──────────────┘
       │
       ▼
  Generate Preview Image
       │
       ▼
  Scan Categories (/archive)
       │
       ▼
  LLM Analysis (gpt-4o-mini)
       │
       ▼
  Rename File (YYYY-MM-DD_Title.pdf)
       │
        ├── Category exists ──▶ Auto-Move + ntfy ✅
        │
        └── New Category ──▶ /pending + ntfy-decision
                                    │
                                    ├── 📂 Create & Move
                                    ├── ➡️ Alternative 1
                                    ├── ➡️ Alternative 2
                                    └── ❌ Reject (→ /error)
```
