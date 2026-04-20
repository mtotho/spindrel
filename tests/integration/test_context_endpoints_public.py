"""Integration tests for the public channel context endpoints.

Mirrors the admin-prefixed endpoints in `api_v1_admin/channels.py` but under
`/api/v1/channels/{id}/` so bot-authenticated HTML widgets can consume them
without the `admin` scope. Covers:

- GET /api/v1/channels/{id}/context-budget
- GET /api/v1/channels/{id}/context-breakdown

And asserts parity with the admin routes where they overlap.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Session, TraceEvent


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


async def _setup_channel_with_trace(
    db_session: AsyncSession,
    *,
    budget: dict | None = None,
) -> str:
    """Insert a channel + session + optional context_injection_summary trace."""
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    db_session.add(Channel(
        id=channel_id,
        name="ctx-endpoint-test",
        bot_id="test-bot",
        active_session_id=session_id,
    ))
    db_session.add(Session(
        id=session_id,
        bot_id="test-bot",
        client_id=f"c-{channel_id.hex[:8]}",
        channel_id=channel_id,
    ))
    if budget is not None:
        db_session.add(TraceEvent(
            session_id=session_id,
            event_type="context_injection_summary",
            data={"context_budget": budget},
            created_at=now,
        ))
    await db_session.commit()
    return str(channel_id)


class TestPublicContextBudget:
    @pytest.mark.asyncio
    async def test_returns_latest_budget(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        cid = await _setup_channel_with_trace(
            db_session,
            budget={"utilization": 0.42, "consumed_tokens": 8400, "total_tokens": 20000},
        )
        resp = await client.get(
            f"/api/v1/channels/{cid}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "utilization": 0.42,
            "consumed_tokens": 8400,
            "total_tokens": 20000,
        }

    @pytest.mark.asyncio
    async def test_returns_sentinel_when_no_trace(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        cid = await _setup_channel_with_trace(db_session, budget=None)
        resp = await client.get(
            f"/api/v1/channels/{cid}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "utilization": None,
            "consumed_tokens": None,
            "total_tokens": None,
        }

    @pytest.mark.asyncio
    async def test_unknown_channel_404s(
        self, client: AsyncClient,
    ):
        fake = uuid.uuid4()
        resp = await client.get(
            f"/api/v1/channels/{fake}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_parity_with_admin_route(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """The public and admin endpoints must return identical payloads —
        drift between them is exactly what moving to a shared helper
        (`fetch_latest_context_budget`) is meant to prevent."""
        cid = await _setup_channel_with_trace(
            db_session,
            budget={"utilization": 0.1, "consumed_tokens": 2000, "total_tokens": 20000},
        )
        public = (await client.get(
            f"/api/v1/channels/{cid}/context-budget", headers=AUTH_HEADERS,
        )).json()
        admin = (await client.get(
            f"/api/v1/admin/channels/{cid}/context-budget", headers=AUTH_HEADERS,
        )).json()
        assert public == admin


class TestPublicContextBreakdown:
    @pytest.mark.asyncio
    async def test_shape_matches_expected(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        cid = await _setup_channel_with_trace(db_session, budget=None)
        resp = await client.get(
            f"/api/v1/channels/{cid}/context-breakdown",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Core fields that widgets will actually consume.
        for key in (
            "channel_id", "session_id", "bot_id",
            "categories", "total_chars", "total_tokens_approx",
            "compaction", "reranking", "context_budget", "disclaimer",
        ):
            assert key in body, f"missing key {key!r} in breakdown response"
        assert isinstance(body["categories"], list)
