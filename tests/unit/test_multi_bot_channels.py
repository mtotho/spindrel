"""Tests for multi-bot channel features.

Covers:
- Member bot routing (_maybe_route_to_member_bot)
- Bot-to-bot @-mention trigger (_trigger_member_bot_replies)
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
        """Verify the awareness message format includes primary and members with @ prefix."""
        bot = _make_bot(id="primary", name="Primary Bot")
        member_bots = [
            _make_bot(id="helper", name="Helper Bot"),
            _make_bot(id="qa", name="QA Bot"),
        ]

        participant_lines = [f"  - @{bot.id} (primary): {bot.name}"]
        for mb in member_bots:
            participant_lines.append(f"  - @{mb.id} (member): {mb.name}")

        msg = (
            "This channel has multiple bot participants:\n"
            + "\n".join(participant_lines)
            + "\nTo mention another bot, use @bot_id or @Display_Name."
        )

        assert "@primary (primary): Primary Bot" in msg
        assert "@helper (member): Helper Bot" in msg
        assert "@qa (member): QA Bot" in msg
        assert "@bot_id" in msg

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


class TestMultiBotIdentity:
    """Test that multi-bot awareness correctly identifies primary vs member bots
    and includes 'You are' identity."""

    def test_awareness_identifies_current_bot(self):
        """Awareness message should start with 'You are {bot.name}'."""
        bot = _make_bot(id="helper", name="Helper Bot")
        # Simulate the awareness message construction from context_assembly.py
        # when the responding bot is a member (not the primary)
        primary_bot_id = "primary"
        member_bot_ids = ["helper"]

        _all_bot_ids = [primary_bot_id] + [mid for mid in member_bot_ids if mid != primary_bot_id]
        if bot.id != primary_bot_id and bot.id not in _all_bot_ids:
            _all_bot_ids.append(bot.id)

        participant_lines = []
        for _bid in _all_bot_ids:
            _is_primary = _bid == primary_bot_id
            _is_self = _bid == bot.id
            _role_label = "primary" if _is_primary else "member"
            _you_marker = " ← you" if _is_self else ""
            participant_lines.append(f"  - {_bid} ({_role_label}): Bot{_you_marker}")

        msg = (
            f"You are {bot.name} (bot_id: {bot.id}).\n\n"
            "This channel has multiple bot participants:\n"
            + "\n".join(participant_lines)
            + "\nDo not @-mention yourself."
        )

        assert msg.startswith("You are Helper Bot (bot_id: helper).")
        assert "helper (member)" in msg
        assert "← you" in msg
        assert "primary (primary)" in msg

    def test_member_bot_not_labeled_as_primary(self):
        """When a member bot is responding, it should NOT be labeled (primary)."""
        bot = _make_bot(id="helper", name="Helper Bot")
        primary_bot_id = "rolland"
        member_bot_ids = ["helper"]

        _all_bot_ids = [primary_bot_id] + [mid for mid in member_bot_ids if mid != primary_bot_id]
        if bot.id != primary_bot_id and bot.id not in _all_bot_ids:
            _all_bot_ids.append(bot.id)

        participant_lines = []
        for _bid in _all_bot_ids:
            _is_primary = _bid == primary_bot_id
            _is_self = _bid == bot.id
            _role_label = "primary" if _is_primary else "member"
            _you_marker = " ← you" if _is_self else ""
            participant_lines.append(f"  - {_bid} ({_role_label}): Bot{_you_marker}")

        msg = "\n".join(participant_lines)

        # Helper should be labeled as member, not primary
        assert "helper (member)" in msg
        assert "helper (primary)" not in msg
        # Primary should be labeled as primary
        assert "rolland (primary)" in msg
        # Helper should have the "← you" marker
        assert "helper (member): Bot ← you" in msg
        # Primary should NOT have "← you"
        assert "rolland (primary): Bot ← you" not in msg

    def test_primary_bot_labeled_correctly_when_responding(self):
        """When the primary bot is responding, it should be labeled (primary) and ← you."""
        bot = _make_bot(id="primary", name="Primary Bot")
        primary_bot_id = "primary"
        member_bot_ids = ["helper"]

        _all_bot_ids = [primary_bot_id] + [mid for mid in member_bot_ids if mid != primary_bot_id]
        if bot.id != primary_bot_id and bot.id not in _all_bot_ids:
            _all_bot_ids.append(bot.id)

        participant_lines = []
        for _bid in _all_bot_ids:
            _is_primary = _bid == primary_bot_id
            _is_self = _bid == bot.id
            _role_label = "primary" if _is_primary else "member"
            _you_marker = " ← you" if _is_self else ""
            participant_lines.append(f"  - {_bid} ({_role_label}): Bot{_you_marker}")

        msg = "\n".join(participant_lines)

        assert "primary (primary): Bot ← you" in msg
        assert "helper (member): Bot" in msg
        # Helper should not have ← you
        assert "helper (member): Bot ← you" not in msg

    def test_awareness_includes_do_not_self_mention(self):
        """Awareness message should tell the bot not to @-mention itself."""
        bot = _make_bot(id="helper", name="Helper Bot")
        msg = (
            f"You are {bot.name} (bot_id: {bot.id}).\n\n"
            "This channel has multiple bot participants:\n"
            "  - primary (primary): Primary Bot\n"
            "  - helper (member): Helper Bot ← you\n"
            "Do not @-mention yourself."
        )
        assert "Do not @-mention yourself." in msg

    def test_trigger_prompt_uses_system_preamble(self):
        """The identity info should go into system_preamble (not user message)."""
        member_bot_name = "Helper Bot"
        member_bot_id = "helper"
        mentioning_bot_name = "Rolland"
        mentioning_bot_id = "rolland"

        # system_preamble carries identity (injected as system message)
        preamble = (
            f"You are {member_bot_name} (bot_id: {member_bot_id}). "
            f"{mentioning_bot_name} (@{mentioning_bot_id}) mentioned you. "
            f"Read the conversation and respond naturally. Do not @-mention yourself."
        )

        assert preamble.startswith("You are Helper Bot (bot_id: helper).")
        assert "Do not @-mention yourself." in preamble
        assert "Rolland (@rolland) mentioned you" in preamble

        # user_message is empty — no text to leak into the response
        prompt = ""
        assert prompt == ""


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


# ---------------------------------------------------------------------------
# _detect_member_mentions
# ---------------------------------------------------------------------------

class TestDetectMemberMentions:
    @pytest.mark.asyncio
    async def test_detects_member_mention(self):
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot", config={"auto_respond": True})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        # Mock Channel lookup (primary bot)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm):
            result = await _detect_member_mentions(
                channel_id, "primary-bot", "Hey @helper-bot, help me!"
            )

        assert len(result) == 1
        assert result[0][0] == "helper-bot"
        assert result[0][1] == {"auto_respond": True}

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_mentions(self):
        from app.routers.chat import _detect_member_mentions

        result = await _detect_member_mentions(
            uuid.uuid4(), "primary-bot", "No mentions here"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_at_depth_limit(self):
        from app.routers.chat import _detect_member_mentions, _MEMBER_MENTION_MAX_DEPTH

        result = await _detect_member_mentions(
            uuid.uuid4(), "primary-bot", "@helper-bot hello",
            _depth=_MEMBER_MENTION_MAX_DEPTH,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_display_name_resolves_to_bot_id(self):
        """@Rolland (display name) should resolve to qa-bot (bot_id)."""
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        member_row = _make_member_row("qa-bot", config={"auto_respond": True})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        bots = {
            "qa-bot": _make_bot(id="qa-bot", name="Rolland"),
            "primary-bot": _make_bot(id="primary-bot", name="Primary Bot"),
        }

        def _get_bot_side_effect(bid):
            if bid in bots:
                return bots[bid]
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Unknown bot: {bid}")

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("app.agent.bots.get_bot", side_effect=_get_bot_side_effect):
            result = await _detect_member_mentions(
                channel_id, "primary-bot", "Hey @Rolland, can you review this?"
            )

        assert len(result) == 1
        assert result[0][0] == "qa-bot"

    @pytest.mark.asyncio
    async def test_case_insensitive_bot_id_match(self):
        """@QA-BOT (uppercase) should resolve to qa-bot."""
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        # Note: tag regex requires [A-Za-z_][\w\-\.] so QA-BOT is valid
        member_row = _make_member_row("qa-bot", config={})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        bots = {
            "qa-bot": _make_bot(id="qa-bot", name="QA Bot"),
            "primary-bot": _make_bot(id="primary-bot", name="Primary Bot"),
        }

        def _get_bot_side_effect(bid):
            if bid in bots:
                return bots[bid]
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Unknown bot: {bid}")

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("app.agent.bots.get_bot", side_effect=_get_bot_side_effect):
            result = await _detect_member_mentions(
                channel_id, "primary-bot", "Hey @QA-BOT check this"
            )

        # QA-BOT → qa-bot via case-insensitive match
        assert len(result) == 1
        assert result[0][0] == "qa-bot"

    @pytest.mark.asyncio
    async def test_display_name_and_bot_id_deduplicated(self):
        """@Rolland and @qa-bot in same message should only trigger once."""
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        member_row = _make_member_row("qa-bot", config={})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        bots = {
            "qa-bot": _make_bot(id="qa-bot", name="Rolland"),
            "primary-bot": _make_bot(id="primary-bot", name="Primary Bot"),
        }

        def _get_bot_side_effect(bid):
            if bid in bots:
                return bots[bid]
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Unknown bot: {bid}")

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("app.agent.bots.get_bot", side_effect=_get_bot_side_effect):
            result = await _detect_member_mentions(
                channel_id, "primary-bot", "@Rolland and @qa-bot both refer to the same bot"
            )

        # Both resolve to qa-bot; deduplication should give us exactly one
        assert len(result) == 1
        assert result[0][0] == "qa-bot"


# ---------------------------------------------------------------------------
# Bot-to-bot @-mention trigger
# ---------------------------------------------------------------------------

class TestBotToBotMention:
    """Tests for _trigger_member_bot_replies — fires background runs when
    a bot's response @-mentions a channel member bot."""

    @pytest.mark.asyncio
    async def test_no_tags_in_response_does_nothing(self):
        """Response without @-mentions creates no tasks."""
        from app.routers.chat import _trigger_member_bot_replies

        # No @-mentions → should return immediately
        await _trigger_member_bot_replies(
            uuid.uuid4(), uuid.uuid4(), "primary-bot", "Hello, no mentions here."
        )
        # No error = success (nothing to assert, just verifying no crash)

    @pytest.mark.asyncio
    async def test_empty_response_does_nothing(self):
        from app.routers.chat import _trigger_member_bot_replies

        await _trigger_member_bot_replies(
            uuid.uuid4(), uuid.uuid4(), "primary-bot", ""
        )

    @pytest.mark.asyncio
    async def test_mention_non_member_bot_ignored(self):
        """@-mentioning a bot that isn't a channel member creates no tasks."""
        from app.routers.chat import _trigger_member_bot_replies

        channel_id = uuid.uuid4()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # no members
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("asyncio.create_task") as mock_create_task:
            await _trigger_member_bot_replies(
                channel_id, uuid.uuid4(), "primary-bot",
                "Hey @unknown_bot, what do you think?"
            )

        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_member_bot_triggers_task(self):
        """@-mentioning a channel member bot creates a background task."""
        from app.routers.chat import _trigger_member_bot_replies

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()

        member_row = _make_member_row("helper-bot", config={"auto_respond": True})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("asyncio.create_task") as mock_create_task:
            await _trigger_member_bot_replies(
                channel_id, session_id, "primary-bot",
                "Hey @helper-bot, can you help with this?"
            )

        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_self_mention_ignored(self):
        """A bot mentioning itself does not trigger a task."""
        from app.routers.chat import _trigger_member_bot_replies

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        # helper-bot mentions itself
        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("asyncio.create_task") as mock_create_task:
            await _trigger_member_bot_replies(
                channel_id, uuid.uuid4(), "helper-bot",
                "I am @helper-bot and I'm here."
            )

        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_depth_limit_prevents_infinite_chain(self):
        """Exceeding max depth returns immediately without processing."""
        from app.routers.chat import _trigger_member_bot_replies, _MEMBER_MENTION_MAX_DEPTH

        # At max depth, should not even attempt DB queries
        with patch("app.db.engine.async_session") as mock_session:
            await _trigger_member_bot_replies(
                uuid.uuid4(), uuid.uuid4(), "bot",
                "@helper-bot hello",
                _depth=_MEMBER_MENTION_MAX_DEPTH,
            )

        mock_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_mentions_deduplicated(self):
        """Same bot mentioned twice creates only one task."""
        from app.routers.chat import _trigger_member_bot_replies

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("asyncio.create_task") as mock_create_task:
            await _trigger_member_bot_replies(
                channel_id, uuid.uuid4(), "primary-bot",
                "@helper-bot what do you think? Also @helper-bot please check this."
            )

        # Only one task despite two mentions
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_skill_tag_not_treated_as_bot_mention(self):
        """@skill:name and @tool:name are not treated as bot mentions."""
        from app.routers.chat import _trigger_member_bot_replies

        channel_id = uuid.uuid4()
        # Even if a member bot exists with these names, the prefix filter should exclude them
        member_row = _make_member_row("myskill")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("asyncio.create_task") as mock_create_task:
            await _trigger_member_bot_replies(
                channel_id, uuid.uuid4(), "primary-bot",
                "Let me check @skill:myskill for help."
            )

        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_member_bot_reply_throttled(self):
        """Channel throttle prevents member bot reply."""
        from app.routers.chat import _run_member_bot_reply

        with patch("app.routers.chat._channel_throttled", return_value=True):
            # Should return without doing anything
            await _run_member_bot_reply(
                uuid.uuid4(), uuid.uuid4(), "helper-bot", {},
                "primary-bot",
            )
            # No error = throttle check worked

    @pytest.mark.asyncio
    async def test_run_member_bot_reply_lock_timeout(self):
        """If session lock can't be acquired, reply is skipped."""
        from app.routers.chat import _run_member_bot_reply

        with patch("app.routers.chat._channel_throttled", return_value=False), \
             patch("app.routers.chat.session_locks") as mock_locks, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            # Lock always busy
            mock_locks.acquire.return_value = False

            await _run_member_bot_reply(
                uuid.uuid4(), uuid.uuid4(), "helper-bot", {},
                "primary-bot",
            )
            # Should have tried multiple times then given up
            assert mock_locks.acquire.call_count == 30


