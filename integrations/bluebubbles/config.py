"""BlueBubbles integration config — DB-backed with env var fallback.

When running inside the agent server, values come from DB cache > env var > default.
When running standalone (bb_client process), falls back to env vars only.
"""
from integrations.sdk import make_settings

IDENTITY_FIELDS = [
    {
        "key": "phone_number",
        "label": "Phone Number",
        "description": "Your iMessage phone number (e.g. +15551234567)",
    },
]

_Base = make_settings("bluebubbles", {
    "BLUEBUBBLES_SERVER_URL": "",
    "BLUEBUBBLES_PASSWORD": "",
    "BB_DEFAULT_BOT": "default",
    "BB_WAKE_WORDS": "",
    "BB_WEBHOOK_TOKEN": "",
    "BB_SEND_METHOD": "",
})


class _Settings(_Base):
    @property
    def BB_SUGGEST_CHATS(self) -> bool:
        return self._get("BB_SUGGEST_CHATS", "true").lower() in ("true", "1", "yes")

    @property
    def BB_SUGGEST_COUNT(self) -> int:
        try:
            return max(1, min(50, int(self._get("BB_SUGGEST_COUNT", "10"))))
        except ValueError:
            return 10

    @property
    def BB_SUGGEST_PREVIEW(self) -> bool:
        return self._get("BB_SUGGEST_PREVIEW", "true").lower() in ("true", "1", "yes")

    @property
    def BB_ECHO_SUPPRESS_WINDOW(self) -> float:
        try:
            return max(0.0, float(self._get("BB_ECHO_SUPPRESS_WINDOW", "15")))
        except ValueError:
            return 15.0


settings = _Settings()
