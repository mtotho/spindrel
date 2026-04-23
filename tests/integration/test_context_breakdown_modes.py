"""Integration tests for the ``mode`` parameter on context-breakdown.

The two modes answer different questions:

- ``last_turn`` reads the API-reported ``prompt_tokens`` from the most recent
  ``token_usage`` trace event. This is what the chat header shows.
- ``next_turn`` is a forecast over the channel's static configuration.

These tests pin both behaviors so the header and dev panel can't silently
drift apart again.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Session, TraceEvent


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


async def _seed_channel_with_token_usage(
    db_session: AsyncSession,
    *,
    api_prompt_tokens: int,
    estimate_consumed: int = 999,
    estimate_total: int = 200_000,
) -> str:
    """Create a channel + session and write the two trace events the
    breakdown service joins on."""
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    db_session.add(Channel(
        id=channel_id, name="ctx-mode-test", bot_id="test-bot",
        active_session_id=session_id,
    ))
    db_session.add(Session(
        id=session_id, bot_id="test-bot",
        client_id=f"c-{channel_id.hex[:8]}", channel_id=channel_id,
    ))

    # Earlier event: pre-call estimate (carries `total_tokens` for the budget block).
    db_session.add(TraceEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        bot_id="test-bot",
        event_type="context_injection_summary",
        data={
            "breakdown": {"system_prompt": 1000, "memory": 500},
            "total_chars": 1500,
            "context_profile": "chat",
            "context_origin": "task",
            "context_policy": {
                "live_history_turns": 4,
                "mandatory_static_injections": ["plan_artifact", "section_index"],
                "optional_static_injections": ["tool_index"],
            },
            "context_budget": {
                "consumed_tokens": estimate_consumed,
                "total_tokens": estimate_total,
                "utilization": round(estimate_consumed / estimate_total, 3),
            },
        },
        created_at=now,
    ))
    # Later event: API-reported usage (the truth).
    db_session.add(TraceEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        bot_id="test-bot",
        event_type="token_usage",
        data={
            "prompt_tokens": api_prompt_tokens,
            "gross_prompt_tokens": api_prompt_tokens,
            "current_prompt_tokens": api_prompt_tokens - 100,
            "cached_prompt_tokens": 100,
            "completion_tokens": 42,
            "total_tokens": api_prompt_tokens + 42,
        },
        created_at=now,
    ))
    await db_session.commit()
    return str(channel_id)


async def _seed_compacted_channel_with_stale_usage(
    db_session: AsyncSession,
    *,
    stale_prompt_tokens: int,
    estimate_total: int = 200_000,
) -> str:
    """Create a channel whose latest token_usage predates a completed compaction.

    The session summary/watermark reflect the current compacted state, so any
    older API usage snapshot is no longer representative of the live context.
    """
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    trace_at = now - timedelta(minutes=2)
    watermark_at = now - timedelta(minutes=1)
    compaction_at = now

    db_session.add(Channel(
        id=channel_id, name="ctx-compact-stale", bot_id="test-bot",
        active_session_id=session_id,
    ))
    session = Session(
        id=session_id,
        bot_id="test-bot",
        client_id=f"c-{channel_id.hex[:8]}",
        channel_id=channel_id,
        summary="Compacted summary of earlier work.",
    )
    db_session.add(session)

    watermark = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role="assistant",
        content="Older assistant reply before compaction",
        created_at=watermark_at,
    )
    db_session.add(watermark)
    await db_session.flush()
    session.summary_message_id = watermark.id

    db_session.add(TraceEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        bot_id="test-bot",
        event_type="context_injection_summary",
        data={
            "context_profile": "chat",
            "context_origin": "chat",
            "context_policy": {"live_history_turns": 6},
            "context_budget": {
                "consumed_tokens": stale_prompt_tokens,
                "total_tokens": estimate_total,
                "utilization": round(stale_prompt_tokens / estimate_total, 3),
            },
        },
        created_at=trace_at,
    ))
    db_session.add(TraceEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        bot_id="test-bot",
        event_type="token_usage",
        data={
            "prompt_tokens": stale_prompt_tokens,
            "gross_prompt_tokens": stale_prompt_tokens,
            "current_prompt_tokens": stale_prompt_tokens - 100,
            "cached_prompt_tokens": 100,
            "completion_tokens": 42,
            "total_tokens": stale_prompt_tokens + 42,
        },
        created_at=trace_at,
    ))
    db_session.add(TraceEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        bot_id="test-bot",
        event_type="compaction_done",
        data={"title": "Context compacted", "summary_len": len(session.summary or "")},
        created_at=compaction_at,
    ))
    await db_session.commit()
    return str(channel_id)


class TestBreakdownModes:
    @pytest.mark.asyncio
    async def test_last_turn_total_matches_api_prompt_tokens(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """In last_turn mode, total_tokens_approx == API prompt_tokens.

        This is the invariant that keeps the dev-panel total in lockstep
        with the chat-header value.
        """
        cid = await _seed_channel_with_token_usage(
            db_session, api_prompt_tokens=12345, estimate_consumed=8000,
        )

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown?mode=last_turn",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "last_turn"
        assert data["total_tokens_approx"] == 12345
        assert data["context_profile"] == "chat"
        assert data["context_budget"]["usage"]["gross_prompt_tokens"] == 12345
        assert data["context_budget"]["usage"]["current_prompt_tokens"] == 12245
        assert data["context_budget"]["usage"]["cached_prompt_tokens"] == 100
        assert data["context_origin"] == "task"
        assert data["live_history_turns"] == 4
        assert data["mandatory_static_injections"] == ["plan_artifact", "section_index"]

    @pytest.mark.asyncio
    async def test_next_turn_total_uses_forecast_not_api(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """next_turn forecasts from current state — independent of the API count."""
        cid = await _seed_channel_with_token_usage(
            db_session, api_prompt_tokens=12345,
        )

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown?mode=next_turn",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "next_turn"
        # Forecast comes from summing categories, not from the API event.
        assert data["total_tokens_approx"] != 12345

    @pytest.mark.asyncio
    async def test_invalid_mode_is_422(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        cid = await _seed_channel_with_token_usage(
            db_session, api_prompt_tokens=100,
        )
        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown?mode=bogus",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_context_budget_endpoint_prefers_api_usage(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """The header endpoint must source from token_usage, not the estimate."""
        cid = await _seed_channel_with_token_usage(
            db_session, api_prompt_tokens=54321, estimate_consumed=999,
        )

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["consumed_tokens"] == 54321
        assert data["gross_prompt_tokens"] == 54321
        assert data["current_prompt_tokens"] == 54221
        assert data["cached_prompt_tokens"] == 100
        assert data["completion_tokens"] == 42
        assert data["context_profile"] == "chat"
        assert data["context_origin"] == "task"
        assert data["live_history_turns"] == 4
        assert data["source"] == "api"

    @pytest.mark.asyncio
    async def test_context_budget_falls_back_when_no_api_usage(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """No token_usage event yet → fall back to the estimate."""
        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        db_session.add(Channel(
            id=channel_id, name="ctx-fallback", bot_id="test-bot",
            active_session_id=session_id,
        ))
        db_session.add(Session(
            id=session_id, bot_id="test-bot",
            client_id=f"c-{channel_id.hex[:8]}", channel_id=channel_id,
        ))
        db_session.add(TraceEvent(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id="test-bot",
            event_type="context_injection_summary",
            data={"context_budget": {
                "consumed_tokens": 777, "total_tokens": 200_000, "utilization": 0.004,
            }, "context_profile": "planning"},
            created_at=now,
        ))
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/admin/channels/{channel_id}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["consumed_tokens"] == 777
        assert data["gross_prompt_tokens"] == 777
        assert data["current_prompt_tokens"] == 777
        assert data["cached_prompt_tokens"] is None
        assert data["context_profile"] == "planning"
        assert data["source"] == "estimate"

    @pytest.mark.asyncio
    async def test_context_budget_ignores_stale_api_usage_after_compaction(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """A compaction invalidates older token_usage snapshots until a newer turn lands."""
        cid = await _seed_compacted_channel_with_stale_usage(
            db_session, stale_prompt_tokens=54_321,
        )

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "estimate"
        assert data["consumed_tokens"] != 54_321
        assert data["gross_prompt_tokens"] == data["consumed_tokens"]
        assert data["current_prompt_tokens"] == data["consumed_tokens"]
        assert data["cached_prompt_tokens"] is None
        assert data["completion_tokens"] is None
        assert data["context_profile"] == "chat"

    @pytest.mark.asyncio
    async def test_context_budget_can_scope_to_specific_session(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """Scratch/session UIs need the selected session's budget, not the
        newest budget across the whole channel."""
        channel_id = uuid.uuid4()
        older_session_id = uuid.uuid4()
        newer_session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        older_at = now.replace(microsecond=1000)
        newer_at = now.replace(microsecond=2000)

        db_session.add(Channel(
            id=channel_id, name="ctx-session-scope", bot_id="test-bot",
            active_session_id=newer_session_id,
        ))
        db_session.add_all([
            Session(
                id=older_session_id, bot_id="test-bot",
                client_id=f"c-{channel_id.hex[:8]}-old", channel_id=channel_id,
            ),
            Session(
                id=newer_session_id, bot_id="test-bot",
                client_id=f"c-{channel_id.hex[:8]}-new", channel_id=channel_id,
            ),
        ])
        db_session.add_all([
            TraceEvent(
                id=uuid.uuid4(),
                session_id=older_session_id,
                bot_id="test-bot",
                event_type="context_injection_summary",
                data={"context_budget": {
                    "consumed_tokens": 111, "total_tokens": 10_000, "utilization": 0.011,
                }},
                created_at=older_at,
            ),
            TraceEvent(
                id=uuid.uuid4(),
                session_id=newer_session_id,
                bot_id="test-bot",
                event_type="context_injection_summary",
                data={"context_budget": {
                    "consumed_tokens": 999, "total_tokens": 10_000, "utilization": 0.099,
                }},
                created_at=newer_at,
            ),
        ])
        await db_session.commit()

        default_resp = await client.get(
            f"/api/v1/admin/channels/{channel_id}/context-budget",
            headers=AUTH_HEADERS,
        )
        scoped_resp = await client.get(
            f"/api/v1/admin/channels/{channel_id}/context-budget?session_id={older_session_id}",
            headers=AUTH_HEADERS,
        )

        assert default_resp.status_code == 200
        assert scoped_resp.status_code == 200
        assert default_resp.json()["consumed_tokens"] == 999
        assert scoped_resp.json()["consumed_tokens"] == 111

    @pytest.mark.asyncio
    async def test_last_turn_total_falls_back_to_forecast_after_compaction(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """last_turn mode should stop advertising pre-compaction API usage."""
        cid = await _seed_compacted_channel_with_stale_usage(
            db_session, stale_prompt_tokens=54_321,
        )

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown?mode=last_turn",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "last_turn"
        assert data["total_tokens_approx"] != 54_321
        assert data["context_budget"]["usage"]["source"] == "estimate"
        assert data["context_budget"]["usage"]["gross_prompt_tokens"] == data["total_tokens_approx"]
