"""ARR media stack settings — DB-backed with env var fallback."""
from integrations.sdk import make_settings

_Settings = make_settings("arr", {
    "SONARR_URL": "",
    "SONARR_API_KEY": "",
    "RADARR_URL": "",
    "RADARR_API_KEY": "",
    "QBIT_URL": "",
    "QBIT_USERNAME": "",
    "QBIT_PASSWORD": "",
    "JELLYFIN_URL": "",
    "JELLYFIN_API_KEY": "",
    "JELLYSEERR_URL": "",
    "JELLYSEERR_API_KEY": "",
    "PROWLARR_URL": "",
    "PROWLARR_API_KEY": "",
    "BAZARR_URL": "",
    "BAZARR_API_KEY": "",
    "FLARESOLVERR_URL": "",
})

settings = _Settings()
