"""In-memory device/connection status store for integrations.

Integration processes report their connected devices via the admin API.
The store holds the latest report per integration with a TTL so stale
entries (process died) are flagged automatically.

Any integration can adopt this — just POST device status during your
process's refresh loop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

STALE_SECONDS = 90  # Mark report stale after this many seconds


@dataclass
class DeviceInfo:
    device_id: str
    label: str = ""
    protocol: str = ""
    uri: str = ""
    status: str = "disconnected"  # connected | disconnected | connecting | error
    detail: str | None = None
    last_activity: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class DeviceStatusReport:
    integration_id: str
    updated_at: float  # monotonic time for TTL
    updated_at_iso: str = ""
    devices: dict[str, DeviceInfo] = field(default_factory=dict)


class IntegrationDeviceStatusStore:
    """Thread-safe in-memory store for device status reports."""

    def __init__(self):
        self._reports: dict[str, DeviceStatusReport] = {}

    def report(self, integration_id: str, devices: list[dict]) -> None:
        """Accept a status report from an integration process."""
        from datetime import datetime, timezone

        device_map: dict[str, DeviceInfo] = {}
        for d in devices:
            did = d.get("device_id", "")
            if not did:
                continue
            device_map[did] = DeviceInfo(
                device_id=did,
                label=d.get("label", did),
                protocol=d.get("protocol", ""),
                uri=d.get("uri", ""),
                status=d.get("status", "disconnected"),
                detail=d.get("detail"),
                last_activity=d.get("last_activity"),
                metadata=d.get("metadata", {}),
            )

        self._reports[integration_id] = DeviceStatusReport(
            integration_id=integration_id,
            updated_at=time.monotonic(),
            updated_at_iso=datetime.now(timezone.utc).isoformat(),
            devices=device_map,
        )

    def get(self, integration_id: str) -> dict | None:
        """Get the current device status for an integration.

        Returns None if no report has ever been received.
        Returns {devices: [...], updated_at: str, stale: bool}.
        """
        report = self._reports.get(integration_id)
        if not report:
            return None

        stale = (time.monotonic() - report.updated_at) > STALE_SECONDS
        devices = [
            {
                "device_id": d.device_id,
                "label": d.label,
                "protocol": d.protocol,
                "uri": d.uri,
                "status": d.status,
                "detail": d.detail,
                "last_activity": d.last_activity,
                "metadata": d.metadata,
            }
            for d in report.devices.values()
        ]
        return {
            "devices": devices,
            "updated_at": report.updated_at_iso,
            "stale": stale,
        }

    def clear(self, integration_id: str) -> None:
        """Remove status for an integration (e.g., on process stop)."""
        self._reports.pop(integration_id, None)


# Singleton
device_status_store = IntegrationDeviceStatusStore()
