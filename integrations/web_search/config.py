"""Web Search integration configuration — DB-backed with env var fallback."""
from __future__ import annotations

import os

from integrations import sdk

_Base = sdk.make_settings("web_search", {
    "WEB_SEARCH_MODE": "searxng",
})


def _in_docker() -> bool:
    """Detect if we're running inside a Docker container."""
    return os.path.exists("/.dockerenv")


def _instance_id() -> str:
    # Prefer the app-level setting when available (populated at startup with a
    # hostname-slug default). Fall back to the raw env var and then "default".
    try:
        if sdk.app_settings.SPINDREL_INSTANCE_ID:
            return sdk.app_settings.SPINDREL_INSTANCE_ID
    except Exception:
        pass
    return os.environ.get("SPINDREL_INSTANCE_ID", "").strip() or "default"


class _Settings(_Base):
    @property
    def WEB_SEARCH_CONTAINERS(self) -> bool:
        val = self._get("WEB_SEARCH_CONTAINERS", "true")
        return val.lower() in ("true", "1", "yes")

    @property
    def SEARXNG_URL(self) -> str:
        val = self._get("SEARXNG_URL", "")
        if val:
            return val
        if _in_docker():
            return f"http://searxng-{_instance_id()}:8080"
        return "http://localhost:8080"

    @property
    def PLAYWRIGHT_WS_URL(self) -> str:
        val = self._get("PLAYWRIGHT_WS_URL", "")
        if val:
            return val
        if _in_docker():
            return f"ws://playwright-{_instance_id()}:3000"
        return "ws://localhost:3000"


settings = _Settings()
