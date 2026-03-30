"""GitHub integration configuration."""
from __future__ import annotations

import os


class _Settings:
    @property
    def GITHUB_TOKEN(self) -> str:
        return os.environ.get("GITHUB_TOKEN", "")

    @property
    def GITHUB_WEBHOOK_SECRET(self) -> str:
        return os.environ.get("GITHUB_WEBHOOK_SECRET", "")

    @property
    def GITHUB_BOT_LOGIN(self) -> str:
        """GitHub username of the bot/PAT owner (to ignore its own comments)."""
        return os.environ.get("GITHUB_BOT_LOGIN", "")


settings = _Settings()

IDENTITY_FIELDS = [
    {
        "key": "github_username",
        "label": "GitHub Username",
        "description": "Your GitHub login (e.g. octocat)",
    },
]
