"""Tests for multi-bot channel features.

Covers:
- Member bot routing (_maybe_route_to_member_bot)
- Bot-to-bot @-mention trigger (_trigger_member_bot_replies)
- Anti-loop protection (ContextVar tracking)
- Context injection (membership awareness + delegate index merge)
- Member bot memory flush on compaction

DB-touching classes use the real ``db_session`` + ``bot_registry`` fixtures
from ``tests/conftest.py`` and ``tests/unit/conftest.py``; routing and
mention resolution run the real SQL against SQLite-in-memory.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.factories import build_channel, build_channel_bot_member


def _make_bot(**overrides):
    """Construct a ``BotConfig`` (the in-registry shape, not the ORM row).

    Used where production code calls ``app.agent.bots.get_bot()`` and needs a
    ``BotConfig``. For routing tests that also need a ``Bot`` ORM row, use the
    ``bot_registry`` fixture plus ``build_bot()`` from ``tests.factories``.
    """
    from app.agent.bots import BotConfig, MemoryConfig

    defaults = dict(
        id="primary-bot",
        name="Primary Bot",
        model="gpt-4",
        system_prompt="You are a bot.",
        delegate_bots=[],
        memory=MemoryConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# _maybe_route_to_member_bot
# ---------------------------------------------------------------------------


class TestMemberBotRouting:
    @pytest.mark.asyncio
    async def test_when_message_is_empty_then_returns_original_bot(self, db_session):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot()
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.commit()

        result_bot, result_cfg = await _maybe_route_to_member_bot(db_session, channel, primary, "")

        assert (result_bot, result_cfg) == (primary, {})

    @pytest.mark.asyncio
    async def test_when_message_has_no_tags_then_returns_original_bot(self, db_session):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot()
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.commit()

        result_bot, result_cfg = await _maybe_route_to_member_bot(
            db_session, channel, primary, "hello world no tags here"
        )

        assert (result_bot, result_cfg) == (primary, {})

    @pytest.mark.asyncio
    async def test_when_mention_matches_channel_member_then_routes_to_member(
        self, db_session, bot_registry
    ):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        helper = bot_registry.register("helper", name="Helper Bot")
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.merge(build_channel_bot_member(channel_id=channel.id, bot_id="helper"))
        await db_session.commit()

        result_bot, result_cfg = await _maybe_route_to_member_bot(
            db_session, channel, primary, "@helper what do you think?"
        )

        assert result_bot is helper
        assert result_cfg == {}

    @pytest.mark.asyncio
    async def test_when_typed_bot_tag_matches_member_then_routes_to_member(
        self, db_session, bot_registry
    ):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        helper = bot_registry.register("helper", name="Helper Bot")
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.merge(build_channel_bot_member(channel_id=channel.id, bot_id="helper"))
        await db_session.commit()

        result_bot, _ = await _maybe_route_to_member_bot(
            db_session, channel, primary, "@bot:helper please respond"
        )

        assert result_bot is helper

    @pytest.mark.asyncio
    async def test_when_non_bot_typed_tag_matches_member_id_then_ignored(
        self, db_session, bot_registry
    ):
        """@skill:helper must NOT route to a member bot named helper."""
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        bot_registry.register("helper", name="Helper Bot")
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.merge(build_channel_bot_member(channel_id=channel.id, bot_id="helper"))
        await db_session.commit()

        result_bot, _ = await _maybe_route_to_member_bot(
            db_session, channel, primary, "@skill:helper describe yourself"
        )

        assert result_bot is primary

    @pytest.mark.asyncio
    async def test_when_tag_not_in_member_list_then_returns_original(
        self, db_session, bot_registry
    ):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        bot_registry.register("helper", name="Helper Bot")
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.merge(build_channel_bot_member(channel_id=channel.id, bot_id="helper"))
        await db_session.commit()

        result_bot, _ = await _maybe_route_to_member_bot(
            db_session, channel, primary, "@unknown_bot hello"
        )

        assert result_bot is primary

    @pytest.mark.asyncio
    async def test_when_channel_has_no_members_then_returns_original(self, db_session):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.commit()

        result_bot, _ = await _maybe_route_to_member_bot(
            db_session, channel, primary, "@helper hello"
        )

        assert result_bot is primary

    @pytest.mark.asyncio
    async def test_when_member_bot_id_missing_from_registry_then_falls_through(
        self, db_session
    ):
        """DB row for member bot exists but registry lookup raises — don't route."""
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.merge(build_channel_bot_member(channel_id=channel.id, bot_id="helper"))
        await db_session.commit()
        # bot_registry fixture NOT requested — helper is absent from _registry,
        # so get_bot("helper") raises and the router falls through to primary.

        result_bot, _ = await _maybe_route_to_member_bot(
            db_session, channel, primary, "@helper hello"
        )

        assert result_bot is primary

    @pytest.mark.asyncio
    async def test_when_member_is_routed_then_config_dict_returned(
        self, db_session, bot_registry
    ):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        helper = bot_registry.register("helper", name="Helper Bot")
        member_cfg = {"model_override": "gpt-4o", "auto_respond": True, "priority": 1}
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper", config=member_cfg,
        ))
        await db_session.commit()

        result_bot, result_cfg = await _maybe_route_to_member_bot(
            db_session, channel, primary, "@helper hello"
        )

        assert (result_bot, result_cfg) == (helper, member_cfg)

    @pytest.mark.asyncio
    async def test_when_no_member_matched_then_config_is_empty(
        self, db_session, bot_registry
    ):
        from app.routers.chat import _maybe_route_to_member_bot

        primary = _make_bot(id="primary-bot")
        bot_registry.register("helper", name="Helper Bot")
        channel = await db_session.merge(build_channel(bot_id=primary.id))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper", config={"auto_respond": True},
        ))
        await db_session.commit()

        result_bot, result_cfg = await _maybe_route_to_member_bot(
            db_session, channel, primary, "@unknown hello"
        )

        assert (result_bot, result_cfg) == (primary, {})


