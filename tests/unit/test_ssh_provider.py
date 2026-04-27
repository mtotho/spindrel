from __future__ import annotations

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from integrations.ssh import machine_control as ssh_machine_control


class _FakeDb:
    pass


def _real_openssh_private_key() -> str:
    """Generate a fresh ed25519 OpenSSH private key for tests."""
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _real_ssh_public_key_line() -> str:
    """Generate a fresh ed25519 OpenSSH public key line."""
    key = ed25519.Ed25519PrivateKey.generate().public_key()
    return key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode()


# Cached so we don't burn entropy across many tests.
_SAMPLE_PRIVATE_KEY = _real_openssh_private_key()


def _stored_profile(profile_id: str = "profile-1") -> dict:
    return {
        "profile_id": profile_id,
        "label": "LAN Profile",
        "created_at": "2026-04-24T10:00:00+00:00",
        "updated_at": "2026-04-24T10:00:00+00:00",
        "config": {
            "private_key": _SAMPLE_PRIVATE_KEY,
            "known_hosts": "known-hosts-entry",
        },
    }


@pytest.mark.asyncio
async def test_ssh_create_profile_persists_secret_payload(monkeypatch):
    saved_profiles: list[dict] = []
    enabled_states: list[tuple[str, str]] = []

    async def _fake_save_profiles(_db, profiles):
        saved_profiles[:] = list(profiles)

    async def _fake_set_status(integration_id: str, status: str):
        enabled_states.append((integration_id, status))

    monkeypatch.setattr(ssh_machine_control, "_save_profiles", _fake_save_profiles)
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [])
    monkeypatch.setattr(ssh_machine_control, "get_status", lambda _integration_id: "disabled")
    monkeypatch.setattr(ssh_machine_control, "set_status", _fake_set_status)

    provider = ssh_machine_control.SSHMachineControlProvider()
    payload = await provider.create_profile(
        _FakeDb(),
        label="LAN Profile",
        config={
            "private_key": _SAMPLE_PRIVATE_KEY,
            "known_hosts": "known-hosts-entry",
        },
    )

    assert payload["label"] == "LAN Profile"
    assert payload["summary"] == "2 secrets configured"
    assert payload["metadata"]["configured_secrets"] == ["private_key", "known_hosts"]
    assert saved_profiles[0]["config"]["private_key"] == _SAMPLE_PRIVATE_KEY
    assert enabled_states == [("ssh", "enabled")]


@pytest.mark.asyncio
async def test_ssh_update_profile_preserves_existing_secret_when_omitted(monkeypatch):
    profiles = [_stored_profile()]

    async def _fake_save_profiles(_db, new_profiles):
        profiles[:] = list(new_profiles)

    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: list(profiles))
    monkeypatch.setattr(ssh_machine_control, "_save_profiles", _fake_save_profiles)

    provider = ssh_machine_control.SSHMachineControlProvider()
    payload = await provider.update_profile(
        _FakeDb(),
        profile_id="profile-1",
        label="Renamed",
        config={"known_hosts": "new-known-hosts"},
    )

    assert payload["label"] == "Renamed"
    assert profiles[0]["config"]["private_key"] == _SAMPLE_PRIVATE_KEY
    assert profiles[0]["config"]["known_hosts"] == "new-known-hosts"


@pytest.mark.asyncio
async def test_ssh_delete_profile_rejects_in_use_profile(monkeypatch):
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [_stored_profile()])
    monkeypatch.setattr(
        ssh_machine_control,
        "get_registered_targets",
        lambda: [{"target_id": "target-1", "profile_id": "profile-1"}],
    )

    provider = ssh_machine_control.SSHMachineControlProvider()
    with pytest.raises(RuntimeError, match="still in use"):
        await provider.delete_profile(_FakeDb(), "profile-1")


