from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Message, Session as SessionRow
from app.services.agent_harnesses.session_state import (
    HARNESS_CONTEXT_HINTS_KEY,
    compact_harness_session,
    context_window_from_usage,
    estimate_context_remaining_pct,
    estimate_native_compaction_remaining_pct,
    load_context_hints,
    load_latest_harness_metadata,
    normalize_context_usage,
    set_resume_reset,
)
from tests.factories import build_bot, build_channel

pytestmark = pytest.mark.asyncio


async def test_context_window_from_usage_only_reads_normalized_fields():
    assert context_window_from_usage({"context_window_tokens": 200_000}) == 200_000
    assert context_window_from_usage({"model_context_window": 100_000}) == 100_000
    assert context_window_from_usage({"modelContextWindow": 50_000}) is None


async def test_native_compaction_remaining_treats_oversized_totals_as_reset():
    usage = {
        "input_tokens": 195_151,
        "output_tokens": 5_273,
        "cached_tokens": 168_064,
        "total_tokens": 200_424,
    }

    assert estimate_native_compaction_remaining_pct(
        usage,
        context_window_tokens=121_600,
    ) == 100.0


async def test_native_compaction_remaining_prefers_last_turn_usage():
    usage = {
        "total_tokens": 200_424,
        "last_total_tokens": 12_160,
    }

    assert estimate_native_compaction_remaining_pct(
        usage,
        context_window_tokens=121_600,
    ) == 90.0


async def test_context_remaining_prefers_codex_last_turn_over_cumulative_total():
    usage = {
        "input_tokens": 276_563,
        "output_tokens": 6_529,
        "cached_tokens": 225_664,
        "total_tokens": 283_092,
        "last_total_tokens": 12_160,
    }

    assert estimate_context_remaining_pct(
        usage,
        context_window_tokens=121_600,
    ) == 90.0


async def test_context_remaining_ignores_low_confidence_total_only_usage():
    usage = {"total_tokens": 283_092}

    assert estimate_context_remaining_pct(
        usage,
        context_window_tokens=200_000,
    ) is None
    snapshot = normalize_context_usage(
        usage,
        runtime="claude-code",
        context_window_tokens=200_000,
    )
    assert snapshot["confidence"] == "low"
    assert snapshot["remaining_pct"] == 0.0
    assert snapshot["reason"] == "total_tokens may be billing or cumulative, not active context"


async def test_context_usage_does_not_add_cache_tokens_to_prompt_footprint():
    usage = {
        "input_tokens": 78_000,
        "output_tokens": 2_000,
        "cache_read_input_tokens": 120_000,
        "cached_tokens": 120_000,
    }

    snapshot = normalize_context_usage(
        usage,
        runtime="claude-code",
        context_window_tokens=200_000,
    )

    assert snapshot["confidence"] == "medium"
    assert snapshot["context_tokens"] == 80_000
    assert snapshot["remaining_pct"] == 60.0
    assert snapshot["source_fields"] == ["input_tokens", "output_tokens"]


@pytest.fixture
async def harness_session(db_session):
    bot = build_bot(id="harness-state-bot", name="Harness State", model="x")
    bot.harness_runtime = "claude-code"
    db_session.add(bot)
    channel = build_channel(bot_id=bot.id)
    db_session.add(channel)
    session = SessionRow(
        id=uuid.uuid4(),
        client_id="harness-state-client",
        bot_id=bot.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.commit()
    return session


async def test_compact_harness_session_adds_summary_hint(harness_session, db_session):
    db_session.add(
        Message(
            session_id=harness_session.id,
            role="user",
            content="Remember the deployment gotcha.",
            metadata_={},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    summary = await compact_harness_session(db_session, harness_session.id)

    assert "deployment gotcha" in summary
    hints = await load_context_hints(db_session, harness_session.id)
    assert len(hints) == 1
    assert hints[0].kind == "compact_summary"
    assert "deployment gotcha" in hints[0].text
    await db_session.refresh(harness_session)
    assert HARNESS_CONTEXT_HINTS_KEY in (harness_session.metadata_ or {})


async def test_resume_reset_hides_older_harness_resume(harness_session, db_session):
    old_message = Message(
        session_id=harness_session.id,
        role="assistant",
        content="old",
        metadata_={"harness": {"runtime": "claude-code", "session_id": "old-native"}},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(old_message)
    await db_session.commit()

    await set_resume_reset(db_session, harness_session.id, summary="reset")
    meta, _ = await load_latest_harness_metadata(db_session, harness_session.id)
    assert meta is None

    db_session.add(
        Message(
            session_id=harness_session.id,
            role="assistant",
            content="new",
            metadata_={"harness": {"runtime": "claude-code", "session_id": "new-native"}},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    meta, _ = await load_latest_harness_metadata(db_session, harness_session.id)
    assert meta and meta["session_id"] == "new-native"
