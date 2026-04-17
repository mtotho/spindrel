"""OpenWeather integration settings — DB-backed with env var fallback."""
from integrations.sdk import make_settings

_Base = make_settings("openweather", {
    "OPENWEATHERMAP_API_KEY": "",
})


class _Settings(_Base):
    @property
    def POLL_INTERVAL_MINUTES(self) -> int:
        """How often pinned weather widgets refresh. Default 60 (1 hour)."""
        return max(1, int(self._get("POLL_INTERVAL_MINUTES", "60")))


settings = _Settings()