# ---------------------------------------------------------------------------
# Anti-loop protection
# ---------------------------------------------------------------------------

class TestAntiLoop:
    """Anti-loop is enforced inside ``DelegationService.run_immediate`` — tests
    drive that real entry point rather than asserting on ``ContextVar`` get/set
    (pure Python semantics, not product code)."""

    @pytest.mark.asyncio
    async def test_when_delegate_already_responded_then_run_immediate_raises(
        self, agent_context
    ):
        from app.services.delegation import DelegationError, DelegationService

        parent = _make_bot(id="primary-bot", delegate_bots=["helper-bot"])
        agent_context(turn_responded_bots={"primary-bot", "helper-bot"})

        with patch("app.services.delegation.settings") as s:
            s.DELEGATION_MAX_DEPTH = 5
            with pytest.raises(DelegationError, match="Anti-loop"):
                await DelegationService().run_immediate(
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
    async def test_when_delegate_runs_then_bot_id_added_to_responded_set(
        self, agent_context, bot_registry
    ):
        from app.services.delegation import DelegationService

        parent = _make_bot(id="primary-bot", delegate_bots=["helper-bot"])
        bot_registry.register("helper-bot", name="Helper")
        responded: set[str] = {"primary-bot"}
        agent_context(turn_responded_bots=responded)

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "ok", "client_actions": []}

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None):
            s.DELEGATION_MAX_DEPTH = 5
            await DelegationService().run_immediate(
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

    def test_when_snapshot_taken_then_responded_bots_preserved(self, agent_context):
        from app.agent.context import snapshot_agent_context

        responded = {"bot-a", "bot-b"}
        agent_context(
            turn_responded_bots=responded,
            session_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            client_id="test",
            bot_id="bot-a",
        )

        snap = snapshot_agent_context()

        assert snap.turn_responded_bots is responded


# ---------------------------------------------------------------------------
# Context injection — multi-bot awareness message
# ---------------------------------------------------------------------------

class TestContextInjection:
    """Snapshot-level tests: verify the member bot run path strips the primary
    bot's system messages and injects persona when enabled. Pure-string
    awareness-message format tests were deleted — they re-implemented the
    builder inline (skill B.23 — self-validating re-implementation)."""

    @pytest.mark.asyncio
    async def test_when_snapshot_passed_then_primary_system_messages_replaced_with_member_prompt(
        self, db_session, patched_async_sessions, bot_registry
    ):
        from app.routers.chat import _run_member_bot_reply

        bot_registry.register(
            "primary", name="Primary Bot", system_prompt="I am the primary bot.",
        )
        bot_registry.register(
            "helper", name="Helper Bot",
            system_prompt="I am the helper bot.", persona=False,
        )
        channel = await db_session.merge(build_channel(bot_id="primary"))
        await db_session.commit()
        snapshot = [
            {"role": "system", "content": "You are Primary Bot. I am the primary bot."},
            {"role": "system", "content": "[PERSONA]\nPrimary persona info"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there from primary"},
        ]
        captured: list[dict] = []

        async def fake_run_stream(messages, bot, prompt, **kwargs):
            captured.extend(messages)
            yield {"type": "response", "text": "Hello from helper"}

        with patch("app.agent.loop.run_stream", fake_run_stream), \
             patch("app.services.channel_events.publish_typed"), \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.routers.chat._multibot._record_channel_run"), \
             patch(
                 "app.services.sessions._resolve_workspace_base_prompt_enabled",
                 new_callable=AsyncMock, return_value=False,
             ):
            await _run_member_bot_reply(
                channel.id, uuid.uuid4(), "helper", {}, "primary",
                messages_snapshot=snapshot,
            )

        system_contents = [m["content"] for m in captured if m.get("role") == "system"]
        first_sys = system_contents[0]
        user_contents = [m["content"] for m in captured if m.get("role") == "user"]
        assert "I am the helper bot" in first_sys
        assert "I am the primary bot" not in first_sys and "Primary persona" not in first_sys
        assert user_contents[0] == "Hello"

    @pytest.mark.asyncio
    async def test_when_member_has_persona_enabled_then_persona_marker_injected(
        self, db_session, patched_async_sessions, bot_registry
    ):
        from app.routers.chat import _run_member_bot_reply

        bot_registry.register(
            "helper", name="Helper Bot", system_prompt="I am helper.", persona=True,
        )
        bot_registry.register(
            "primary", name="Primary Bot", system_prompt="I am primary.",
        )
        channel = await db_session.merge(build_channel(bot_id="primary"))
        await db_session.commit()
        snapshot = [
            {"role": "system", "content": "Primary system prompt"},
            {"role": "user", "content": "Hi"},
        ]
        captured: list[dict] = []

        async def fake_run_stream(messages, bot, prompt, **kwargs):
            captured.extend(messages)
            yield {"type": "response", "text": "Hello"}

        with patch("app.agent.loop.run_stream", fake_run_stream), \
             patch("app.services.channel_events.publish_typed"), \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.routers.chat._multibot._record_channel_run"), \
             patch(
                 "app.services.sessions._resolve_workspace_base_prompt_enabled",
                 new_callable=AsyncMock, return_value=False,
             ), \
             patch(
                 "app.agent.persona.get_persona",
                 new_callable=AsyncMock, return_value="Helper persona text",
             ):
            await _run_member_bot_reply(
                channel.id, uuid.uuid4(), "helper", {}, "primary",
                messages_snapshot=snapshot,
            )

        persona_msgs = [
            m["content"] for m in captured
            if m.get("role") == "system" and "[PERSONA]" in m.get("content", "")
        ]
        has_primary_prompt = any(
            "Primary system prompt" in m.get("content", "") for m in captured
        )
        assert len(persona_msgs) == 1 and "Helper persona text" in persona_msgs[0]
        assert not has_primary_prompt


