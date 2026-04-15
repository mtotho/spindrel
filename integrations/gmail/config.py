"""Gmail integration configuration — DB-backed with env var fallback."""
from integrations.sdk import make_settings

_Base = make_settings("gmail", {
    "GMAIL_EMAIL": "",
    "GMAIL_APP_PASSWORD": "",
    "GMAIL_IMAP_HOST": "imap.gmail.com",
    "GMAIL_INITIAL_FETCH": "new",
    "AGENT_BASE_URL": "http://localhost:8000",
    "AGENT_API_KEY": "",
    "INGESTION_CLASSIFIER_MODEL": "gpt-4o-mini",
})


class _Settings(_Base):
    @property
    def GMAIL_IMAP_PORT(self) -> int:
        return int(self._get("GMAIL_IMAP_PORT", "993"))

    @property
    def GMAIL_POLL_INTERVAL(self) -> int:
        return int(self._get("GMAIL_POLL_INTERVAL", "60"))

    @property
    def GMAIL_MAX_PER_POLL(self) -> int:
        return int(self._get("GMAIL_MAX_PER_POLL", "25"))

    @property
    def GMAIL_FOLDERS(self) -> list[str]:
        raw = self._get("GMAIL_FOLDERS", "INBOX")
        return [f.strip() for f in raw.split(",") if f.strip()]


settings = _Settings()
