"""ARR media stack configuration — loaded from environment variables."""

from pydantic_settings import BaseSettings


class ArrConfig(BaseSettings):
    SONARR_URL: str = ""
    SONARR_API_KEY: str = ""
    RADARR_URL: str = ""
    RADARR_API_KEY: str = ""
    QBIT_URL: str = ""
    QBIT_USERNAME: str = ""
    QBIT_PASSWORD: str = ""
    JELLYFIN_URL: str = ""
    JELLYFIN_API_KEY: str = ""
    JELLYSEERR_URL: str = ""
    JELLYSEERR_API_KEY: str = ""
    BAZARR_URL: str = ""
    BAZARR_API_KEY: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = ArrConfig()