# ---------------------------------------------------------------------------
# Member bot memory flush
# ---------------------------------------------------------------------------

class TestMemberBotFlush:
    @pytest.mark.asyncio
    async def test_when_member_not_on_workspace_files_scheme_then_skipped(
        self, db_session, patched_async_sessions, bot_registry
    ):
        from app.services.compaction import _flush_member_bots

        bot_registry.register("helper", memory=None)  # BotConfig has memory_scheme indirectly
        # BotConfig doesn't carry memory_scheme directly — it's on the Bot ORM row.
        # For _flush_member_bots the lookup is via get_bot(), which returns BotConfig.
        # We set memory_scheme on the registry entry by overriding after construction.
        from app.agent.bots import _registry as _bot_reg
        _bot_reg["helper"].memory_scheme = None  # type: ignore[attr-defined]

        channel = await db_session.merge(build_channel(bot_id="primary"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper",
        ))
        await db_session.commit()

        with patch("app.services.compaction._run_memory_flush", new_callable=AsyncMock) as mock_flush:
            await _flush_member_bots(channel, uuid.uuid4(), [])

        mock_flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_when_member_is_workspace_files_bot_then_memory_flushed(
        self, db_session, patched_async_sessions, bot_registry
    ):
        from app.services.compaction import _flush_member_bots
        from app.agent.bots import _registry as _bot_reg

        bot_registry.register("helper")
        _bot_reg["helper"].memory_scheme = "workspace-files"  # type: ignore[attr-defined]

        channel = await db_session.merge(build_channel(bot_id="primary"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper",
        ))
        await db_session.commit()

        with patch("app.services.compaction._run_memory_flush", new_callable=AsyncMock) as mock_flush:
            await _flush_member_bots(
                channel, uuid.uuid4(), [{"role": "user", "content": "hi"}]
            )

        mock_flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_when_channel_has_no_members_then_no_flush(
        self, db_session, patched_async_sessions
    ):
        from app.services.compaction import _flush_member_bots

        channel = await db_session.merge(build_channel(bot_id="primary"))
        await db_session.commit()

        with patch("app.services.compaction._run_memory_flush", new_callable=AsyncMock) as mock_flush:
            await _flush_member_bots(channel, uuid.uuid4(), [])

        mock_flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_when_db_load_fails_then_exception_swallowed_and_no_flush(
        self, db_session, patched_async_sessions
    ):
        """Contract per `compaction.py:358`: DB failure during member-bot
        lookup is swallowed and logged at debug level — the flush is skipped
        rather than propagated into the caller's turn loop."""
        from app.services.compaction import _flush_member_bots

        channel = await db_session.merge(build_channel(bot_id="primary"))
        await db_session.commit()

        with patch(
            "app.services.compaction.async_session",
            side_effect=Exception("DB down"),
        ), patch(
            "app.services.compaction._run_memory_flush", new_callable=AsyncMock
        ) as mock_flush:
            await _flush_member_bots(channel, uuid.uuid4(), [])

        mock_flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_when_one_member_flush_fails_then_remaining_members_still_attempted(
        self, db_session, patched_async_sessions, bot_registry
    ):
        from app.services.compaction import _flush_member_bots
        from app.agent.bots import _registry as _bot_reg

        bot_registry.register("bot-a")
        bot_registry.register("bot-b")
        _bot_reg["bot-a"].memory_scheme = "workspace-files"  # type: ignore[attr-defined]
        _bot_reg["bot-b"].memory_scheme = "workspace-files"  # type: ignore[attr-defined]

        channel = await db_session.merge(build_channel(bot_id="primary"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="bot-a",
        ))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="bot-b",
        ))
        await db_session.commit()

        async def flush_side_effect(ch, bot, sid, msgs, correlation_id=None):
            if bot.id == "bot-a":
                raise Exception("flush failed for bot-a")

        with patch(
            "app.services.compaction._run_memory_flush",
            new_callable=AsyncMock,
            side_effect=flush_side_effect,
        ) as mock_flush:
            await _flush_member_bots(channel, uuid.uuid4(), [])

        assert mock_flush.await_count == 2


