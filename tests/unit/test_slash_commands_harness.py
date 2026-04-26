"""Slash-command harness branches.

Pins the Phase 4 contract:

- harness ``/effort low`` does NOT mutate ``channel.config['effort_override']``
  (test gate from the v2 plan review)
- harness ``/model X`` writes per-session ``harness_settings.model``
- non-harness ``/model X`` writes ``channel.model_override``
- harness ``/help`` lists only the runtime-allowlisted commands
- catalog endpoint with ``?bot_id=`` returns the intersected list
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Bot as BotRow, Channel as ChannelRow, Session as SessionRow
from app.services.agent_harnesses import HARNESS_REGISTRY, register_runtime, unregister_runtime
from app.services.agent_harnesses.base import (
    HarnessSlashCommandPolicy,
    RuntimeCapabilities,
)
from app.services.agent_harnesses.settings import (
    HARNESS_SETTINGS_KEY,
    load_session_settings,
)
from app.services.slash_commands import (
    execute_slash_command,
    list_supported_slash_commands,
)
from tests.factories import build_bot, build_channel

pytestmark = pytest.mark.asyncio

_RUNTIME_NAME = "test-harness-phase4"


class _StubRuntime:
    """A harness runtime with a tiny allowlist + no effort knob."""

    name = _RUNTIME_NAME

    def readonly_tools(self):
        return frozenset()

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        return True

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        return False

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            display_name="Test Harness",
            supported_models=(),
            model_is_freeform=True,
            effort_values=(),  # No effort — friendly no-op path
            slash_policy=HarnessSlashCommandPolicy(
                allowed_command_ids=frozenset({"help", "stop", "rename"}),
            ),
        )


@pytest.fixture(autouse=True)
def _register_stub_runtime():
    register_runtime(_RUNTIME_NAME, _StubRuntime())
    yield
    unregister_runtime(_RUNTIME_NAME)


async def _make_harness_setup(db_session):
    bot = build_bot(id="harness-slash-bot", name="HS Bot", model="x")
    bot.harness_runtime = _RUNTIME_NAME
    db_session.add(bot)
    channel = build_channel(bot_id=bot.id)
    db_session.add(channel)
    session = SessionRow(
        id=uuid.uuid4(),
        client_id="hs-client",
        bot_id=bot.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.commit()
    return bot, channel, session


async def _make_normal_setup(db_session):
    bot = build_bot(id="normal-bot", name="Normal Bot", model="x")
    db_session.add(bot)
    channel = build_channel(bot_id=bot.id)
    db_session.add(channel)
    session = SessionRow(
        id=uuid.uuid4(),
        client_id="norm-client",
        bot_id=bot.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.commit()
    return bot, channel, session


# ---------------------------------------------------------------------------
# /effort — harness with no effort_values must NOT touch channel.config
# ---------------------------------------------------------------------------


async def test_harness_effort_does_not_mutate_channel_config(db_session):
    """v2 review test gate: friendly no-op never writes effort_override."""
    bot, channel, session = await _make_harness_setup(db_session)
    initial_config = dict(channel.config or {})

    result = await execute_slash_command(
        command_id="effort",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["low"],
    )

    assert result.command_id == "effort"
    # Friendly no-op message — runtime declares no effort knob.
    assert "does not expose" in result.payload["detail"].lower()
    # Critical: channel.config must be unchanged.
    await db_session.refresh(channel)
    assert (channel.config or {}) == initial_config
    assert "effort_override" not in (channel.config or {})


# ---------------------------------------------------------------------------
# /model — harness writes harness_settings; non-harness writes channel
# ---------------------------------------------------------------------------


async def test_harness_model_writes_harness_settings(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="model",
        channel_id=None,
        session_id=session.id,
        db=db_session,
        args=["claude-sonnet-4-6"],
    )
    assert result.command_id == "model"

    fresh = await load_session_settings(db_session, session.id)
    assert fresh.model == "claude-sonnet-4-6"
    # Channel override must NOT be touched for harness bots.
    await db_session.refresh(channel)
    assert channel.model_override is None


async def test_normal_model_writes_channel_override(db_session):
    bot, channel, session = await _make_normal_setup(db_session)

    result = await execute_slash_command(
        command_id="model",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["gpt-4o"],
    )
    assert result.command_id == "model"

    await db_session.refresh(channel)
    assert channel.model_override == "gpt-4o"
    # Harness settings must NOT be touched for non-harness bots.
    fresh = await load_session_settings(db_session, session.id)
    assert fresh.model is None


async def test_harness_model_rejects_oversized(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    with pytest.raises(ValueError, match="exceeds"):
        await execute_slash_command(
            command_id="model",
            channel_id=None,
            session_id=session.id,
            db=db_session,
            args=["x" * 257],
        )


# ---------------------------------------------------------------------------
# /help filtered by runtime allowlist
# ---------------------------------------------------------------------------


async def test_harness_help_lists_only_allowed_commands(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="help",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=[],
    )
    labels = {c["label"] for c in result.payload["top_categories"]}
    # Allowlist for stub: {help, stop, rename}
    assert labels == {"/help", "/stop", "/rename"}


async def test_normal_help_lists_full_surface(db_session):
    bot, channel, session = await _make_normal_setup(db_session)

    result = await execute_slash_command(
        command_id="help",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=[],
    )
    labels = {c["label"] for c in result.payload["top_categories"]}
    # Spot-check that several non-allowlisted commands appear for a normal bot.
    assert "/find" in labels
    assert "/effort" in labels
    assert "/compact" in labels


# ---------------------------------------------------------------------------
# Catalog endpoint with bot_id intersects
# ---------------------------------------------------------------------------


async def test_catalog_with_bot_id_intersects(db_session):
    bot, _channel, _session = await _make_harness_setup(db_session)

    catalog = await list_supported_slash_commands(db=db_session, bot_id=bot.id)
    ids = {c["id"] for c in catalog}
    assert ids == {"help", "stop", "rename"}


async def test_catalog_without_bot_id_returns_full(db_session):
    catalog = await list_supported_slash_commands()
    ids = {c["id"] for c in catalog}
    # Sanity: full catalog has more than the stub allowlist.
    assert len(ids) > 3
    assert {"help", "stop", "rename", "find", "effort"} <= ids
