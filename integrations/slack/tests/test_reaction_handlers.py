"""Tests for the reaction_added handler dispatch."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from reaction_handlers import (
    _approval_id_from_button_value,
    _extract_approval_id,
    on_reaction_added_for_tests,
)
import reaction_handlers


# ---------------------------------------------------------------------------
# Unit: button value parsing
# ---------------------------------------------------------------------------


class TestApprovalIdFromButtonValue:
    def test_bare_uuid(self):
        assert _approval_id_from_button_value("abc-123") == "abc-123"

    def test_json_value(self):
        raw = json.dumps({"approval_id": "xyz-789", "bot_id": "b1"})
        assert _approval_id_from_button_value(raw) == "xyz-789"

    def test_empty(self):
        assert _approval_id_from_button_value("") is None

    def test_json_without_approval_id(self):
        assert _approval_id_from_button_value(json.dumps({"foo": "bar"})) is None

    def test_invalid_json_treated_as_non_approval(self):
        # A stray '{' prefix is not valid JSON and should not crash.
        assert _approval_id_from_button_value("{not json") is None


# ---------------------------------------------------------------------------
# Unit: _extract_approval_id — walks the Slack block tree
# ---------------------------------------------------------------------------


def _history_response(blocks):
    return {"ok": True, "messages": [{"blocks": blocks}]}


class TestExtractApprovalId:
    @pytest.mark.asyncio
    async def test_finds_id_in_bare_button(self):
        client = AsyncMock()
        client.conversations_history = AsyncMock(
            return_value=_history_response([
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "action_id": "approve_tool_call", "value": "APR-1"},
                        {"type": "button", "action_id": "deny_tool_call", "value": "APR-1"},
                    ],
                },
            ])
        )
        assert await _extract_approval_id(client, "C1", "1.0") == "APR-1"

    @pytest.mark.asyncio
    async def test_finds_id_in_json_button(self):
        client = AsyncMock()
        client.conversations_history = AsyncMock(
            return_value=_history_response([
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "allow_rule_0",
                            "value": json.dumps(
                                {"approval_id": "APR-2", "bot_id": "b1", "tool_name": "x"}
                            ),
                        },
                    ],
                },
            ])
        )
        assert await _extract_approval_id(client, "C1", "1.0") == "APR-2"

    @pytest.mark.asyncio
    async def test_none_when_no_action_block(self):
        client = AsyncMock()
        client.conversations_history = AsyncMock(
            return_value=_history_response([
                {"type": "section", "text": {"type": "mrkdwn", "text": "hi"}},
            ])
        )
        assert await _extract_approval_id(client, "C1", "1.0") is None

    @pytest.mark.asyncio
    async def test_none_when_history_fails(self):
        client = AsyncMock()
        client.conversations_history = AsyncMock(return_value={"ok": False})
        assert await _extract_approval_id(client, "C1", "1.0") is None


# ---------------------------------------------------------------------------
# Integration: on_reaction_added end-to-end (mocked HTTP + Slack client)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_bot_id_cache():
    """Prevent test order from changing the cached own-bot user id."""
    reaction_handlers._own_bot_user_id = None
    yield
    reaction_handlers._own_bot_user_id = None


class TestOnReactionAdded:
    @pytest.mark.asyncio
    async def test_thumbsup_approves_pending(self, monkeypatch):
        client = AsyncMock()
        client.auth_test = AsyncMock(return_value={"ok": True, "user_id": "UBOT"})
        client.conversations_history = AsyncMock(
            return_value=_history_response([
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "action_id": "approve_tool_call", "value": "APR-7"},
                    ],
                },
            ])
        )
        client.chat_postMessage = AsyncMock()

        decisions: list[tuple[str, str]] = []

        async def fake_decide(approval_id, user_id):
            decisions.append((approval_id, user_id))
            return True

        monkeypatch.setattr(reaction_handlers, "_decide_approval", fake_decide)

        event = {
            "reaction": "+1",
            "user": "UALICE",
            "item": {"type": "message", "channel": "C1", "ts": "1.0"},
        }
        await on_reaction_added_for_tests(event, client)

        assert decisions == [("APR-7", "UALICE")]
        client.chat_postMessage.assert_awaited_once()
        kwargs = client.chat_postMessage.await_args.kwargs
        assert kwargs["channel"] == "C1"
        assert kwargs["thread_ts"] == "1.0"
        assert "<@UALICE>" in kwargs["text"]

    @pytest.mark.asyncio
    async def test_own_bot_reaction_is_ignored(self, monkeypatch):
        client = AsyncMock()
        client.auth_test = AsyncMock(return_value={"ok": True, "user_id": "UBOT"})
        client.conversations_history = AsyncMock()
        decisions: list[str] = []

        async def fake_decide(approval_id, user_id):
            decisions.append(approval_id)
            return True

        monkeypatch.setattr(reaction_handlers, "_decide_approval", fake_decide)

        event = {
            "reaction": "+1",
            "user": "UBOT",
            "item": {"type": "message", "channel": "C1", "ts": "1.0"},
        }
        await on_reaction_added_for_tests(event, client)

        client.conversations_history.assert_not_awaited()
        assert decisions == []

    @pytest.mark.asyncio
    async def test_unmapped_reaction_is_ignored(self, monkeypatch):
        client = AsyncMock()
        client.auth_test = AsyncMock(return_value={"ok": True, "user_id": "UBOT"})
        client.conversations_history = AsyncMock()

        called = False

        async def fake_decide(*a, **kw):
            nonlocal called
            called = True
            return True

        monkeypatch.setattr(reaction_handlers, "_decide_approval", fake_decide)

        event = {
            "reaction": "eyes",
            "user": "UALICE",
            "item": {"type": "message", "channel": "C1", "ts": "1.0"},
        }
        await on_reaction_added_for_tests(event, client)

        assert called is False
        client.conversations_history.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_message_item_ignored(self, monkeypatch):
        client = AsyncMock()
        client.auth_test = AsyncMock(return_value={"ok": True, "user_id": "UBOT"})
        event = {
            "reaction": "+1",
            "user": "UALICE",
            "item": {"type": "file", "file": "F1"},
        }
        await on_reaction_added_for_tests(event, client)
        client.auth_test.assert_not_awaited()
