"""Web Search integration configuration — DB-backed with env var fallback."""
from __future__ import annotations

import os


def _get(key: str, default: str = "") -> str:
    """Get a config value: DB cache > env var > default."""
    try:
        from app.services.integration_settings import get_value
        return get_value("web_search", key, default)
    except ImportError:
        return os.environ.get(key, default)


def _in_docker() -> bool:
    """Detect if we're running inside a Docker container."""
    return os.path.exists("/.dockerenv")


class _Settings:
    @property
    def WEB_SEARCH_MODE(self) -> str:
        return _get("WEB_SEARCH_MODE", "searxng")

    @property
    def WEB_SEARCH_CONTAINERS(self) -> bool:
        val = _get("WEB_SEARCH_CONTAINERS", "false")
        return val.lower() in ("true", "1", "yes")

    @property
    def SEARXNG_URL(self) -> str:
        val = _get("SEARXNG_URL", "")
        if val:
            return val
        # Auto-detect: container names in Docker, localhost in local dev
        if _in_docker() or self.WEB_SEARCH_CONTAINERS:
            return "http://spindrel-searxng:8080"
        return "http://localhost:8080"

    @property
    def PLAYWRIGHT_WS_URL(self) -> str:
        val = _get("PLAYWRIGHT_WS_URL", "")
        if val:
            return val
        # Auto-detect: container names in Docker, localhost in local dev
        if _in_docker() or self.WEB_SEARCH_CONTAINERS:
            return "ws://spindrel-playwright:3000"
        return "ws://localhost:3000"


settings = _Settings()
