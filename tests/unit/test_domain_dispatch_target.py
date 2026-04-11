"""Tests for app.domain.dispatch_target — core targets + parser.

Integration-specific target classes (Slack/Discord/BlueBubbles/GitHub)
live in their integration packages and have per-integration test
coverage in ``tests/unit/test_<integration>_renderer.py``. We import
them here only to keep the round-trip tests against
``parse_dispatch_target`` working — those tests prove the registry
lookup chain works end-to-end.
"""
from __future__ import annotations

import pytest

from app.domain.dispatch_target import (
    InternalTarget,
    NoneTarget,
    WebhookTarget,
    WebTarget,
    parse_dispatch_target,
)
# Import the integration target packages so they self-register with
# `target_registry`. Without these imports the round-trip tests below
# would fail with "unknown dispatch target type" because the test
# process never went through the integration discovery loop.
from integrations.bluebubbles.target import BlueBubblesTarget  # noqa: F401
from integrations.discord.target import DiscordTarget  # noqa: F401
from integrations.slack.target import SlackTarget  # noqa: F401


class TestSlackTarget:
    def test_round_trip(self):
        t = SlackTarget(
            channel_id="C123",
            token="xoxb-abc",
            thread_ts="1234.56",
            message_ts="1234.78",
            reply_in_thread=True,
        )
        d = t.to_dict()
        assert d["type"] == "slack"
        assert d["channel_id"] == "C123"
        assert d["thread_ts"] == "1234.56"
        assert d["message_ts"] == "1234.78"
        assert d["reply_in_thread"] is True
        parsed = parse_dispatch_target(d)
        assert parsed == t

    def test_parse_from_message_handlers_shape(self):
        """Regression: integrations/slack/message_handlers.py builds
        dispatch_config with all five slack keys. parse_dispatch_target
        must accept them or `resolve_targets` silently drops slack to
        NoneTarget and no messages reach Slack."""
        cfg = {
            "type": "slack",
            "channel_id": "C123",
            "thread_ts": "1234.56",
            "message_ts": "1234.78",
            "token": "xoxb-abc",
            "reply_in_thread": True,
        }
        parsed = parse_dispatch_target(cfg)
        assert isinstance(parsed, SlackTarget)
        assert parsed.message_ts == "1234.78"

    def test_integration_id_class_var(self):
        assert SlackTarget.integration_id == "slack"
        assert SlackTarget(channel_id="X", token="Y").integration_id == "slack"

    def test_optional_fields_default(self):
        t = SlackTarget(channel_id="C", token="t")
        assert t.thread_ts is None
        assert t.message_ts is None
        assert t.reply_in_thread is False


class TestDiscordTarget:
    def test_round_trip(self):
        t = DiscordTarget(channel_id="123456", token="bot-token")
        parsed = parse_dispatch_target(t.to_dict())
        assert parsed == t
        assert parsed.integration_id == "discord"


class TestBlueBubblesTarget:
    def test_round_trip(self):
        t = BlueBubblesTarget(
            chat_guid="iMessage;-;+15551234",
            server_url="http://10.0.0.1:1234",
            password="hunter2",
            send_method="apple-script",
            text_footer="-- sent via Spindrel",
        )
        parsed = parse_dispatch_target(t.to_dict())
        assert parsed == t
        assert parsed.integration_id == "bluebubbles"

    def test_optional_fields(self):
        t = BlueBubblesTarget(chat_guid="g", server_url="u", password="p")
        assert t.send_method is None
        assert t.text_footer is None


class TestWebTarget:
    def test_round_trip(self):
        t = WebTarget()
        d = t.to_dict()
        assert d == {"type": "web"}
        assert parse_dispatch_target(d) == t


class TestWebhookTarget:
    def test_round_trip(self):
        t = WebhookTarget(url="https://example.com/hook", headers={"X-Auth": "secret"})
        parsed = parse_dispatch_target(t.to_dict())
        assert parsed == t

    def test_default_headers(self):
        t = WebhookTarget(url="https://example.com")
        assert t.headers == {}


class TestInternalTarget:
    def test_round_trip(self):
        t = InternalTarget(parent_session_id="abc-123-def")
        parsed = parse_dispatch_target(t.to_dict())
        assert parsed == t


class TestNoneTarget:
    def test_round_trip(self):
        t = NoneTarget()
        assert parse_dispatch_target(t.to_dict()) == t


class TestParseDispatchTarget:
    def test_none_dict(self):
        assert parse_dispatch_target(None) == NoneTarget()

    def test_empty_dict(self):
        assert parse_dispatch_target({}) == NoneTarget()

    def test_missing_type_raises(self):
        with pytest.raises(ValueError, match="missing required 'type'"):
            parse_dispatch_target({"channel_id": "C"})

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="unknown dispatch target type"):
            parse_dispatch_target({"type": "telegram"})

    def test_missing_required_field_raises(self):
        # SlackTarget requires channel_id and token
        with pytest.raises(ValueError, match="invalid slack target"):
            parse_dispatch_target({"type": "slack"})

    def test_extra_fields_raise(self):
        # Discriminated union should reject extra junk
        with pytest.raises(ValueError, match="invalid slack target"):
            parse_dispatch_target({
                "type": "slack",
                "channel_id": "C",
                "token": "t",
                "made_up_field": "wat",
            })


class TestImmutability:
    def test_target_is_frozen(self):
        t = SlackTarget(channel_id="C", token="t")
        with pytest.raises(Exception):  # FrozenInstanceError
            t.channel_id = "D"  # type: ignore[misc]
