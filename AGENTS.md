Project: SmartInboxAI
Stack: Python 3.12+, uv, asyncio, Docker.
Project Layout: Source code lives in `src/`. Entry point is `src/main.py`.

## Core Security Rules
- **Telegram Bot Access Control**: The bot MUST strictly ignore any Chat ID not matching the authorized `TELEGRAM_CHAT_ID` specified in `.env`.

## Architecture & Specifications
For all detailed feature specifications, pipeline steps, and implementation guidelines, refer directly to the markdown files in the `/docs/requirements` and `/docs/architecture` directories.