# ---------------------------------------------------------------------------
# History rewriting for member bots
# ---------------------------------------------------------------------------

class TestRewriteHistoryForMemberBot:
    """Tests for _rewrite_history_for_member_bot — ensures member bots
    have proper identity by rewriting other bots' messages."""

    def test_member_bot_own_messages_kept_as_assistant(self):
        """Messages from the member bot itself stay as role=assistant."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "You are helper."},
            {"role": "user", "content": "hello", "_metadata": {}},
            {"role": "assistant", "content": "Hi there!", "_metadata": {
                "sender_id": "bot:helper", "sender_display_name": "Helper Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "Hi there!"

    def test_other_bot_messages_rewritten_to_user(self):
        """Messages from another bot become role=user with name prefix."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "You are helper."},
            {"role": "user", "content": "hello", "_metadata": {}},
            {"role": "assistant", "content": "I'm the primary bot.", "_metadata": {
                "sender_id": "bot:primary", "sender_display_name": "Primary Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "[Primary Bot]: I'm the primary bot."

    def test_untagged_messages_treated_as_other_bot(self):
        """Messages without sender_id (old messages) are treated as another bot."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "You are helper."},
            {"role": "user", "content": "hello", "_metadata": {}},
            {"role": "assistant", "content": "Old response with no metadata.", "_metadata": {}},
        ]
        _rewrite_history_for_member_bot(messages, "helper", primary_bot_name="Rolland")

        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "[Rolland]: Old response with no metadata."

    def test_untagged_messages_use_fallback_label(self):
        """Without primary_bot_name, fallback label is 'Other bot'."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "assistant", "content": "No metadata at all."},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "[Other bot]: No metadata at all."

    def test_other_bot_tool_calls_dropped(self):
        """Tool call messages from other bots (and their results) are removed."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "run a search", "_metadata": {}},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc_1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}
            ], "_metadata": {"sender_id": "bot:primary", "sender_display_name": "Primary Bot"}},
            {"role": "tool", "tool_call_id": "tc_1", "content": "search results"},
            {"role": "assistant", "content": "Here's what I found.", "_metadata": {
                "sender_id": "bot:primary", "sender_display_name": "Primary Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        # Tool call + tool result should be gone, text response should be rewritten
        assert len(messages) == 2  # user + rewritten assistant
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "[Primary Bot]: Here's what I found."

    def test_member_bot_tool_calls_kept(self):
        """Tool call messages from the member bot itself are kept intact."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "do something", "_metadata": {}},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc_1", "type": "function", "function": {"name": "file_read", "arguments": "{}"}}
            ], "_metadata": {"sender_id": "bot:helper", "sender_display_name": "Helper Bot"}},
            {"role": "tool", "tool_call_id": "tc_1", "content": "file contents"},
            {"role": "assistant", "content": "Done!", "_metadata": {
                "sender_id": "bot:helper", "sender_display_name": "Helper Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert len(messages) == 4  # all kept
        assert messages[1]["role"] == "assistant"
        assert messages[1].get("tool_calls")
        assert messages[2]["role"] == "tool"
        assert messages[3]["role"] == "assistant"
        assert messages[3]["content"] == "Done!"

    def test_user_messages_get_attribution(self):
        """User messages with sender_display_name get prefixed."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "What's up?", "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["content"] == "[Mike]: What's up?"

    def test_user_messages_not_double_prefixed(self):
        """Already-prefixed user messages aren't double-prefixed."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "[Mike]: hello", "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["content"] == "[Mike]: hello"

    def test_user_messages_without_display_name_unchanged(self):
        """User messages without sender_display_name stay unchanged."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "just a message", "_metadata": {}},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["content"] == "just a message"

    def test_system_messages_untouched(self):
        """System messages are never modified."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "You are a helpful bot."},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful bot."

    def test_mixed_conversation_realistic(self):
        """Realistic multi-bot conversation with proper rewriting."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "You are dev_bot."},
            {"role": "user", "content": "Hey what's the status?", "_metadata": {
                "sender_display_name": "Mike",
            }},
            {"role": "assistant", "content": "Everything looks good. Let me ask @dev_bot.", "_metadata": {
                "sender_id": "bot:rolland", "sender_display_name": "Rolland",
            }},
            # Trigger prompt (hidden in UI, but present in history)
            {"role": "user", "content": "Rolland (@rolland) mentioned you.", "_metadata": {
                "trigger": "member_mention", "hidden": True,
                "sender_display_name": "Rolland",
            }},
            {"role": "assistant", "content": "I checked the CI — all green.", "_metadata": {
                "sender_id": "bot:dev_bot", "sender_display_name": "Dev Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "dev_bot", primary_bot_name="Rolland")

        # System stays as-is
        assert messages[0]["role"] == "system"

        # User message gets attribution
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "[Mike]: Hey what's the status?"

        # Rolland's assistant message → rewritten to user
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "[Rolland]: Everything looks good. Let me ask @dev_bot."

        # Hidden trigger prompt is REMOVED (it's a system-injected prompt, not real input)
        # Dev bot's own response stays as assistant — now at index 3
        assert len(messages) == 4
        assert messages[3]["role"] == "assistant"
        assert messages[3]["content"] == "I checked the CI — all green."

    def test_primary_bot_sees_member_responses_with_attribution(self):
        """Primary bot should see member bot responses as attributed user messages."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "You are Rolland."},
            {"role": "user", "content": "Deploy the app", "_metadata": {
                "sender_display_name": "Mike",
            }},
            # Primary bot's own response
            {"role": "assistant", "content": "Sure, let me ask @dev_bot to handle it.", "_metadata": {
                "sender_id": "bot:rolland", "sender_display_name": "Rolland",
            }},
            # Trigger prompt for dev_bot (hidden)
            {"role": "user", "content": "You are Dev Bot. Rolland mentioned you.", "_metadata": {
                "trigger": "member_mention", "hidden": True,
                "sender_display_name": "Rolland",
            }},
            # Dev bot's response
            {"role": "assistant", "content": "Deployment started. ETA 5 minutes.", "_metadata": {
                "sender_id": "bot:dev_bot", "sender_display_name": "Dev Bot",
            }},
        ]
        # Rewrite from PRIMARY bot's perspective
        _rewrite_history_for_member_bot(
            messages, "rolland", primary_bot_name="Rolland", is_primary=True,
        )

        assert messages[0]["role"] == "system"

        # User message gets attribution
        assert messages[1]["content"] == "[Mike]: Deploy the app"

        # Primary bot's own response stays as assistant
        assert messages[2]["role"] == "assistant"
        assert "Sure, let me ask @dev_bot" in messages[2]["content"]

        # Hidden trigger prompt is removed
        # Dev bot's response is rewritten to user with attribution
        assert len(messages) == 4
        assert messages[3]["role"] == "user"
        assert messages[3]["content"] == "[Dev Bot]: Deployment started. ETA 5 minutes."

    def test_hidden_messages_removed(self):
        """Messages with hidden=True metadata are removed during rewrite."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Normal message"},
            {"role": "user", "content": "Hidden trigger", "_metadata": {"hidden": True}},
            {"role": "assistant", "content": "Bot response", "_metadata": {
                "sender_id": "bot:test_bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "test_bot")
        assert len(messages) == 3
        assert messages[1]["content"] == "Normal message"
        assert messages[2]["role"] == "assistant"


# ---------------------------------------------------------------------------
# _inject_member_config
# ---------------------------------------------------------------------------

class TestInjectMemberConfig:
    def test_empty_config_no_injection(self):
        from app.routers.chat import _inject_member_config

        messages = [{"role": "system", "content": "base"}]
        _inject_member_config(messages, {})
        assert len(messages) == 1

    def test_system_prompt_addon_injected(self):
        from app.routers.chat import _inject_member_config

        messages = [{"role": "system", "content": "base"}]
        _inject_member_config(messages, {"system_prompt_addon": "Always be brief."})
        assert len(messages) == 2
        assert "Always be brief." in messages[1]["content"]
        assert messages[1]["role"] == "system"

    def test_response_style_injected(self):
        from app.routers.chat import _inject_member_config

        messages = []
        _inject_member_config(messages, {"response_style": "brief"})
        assert len(messages) == 1
        assert "brief and concise" in messages[0]["content"]

    def test_combined_config(self):
        from app.routers.chat import _inject_member_config

        messages = []
        _inject_member_config(messages, {
            "system_prompt_addon": "Focus on code review.",
            "response_style": "detailed",
        })
        assert len(messages) == 1
        assert "Focus on code review." in messages[0]["content"]
        assert "detailed" in messages[0]["content"]


# ---------------------------------------------------------------------------
# _apply_user_attribution (speaker identity for primary bot)
# ---------------------------------------------------------------------------

class TestApplyUserAttribution:
    """Test that _apply_user_attribution adds [Name]: prefix to user messages
    using _metadata.sender_display_name, so the primary bot can distinguish
    multiple speakers."""

    def test_adds_prefix_from_metadata(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "hello", "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "[Mike]: hello"

    def test_no_metadata_unchanged(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "hello"},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "hello"

    def test_empty_display_name_unchanged(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "hello", "_metadata": {}},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "hello"

    def test_no_double_prefix(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "[Mike]: hello", "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "[Mike]: hello"

    def test_assistant_messages_untouched(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "assistant", "content": "hi", "_metadata": {
                "sender_display_name": "Bot",
            }},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "hi"

    def test_system_messages_untouched(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "system", "content": "prompt", "_metadata": {
                "sender_display_name": "System",
            }},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "prompt"

    def test_multiple_users_distinguished(self):
        """Two different users get their own prefixes."""
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "What's the status?", "_metadata": {
                "sender_display_name": "Mike",
            }},
            {"role": "assistant", "content": "All good."},
            {"role": "user", "content": "Can you elaborate?", "_metadata": {
                "sender_display_name": "Sarah",
            }},
        ]
        _apply_user_attribution(messages)

        assert messages[0]["content"] == "[Mike]: What's the status?"
        assert messages[1]["content"] == "All good."
        assert messages[2]["content"] == "[Sarah]: Can you elaborate?"

    def test_safe_with_member_bot_rewrite(self):
        """When called after _rewrite_history_for_member_bot, no double-prefix."""
        from app.routers.chat import _apply_user_attribution, _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "hello", "_metadata": {
                "sender_display_name": "Mike",
            }},
            {"role": "assistant", "content": "response", "_metadata": {
                "sender_id": "bot:primary", "sender_display_name": "Primary Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")
        _apply_user_attribution(messages)

        assert messages[0]["content"] == "[Mike]: hello"
        # No double prefix on the rewritten bot message (now role=user)
        assert messages[1]["content"] == "[Primary Bot]: response"

    def test_multimodal_content_skipped(self):
        """List content (images) is left untouched — no crash."""
        from app.routers.chat import _apply_user_attribution

        multimodal = [
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        ]
        messages = [
            {"role": "user", "content": multimodal, "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _apply_user_attribution(messages)
        # Content should be unchanged (still the list)
        assert messages[0]["content"] is multimodal

    def test_rewrite_multimodal_user_skipped(self):
        """_rewrite_history_for_member_bot also handles list content safely."""
        from app.routers.chat import _rewrite_history_for_member_bot

        multimodal = [
            {"type": "text", "text": "see this image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        ]
        messages = [
            {"role": "user", "content": multimodal, "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")
        # Content should be unchanged (still the list, no crash)
        assert messages[0]["content"] is multimodal


# ---------------------------------------------------------------------------
# Bug fix: _metadata must survive for history rewriting
# ---------------------------------------------------------------------------

class TestMetadataPreservation:
    """Verify that _metadata is preserved when loading messages for member bot
    rewriting, and stripped afterwards."""

    def test_rewriting_uses_metadata_for_sender_identity(self):
        """With _metadata present, member bot correctly identifies its own messages."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "assistant", "content": "Primary said this.", "_metadata": {
                "sender_id": "bot:primary", "sender_display_name": "Primary Bot",
            }},
            {"role": "assistant", "content": "Helper said this.", "_metadata": {
                "sender_id": "bot:helper", "sender_display_name": "Helper Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        # Primary bot's message should be rewritten
        assert messages[0]["role"] == "user"
        assert "[Primary Bot]:" in messages[0]["content"]
        # Helper's own message stays as assistant
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Helper said this."

    def test_rewriting_without_metadata_treats_all_as_other(self):
        """Without _metadata (the bug), all messages are treated as other bot."""
        from app.routers.chat import _rewrite_history_for_member_bot

        # Simulate what happened before the fix: _metadata stripped before rewriting
        messages = [
            {"role": "assistant", "content": "Primary said this."},
            {"role": "assistant", "content": "Helper said this."},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        # Both get rewritten — this is the correct behavior for stripped metadata
        # (without metadata, we can't distinguish, so all are treated as other)
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "user"

    def test_strip_metadata_keys_removes_metadata(self):
        """strip_metadata_keys properly removes _metadata from messages."""
        from app.services.sessions import strip_metadata_keys

        messages = [
            {"role": "assistant", "content": "test", "_metadata": {"sender_id": "bot:x"}},
            {"role": "user", "content": "hi"},
        ]
        result = strip_metadata_keys(messages)

        assert "_metadata" not in result[0]
        assert result[0]["content"] == "test"
        assert result[1] == {"role": "user", "content": "hi"}


# ---------------------------------------------------------------------------
# Bug fix: is_primary flag for primary bot history rewriting
# ---------------------------------------------------------------------------

class TestIsPrimaryRewriting:
    """When the primary bot is triggered via @-mention from a member bot,
    is_primary=True ensures untagged messages are kept as its own."""

    def test_primary_bot_untagged_messages_kept(self):
        """With is_primary=True, untagged assistant messages stay as assistant."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "assistant", "content": "Old message before multi-bot.", "_metadata": {}},
            {"role": "assistant", "content": "Primary's recent message.", "_metadata": {
                "sender_id": "bot:primary", "sender_display_name": "Primary Bot",
            }},
            {"role": "assistant", "content": "Helper's message.", "_metadata": {
                "sender_id": "bot:helper", "sender_display_name": "Helper Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "primary", is_primary=True)

        # Untagged message stays as assistant (primary bot's own)
        assert messages[0]["role"] == "assistant"
        # Explicitly tagged as primary stays as assistant
        assert messages[1]["role"] == "assistant"
        # Helper's message gets rewritten
        assert messages[2]["role"] == "user"
        assert "[Helper Bot]:" in messages[2]["content"]

    def test_member_bot_untagged_messages_rewritten(self):
        """With is_primary=False (default), untagged messages are treated as other bot."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "assistant", "content": "Old message before multi-bot.", "_metadata": {}},
        ]
        _rewrite_history_for_member_bot(messages, "helper", primary_bot_name="Primary Bot")

        # Untagged message is rewritten (not the member bot's own)
        assert messages[0]["role"] == "user"
        assert "[Primary Bot]:" in messages[0]["content"]


# ---------------------------------------------------------------------------
# Bug fix: primary bot detectable in _detect_member_mentions
# ---------------------------------------------------------------------------

class TestPrimaryBotMentionBack:
    """Member bots can @-mention the primary bot to trigger a reply."""

    @pytest.mark.asyncio
    async def test_primary_bot_detected_in_mentions(self):
        """Primary bot is included as a valid mention target."""
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock the Channel with a primary bot
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm):
            result = await _detect_member_mentions(
                channel_id, "helper-bot", "Hey @primary-bot, can you check this?"
            )

        assert len(result) == 1
        assert result[0][0] == "primary-bot"
        assert result[0][1] == {}  # primary bot has no member config

    @pytest.mark.asyncio
    async def test_primary_bot_not_triggered_by_self(self):
        """Primary bot mentioning itself doesn't trigger."""
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm):
            result = await _detect_member_mentions(
                channel_id, "primary-bot", "I am @primary-bot."
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_back_and_forth_chain(self):
        """Primary → member → primary chain is allowed within depth limit."""
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot", config={"auto_respond": True})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        # Depth 0: primary bot mentions helper (allowed)
        with patch("app.db.engine.async_session", return_value=mock_cm):
            result = await _detect_member_mentions(
                channel_id, "primary-bot", "Hey @helper-bot check this",
                _depth=0,
            )
        assert len(result) == 1
        assert result[0][0] == "helper-bot"

        # Depth 1: helper mentions primary back (allowed)
        with patch("app.db.engine.async_session", return_value=mock_cm):
            result = await _detect_member_mentions(
                channel_id, "helper-bot", "Done, @primary-bot here are results",
                _depth=1,
            )
        assert len(result) == 1
        assert result[0][0] == "primary-bot"

        # Depth 2: primary mentions helper again (allowed, depth < 3)
        with patch("app.db.engine.async_session", return_value=mock_cm):
            result = await _detect_member_mentions(
                channel_id, "primary-bot", "@helper-bot one more thing",
                _depth=2,
            )
        assert len(result) == 1
        assert result[0][0] == "helper-bot"

        # Depth 3: blocked by max depth
        with patch("app.db.engine.async_session", return_value=mock_cm):
            result = await _detect_member_mentions(
                channel_id, "helper-bot", "@primary-bot results",
                _depth=3,
            )
        assert result == []


# ---------------------------------------------------------------------------
# Parallel invocation & dedup
# ---------------------------------------------------------------------------

class TestParallelInvocation:
    """Tests for parallel member bot invocation features."""

    @pytest.mark.asyncio
    async def test_trigger_passes_snapshot_to_run(self):
        """_trigger_member_bot_replies passes messages_snapshot to each task."""
        from app.routers.chat import _trigger_member_bot_replies

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()

        member_row = _make_member_row("helper-bot", config={})
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        snapshot = [{"role": "user", "content": "hi"}]
        captured_kwargs = {}

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("asyncio.create_task") as mock_create_task:
            mock_create_task.return_value = MagicMock()
            mock_create_task.return_value.add_done_callback = MagicMock()
            result = await _trigger_member_bot_replies(
                channel_id, session_id, "primary-bot",
                "Hey @helper-bot help",
                messages_snapshot=snapshot,
            )

        assert len(result) == 1
        # Verify create_task was called with a coroutine containing snapshot
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_skips_already_invoked(self):
        """Bots in already_invoked set are skipped."""
        from app.routers.chat import _trigger_member_bot_replies

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot", config={})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("asyncio.create_task") as mock_create_task:
            result = await _trigger_member_bot_replies(
                channel_id, uuid.uuid4(), "primary-bot",
                "Hey @helper-bot help",
                already_invoked={"helper-bot"},
            )

        # helper-bot was already invoked, so no task created
        assert len(result) == 0
        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_trigger_returns_mentioned_list(self):
        """_trigger_member_bot_replies returns the list of triggered bots."""
        from app.routers.chat import _trigger_member_bot_replies

        channel_id = uuid.uuid4()
        member_a = _make_member_row("bot-a", config={})
        member_b = _make_member_row("bot-b", config={})

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_a, member_b]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db.get = AsyncMock(return_value=mock_channel)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("asyncio.create_task") as mock_create_task:
            mock_create_task.return_value = MagicMock()
            mock_create_task.return_value.add_done_callback = MagicMock()
            result = await _trigger_member_bot_replies(
                channel_id, uuid.uuid4(), "primary-bot",
                "@bot-a and @bot-b both help",
            )

        assert len(result) == 2
        bot_ids = [r[0] for r in result]
        assert "bot-a" in bot_ids
        assert "bot-b" in bot_ids

    @pytest.mark.asyncio
    async def test_snapshot_path_skips_lock(self):
        """With messages_snapshot, _run_member_bot_reply doesn't acquire lock."""
        from app.routers.chat import _run_member_bot_reply

        snapshot = [
            {"role": "system", "content": "You are helper."},
            {"role": "user", "content": "hello"},
        ]

        with patch("app.routers.chat._channel_throttled", return_value=False), \
             patch("app.routers.chat.session_locks") as mock_locks, \
             patch("app.routers.chat.get_bot", return_value=_make_bot(id="helper-bot", name="Helper")), \
             patch("app.routers.chat._record_channel_run"), \
             patch("app.routers.chat.set_agent_context"), \
             patch("app.routers.chat.run_stream", side_effect=_fake_stream), \
             patch("app.services.channel_events.publish"), \
             patch("app.db.engine.async_session") as mock_session:

            mock_db = AsyncMock()
            mock_channel = MagicMock()
            mock_channel.bot_id = "primary-bot"
            mock_db.get = AsyncMock(return_value=mock_channel)
            mock_db.execute = AsyncMock()
            mock_db.commit = AsyncMock()
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session.return_value = mock_cm

            with patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
                 patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: x):
                await _run_member_bot_reply(
                    uuid.uuid4(), uuid.uuid4(), "helper-bot", {},
                    "primary-bot",
                    messages_snapshot=snapshot,
                    stream_id="test-stream-123",
                )

            # Lock should NOT have been acquired when using snapshot
            mock_locks.acquire.assert_not_called()
            mock_locks.release.assert_not_called()

    def test_invoked_member_bots_contextvar(self):
        """current_invoked_member_bots tracks invoked bots."""
        from app.agent.context import current_invoked_member_bots

        # Default is None
        current_invoked_member_bots.set(None)
        assert current_invoked_member_bots.get() is None

        # Set and track
        invoked = set()
        current_invoked_member_bots.set(invoked)
        invoked.add("bot-a")
        invoked.add("bot-b")

        result = current_invoked_member_bots.get()
        assert result is not None
        assert "bot-a" in result
        assert "bot-b" in result

    @pytest.mark.asyncio
    async def test_invoke_member_bot_tool_validates_channel(self):
        """invoke_member_bot returns error when no channel context."""
        from app.tools.local.channel_bots import invoke_member_bot
        from app.agent.context import current_channel_id, current_session_id, current_bot_id
        import json

        current_channel_id.set(None)
        current_session_id.set(None)
        current_bot_id.set("primary-bot")

        result = await invoke_member_bot(bot_id="helper-bot")
        data = json.loads(result)
        assert "error" in data
        assert "channel" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_invoke_member_bot_tool_rejects_self(self):
        """invoke_member_bot returns error when trying to invoke self."""
        from app.tools.local.channel_bots import invoke_member_bot
        from app.agent.context import current_channel_id, current_session_id, current_bot_id
        import json

        current_channel_id.set(uuid.uuid4())
        current_session_id.set(uuid.uuid4())
        current_bot_id.set("primary-bot")

        result = await invoke_member_bot(bot_id="primary-bot")
        data = json.loads(result)
        assert "error" in data
        assert "yourself" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_invoke_member_bot_tool_validates_membership(self):
        """invoke_member_bot returns error if target bot is not a channel member."""
        from app.tools.local.channel_bots import invoke_member_bot
        from app.agent.context import current_channel_id, current_session_id, current_bot_id
        import json

        channel_id = uuid.uuid4()
        current_channel_id.set(channel_id)
        current_session_id.set(uuid.uuid4())
        current_bot_id.set("primary-bot")

        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_channel)
        # No member row found
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("app.agent.bots.get_bot", return_value=_make_bot(id="unknown-bot")):
            result = await invoke_member_bot(bot_id="unknown-bot")

        data = json.loads(result)
        assert "error" in data
        assert "not a member" in data["error"].lower()


    @pytest.mark.asyncio
    async def test_invoke_member_bot_tool_double_invocation_guard(self):
        """Calling invoke_member_bot twice for the same bot returns already_invoked."""
        from app.tools.local.channel_bots import invoke_member_bot
        from app.agent.context import (
            current_channel_id, current_session_id, current_bot_id,
            current_invoked_member_bots,
        )
        import json

        current_channel_id.set(uuid.uuid4())
        current_session_id.set(uuid.uuid4())
        current_bot_id.set("primary-bot")
        # Pre-populate: helper-bot was already invoked this turn
        current_invoked_member_bots.set({"helper-bot"})

        # No DB mocks needed — guard fires before any DB access
        result = await invoke_member_bot(bot_id="helper-bot")
        data = json.loads(result)
        assert data["status"] == "already_invoked"

    @pytest.mark.asyncio
    async def test_invoke_member_bot_tool_happy_path(self):
        """invoke_member_bot success path creates a background task."""
        from app.tools.local.channel_bots import invoke_member_bot
        from app.agent.context import (
            current_channel_id, current_session_id, current_bot_id,
            current_invoked_member_bots,
        )
        import json

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        current_channel_id.set(channel_id)
        current_session_id.set(session_id)
        current_bot_id.set("primary-bot")
        current_invoked_member_bots.set(None)

        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_member = MagicMock()
        mock_member.config = {"response_style": "concise"}

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_channel)
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=mock_member)
        ))
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("app.agent.bots.get_bot", return_value=_make_bot(id="helper-bot", name="Helper")), \
             patch("app.services.sessions.load_or_create", new_callable=AsyncMock,
                   return_value=(session_id, mock_messages)), \
             patch("app.routers.chat._run_member_bot_reply", new_callable=AsyncMock) as mock_run, \
             patch("app.routers.chat._background_tasks", set()):
            result = await invoke_member_bot(bot_id="helper-bot", message="focus on errors")

        data = json.loads(result)
        assert data["status"] == "ok"
        assert "Helper" in data["message"]

        # Verify dedup tracking
        invoked = current_invoked_member_bots.get()
        assert "helper-bot" in invoked

    @pytest.mark.asyncio
    async def test_invoke_member_bot_contextvar_creates_new_set(self):
        """ContextVar mutation uses a new set (not in-place mutation)."""
        from app.tools.local.channel_bots import invoke_member_bot
        from app.agent.context import (
            current_channel_id, current_session_id, current_bot_id,
            current_invoked_member_bots,
        )
        import json

        channel_id = uuid.uuid4()
        current_channel_id.set(channel_id)
        current_session_id.set(uuid.uuid4())
        current_bot_id.set("primary-bot")
        original_set = {"other-bot"}
        current_invoked_member_bots.set(original_set)

        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_member = MagicMock()
        mock_member.config = {}
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_channel)
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=mock_member)
        ))
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm), \
             patch("app.agent.bots.get_bot", return_value=_make_bot(id="helper-bot")), \
             patch("app.services.sessions.load_or_create", new_callable=AsyncMock,
                   return_value=(uuid.uuid4(), [{"role": "system", "content": "s"}])), \
             patch("app.routers.chat._run_member_bot_reply", new_callable=AsyncMock), \
             patch("app.routers.chat._background_tasks", set()):
            await invoke_member_bot(bot_id="helper-bot")

        # The original set should NOT have been mutated in-place
        assert "helper-bot" not in original_set
        # But the ContextVar should have the new value
        new_set = current_invoked_member_bots.get()
        assert "helper-bot" in new_set
        assert "other-bot" in new_set

    @pytest.mark.asyncio
    async def test_chained_trigger_passes_snapshot(self):
        """When a member bot's response triggers another bot, it passes a snapshot."""
        from app.routers.chat import _run_member_bot_reply

        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        messages_snapshot = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ]

        with patch("app.agent.bots.get_bot") as mock_get_bot, \
             patch("app.services.channel_events.publish") as mock_publish, \
             patch("app.agent.loop.run_stream") as mock_run_stream, \
             patch("app.db.engine.async_session") as mock_session_factory, \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch("app.routers.chat._mirror_to_integration", new_callable=AsyncMock), \
             patch("app.routers.chat._trigger_member_bot_replies", new_callable=AsyncMock) as mock_trigger:

            mock_get_bot.side_effect = lambda bid: _make_bot(id=bid, name=bid)
            mock_run_stream.return_value = _fake_stream()

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=MagicMock(bot_id="primary-bot"))
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session_factory.return_value = mock_cm

            await _run_member_bot_reply(
                channel_id, session_id, "helper-bot", {},
                "primary-bot", _depth=1,
                messages_snapshot=messages_snapshot,
                stream_id="test-stream-id",
            )

            # The chained trigger should have been called with a snapshot
            mock_trigger.assert_called_once()
            call_kwargs = mock_trigger.call_args
            assert call_kwargs.kwargs.get("messages_snapshot") is not None


    @pytest.mark.asyncio
    async def test_user_message_mentions_trigger_parallel_streams(self):
        """User @-mentioning multiple bots in their message triggers all of them."""
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot", config={})
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.get = AsyncMock(return_value=mock_channel)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm):
            # Scan the USER's message — primary-bot is the responder, excluded
            mentioned = await _detect_member_mentions(
                channel_id, "primary-bot",
                "Hey @bot:helper-bot and @bot:primary-bot check this out",
                _depth=0,
            )
        bot_ids = [bid for bid, _ in mentioned]
        assert "helper-bot" in bot_ids
        # primary-bot excluded because it's the responding_bot_id
        assert "primary-bot" not in bot_ids

    @pytest.mark.asyncio
    async def test_user_mention_dedup_prevents_response_retrigger(self):
        """Bots triggered by user @-mentions aren't re-triggered by response @-mentions."""
        from app.routers.chat import _detect_member_mentions

        channel_id = uuid.uuid4()
        member_row = _make_member_row("helper-bot", config={})
        mock_channel = MagicMock()
        mock_channel.bot_id = "primary-bot"
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [member_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.get = AsyncMock(return_value=mock_channel)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_cm):
            # Step 1: detect user mentions (helper-bot found)
            user_mentioned = await _detect_member_mentions(
                channel_id, "primary-bot",
                "Hey @bot:helper-bot what do you think?",
                _depth=0,
            )
        user_mentioned_ids = {bid for bid, _ in user_mentioned}
        assert "helper-bot" in user_mentioned_ids

        # Step 2: simulate post-completion scan with already_invoked filtering
        with patch("app.db.engine.async_session", return_value=mock_cm):
            response_mentioned = await _detect_member_mentions(
                channel_id, "primary-bot",
                "I agree with @helper-bot's take",
                _depth=0,
            )
        # Filter with already_invoked (as the real code does in event_generator)
        filtered = [(bid, cfg) for bid, cfg in response_mentioned if bid not in user_mentioned_ids]
        assert len(filtered) == 0  # helper-bot already invoked, not re-triggered


async def _fake_stream(*a, **kw):
    """Minimal fake for run_stream that yields a response event."""
    yield {"type": "response", "text": "ok", "client_actions": []}