# ---------------------------------------------------------------------------
# _detect_member_mentions
# ---------------------------------------------------------------------------

class TestDetectMemberMentions:
    @pytest.mark.asyncio
    async def test_when_response_mentions_member_bot_then_returned_with_config(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _detect_member_mentions

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot", config={"auto_respond": True},
        ))
        await db_session.commit()

        result = await _detect_member_mentions(
            channel.id, "primary-bot", "Hey @helper-bot, help me!"
        )

        assert result == [("helper-bot", {"auto_respond": True})]

    @pytest.mark.asyncio
    async def test_when_no_mentions_in_response_then_returns_empty(self):
        from app.routers.chat import _detect_member_mentions

        result = await _detect_member_mentions(
            uuid.uuid4(), "primary-bot", "No mentions here"
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_when_at_max_depth_then_returns_empty(self):
        from app.routers.chat import _detect_member_mentions, _MEMBER_MENTION_MAX_DEPTH

        result = await _detect_member_mentions(
            uuid.uuid4(), "primary-bot", "@helper-bot hello",
            _depth=_MEMBER_MENTION_MAX_DEPTH,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_when_display_name_mentioned_then_resolves_to_bot_id(
        self, db_session, patched_async_sessions, bot_registry
    ):
        bot_registry.register("qa-bot", name="Rolland")
        bot_registry.register("primary-bot", name="Primary Bot")
        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="qa-bot", config={"auto_respond": True},
        ))
        await db_session.commit()

        from app.routers.chat import _detect_member_mentions
        result = await _detect_member_mentions(
            channel.id, "primary-bot", "Hey @Rolland, can you review this?"
        )

        assert [bid for bid, _ in result] == ["qa-bot"]

    @pytest.mark.asyncio
    async def test_when_bot_id_mentioned_in_uppercase_then_matches_case_insensitively(
        self, db_session, patched_async_sessions, bot_registry
    ):
        bot_registry.register("qa-bot", name="QA Bot")
        bot_registry.register("primary-bot", name="Primary Bot")
        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="qa-bot",
        ))
        await db_session.commit()

        from app.routers.chat import _detect_member_mentions
        result = await _detect_member_mentions(
            channel.id, "primary-bot", "Hey @QA-BOT check this"
        )

        assert [bid for bid, _ in result] == ["qa-bot"]

    @pytest.mark.asyncio
    async def test_when_same_bot_mentioned_by_id_and_display_name_then_deduplicated(
        self, db_session, patched_async_sessions, bot_registry
    ):
        bot_registry.register("qa-bot", name="Rolland")
        bot_registry.register("primary-bot", name="Primary Bot")
        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="qa-bot",
        ))
        await db_session.commit()

        from app.routers.chat import _detect_member_mentions
        result = await _detect_member_mentions(
            channel.id, "primary-bot", "@Rolland and @qa-bot both refer to the same bot"
        )

        assert [bid for bid, _ in result] == ["qa-bot"]


# ---------------------------------------------------------------------------
# Bot-to-bot @-mention trigger
# ---------------------------------------------------------------------------

