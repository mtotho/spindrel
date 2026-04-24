"""Integration tests for the `/effort` capability gate.

Pins behavior: `/effort <level>` on a channel whose primary bot runs a
non-reasoning model returns 400 with a helpful error, and `/effort off`
always succeeds (it clears state — no capability needed).
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.db.models import Bot, Channel, ProviderConfig, ProviderModel, Session
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _seed_provider_model(db_session, model_id: str, supports_reasoning: bool):
    db_session.add(
        ProviderConfig(
            id="effort-gate-provider",
            provider_type="openai-compatible",
            display_name="Effort Gate Test",
            is_enabled=True,
        )
    )
    db_session.add(
        ProviderModel(
            provider_id="effort-gate-provider",
            model_id=model_id,
            supports_reasoning=supports_reasoning,
        )
    )
    await db_session.commit()


async def _seed_bot(db_session, bot_id: str, model: str):
    db_session.add(
        Bot(
            id=bot_id,
            name=bot_id,
            model=model,
            system_prompt="",
        )
    )
    await db_session.commit()


async def _create_channel(db_session: AsyncSession, *, bot_id: str = "test-bot") -> str:
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name=f"effort-gate-{channel_id.hex[:6]}",
        bot_id=bot_id,
        active_session_id=session_id,
    ))
    db_session.add(Session(
        id=session_id,
        bot_id=bot_id,
        client_id=f"gate-{channel_id.hex[:8]}",
        channel_id=channel_id,
    ))
    await db_session.commit()
    return str(channel_id)


async def _reload_cache_from_test_db(engine):
    from app.services import providers
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch("app.services.providers.async_session", factory):
        await providers.load_providers()


class TestEffortCapabilityGate:
    async def test_high_effort_rejected_for_non_reasoning_bot(
        self, client, db_session, engine,
    ):
        await _seed_provider_model(db_session, "gpt-4o", supports_reasoning=False)
        await _seed_bot(db_session, "no-reason-bot", "gpt-4o")
        await _reload_cache_from_test_db(engine)

        channel_id = await _create_channel(db_session, bot_id="no-reason-bot")

        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": ["high"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400, resp.text
        # Helpful message names the model + points toward the fix
        body_text = resp.text.lower()
        assert "gpt-4o" in body_text or "reasoning" in body_text

        # Smoking gun: nothing was persisted
        await db_session.commit()
        refreshed = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(refreshed)
        assert "effort_override" not in (refreshed.config or {})

    async def test_high_effort_accepted_for_reasoning_bot(
        self, client, db_session, engine,
    ):
        await _seed_provider_model(
            db_session, "anthropic/claude-opus-4-7", supports_reasoning=True,
        )
        await _seed_bot(db_session, "reason-bot", "anthropic/claude-opus-4-7")
        await _reload_cache_from_test_db(engine)

        channel_id = await _create_channel(db_session, bot_id="reason-bot")

        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": ["high"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text

        await db_session.commit()
        refreshed = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(refreshed)
        assert refreshed.config.get("effort_override") == "high"

    async def test_off_always_succeeds_even_for_non_reasoning_bot(
        self, client, db_session, engine,
    ):
        await _seed_provider_model(db_session, "gpt-4o", supports_reasoning=False)
        await _seed_bot(db_session, "off-bot", "gpt-4o")
        await _reload_cache_from_test_db(engine)

        channel_id = await _create_channel(db_session, bot_id="off-bot")

        # /effort off clears state — no capability needed
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": ["off"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text

    async def test_missing_bot_row_does_not_block_persistence(
        self, client, db_session, engine,
    ):
        """Channel.bot_id pointing to a bot that isn't in the DB should not
        fall through the capability check. Acceptable: skip check, persist.
        This mirrors existing effort tests which use bot_id='test-bot' without
        a real row."""
        await _reload_cache_from_test_db(engine)

        channel_id = await _create_channel(db_session, bot_id="ghost-bot")
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": ["high"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
