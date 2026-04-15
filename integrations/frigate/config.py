"""Frigate integration settings — DB-backed with env var fallback.

When running inside the agent server, values come from DB cache > env var > default.
When running standalone (MQTT listener), falls back to env vars only.
"""
from integrations.sdk import make_settings

_Base = make_settings("frigate", {
    "FRIGATE_URL": "",
    "FRIGATE_API_KEY": "",
    "FRIGATE_MQTT_BROKER": "",
    "FRIGATE_MQTT_USERNAME": "",
    "FRIGATE_MQTT_PASSWORD": "",
    "FRIGATE_MQTT_TOPIC_PREFIX": "frigate",
    "FRIGATE_WEBHOOK_TOKEN": "",
})


class _Settings(_Base):
    @property
    def FRIGATE_MAX_CLIP_BYTES(self) -> int:
        return int(self._get("FRIGATE_MAX_CLIP_BYTES", "52428800"))

    @property
    def FRIGATE_MQTT_PORT(self) -> int:
        return int(self._get("FRIGATE_MQTT_PORT", "1883"))

    @property
    def FRIGATE_MQTT_CAMERAS(self) -> list[str]:
        """Comma-separated camera filter. Empty = all cameras."""
        val = self._get("FRIGATE_MQTT_CAMERAS")
        return [c.strip() for c in val.split(",") if c.strip()] if val else []

    @property
    def FRIGATE_MQTT_LABELS(self) -> list[str]:
        """Comma-separated label filter (e.g. person,car). Empty = all labels."""
        val = self._get("FRIGATE_MQTT_LABELS")
        return [lb.strip() for lb in val.split(",") if lb.strip()] if val else []

    @property
    def FRIGATE_MQTT_MIN_SCORE(self) -> float:
        return float(self._get("FRIGATE_MQTT_MIN_SCORE", "0.6"))

    @property
    def FRIGATE_MQTT_COOLDOWN(self) -> int:
        """Seconds between alerts for same camera+label."""
        return int(self._get("FRIGATE_MQTT_COOLDOWN", "300"))


settings = _Settings()
