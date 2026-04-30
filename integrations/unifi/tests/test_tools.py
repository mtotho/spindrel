from __future__ import annotations

import json
from typing import Any

import pytest

from integrations.unifi.client import UniFiConnectionError
from integrations.unifi.tools import unifi as tools


class FakeUniFiClient:
    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.site_id = ""

    async def __aenter__(self) -> "FakeUniFiClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def connection_summary(self) -> dict[str, Any]:
        return {
            "base_url": "https://unifi.local",
            "api_base_path": "/proxy/network/integration/v1",
            "site_id": self.site_id,
            "attempted_endpoints": [{"status": "connected"}],
        }

    async def sites(self) -> list[Any]:
        return self.responses["/sites"]

    async def selected_site_id(self) -> str:
        if self.site_id:
            return self.site_id
        self.site_id = self.responses.get("site_id", "default")
        return self.site_id

    async def list_paginated(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        limit: int = 200,
        max_items: int = 1000,
    ) -> list[Any]:
        self.calls.append((path, params))
        result = self.responses[path]
        if isinstance(result, Exception):
            raise result
        return result

    async def get_first(self, paths: list[str], params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("|".join(paths), params))
        for path in paths:
            if path in self.responses:
                result = self.responses[path]
                if isinstance(result, Exception):
                    raise result
                return result
        return []


class FailingUniFiClient:
    async def __aenter__(self) -> "FailingUniFiClient":
        raise UniFiConnectionError(
            "Failed to connect to UniFi Network API at https://unifi.local/proxy/network/integration/v1",
            attempts=[{
                "base_url": "https://unifi.local",
                "api_base_path": "/proxy/network/integration/v1",
                "status": "failed",
                "error": "HTTP 404",
            }],
        )

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def install_fake_client(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(tools, "unifi_client_from_settings", lambda: client)


def parse(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def fake_responses() -> dict[str, Any]:
    return {
        "/sites": [{"id": "default", "name": "Default"}],
        "site_id": "default",
        "/sites/default/devices": [
            {"name": "UDM Pro", "type": "gateway", "state": "online"},
            {"name": "Office AP", "type": "ap", "state": "offline"},
        ],
        "/sites/default/clients": [
            {"hostname": "printer", "ipAddress": "169.254.1.4", "networkName": "IoT", "connected": True},
            {"hostname": "laptop", "ipAddress": "192.168.1.23", "networkName": "Default", "connected": True},
        ],
        "/sites/default/networks": [
            {"id": "default", "name": "Default", "vlanId": None, "subnet": "192.168.1.0/24"},
            {"id": "iot", "name": "IoT", "vlanId": 30, "subnet": "192.168.30.0/24"},
        ],
        "/sites/default/wifi": [
            {"name": "Home", "vlanId": None, "enabled": True},
            {"name": "IoT WiFi", "vlanId": 30, "enabled": True},
        ],
        "/sites/default/firewall/zones": [{"name": "LAN"}, {"name": "IoT"}],
    }


@pytest.mark.asyncio
async def test_network_snapshot_returns_partial_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = fake_responses()
    responses["/sites/default/wifi"] = RuntimeError("wifi unavailable")
    client = FakeUniFiClient(responses)
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.unifi_network_snapshot())

    assert payload["status"] == "warning"
    assert payload["site_id"] == "default"
    assert payload["errors"] == {"wifi": "wifi unavailable"}
    assert payload["tiles"][0]["label"] == "Devices"
    assert payload["device_tiles"][1]["status"] == "danger"


@pytest.mark.asyncio
async def test_widget_backed_tools_return_visible_connection_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(monkeypatch, FailingUniFiClient())

    payload = parse(await tools.unifi_network_snapshot())

    assert payload["status"] == "unavailable"
    assert "error" not in payload
    assert payload["message"].startswith("Failed to connect to UniFi Network API")
    assert payload["diagnostics"]["attempted_endpoints"][0]["api_base_path"] == "/proxy/network/integration/v1"
    assert payload["tiles"][0]["label"] == "Connection"


@pytest.mark.asyncio
async def test_test_connection_exposes_connection_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeUniFiClient(fake_responses())
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.unifi_test_connection())

    assert payload["status"] == "ok"
    assert payload["site_id"] == "default"
    assert payload["connection"]["base_url"] == "https://unifi.local"


@pytest.mark.asyncio
async def test_vlan_advisor_separates_dhcp_and_manual_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeUniFiClient(fake_responses())
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.unifi_vlan_advisor(symptom="IoT VLAN has no internet", target_client="printer"))

    assert payload["target_client"] == "printer"
    assert any("DHCP" in item for item in payload["likely_causes"])
    assert any("printer" in item for item in payload["evidence_from_tools"])
    assert any("VLAN Viewer" in item for item in payload["safe_next_steps"])
    assert payload["do_not_change_yet"]

