"""Harness auto-compaction decision coverage."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import Channel, Session, TraceEvent
from app.services.agent_harnesses import session_state
from app.services.agent_harnesses.session_state import (
    decide_harness_auto_compaction,
    maybe_run_harness_auto_compaction,
)

def _usage(*, remaining: float) -> dict:
    return {
        "context_window_tokens": 1000,
        "context_remaining_pct": remaining,
    }


def test_decision_ignores_missing_usage():
    decision = decide_harness_auto_compaction(
        channel_config={"harness_auto_compaction": {"enabled": True}},
        usage=None,
    )

    assert decision.action == "none"
    assert decision.reason == "missing usage"


def test_decision_prompts_once_below_soft_threshold():
    config = {
        "harness_auto_compaction": {
            "enabled": True,
            "soft_remaining_pct": 60,
            "hard_remaining_pct": 10,
        }
    }

    first = decide_harness_auto_compaction(channel_config=config, usage=_usage(remaining=42))
    assert first.action == "soft"
    assert first.threshold_pct == 60

    config["harness_auto_compaction"]["last_action"] = "soft"
    config["harness_auto_compaction"]["last_remaining_pct"] = 42
    repeat = decide_harness_auto_compaction(channel_config=config, usage=_usage(remaining=40))
    assert repeat.action == "none"
    assert repeat.reason == "already below soft threshold"


def test_decision_triggers_hard_once_below_hard_threshold():
    config = {
        "harness_auto_compaction": {
            "enabled": True,
            "soft_remaining_pct": 60,
            "hard_remaining_pct": 10,
        }
    }

    first = decide_harness_auto_compaction(channel_config=config, usage=_usage(remaining=8))
    assert first.action == "hard"
    assert first.threshold_pct == 10

    config["harness_auto_compaction"]["last_action"] = "hard"
    config["harness_auto_compaction"]["last_remaining_pct"] = 8
    repeat = decide_harness_auto_compaction(channel_config=config, usage=_usage(remaining=7))
    assert repeat.action == "none"
    assert repeat.reason == "already below hard threshold"


@pytest.mark.asyncio
async def test_maybe_run_records_soft_trace_and_channel_state(db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="harness-auto-soft",
        bot_id="harness-bot",
        config={"harness_auto_compaction": {"soft_remaining_pct": 60, "hard_remaining_pct": 10}},
    ))
    db_session.add(Session(
        id=session_id,
        bot_id="harness-bot",
        client_id="harness-auto-soft",
        channel_id=channel_id,
    ))
    await db_session.commit()

    result = await maybe_run_harness_auto_compaction(
        db_session,
        session_id,
        runtime="test-runtime",
        usage=_usage(remaining=35),
    )

    assert result and result["status"] == "prompted"
    channel = await db_session.get(Channel, channel_id)
    assert (channel.config or {})["harness_auto_compaction"]["last_action"] == "soft"

    rows = (await db_session.execute(
        select(TraceEvent).where(TraceEvent.session_id == session_id)
    )).scalars().all()
    assert any(row.event_type == "harness_auto_compaction" and row.event_name == "soft" for row in rows)


@pytest.mark.asyncio
async def test_maybe_run_hard_triggers_native_compaction(monkeypatch, db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="harness-auto-hard",
        bot_id="harness-bot",
        config={"harness_auto_compaction": {"soft_remaining_pct": 60, "hard_remaining_pct": 10}},
    ))
    db_session.add(Session(
        id=session_id,
        bot_id="harness-bot",
        client_id="harness-auto-hard",
        channel_id=channel_id,
    ))
    await db_session.commit()

    calls: list[tuple[uuid.UUID, str]] = []

    async def fake_compact(db, sid, *, source):
        calls.append((sid, source))
        return {"status": "completed", "source": source}

    monkeypatch.setattr(session_state, "run_native_harness_compact", fake_compact)

    result = await maybe_run_harness_auto_compaction(
        db_session,
        session_id,
        runtime="test-runtime",
        usage=_usage(remaining=5),
    )

    assert result == {"status": "completed", "source": "auto-context-pressure"}
    assert calls == [(session_id, "auto-context-pressure")]

    channel = await db_session.get(Channel, channel_id)
    assert (channel.config or {})["harness_auto_compaction"]["last_action"] == "hard"