@pytest.mark.asyncio
async def test_ssh_enroll_persists_target_metadata_and_profile_reference(monkeypatch):
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
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [_stored_profile()])

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
            "profile_id": "profile-1",
        },
    )

    assert payload["target"]["label"] == "LAN Box"
    assert payload["target"]["hostname"] == "10.0.0.15"
    assert payload["target"]["profile_id"] == "profile-1"
    assert payload["target"]["profile_label"] == "LAN Profile"
    assert payload["target"]["metadata"]["username"] == "matt"
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
        "profile_id": "profile-1",
        "profile_label": "LAN Profile",
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

    monkeypatch.setattr(ssh_machine_control, "_save_targets", _fake_save_targets)
    monkeypatch.setattr(ssh_machine_control, "get_registered_targets", lambda: list(targets))
    monkeypatch.setattr(ssh_machine_control, "_run_ssh", _fake_run_ssh)
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [_stored_profile()])

    provider = ssh_machine_control.SSHMachineControlProvider()
    status = await provider.probe_target(_FakeDb(), target_id="target-1")

    assert status["ready"] is True
    assert status["status"] == "reachable"
    assert targets[0]["hostname"] == "lan-box"
    assert targets[0]["platform"] == "Linux 6.8.9 x86_64"
    assert targets[0]["metadata"]["status"] == "reachable"
    assert targets[0]["metadata"]["reason"] is None


@pytest.mark.asyncio
async def test_ssh_exec_uses_default_working_dir_and_profile_auth(monkeypatch):
    target = {
        "target_id": "target-1",
        "driver": "ssh",
        "label": "LAN Box",
        "hostname": "10.0.0.15",
        "platform": "",
        "capabilities": ["shell"],
        "profile_id": "profile-1",
        "profile_label": "LAN Profile",
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
        captured["auth"] = kwargs["auth"]
        captured["remote_command"] = kwargs["remote_command"]
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 0,
            "truncated": False,
        }

    monkeypatch.setattr(ssh_machine_control, "get_registered_targets", lambda: [target])
    monkeypatch.setattr(ssh_machine_control, "_run_ssh", _fake_run_ssh)
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [_stored_profile()])

    provider = ssh_machine_control.SSHMachineControlProvider()
    await provider.exec_command("target-1", "git status")

    assert "cd /srv/app && git status" in str(captured["remote_command"])
    assert captured["auth"]["profile_id"] == "profile-1"


@pytest.mark.asyncio
async def test_ssh_create_profile_rejects_public_key(monkeypatch):
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [])
    provider = ssh_machine_control.SSHMachineControlProvider()
    with pytest.raises(ValueError, match="public key"):
        await provider.create_profile(
            _FakeDb(),
            label="LAN Profile",
            config={
                "private_key": _real_ssh_public_key_line(),
                "known_hosts": "known-hosts-entry",
            },
        )


@pytest.mark.asyncio
async def test_ssh_create_profile_rejects_putty_ppk(monkeypatch):
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [])
    provider = ssh_machine_control.SSHMachineControlProvider()
    with pytest.raises(ValueError, match="PuTTY"):
        await provider.create_profile(
            _FakeDb(),
            config={
                "private_key": "PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\n...",
                "known_hosts": "known-hosts-entry",
            },
        )


@pytest.mark.asyncio
async def test_ssh_create_profile_rejects_truncated_key(monkeypatch):
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [])
    provider = ssh_machine_control.SSHMachineControlProvider()
    with pytest.raises(ValueError, match="OpenSSH/PEM"):
        await provider.create_profile(
            _FakeDb(),
            config={
                "private_key": "this is just some random pasted text",
                "known_hosts": "known-hosts-entry",
            },
        )


@pytest.mark.asyncio
async def test_ssh_create_profile_rejects_encrypted_key(monkeypatch):
    encrypted = ed25519.Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.BestAvailableEncryption(b"hunter2"),
    ).decode()
    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: [])
    provider = ssh_machine_control.SSHMachineControlProvider()
    with pytest.raises(ValueError, match="passphrase"):
        await provider.create_profile(
            _FakeDb(),
            config={
                "private_key": encrypted,
                "known_hosts": "known-hosts-entry",
            },
        )


@pytest.mark.asyncio
async def test_ssh_update_profile_validates_new_private_key(monkeypatch):
    profiles = [_stored_profile()]

    async def _fake_save_profiles(_db, new_profiles):
        profiles[:] = list(new_profiles)

    monkeypatch.setattr(ssh_machine_control, "_get_stored_profiles", lambda: list(profiles))
    monkeypatch.setattr(ssh_machine_control, "_save_profiles", _fake_save_profiles)

    provider = ssh_machine_control.SSHMachineControlProvider()
    with pytest.raises(ValueError, match="public key"):
        await provider.update_profile(
            _FakeDb(),
            profile_id="profile-1",
            config={"private_key": _real_ssh_public_key_line()},
        )
    # Original key should be untouched.
    assert profiles[0]["config"]["private_key"] == _SAMPLE_PRIVATE_KEY
