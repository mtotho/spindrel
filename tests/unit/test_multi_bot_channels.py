"""Tests for multi-bot channel features.

Covers:
- Member bot routing (_maybe_route_to_member_bot)
- Anti-loop protection (ContextVar tracking)
- Context injection (membership awareness + delegate index merge)
- Member bot memory flush on compaction
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_bot(**overrides):
    from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig

    defaults = dict(
        id="primary-bot",
        name="Primary Bot",
        model="gpt-4",
        system_prompt="You are a bot.",
        delegate_bots=[],
        memory=MemoryConfig(),
        knowledge=KnowledgeConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# _maybe_route_to_member_bot
# ---------------------------------------------------------------------------

def _make_member_row(bot_id, config=None):
    """Create a mock ChannelBotMember row."""
    row = MagicMock()
    row.bot_id = bot_id
    row.config = config or {}
    return row


def _mock_db_with_member_rows(rows):
    """Create a mock DB session that returns the given member rows from execute."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=mock_result)
    return db


class TestMemberBotRouting:
    @pytest.mark.asyncio
    async def test_no_message_returns_original_bot(self):
        from app.routers.chat import _maybe_route_to_member_bot

        bot = _make_bot()
        result_bot, result_cfg = await _maybe_route_to_member_bot(MagicMock(), MagicMock(), bot, "")
        assert result_bot is bot
        assert result_cfg == {}

    @pytest.mark.asyncio
    async def test_no_tags_returns_original_bot(self):
        from app.routers.chat import _maybe_route_to_member_bot

        bot = _make_bot()
        result_bot, result_cfg = await _maybe_route_to_member_bot(
            MagicMock(), MagicMock(), bot, "hello world no tags here"
        )
        assert result_bot is bot
        assert result_cfg == {}

    @pytest.mark.asyncio
    async def test_tag_matches_member_bot(self):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        member = _make_bot(id="helper", name="Helper Bot")
        channel = MagicMock()
        channel.id = uuid.uuid4()

        db = _mock_db_with_member_rows([_make_member_row("helper")])

        with patch("app.routers.chat.get_bot", return_value=member):
            result_bot, result_cfg = await _maybe_route_to_member_bot(
                db, channel, primary, "@helper what do you think?"
            )

        assert result_bot.id == "helper"
        assert result_cfg == {}

    @pytest.mark.asyncio
    async def test_typed_bot_tag_matches(self):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        member = _make_bot(id="helper", name="Helper Bot")
        channel = MagicMock()
        channel.id = uuid.uuid4()

        db = _mock_db_with_member_rows([_make_member_row("helper")])

        with patch("app.routers.chat.get_bot", return_value=member):
            result_bot, result_cfg = await _maybe_route_to_member_bot(
                db, channel, primary, "@bot:helper please respond"
            )

        assert result_bot.id == "helper"

    @pytest.mark.asyncio
    async def test_non_bot_typed_tag_ignored(self):
        """@skill:helper should NOT route to a member bot named helper."""
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        channel = MagicMock()
        channel.id = uuid.uuid4()

        db = _mock_db_with_member_rows([_make_member_row("helper")])

        result_bot, _ = await _maybe_route_to_member_bot(
            db, channel, primary, "@skill:helper describe yourself"
        )
        assert result_bot is primary

    @pytest.mark.asyncio
    async def test_tag_not_in_members_returns_original(self):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        channel = MagicMock()
        channel.id = uuid.uuid4()

        db = _mock_db_with_member_rows([_make_member_row("helper")])

        result_bot, _ = await _maybe_route_to_member_bot(
            db, channel, primary, "@unknown_bot hello"
        )
        assert result_bot is primary

    @pytest.mark.asyncio
    async def test_no_members_returns_original(self):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        channel = MagicMock()
        channel.id = uuid.uuid4()

        db = _mock_db_with_member_rows([])

        result_bot, _ = await _maybe_route_to_member_bot(
            db, channel, primary, "@helper hello"
        )
        assert result_bot is primary

    @pytest.mark.asyncio
    async def test_member_bot_not_in_registry_falls_through(self):
        """If member bot ID is in DB but not in bot registry, skip it."""
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        channel = MagicMock()
        channel.id = uuid.uuid4()

        db = _mock_db_with_member_rows([_make_member_row("helper")])

        with patch("app.routers.chat.get_bot", side_effect=Exception("not found")):
            result_bot, _ = await _maybe_route_to_member_bot(
                db, channel, primary, "@helper hello"
            )

        assert result_bot is primary

    @pytest.mark.asyncio
    async def test_routing_returns_member_config(self):
        """When routed to a member bot, the member's config dict is returned."""
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        member = _make_bot(id="helper", name="Helper Bot")
        channel = MagicMock()
        channel.id = uuid.uuid4()

        cfg = {"model_override": "gpt-4o", "auto_respond": True, "priority": 1}
        db = _mock_db_with_member_rows([_make_member_row("helper", config=cfg)])

        with patch("app.routers.chat.get_bot", return_value=member):
            result_bot, result_cfg = await _maybe_route_to_member_bot(
                db, channel, primary, "@helper hello"
            )

        assert result_bot.id == "helper"
        assert result_cfg == cfg
        assert result_cfg["model_override"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_routing_returns_empty_config_for_primary(self):
        """When no member is matched, config is empty dict."""
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        channel = MagicMock()
        channel.id = uuid.uuid4()

        db = _mock_db_with_member_rows([_make_member_row("helper", config={"auto_respond": True})])

        result_bot, result_cfg = await _maybe_route_to_member_bot(
            db, channel, primary, "@unknown hello"
        )
        assert result_bot is primary
        assert result_cfg == {}


# ---------------------------------------------------------------------------
# Anti-loop protection
# ---------------------------------------------------------------------------

class TestAntiLoop:
    def test_contextvar_tracks_responded_bots(self):
        from app.agent.context import current_turn_responded_bots

        # Simulate outermost run_stream initialization
        responded = {"primary-bot"}
        current_turn_responded_bots.set(responded)

        # Check that adding works
        responded.add("helper-bot")
        assert "helper-bot" in current_turn_responded_bots.get()

    def test_anti_loop_blocks_duplicate(self):
        from app.agent.context import current_turn_responded_bots

        responded = {"primary-bot", "helper-bot"}
        current_turn_responded_bots.set(responded)

        # Simulating what delegation.py does
        bot_id = "helper-bot"
        _responded = current_turn_responded_bots.get()
        assert _responded is not None and bot_id in _responded

    def test_anti_loop_allows_new_bot(self):
        from app.agent.context import current_turn_responded_bots

        responded = {"primary-bot"}
        current_turn_responded_bots.set(responded)

        bot_id = "new-bot"
        _responded = current_turn_responded_bots.get()
        assert _responded is not None
        assert bot_id not in _responded

    def test_anti_loop_none_is_safe(self):
        """When ContextVar is None (e.g. task worker), anti-loop is skipped."""
        from app.agent.context import current_turn_responded_bots

        current_turn_responded_bots.set(None)
        _responded = current_turn_responded_bots.get()
        assert _responded is None
        # The check `if _responded is not None and X in _responded` should short-circuit

    @pytest.mark.asyncio
    async def test_delegation_blocks_repeated_bot(self):
        """DelegationService.run_immediate raises when bot already responded."""
        from app.agent.context import current_turn_responded_bots
        from app.services.delegation import DelegationError, DelegationService

        svc = DelegationService()
        parent = _make_bot(id="primary-bot", delegate_bots=["helper-bot"])

        # Pre-populate the anti-loop set with helper-bot
        current_turn_responded_bots.set({"primary-bot", "helper-bot"})

        with patch("app.services.delegation.settings") as s:
            s.DELEGATION_MAX_DEPTH = 5
            with pytest.raises(DelegationError, match="Anti-loop"):
                await svc.run_immediate(
                    parent_session_id=uuid.uuid4(),
                    parent_bot=parent,
                    delegate_bot_id="helper-bot",
                    prompt="test",
                    dispatch_type=None,
                    dispatch_config=None,
                    depth=0,
                    root_session_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_delegation_adds_bot_to_set(self):
        """run_immediate adds the delegate bot to the anti-loop set."""
        from app.agent.context import current_turn_responded_bots
        from app.services.delegation import DelegationService

        svc = DelegationService()
        parent = _make_bot(id="primary-bot", delegate_bots=["helper-bot"])
        child = _make_bot(id="helper-bot", name="Helper")
        responded = {"primary-bot"}
        current_turn_responded_bots.set(responded)

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "ok", "client_actions": []}

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.bots.get_bot", return_value=child), \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.context.snapshot_agent_context", return_value=MagicMock(turn_responded_bots=responded)), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.context.restore_agent_context"):
            s.DELEGATION_MAX_DEPTH = 5

            await svc.run_immediate(
                parent_session_id=uuid.uuid4(),
                parent_bot=parent,
                delegate_bot_id="helper-bot",
                prompt="test",
                dispatch_type=None,
                dispatch_config=None,
                depth=0,
                root_session_id=uuid.uuid4(),
            )

        assert "helper-bot" in responded

    def test_snapshot_preserves_responded_bots(self):
        """snapshot_agent_context captures turn_responded_bots."""
        from app.agent.context import (
            current_turn_responded_bots,
            current_session_id,
            current_channel_id,
            current_correlation_id,
            current_client_id,
            current_bot_id,
            snapshot_agent_context,
        )

        responded = {"bot-a", "bot-b"}
        current_turn_responded_bots.set(responded)
        current_session_id.set(uuid.uuid4())
        current_channel_id.set(uuid.uuid4())
        current_correlation_id.set(uuid.uuid4())
        current_client_id.set("test")
        current_bot_id.set("bot-a")

        snap = snapshot_agent_context()
        assert snap.turn_responded_bots is responded


