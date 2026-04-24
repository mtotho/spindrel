from __future__ import annotations

import pytest

from integrations.ssh import machine_control as ssh_machine_control


class _FakeDb:
    pass


@pytest.mark.asyncio
async def test_ssh_enroll_persists_target_metadata(monkeypatch):
    saved_targets: list[dict] = []
    enabled_states: list[tuple[str, str]] = []

    async def _fake_save_targets(_db, targets):
        saved_targets[:] = list(targets)

    async def _fake_set_status(integration_id: str, status: str):
        enabled_states.append((integration_id, status))

    monkeypatch.setattr(ssh_machine_control, "_save_targets", _fake_save_targets)
    monkeypatch.setattr(ssh_machine_control, "get_registered_targets", lambda: [])
    monkeypatch.setattr(ssh_machine_control, "get_status", lambda _integration_id: "disabled")
    monkeypatch.setattr(ssh_machine_control, "set_status", _fake_set_status)

    provider = ssh_machine_control.SSHMachineControlProvider()
    payload = await provider.enroll(
        _FakeDb(),
        server_base_url="http://spindrel.local/",
        label="LAN Box",
        config={
            "host": "10.0.0.15",
            "username": "matt",
            "port": 2222,
            "working_dir": "/srv/app",
        },
    )

    assert payload["target"]["label"] == "LAN Box"
    assert payload["target"]["hostname"] == "10.0.0.15"
    assert payload["target"]["metadata"]["username"] == "matt"
    assert payload["target"]["metadata"]["port"] == 2222
    assert payload["target"]["metadata"]["working_dir"] == "/srv/app"
    assert payload["target"]["metadata"]["status"] == "unknown"
    assert enabled_states == [("ssh", "enabled")]
    assert saved_targets


@pytest.mark.asyncio
async def test_ssh_probe_updates_cached_reachability(monkeypatch):
    targets = [{
        "target_id": "target-1",
        "driver": "ssh",
        "label": "LAN Box",
        "hostname": "10.0.0.15",
        "platform": "",
        "capabilities": ["shell"],
        "enrolled_at": "2026-04-23T12:00:00+00:00",
        "last_seen_at": None,
        "metadata": {
            "host": "10.0.0.15",
            "username": "matt",
            "port": 22,
            "working_dir": "/srv/app",
            "status": "unknown",
            "reason": None,
            "checked_at": None,
            "handle_id": None,
        },
    }]

    async def _fake_save_targets(_db, new_targets):
        targets[:] = list(new_targets)

    async def _fake_run_ssh(*_args, **_kwargs):
        return {
            "stdout": "lan-box\nLinux 6.8.9 x86_64\n",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 0,
            "truncated": False,
        }

    def _fake_get_value(_integration_id: str, key: str, default: str = ""):
        values = {
            "SSH_PRIVATE_KEY": "PRIVATE KEY",
            "SSH_KNOWN_HOSTS": "known-hosts-entry",
        }
        return values.get(key, default)

    monkeypatch.setattr(ssh_machine_control, "_save_targets", _fake_save_targets)
    monkeypatch.setattr(ssh_machine_control, "get_registered_targets", lambda: list(targets))
    monkeypatch.setattr(ssh_machine_control, "_run_ssh", _fake_run_ssh)
    monkeypatch.setattr(ssh_machine_control, "get_value", _fake_get_value)

    provider = ssh_machine_control.SSHMachineControlProvider()
    status = await provider.probe_target(_FakeDb(), target_id="target-1")

    assert status["ready"] is True
    assert status["status"] == "reachable"
    assert targets[0]["hostname"] == "lan-box"
    assert targets[0]["platform"] == "Linux 6.8.9 x86_64"
    assert targets[0]["metadata"]["status"] == "reachable"
    assert targets[0]["metadata"]["reason"] is None


@pytest.mark.asyncio
async def test_ssh_exec_uses_default_working_dir(monkeypatch):
    target = {
        "target_id": "target-1",
        "driver": "ssh",
        "label": "LAN Box",
        "hostname": "10.0.0.15",
        "platform": "",
        "capabilities": ["shell"],
        "enrolled_at": "2026-04-23T12:00:00+00:00",
        "last_seen_at": None,
        "metadata": {
            "host": "10.0.0.15",
            "username": "matt",
            "port": 22,
            "working_dir": "/srv/app",
            "status": "reachable",
            "reason": None,
            "checked_at": "2026-04-23T12:01:00+00:00",
            "handle_id": "ssh://matt@10.0.0.15:22",
        },
    }
    captured: dict[str, object] = {}

    async def _fake_run_ssh(current_target, **kwargs):
        captured["target"] = current_target
        captured["remote_command"] = kwargs["remote_command"]
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 0,
            "truncated": False,
        }

    def _fake_get_value(_integration_id: str, key: str, default: str = ""):
        values = {
            "SSH_PRIVATE_KEY": "PRIVATE KEY",
            "SSH_KNOWN_HOSTS": "known-hosts-entry",
        }
        return values.get(key, default)

    monkeypatch.setattr(ssh_machine_control, "get_registered_targets", lambda: [target])
    monkeypatch.setattr(ssh_machine_control, "_run_ssh", _fake_run_ssh)
    monkeypatch.setattr(ssh_machine_control, "get_value", _fake_get_value)

    provider = ssh_machine_control.SSHMachineControlProvider()
    await provider.exec_command("target-1", "git status")

    assert "cd /srv/app && git status" in str(captured["remote_command"])
