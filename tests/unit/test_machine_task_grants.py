from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.context import current_session_id, current_task_id
from app.db.models import Session, Task, User
from app.services import machine_control, machine_task_grants, step_executor


class _FakeAsyncSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, *, task: Task | None = None, session: Session | None = None, user: User | None = None):
        self.task = task
        self.session = session
        self.user = user
        self.commit_count = 0

    async def get(self, model, row_id):
        if model is Task and self.task is not None and row_id == self.task.id:
            return self.task
        if model is Session and self.session is not None and row_id == self.session.id:
            return self.session
        if model is User and self.user is not None and row_id == self.user.id:
            return self.user
        return None

    async def commit(self):
        self.commit_count += 1


class _FakeProvider:
    provider_id = "ssh"
    label = "SSH"
    driver = "ssh"
    supports_enroll = True
    supports_remove_target = True
    supports_profiles = True

    def __init__(self):
        self.exec_command = AsyncMock(return_value={
            "exit_code": 0,
            "duration_ms": 17,
            "stdout": "ok\n",
            "stderr": "",
            "truncated": False,
        })

    def get_target(self, target_id: str):
        if target_id == "target-1":
            return {"target_id": "target-1", "label": "Runner"}
        return None


def _task_session_user():
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    task = Task(
        id=task_id,
        bot_id="agent-bot",
        prompt="run machine step",
        session_id=session_id,
    )
    session = Session(
        id=session_id,
        client_id="client-1",
        bot_id="agent-bot",
        owner_user_id=user_id,
        metadata_={},
    )
    user = User(
        id=user_id,
        email="operator@example.test",
        display_name="Operator",
        auth_method="local",
        password_hash="hash",
        is_active=True,
        is_admin=True,
        integration_config={},
    )
    return task, session, user


@pytest.mark.asyncio
async def test_autonomous_machine_policy_uses_active_task_grant(monkeypatch):
    task, session, user = _task_session_user()
    db = _FakeDb(task=task, session=session, user=user)
    active = SimpleNamespace(grant=SimpleNamespace(allow_agent_tools=True))
    lease = {
        "provider_id": "ssh",
        "target_id": "target-1",
        "user_id": str(user.id),
        "lease_id": "lease-1",
    }

    monkeypatch.setattr(machine_task_grants, "async_session", lambda: _FakeAsyncSessionContext(db))
    monkeypatch.setattr(machine_task_grants, "get_active_task_machine_grant", AsyncMock(return_value=active))
    monkeypatch.setattr(machine_task_grants, "ensure_task_machine_lease", AsyncMock(return_value=lease))
    monkeypatch.setattr(machine_control, "enrich_lease_payload", lambda payload: {**payload, "target_label": "Runner"})
    task_token = current_task_id.set(task.id)
    session_token = current_session_id.set(session.id)
    try:
        result = await machine_task_grants.validate_current_automation_execution_policy("live_target_lease")
    finally:
        current_session_id.reset(session_token)
        current_task_id.reset(task_token)

    assert result.allowed is True
    assert result.session is session
    assert result.user is user
    assert result.lease["target_label"] == "Runner"
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_pipeline_machine_exec_runs_against_task_granted_target(monkeypatch):
    task, _session, _user = _task_session_user()
    db = _FakeDb(task=task)
    provider = _FakeProvider()
    active = SimpleNamespace(
        grant=SimpleNamespace(
            provider_id="ssh",
            target_id="target-1",
            capabilities=["exec"],
        )
    )

    monkeypatch.setattr("app.db.engine.async_session", lambda: _FakeAsyncSessionContext(db))
    monkeypatch.setattr(machine_task_grants, "get_active_task_machine_grant", AsyncMock(return_value=active))
    monkeypatch.setattr(machine_task_grants, "probe_granted_target", AsyncMock(return_value={"ready": True}))
    monkeypatch.setattr(
        machine_task_grants,
        "task_machine_grant_payload",
        AsyncMock(return_value={"target_label": "Runner"}),
    )
    monkeypatch.setattr(machine_control, "get_provider", lambda _provider_id: provider)
    monkeypatch.setattr(machine_task_grants, "provider_supports_task_machine_automation", lambda *_args, **_kwargs: True)

    status, result, error = await step_executor._run_machine_step(
        task,
        {
            "type": "machine_exec",
            "command": "pytest -q",
            "working_directory": "/repo",
        },
        0,
        [],
        [],
        mode="machine_exec",
    )

    assert status == "done"
    assert error is None
    assert result and "Command on Runner: pytest -q" in result
    assert "Working directory: /repo" in result
    assert "ok" in result
    provider.exec_command.assert_awaited_once_with("target-1", "pytest -q", "/repo")
