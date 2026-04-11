"""Phase F — Slack end-to-end acceptance test.

The whole motivation for the Integration Delivery refactor was a
user-reported bug: Slack mobile clients sometimes never refresh to
the agent's final reply during a long streaming turn. The root cause
was two parallel ``chat.update`` storms (one inside the Slack
subprocess, one inside the queued main-process dispatcher) racing
each other with no shared rate limiter.

Phase F collapses both onto the SlackRenderer with a 0.8s coalesce
window and a safety pass. This test exercises the full event sequence
the agent loop publishes for a normal turn — TURN_STARTED + many
TURN_STREAM_TOKEN + TURN_ENDED — against a fake Slack HTTP backend
and asserts:

1. Exactly one ``chat.postMessage`` for the thinking placeholder.
2. The number of ``chat.update`` calls is bounded by the debounce
   window, NOT one per token.
3. The final ``chat.update`` carries the complete final text.
4. No second ``chat.postMessage`` for the body (the placeholder is
   reused via update, not replaced with a new post).
5. The render-context registry is empty after TURN_ENDED — no
   in-memory leak across turns.
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from integrations.slack.target import SlackTarget
from app.domain.payloads import (
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamTokenPayload,
)
from integrations.slack import renderer as slack_renderer_mod
from integrations.slack.rate_limit import slack_rate_limiter
from integrations.slack.render_context import (
    STREAM_FLUSH_INTERVAL,
    slack_render_contexts,
)
from integrations.slack.renderer import SlackRenderer

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_state():
    slack_render_contexts.reset()
    slack_rate_limiter.reset()
    # Drop the per-method min_interval to zero for tests so the
    # 1.05s real-world Slack tier-1 limit doesn't make every test
    # take 60 seconds. The test still verifies the debounce window
    # via the renderer-side context flush math, which is independent
    # of the rate limiter.
    slack_rate_limiter._default = 0.0
    yield
    slack_render_contexts.reset()
    slack_rate_limiter.reset()


@pytest.fixture(autouse=True)
def _mock_bot_attribution():
    with patch(
        "integrations.slack.renderer.bot_attribution",
        return_value={"username": "Test Bot"},
    ):
        yield


@pytest.fixture
def fake_slack_http():
    """A request-recording fake for the Slack HTTP client."""
    class FakeHTTP:
        def __init__(self):
            self.calls: list[dict] = []
            self._next_ts = 1700000000

        async def post(self, url, *, json=None, headers=None):
            self.calls.append({"url": url, "body": dict(json or {})})
            method = url.rsplit("/", 1)[-1]
            self._next_ts += 1
            payload = {"ok": True, "ts": f"{self._next_ts}.0", "channel": "C123"}
            response = MagicMock()
            response.status_code = 200
            response.is_success = True
            response.headers = {}
            response.json = MagicMock(return_value=payload)
            return response

        def calls_to(self, method: str) -> list[dict]:
            suffix = f"/api/{method}"
            return [c for c in self.calls if c["url"].endswith(suffix)]

    fake = FakeHTTP()
    with patch.object(slack_renderer_mod, "_http", fake):
        yield fake


def _target() -> SlackTarget:
    return SlackTarget(channel_id="C123", token="xoxb-test", reply_in_thread=False)


def _started(turn_id: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id="bot1", turn_id=turn_id, reason="user_message"),
    )


def _token(turn_id: uuid.UUID, delta: str) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_STREAM_TOKEN,
        payload=TurnStreamTokenPayload(bot_id="bot1", turn_id=turn_id, delta=delta),
    )


def _ended(turn_id: uuid.UUID, result: str) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(
            bot_id="bot1", turn_id=turn_id, result=result, client_actions=[],
        ),
    )


class TestSlackRenderEndToEnd:
    async def test_long_streaming_turn_coalesces_chat_updates(self, fake_slack_http):
        """The acceptance test for the original user-reported bug.

        Drive a 50-token streaming sequence through SlackRenderer and
        assert that the number of ``chat.update`` calls is bounded —
        far fewer than 50 — and that the placeholder is the only
        ``chat.postMessage`` call. This is the contract that prevents
        Slack mobile clients from missing the final state.
        """
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _target()

        # 1. Placeholder.
        await renderer.render(_started(turn_id), target)

        # 2. Drive 50 token deltas back-to-back, jumping the wall clock
        #    forward through the renderer's debounce window so flushes
        #    actually fire (the unit-test cheat we use elsewhere is to
        #    reach into the context and reset last_flush_at).
        ctx = slack_render_contexts.get("C123", str(turn_id))
        full_text = ""
        for i in range(50):
            full_text += f"tok{i} "
            # Force the debounce on every 5th token to simulate the
            # pace at which 0.8s windows would actually fire on the wall
            # clock during a real streamed turn.
            if i % 5 == 0:
                ctx.last_flush_at = time.monotonic() - (STREAM_FLUSH_INTERVAL + 0.1)
            await renderer.render(_token(turn_id, f"tok{i} "), target)

        # 3. Final TURN_ENDED.
        await renderer.render(_ended(turn_id, full_text.strip()), target)

        # ----- Assertions ------------------------------------------------
        post_calls = fake_slack_http.calls_to("chat.postMessage")
        update_calls = fake_slack_http.calls_to("chat.update")

        # Exactly one POST: the thinking placeholder. No second POST for
        # the body (the renderer reuses the placeholder via chat.update).
        assert len(post_calls) == 1, (
            f"expected exactly one chat.postMessage, got {len(post_calls)}"
        )
        assert post_calls[0]["body"]["channel"] == "C123"

        # Update calls are bounded — must be far fewer than 50 (one per
        # token would be the bug). The exact count depends on debounce
        # math + safety-pass behavior, but it should land roughly at
        # one flush per 5-token batch (the test cheat advances the
        # wall clock every 5 tokens), plus a possible safety-pass
        # edit per flush, plus the final TURN_ENDED edit. The hard
        # ceiling: it must be at most ~half the token count, since
        # one-per-token is the literal bug.
        assert len(update_calls) >= 1, "expected at least one chat.update flush"
        assert len(update_calls) < 30, (
            f"expected coalesced chat.update calls (<30), got {len(update_calls)} — "
            f"the debounce window is broken"
        )

        # The LAST chat.update is the TURN_ENDED final edit and must
        # carry the full text (no truncation marker on the final state).
        last_update = update_calls[-1]
        assert "tok49" in last_update["body"]["text"]
        assert "tok0" in last_update["body"]["text"]
        # Final state must NOT have the streaming "..." trailing marker
        # (only intermediate flushes append " ..." for visual hint).
        assert not last_update["body"]["text"].endswith(" ..."), (
            "final TURN_ENDED edit should not carry the streaming '...' marker"
        )

        # Render-context registry is empty after TURN_ENDED.
        assert slack_render_contexts.get("C123", str(turn_id)) is None

    async def test_no_orphaned_placeholder_on_error(self, fake_slack_http):
        """If the agent emits TURN_ENDED with an error, the placeholder
        is updated to the error text (not left dangling)."""
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _target()

        await renderer.render(_started(turn_id), target)
        await renderer.render(
            ChannelEvent(
                channel_id=uuid.uuid4(),
                kind=ChannelEventKind.TURN_ENDED,
                payload=TurnEndedPayload(
                    bot_id="bot1",
                    turn_id=turn_id,
                    result=None,
                    error="provider timed out",
                    client_actions=[],
                ),
            ),
            target,
        )

        update_calls = fake_slack_http.calls_to("chat.update")
        assert len(update_calls) == 1
        final_text = update_calls[-1]["body"]["text"]
        assert "provider timed out" in final_text
        assert "Agent error" in final_text
        # Registry cleared.
        assert slack_render_contexts.get("C123", str(turn_id)) is None

    async def test_two_parallel_turns_do_not_share_state(self, fake_slack_http):
        """Two simultaneous turns on the same Slack channel must not
        share placeholder state — each turn gets its own ts.
        """
        renderer = SlackRenderer()
        target = _target()
        turn_a = uuid.uuid4()
        turn_b = uuid.uuid4()

        await renderer.render(_started(turn_a), target)
        await renderer.render(_started(turn_b), target)

        ctx_a = slack_render_contexts.get("C123", str(turn_a))
        ctx_b = slack_render_contexts.get("C123", str(turn_b))
        assert ctx_a is not None
        assert ctx_b is not None
        assert ctx_a.thinking_ts != ctx_b.thinking_ts
        # Both placeholders posted as separate chat.postMessage calls.
        assert len(fake_slack_http.calls_to("chat.postMessage")) == 2
