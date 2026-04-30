import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import Task
from app.services.machine_task_grants import is_grant_active, normalize_capabilities
from app.services.step_executor import _run_machine_step


def test_normalize_task_machine_grant_capabilities_defaults_to_inspect_exec():
    assert normalize_capabilities(None) == ["exec", "inspect"]
    assert normalize_capabilities(["inspect", "unknown", "inspect"]) == ["inspect"]


def test_task_machine_grant_active_requires_not_expired_or_revoked():
    now = datetime.now(timezone.utc)
    active = SimpleNamespace(revoked_at=None, expires_at=now + timedelta(minutes=5))
    expired = SimpleNamespace(revoked_at=None, expires_at=now - timedelta(seconds=1))
    revoked = SimpleNamespace(revoked_at=now, expires_at=now + timedelta(minutes=5))

    assert is_grant_active(active, now=now)
    assert not is_grant_active(expired, now=now)
    assert not is_grant_active(revoked, now=now)


@pytest.mark.asyncio
async def test_machine_inspect_step_runs_against_granted_ssh_target(monkeypatch):
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
    assert error == "Task does not have an active SSH machine grant."
