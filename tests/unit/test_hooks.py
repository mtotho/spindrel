"""Tests for the integration hook system (app/agent/hooks.py)."""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.hooks import (
    HookContext,
    IntegrationMeta,
    _lifecycle_hooks,
    _meta_registry,
    fire_hook,
    get_all_client_id_prefixes,
    get_integration_meta,
    get_user_attribution,
    register_hook,
    register_integration,
    resolve_all_display_names,
)


@pytest.fixture(autouse=True)
def _clean_registries():
    """Ensure registries are clean before/after each test."""
    saved_meta = dict(_meta_registry)
    saved_hooks = {k: list(v) for k, v in _lifecycle_hooks.items()}
    _meta_registry.clear()
    _lifecycle_hooks.clear()
    yield
    _meta_registry.clear()
    _meta_registry.update(saved_meta)
    _lifecycle_hooks.clear()
    _lifecycle_hooks.update(saved_hooks)


def test_register_integration():
    """Register an integration and verify prefix is returned."""
    meta = IntegrationMeta(
        integration_type="test",
        client_id_prefix="test:",
    )
    register_integration(meta)

    assert get_integration_meta("test") is meta
    assert "test:" in get_all_client_id_prefixes()


def test_user_attribution_dispatch():
    """Register a mock user_attribution and verify routing."""
    def _mock_attr(user):
        return {"username": user.name, "icon_emoji": ":robot:"}

    register_integration(IntegrationMeta(
        integration_type="mock",
        client_id_prefix="mock:",
        user_attribution=_mock_attr,
    ))

    user = MagicMock()
    user.name = "testuser"
    result = get_user_attribution("mock", user)
    assert result == {"username": "testuser", "icon_emoji": ":robot:"}


def test_user_attribution_unknown():
    """Unregistered integration type returns empty dict."""
    user = MagicMock()
    result = get_user_attribution("nonexistent", user)
    assert result == {}


def test_user_attribution_error_swallowed():
    """If user_attribution callback raises, return empty dict."""
    def _bad_attr(user):
        raise ValueError("boom")

    register_integration(IntegrationMeta(
        integration_type="bad",
        client_id_prefix="bad:",
        user_attribution=_bad_attr,
    ))

    result = get_user_attribution("bad", MagicMock())
    assert result == {}


@pytest.mark.asyncio
async def test_lifecycle_hook_fire():
    """Register a callback, fire the event, verify it was called."""
    calls = []

    async def _on_tool_call(ctx, **kwargs):
        calls.append(ctx)

    register_hook("after_tool_call", _on_tool_call)

    ctx = HookContext(bot_id="test-bot", extra={"tool_name": "web_search"})
    await fire_hook("after_tool_call", ctx)

    assert len(calls) == 1
    assert calls[0].bot_id == "test-bot"
    assert calls[0].extra["tool_name"] == "web_search"


@pytest.mark.asyncio
async def test_lifecycle_hook_error_swallowed():
    """A raising callback doesn't propagate the exception."""
    async def _bad_hook(ctx, **kwargs):
        raise RuntimeError("hook exploded")

    register_hook("after_response", _bad_hook)

    # Should not raise
    await fire_hook("after_response", HookContext(bot_id="test"))


@pytest.mark.asyncio
async def test_lifecycle_hook_sync_callback():
    """Sync callbacks also work."""
    calls = []

    def _sync_hook(ctx, **kwargs):
        calls.append(ctx.extra.get("data"))

    register_hook("test_sync", _sync_hook)
    await fire_hook("test_sync", HookContext(extra={"data": "hello"}))

    assert calls == ["hello"]


@pytest.mark.asyncio
async def test_fire_hook_no_listeners():
    """Firing an event with no listeners is a no-op."""
    # Should not raise
    await fire_hook("nonexistent_event", HookContext())


def test_client_id_prefix_dynamic():
    """Register a prefix and verify is_integration_client_id recognizes it."""
    from app.services.channels import is_integration_client_id

    register_integration(IntegrationMeta(
        integration_type="custom",
        client_id_prefix="custom:",
    ))

    assert is_integration_client_id("custom:chan123") is True
    assert is_integration_client_id("unknown:chan123") is False


@pytest.mark.asyncio
async def test_resolve_all_display_names():
    """resolve_all_display_names dispatches to registered integrations."""
    async def _mock_resolve(channels):
        return {ch.id: f"#{ch.name}" for ch in channels}

    register_integration(IntegrationMeta(
        integration_type="test",
        client_id_prefix="test:",
        resolve_display_names=_mock_resolve,
    ))

    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.name = "general"
    ch.integration = "test"

    result = await resolve_all_display_names([ch])
    assert result[ch.id] == "#general"


@pytest.mark.asyncio
async def test_resolve_display_names_error_swallowed():
    """If an integration's resolve_display_names raises, it's swallowed."""
    async def _bad_resolve(channels):
        raise RuntimeError("API down")

    register_integration(IntegrationMeta(
        integration_type="broken",
        client_id_prefix="broken:",
        resolve_display_names=_bad_resolve,
    ))

    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.integration = "broken"

    # Should not raise
    result = await resolve_all_display_names([ch])
    assert result == {}


