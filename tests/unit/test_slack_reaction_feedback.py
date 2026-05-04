"""Slack reaction → turn-feedback bridge.

Covers the disambiguation between the legacy ``:+1:`` approval path and
the new feedback path, plus the ``reaction_removed`` clear flow. The
HTTP calls back into the agent server are mocked — we only assert that
the right URL/payload is produced.
"""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _stub_slack_settings(monkeypatch):
    """The reaction handler does ``from slack_settings import ...`` lazily.

    Stub the module in ``sys.modules`` for the duration of the test. The
    real module only exists in the slack runtime image.
    """
    stub = types.ModuleType("slack_settings")
    stub.AGENT_BASE_URL = "http://agent.test"  # type: ignore[attr-defined]
    stub.API_KEY = "test-api-key"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "slack_settings", stub)
    yield


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in capturing one POST call."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, json, headers):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        resp = types.SimpleNamespace()
        resp.status_code = captured.get("status_code", 200)
        resp.text = ""
        return resp


captured: dict = {}


@pytest.fixture(autouse=True)
def _reset_captured():
    captured.clear()
    captured["status_code"] = 200
    yield


class _FakeSlackClient:
    """Slack web client stub. Fakes auth.test + conversations.history."""

    def __init__(self, *, own_user="UBOT", history=None):
        self.own_user = own_user
        self.history = history or {"ok": True, "messages": [{"blocks": []}]}

    async def auth_test(self):
        return {"ok": True, "user_id": self.own_user}

    async def conversations_history(self, **kwargs):
        return self.history


@pytest.mark.asyncio
async def test_thumbs_up_on_non_approval_message_records_up_vote(monkeypatch):
    from integrations.slack import reaction_handlers

    # Reset the cached own-user id so auth_test runs cleanly per test.
    monkeypatch.setattr(reaction_handlers, "_own_bot_user_id", None)
    monkeypatch.setattr(reaction_handlers, "httpx", types.SimpleNamespace(
        AsyncClient=_FakeAsyncClient,
    ))

    event = {
        "reaction": "+1",
        "user": "U_HUMAN",
        "item": {"type": "message", "channel": "C1", "ts": "1700000000.1"},
    }
    client = _FakeSlackClient()  # no approval blocks
    await reaction_handlers.on_reaction_added_for_tests(event, client)

    assert captured["url"].endswith("/api/v1/messages/feedback/by-slack-reaction")
    assert captured["json"] == {
        "slack_ts": "1700000000.1",
        "slack_channel": "C1",
        "slack_user_id": "U_HUMAN",
        "vote": "up",
    }
    assert captured["headers"]["Authorization"] == "Bearer test-api-key"


@pytest.mark.asyncio
async def test_thumbs_down_records_down_vote(monkeypatch):
    from integrations.slack import reaction_handlers

    monkeypatch.setattr(reaction_handlers, "_own_bot_user_id", None)
    monkeypatch.setattr(reaction_handlers, "httpx", types.SimpleNamespace(
        AsyncClient=_FakeAsyncClient,
    ))

    event = {
        "reaction": "thumbsdown",
        "user": "U_HUMAN",
        "item": {"type": "message", "channel": "C2", "ts": "1700000000.2"},
    }
    await reaction_handlers.on_reaction_added_for_tests(event, _FakeSlackClient())

    assert captured["json"]["vote"] == "down"
    assert captured["url"].endswith("/api/v1/messages/feedback/by-slack-reaction")


@pytest.mark.asyncio
async def test_thumbs_up_on_approval_message_takes_approval_path(monkeypatch):
    """If the message *is* an approval block, :+1: still approves — no feedback POST."""
    from integrations.slack import reaction_handlers

    monkeypatch.setattr(reaction_handlers, "_own_bot_user_id", None)
    decided: list[str] = []

    async def fake_decide(approval_id, user_id):
        decided.append((approval_id, user_id))
        return True

    monkeypatch.setattr(reaction_handlers, "_decide_approval", fake_decide)

    # Capture chat_postMessage so the test doesn't choke on the ack call.
    posted: list[dict] = []

    class _ApprovalSlackClient(_FakeSlackClient):
        def __init__(self):
            super().__init__(history={
                "ok": True,
                "messages": [{
                    "blocks": [{
                        "type": "actions",
                        "elements": [{
                            "type": "button",
                            "value": "abc123",
                        }],
                    }],
                }],
            })

        async def chat_postMessage(self, **kwargs):
            posted.append(kwargs)
            return {"ok": True}

    event = {
        "reaction": "+1",
        "user": "U_HUMAN",
        "item": {"type": "message", "channel": "C3", "ts": "1700000000.3"},
    }
    await reaction_handlers.on_reaction_added_for_tests(event, _ApprovalSlackClient())

    assert decided == [("abc123", "U_HUMAN")]
    # The feedback path was NOT taken — captured is untouched.
    assert "url" not in captured


@pytest.mark.asyncio
async def test_reaction_removed_clears_feedback(monkeypatch):
    from integrations.slack import reaction_handlers

    monkeypatch.setattr(reaction_handlers, "_own_bot_user_id", None)
    monkeypatch.setattr(reaction_handlers, "httpx", types.SimpleNamespace(
        AsyncClient=_FakeAsyncClient,
    ))

    event = {
        "reaction": "thumbsup",
        "user": "U_HUMAN",
        "item": {"type": "message", "channel": "C4", "ts": "1700000000.4"},
    }
    await reaction_handlers.on_reaction_removed_for_tests(event, _FakeSlackClient())

    assert captured["url"].endswith(
        "/api/v1/messages/feedback/by-slack-reaction/clear",
    )
    assert "vote" not in captured["json"]


@pytest.mark.asyncio
async def test_own_bot_reactions_are_ignored(monkeypatch):
    from integrations.slack import reaction_handlers

    monkeypatch.setattr(reaction_handlers, "_own_bot_user_id", None)
    monkeypatch.setattr(reaction_handlers, "httpx", types.SimpleNamespace(
        AsyncClient=_FakeAsyncClient,
    ))

    event = {
        "reaction": "+1",
        "user": "UBOT",
        "item": {"type": "message", "channel": "C5", "ts": "1700000000.5"},
    }
    await reaction_handlers.on_reaction_added_for_tests(event, _FakeSlackClient(own_user="UBOT"))
    assert "url" not in captured
