"""Claude Code integration configuration — DB-backed with env var fallback."""
from __future__ import annotations

from integrations.sdk import make_settings

_VALID_PERMISSION_MODES = {"default", "acceptEdits", "plan", "bypassPermissions"}

_Base = make_settings("claude_code", {})


class _Settings(_Base):
    @property
    def MAX_TURNS(self) -> int:
        return int(self._get("CLAUDE_CODE_MAX_TURNS", "30"))

    @property
    def TIMEOUT(self) -> int:
        return int(self._get("CLAUDE_CODE_TIMEOUT", "1800"))

    @property
    def MAX_RESUME_RETRIES(self) -> int:
        return int(self._get("CLAUDE_CODE_MAX_RESUME_RETRIES", "1"))

    @property
    def PERMISSION_MODE(self) -> str:
        v = self._get("CLAUDE_CODE_PERMISSION_MODE", "bypassPermissions")
        if v not in _VALID_PERMISSION_MODES:
            raise ValueError(
                f"Invalid CLAUDE_CODE_PERMISSION_MODE={v!r}; "
                f"must be one of {_VALID_PERMISSION_MODES}"
            )
        return v

    @property
    def ALLOWED_TOOLS(self) -> list[str]:
        raw = self._get("CLAUDE_CODE_ALLOWED_TOOLS", "Read,Write,Edit,Bash,Glob,Grep")
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def MODEL(self) -> str | None:
        v = self._get("CLAUDE_CODE_MODEL", "")
        return v or None


settings = _Settings()
