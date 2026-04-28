"""Browser automation integration settings."""
from __future__ import annotations

from integrations import sdk

_Base = sdk.make_settings("browser_automation", {})


class _Settings(_Base):
    @property
    def HEADLESS_BROWSER_CONTAINERS(self) -> bool:
        value = self._get("HEADLESS_BROWSER_CONTAINERS", "true")
        return value.lower() in ("true", "1", "yes")

    @property
    def HEADLESS_BROWSER_WS_URL(self) -> str:
        return self._get("HEADLESS_BROWSER_WS_URL", "").strip()

    @property
    def HEADLESS_BROWSER_IDLE_TTL_SECONDS(self) -> int:
        raw = self._get("HEADLESS_BROWSER_IDLE_TTL_SECONDS", "900")
        try:
            return max(60, int(raw))
        except ValueError:
            return 900


settings = _Settings()

