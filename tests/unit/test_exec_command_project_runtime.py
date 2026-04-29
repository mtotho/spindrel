from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.context import current_bot_id, current_channel_id
from app.services.workspace import ExecResult
from app.tools.local import exec_command as exec_tool


class _AsyncSessionCtx:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *_exc):
        return False


@pytest.mark.asyncio
async def test_exec_command_injects_project_runtime_env_and_redacts_output(monkeypatch) -> None:
    channel_id = uuid.uuid4()
    bot = SimpleNamespace(
        id="runtime-bot",
        shared_workspace_id=str(uuid.uuid4()),
        workspace=SimpleNamespace(enabled=True),
        bot_sandbox=SimpleNamespace(enabled=False),
        host_exec=SimpleNamespace(),
    )
    runtime_env = SimpleNamespace(
        env={"PROJECT_KIND": "screenshot", "GITHUB_TOKEN": "ghp_project_runtime_secret"},
        redact_text=lambda text: text.replace("ghp_project_runtime_secret", "[REDACTED]"),
    )
    exec_mock = AsyncMock(
        return_value=ExecResult(
            stdout="PROJECT_KIND=screenshot\nGITHUB_TOKEN=[REDACTED]\n",
            stderr="",
            exit_code=0,
            truncated=False,
            duration_ms=5,
            workspace_type="shared",
        )
    )

    monkeypatch.setattr(exec_tool, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr("app.db.engine.async_session", lambda: _AsyncSessionCtx())
    monkeypatch.setattr(
        "app.services.projects.resolve_channel_work_surface_by_id",
        AsyncMock(return_value=SimpleNamespace(kind="project", root_host_path="/tmp/project", project_id=uuid.uuid4())),
    )
    monkeypatch.setattr(
        "app.services.project_runtime.load_project_runtime_environment_for_id",
        AsyncMock(return_value=runtime_env),
    )
    monkeypatch.setattr("app.services.bot_hooks.run_before_access", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.bot_hooks.run_after_exec", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.bot_hooks.schedule_after_write", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.services.workspace.workspace_service.exec", exec_mock)

    bot_token = current_bot_id.set(bot.id)
    channel_token = current_channel_id.set(channel_id)
    try:
        raw = await exec_tool.exec_command("env | sort")
    finally:
        current_channel_id.reset(channel_token)
        current_bot_id.reset(bot_token)

    body = json.loads(raw)
    assert body["stdout"].endswith("GITHUB_TOKEN=[REDACTED]\n")
    assert "ghp_project_runtime_secret" not in raw
    _, args, kwargs = exec_mock.mock_calls[0]
    assert args[3] == "/tmp/project"
    assert kwargs["extra_env"] == runtime_env.env
    assert kwargs["redact_output"] is runtime_env.redact_text
