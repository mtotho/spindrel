"""ARR media stack integration setup manifest."""

SETUP = {
    "icon": "Tv",
    "env_vars": [
        # Sonarr
        {"key": "SONARR_URL", "required": False, "description": "Sonarr base URL (e.g. http://192.168.1.x:8989)"},
        {"key": "SONARR_API_KEY", "required": False, "description": "Sonarr API key (Settings → General)", "secret": True},
        # Radarr
        {"key": "RADARR_URL", "required": False, "description": "Radarr base URL (e.g. http://192.168.1.x:7878)"},
        {"key": "RADARR_API_KEY", "required": False, "description": "Radarr API key (Settings → General)", "secret": True},
        # qBittorrent
        {"key": "QBIT_URL", "required": False, "description": "qBittorrent Web UI URL (e.g. http://192.168.1.x:8080)"},
        {"key": "QBIT_USERNAME", "required": False, "description": "qBittorrent Web UI username"},
        {"key": "QBIT_PASSWORD", "required": False, "description": "qBittorrent Web UI password", "secret": True},
        # Jellyfin
        {"key": "JELLYFIN_URL", "required": False, "description": "Jellyfin base URL (e.g. http://192.168.1.x:8096)"},
        {"key": "JELLYFIN_API_KEY", "required": False, "description": "Jellyfin API key (Dashboard → API Keys)", "secret": True},
        # Jellyseerr
        {"key": "JELLYSEERR_URL", "required": False, "description": "Jellyseerr base URL (e.g. http://192.168.1.x:5055)"},
        {"key": "JELLYSEERR_API_KEY", "required": False, "description": "Jellyseerr API key (Settings → General)", "secret": True},
        # Bazarr
        {"key": "BAZARR_URL", "required": False, "description": "Bazarr base URL (e.g. http://192.168.1.x:6767)"},
        {"key": "BAZARR_API_KEY", "required": False, "description": "Bazarr API key (Settings → General)", "secret": True},
    ],
    "activation": {
        "carapaces": ["arr"],
        "includes": ["mission_control"],
        "requires_workspace": False,
        "description": "Media library management with Sonarr, Radarr, qBittorrent, Jellyfin, Jellyseerr, and Bazarr",
        "compatible_templates": ["media-management"],
    },
}
