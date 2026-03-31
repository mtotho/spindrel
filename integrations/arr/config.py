"""ARR media stack settings — DB-backed with env var fallback.

When running inside the agent server, values come from DB cache > env var > default.
When running standalone, falls back to env vars only.
"""

import os


def _get(key: str, default: str = "") -> str:
    """Get a config value: DB cache > env var > default."""
    try:
        from app.services.integration_settings import get_value
        return get_value("arr", key, default)
    except ImportError:
        return os.environ.get(key, default)


class _Settings:
    # -- Sonarr --
    @property
    def SONARR_URL(self) -> str:
        return _get("SONARR_URL")

    @property
    def SONARR_API_KEY(self) -> str:
        return _get("SONARR_API_KEY")

    # -- Radarr --
    @property
    def RADARR_URL(self) -> str:
        return _get("RADARR_URL")

    @property
    def RADARR_API_KEY(self) -> str:
        return _get("RADARR_API_KEY")

    # -- qBittorrent --
    @property
    def QBIT_URL(self) -> str:
        return _get("QBIT_URL")

    @property
    def QBIT_USERNAME(self) -> str:
        return _get("QBIT_USERNAME")

    @property
    def QBIT_PASSWORD(self) -> str:
        return _get("QBIT_PASSWORD")

    # -- Jellyfin --
    @property
    def JELLYFIN_URL(self) -> str:
        return _get("JELLYFIN_URL")

    @property
    def JELLYFIN_API_KEY(self) -> str:
        return _get("JELLYFIN_API_KEY")

    # -- Jellyseerr --
    @property
    def JELLYSEERR_URL(self) -> str:
        return _get("JELLYSEERR_URL")

    @property
    def JELLYSEERR_API_KEY(self) -> str:
        return _get("JELLYSEERR_API_KEY")

    # -- Bazarr --
    @property
    def BAZARR_URL(self) -> str:
        return _get("BAZARR_URL")

    @property
    def BAZARR_API_KEY(self) -> str:
        return _get("BAZARR_API_KEY")


settings = _Settings()
