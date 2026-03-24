"""Tests for delegation dispatch logic — the part that keeps breaking.

Covers:
- Permission checks (allowlist, ephemeral, depth)
- client_actions propagation through both dispatch paths
- Streaming path (pending queue) vs non-streaming path (post_child_response)
- post_child_response forwarding client_actions to dispatcher
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.delegation import (
    DelegationDepthError,
    DelegationError,
    DelegationPermissionError,
    DelegationService,
)


def _make_parent_bot(**overrides):
    from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig

    defaults = dict(
        id="parent-bot",
        name="Parent",
        model="gpt-4",
        system_prompt="You are a parent bot.",
        delegate_bots=["child-bot"],
        memory=MemoryConfig(),
        knowledge=KnowledgeConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_child_bot(**overrides):
    from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig

    defaults = dict(
        id="child-bot",
        name="Child",
        model="gpt-4",
        system_prompt="You are a child bot.",
        memory=MemoryConfig(),
        knowledge=KnowledgeConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------

class TestDelegationPermissions:
    @pytest.mark.asyncio
    async def test_no_delegate_bots_raises(self):
        svc = DelegationService()
        parent = _make_parent_bot(delegate_bots=[])
        with pytest.raises(DelegationError, match="Delegation is disabled"):
            await svc.run_immediate(
                parent_session_id=uuid.uuid4(),
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="test",
                dispatch_type=None,
                dispatch_config=None,
                depth=0,
                root_session_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_depth_limit_raises(self):
        svc = DelegationService()
        parent = _make_parent_bot()
        with patch("app.services.delegation.settings") as s:
            s.DELEGATION_MAX_DEPTH = 2
            with pytest.raises(DelegationDepthError, match="depth limit"):
                await svc.run_immediate(
                    parent_session_id=uuid.uuid4(),
                    parent_bot=parent,
                    delegate_bot_id="child-bot",
                    prompt="test",
                    dispatch_type=None,
                    dispatch_config=None,
                    depth=2,
                    root_session_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_bot_not_in_allowlist_raises(self):
        svc = DelegationService()
        parent = _make_parent_bot(delegate_bots=["other-bot"])
        with patch("app.services.delegation.settings") as s:
            s.DELEGATION_MAX_DEPTH = 5
            with pytest.raises(DelegationPermissionError, match="not allowed"):
                await svc.run_immediate(
                    parent_session_id=uuid.uuid4(),
                    parent_bot=parent,
                    delegate_bot_id="child-bot",
                    prompt="test",
                    dispatch_type=None,
                    dispatch_config=None,
                    depth=0,
                    root_session_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_ephemeral_bypasses_allowlist(self):
        """ephemeral_delegate=True skips the allowlist check."""
        svc = DelegationService()
        parent = _make_parent_bot(delegate_bots=["other-bot"])
        child = _make_child_bot()

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "done", "client_actions": []}

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.bots.get_bot", return_value=child), \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.context.snapshot_agent_context", return_value={}), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.context.restore_agent_context"):
            s.DELEGATION_MAX_DEPTH = 5
            result = await svc.run_immediate(
                parent_session_id=uuid.uuid4(),
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="test",
                dispatch_type=None,
                dispatch_config=None,
                depth=0,
                root_session_id=uuid.uuid4(),
                ephemeral_delegate=True,
            )
            assert result == "done"


# ---------------------------------------------------------------------------
# Dispatch path: streaming (pending queue exists)
# ---------------------------------------------------------------------------

class TestStreamingDispatchPath:
    """When current_pending_delegation_posts is not None (streaming context),
    delegation appends to the shared list instead of calling post_child_response."""

    @pytest.mark.asyncio
    async def test_appends_to_pending_with_client_actions(self):
        svc = DelegationService()
        parent = _make_parent_bot()
        child = _make_child_bot()

        fake_actions = [{"type": "upload_image", "data": "abc123", "filename": "img.png"}]

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "here is your image", "client_actions": fake_actions}

        pending_list: list = []

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.bots.get_bot", return_value=child), \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.context.snapshot_agent_context", return_value={}), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.context.restore_agent_context"), \
             patch("app.agent.context.current_pending_delegation_posts") as mock_cv, \
             patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock) as mock_echo:
            s.DELEGATION_MAX_DEPTH = 5
            mock_cv.get.return_value = pending_list

            result = await svc.run_immediate(
                parent_session_id=uuid.uuid4(),
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="generate an image",
                dispatch_type="slack",
                dispatch_config={"channel_id": "C123", "token": "xoxb-test"},
                depth=0,
                root_session_id=uuid.uuid4(),
            )

        assert result == "here is your image"
        assert len(pending_list) == 1
        post = pending_list[0]
        assert post["text"] == "here is your image"
        assert post["bot_id"] == "child-bot"
        assert post["client_actions"] == fake_actions
        mock_echo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_dispatch_when_response_empty(self):
        """Empty child response → skip dispatch entirely."""
        svc = DelegationService()
        parent = _make_parent_bot()
        child = _make_child_bot()

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "", "client_actions": []}

        pending_list: list = []

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.bots.get_bot", return_value=child), \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.context.snapshot_agent_context", return_value={}), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.context.restore_agent_context"), \
             patch("app.agent.context.current_pending_delegation_posts") as mock_cv:
            s.DELEGATION_MAX_DEPTH = 5
            mock_cv.get.return_value = pending_list

            result = await svc.run_immediate(
                parent_session_id=uuid.uuid4(),
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="test",
                dispatch_type="slack",
                dispatch_config={"channel_id": "C123"},
                depth=0,
                root_session_id=uuid.uuid4(),
            )

        assert result == ""
        assert len(pending_list) == 0  # nothing appended


# ---------------------------------------------------------------------------
# Dispatch path: non-streaming (pending queue is None — task worker / keepalive boundary)
# ---------------------------------------------------------------------------

class TestNonStreamingDispatchPath:
    """When current_pending_delegation_posts is None, delegation calls
    post_child_response directly. This is the path that was broken — it
    was dropping client_actions."""

    @pytest.mark.asyncio
    async def test_calls_post_child_response_with_client_actions(self):
        svc = DelegationService()
        parent = _make_parent_bot()
        child = _make_child_bot()

        fake_actions = [{"type": "upload_image", "data": "abc123", "filename": "img.png"}]

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "image result", "client_actions": fake_actions}

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.bots.get_bot", return_value=child), \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.context.snapshot_agent_context", return_value={}), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.context.restore_agent_context"), \
             patch("app.agent.context.current_pending_delegation_posts") as mock_cv, \
             patch.object(svc, "post_child_response", new_callable=AsyncMock, return_value=True) as mock_post, \
             patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock) as mock_echo:
            s.DELEGATION_MAX_DEPTH = 5
            mock_cv.get.return_value = None  # non-streaming path

            session_id = uuid.uuid4()
            dispatch_cfg = {"channel_id": "C123", "token": "xoxb-test"}

            result = await svc.run_immediate(
                parent_session_id=session_id,
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="generate image",
                dispatch_type="slack",
                dispatch_config=dispatch_cfg,
                depth=0,
                root_session_id=uuid.uuid4(),
                client_id="slack:C123",
            )

        assert result == "image result"
        mock_post.assert_awaited_once_with(
            "slack", dispatch_cfg, "image result",
            "child-bot", reply_in_thread=False,
            client_actions=fake_actions,
        )
        mock_echo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_echo_when_post_fails(self):
        """If dispatcher returns False, store_dispatch_echo is NOT called."""
        svc = DelegationService()
        parent = _make_parent_bot()
        child = _make_child_bot()

        async def fake_stream(*a, **kw):
            yield {"type": "response", "text": "hello", "client_actions": []}

        with patch("app.services.delegation.settings") as s, \
             patch("app.agent.bots.get_bot", return_value=child), \
             patch("app.agent.loop.run_stream", side_effect=fake_stream), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.context.snapshot_agent_context", return_value={}), \
             patch("app.agent.context.set_agent_context"), \
             patch("app.agent.context.restore_agent_context"), \
             patch("app.agent.context.current_pending_delegation_posts") as mock_cv, \
             patch.object(svc, "post_child_response", new_callable=AsyncMock, return_value=False), \
             patch("app.services.sessions.store_dispatch_echo", new_callable=AsyncMock) as mock_echo:
            s.DELEGATION_MAX_DEPTH = 5
            mock_cv.get.return_value = None

            await svc.run_immediate(
                parent_session_id=uuid.uuid4(),
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="test",
                dispatch_type="slack",
                dispatch_config={"channel_id": "C123", "token": "xoxb-test"},
                depth=0,
                root_session_id=uuid.uuid4(),
            )

        mock_echo.assert_not_awaited()


# ---------------------------------------------------------------------------
# post_child_response forwards client_actions to dispatcher
# ---------------------------------------------------------------------------

class TestPostChildResponse:
    @pytest.mark.asyncio
    async def test_forwards_client_actions(self):
        svc = DelegationService()
        fake_actions = [{"type": "upload_image", "data": "base64data"}]
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)

        with patch("app.agent.dispatchers.get", return_value=mock_dispatcher):
            ok = await svc.post_child_response(
                dispatch_type="slack",
                dispatch_config={"channel_id": "C123", "token": "xoxb-test"},
                text="here is the image",
                bot_id="child-bot",
                client_actions=fake_actions,
            )

        assert ok is True
        mock_dispatcher.post_message.assert_awaited_once()
        call_kwargs = mock_dispatcher.post_message.call_args
        assert call_kwargs.kwargs["client_actions"] == fake_actions
        assert call_kwargs.kwargs["bot_id"] == "child-bot"

    @pytest.mark.asyncio
    async def test_none_client_actions_forwarded(self):
        """client_actions=None should be forwarded without error."""
        svc = DelegationService()
        mock_dispatcher = MagicMock()
        mock_dispatcher.post_message = AsyncMock(return_value=True)

        with patch("app.agent.dispatchers.get", return_value=mock_dispatcher):
            ok = await svc.post_child_response(
                dispatch_type="slack",
                dispatch_config={"channel_id": "C123"},
                text="text only",
                bot_id="child-bot",
                client_actions=None,
            )

        assert ok is True
        assert mock_dispatcher.post_message.call_args.kwargs["client_actions"] is None

    @pytest.mark.asyncio
    async def test_unknown_dispatch_type_returns_false(self):
        """Unknown dispatch type falls back to NoneDispatcher which returns False."""
        svc = DelegationService()
        ok = await svc.post_child_response(
            dispatch_type="nonexistent",
            dispatch_config={},
            text="test",
            bot_id="bot",
        )
        assert ok is False


# ---------------------------------------------------------------------------
# run_deferred propagates channel_id
# ---------------------------------------------------------------------------

class TestRunDeferredChannelId:
    @pytest.mark.asyncio
    async def test_channel_id_set_on_task(self):
        """run_deferred must set channel_id on the Task so the child bot can access attachments."""
        svc = DelegationService()
        parent = _make_parent_bot()
        channel_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.delegation.async_session", return_value=cm):
            await svc.run_deferred(
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="generate an image",
                dispatch_type="slack",
                dispatch_config={"channel_id": "C123", "token": "xoxb-test"},
                scheduled_at=None,
                client_id="slack:C123",
                parent_session_id=uuid.uuid4(),
                channel_id=channel_id,
            )

        db.add.assert_called_once()
        task = db.add.call_args[0][0]
        assert task.channel_id == channel_id

    @pytest.mark.asyncio
    async def test_channel_id_none_when_not_provided(self):
        """channel_id defaults to None when not provided (backwards compat)."""
        svc = DelegationService()
        parent = _make_parent_bot()

        db = AsyncMock()
        db.add = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.delegation.async_session", return_value=cm):
            await svc.run_deferred(
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="test",
                dispatch_type="none",
                dispatch_config={},
                scheduled_at=None,
            )

        task = db.add.call_args[0][0]
        assert task.channel_id is None
