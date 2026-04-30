import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import Task
from app.services.machine_task_grants import is_grant_active, normalize_capabilities
from app.services.machine_control import build_machine_task_automation_options, provider_supports_task_machine_automation
from app.services.step_executor import _run_machine_step


def test_normalize_task_machine_grant_capabilities_defaults_to_inspect_exec():
    assert normalize_capabilities(None) == ["exec", "inspect"]
    assert normalize_capabilities(["inspect", "unknown", "inspect"]) == ["inspect"]
    assert normalize_capabilities(["exec", "inspect"], allowed_capabilities=["inspect"]) == ["inspect"]


def test_machine_automation_support_requires_manifest_enablement(monkeypatch):
    monkeypatch.setattr("app.services.machine_control.get_status", lambda _provider_id: "enabled")
    monkeypatch.setattr("app.services.machine_control.is_configured", lambda _provider_id: True)
    monkeypatch.setattr(
        "app.services.machine_control._provider_task_automation_block",
        lambda provider_id: {"enabled": True, "capabilities": ["inspect"]} if provider_id == "adapter" else {},
    )

    assert provider_supports_task_machine_automation("adapter", capability="inspect")
    assert not provider_supports_task_machine_automation("adapter", capability="exec")
    assert not provider_supports_task_machine_automation("plain_machine_provider")


def test_machine_automation_options_are_provider_advertised(monkeypatch):
    class Provider:
        provider_id = "adapter"
        label = "Adapter"
        driver = "adapter"
        supports_enroll = False
        supports_remove_target = False
        supports_profiles = False

        def __init__(self, provider_id: str, targets: list[dict]):
            self.provider_id = provider_id
            self._targets = targets

        def list_targets(self):
            return self._targets

        def get_target_status(self, _target_id):
            return {"ready": True, "status": "ready"}

    providers = {
        "adapter": Provider("adapter", [{"target_id": "target-1", "label": "Build Box"}]),
        "empty": Provider("empty", []),
    }

    monkeypatch.setattr("app.services.machine_control.list_provider_ids", lambda: ["adapter", "plain", "empty"])
    monkeypatch.setattr("app.services.machine_control.get_status", lambda _provider_id: "enabled")
    monkeypatch.setattr("app.services.machine_control.is_configured", lambda _provider_id: True)
    monkeypatch.setattr("app.services.machine_control.get_provider", lambda provider_id: providers[provider_id])
    monkeypatch.setattr(
        "app.services.machine_control._provider_task_automation_block",
        lambda provider_id: (
            {
                "enabled": True,
                "label": "Adapter Machine",
                "target_label": "Adapter target",
                "capabilities": ["inspect"],
            }
            if provider_id in {"adapter", "empty"}
            else {}
        ),
    )

    options = build_machine_task_automation_options()

    assert [provider["provider_id"] for provider in options["providers"]] == ["adapter"]
    assert options["providers"][0]["capabilities"] == ["inspect"]
    assert options["providers"][0]["targets"][0]["target_id"] == "target-1"
    assert [step["type"] for step in options["step_types"]] == ["machine_inspect", "machine_exec"]


def test_task_machine_grant_active_requires_not_expired_or_revoked():
    now = datetime.now(timezone.utc)
    active = SimpleNamespace(revoked_at=None, expires_at=now + timedelta(minutes=5))
    expired = SimpleNamespace(revoked_at=None, expires_at=now - timedelta(seconds=1))
    revoked = SimpleNamespace(revoked_at=now, expires_at=now + timedelta(minutes=5))

    assert is_grant_active(active, now=now)
    assert not is_grant_active(expired, now=now)
    assert not is_grant_active(revoked, now=now)


@pytest.mark.asyncio
async def test_machine_inspect_step_runs_against_granted_machine_target(monkeypatch):
    task = Task(id=uuid.uuid4(), bot_id="bot", prompt="", status="running")
    grant = SimpleNamespace(provider_id="ssh", target_id="target-1", capabilities=["inspect", "exec"])
    active = SimpleNamespace(grant=grant, source_task_id=task.id)

    class _Db:
        async def get(self, _model, _id):
            return task

    class _SessionFactory:
        async def __aenter__(self):
            return _Db()

        async def __aexit__(self, *_args):
            return False

    class _Provider:
        async def inspect_command(self, target_id, command):
            assert target_id == "target-1"
            assert command == "pwd"
            return {"stdout": "/srv/app\n", "stderr": "", "exit_code": 0, "duration_ms": 12}

    async def _active(_db, _task):
        return active

    async def _probe(_db, _active):
        return {"ready": True}

    async def _payload(_db, _task):
        return {"target_label": "Prod SSH"}

    monkeypatch.setattr("app.db.engine.async_session", lambda: _SessionFactory())
    monkeypatch.setattr("app.services.machine_task_grants.get_active_task_machine_grant", _active)
    monkeypatch.setattr("app.services.machine_task_grants.probe_granted_target", _probe)
    monkeypatch.setattr("app.services.machine_task_grants.task_machine_grant_payload", _payload)
    monkeypatch.setattr("app.services.machine_control.get_provider", lambda _provider_id: _Provider())
    monkeypatch.setattr("app.services.machine_control.provider_supports_task_machine_automation", lambda *_args, **_kwargs: True)

    status, result, error = await _run_machine_step(
        task,
        {"type": "machine_inspect", "command": "pwd"},
        0,
        [{"type": "machine_inspect", "command": "pwd"}],
        [{"status": "running"}],
        mode="machine_inspect",
    )

    assert status == "done"
    assert error is None
    assert "Command on Prod SSH: pwd" in result
    assert "/srv/app" in result


@pytest.mark.asyncio
async def test_machine_step_without_task_grant_fails(monkeypatch):
    task = Task(id=uuid.uuid4(), bot_id="bot", prompt="", status="running")

    class _Db:
        async def get(self, _model, _id):
            return task

    class _SessionFactory:
        async def __aenter__(self):
            return _Db()

        async def __aexit__(self, *_args):
            return False

    async def _active(_db, _task):
        return None

    monkeypatch.setattr("app.db.engine.async_session", lambda: _SessionFactory())
    monkeypatch.setattr("app.services.machine_task_grants.get_active_task_machine_grant", _active)

    status, result, error = await _run_machine_step(
        task,
        {"type": "machine_exec", "command": "echo hi"},
        0,
        [{"type": "machine_exec", "command": "echo hi"}],
        [{"status": "running"}],
        mode="machine_exec",
    )

    assert status == "failed"
    assert result is None
    assert error == "Task does not have an active machine grant."
