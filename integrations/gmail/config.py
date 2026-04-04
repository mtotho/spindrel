"""Gmail integration configuration — DB-backed with env var fallback."""
from __future__ import annotations

import os


def _get(key: str, default: str = "") -> str:
    """Get a config value: DB cache > env var > default."""
    try:
        from app.services.integration_settings import get_value
        return get_value("gmail", key, default)
    except ImportError:
        return os.environ.get(key, default)


class _Settings:
    @property
    def GMAIL_EMAIL(self) -> str:
        return _get("GMAIL_EMAIL")

    @property
    def GMAIL_APP_PASSWORD(self) -> str:
        return _get("GMAIL_APP_PASSWORD")

    @property
    def GMAIL_IMAP_HOST(self) -> str:
        return _get("GMAIL_IMAP_HOST", "imap.gmail.com")

    @property
    def GMAIL_IMAP_PORT(self) -> int:
        return int(_get("GMAIL_IMAP_PORT", "993"))

    @property
    def GMAIL_POLL_INTERVAL(self) -> int:
        return int(_get("GMAIL_POLL_INTERVAL", "60"))

    @property
    def GMAIL_MAX_PER_POLL(self) -> int:
        return int(_get("GMAIL_MAX_PER_POLL", "25"))

    @property
    def GMAIL_FOLDERS(self) -> list[str]:
        raw = _get("GMAIL_FOLDERS", "INBOX")
        return [f.strip() for f in raw.split(",") if f.strip()]

    @property
    def AGENT_BASE_URL(self) -> str:
        return _get("AGENT_BASE_URL", "http://localhost:8000")

    @property
    def AGENT_API_KEY(self) -> str:
        return _get("AGENT_API_KEY")

    @property
    def INGESTION_CLASSIFIER_MODEL(self) -> str:
        return _get("INGESTION_CLASSIFIER_MODEL", "gpt-4o-mini")


settings = _Settings()
