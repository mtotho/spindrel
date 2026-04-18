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

from app.db.models import Message, Session, TraceEvent
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
