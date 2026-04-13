"""ESPHome device registry — maps device names to channel config for routing."""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ESPHomeDeviceConfig:
    """Config for one ESPHome device, populated from binding config refresh."""

    bot_id: str
    client_id: str
    channel_id: str
    channel_name: str
    voice: str | None = None
    wake_words: str | None = None
    esphome_device_name: str | None = None


class ESPHomeDeviceRegistry:
    """Thread-safe registry of ESPHome device configs.

    Updated periodically from the orchestrator's config refresh cycle.
    Keyed by the ESPHome device name (from HelloRequest.client_info)
    which maps to the ``esphome_device_name`` binding config field.
    """

    def __init__(self) -> None:
        self._devices: dict[str, ESPHomeDeviceConfig] = {}

    def update(self, devices: dict[str, dict]) -> None:
        """Replace the registry contents from a config refresh.

        ``devices`` is a dict of device_id -> config dicts from the
        ``/integrations/wyoming/config`` endpoint, pre-filtered to
        only include ``protocol=esphome`` entries.
        """
        new: dict[str, ESPHomeDeviceConfig] = {}
        for device_id, cfg in devices.items():
            # The key for lookup is the esphome_device_name from binding config.
            # Fall back to device_id if not explicitly set.
            device_name = cfg.get("esphome_device_name") or device_id
            new[device_name] = ESPHomeDeviceConfig(
                bot_id=cfg.get("bot_id", ""),
                client_id=cfg.get("client_id", f"wyoming:{device_id}"),
                channel_id=cfg.get("channel_id", ""),
                channel_name=cfg.get("channel_name", ""),
                voice=cfg.get("voice"),
                wake_words=cfg.get("wake_words"),
                esphome_device_name=device_name,
            )
        if new != self._devices:
            added = set(new) - set(self._devices)
            removed = set(self._devices) - set(new)
            if added:
                logger.info("ESPHome devices added: %s", added)
            if removed:
                logger.info("ESPHome devices removed: %s", removed)
            self._devices = new

    def get(self, device_name: str) -> ESPHomeDeviceConfig | None:
        """Look up config by ESPHome device name (from HelloRequest)."""
        return self._devices.get(device_name)

    def get_all(self) -> dict[str, ESPHomeDeviceConfig]:
        """Return all registered devices."""
        return dict(self._devices)
