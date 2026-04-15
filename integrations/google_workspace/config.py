"""Google Workspace integration configuration — DB-backed with env var fallback."""
from __future__ import annotations

from integrations.sdk import make_settings

_Base = make_settings("google_workspace", {
    "GWS_CLIENT_ID": "",
    "GWS_CLIENT_SECRET": "",
})


class _Settings(_Base):
    @property
    def GWS_TIMEOUT(self) -> int:
        val = self._get("GWS_TIMEOUT", "60")
        try:
            return int(val)
        except ValueError:
            return 60


settings = _Settings()

# Google OAuth scope mapping: service name → Google scope URIs
SCOPE_MAP: dict[str, str] = {
    "drive": "https://www.googleapis.com/auth/drive",
    "gmail": "https://www.googleapis.com/auth/gmail.modify",
    "calendar": "https://www.googleapis.com/auth/calendar",
    "sheets": "https://www.googleapis.com/auth/spreadsheets",
    "docs": "https://www.googleapis.com/auth/documents",
    "slides": "https://www.googleapis.com/auth/presentations",
    "tasks": "https://www.googleapis.com/auth/tasks",
    "people": "https://www.googleapis.com/auth/contacts",
    "chat": "https://www.googleapis.com/auth/chat.messages",
    "forms": "https://www.googleapis.com/auth/forms",
    "keep": "https://www.googleapis.com/auth/keep",
    "meet": "https://www.googleapis.com/auth/meetings.space.created",
}

ALL_SERVICES = list(SCOPE_MAP.keys())

# GWS CLI command aliases → canonical service names
SERVICE_ALIASES: dict[str, str] = {
    "wf": "workflow",
    "reports": "admin-reports",
}
