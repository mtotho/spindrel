import os
import pytest

# Set env vars before any arr imports so the config._get() fallback reads them
@pytest.fixture(autouse=True)
def arr_env(monkeypatch):
    """Inject ARR env vars for all tests."""
    monkeypatch.setenv("SONARR_URL", "http://sonarr:8989")
    monkeypatch.setenv("SONARR_API_KEY", "test-sonarr-key")
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "test-radarr-key")
    monkeypatch.setenv("QBIT_URL", "http://qbit:8080")
    monkeypatch.setenv("QBIT_USERNAME", "admin")
    monkeypatch.setenv("QBIT_PASSWORD", "password")
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "test-jellyfin-key")
    monkeypatch.setenv("JELLYSEERR_URL", "http://jellyseerr:5055")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "test-jellyseerr-key")
    monkeypatch.setenv("PROWLARR_URL", "http://prowlarr:9696")
    monkeypatch.setenv("PROWLARR_API_KEY", "test-prowlarr-key")
    monkeypatch.setenv("BAZARR_URL", "http://bazarr:6767")
    monkeypatch.setenv("BAZARR_API_KEY", "test-bazarr-key")
    monkeypatch.setenv("FLARESOLVERR_URL", "http://flaresolverr:8191")
