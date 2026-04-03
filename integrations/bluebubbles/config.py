"""BlueBubbles integration config — DB-backed with env var fallback.

When running inside the agent server, values come from DB cache > env var > default.
When running standalone (bb_client process), falls back to env vars only.
"""

import os

IDENTITY_FIELDS = [
    {
        "key": "phone_number",
        "label": "Phone Number",
        "description": "Your iMessage phone number (e.g. +15551234567)",
    },
]


def _get(key: str, default: str = "") -> str:
    """Get a config value: DB cache > env var > default."""
    try:
        from app.services.integration_settings import get_value
        return get_value("bluebubbles", key, default)
    except ImportError:
        return os.environ.get(key, default)


class _Settings:
    @property
    def BLUEBUBBLES_SERVER_URL(self) -> str:
        return _get("BLUEBUBBLES_SERVER_URL")

    @property
    def BLUEBUBBLES_PASSWORD(self) -> str:
        return _get("BLUEBUBBLES_PASSWORD")

    @property
    def BB_DEFAULT_BOT(self) -> str:
        return _get("BB_DEFAULT_BOT", "default")

    @property
    def BB_WAKE_WORDS(self) -> str:
        return _get("BB_WAKE_WORDS")

    @property
    def BB_WEBHOOK_TOKEN(self) -> str:
        return _get("BB_WEBHOOK_TOKEN")

    @property
    def BB_SEND_METHOD(self) -> str:
        return _get("BB_SEND_METHOD", "")

    @property
    def BB_SUGGEST_CHATS(self) -> bool:
        return _get("BB_SUGGEST_CHATS", "true").lower() in ("true", "1", "yes")

    @property
    def BB_SUGGEST_COUNT(self) -> int:
        try:
            return max(1, min(50, int(_get("BB_SUGGEST_COUNT", "10"))))
        except ValueError:
            return 10

    @property
    def BB_SUGGEST_PREVIEW(self) -> bool:
        return _get("BB_SUGGEST_PREVIEW", "true").lower() in ("true", "1", "yes")


settings = _Settings()
