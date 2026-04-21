"""Unit tests for the propose_config_change tool.

Covers per-scope allowlist enforcement, happy-path PATCH, and evidence validation.
Uses the real SQLite-in-memory DB via the shared `db_session` fixture so we
exercise the actual setattr / JSONB merge paths rather than mocks.
"""
import json
import uuid
from unittest.mock import patch

import pytest

from app.db.models import Bot, Channel
from app.tools.local.propose_config_change import propose_config_change


def _valid_evidence() -> list[dict]:
    return [
        {"correlation_id": "11111111-1111-1111-1111-111111111111", "signal": "threshold=0.5 missed 3/5 queries"},
        {"correlation_id": "22222222-2222-2222-2222-222222222222", "signal": "bot never called tool X in 10 turns"},
    ]


@pytest.fixture
def _patch_async_session(db_session):
    """Patch `async_session` inside the tool so it uses the fixture's session."""
    class _Ctx:
        async def __aenter__(self_inner):
            return db_session
        async def __aexit__(self_inner, *exc):
            # Don't close — the fixture owns the lifetime.
            return False

    with patch("app.db.engine.async_session", lambda: _Ctx()):
        yield


@pytest.fixture
async def _seed_bot(db_session):
    bot = Bot(
        id="testbot",
        name="Test Bot",
        model="gpt-4o",
        system_prompt="You are a test.",
        tool_similarity_threshold=0.5,
    )
    db_session.add(bot)
    await db_session.commit()
    return bot


@pytest.fixture
async def _seed_channel(db_session):
    ch = Channel(
        id=uuid.uuid4(),
        name="Test Channel",
        bot_id="testbot",
        client_id="test-channel",
        config={"pipeline_mode": "auto"},
    )
    db_session.add(ch)
    await db_session.commit()
    return ch


# --------------------------------------------------------------------------
# Evidence validation
# --------------------------------------------------------------------------

class TestEvidenceValidation:
    @pytest.mark.asyncio
    async def test_empty_evidence_refuses(self):
        result = json.loads(await propose_config_change(
            scope="bot",
            target_id="any",
            field="tool_similarity_threshold",
            new_value=0.3,
            rationale="because",
            evidence=[],
            diff_preview="0.5 → 0.3",
        ))
        assert result["applied"] is False
        assert "evidence" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_evidence_missing_signal_refuses(self):
        result = json.loads(await propose_config_change(
            scope="bot",
            target_id="any",
            field="tool_similarity_threshold",
            new_value=0.3,
            rationale="r",
            evidence=[{"correlation_id": "x"}],
            diff_preview="d",
        ))
        assert result["applied"] is False
        assert "signal" in result["error"].lower()


# --------------------------------------------------------------------------
# Bot scope
# --------------------------------------------------------------------------

class TestBotScope:
    @pytest.mark.asyncio
    async def test_allowlist_rejects_unknown_field(self):
        result = json.loads(await propose_config_change(
            scope="bot",
            target_id="testbot",
            field="api_permissions",  # NOT in _BOT_ALLOWED
            new_value=["bots:write"],
            rationale="grant write",
            evidence=_valid_evidence(),
            diff_preview="none → write",
        ))
        assert result["applied"] is False
        assert "allowlist" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_threshold_out_of_range_refuses(self, _patch_async_session, _seed_bot):
        result = json.loads(await propose_config_change(
            scope="bot",
            target_id="testbot",
            field="tool_similarity_threshold",
            new_value=1.5,
            rationale="r",
            evidence=_valid_evidence(),
            diff_preview="0.5 → 1.5",
        ))
        assert result["applied"] is False
        assert "0.0" in result["error"] or "1.0" in result["error"]

    @pytest.mark.asyncio
    async def test_happy_path_patches_threshold(
        self, _patch_async_session, _seed_bot, db_session,
    ):
        with patch("app.agent.bots.reload_bots", return_value=None):
            result = json.loads(await propose_config_change(
                scope="bot",
                target_id="testbot",
                field="tool_similarity_threshold",
                new_value=0.25,
                rationale="lower threshold so tool X is reachable",
                evidence=_valid_evidence(),
                diff_preview="0.5 → 0.25",
            ))

        assert result["applied"] is True
        assert result["before"] == 0.5
        assert result["after"] == 0.25

        # Verify the DB row actually changed
        await db_session.refresh(_seed_bot)
        assert _seed_bot.tool_similarity_threshold == 0.25

    @pytest.mark.asyncio
    async def test_missing_bot_refuses(self, _patch_async_session):
        result = json.loads(await propose_config_change(
            scope="bot",
            target_id="does-not-exist",
            field="tool_similarity_threshold",
            new_value=0.3,
            rationale="r",
            evidence=_valid_evidence(),
            diff_preview="d",
        ))
        assert result["applied"] is False
        assert "not found" in result["error"].lower()


