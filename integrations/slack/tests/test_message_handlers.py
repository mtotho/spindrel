"""Tests for message_handlers — thread read-up and user-id attribution."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import message_handlers
from message_handlers import _fetch_thread_parent_summary


@pytest.fixture(autouse=True)
def _reset_name_cache():
    message_handlers._user_name_cache.clear()
    yield
    message_handlers._user_name_cache.clear()


def _reply(text, *, user=None, bot_id=None, ts="1.0"):
    msg = {"text": text, "ts": ts}
    if user:
        msg["user"] = user
    if bot_id:
        msg["bot_id"] = bot_id
    return msg


class TestFetchThreadParentSummary:
    @pytest.mark.asyncio
    async def test_returns_empty_when_thread_ts_equals_current_ts(self):
        client = AsyncMock()
        client.conversations_replies = AsyncMock()
        result = await _fetch_thread_parent_summary(
            client, "C1", thread_ts="100.0", current_ts="100.0",
        )
        assert result == ""
        client.conversations_replies.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_empty_when_thread_ts_missing(self):
        client = AsyncMock()
        client.conversations_replies = AsyncMock()
        result = await _fetch_thread_parent_summary(
            client, "C1", thread_ts="", current_ts="100.0",
        )
        assert result == ""
        client.conversations_replies.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_current_message_and_renders_others(self):
        client = AsyncMock()
        client.conversations_replies = AsyncMock(return_value={
            "ok": True,
            "messages": [
                _reply("hi team", user="U1", ts="100.0"),
                _reply("anyone around?", user="U2", ts="101.0"),
                _reply("bot's reply here", user="U3", ts="102.0"),
            ],
        })
        client.users_info = AsyncMock(side_effect=[
            {"ok": True, "user": {"profile": {"display_name": "alice"}}},
            {"ok": True, "user": {"profile": {"display_name": "bob"}}},
        ])

        result = await _fetch_thread_parent_summary(
            client, "C1", thread_ts="100.0", current_ts="102.0",
        )
        lines = result.splitlines()
        assert lines[0].startswith("[Thread context")
        # The current message (ts=102.0) is skipped.
        body = "\n".join(lines[1:])
        assert "alice" in body and "<@U1>" in body
        assert "bob" in body and "<@U2>" in body
        assert "bot's reply here" not in body

    @pytest.mark.asyncio
    async def test_truncates_long_messages(self):
        long_text = "x" * 600
        client = AsyncMock()
        client.conversations_replies = AsyncMock(return_value={
            "ok": True,
            "messages": [_reply(long_text, user="U1", ts="100.0")],
        })
        client.users_info = AsyncMock(return_value={
            "ok": True, "user": {"profile": {"display_name": "alice"}},
        })

        result = await _fetch_thread_parent_summary(
            client, "C1", thread_ts="100.0", current_ts="999.0",
        )
        assert "…" in result
        # No single line carries the full 600-char payload.
        for line in result.splitlines():
            assert len(line) <= 500

    @pytest.mark.asyncio
    async def test_returns_empty_on_api_failure(self):
        client = AsyncMock()
        client.conversations_replies = AsyncMock(side_effect=RuntimeError("boom"))
        result = await _fetch_thread_parent_summary(
            client, "C1", thread_ts="100.0", current_ts="999.0",
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_messages_filtered(self):
        """Only the current message in the thread → nothing to prepend."""
        client = AsyncMock()
        client.conversations_replies = AsyncMock(return_value={
            "ok": True,
            "messages": [_reply("just me", user="U1", ts="100.0")],
        })
        result = await _fetch_thread_parent_summary(
            client, "C1", thread_ts="100.0", current_ts="100.0",
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_bot_sender_labeled_as_bot(self):
        client = AsyncMock()
        client.conversations_replies = AsyncMock(return_value={
            "ok": True,
            "messages": [_reply("from a bot", bot_id="B123", ts="100.0")],
        })
        result = await _fetch_thread_parent_summary(
            client, "C1", thread_ts="100.0", current_ts="999.0",
        )
        assert "bot:B123" in result
        # No user lookup should happen for a bot message.
        client.users_info.assert_not_called()