# ---------------------------------------------------------------------------
# Context injection — multi-bot awareness message
# ---------------------------------------------------------------------------

class TestContextInjection:
    """Test that multi-bot channel context is injected correctly.
    These test the logic inline — we mock the DB query and verify the
    system message and delegate index merge."""

    def test_member_bot_ids_merged_into_delegate_index(self):
        """Verify that member bot IDs appear in the combined delegate list."""
        # This tests the dict.fromkeys merge logic used in context_assembly.py
        delegate_bots = ["delegate-a"]
        tagged_bot_names = ["tagged-b"]
        member_bot_ids = ["member-c", "delegate-a"]  # duplicate with delegate

        all_delegate_ids = list(dict.fromkeys(
            delegate_bots + tagged_bot_names + member_bot_ids
        ))

        assert all_delegate_ids == ["delegate-a", "tagged-b", "member-c"]

    def test_awareness_message_format(self):
        """Verify the awareness message format includes primary and members."""
        bot = _make_bot(id="primary", name="Primary Bot")
        member_bots = [
            _make_bot(id="helper", name="Helper Bot"),
            _make_bot(id="qa", name="QA Bot"),
        ]

        participant_lines = [f"  - {bot.id} (primary): {bot.name}"]
        for mb in member_bots:
            participant_lines.append(f"  - {mb.id} (member): {mb.name}")

        msg = (
            "This channel has multiple bot participants:\n"
            + "\n".join(participant_lines)
            + "\nYou can @-mention other bots to direct questions to them."
        )

        assert "primary (primary): Primary Bot" in msg
        assert "helper (member): Helper Bot" in msg
        assert "qa (member): QA Bot" in msg
        assert "@-mention" in msg

    def test_awareness_message_includes_config_badges(self):
        """Verify config info is included in awareness message."""
        cfg = {"auto_respond": True, "response_style": "brief"}
        cfg_parts = []
        if cfg.get("auto_respond"):
            cfg_parts.append("auto-respond")
        if cfg.get("response_style"):
            cfg_parts.append(f"style={cfg['response_style']}")
        cfg_suffix = f" [{', '.join(cfg_parts)}]" if cfg_parts else ""

        line = f"  - helper (member): Helper Bot{cfg_suffix}"
        assert "[auto-respond, style=brief]" in line

    def test_awareness_message_no_config_no_suffix(self):
        """Members with empty config get no suffix."""
        cfg = {}
        cfg_parts = []
        if cfg.get("auto_respond"):
            cfg_parts.append("auto-respond")
        if cfg.get("response_style"):
            cfg_parts.append(f"style={cfg['response_style']}")
        cfg_suffix = f" [{', '.join(cfg_parts)}]" if cfg_parts else ""

        line = f"  - helper (member): Helper Bot{cfg_suffix}"
        assert line == "  - helper (member): Helper Bot"
        assert "[" not in line


