import json

import pytest

from app.db.models import Skill
from app.tools.local.bot_skills import manage_bot_skill
from tests.factories import build_bot_skill


@pytest.mark.asyncio
async def test_create_with_named_scripts_persists_and_summarizes(
    db_session, patched_async_sessions, agent_context,
    embed_skill_patch, dedup_patch,
):
    agent_context(bot_id="testbot")
    body = "# Docker Networking\n\nHow to configure bridge networks. " + "x" * 50

    result = json.loads(await manage_bot_skill(
        action="create",
        name="docker-net",
        title="Docker Networking",
        content=body,
        scripts=[{
            "name": "inspect-ports",
            "description": "Check published ports for a compose stack.",
            "script": "from spindrel import tools\nprint('hi')\n",
            "timeout_s": 45,
        }],
    ))

    assert result["ok"] is True
    row = await db_session.get(Skill, "bots/testbot/docker-net")
    assert row.scripts == [{
        "name": "inspect-ports",
        "description": "Check published ports for a compose stack.",
        "script": "from spindrel import tools\nprint('hi')\n",
        "timeout_s": 45,
    }]

    listed = json.loads(await manage_bot_skill(action="list"))
    assert listed["skills"][0]["script_count"] == 1
    assert listed["skills"][0]["scripts"][0]["name"] == "inspect-ports"

    fetched = json.loads(await manage_bot_skill(action="get", name="docker-net"))
    assert fetched["scripts"] == [{
        "name": "inspect-ports",
        "description": "Check published ports for a compose stack.",
        "timeout_s": 45,
    }]


@pytest.mark.asyncio
async def test_get_script_returns_full_body(db_session, patched_async_sessions, agent_context):
    skill = build_bot_skill(
        bot_id="testbot",
        name="ops-guide",
        scripts=[{
            "name": "tail-logs",
            "description": "Tail recent logs.",
            "script": "print('logs')\n",
            "timeout_s": 25,
        }],
    )
    db_session.add(skill)
    await db_session.commit()
    agent_context(bot_id="testbot")

    result = json.loads(await manage_bot_skill(
        action="get_script",
        name="ops-guide",
        script_name="tail-logs",
    ))

    assert result["ok"] is True
    assert result["script_name"] == "tail-logs"
    assert result["script_body"] == "print('logs')\n"
    assert result["script_timeout_s"] == 25


@pytest.mark.asyncio
async def test_add_update_delete_script_round_trip(db_session, patched_async_sessions, agent_context):
    skill = build_bot_skill(bot_id="testbot", name="ops-guide")
    db_session.add(skill)
    await db_session.commit()
    agent_context(bot_id="testbot")

    added = json.loads(await manage_bot_skill(
        action="add_script",
        name="ops-guide",
        script_name="tail-logs",
        script_description="Tail recent logs.",
        script_body="print('logs')\n",
        script_timeout_s=25,
    ))
    assert added["ok"] is True

    updated = json.loads(await manage_bot_skill(
        action="update_script",
        name="ops-guide",
        script_name="tail-logs",
        script_description="Tail the most recent logs.",
        script_body="print('new logs')\n",
        script_timeout_s=40,
    ))
    assert updated["ok"] is True

    row = await db_session.get(Skill, "bots/testbot/ops-guide")
    assert row.scripts == [{
        "name": "tail-logs",
        "description": "Tail the most recent logs.",
        "script": "print('new logs')\n",
        "timeout_s": 40,
    }]

    deleted = json.loads(await manage_bot_skill(
        action="delete_script",
        name="ops-guide",
        script_name="tail-logs",
    ))
    assert deleted["ok"] is True

    row = await db_session.get(Skill, "bots/testbot/ops-guide")
    assert row.scripts == []
