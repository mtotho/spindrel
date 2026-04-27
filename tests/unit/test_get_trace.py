"""Tests for ``app.tools.local.get_trace`` list mode.

Focus on the ``include_user_message`` path added to support audit pipelines
(analyze_discovery, analyze_skill_quality). The turn's first user message is
the evidence the LLM needs to judge whether a ranker/discovery event fired
correctly — without it the pipeline is flying blind.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.db.models import Message, Session, ToolCall, TraceEvent
from app.tools.local.get_trace import get_trace


async def _seed_turn(
    db_session,
    correlation_id: uuid.UUID,
    bot_id: str,
    user_message: str | None,
    event_data: dict,
    event_type: str = "discovery_summary",
) -> None:
    session_id = uuid.uuid4()
    db_session.add(Session(id=session_id, client_id="test-client", bot_id=bot_id))
    if user_message is not None:
        db_session.add(Message(
            session_id=session_id,
            role="user",
            content=user_message,
            correlation_id=correlation_id,
        ))
    db_session.add(TraceEvent(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot_id,
        event_type=event_type,
        data=event_data,
    ))


class TestGetTraceListMode:
    @pytest.mark.asyncio
    async def test_list_mode_without_user_message_is_compat(
        self, db_session, patched_async_sessions
    ):
        corr = uuid.uuid4()
        await _seed_turn(
            db_session, corr, "crumb", "hello bot", {"threshold": 0.35}
        )
        await db_session.commit()

        out = json.loads(await get_trace(event_type="discovery_summary"))
        assert len(out) == 1
        assert out[0]["correlation_id"] == str(corr)
        assert out[0]["data"] == {"threshold": 0.35}
        # Without the flag, user_message key MUST NOT appear — keeps old callers clean.
        assert "user_message" not in out[0]

    @pytest.mark.asyncio
    async def test_include_user_message_attaches_first_user_message(
        self, db_session, patched_async_sessions
    ):
        corr = uuid.uuid4()
        await _seed_turn(
            db_session, corr, "crumb",
            "can you check the sourdough timing?",
            {"threshold": 0.35, "retrieved": ["foo"]},
        )
        await db_session.commit()

        out = json.loads(
            await get_trace(event_type="discovery_summary", include_user_message=True)
        )
        assert out[0]["user_message"] == "can you check the sourdough timing?"

    @pytest.mark.asyncio
    async def test_include_user_message_truncates_long_content(
        self, db_session, patched_async_sessions
    ):
        long_text = "x" * 800
        corr = uuid.uuid4()
        await _seed_turn(db_session, corr, "crumb", long_text, {"x": 1})
        await db_session.commit()

        out = json.loads(
            await get_trace(event_type="discovery_summary", include_user_message=True)
        )
        msg = out[0]["user_message"]
        assert msg.endswith("…")
        # 400-char preview cap plus the ellipsis
        assert len(msg) == 401

    @pytest.mark.asyncio
    async def test_include_user_message_handles_missing_messages(
        self, db_session, patched_async_sessions
    ):
        # Trace event exists but no corresponding user message (e.g. system-initiated turn)
        corr = uuid.uuid4()
        await _seed_turn(db_session, corr, "crumb", None, {"x": 1})
        await db_session.commit()

        out = json.loads(
            await get_trace(event_type="discovery_summary", include_user_message=True)
        )
        assert out[0]["user_message"] is None

    @pytest.mark.asyncio
    async def test_bot_filter(self, db_session, patched_async_sessions):
        a, b = uuid.uuid4(), uuid.uuid4()
        await _seed_turn(db_session, a, "crumb", "crumb turn", {"x": 1})
        await _seed_turn(db_session, b, "bennie", "bennie turn", {"x": 2})
        await db_session.commit()

        out = json.loads(
            await get_trace(
                event_type="discovery_summary",
                bot_id="crumb",
                include_user_message=True,
            )
        )
        assert len(out) == 1
        assert out[0]["bot_id"] == "crumb"
        assert out[0]["user_message"] == "crumb turn"

    @pytest.mark.asyncio
    async def test_newlines_stripped_from_preview(
        self, db_session, patched_async_sessions
    ):
        corr = uuid.uuid4()
        await _seed_turn(db_session, corr, "crumb", "line1\nline2\nline3", {"x": 1})
        await db_session.commit()

        out = json.loads(
            await get_trace(event_type="discovery_summary", include_user_message=True)
        )
        assert out[0]["user_message"] == "line1 line2 line3"


async def _seed_full_turn(
    db_session,
    correlation_id: uuid.UUID,
    *,
    bot_id: str = "qa-bot",
    tool_calls: int = 2,
    discovery: bool = True,
    skill_index: bool = True,
    error_event: bool = False,
) -> None:
    """Seed a turn with a mix of TraceEvent rows and ToolCall rows so detail-mode
    sub-modes (summary / phase / full) can be exercised end-to-end."""
    session_id = uuid.uuid4()
    db_session.add(Session(id=session_id, client_id="test-client", bot_id=bot_id))
    if discovery:
        db_session.add(TraceEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot_id,
            event_type="discovery_summary",
            data={"tools": {"threshold": 0.35, "retrieved": ["foo"]}, "skills": {"enrolled_count": 3}},
        ))
    if skill_index:
        db_session.add(TraceEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot_id,
            event_type="skill_index",
            data={"unretrieved_count": 4},
        ))
    if error_event:
        db_session.add(TraceEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot_id,
            event_type="error",
            data={"message": "boom"},
        ))
    for i in range(tool_calls):
        db_session.add(ToolCall(
            session_id=session_id,
            bot_id=bot_id,
            tool_name=f"tool_{i}",
            tool_type="local",
            iteration=i + 1,
            arguments={"i": i},
            result=f"ok-{i}",
            correlation_id=correlation_id,
            status="done",
        ))


class TestGetTraceDetailModes:
    """Detail-mode sub-modes: summary (default), phase (paginated), full (legacy)."""

    @pytest.mark.asyncio
    async def test_summary_default_returns_phase_index(
        self, db_session, patched_async_sessions
    ):
        corr = uuid.uuid4()
        await _seed_full_turn(db_session, corr, tool_calls=3)
        await db_session.commit()

        out = json.loads(await get_trace(correlation_id=str(corr)))
        # Summary has no `timeline` key — phases instead.
        assert "timeline" not in out
        assert out["correlation_id"] == str(corr)
        assert out["tool_call_count"] == 3
        assert out["event_count"] == 2  # discovery_summary + skill_index
        names = {p["name"] for p in out["phases"]}
        assert names == {"discovery_summary", "skill_index", "tool_calls"}
        tool_phase = next(p for p in out["phases"] if p["name"] == "tool_calls")
        assert tool_phase["item_count"] == 3
        assert tool_phase["kind"] == "tool_call"

    @pytest.mark.asyncio
    async def test_summary_counts_errors_from_both_sources(
        self, db_session, patched_async_sessions
    ):
        # error_event seeds a TraceEvent with event_type="error". Tool-call
        # errors (status starting with "ERROR") are also counted. We seed one
        # of each below.
        corr = uuid.uuid4()
        session_id = uuid.uuid4()
        db_session.add(Session(id=session_id, client_id="t", bot_id="qa-bot"))
        db_session.add(TraceEvent(
            correlation_id=corr, session_id=session_id, bot_id="qa-bot",
            event_type="error", data={"x": 1},
        ))
        db_session.add(ToolCall(
            session_id=session_id, bot_id="qa-bot",
            tool_name="t", tool_type="local", iteration=1,
            arguments={}, result=None, error="boom", correlation_id=corr,
            status="error",
        ))
        await db_session.commit()

        out = json.loads(await get_trace(correlation_id=str(corr)))
        assert out["error_count"] == 2

    @pytest.mark.asyncio
    async def test_phase_mode_paginates_and_filters_to_one_phase(
        self, db_session, patched_async_sessions
    ):
        corr = uuid.uuid4()
        await _seed_full_turn(db_session, corr, tool_calls=5)
        await db_session.commit()

        page1 = json.loads(await get_trace(
            correlation_id=str(corr), mode="phase", phase="tool_calls", limit=2,
        ))
        assert page1["phase"] == "tool_calls"
        assert page1["total_in_phase"] == 5
        assert page1["cursor"] == 0
        assert page1["next_cursor"] == 2
        assert len(page1["items"]) == 2
        # Only tool_calls — no trace_events.
        assert all(it["type"] == "tool_call" for it in page1["items"])

        page2 = json.loads(await get_trace(
            correlation_id=str(corr), mode="phase", phase="tool_calls",
            cursor=page1["next_cursor"], limit=2,
        ))
        assert page2["cursor"] == 2
        assert page2["next_cursor"] == 4
        assert len(page2["items"]) == 2

        tail = json.loads(await get_trace(
            correlation_id=str(corr), mode="phase", phase="tool_calls",
            cursor=page2["next_cursor"], limit=2,
        ))
        assert tail["next_cursor"] is None
        assert len(tail["items"]) == 1

    @pytest.mark.asyncio
    async def test_phase_mode_unknown_phase_errors(
        self, db_session, patched_async_sessions
    ):
        corr = uuid.uuid4()
        await _seed_full_turn(db_session, corr)
        await db_session.commit()

        out = json.loads(await get_trace(
            correlation_id=str(corr), mode="phase", phase="not_a_phase",
        ))
        assert "error" in out

    @pytest.mark.asyncio
    async def test_full_mode_returns_legacy_timeline_shape(
        self, db_session, patched_async_sessions
    ):
        corr = uuid.uuid4()
        await _seed_full_turn(db_session, corr, tool_calls=2)
        await db_session.commit()

        out = json.loads(await get_trace(correlation_id=str(corr), mode="full"))
        # Legacy shape: timeline + counts.
        assert "timeline" in out
        assert out["tool_call_count"] == 2
        assert out["event_count"] == 2
        # Mix of tool_call + trace_event entries, four total.
        assert len(out["timeline"]) == 4

    @pytest.mark.asyncio
    async def test_invalid_mode_returns_error(
        self, db_session, patched_async_sessions
    ):
        corr = uuid.uuid4()
        await _seed_full_turn(db_session, corr)
        await db_session.commit()

        out = json.loads(await get_trace(correlation_id=str(corr), mode="bogus"))
        assert "error" in out
