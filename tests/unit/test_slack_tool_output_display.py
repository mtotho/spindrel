"""Tests for Slack's ``tool_output_display`` branching.

Covers:
- ``_badges_to_context_block`` — pure Block Kit formatting, no I/O.
- ``_handle_new_message`` rendering behavior for each mode
  (``compact``, ``full``, ``none``) with ``_resolve_tool_output_display``
  patched so we don't need a real DB.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.actor import ActorRef
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message as DomainMessage
from app.domain.payloads import MessagePayload
from integrations.sdk import ToolBadge
from integrations.slack import renderer as slack_renderer_mod
from integrations.slack.rate_limit import slack_rate_limiter
from integrations.slack.render_context import slack_render_contexts
from integrations.slack.renderer import (
    SlackRenderer,
    _badges_to_context_block,
)
from integrations.slack.target import SlackTarget


# ---------------------------------------------------------------------------
# _badges_to_context_block — pure formatting
# ---------------------------------------------------------------------------


class TestBadgesToContextBlock:
    def test_empty_list_returns_none(self):
        assert _badges_to_context_block([]) is None

    def test_single_badge_with_label(self):
        block = _badges_to_context_block([
            ToolBadge(tool_name="get_weather", display_label="Lambertville, NJ"),
        ])
        assert block is not None
        assert block["type"] == "context"
        assert len(block["elements"]) == 1
        text = block["elements"][0]["text"]
        assert ":wrench:" in text
        assert "*get_weather*" in text
        assert "Lambertville, NJ" in text

    def test_single_badge_without_label(self):
        block = _badges_to_context_block([ToolBadge(tool_name="get_weather")])
        text = block["elements"][0]["text"]
        assert "*get_weather*" in text
        assert "—" not in text  # no em-dash separator when label missing

    def test_multiple_badges_become_multiple_elements(self):
        block = _badges_to_context_block([
            ToolBadge(tool_name="get_weather", display_label="NJ"),
            ToolBadge(tool_name="get_forecast"),
        ])
        assert len(block["elements"]) == 2

    def test_caps_at_ten_elements(self):
        """Slack's context block allows up to 10 elements."""
        badges = [ToolBadge(tool_name=f"tool_{i}") for i in range(15)]
        block = _badges_to_context_block(badges)
        assert len(block["elements"]) == 10

    def test_mrkdwn_special_chars_in_label_are_escaped(self):
        """``_escape_mrkdwn`` swaps ``< > &`` for their HTML entity form
        so user-supplied labels can't close out a Slack link or mangle
        formatting. ``*`` is intentionally left alone — Slack uses it
        for bold and round-tripping user text as bold is harmless."""
        block = _badges_to_context_block([
            ToolBadge(tool_name="x", display_label="link <http://a|b> & <c>"),
        ])
        text = block["elements"][0]["text"]
        assert "&lt;" in text
        assert "&gt;" in text
        assert "&amp;" in text
        assert "<http" not in text


# ---------------------------------------------------------------------------
# _handle_new_message — mode branching
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_renderer_state():
    slack_render_contexts.reset()
    slack_rate_limiter.reset()
    slack_renderer_mod._register()
    yield
    slack_render_contexts.reset()
    slack_rate_limiter.reset()


@pytest.fixture(autouse=True)
def _mock_bot_attribution():
    with patch(
        "integrations.slack.renderer.bot_attribution",
        return_value={"username": "Test Bot", "icon_emoji": ":robot:"},
    ):
        yield


@pytest.fixture
def fake_http():
    class FakeHTTP:
        def __init__(self):
            self.calls: list[dict] = []

        async def post(self, url, *, json=None, headers=None):
            self.calls.append({"url": url, "body": json, "headers": headers})
            response = MagicMock()
            response.status_code = 200
            response.headers = {}
            response.is_success = True
            response.json = MagicMock(return_value={"ok": True, "ts": "1.0", "channel": "C1"})
            return response

    fake = FakeHTTP()
    with patch.object(slack_renderer_mod, "_http", fake):
        yield fake


def _weather_envelope_dict() -> dict:
    """A component-vocabulary envelope like get_weather would emit."""
    import json as _json
    components = {
        "v": 1,
        "components": [
            {"type": "heading", "level": 2, "text": "Lambertville, NJ"},
            {"type": "text", "content": "69°F overcast clouds", "style": "bold"},
            {"type": "properties", "items": [
                {"label": "Feels like", "value": "69°F"},
                {"label": "Humidity", "value": "69%"},
                {"label": "Wind", "value": "7.58 mph"},
            ]},
        ],
    }
    return {
        "content_type": "application/vnd.spindrel.components+json",
        "body": _json.dumps(components),
        "plain_body": "Widget: get_weather",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 200,
        "display_label": "Lambertville, NJ",
        "tool_name": "get_weather",
    }


def _message_event(metadata: dict) -> ChannelEvent:
    cid = uuid.uuid4()
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                role="assistant",
                content="69°F overcast humid, gusty winds.",
                created_at=datetime.now(timezone.utc),
                actor=ActorRef.bot("test-bot"),
                correlation_id=None,
                metadata=metadata,
                channel_id=cid,
            ),
        ),
    )