# --------------------------------------------------------------------------
# Channel scope
# --------------------------------------------------------------------------

class TestChannelScope:
    @pytest.mark.asyncio
    async def test_allowlist_rejects_unknown_toplevel(self):
        result = json.loads(await propose_config_change(
            scope="channel",
            target_id=str(uuid.uuid4()),
            field="arbitrary_field",
            new_value="x",
            rationale="r",
            evidence=_valid_evidence(),
            diff_preview="d",
        ))
        assert result["applied"] is False
        assert "allowlist" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_pipeline_mode_value_refuses(self, _patch_async_session, _seed_channel):
        result = json.loads(await propose_config_change(
            scope="channel",
            target_id=str(_seed_channel.id),
            field="pipeline_mode",
            new_value="rampaging",  # NOT in {auto, on, off}
            rationale="r",
            evidence=_valid_evidence(),
            diff_preview="auto → rampaging",
        ))
        assert result["applied"] is False
        assert "auto" in result["error"] or "on" in result["error"]

    @pytest.mark.asyncio
    async def test_happy_path_patches_pipeline_mode(
        self, _patch_async_session, _seed_channel, db_session,
    ):
        result = json.loads(await propose_config_change(
            scope="channel",
            target_id=str(_seed_channel.id),
            field="pipeline_mode",
            new_value="off",
            rationale="quiet this channel",
            evidence=_valid_evidence(),
            diff_preview="auto → off",
        ))

        assert result["applied"] is True
        await db_session.refresh(_seed_channel)
        assert _seed_channel.config.get("pipeline_mode") == "off"

    @pytest.mark.asyncio
    async def test_resolve_by_client_id(
        self, _patch_async_session, _seed_channel, db_session,
    ):
        result = json.loads(await propose_config_change(
            scope="channel",
            target_id="test-channel",
            field="layout_mode",
            new_value="rail-chat",
            rationale="simplify layout",
            evidence=_valid_evidence(),
            diff_preview="full → rail-chat",
        ))

        assert result["applied"] is True
        await db_session.refresh(_seed_channel)
        assert _seed_channel.config.get("layout_mode") == "rail-chat"

    @pytest.mark.asyncio
    async def test_happy_path_patches_chat_mode(
        self, _patch_async_session, _seed_channel, db_session,
    ):
        result = json.loads(await propose_config_change(
            scope="channel",
            target_id=str(_seed_channel.id),
            field="chat_mode",
            new_value="terminal",
            rationale="use command-first chat ui",
            evidence=_valid_evidence(),
            diff_preview="default → terminal",
        ))

        assert result["applied"] is True
        await db_session.refresh(_seed_channel)
        assert _seed_channel.config.get("chat_mode") == "terminal"

    @pytest.mark.asyncio
    async def test_config_key_allowlist_enforced(
        self, _patch_async_session, _seed_channel,
    ):
        result = json.loads(await propose_config_change(
            scope="channel",
            target_id=str(_seed_channel.id),
            field="config.secret_key",  # NOT in _CHANNEL_ALLOWED_CONFIG
            new_value="x",
            rationale="r",
            evidence=_valid_evidence(),
            diff_preview="d",
        ))
        assert result["applied"] is False
        assert "allowlist" in result["error"].lower()


# --------------------------------------------------------------------------
# Integration scope
# --------------------------------------------------------------------------

class TestIntegrationScope:
    @pytest.mark.asyncio
    async def test_enabled_toggle_applies(self):
        with patch("app.services.integration_settings.set_status", return_value=None) as mock_set:
            with patch("app.services.integration_settings.get_status", return_value="available"):
                result = json.loads(await propose_config_change(
                    scope="integration",
                    target_id="frigate",
                    field="enabled",
                    new_value=True,
                    rationale="turn on",
                    evidence=_valid_evidence(),
                    diff_preview="off → on",
                ))
        assert result["applied"] is True
        assert mock_set.call_args.args == ("frigate", "enabled")

    @pytest.mark.asyncio
    async def test_unknown_field_refused(self):
        result = json.loads(await propose_config_change(
            scope="integration",
            target_id="frigate",
            field="random_thing",
            new_value="x",
            rationale="r",
            evidence=_valid_evidence(),
            diff_preview="d",
        ))
        assert result["applied"] is False
        assert "enabled" in result["error"].lower() or "config" in result["error"].lower()


# --------------------------------------------------------------------------
# Unknown scope
# --------------------------------------------------------------------------

class TestUnknownScope:
    @pytest.mark.asyncio
    async def test_refuses_unknown_scope(self):
        result = json.loads(await propose_config_change(
            scope="mystery",
            target_id="x",
            field="y",
            new_value="z",
            rationale="r",
            evidence=_valid_evidence(),
            diff_preview="d",
        ))
        assert result["applied"] is False
        assert "scope" in result["error"].lower()