class TestBotToBotMention:
    """Tests for _trigger_member_bot_replies — returns the list of triggered
    (bot_id, config) tuples. Background task execution is prevented via a
    no-op patch of ``_run_member_bot_reply`` so tests don't need the full
    LLM stack; the return value is the real observable."""

    @pytest.mark.asyncio
    async def test_when_response_has_no_tags_then_returns_empty(
        self, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        result = await _trigger_member_bot_replies(
            uuid.uuid4(), uuid.uuid4(), "primary-bot", "Hello, no mentions here."
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_when_response_is_empty_then_returns_empty(
        self, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        result = await _trigger_member_bot_replies(
            uuid.uuid4(), uuid.uuid4(), "primary-bot", ""
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_when_mention_non_member_bot_then_no_trigger(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.commit()

        with patch("app.routers.chat._multibot._run_member_bot_reply", new_callable=AsyncMock):
            result = await _trigger_member_bot_replies(
                channel.id, uuid.uuid4(), "primary-bot",
                "Hey @unknown_bot, what do you think?"
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_when_mention_member_bot_then_triggers_with_config(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot", config={"auto_respond": True},
        ))
        await db_session.commit()

        with patch("app.routers.chat._multibot._run_member_bot_reply", new_callable=AsyncMock):
            result = await _trigger_member_bot_replies(
                channel.id, uuid.uuid4(), "primary-bot",
                "Hey @helper-bot, can you help with this?"
            )

        assert result == [("helper-bot", {"auto_respond": True})]

    @pytest.mark.asyncio
    async def test_when_bot_mentions_itself_then_no_trigger(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot",
        ))
        await db_session.commit()

        with patch("app.routers.chat._multibot._run_member_bot_reply", new_callable=AsyncMock):
            result = await _trigger_member_bot_replies(
                channel.id, uuid.uuid4(), "helper-bot",
                "I am @helper-bot and I'm here."
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_when_at_max_depth_then_skips_db_entirely(
        self, patched_async_sessions
    ):
        """At max depth the function must return without touching the DB — the
        recursion guard runs before the member lookup query."""
        from app.routers.chat import _trigger_member_bot_replies, _MEMBER_MENTION_MAX_DEPTH

        with patch.object(patched_async_sessions, "__call__") as session_spy:
            result = await _trigger_member_bot_replies(
                uuid.uuid4(), uuid.uuid4(), "bot",
                "@helper-bot hello",
                _depth=_MEMBER_MENTION_MAX_DEPTH,
            )

        assert result == []
        session_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_bot_mentioned_twice_then_dedup_to_single_trigger(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot",
        ))
        await db_session.commit()

        with patch("app.routers.chat._multibot._run_member_bot_reply", new_callable=AsyncMock):
            result = await _trigger_member_bot_replies(
                channel.id, uuid.uuid4(), "primary-bot",
                "@helper-bot what do you think? Also @helper-bot please check this."
            )

        assert [bid for bid, _ in result] == ["helper-bot"]

    @pytest.mark.asyncio
    async def test_when_skill_typed_tag_matches_member_id_then_no_trigger(
        self, db_session, patched_async_sessions
    ):
        """``@skill:name`` must not be treated as a bot mention, even if a
        member bot happens to share the name."""
        from app.routers.chat import _trigger_member_bot_replies

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="myskill",
        ))
        await db_session.commit()

        with patch("app.routers.chat._multibot._run_member_bot_reply", new_callable=AsyncMock):
            result = await _trigger_member_bot_replies(
                channel.id, uuid.uuid4(), "primary-bot",
                "Let me check @skill:myskill for help."
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_when_channel_throttled_then_run_member_bot_reply_returns_early(self):
        from app.routers.chat import _run_member_bot_reply

        with patch("app.routers.chat._multibot._channel_throttled", return_value=True), \
             patch("app.db.engine.async_session") as session_spy:
            await _run_member_bot_reply(
                uuid.uuid4(), uuid.uuid4(), "helper-bot", {},
                "primary-bot",
            )

        session_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_session_lock_busy_then_retries_then_gives_up(self):
        """Lock contention → 30 retries at ~100ms each, then abort."""
        from app.routers.chat import _run_member_bot_reply

        with patch("app.routers.chat._multibot._channel_throttled", return_value=False), \
             patch("app.routers.chat._multibot.session_locks") as mock_locks, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_locks.acquire.return_value = False

            await _run_member_bot_reply(
                uuid.uuid4(), uuid.uuid4(), "helper-bot", {},
                "primary-bot",
            )

        assert mock_locks.acquire.call_count == 30


# ---------------------------------------------------------------------------
# History rewriting for member bots
# ---------------------------------------------------------------------------

class TestRewriteHistoryForMemberBot:
    """Tests for _rewrite_history_for_member_bot — ensures member bots
    have proper identity by rewriting other bots' messages."""

    def test_when_member_bot_is_message_sender_then_rewritten_to_user_role(self):
        """Member bot's own messages are rewritten to user role with attribution.

        This prevents poisoned history (prior identity-confused responses
        persisted with the member bot's sender_id) from teaching the model
        the wrong voice.
        """
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "You are helper."},
            {"role": "user", "content": "hello", "_metadata": {}},
            {"role": "assistant", "content": "Hi there!", "_metadata": {
                "sender_id": "bot:helper", "sender_display_name": "Helper Bot",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "[Helper Bot]: Hi there!"

    def test_when_other_bot_is_message_sender_then_rewritten_to_user_role(self):
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

    def test_when_message_has_no_sender_metadata_then_treated_as_other_bot(self):
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

    def test_when_no_metadata_and_no_primary_name_then_uses_fallback_other_bot_label(self):
        """Without primary_bot_name, fallback label is 'Other bot'."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "assistant", "content": "No metadata at all."},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "[Other bot]: No metadata at all."

    def test_when_other_bot_has_tool_calls_then_calls_and_results_dropped(self):
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

    def test_when_member_bot_has_tool_calls_then_calls_and_results_dropped(self):
        """Tool call messages from the member bot itself are dropped.

        Member bots get ALL assistant messages (including their own) rewritten
        or dropped to prevent poisoned history from reinforcing wrong identity.
        """
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

        # Tool call + tool result dropped, text response rewritten to user
        assert len(messages) == 2  # user + rewritten text
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "[Helper Bot]: Done!"

    def test_when_user_has_display_name_then_message_gets_bracketed_prefix(self):
        """User messages with sender_display_name get prefixed."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "What's up?", "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["content"] == "[Mike]: What's up?"

    def test_when_user_message_already_prefixed_then_not_double_prefixed(self):
        """Already-prefixed user messages aren't double-prefixed."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "[Mike]: hello", "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["content"] == "[Mike]: hello"

    def test_when_user_has_no_display_name_then_message_unchanged(self):
        """User messages without sender_display_name stay unchanged."""
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "user", "content": "just a message", "_metadata": {}},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["content"] == "just a message"

    def test_when_message_is_system_role_then_rewrite_history_leaves_it_unchanged(self):
        from app.routers.chat import _rewrite_history_for_member_bot

        messages = [
            {"role": "system", "content": "You are a helpful bot."},
        ]
        _rewrite_history_for_member_bot(messages, "helper")

        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful bot."

    def test_when_mixed_multi_bot_conversation_then_rewrites_preserve_member_perspective(self):
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
        # Dev bot's own response is rewritten to user (member bots get no assistant msgs)
        assert len(messages) == 4
        assert messages[3]["role"] == "user"
        assert messages[3]["content"] == "[Dev Bot]: I checked the CI — all green."

    def test_when_rewriting_from_primary_perspective_then_member_responses_attributed(self):
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

    def test_when_message_has_hidden_metadata_then_removed_during_rewrite(self):
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
        # Member bot's own message rewritten to user (no assistant msgs for members)
        assert messages[2]["role"] == "user"


# ---------------------------------------------------------------------------
# _inject_member_config
# ---------------------------------------------------------------------------

class TestInjectMemberConfig:
    def test_when_member_config_empty_then_no_injection(self):
        from app.routers.chat import _inject_member_config

        messages = [{"role": "system", "content": "base"}]
        _inject_member_config(messages, {})
        assert len(messages) == 1

    def test_when_system_prompt_addon_set_then_appended_as_system_message(self):
        from app.routers.chat import _inject_member_config

        messages = [{"role": "system", "content": "base"}]
        _inject_member_config(messages, {"system_prompt_addon": "Always be brief."})
        assert len(messages) == 2
        assert "Always be brief." in messages[1]["content"]
        assert messages[1]["role"] == "system"

    def test_when_response_style_set_then_style_instruction_added(self):
        from app.routers.chat import _inject_member_config

        messages = []
        _inject_member_config(messages, {"response_style": "brief"})
        assert len(messages) == 1
        assert "brief and concise" in messages[0]["content"]

    def test_when_addon_and_style_both_set_then_both_appear_in_injection(self):
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

    def test_when_sender_display_name_set_then_user_message_gets_prefix(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "hello", "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "[Mike]: hello"

    def test_when_no_metadata_present_then_content_unchanged(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "hello"},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "hello"

    def test_when_metadata_has_no_display_name_then_content_unchanged(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "hello", "_metadata": {}},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "hello"

    def test_when_message_already_prefixed_then_apply_attribution_skips(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "user", "content": "[Mike]: hello", "_metadata": {
                "sender_display_name": "Mike",
            }},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "[Mike]: hello"

    def test_when_message_is_assistant_role_then_apply_attribution_leaves_it_unchanged(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "assistant", "content": "hi", "_metadata": {
                "sender_display_name": "Bot",
            }},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "hi"

    def test_when_message_is_system_role_then_apply_attribution_leaves_it_unchanged(self):
        from app.routers.chat import _apply_user_attribution

        messages = [
            {"role": "system", "content": "prompt", "_metadata": {
                "sender_display_name": "System",
            }},
        ]
        _apply_user_attribution(messages)
        assert messages[0]["content"] == "prompt"

    def test_when_multiple_distinct_users_present_then_each_gets_own_prefix(self):
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

    def test_when_chained_after_member_bot_rewrite_then_no_double_prefix(self):
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

    def test_when_user_content_is_multimodal_list_then_apply_attribution_skips(self):
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

    def test_when_user_content_is_multimodal_list_then_rewrite_history_skips(self):
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

    def test_when_metadata_present_then_rewrite_distinguishes_member_own_vs_other(self):
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
        # Helper's own message also rewritten (member bots get no assistant msgs)
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "[Helper Bot]: Helper said this."

    def test_when_metadata_stripped_then_all_messages_treated_as_other_bot(self):
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

    def test_when_strip_metadata_keys_called_then_metadata_removed_from_messages(self):
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

    def test_when_is_primary_and_message_untagged_then_kept_as_assistant(self):
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

    def test_when_is_member_and_message_untagged_then_rewritten_to_user_role(self):
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
    async def test_when_member_mentions_primary_then_primary_returned_with_empty_config(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _detect_member_mentions

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot",
        ))
        await db_session.commit()

        result = await _detect_member_mentions(
            channel.id, "helper-bot", "Hey @primary-bot, can you check this?"
        )

        assert result == [("primary-bot", {})]

    @pytest.mark.asyncio
    async def test_when_primary_mentions_itself_then_no_trigger(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _detect_member_mentions

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot",
        ))
        await db_session.commit()

        result = await _detect_member_mentions(
            channel.id, "primary-bot", "I am @primary-bot."
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_when_chain_within_depth_limit_then_allowed_at_each_level(
        self, db_session, patched_async_sessions
    ):
        """Primary → member → primary → member is allowed at depths 0,1,2 and
        blocked at depth 3 (``_MEMBER_MENTION_MAX_DEPTH``)."""
        from app.routers.chat import _detect_member_mentions

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot", config={"auto_respond": True},
        ))
        await db_session.commit()

        depth0 = await _detect_member_mentions(
            channel.id, "primary-bot", "Hey @helper-bot check this", _depth=0,
        )
        depth1 = await _detect_member_mentions(
            channel.id, "helper-bot", "Done, @primary-bot here are results", _depth=1,
        )
        depth2 = await _detect_member_mentions(
            channel.id, "primary-bot", "@helper-bot one more thing", _depth=2,
        )
        depth3 = await _detect_member_mentions(
            channel.id, "helper-bot", "@primary-bot results", _depth=3,
        )

        assert (
            [bid for bid, _ in depth0],
            [bid for bid, _ in depth1],
            [bid for bid, _ in depth2],
            depth3,
        ) == (["helper-bot"], ["primary-bot"], ["helper-bot"], [])


# ---------------------------------------------------------------------------
# Parallel invocation & dedup
# ---------------------------------------------------------------------------

class TestParallelInvocation:
    """Tests for parallel member bot invocation features. Background task
    execution is prevented by patching ``_run_member_bot_reply`` to a no-op
    AsyncMock; the real observables are the return value of
    ``_trigger_member_bot_replies`` and the kwargs captured on that patched
    coroutine."""

    @pytest.mark.asyncio
    async def test_when_snapshot_provided_then_passed_through_to_member_reply(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot",
        ))
        await db_session.commit()
        snapshot = [{"role": "user", "content": "hi"}]

        with patch(
            "app.routers.chat._multibot._run_member_bot_reply", new_callable=AsyncMock
        ) as run_spy:
            result = await _trigger_member_bot_replies(
                channel.id, uuid.uuid4(), "primary-bot",
                "Hey @helper-bot help",
                messages_snapshot=snapshot,
            )
            # Let the background task actually await the spy
            await asyncio.sleep(0)

        assert [bid for bid, _ in result] == ["helper-bot"]
        assert run_spy.await_args.kwargs["messages_snapshot"] == snapshot

    @pytest.mark.asyncio
    async def test_when_bot_in_already_invoked_then_skipped(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot",
        ))
        await db_session.commit()

        with patch(
            "app.routers.chat._multibot._run_member_bot_reply", new_callable=AsyncMock
        ) as run_spy:
            result = await _trigger_member_bot_replies(
                channel.id, uuid.uuid4(), "primary-bot",
                "Hey @helper-bot help",
                already_invoked={"helper-bot"},
            )

        assert result == []
        run_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_multiple_members_mentioned_then_all_returned(
        self, db_session, patched_async_sessions
    ):
        from app.routers.chat import _trigger_member_bot_replies

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="bot-a",
        ))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="bot-b",
        ))
        await db_session.commit()

        with patch(
            "app.routers.chat._multibot._run_member_bot_reply", new_callable=AsyncMock
        ):
            result = await _trigger_member_bot_replies(
                channel.id, uuid.uuid4(), "primary-bot",
                "@bot-a and @bot-b both help",
            )

        assert sorted(bid for bid, _ in result) == ["bot-a", "bot-b"]

    @pytest.mark.asyncio
    async def test_when_snapshot_provided_then_run_member_bot_reply_skips_session_lock(
        self, db_session, patched_async_sessions, bot_registry
    ):
        """Snapshot path must bypass the per-session mutex — the whole point
        of passing the snapshot is parallel execution."""
        from app.routers.chat import _run_member_bot_reply

        bot_registry.register("helper-bot", name="Helper")
        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.commit()
        snapshot = [
            {"role": "system", "content": "You are helper."},
            {"role": "user", "content": "hello"},
        ]

        with patch("app.routers.chat._multibot._channel_throttled", return_value=False), \
             patch("app.routers.chat._multibot.session_locks") as mock_locks, \
             patch("app.routers.chat._multibot._record_channel_run"), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.loop.run_stream", side_effect=_fake_stream), \
             patch("app.services.channel_events.publish_typed"), \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: x):
            await _run_member_bot_reply(
                channel.id, uuid.uuid4(), "helper-bot", {},
                "primary-bot",
                messages_snapshot=snapshot,
                turn_id=uuid.uuid4(),
            )

        mock_locks.acquire.assert_not_called()
        mock_locks.release.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_member_response_mentions_another_bot_then_chained_trigger_passes_snapshot(
        self, db_session, patched_async_sessions, bot_registry
    ):
        from app.routers.chat import _run_member_bot_reply

        bot_registry.register("helper-bot", name="Helper")
        bot_registry.register("primary-bot", name="Primary")
        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.commit()
        messages_snapshot = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ]

        with patch("app.agent.loop.run_stream", side_effect=_fake_stream), \
             patch("app.services.channel_events.publish_typed"), \
             patch("app.services.sessions.persist_turn", new_callable=AsyncMock), \
             patch(
                 "app.routers.chat._multibot._trigger_member_bot_replies",
                 new_callable=AsyncMock,
             ) as mock_trigger, \
             patch(
                 "app.services.sessions._resolve_workspace_base_prompt_enabled",
                 new_callable=AsyncMock, return_value=False,
             ):
            await _run_member_bot_reply(
                channel.id, uuid.uuid4(), "helper-bot", {},
                "primary-bot", _depth=1,
                messages_snapshot=messages_snapshot,
                turn_id=uuid.uuid4(),
            )

        assert mock_trigger.await_args.kwargs.get("messages_snapshot") is not None

    @pytest.mark.asyncio
    async def test_when_user_mentions_multiple_bots_then_all_detected_except_responder(
        self, db_session, patched_async_sessions
    ):
        """primary-bot is the responder → it's excluded; helper-bot is
        returned. The responder-exclusion invariant lives in
        ``_detect_member_mentions``."""
        from app.routers.chat import _detect_member_mentions

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot",
        ))
        await db_session.commit()

        mentioned = await _detect_member_mentions(
            channel.id, "primary-bot",
            "Hey @bot:helper-bot and @bot:primary-bot check this out",
        )

        assert [bid for bid, _ in mentioned] == ["helper-bot"]

    @pytest.mark.asyncio
    async def test_when_user_invoked_bot_already_seen_then_response_mention_is_filtered(
        self, db_session, patched_async_sessions
    ):
        """Real callers combine user-mention detection with response-mention
        detection and filter via ``already_invoked``. This verifies the filter
        correctly dedupes cross-phase."""
        from app.routers.chat import _detect_member_mentions

        channel = await db_session.merge(build_channel(bot_id="primary-bot"))
        await db_session.merge(build_channel_bot_member(
            channel_id=channel.id, bot_id="helper-bot",
        ))
        await db_session.commit()

        user_phase = await _detect_member_mentions(
            channel.id, "primary-bot",
            "Hey @bot:helper-bot what do you think?",
        )
        response_phase = await _detect_member_mentions(
            channel.id, "primary-bot",
            "I agree with @helper-bot's take",
        )
        user_mentioned_ids = {bid for bid, _ in user_phase}
        filtered = [
            (bid, cfg) for bid, cfg in response_phase if bid not in user_mentioned_ids
        ]

        assert (user_mentioned_ids, filtered) == ({"helper-bot"}, [])


async def _fake_stream(*a, **kw):
    """Minimal fake for run_stream that yields a response event."""
    yield {"type": "response", "text": "ok", "client_actions": []}
