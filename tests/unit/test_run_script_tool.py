import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Skill
from app.tools.local.run_script import run_script


@pytest.mark.asyncio
async def test_run_script_can_execute_stored_skill_script(
    db_session, patched_async_sessions, agent_context, tmp_path,
):
    db_session.add(Skill(
        id="bots/testbot/ops-guide",
        name="Ops Guide",
        content="---\nname: Ops Guide\n---\n\nThis is long enough to be a valid skill body.",
        scripts=[{
            "name": "tail-logs",
            "description": "Tail recent logs.",
            "script": "print('from stored script')\n",
            "timeout_s": 25,
        }],
        source_type="tool",
    ))
    await db_session.commit()
    agent_context(bot_id="testbot")

    fake_bot = SimpleNamespace(
        workspace=SimpleNamespace(enabled=True),
        max_script_tool_calls=None,
        shared_workspace_id=None,
    )
    fake_result = SimpleNamespace(
        stdout="ok",
        stderr="",
        exit_code=0,
        duration_ms=12,
        truncated=False,
        workspace_type="host",
    )

    with (
        patch("app.agent.bots.get_bot", return_value=fake_bot),
        patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(tmp_path)),
        patch("app.services.workspace.workspace_service.exec", new=AsyncMock(return_value=fake_result)) as exec_mock,
        patch("app.services.script_runner.cleanup_scratch_dir"),
    ):
        result = json.loads(await run_script(skill_name="ops-guide", script_name="tail-logs"))

    assert result["exit_code"] == 0
    script_path = tmp_path / ".run_script"
    [run_dir] = list(script_path.iterdir())
    assert (run_dir / "script.py").read_text() == "print('from stored script')\n"
    exec_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_script_uses_stored_timeout_when_default_argument_left_unchanged(
    db_session, patched_async_sessions, agent_context, tmp_path,
):
    db_session.add(Skill(
        id="bots/testbot/ops-guide",
        name="Ops Guide",
        content="---\nname: Ops Guide\n---\n\nThis is long enough to be a valid skill body.",
        scripts=[{
            "name": "tail-logs",
            "description": "Tail recent logs.",
            "script": "print('from stored script')\n",
            "timeout_s": 25,
        }],
        source_type="tool",
    ))
    await db_session.commit()
    agent_context(bot_id="testbot")

    fake_bot = SimpleNamespace(
        workspace=SimpleNamespace(enabled=True),
        max_script_tool_calls=None,
        shared_workspace_id=None,
    )
    fake_result = SimpleNamespace(
        stdout="ok",
        stderr="",
        exit_code=0,
        duration_ms=12,
        truncated=False,
        workspace_type="host",
    )

    with (
        patch("app.agent.bots.get_bot", return_value=fake_bot),
        patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(tmp_path)),
        patch("app.services.workspace.workspace_service.exec", new=AsyncMock(return_value=fake_result)),
        patch("app.services.script_runner.cleanup_scratch_dir"),
    ):
        await run_script(skill_name="ops-guide", script_name="tail-logs")

    [run_dir] = list((tmp_path / ".run_script").iterdir())
    script_text = (run_dir / "script.py").read_text()
    assert "from stored script" in script_text


@pytest.mark.asyncio
async def test_run_script_rejects_mixing_inline_and_stored_modes(agent_context):
    agent_context(bot_id="testbot")

    result = json.loads(await run_script(
        script="print('hi')",
        skill_name="ops-guide",
        script_name="tail-logs",
    ))

    assert result["error"] == "provide_either_inline_script_or_stored_script_reference"