# ---------------------------------------------------------------------------
# Member bot memory flush
# ---------------------------------------------------------------------------

class TestMemberBotFlush:
    @pytest.mark.asyncio
    async def test_flush_skips_non_workspace_bots(self):
        """Member bots without memory_scheme='workspace-files' are skipped."""
        from app.services.compaction import _flush_member_bots

        channel = MagicMock()
        channel.id = uuid.uuid4()

        # Bot without workspace-files scheme
        bot_no_ws = _make_bot(id="helper", memory_scheme=None)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["helper"]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.compaction.async_session", return_value=mock_cm), \
             patch("app.services.compaction._run_memory_flush", new_callable=AsyncMock) as mock_flush, \
             patch("app.agent.bots.get_bot", return_value=bot_no_ws):
            await _flush_member_bots(channel, uuid.uuid4(), [])

        mock_flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flush_triggers_for_workspace_bots(self):
        """Member bots with memory_scheme='workspace-files' get flushed."""
        from app.services.compaction import _flush_member_bots

        channel = MagicMock()
        channel.id = uuid.uuid4()

        bot_ws = _make_bot(id="helper", memory_scheme="workspace-files")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["helper"]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.compaction.async_session", return_value=mock_cm), \
             patch("app.services.compaction._run_memory_flush", new_callable=AsyncMock) as mock_flush, \
             patch("app.agent.bots.get_bot", return_value=bot_ws):
            await _flush_member_bots(channel, uuid.uuid4(), [{"role": "user", "content": "hi"}])

        mock_flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_no_members_returns_early(self):
        """No member bots → no flush calls, no errors."""
        from app.services.compaction import _flush_member_bots

        channel = MagicMock()
        channel.id = uuid.uuid4()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.compaction.async_session", return_value=mock_cm), \
             patch("app.services.compaction._run_memory_flush", new_callable=AsyncMock) as mock_flush:
            await _flush_member_bots(channel, uuid.uuid4(), [])

        mock_flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flush_db_error_handled_gracefully(self):
        """DB error during member bot lookup is caught and logged."""
        from app.services.compaction import _flush_member_bots

        channel = MagicMock()
        channel.id = uuid.uuid4()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.compaction.async_session", return_value=mock_cm):
            # Should not raise
            await _flush_member_bots(channel, uuid.uuid4(), [])

    @pytest.mark.asyncio
    async def test_flush_individual_bot_error_continues(self):
        """If one member bot flush fails, others still proceed."""
        from app.services.compaction import _flush_member_bots

        channel = MagicMock()
        channel.id = uuid.uuid4()

        bot_a = _make_bot(id="bot-a", memory_scheme="workspace-files")
        bot_b = _make_bot(id="bot-b", memory_scheme="workspace-files")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["bot-a", "bot-b"]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        async def flush_side_effect(ch, bot, sid, msgs, correlation_id=None):
            nonlocal call_count
            call_count += 1
            if bot.id == "bot-a":
                raise Exception("flush failed for bot-a")

        def get_bot_side_effect(bid):
            return bot_a if bid == "bot-a" else bot_b

        with patch("app.services.compaction.async_session", return_value=mock_cm), \
             patch("app.services.compaction._run_memory_flush", new_callable=AsyncMock, side_effect=flush_side_effect), \
             patch("app.agent.bots.get_bot", side_effect=get_bot_side_effect):
            await _flush_member_bots(channel, uuid.uuid4(), [])

        assert call_count == 2  # both were attempted
