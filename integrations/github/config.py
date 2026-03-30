"""GitHub integration configuration — DB-backed with env var fallback."""
from __future__ import annotations

import os


def _get(key: str, default: str = "") -> str:
    """Get a config value: DB cache > env var > default."""
    try:
        from app.services.integration_settings import get_value
        return get_value("github", key, default)
    except ImportError:
        return os.environ.get(key, default)


class _Settings:
    @property
    def GITHUB_TOKEN(self) -> str:
        return _get("GITHUB_TOKEN")

    @property
    def GITHUB_WEBHOOK_SECRET(self) -> str:
        return _get("GITHUB_WEBHOOK_SECRET")

    @property
    def GITHUB_BOT_LOGIN(self) -> str:
        """GitHub username of the bot/PAT owner (to ignore its own comments)."""
        return _get("GITHUB_BOT_LOGIN")


settings = _Settings()

IDENTITY_FIELDS = [
    {
        "key": "github_username",
        "label": "GitHub Username",
        "description": "Your GitHub login (e.g. octocat)",
    },
]
