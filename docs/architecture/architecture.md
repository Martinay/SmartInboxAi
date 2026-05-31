# Architecture

## Stack
- **Python 3.12+**, managed by **uv**
- Fully asynchronous (`asyncio`) – no blocking calls
- Deployed as a single Docker container

## Project Layout
```
src/main.py          # All application logic (single-file)
pyproject.toml       # uv project + dependencies
Dockerfile           # python:3.12-slim + system deps + uv
docker-compose.yml   # Container definition with volume mounts
.env                 # Runtime secrets (not committed)
```

## Volume Mounts
| Mount | Purpose |
|---|---|
| `/app/inbox` | Watched directory – new scans land here |
| `/app/archive` | Target archive with category subfolders |
| `/app/pending` | Temp storage while awaiting Telegram response |
| `/app/error` | Failed or rejected documents |

## Runtime Flow
```
asyncio.run(main)
  ├── Telegram Bot (polling in background)
  └── watchfiles.awatch(/app/inbox)
        └── per PDF → asyncio.create_task(process_file)
```

Bot polling and file watching run concurrently via `async with application:`. Each incoming PDF spawns an independent task so multiple files can be processed in parallel.

## Environment Variables
| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | API key for litellm → gpt-4o-mini |
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Authorized user ID (sole allowed user) |
| `IGNORE_FOLDERS` | No | Comma-separated folder names to skip during category scan |

## Blacklist
Folders matching any of these names are excluded from category scanning and never offered as targets:
- **System**: `@eaDir`, `.snapshot`, `#recycle`, `.DS_Store`, `@tmp`
- **User-defined**: values from `IGNORE_FOLDERS`

Filtering happens in-place during `os.walk()`, so blacklisted subtrees are never traversed.
