"""Tests for the unified prepare_bot_context() pipeline.

Covers:
- Primary bot: no swap, no preamble, attribution applied
- Routed bot: system prompt swapped, preamble with "NOT {primary}"
- Member bot snapshot: user prompt extraction, preamble with mentioning bot
- Pipeline order: rewrite → attribution → strip → inject (invariant)
- _build_identity_preamble: primary→None, routed→"NOT", mention→name, invocation→message
"""
import copy
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_bot(**overrides):
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


PRIMARY = _make_bot(id="primary-bot", name="Primary Bot", system_prompt="I am primary.")
MEMBER = _make_bot(id="helper", name="Helper Bot", system_prompt="I am helper.", persona=False)
MENTIONER = _make_bot(id="mentioner", name="Mentioner Bot")


def _base_messages():
    """Minimal message list with system + one user message."""
    return [
        {"role": "system", "content": "I am primary."},
        {"role": "user", "content": "hello", "_metadata": {"sender_display_name": "Alice", "sender_type": "human"}},
    ]


# ---------------------------------------------------------------------------
# TestPrimaryBot
# ---------------------------------------------------------------------------

class TestPrimaryBot:
    @pytest.mark.asyncio
    async def test_no_system_prompt_swap(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        with patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
            {k: v for k, v in m.items() if k != "_metadata"} for m in x
        ]):
            ctx = await prepare_bot_context(
                messages=messages, bot=PRIMARY,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
            )
        # System prompt unchanged (primary keeps its own)
        sys_msgs = [m for m in ctx.messages if m.get("role") == "system"]
        assert any("I am primary" in m["content"] for m in sys_msgs)

    @pytest.mark.asyncio
    async def test_no_preamble(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        with patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
            {k: v for k, v in m.items() if k != "_metadata"} for m in x
        ]):
            ctx = await prepare_bot_context(
                messages=messages, bot=PRIMARY,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
            )
        assert ctx.system_preamble is None
        assert ctx.is_primary is True

    @pytest.mark.asyncio
    async def test_metadata_stripped(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        with patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
            {k: v for k, v in m.items() if k != "_metadata"} for m in x
        ]):
            ctx = await prepare_bot_context(
                messages=messages, bot=PRIMARY,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
            )
        for msg in ctx.messages:
            assert "_metadata" not in msg

    @pytest.mark.asyncio
    async def test_user_attribution_applied(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        with patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
            {k: v for k, v in m.items() if k != "_metadata"} for m in x
        ]):
            ctx = await prepare_bot_context(
                messages=messages, bot=PRIMARY,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
            )
        user_msgs = [m for m in ctx.messages if m.get("role") == "user"]
        assert user_msgs[0]["content"].startswith("[Alice]:")

    @pytest.mark.asyncio
    async def test_raw_snapshot_includes_user_message(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        with patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
            {k: v for k, v in m.items() if k != "_metadata"} for m in x
        ]):
            ctx = await prepare_bot_context(
                messages=messages, bot=PRIMARY,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                user_message="new question", msg_metadata={"sender_type": "human"},
            )
        # raw_snapshot should include the appended user message
        assert ctx.raw_snapshot[-1]["role"] == "user"
        assert ctx.raw_snapshot[-1]["content"] == "new question"


# ---------------------------------------------------------------------------
# TestRoutedBot
# ---------------------------------------------------------------------------

class TestRoutedBot:
    @pytest.mark.asyncio
    async def test_system_prompt_swapped(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        with patch("app.agent.bots.get_bot", side_effect=lambda bid: PRIMARY if bid == "primary-bot" else MEMBER), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db,
            )
        sys_msgs = [m for m in ctx.messages if m.get("role") == "system"]
        assert sys_msgs[0]["content"] == "I am helper."
        assert not any("I am primary" in m["content"] for m in sys_msgs)

    @pytest.mark.asyncio
    async def test_preamble_generated(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        with patch("app.agent.bots.get_bot", side_effect=lambda bid: PRIMARY if bid == "primary-bot" else MEMBER), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db,
            )
        assert ctx.system_preamble is not None
        assert "You are NOT Primary Bot" in ctx.system_preamble
        assert "Helper Bot" in ctx.system_preamble

    @pytest.mark.asyncio
    async def test_member_config_applied(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        config = {"response_style": "brief", "system_prompt_addon": "Be extra helpful.", "model_override": "gpt-3.5"}
        with patch("app.agent.bots.get_bot", side_effect=lambda bid: PRIMARY if bid == "primary-bot" else MEMBER), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                member_config=config, db=db,
            )
        config_msgs = [m for m in ctx.messages if "Member bot instructions" in m.get("content", "")]
        assert len(config_msgs) == 1
        assert "Be extra helpful" in config_msgs[0]["content"]
        assert "brief" in config_msgs[0]["content"].lower()
        assert ctx.model_override == "gpt-3.5"

    @pytest.mark.asyncio
    async def test_history_rewritten(self):
        from app.services.turn_context import prepare_bot_context

        messages = [
            {"role": "system", "content": "I am primary."},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "I'm primary", "_metadata": {"sender_id": "bot:primary-bot", "sender_display_name": "Primary Bot"}},
            {"role": "user", "content": "now talk to helper"},
        ]
        with patch("app.agent.bots.get_bot", side_effect=lambda bid: PRIMARY if bid == "primary-bot" else MEMBER), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db,
            )
        # Primary bot's assistant message should be rewritten to user with attribution
        rewritten = [m for m in ctx.messages if m.get("role") == "user" and "[Primary Bot]:" in m.get("content", "")]
        assert len(rewritten) == 1


