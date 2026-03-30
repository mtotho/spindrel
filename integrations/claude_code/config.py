"""Claude Code integration configuration — env var based."""
from __future__ import annotations

import os


def _get(key: str, default: str = "") -> str:
    try:
        from app.services.integration_settings import get_value
        return get_value("claude_code", key, default)
    except ImportError:
        return os.environ.get(key, default)


class _Settings:
    @property
    def MAX_TURNS(self) -> int:
        return int(_get("CLAUDE_CODE_MAX_TURNS", "30"))

    @property
    def TIMEOUT(self) -> int:
        return int(_get("CLAUDE_CODE_TIMEOUT", "1800"))

    @property
    def MAX_RESUME_RETRIES(self) -> int:
        return int(_get("CLAUDE_CODE_MAX_RESUME_RETRIES", "1"))

    @property
    def PERMISSION_MODE(self) -> str:
        return _get("CLAUDE_CODE_PERMISSION_MODE", "bypassPermissions")

    @property
    def ALLOWED_TOOLS(self) -> list[str]:
        raw = _get("CLAUDE_CODE_ALLOWED_TOOLS", "Read,Write,Edit,Bash,Glob,Grep")
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def MODEL(self) -> str | None:
        v = _get("CLAUDE_CODE_MODEL", "")
        return v or None


settings = _Settings()
