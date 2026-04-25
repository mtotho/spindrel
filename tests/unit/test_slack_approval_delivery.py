"""Slack approval delivery tests."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import ApprovalRequestedPayload
from integrations.slack import transport as slack_transport_mod
from integrations.slack.approval_delivery import SlackApprovalDelivery
from integrations.slack.rate_limit import slack_rate_limiter
from integrations.slack.render_context import slack_render_contexts
from integrations.slack.target import SlackTarget

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_delivery_state():
    slack_render_contexts.reset()
    slack_rate_limiter.reset()
    yield
    slack_render_contexts.reset()
    slack_rate_limiter.reset()


@pytest.fixture
def fake_http():
    class FakeHTTP:
        def __init__(self):
            self.calls: list[dict] = []
            self._next = {"ok": True}

        def set_response(self, data: dict):
            self._next = data

        async def post(self, url, *, json=None, headers=None):
            self.calls.append({"url": url, "body": json, "headers": headers})
            response = MagicMock()
            response.status_code = 200
            response.headers = {}
            response.is_success = True
            response.json = MagicMock(return_value=self._next)
            return response

    fake = FakeHTTP()
    with patch.object(slack_transport_mod, "_http", fake):
        yield fake


def _delivery() -> SlackApprovalDelivery:
    return SlackApprovalDelivery(
        call_slack=slack_transport_mod.call_slack,
        bot_attribution=lambda _bot_id: {
            "username": "Test Bot",
            "icon_emoji": ":robot:",
        },
    )


def _target() -> SlackTarget:
    return SlackTarget(channel_id="C123", token="xoxb-test")


def _approval_event(
    *,
    capability: dict | None = None,
) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.APPROVAL_REQUESTED,
        payload=ApprovalRequestedPayload(
            approval_id="appr-1",
            bot_id="test-bot",
            tool_name="dangerous_tool",
            arguments={"x": 1},
            reason="Policy requires approval",
            capability=capability,
        ),
    )


class TestSlackApprovalDelivery:
    async def test_tool_approval_posts_block_kit(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000003.0"})

        with patch(
            "integrations.slack.approval_blocks.build_suggestions",
            return_value=[],
        ):
            receipt = await _delivery().render(_approval_event(), _target())

        assert receipt.success is True
        body = fake_http.calls[0]["body"]
        assert body["channel"] == "C123"
        assert body["username"] == "Test Bot"
        assert "blocks" in body
        action_blocks = [b for b in body["blocks"] if b["type"] == "actions"]
        assert any(
            any(el["action_id"] == "approve_tool_call" for el in b["elements"])
            for b in action_blocks
        )

    async def test_capability_approval_uses_capability_blocks(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000003.5"})
        cap = {
            "id": "cap-1",
            "name": "WebSearch",
            "description": "Search the web",
            "tools_count": 2,
            "skills_count": 1,
        }

        receipt = await _delivery().render(_approval_event(capability=cap), _target())

        assert receipt.success is True
        body = fake_http.calls[0]["body"]
        first_section = next(b for b in body["blocks"] if b["type"] == "section")
        assert "WebSearch" in first_section["text"]["text"]
        assert "Capability activation" in first_section["text"]["text"]
