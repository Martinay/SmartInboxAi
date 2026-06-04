# ---------------------------------------------------------------------------
# SmartInboxAI – Dockerfile
# ---------------------------------------------------------------------------
# Enthält alle System-Abhängigkeiten für OCR, PDF-Verarbeitung und
# die Python-Anwendung, verwaltet über uv.
# ---------------------------------------------------------------------------

FROM python:3.12-slim

LABEL maintainer="SmartInboxAI"
LABEL description="Automatisierte Dokumentenverwaltung mit OCR, KI und Telegram-Bot"

# System-Abhängigkeiten installieren:
#  - tesseract-ocr + Sprachpakete (DE, EN) für OCR
#  - ghostscript, qpdf für OCRmyPDF
#  - ocrmypdf als System-Tool
#  - poppler-utils für pdf2image (pdfinfo, pdftoppm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    ghostscript \
    qpdf \
    ocrmypdf \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# uv aus offiziellem Image kopieren
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Arbeitsverzeichnis
WORKDIR /app

# Projekt-Metadaten kopieren und Dependencies installieren (Cache-Layer)
COPY pyproject.toml .
RUN uv sync --no-dev

# Anwendung kopieren
COPY src/ ./src/

# Standardverzeichnisse erstellen (werden i.d.R. über Volumes gemountet)
RUN mkdir -p /app/inbox /app/archive /app/pending /app/error

# Polling-Modus für watchfiles aktivieren – inotify-Events werden bei
# Docker-Bind-Mounts (insb. macOS → Linux) nicht weitergereicht.
ENV WATCHFILES_FORCE_POLLING=true

# Anwendung starten
CMD ["uv", "run", "python", "-m", "src.main"]
