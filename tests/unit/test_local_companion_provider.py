from __future__ import annotations

from pathlib import Path

import pytest

from integrations.local_companion import machine_control as local_companion_machine_control
from integrations.local_companion import client as local_companion_client
from integrations.local_companion import router as local_companion_router


class _FakeDb:
    pass


@pytest.mark.asyncio
async def test_local_companion_enroll_returns_curl_bootstrap_launch_command(monkeypatch):
    saved_targets: list[dict] = []
    enabled_states: list[tuple[str, str]] = []

    async def _fake_save_targets(_db, targets):
        saved_targets[:] = list(targets)

    async def _fake_set_status(integration_id: str, status: str):
        enabled_states.append((integration_id, status))

    monkeypatch.setattr(local_companion_machine_control, "_save_targets", _fake_save_targets)
    monkeypatch.setattr(local_companion_machine_control, "get_registered_targets", lambda: [])
    monkeypatch.setattr(local_companion_machine_control, "get_status", lambda _integration_id: "disabled")
    monkeypatch.setattr(local_companion_machine_control, "set_status", _fake_set_status)
    monkeypatch.setattr(local_companion_machine_control.secrets, "token_urlsafe", lambda _n: "token-123")

    provider = local_companion_machine_control.LocalCompanionMachineControlProvider()

    payload = await provider.enroll(
        _FakeDb(),
        server_base_url="http://10.10.30.208:8000/",
        label="Desk",
    )

    command = payload["launch"]["example_command"]
    service_command = payload["launch"]["install_systemd_user_command"]

    assert "curl -fsSL http://10.10.30.208:8000/integrations/local_companion/client.py" in command
    assert "-o /tmp/spindrel-local-companion.py" in command
    assert "python /tmp/spindrel-local-companion.py" in command
    assert "--server-url http://10.10.30.208:8000" in command
    assert "--target-id " in command
    assert "--token token-123" in command
    assert "-m integrations.local_companion.client" not in command
    assert "--server " not in command
    assert "--install-systemd-user" in service_command
    assert "token-123" in service_command
    assert saved_targets
    assert enabled_states == [("local_companion", "enabled")]


@pytest.mark.asyncio
async def test_local_companion_target_setup_regenerates_launch_commands(monkeypatch):
    target = {
        "target_id": "target-123",
        "driver": "companion",
        "label": "Desk",
        "hostname": "",
        "platform": "",
        "capabilities": ["shell"],
        "token": "token-abc",
        "enrolled_at": "2026-04-25T12:00:00+00:00",
    }

    monkeypatch.setattr(local_companion_machine_control, "get_registered_targets", lambda: [target])

    provider = local_companion_machine_control.LocalCompanionMachineControlProvider()
    setup = await provider.get_target_setup(
        _FakeDb(),
        target_id="target-123",
        server_base_url="https://spindrel.example.com/base/",
    )

    assert setup["kind"] == "local_companion"
    assert setup["download_url"] == "https://spindrel.example.com/base/integrations/local_companion/client.py"
    assert "--target-id target-123" in setup["launch_command"]
    assert "--token token-abc" in setup["launch_command"]
    assert "--install-systemd-user" in setup["install_systemd_user_command"]
    assert setup["notes"]


def test_local_companion_router_serves_client_script_file():
    response = local_companion_router.download_client_script()

    assert Path(response.path) == Path(local_companion_router.__file__).with_name("client.py")
    assert response.filename == "spindrel-local-companion.py"


def test_local_companion_client_converts_http_server_url_to_ws_url():
    url = local_companion_client._build_ws_url(
        "http://10.10.30.208:8000/",
        target_id="target-123",
        token="token-123",
    )

    assert url == (
        "ws://10.10.30.208:8000/integrations/local_companion/ws?"
        "target_id=target-123&token=token-123"
    )


def test_local_companion_client_converts_https_server_url_to_wss_url():
    url = local_companion_client._build_ws_url(
        "https://spindrel.example.com/base/",
        target_id="target-123",
        token="token-123",
    )

    assert url == (
        "wss://spindrel.example.com/base/integrations/local_companion/ws?"
        "target_id=target-123&token=token-123"
    )


@pytest.mark.asyncio
async def test_local_companion_reconnects_after_failed_attempt(monkeypatch):
    attempts = {"count": 0}

    async def _fake_run_client(_args):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("server down")
        raise KeyboardInterrupt

    async def _fake_sleep(_delay):
        return None

    args = type("Args", (), {
        "once": False,
        "reconnect_initial_seconds": 0.25,
        "reconnect_max_seconds": 1.0,
    })()

    monkeypatch.setattr(local_companion_client, "_run_client", _fake_run_client)
    monkeypatch.setattr(local_companion_client.asyncio, "sleep", _fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        await local_companion_client._run_reconnecting_client(args)

    assert attempts["count"] == 2


def test_local_companion_service_exec_start_quotes_arguments():
    command = local_companion_client._systemd_exec_start([
        "/home/me/.venv/bin/python",
        "/home/me/client.py",
        "--server-url",
        "https://spindrel.example.com/base path",
    ])

    assert "'https://spindrel.example.com/base path'" in command