# ---------------------------------------------------------------------------
# Slack reaction hook tests
# ---------------------------------------------------------------------------

class TestSlackReactionHooks:
    """Test the Slack emoji reaction lifecycle hooks."""

    @pytest.fixture(autouse=True)
    def _clean_active_reactions(self):
        from integrations.slack.hooks import _active_reactions
        saved = dict(_active_reactions)
        _active_reactions.clear()
        yield
        _active_reactions.clear()
        _active_reactions.update(saved)

    @pytest.mark.asyncio
    @patch("integrations.slack.hooks._slack_react", new_callable=AsyncMock)
    @patch("integrations.slack.hooks._get_slack_ref")
    async def test_after_tool_call_adds_reactions(self, mock_ref, mock_react):
        """First tool call adds hourglass + tool emoji."""
        mock_ref.return_value = ("C123", "1234.5678", "xoxb-token")

        from integrations.slack.hooks import _on_after_tool_call
        ctx = HookContext(
            correlation_id=uuid.uuid4(),
            extra={"tool_name": "web_search"},
        )
        await _on_after_tool_call(ctx)

        # Should add hourglass (first tool) + mag (search tool)
        calls = mock_react.call_args_list
        assert len(calls) == 2
        assert calls[0].args == ("xoxb-token", "C123", "1234.5678", "hourglass_flowing_sand")
        assert calls[1].args == ("xoxb-token", "C123", "1234.5678", "mag")

    @pytest.mark.asyncio
    @patch("integrations.slack.hooks._slack_react", new_callable=AsyncMock)
    @patch("integrations.slack.hooks._get_slack_ref")
    async def test_after_tool_call_deduplicates_emoji(self, mock_ref, mock_react):
        """Same emoji not added twice for same correlation."""
        mock_ref.return_value = ("C123", "1234.5678", "xoxb-token")
        corr = uuid.uuid4()

        from integrations.slack.hooks import _on_after_tool_call
        ctx1 = HookContext(correlation_id=corr, extra={"tool_name": "web_search"})
        ctx2 = HookContext(correlation_id=corr, extra={"tool_name": "search_docs"})
        await _on_after_tool_call(ctx1)
        mock_react.reset_mock()
        await _on_after_tool_call(ctx2)

        # Second call: mag already added, hourglass already added → no new calls
        assert mock_react.call_count == 0

    @pytest.mark.asyncio
    @patch("integrations.slack.hooks._slack_react", new_callable=AsyncMock)
    @patch("integrations.slack.hooks._get_slack_ref")
    async def test_after_response_cleans_up(self, mock_ref, mock_react):
        """after_response removes hourglass, adds checkmark."""
        mock_ref.return_value = ("C123", "1234.5678", "xoxb-token")
        corr = uuid.uuid4()

        from integrations.slack.hooks import _on_after_tool_call, _on_after_response
        # Simulate a tool call first
        await _on_after_tool_call(HookContext(correlation_id=corr, extra={"tool_name": "exec_command"}))
        mock_react.reset_mock()

        # Now response fires
        await _on_after_response(HookContext(correlation_id=corr, extra={}))

        calls = mock_react.call_args_list
        # Remove hourglass + add checkmark
        assert len(calls) == 2
        assert calls[0].args == ("xoxb-token", "C123", "1234.5678", "hourglass_flowing_sand")
        assert calls[0].kwargs == {"remove": True}
        assert calls[1].args == ("xoxb-token", "C123", "1234.5678", "white_check_mark")

    @pytest.mark.asyncio
    @patch("integrations.slack.hooks._slack_react", new_callable=AsyncMock)
    @patch("integrations.slack.hooks._get_slack_ref")
    async def test_after_response_noop_without_tools(self, mock_ref, mock_react):
        """If no tool calls were made, after_response adds no reactions."""
        mock_ref.return_value = ("C123", "1234.5678", "xoxb-token")

        from integrations.slack.hooks import _on_after_response
        await _on_after_response(HookContext(correlation_id=uuid.uuid4(), extra={}))

        assert mock_react.call_count == 0

    @pytest.mark.asyncio
    @patch("integrations.slack.hooks._slack_react", new_callable=AsyncMock)
    @patch("integrations.slack.hooks._get_slack_ref")
    async def test_skips_non_slack_dispatch(self, mock_ref, mock_react):
        """Hook is a no-op when dispatch isn't Slack."""
        mock_ref.return_value = (None, None, None)

        from integrations.slack.hooks import _on_after_tool_call
        await _on_after_tool_call(HookContext(
            correlation_id=uuid.uuid4(),
            extra={"tool_name": "web_search"},
        ))

        assert mock_react.call_count == 0

    def test_emoji_for_tool_mapping(self):
        """Verify emoji mapping for common tool names."""
        from integrations.slack.hooks import _emoji_for_tool
        assert _emoji_for_tool("web_search") == "mag"
        assert _emoji_for_tool("exec_sandbox") == "computer"
        assert _emoji_for_tool("save_memory") == "brain"
        assert _emoji_for_tool("read_file") == "eyes"
        assert _emoji_for_tool("write_document") == "pencil2"
        assert _emoji_for_tool("delegate_to_agent") == "speech_balloon"
        assert _emoji_for_tool("some_unknown_tool") == "gear"
