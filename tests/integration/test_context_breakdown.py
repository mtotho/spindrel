"""Integration tests for context breakdown pruning estimate.

Tests the pruning savings estimate logic in compute_context_breakdown.
Uses the HTTP client fixture to bypass SQLite/UUID compat issues.
"""
import uuid
import json
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Session


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


async def _setup_channel(client: AsyncClient, db_session: AsyncSession, *,
                          tool_result_size: int = 1000, num_turns: int = 5,
                          pruning: bool = True, tool_arg_size: int = 0) -> str:
    """Create channel via internal DB, insert tool messages, return channel_id."""
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    db_session.add(Channel(
        id=channel_id, name="test-pruning", bot_id="test-bot",
        active_session_id=session_id, context_pruning=pruning,
    ))
    db_session.add(Session(
        id=session_id, bot_id="test-bot",
        client_id=f"c-{channel_id.hex[:8]}", channel_id=channel_id,
    ))
    for turn in range(num_turns):
        t = now + timedelta(seconds=turn * 10)
        db_session.add(Message(session_id=session_id, role="user",
                               content=f"q{turn}", created_at=t))
        db_session.add(Message(session_id=session_id, role="assistant", content="",
                               tool_calls=[{"id": f"tc{turn}", "type": "function",
                                            "function": {
                                                "name": f"tool_{turn}",
                                                "arguments": json.dumps({"payload": "x" * tool_arg_size}) if tool_arg_size else "{}",
                                            }}],
                               created_at=t + timedelta(seconds=1)))
        db_session.add(Message(session_id=session_id, role="tool",
                               content="x" * tool_result_size, tool_call_id=f"tc{turn}",
                               created_at=t + timedelta(seconds=2)))
        db_session.add(Message(session_id=session_id, role="assistant",
                               content=f"a{turn}", created_at=t + timedelta(seconds=3)))
    await db_session.commit()
    return str(channel_id)


class TestPruningEstimate:
    @pytest.mark.asyncio
    async def test_estimates_savings_for_large_tool_results(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """Pruning estimate should count all tool results >= min_length."""
        cid = await _setup_channel(client, db_session)

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        pruning_cats = [c for c in data["categories"] if c["key"] == "context_pruning"]
        assert len(pruning_cats) == 1, f"Expected context_pruning, got: {[c['key'] for c in data['categories']]}"

        pruning = pruning_cats[0]
        assert pruning["chars"] < 0
        assert "retrieval pointers" in pruning["description"]
        # 5 × 1000 chars minus 5 × ~120 marker ≈ 4400 savings
        assert pruning["chars"] <= -4000

    @pytest.mark.asyncio
    async def test_no_estimate_when_pruning_disabled(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """No pruning category when pruning is disabled."""
        cid = await _setup_channel(client, db_session, pruning=False)

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        pruning_cats = [c for c in resp.json()["categories"] if c["key"] == "context_pruning"]
        assert len(pruning_cats) == 0

    @pytest.mark.asyncio
    async def test_small_tool_results_not_counted(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """Tool results below min_content_length should not produce estimate."""
        cid = await _setup_channel(client, db_session, tool_result_size=50, num_turns=1)

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        pruning_cats = [c for c in resp.json()["categories"] if c["key"] == "context_pruning"]
        assert len(pruning_cats) == 0

    @pytest.mark.asyncio
    async def test_estimates_savings_for_large_tool_call_arguments(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """Huge assistant tool-call args should count toward forecast and pruning savings."""
        cid = await _setup_channel(
            client, db_session,
            tool_result_size=2,
            num_turns=1,
            tool_arg_size=5000,
        )

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        conversation = [c for c in data["categories"] if c["key"] == "conversation"][0]
        assert conversation["chars"] >= 5000
        pruning = [c for c in data["categories"] if c["key"] == "context_pruning"][0]
        assert pruning["chars"] <= -4500
        assert "tool-call argument" in pruning["description"]
