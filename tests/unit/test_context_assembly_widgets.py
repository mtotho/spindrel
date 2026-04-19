"""Integration-ish test: `assemble_context` injects pinned-widget state.

Focuses solely on the hook wired after the temporal block in
`app/agent/context_assembly.py`. Verifies that a channel with pins on its
implicit widget dashboard (``widget_dashboard_pins`` at
``channel:<uuid>``) produces a system message whose content comes from
``build_widget_context_block``.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.bots import BotConfig
from app.agent.context_assembly import AssemblyResult, assemble_context


def _minimal_bot(bot_id: str = "bot-a") -> BotConfig:
    return BotConfig(
        id=bot_id,
        name="Test Bot",
        model="gpt-4o",
        system_prompt="You are a test bot.",
        local_tools=[],
        mcp_servers=[],
        client_tools=[],
        skills=[],
        pinned_tools=[],
        tool_retrieval=False,
        carapaces=[],
        memory_scheme=None,
        history_mode=None,
        filesystem_indexes=[],
        delegate_bots=[],
    )


async def _drain(gen) -> list[dict]:
    return [ev async for ev in gen]


class _FakeChannel:
    """Duck-typed channel row. Any attribute not set explicitly returns None."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):  # pragma: no cover - trivial
        return None


def _fake_channel():
    return _FakeChannel(
        id=uuid.uuid4(),
        bot_id="bot-a",
        config={},
        local_tools_disabled=[],
        mcp_servers_disabled=[],
        client_tools_disabled=[],
        skills_disabled=[],
        integrations=[],
    )


def _fake_session_factory(channel_row):
    """Produce a callable that returns an async-context-managed fake DB session.

    Only the Channel lookup is satisfied with a real row; every other query
    returns empty results. Good enough to exercise the widget-injection hook
    without building a real DB.
    """

    class _EmptyResult:
        def scalar_one_or_none(self):
            return None

        def scalar(self):
            return None

        def scalars(self):
            return self

        def all(self):
            return []

        def __iter__(self):
            return iter([])

    class _ChannelResult(_EmptyResult):
        def scalar_one_or_none(self):
            return channel_row

    class _FakeSession:
        async def execute(self, stmt, *a, **kw):
            # Heuristic: the first query to the channels table in
            # context_assembly loads the Channel row. Other queries
            # (messages, tool_embeddings, etc.) get empty results.
            txt = str(stmt).lower()
            if "from channels" in txt and "channels.id" in txt:
                return _ChannelResult()
            return _EmptyResult()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Factory:
        def __call__(self):
            return _FakeSession()

    return _Factory()


@pytest.mark.asyncio
async def test_pinned_widgets_injected_as_system_message():
    channel_row = _fake_channel()
    pins = [
        {
            "id": "p1",
            "tool_name": "get_weather",
            "display_name": "Weather",
            "bot_id": "bot-a",
            "envelope": {
                "display_label": "Seattle",
                "plain_body": "52F cloudy",
            },
            "position": 0,
            "pinned_at": "2026-04-17T12:00:00+00:00",
            "config": {},
        },
    ]
    bot = _minimal_bot()
    messages: list[dict] = []
    result = AssemblyResult()

    fetch_stub = AsyncMock(return_value=pins)

    with patch(
        "app.db.engine.async_session",
        new=_fake_session_factory(channel_row),
    ), patch(
        "app.services.widget_context.fetch_channel_pin_dicts",
        new=fetch_stub,
    ), patch(
        "app.agent.hooks.fire_hook", new_callable=AsyncMock,
    ), patch(
        "app.agent.recording._record_trace_event", new_callable=AsyncMock,
    ):
        await _drain(assemble_context(
            messages=messages,
            bot=bot,
            user_message="hi",
            session_id=None,
            client_id=None,
            correlation_id=None,
            channel_id=channel_row.id,
            audio_data=None,
            audio_format=None,
            attachments=None,
            native_audio=False,
            result=result,
        ))

    widget_system_msgs = [
        m for m in messages
        if m.get("role") == "system"
        and isinstance(m.get("content"), str)
        and "The user has these widgets pinned" in m["content"]
    ]
    assert len(widget_system_msgs) == 1, (
        f"expected 1 pinned-widget system msg, got {len(widget_system_msgs)} "
        f"among {[m.get('role') for m in messages]}"
    )
    assert "Seattle: 52F cloudy" in widget_system_msgs[0]["content"]
    # The new source is fetched from the dashboard pins table, not JSONB.
    assert fetch_stub.await_count == 1


@pytest.mark.asyncio
async def test_no_pins_no_widget_injection():
    channel_row = _fake_channel()
    bot = _minimal_bot()
    messages: list[dict] = []
    result = AssemblyResult()

    with patch(
        "app.db.engine.async_session",
        new=_fake_session_factory(channel_row),
    ), patch(
        "app.services.widget_context.fetch_channel_pin_dicts",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.agent.hooks.fire_hook", new_callable=AsyncMock,
    ), patch(
        "app.agent.recording._record_trace_event", new_callable=AsyncMock,
    ):
        await _drain(assemble_context(
            messages=messages,
            bot=bot,
            user_message="hi",
            session_id=None,
            client_id=None,
            correlation_id=None,
            channel_id=channel_row.id,
            audio_data=None,
            audio_format=None,
            attachments=None,
            native_audio=False,
            result=result,
        ))

    assert not any(
        isinstance(m.get("content"), str)
        and "The user has these widgets pinned" in m["content"]
        for m in messages
    )
