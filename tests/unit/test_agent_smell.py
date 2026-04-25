from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Bot, Task, ToolCall, TraceEvent
from app.routers.api_v1_admin.usage import agent_smell


def _bot(bot_id: str, *, emoji: str | None = None) -> Bot:
    return Bot(
        id=bot_id,
        name=bot_id.replace("-", " ").title(),
        display_name=bot_id.title(),
        avatar_emoji=emoji,
        model="test/model",
        system_prompt="test",
    )


def _usage_event(
    *,
    bot_id: str,
    correlation_id: uuid.UUID,
    created_at: datetime,
    tokens: int,
    iteration: int = 1,
) -> TraceEvent:
    return TraceEvent(
        bot_id=bot_id,
        correlation_id=correlation_id,
        event_type="token_usage",
        data={
            "prompt_tokens": tokens,
            "completion_tokens": 0,
            "total_tokens": tokens,
            "iteration": iteration,
            "model": "test/model",
        },
        created_at=created_at,
    )


def _tool_call(
    *,
    bot_id: str,
    correlation_id: uuid.UUID,
    created_at: datetime,
    tool_name: str = "inspect_trace",
    arguments: dict | None = None,
    status: str = "done",
    error: str | None = None,
    iteration: int = 1,
) -> ToolCall:
    return ToolCall(
        bot_id=bot_id,
        tool_name=tool_name,
        tool_type="local",
        arguments=arguments or {"trace": "same"},
        status=status,
        error=error,
        iteration=iteration,
        correlation_id=correlation_id,
        created_at=created_at,
        completed_at=created_at + timedelta(seconds=1),
    )


@pytest.mark.asyncio
async def test_agent_smell_ranks_loop_friction_above_plain_token_volume(db_session):
    now = datetime.now(timezone.utc)
    loop_trace = uuid.uuid4()
    token_trace = uuid.uuid4()
    db_session.add_all([
        _bot("loop-bot", emoji="L"),
        _bot("token-bot", emoji="T"),
        _usage_event(
            bot_id="loop-bot",
            correlation_id=loop_trace,
            created_at=now - timedelta(minutes=20),
            tokens=2_000,
            iteration=7,
        ),
        _usage_event(
            bot_id="token-bot",
            correlation_id=token_trace,
            created_at=now - timedelta(minutes=10),
            tokens=20_000,
        ),
    ])
    for index in range(10):
        db_session.add(_tool_call(
            bot_id="loop-bot",
            correlation_id=loop_trace,
            created_at=now - timedelta(minutes=19, seconds=-index),
            status="error" if index >= 8 else "done",
            error="boom" if index >= 8 else None,
            iteration=index + 1,
        ))
    await db_session.commit()

    out = await agent_smell(
        hours=24,
        baseline_days=7,
        bot_id=None,
        source_type=None,
        limit=10,
        db=db_session,
        _auth=None,
    )

    assert out.bots[0].bot_id == "loop-bot"
    assert out.bots[0].avatar_emoji == "L"
    assert out.bots[0].score >= 50
    assert out.bots[0].reasons[0].key == "loop_friction"
    assert out.bots[0].metrics.repeated_tool_calls == 9
    assert out.bots[0].traces[0].correlation_id == str(loop_trace)


@pytest.mark.asyncio
async def test_agent_smell_source_filter_is_applied_to_tasks_and_agent_traces(db_session):
    now = datetime.now(timezone.utc)
    agent_trace = uuid.uuid4()
    heartbeat_trace = uuid.uuid4()
    db_session.add_all([
        _bot("agent-bot"),
        _bot("heartbeat-bot"),
        Task(
            bot_id="heartbeat-bot",
            prompt="heartbeat",
            title="Heartbeat",
            task_type="heartbeat",
            correlation_id=heartbeat_trace,
        ),
        _usage_event(
            bot_id="agent-bot",
            correlation_id=agent_trace,
            created_at=now - timedelta(minutes=20),
            tokens=1_000,
        ),
        _usage_event(
            bot_id="heartbeat-bot",
            correlation_id=heartbeat_trace,
            created_at=now - timedelta(minutes=20),
            tokens=1_000,
        ),
    ])
    for index in range(4):
        db_session.add(_tool_call(
            bot_id="agent-bot",
            correlation_id=agent_trace,
            created_at=now - timedelta(minutes=19, seconds=-index),
        ))
        db_session.add(_tool_call(
            bot_id="heartbeat-bot",
            correlation_id=heartbeat_trace,
            created_at=now - timedelta(minutes=18, seconds=-index),
        ))
    await db_session.commit()

    heartbeat = await agent_smell(
        hours=24,
        baseline_days=7,
        bot_id=None,
        source_type="heartbeat",
        limit=10,
        db=db_session,
        _auth=None,
    )
    agent = await agent_smell(
        hours=24,
        baseline_days=7,
        bot_id=None,
        source_type="agent",
        limit=10,
        db=db_session,
        _auth=None,
    )

    assert [row.bot_id for row in heartbeat.bots] == ["heartbeat-bot"]
    assert [row.bot_id for row in agent.bots] == ["agent-bot"]
