"""Frigate integration settings — read from environment variables.

Kept local to the integration (not in app/config.py) per DESIGN.md boundary.
"""

import os


class _Settings:
    @property
    def FRIGATE_URL(self) -> str:
        return os.environ.get("FRIGATE_URL", "")

    @property
    def FRIGATE_API_KEY(self) -> str:
        return os.environ.get("FRIGATE_API_KEY", "")

    @property
    def FRIGATE_MAX_CLIP_BYTES(self) -> int:
        return int(os.environ.get("FRIGATE_MAX_CLIP_BYTES", 52_428_800))

    # -- MQTT push event settings --

    @property
    def FRIGATE_MQTT_BROKER(self) -> str:
        return os.environ.get("FRIGATE_MQTT_BROKER", "")

    @property
    def FRIGATE_MQTT_PORT(self) -> int:
        return int(os.environ.get("FRIGATE_MQTT_PORT", 1883))

    @property
    def FRIGATE_MQTT_USERNAME(self) -> str:
        return os.environ.get("FRIGATE_MQTT_USERNAME", "")

    @property
    def FRIGATE_MQTT_PASSWORD(self) -> str:
        return os.environ.get("FRIGATE_MQTT_PASSWORD", "")

    @property
    def FRIGATE_MQTT_TOPIC_PREFIX(self) -> str:
        return os.environ.get("FRIGATE_MQTT_TOPIC_PREFIX", "frigate")

    @property
    def FRIGATE_MQTT_CAMERAS(self) -> list[str]:
        """Comma-separated camera filter. Empty = all cameras."""
        val = os.environ.get("FRIGATE_MQTT_CAMERAS", "")
        return [c.strip() for c in val.split(",") if c.strip()] if val else []

    @property
    def FRIGATE_MQTT_LABELS(self) -> list[str]:
        """Comma-separated label filter (e.g. person,car). Empty = all labels."""
        val = os.environ.get("FRIGATE_MQTT_LABELS", "")
        return [lb.strip() for lb in val.split(",") if lb.strip()] if val else []

    @property
    def FRIGATE_MQTT_MIN_SCORE(self) -> float:
        return float(os.environ.get("FRIGATE_MQTT_MIN_SCORE", 0.6))

    @property
    def FRIGATE_MQTT_COOLDOWN(self) -> int:
        """Seconds between alerts for same camera+label."""
        return int(os.environ.get("FRIGATE_MQTT_COOLDOWN", 300))

    # -- Agent server connection --

    @property
    def FRIGATE_BOT_ID(self) -> str:
        return os.environ.get("FRIGATE_BOT_ID", "")

    @property
    def FRIGATE_CLIENT_ID(self) -> str:
        return os.environ.get("FRIGATE_CLIENT_ID", "frigate:events")


settings = _Settings()
