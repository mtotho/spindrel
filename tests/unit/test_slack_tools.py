"""Tests for the Slack integration server-side tools."""
from __future__ import annotations

import json
import uuid
from contextvars import copy_context

import pytest

from app.agent.context import current_channel_id
from integrations.slack import web_api
from integrations.slack.tools import bookmarks, pins, scheduled


CH_UUID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def channel_ctx():
    """Run the tool inside a context where current_channel_id is set."""
    def _run(awaitable):
        token = current_channel_id.set(CH_UUID)
        try:
            return awaitable
        finally:
            current_channel_id.reset(token)
    return _run


# ---------------------------------------------------------------------------
# slack_schedule_message
# ---------------------------------------------------------------------------


class TestScheduleMessage:
    @pytest.mark.asyncio
    async def test_iso_timestamp_converted_to_epoch(self, monkeypatch):
        calls: list[tuple[str, dict]] = []

        async def fake_resolve(ch):
            assert ch == CH_UUID
            return "C0123"

        async def fake_call(method, *, body=None, token=None):
            calls.append((method, body))
            return {"ok": True, "scheduled_message_id": "Q1", "post_at": body["post_at"], "channel": body["channel"]}

        monkeypatch.setattr(scheduled, "resolve_slack_channel_id", fake_resolve)
        monkeypatch.setattr(scheduled, "slack_call", fake_call)

        current_channel_id.set(CH_UUID)
        raw = await scheduled.slack_schedule_message(
            text="hello",
            post_at="2030-01-01T12:00:00Z",
        )
        out = json.loads(raw)
        assert out == {
            "ok": True,
            "scheduled_message_id": "Q1",
            "post_at": calls[0][1]["post_at"],
            "channel": "C0123",
        }
        assert calls[0][0] == "chat.scheduleMessage"
        assert calls[0][1]["post_at"] == 1893499200  # 2030-01-01T12:00:00Z

    @pytest.mark.asyncio
    async def test_thread_ts_passed_through(self, monkeypatch):
        captured: dict = {}

        async def fake_resolve(ch):
            return "C0"

        async def fake_call(method, *, body=None, token=None):
            captured.update(body)
            return {"ok": True, "scheduled_message_id": "Q2", "post_at": body["post_at"], "channel": "C0"}

        monkeypatch.setattr(scheduled, "resolve_slack_channel_id", fake_resolve)
        monkeypatch.setattr(scheduled, "slack_call", fake_call)

        current_channel_id.set(CH_UUID)
        await scheduled.slack_schedule_message(
            text="in thread", post_at="9999999999", thread_ts="1.234",
        )
        assert captured["thread_ts"] == "1.234"

    @pytest.mark.asyncio
    async def test_non_slack_channel_returns_error(self, monkeypatch):
        async def fake_resolve(ch):
            raise web_api.SlackApiError("channel is not a Slack channel")

        monkeypatch.setattr(scheduled, "resolve_slack_channel_id", fake_resolve)
        current_channel_id.set(CH_UUID)

        raw = await scheduled.slack_schedule_message(text="x", post_at="99999")
        assert json.loads(raw)["error"].startswith("channel is not")

    @pytest.mark.asyncio
    async def test_invalid_post_at_returns_error(self, monkeypatch):
        async def fake_resolve(ch):
            return "C0"

        monkeypatch.setattr(scheduled, "resolve_slack_channel_id", fake_resolve)
        current_channel_id.set(CH_UUID)

        raw = await scheduled.slack_schedule_message(text="x", post_at="not a date")
        assert "invalid post_at" in json.loads(raw)["error"]


# ---------------------------------------------------------------------------
# slack_pin_message
# ---------------------------------------------------------------------------


class TestPinMessage:
    @pytest.mark.asyncio
    async def test_pins_message_with_channel_and_ts(self, monkeypatch):
        body_captured: dict = {}

        async def fake_resolve(ch):
            return "C0ABC"

        async def fake_call(method, *, body=None, token=None):
            body_captured.update(body)
            return {"ok": True}

        monkeypatch.setattr(pins, "resolve_slack_channel_id", fake_resolve)
        monkeypatch.setattr(pins, "slack_call", fake_call)

        current_channel_id.set(CH_UUID)
        raw = await pins.slack_pin_message(message_ts="1700000000.1")
        out = json.loads(raw)
        assert out == {"ok": True, "pinned_ts": "1700000000.1", "channel": "C0ABC"}
        assert body_captured == {"channel": "C0ABC", "timestamp": "1700000000.1"}

    @pytest.mark.asyncio
    async def test_error_propagates(self, monkeypatch):
        async def fake_resolve(ch):
            return "C0"

        async def fake_call(method, *, body=None, token=None):
            raise web_api.SlackApiError("slack pins.add: already_pinned")

        monkeypatch.setattr(pins, "resolve_slack_channel_id", fake_resolve)
        monkeypatch.setattr(pins, "slack_call", fake_call)

        current_channel_id.set(CH_UUID)
        raw = await pins.slack_pin_message(message_ts="1.0")
        assert "already_pinned" in json.loads(raw)["error"]


# ---------------------------------------------------------------------------
# slack_add_bookmark
# ---------------------------------------------------------------------------


class TestAddBookmark:
    @pytest.mark.asyncio
    async def test_adds_bookmark_with_emoji(self, monkeypatch):
        body_captured: dict = {}

        async def fake_resolve(ch):
            return "C0"

        async def fake_call(method, *, body=None, token=None):
            body_captured.update(body)
            return {
                "ok": True,
                "bookmark": {
                    "id": "Bk001",
                    "title": "Runbook",
                    "link": "https://example.com/book",
                },
            }

        monkeypatch.setattr(bookmarks, "resolve_slack_channel_id", fake_resolve)
        monkeypatch.setattr(bookmarks, "slack_call", fake_call)

        current_channel_id.set(CH_UUID)
        raw = await bookmarks.slack_add_bookmark(
            title="Runbook", link="https://example.com/book", emoji=":book:",
        )
        out = json.loads(raw)
        assert out["bookmark_id"] == "Bk001"
        assert body_captured["emoji"] == ":book:"
        assert body_captured["type"] == "link"

    @pytest.mark.asyncio
    async def test_no_channel_returns_error(self):
        # No current_channel_id.set — the ContextVar defaults to None.
        # Use a fresh context to make sure a prior test's value does not leak.
        async def run():
            raw = await bookmarks.slack_add_bookmark(
                title="x", link="https://example.com",
            )
            return raw

        ctx = copy_context()
        # Run the tool in an isolated context with no channel.
        raw = await ctx.run(run)
        assert "no channel" in json.loads(raw)["error"]
