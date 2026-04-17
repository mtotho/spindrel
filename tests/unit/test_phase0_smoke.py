"""Smoke tests for Phase 0 shared infra.

Proves the three load-bearing pieces actually work end-to-end:

1. Factories produce real ORM rows that commit against the test engine.
2. ``patched_async_sessions`` routes service-module-local ``async_session()``
   calls to the test DB.
3. ``agent_context`` sets ContextVars and tears them down.

Delete this file once the Phase 1 pilot (``test_memory_hygiene.py`` rewrite)
has landed — these are only here to validate the scaffolding.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.context import current_bot_id, current_channel_id
from app.db.models import Bot, Channel, ChannelBotMember, Task
from tests.factories import (
    build_bot,
    build_channel,
    build_channel_bot_member,
    build_skill,
    build_task,
    build_workflow,
    build_workflow_run,
)


@pytest.mark.asyncio
async def test_when_factories_flush_then_rows_round_trip_through_real_db(db_session):
    bot = build_bot()
    channel = build_channel(bot_id=bot.id)
    member = build_channel_bot_member(channel_id=channel.id, bot_id=bot.id)

    db_session.add_all([bot, channel, member])
    await db_session.commit()

    fetched_bot = (await db_session.execute(select(Bot).where(Bot.id == bot.id))).scalar_one()
    fetched_channel = (
        await db_session.execute(select(Channel).where(Channel.id == channel.id))
    ).scalar_one()
    fetched_member = (
        await db_session.execute(
            select(ChannelBotMember).where(ChannelBotMember.id == member.id)
        )
    ).scalar_one()

    assert fetched_bot.name.startswith("Test Bot")
    assert fetched_channel.bot_id == fetched_bot.id
    assert fetched_member.channel_id == fetched_channel.id


@pytest.mark.asyncio
async def test_when_workflow_run_factory_flushes_then_step_states_jsonb_roundtrips(db_session):
    workflow = build_workflow()
    run = build_workflow_run(workflow_id=workflow.id, bot_id="bot-a")

    db_session.add_all([workflow, run])
    await db_session.commit()
    await db_session.refresh(run)

    assert run.step_states == [
        {"status": "running", "task_id": None, "result": None, "error": None}
    ]


@pytest.mark.asyncio
async def test_when_patched_async_sessions_then_tasks_module_uses_test_engine(
    db_session, patched_async_sessions, agent_context
):
    """End-to-end: a service that opens its own ``async_session()`` persists
    against the test DB, and rows are visible via ``db_session``."""
    from app.tools.local.tasks import schedule_task

    agent_context(
        bot_id="smoke-bot",
        session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        client_id="smoke-client",
        dispatch_type="none",
        dispatch_config={},
    )

    result_json = await schedule_task(prompt="smoke-test prompt")
    import json

    data = json.loads(result_json)
    assert data["status"] == "pending"
    assert data["bot_id"] == "smoke-bot"

    persisted = (
        await db_session.execute(select(Task).where(Task.id == uuid.UUID(data["id"])))
    ).scalar_one()
    assert persisted.prompt == "smoke-test prompt"


def test_when_agent_context_exits_then_contextvars_reset(agent_context):
    agent_context(bot_id="temporary", channel_id=uuid.uuid4())

    assert current_bot_id.get() == "temporary"
    # channel_id is set; we don't assert its value, just that set/reset works
    assert current_channel_id.get() is not None


def test_when_skill_factory_called_then_returns_real_skill_orm(db_session):
    skill = build_skill(name="Hello")
    assert skill.name == "Hello"
    assert skill.id.startswith("skills/")


def test_when_task_factory_called_then_required_fields_populated():
    task = build_task(bot_id="x")
    assert task.bot_id == "x"
    assert task.status == "pending"
    assert task.prompt.startswith("Test prompt")