# ---------------------------------------------------------------------------
# TestMemberBotSnapshot
# ---------------------------------------------------------------------------

class TestMemberBotSnapshot:
    @pytest.mark.asyncio
    async def test_user_prompt_extracted_from_snapshot_end(self):
        from app.services.turn_context import prepare_bot_context

        messages = [
            {"role": "user", "content": "earlier msg"},
            {"role": "assistant", "content": "bot response", "_metadata": {"sender_id": "bot:primary-bot"}},
            {"role": "user", "content": "latest question", "_metadata": {"sender_type": "human"}},
        ]
        with patch("app.agent.bots.get_bot", return_value=PRIMARY), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db, from_snapshot=True,
                mentioning_bot_id="primary-bot",
            )
        assert ctx.extracted_user_prompt == "latest question"
        # Extracted message should be removed from messages (no duplication)
        user_msgs = [m for m in ctx.messages if m.get("role") == "user"]
        assert not any("latest question" in m.get("content", "") for m in user_msgs)

    @pytest.mark.asyncio
    async def test_bot_messages_at_end_not_extracted(self):
        from app.services.turn_context import prepare_bot_context

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "bot response", "_metadata": {"sender_id": "bot:primary-bot", "sender_type": "bot"}},
        ]
        with patch("app.agent.bots.get_bot", return_value=PRIMARY), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db, from_snapshot=True,
                mentioning_bot_id="primary-bot",
            )
        assert ctx.extracted_user_prompt == ""

    @pytest.mark.asyncio
    async def test_mentioning_bot_name_in_preamble(self):
        from app.services.turn_context import prepare_bot_context

        messages = [
            {"role": "user", "content": "hello", "_metadata": {"sender_type": "human"}},
        ]
        with patch("app.agent.bots.get_bot", side_effect=lambda bid: MENTIONER if bid == "mentioner" else PRIMARY), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db, from_snapshot=True,
                mentioning_bot_id="mentioner",
            )
        assert "Mentioner Bot" in ctx.system_preamble
        assert "mentioned you" in ctx.system_preamble

    @pytest.mark.asyncio
    async def test_invocation_message_in_preamble(self):
        from app.services.turn_context import prepare_bot_context

        messages = [
            {"role": "user", "content": "hello", "_metadata": {"sender_type": "human"}},
        ]
        with patch("app.agent.bots.get_bot", side_effect=lambda bid: MENTIONER if bid == "mentioner" else PRIMARY), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db, from_snapshot=True,
                mentioning_bot_id="mentioner",
                invocation_message="please help with this",
            )
        assert "invoked you" in ctx.system_preamble
        assert "please help with this" in ctx.system_preamble

    @pytest.mark.asyncio
    async def test_extracted_msg_removed_even_with_member_config(self):
        """Regression: _inject_member_config appends system msg, which broke the
        messages[-1].role == 'user' check for removing the extracted message."""
        from app.services.turn_context import prepare_bot_context

        messages = [
            {"role": "user", "content": "earlier msg"},
            {"role": "user", "content": "latest question", "_metadata": {"sender_type": "human"}},
        ]
        config = {"response_style": "brief", "system_prompt_addon": "Be terse."}
        with patch("app.agent.bots.get_bot", return_value=PRIMARY), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                member_config=config, db=db, from_snapshot=True,
                mentioning_bot_id="primary-bot",
            )
        assert ctx.extracted_user_prompt == "latest question"
        # The extracted user message must NOT appear in ctx.messages
        user_msgs = [m for m in ctx.messages if m.get("role") == "user"]
        assert not any("latest question" in m.get("content", "") for m in user_msgs)
        # But member config system message should still be present
        config_msgs = [m for m in ctx.messages if "Member bot instructions" in m.get("content", "")]
        assert len(config_msgs) == 1

    @pytest.mark.asyncio
    async def test_user_attribution_applied_in_member_path(self):
        """This is THE BUG FIX: _apply_user_attribution was missing from member bot path."""
        from app.services.turn_context import prepare_bot_context

        messages = [
            {"role": "user", "content": "hello from bob", "_metadata": {"sender_display_name": "Bob", "sender_type": "human"}},
            {"role": "user", "content": "hello from carol", "_metadata": {"sender_display_name": "Carol", "sender_type": "human"}},
        ]
        with patch("app.agent.bots.get_bot", return_value=PRIMARY), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db, from_snapshot=True,
                mentioning_bot_id="primary-bot",
            )
        # Both user messages should have attribution prefixes
        user_msgs = [m for m in ctx.messages if m.get("role") == "user"]
        assert any("[Bob]:" in m.get("content", "") for m in user_msgs)


