"""Configuration for SmartInboxAI.

Settings are loaded from environment variables via dotenv and exposed
as a frozen dataclass.  No module-level side effects — call
``load_settings()`` explicitly.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Folders that are always excluded from category scanning.
_SYSTEM_BLACKLIST: frozenset[str] = frozenset(
    {"@eaDir", ".snapshot", "#recycle", ".DS_Store", "@tmp"}
)


@dataclass(frozen=True)
class Settings:
    """Immutable application configuration."""

    # Secrets / tokens
    openai_api_key: str = ""
    ntfy_url: str = ""
    ntfy_token: str = ""
    secret_token: str = ""
    callback_base_url: str = ""

    # Webhook server
    webhook_port: int = 8000

    # Directories
    inbox_dir: Path = Path("/app/inbox")
    archive_dir: Path = Path("/app/archive")
    pending_dir: Path = Path("/app/pending")
    error_dir: Path = Path("/app/error")

    # Blacklists
    system_blacklist: frozenset[str] = field(default_factory=lambda: _SYSTEM_BLACKLIST)
    user_blacklist: frozenset[str] = field(default_factory=frozenset)

    # LLM
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    max_text_pages: int = 3
    max_text_chars: int = 4000

    # File-stability polling
    file_stable_seconds: int = 3
    file_stable_checks: int = 3

    @property
    def blacklist(self) -> frozenset[str]:
        """Combined system + user blacklist."""
        return self.system_blacklist | self.user_blacklist


def _read_secret(env_var: str) -> str:
    """Read a secret from an env var or its _FILE counterpart."""
    value = os.getenv(env_var, "")
    if value:
        return value
    file_path = os.getenv(f"{env_var}_FILE")
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return ""

def load_settings() -> Settings:
    """Read ``.env`` and construct a ``Settings`` instance."""
    load_dotenv()

    ignore_folders_env = os.getenv("IGNORE_FOLDERS", "")
    user_blacklist = frozenset(
        f.strip() for f in ignore_folders_env.split(",") if f.strip()
    )

    return Settings(
        openai_api_key=_read_secret("OPENAI_API_KEY"),
        ntfy_url=os.getenv("NTFY_URL", ""),
        ntfy_token=_read_secret("NTFY_TOKEN"),
        secret_token=_read_secret("SECRET_TOKEN"),
        callback_base_url=os.getenv("CALLBACK_BASE_URL", ""),
        webhook_port=int(os.getenv("WEBHOOK_PORT", "8000")),
        user_blacklist=user_blacklist,
    )
