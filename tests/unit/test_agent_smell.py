from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Bot, BotSkillEnrollment, BotToolEnrollment, Skill, Task, ToolCall, TraceEvent
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


@pytest.mark.asyncio
async def test_agent_smell_flags_context_bloat_from_unused_enrollments(db_session):
    """Bot with stale fetched enrollments + pinned-but-unused tools should
    surface a 'context_bloat' reason and contribute to the smell score even
    without recent trace activity. This guards the bloat satellite signal.
    """
    now = datetime.now(timezone.utc)
    bloated = Bot(
        id="bloated-bot",
        name="Bloated",
        display_name="Bloated",
        model="test/model",
        system_prompt="test",
        pinned_tools=["never_used_pin", "also_never_used"],
    )
    db_session.add(bloated)
    # 4 stale fetched enrollments older than the 7-day grace window — all unused.
    stale_enrolled_at = now - timedelta(days=14)
    for i in range(4):
        db_session.add(BotToolEnrollment(
            bot_id="bloated-bot",
            tool_name=f"stale_tool_{i}",
            source="fetched",
            enrolled_at=stale_enrolled_at,
            fetch_count=0,
            last_used_at=None,
        ))
    # One recent enrollment (within grace) — should NOT be flagged.
    db_session.add(BotToolEnrollment(
        bot_id="bloated-bot",
        tool_name="recent_tool",
        source="fetched",
        enrolled_at=now - timedelta(days=1),
        fetch_count=0,
    ))
    # tool_surface_summary trace event — drives the schema-tokens estimate.
    db_session.add(TraceEvent(
        bot_id="bloated-bot",
        event_type="tool_surface_summary",
        data={"tool_schema_tokens_estimate": 6500, "tool_count": 18},
        created_at=now - timedelta(hours=1),
    ))
    # A small token_usage event so the bot is in the bot_ids set anyway.
    db_session.add(_usage_event(
        bot_id="bloated-bot",
        correlation_id=uuid.uuid4(),
        created_at=now - timedelta(hours=2),
        tokens=500,
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

    bloated_row = next((b for b in out.bots if b.bot_id == "bloated-bot"), None)
    assert bloated_row is not None, "bloated bot should rank"
    assert bloated_row.metrics.unused_tools_count == 4
    assert set(bloated_row.metrics.pinned_unused_tools) == {"never_used_pin", "also_never_used"}
    assert bloated_row.metrics.tool_schema_tokens_estimate == 6500
    assert bloated_row.metrics.estimated_bloat_tokens > 0
    bloat_reason = next((r for r in bloated_row.reasons if r.key == "context_bloat"), None)
    assert bloat_reason is not None, "context_bloat reason should be present"
    assert bloat_reason.points >= 6
    # Summary surfaces the workspace-wide signal that drives the satellite.
    assert out.summary.bloated_bot_count >= 1
    assert out.summary.total_unused_tools == 4
    assert out.summary.total_pinned_unused_tools == 2


@pytest.mark.asyncio
async def test_agent_smell_excludes_pinned_tools_from_unused_count(db_session):
    """A pinned tool with fetch_count==0 belongs in pinned_unused_tools, not
    unused_tools_count — the snapshot must distinguish user intent from
    discovery noise so the bot can report rather than prune.
    """
    now = datetime.now(timezone.utc)
    db_session.add(Bot(
        id="pinned-bot",
        name="Pinned",
        model="test/model",
        system_prompt="test",
        pinned_tools=["my_pinned_tool"],
    ))
    db_session.add(BotToolEnrollment(
        bot_id="pinned-bot",
        tool_name="my_pinned_tool",
        source="manual",
        enrolled_at=now - timedelta(days=30),
        fetch_count=0,
    ))
    db_session.add(_usage_event(
        bot_id="pinned-bot",
        correlation_id=uuid.uuid4(),
        created_at=now - timedelta(hours=1),
        tokens=200,
    ))
    await db_session.commit()

    out = await agent_smell(
        hours=24, baseline_days=7, bot_id=None, source_type=None,
        limit=10, db=db_session, _auth=None,
    )
    row = next(b for b in out.bots if b.bot_id == "pinned-bot")
    assert row.metrics.unused_tools_count == 0
    assert row.metrics.pinned_unused_tools == ["my_pinned_tool"]


@pytest.mark.asyncio
async def test_agent_smell_skips_recently_enrolled_tools_under_grace(db_session):
    """Tools enrolled less than 7 days ago must NOT count as unused (grace window).
    The whole point of the grace is to avoid penalizing a bot that just got
    hit with a discovery sweep before it has a chance to use the new tools.
    """
    now = datetime.now(timezone.utc)
    db_session.add(Bot(id="fresh-bot", name="Fresh", model="test/model", system_prompt="test"))
    for i in range(3):
        db_session.add(BotToolEnrollment(
            bot_id="fresh-bot",
            tool_name=f"fresh_tool_{i}",
            source="fetched",
            enrolled_at=now - timedelta(days=2),  # within 7d grace
            fetch_count=0,
        ))
    db_session.add(_usage_event(
        bot_id="fresh-bot",
        correlation_id=uuid.uuid4(),
        created_at=now - timedelta(hours=1),
        tokens=200,
    ))
    await db_session.commit()

    out = await agent_smell(
        hours=24, baseline_days=7, bot_id=None, source_type=None,
        limit=10, db=db_session, _auth=None,
    )
    row = next(b for b in out.bots if b.bot_id == "fresh-bot")
    assert row.metrics.unused_tools_count == 0
    assert all(r.key != "context_bloat" for r in row.reasons)


@pytest.mark.asyncio
async def test_agent_smell_resolves_pinned_skill_names_via_skill_table(db_session):
    """Pinned-unused skills should report the human-readable Skill.name, not
    the raw skill_id. Bot.skills is the pin list; Skill rows hold the labels.
    """
    now = datetime.now(timezone.utc)
    db_session.add(Skill(
        id="my-skill-id",
        name="My Friendly Skill Name",
        content="...",
    ))
    db_session.add(Bot(
        id="skill-bot",
        name="SkillBot",
        model="test/model",
        system_prompt="test",
        skills=["my-skill-id"],
    ))
    db_session.add(_usage_event(
        bot_id="skill-bot",
        correlation_id=uuid.uuid4(),
        created_at=now - timedelta(hours=1),
        tokens=200,
    ))
    await db_session.commit()

    out = await agent_smell(
        hours=24, baseline_days=7, bot_id=None, source_type=None,
        limit=10, db=db_session, _auth=None,
    )
    row = next(b for b in out.bots if b.bot_id == "skill-bot")
    assert row.metrics.pinned_unused_skills == ["My Friendly Skill Name"]