# ---------------------------------------------------------------------------
# TestPipelineOrder
# ---------------------------------------------------------------------------

class TestPipelineOrder:
    @pytest.mark.asyncio
    async def test_raw_snapshot_captured_before_rewrite(self):
        """Raw snapshot must be captured BEFORE rewrite mutates messages."""
        from app.services.turn_context import prepare_bot_context

        messages = [
            {"role": "system", "content": "I am primary."},
            {"role": "assistant", "content": "hello from other bot", "_metadata": {"sender_id": "bot:other-bot", "sender_display_name": "Other"}},
            {"role": "user", "content": "test"},
        ]
        with patch("app.agent.bots.get_bot", return_value=PRIMARY), \
             patch("app.services.sessions._effective_system_prompt", return_value="I am helper."), \
             patch("app.services.sessions._resolve_workspace_base_prompt_enabled", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
                 {k: v for k, v in m.items() if k != "_metadata"} for m in x
             ]):
            db = AsyncMock()
            ctx = await prepare_bot_context(
                messages=messages, bot=MEMBER,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
                db=db,
            )
        # raw_snapshot should have the original assistant message (not rewritten)
        assistant_msgs = [m for m in ctx.raw_snapshot if m.get("role") == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "hello from other bot"
        assert "_metadata" in assistant_msgs[0]

    @pytest.mark.asyncio
    async def test_strip_removes_metadata(self):
        from app.services.turn_context import prepare_bot_context

        messages = _base_messages()
        with patch("app.services.sessions.strip_metadata_keys", side_effect=lambda x: [
            {k: v for k, v in m.items() if k != "_metadata"} for m in x
        ]):
            ctx = await prepare_bot_context(
                messages=messages, bot=PRIMARY,
                primary_bot_id="primary-bot", channel_id=uuid.uuid4(),
            )
        for msg in ctx.messages:
            assert "_metadata" not in msg


# ---------------------------------------------------------------------------
# TestBuildIdentityPreamble
# ---------------------------------------------------------------------------

class TestBuildIdentityPreamble:
    def test_primary_returns_none(self):
        from app.services.turn_context import _build_identity_preamble

        result = _build_identity_preamble(
            bot=PRIMARY, primary_bot_id="primary-bot",
            primary_bot_name="Primary Bot", is_primary=True,
        )
        assert result is None

    def test_routed_includes_not_primary(self):
        from app.services.turn_context import _build_identity_preamble

        result = _build_identity_preamble(
            bot=MEMBER, primary_bot_id="primary-bot",
            primary_bot_name="Primary Bot", is_primary=False,
        )
        assert "You are NOT Primary Bot" in result
        assert "Helper Bot" in result
        assert "Respond only as Helper Bot" in result

    def test_mentioned_includes_mentioning_bot_name(self):
        from app.services.turn_context import _build_identity_preamble

        with patch("app.agent.bots.get_bot", return_value=MENTIONER):
            result = _build_identity_preamble(
                bot=MEMBER, primary_bot_id="primary-bot",
                primary_bot_name="Primary Bot", is_primary=False,
                mentioning_bot_id="mentioner",
            )
        assert "Mentioner Bot" in result
        assert "mentioned you" in result

    def test_invoked_includes_invocation_message(self):
        from app.services.turn_context import _build_identity_preamble

        with patch("app.agent.bots.get_bot", return_value=MENTIONER):
            result = _build_identity_preamble(
                bot=MEMBER, primary_bot_id="primary-bot",
                primary_bot_name="Primary Bot", is_primary=False,
                mentioning_bot_id="mentioner",
                invocation_message="help with code review",
            )
        assert "invoked you" in result
        assert "help with code review" in result
