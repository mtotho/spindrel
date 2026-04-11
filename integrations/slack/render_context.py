"""Per-channel render context for SlackRenderer.

The Slack renderer needs state that persists across multiple
ChannelEvents within the same turn:

- The Slack ``ts`` of the "thinking…" placeholder (so streaming token
  deltas update it via ``chat.update`` instead of posting new messages).
- The accumulated streaming text (so the placeholder edit shows the
  partial response, not just the latest token).
- A debounced flush schedule so we don't fire ``chat.update`` on every
  token arrival — that's the rapid-edit pattern Slack mobile clients
  occasionally fail to refresh from, which is the original
  user-reported bug this whole track was started to fix.

State is keyed by ``(channel_id, turn_id)`` so parallel multi-bot turns
on the same Slack channel don't trample each other.

The legacy ``SlackStreamBuffer`` (in
``integrations/slack/message_handlers.py:118-163``) lived inside the
in-subprocess long-poll path and is now obsolete — that whole function
gets deleted in the same commit as this renderer lands.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Slack's chat_update accepts plain text up to 40k chars but the in-thread
# rendering trims at ~3500 cleanly. Match the legacy SlackStreamBuffer
# value so the visual behavior is unchanged.
STREAM_MAX_CHARS = 3500

# Minimum interval between ``chat.update`` calls for the same placeholder.
# Same value as the legacy SlackStreamBuffer; the safety-pass queue below
# absorbs token bursts that arrive while a flush is in flight, eliminating
# the rapid-edit race that broke Slack mobile caches.
STREAM_FLUSH_INTERVAL = 0.8


@dataclass
class TurnContext:
    """Mutable state for one in-flight Slack turn placeholder."""

    bot_id: str
    thinking_channel: str | None = None
    thinking_ts: str | None = None
    accumulated_text: str = ""
    last_flush_at: float = 0.0
    flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_text: str | None = None
    """If a token arrives while ``flush_lock`` is held, the renderer
    stashes the latest accumulated text here. After the in-flight flush
    completes, the lock holder fires one more update with the queued
    text. This is the safety-pass that prevents Slack mobile clients
    from missing the final state.
    """


@dataclass
class _RegistryEntry:
    by_turn: dict[str, TurnContext] = field(default_factory=dict)


class SlackRenderContextRegistry:
    """Registry of per-channel, per-turn ``TurnContext`` objects.

    Keyed by ``channel_id`` (the Slack channel id, NOT the agent-server
    channel id) and then by ``turn_id`` (a string for JSON friendliness;
    the renderer converts ``uuid.UUID`` to str at lookup time).
    """

    def __init__(self) -> None:
        self._by_channel: dict[str, _RegistryEntry] = {}

    def get_or_create(
        self, slack_channel_id: str, turn_id: str, *, bot_id: str
    ) -> TurnContext:
        entry = self._by_channel.get(slack_channel_id)
        if entry is None:
            entry = _RegistryEntry()
            self._by_channel[slack_channel_id] = entry
        ctx = entry.by_turn.get(turn_id)
        if ctx is None:
            ctx = TurnContext(bot_id=bot_id, last_flush_at=time.monotonic())
            entry.by_turn[turn_id] = ctx
        return ctx

    def get(self, slack_channel_id: str, turn_id: str) -> TurnContext | None:
        entry = self._by_channel.get(slack_channel_id)
        if entry is None:
            return None
        return entry.by_turn.get(turn_id)

    def discard(self, slack_channel_id: str, turn_id: str) -> None:
        """Remove the context for a finished turn so we don't leak memory."""
        entry = self._by_channel.get(slack_channel_id)
        if entry is None:
            return
        entry.by_turn.pop(turn_id, None)
        if not entry.by_turn:
            del self._by_channel[slack_channel_id]

    def has_active_turn(self, slack_channel_id: str) -> bool:
        """Return True if any turn context currently exists for this channel.

        Used by the NEW_MESSAGE handler to decide whether a bot-authored
        message is part of an in-flight turn (delivered via TURN_ENDED's
        streaming chat.update path) or a sideband message that needs to
        be posted as a fresh chat.postMessage.
        """
        entry = self._by_channel.get(slack_channel_id)
        return entry is not None and bool(entry.by_turn)

    def reset(self) -> None:
        """Test helper — wipe all state."""
        self._by_channel.clear()


# Single global registry instance — same singleton pattern as the rate
# limiter. SlackRenderer reads/writes through this.
slack_render_contexts = SlackRenderContextRegistry()
