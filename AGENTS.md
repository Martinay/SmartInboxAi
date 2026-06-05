Project: SmartInboxAI
Stack: Python 3.12+, uv, asyncio, Docker.
Project Layout: Source code lives in `src/`. Entry point is `src/main.py`.

## Core Security Rules
- **Webhook Access Control**: The FastAPI webhook endpoint (`POST /action`) MUST validate the `SECRET_TOKEN` query parameter against the value specified in `.env`. Requests with an invalid or missing token MUST be rejected with `403 Forbidden`.

## Architecture & Specifications
For all detailed feature specifications, pipeline steps, and implementation guidelines, refer directly to the markdown files in the `/docs/requirements` and `/docs/architecture` directories.