def _target() -> SlackTarget:
    return SlackTarget(channel_id="C123", token="xoxb-test")


async def _render(mode: str, fake_http, metadata: dict) -> list[dict]:
    """Render one NEW_MESSAGE and return the list of chat.postMessage bodies."""
    with patch(
        "integrations.slack.renderer._resolve_tool_output_display",
        AsyncMock(return_value=mode),
    ):
        receipt = await SlackRenderer().render(_message_event(metadata), _target())
    assert receipt.ok, f"delivery failed: {receipt}"
    return [
        call["body"]
        for call in fake_http.calls
        if call["url"].endswith("chat.postMessage")
    ]


@pytest.mark.asyncio
class TestRendererBranching:
    async def test_compact_attaches_badge_to_same_message(self, fake_http):
        """Tool badge rides along on the assistant's chat.postMessage —
        not a separate post — so Slack doesn't interleave a subsequent
        user message between the text and the badge (the bug that
        surfaced the ts-ordering issue)."""
        metadata = {"tool_results": [_weather_envelope_dict()]}
        posts = await _render("compact", fake_http, metadata)

        # Exactly one chat.postMessage — text + blocks together.
        assert len(posts) == 1
        body = posts[0]
        assert "overcast" in body["text"].lower()
        blocks = body["blocks"]
        # First block is the section carrying the assistant text.
        assert blocks[0]["type"] == "section"
        assert "overcast" in blocks[0]["text"]["text"].lower()
        # Trailing context block is the tool badge.
        ctx = blocks[-1]
        assert ctx["type"] == "context"
        badge_text = ctx["elements"][0]["text"]
        assert "get_weather" in badge_text
        assert "Lambertville" in badge_text
        # And the compact line must NOT include the full fields.
        assert "Feels like" not in badge_text
        assert "Humidity" not in badge_text

    async def test_full_attaches_block_kit_widget_to_same_message(self, fake_http):
        metadata = {"tool_results": [_weather_envelope_dict()]}
        posts = await _render("full", fake_http, metadata)

        assert len(posts) == 1
        blocks = posts[0]["blocks"]
        # Section for text + heading + bold text + properties.
        assert len(blocks) >= 3
        serialized = str(blocks)
        assert "Feels like" in serialized
        assert "Humidity" in serialized

    async def test_full_badges_unsupported_html_widget(self, fake_http):
        html_env = {
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "<div>weather</div>",
            "plain_body": "Weather widget",
            "display": "inline",
            "truncated": False,
            "record_id": None,
            "byte_size": 200,
            "display_label": "Lambertville, NJ",
            "tool_name": "get_weather",
        }
        metadata = {"tool_results": [_weather_envelope_dict(), html_env]}
        posts = await _render("full", fake_http, metadata)

        assert len(posts) == 1
        serialized = str(posts[0]["blocks"])
        assert "Humidity" in serialized
        assert ":wrench:" in serialized
        assert "get_weather" in serialized

    async def test_none_skips_tool_output(self, fake_http):
        metadata = {"tool_results": [_weather_envelope_dict()]}
        posts = await _render("none", fake_http, metadata)

        # Only the assistant text — no blocks attached.
        assert len(posts) == 1
        assert "blocks" not in posts[0]

    async def test_compact_with_no_tool_results_leaves_plain_text(self, fake_http):
        posts = await _render("compact", fake_http, {"tool_results": []})
        assert len(posts) == 1
        assert "blocks" not in posts[0]

    async def test_compact_dedups_repeated_envelopes(self, fake_http):
        env = _weather_envelope_dict()
        metadata = {"tool_results": [env, dict(env)]}  # identical
        posts = await _render("compact", fake_http, metadata)

        ctx = posts[0]["blocks"][-1]
        # Only one element in the context block because both envelopes
        # have the same (tool_name, display_label).
        assert len(ctx["elements"]) == 1

    async def test_user_message_with_tool_results_does_not_render_badge(self, fake_http):
        """User messages (role=user) never get tool badges attached —
        tools run on bot turns, and stamping a wrench on a user reply
        would misattribute the action."""
        cid = uuid.uuid4()
        evt = ChannelEvent(
            channel_id=cid,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(
                message=DomainMessage(
                    id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                    role="user",
                    content="ok get the weather again",
                    created_at=datetime.now(timezone.utc),
                    actor=ActorRef.user("u1", display_name="Michael"),
                    correlation_id=None,
                    metadata={"tool_results": [_weather_envelope_dict()]},
                    channel_id=cid,
                ),
            ),
        )
        with patch(
            "integrations.slack.renderer._resolve_tool_output_display",
            AsyncMock(return_value="compact"),
        ):
            receipt = await SlackRenderer().render(evt, _target())
        assert receipt.ok
        posts = [c["body"] for c in fake_http.calls if c["url"].endswith("chat.postMessage")]
        assert len(posts) == 1
        assert "blocks" not in posts[0]
