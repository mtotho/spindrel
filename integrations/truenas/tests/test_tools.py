from __future__ import annotations

import json
from typing import Any

import pytest

from integrations.truenas.client import TrueNASApiError
from integrations.truenas.tools import truenas as tools


class FakeTrueNASClient:
    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[tuple[str, list[Any]]] = []

    async def __aenter__(self) -> "FakeTrueNASClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        self.calls.append((method, params or []))
        result = self.responses[method]
        if isinstance(result, Exception):
            raise result
        return result


def install_fake_client(monkeypatch: pytest.MonkeyPatch, client: FakeTrueNASClient) -> None:
    monkeypatch.setattr(tools, "truenas_client_from_settings", lambda: client)


def parse(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.asyncio
async def test_health_snapshot_returns_partial_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTrueNASClient({
        "system.info": {"hostname": "nas", "version": "25.04.2"},
        "pool.query": [{"name": "tank", "status": "ONLINE", "healthy": True}],
        "alert.list": [{"level": "WARNING", "formatted": "SMART warning"}],
        "core.get_jobs": [{"id": 7, "method": "pool.scrub.run", "state": "SUCCESS"}],
        "service.query": [{"service": "smb", "state": "RUNNING", "enable": True}],
        "disk.temperatures": {"sda": 41, "sdb": 58},
        "update.status": TrueNASApiError("update.status", {"message": "permission denied"}),
    })
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.truenas_health_snapshot())

    assert payload["status"] == "warning"
    assert payload["system"]["hostname"] == "nas"
    assert payload["errors"] == {"update_status": "update.status: permission denied"}
    assert payload["disk_temperatures"][1]["status"] == "warning"
    assert payload["tiles"][0]["label"] == "Pools"
    assert ("alert.list", []) in client.calls


@pytest.mark.asyncio
async def test_pool_status_filters_named_pool_and_scrub_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTrueNASClient({
        "pool.query": [{"name": "tank", "status": "ONLINE", "healthy": True}],
        "pool.scrub.query": [{"pool_name": "tank", "enabled": True}],
    })
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.truenas_pool_status_tool(pool_name="tank"))

    assert payload["status"] == "ok"
    assert payload["pool_name"] == "tank"
    assert client.calls == [
        ("pool.query", [[["name", "=", "tank"]], {}]),
        ("pool.scrub.query", [[["pool_name", "=", "tank"]], {}]),
    ]


@pytest.mark.asyncio
async def test_start_scrub_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTrueNASClient({"pool.scrub.run": None})
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.truenas_start_scrub(pool_name="tank", confirmed=False))

    assert payload["status"] == "confirmation_required"
    assert client.calls == []


@pytest.mark.asyncio
async def test_start_scrub_calls_pool_scrub_run_when_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTrueNASClient({"pool.scrub.run": None})
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.truenas_start_scrub(pool_name="tank", threshold=14, confirmed=True))

    assert payload == {"status": "ok", "pool_name": "tank", "result": None}
    assert client.calls == [("pool.scrub.run", ["tank", 14])]


@pytest.mark.asyncio
async def test_control_service_requires_valid_action_before_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTrueNASClient({"service.control": True})
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.truenas_control_service(service="smb", action="BOUNCE", confirmed=True))

    assert payload["status"] == "error"
    assert client.calls == []


@pytest.mark.asyncio
async def test_control_service_calls_service_control_when_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTrueNASClient({"service.control": True})
    install_fake_client(monkeypatch, client)

    payload = parse(await tools.truenas_control_service(service="smb", action="restart", confirmed=True))

    assert payload["status"] == "ok"
    assert client.calls == [
        ("service.control", ["RESTART", "smb", {"ha_propagate": True, "silent": False, "timeout": 120}])
    ]
