# SmartInboxAI

Automated Document Management System (DMS) for NAS systems. Monitors an inbox folder for new PDFs, performs OCR, extracts metadata via AI, and automatically sorts documents – with ntfy push notifications for manual decisions.

## Features

- **Asynchronous File Monitoring** – Processes existing PDFs at startup and reacts to new PDFs in the inbox folder
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
| `LLM_API_KEY` | API key for LiteLLM (OpenAI, Mistral, etc.). Can also be provided via `LLM_API_KEY_FILE` when using Docker secrets. |
| `LLM_MODEL` | Optional. LLM model identifier (default: `gpt-4o-mini`). For Mistral API, use `mistral/mistral-small-latest` or `mistral/mistral-large-latest`. |
| `NTFY_URL` | Full URL to the ntfy topic (e.g., `http://ntfy.local/my_topic`) |
| `NTFY_TOKEN` | Optional ntfy access token for protected topics. Can also be provided via `NTFY_TOKEN_FILE`. |
| `SECRET_TOKEN` | Secret token to secure callback URLs. Can also be provided via `SECRET_TOKEN_FILE`. |
| `CALLBACK_BASE_URL` | Base URL for action button callbacks (e.g., `http://192.168.1.100:8000`) |
| `WEBHOOK_PORT` | Port for the FastAPI server (default: `8000`) |
| `IGNORE_FOLDERS` | Comma-separated list of folder names to ignore |
| `WATCHFILES_FORCE_POLLING` | Optional. Set to `true` to force polling mode. **Default: disabled** (uses native OS events / inotify to allow disks to sleep). Required on Windows and macOS host systems when running in Docker, as bind-mounts do not forward filesystem events across the OS boundary. |

> [!NOTE]
> All secret variables (`LLM_API_KEY`, `NTFY_TOKEN`, `SECRET_TOKEN`) support their `_FILE` counterparts (e.g., `LLM_API_KEY_FILE`, `SECRET_TOKEN_FILE`) for Docker secrets compatibility. For backward compatibility, `OPENAI_API_KEY` and `OPENAI_API_KEY_FILE` are also accepted as fallbacks.

## Workflow

At startup, monitoring begins before the inbox is scanned recursively for existing
PDFs (including `.PDF` files). Existing and newly arriving PDFs use the same
processing pipeline and file-stability check. Non-PDF files and paths ignored by
the watcher are skipped. Startup discoveries and overlapping watcher events are
deduplicated while processing; delayed events for unchanged files are also ignored.
Each PDF is processed in an independent asynchronous task.

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
