"""GitHub integration configuration — DB-backed with env var fallback."""
from integrations.sdk import make_settings

_Settings = make_settings("github", {
    "GITHUB_TOKEN": "",
    "GITHUB_WEBHOOK_SECRET": "",
    "GITHUB_BOT_LOGIN": "",
})

settings = _Settings()

IDENTITY_FIELDS = [
    {
        "key": "github_username",
        "label": "GitHub Username",
        "description": "Your GitHub login (e.g. octocat)",
    },
]
