"""Integration tests for context breakdown pruning estimate.

Tests the pruning savings estimate logic in compute_context_breakdown.
"""
import uuid
import json
from datetime import datetime, timezone, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Session
from app.services.context_breakdown import (
    compute_context_breakdown,
    invalidate_context_breakdown_cache,
)
from tests.integration.conftest import DEFAULT_BOT, TEST_BOT


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


@pytest.fixture(autouse=True)
def _test_bot_registry(monkeypatch):
    monkeypatch.setattr("app.agent.bots._registry", {
        "test-bot": TEST_BOT,
        "default": DEFAULT_BOT,
    })


async def _setup_channel(db_session: AsyncSession, *,
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
    invalidate_context_breakdown_cache(str(channel_id))
    return str(channel_id)


def _category(data, key: str):
    for category in data.categories:
        if category.key == key:
            return category
    raise AssertionError(f"Expected {key!r}, got: {[c.key for c in data.categories]}")


class TestPruningEstimate:
    @pytest.mark.asyncio
    async def test_estimates_savings_for_large_tool_results(
        self, db_session: AsyncSession,
    ):
        """Pruning estimate should count all tool results >= min_length."""
        cid = await _setup_channel(db_session)

        data = await compute_context_breakdown(cid, db_session)

        pruning = _category(data, "context_pruning")
        assert pruning.chars < 0
        assert "retrieval pointers" in pruning.description
        # 5 × 1000 chars minus 5 × ~120 marker ≈ 4400 savings
        assert pruning.chars <= -4000

    @pytest.mark.asyncio
    async def test_no_estimate_when_pruning_disabled(
        self, db_session: AsyncSession,
    ):
        """No pruning category when pruning is disabled."""
        cid = await _setup_channel(db_session, pruning=False)

        data = await compute_context_breakdown(cid, db_session)

        assert [c for c in data.categories if c.key == "context_pruning"] == []

    @pytest.mark.asyncio
    async def test_small_tool_results_not_counted(
        self, db_session: AsyncSession,
    ):
        """Tool results below min_content_length should not produce estimate."""
        cid = await _setup_channel(db_session, tool_result_size=50, num_turns=1)

        data = await compute_context_breakdown(cid, db_session)

        assert [c for c in data.categories if c.key == "context_pruning"] == []

    @pytest.mark.asyncio
    async def test_estimates_savings_for_large_tool_call_arguments(
        self, db_session: AsyncSession,
    ):
        """Huge assistant tool-call args should count toward forecast and pruning savings."""
        cid = await _setup_channel(
            db_session,
            tool_result_size=2,
            num_turns=1,
            tool_arg_size=5000,
        )

        data = await compute_context_breakdown(cid, db_session)

        conversation = _category(data, "conversation")
        assert conversation.chars >= 5000
        pruning = _category(data, "context_pruning")
        assert pruning.chars <= -4500
        assert "tool-call argument" in pruning.description

    @pytest.mark.asyncio
    async def test_original_trace_sized_tool_call_arguments_are_visible_and_offset(
        self, db_session: AsyncSession,
    ):
        """Regression shape for the qa-bot trace: huge args are counted and offset."""
        cid = await _setup_channel(
            db_session,
            tool_result_size=2,
            num_turns=1,
            tool_arg_size=801_000,
        )

        data = await compute_context_breakdown(cid, db_session)

        conversation = _category(data, "conversation")
        assert conversation.chars >= 801_000
        pruning = _category(data, "context_pruning")
        assert pruning.chars <= -800_000
        assert data.context_budget is not None
        assert data.context_budget["estimate"]["gross_prompt_tokens"] < 20_000

    @pytest.mark.asyncio
    async def test_admin_context_breakdown_route_serializes_pruning_estimate(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """Route smoke: the endpoint still exposes the service pruning category."""
        cid = await _setup_channel(db_session, tool_result_size=1000, num_turns=1)

        resp = await client.get(
            f"/api/v1/admin/channels/{cid}/context-breakdown",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        pruning = [c for c in data["categories"] if c["key"] == "context_pruning"][0]
        assert pruning["chars"] < 0
        assert "retrieval pointers" in pruning["description"]
