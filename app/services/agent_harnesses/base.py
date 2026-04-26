"""Protocol + dataclasses for agent-harness runtimes.

A ``HarnessRuntime`` is a small adapter around an external agent loop
(Claude Code, Codex, etc.). It owns one method that drives a single turn:
pump the harness's streaming messages into ``ChannelEventEmitter`` calls,
collect the final assistant text + provenance, return.

The emitter wraps the existing ``publish_typed`` / ``ChannelEventKind``
machinery so harness turns appear on the bus indistinguishably from RAG
turns. No new event types, no new renderer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol, runtime_checkable

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import (
    TurnStreamThinkingPayload,
    TurnStreamTokenPayload,
    TurnStreamToolResultPayload,
    TurnStreamToolStartPayload,
)
from app.services.channel_events import publish_typed


@dataclass(frozen=True)
class AuthStatus:
    """Reported by ``HarnessRuntime.auth_status()``.

    ``ok`` is the only field UIs need to gate on; ``detail`` is human-readable
    instructions ("Logged in via /home/spindrel/.claude/.credentials.json" or
    "Run `claude login` inside the Spindrel container").

    ``suggested_command`` is an optional hint the admin UI can offer as a
    one-click action (opens the in-app terminal pre-seeded with the command).
    Each integration owns this hint — core knows nothing about Claude vs Codex
    auth flows. Leave ``None`` for runtimes that have no copy-pasteable setup
    command.
    """

    ok: bool
    detail: str
    suggested_command: str | None = None


@dataclass
class TurnResult:
    """Returned by ``HarnessRuntime.start_turn``.

    ``session_id`` is the harness-native id used to resume the conversation
    on the next turn (Claude SDK's ``ClaudeAgentOptions(resume=...)``).
    ``final_text`` is what we persist on the assistant Message row so refresh
    rehydrates the transcript without needing the live event stream.
    """

    session_id: str
    final_text: str
    cost_usd: float | None = None
    usage: dict | None = None


class ChannelEventEmitter:
    """Thin scoped wrapper around ``publish_typed``.

    Constructed once per turn with ``(channel_id, turn_id, bot_id, session_id)``
    so drivers don't have to thread those through every call. Each method maps
    one harness-side concept onto an existing ``ChannelEventKind`` payload.
    """

    def __init__(
        self,
        *,
        channel_id: uuid.UUID,
        turn_id: uuid.UUID,
        bot_id: str,
        session_id: uuid.UUID | None = None,
    ) -> None:
        self._channel_id = channel_id
        self._turn_id = turn_id
        self._bot_id = bot_id
        self._session_id = session_id

    def token(self, delta: str) -> None:
        if not delta:
            return
        publish_typed(
            self._channel_id,
            ChannelEvent(
                channel_id=self._channel_id,
                kind=ChannelEventKind.TURN_STREAM_TOKEN,
                payload=TurnStreamTokenPayload(
                    bot_id=self._bot_id,
                    turn_id=self._turn_id,
                    delta=delta,
                    session_id=self._session_id,
                ),
            ),
        )

    def thinking(self, delta: str) -> None:
        if not delta:
            return
        publish_typed(
            self._channel_id,
            ChannelEvent(
                channel_id=self._channel_id,
                kind=ChannelEventKind.TURN_STREAM_THINKING,
                payload=TurnStreamThinkingPayload(
                    bot_id=self._bot_id,
                    turn_id=self._turn_id,
                    delta=delta,
                    session_id=self._session_id,
                ),
            ),
        )

    def tool_start(
        self,
        *,
        tool_name: str,
        arguments: dict | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        publish_typed(
            self._channel_id,
            ChannelEvent(
                channel_id=self._channel_id,
                kind=ChannelEventKind.TURN_STREAM_TOOL_START,
                payload=TurnStreamToolStartPayload(
                    bot_id=self._bot_id,
                    turn_id=self._turn_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    arguments=arguments or {},
                    surface="harness",
                    session_id=self._session_id,
                ),
            ),
        )

    def tool_result(
        self,
        *,
        tool_name: str,
        result_summary: str,
        is_error: bool = False,
        tool_call_id: str | None = None,
    ) -> None:
        publish_typed(
            self._channel_id,
            ChannelEvent(
                channel_id=self._channel_id,
                kind=ChannelEventKind.TURN_STREAM_TOOL_RESULT,
                payload=TurnStreamToolResultPayload(
                    bot_id=self._bot_id,
                    turn_id=self._turn_id,
                    tool_name=tool_name,
                    result_summary=result_summary,
                    tool_call_id=tool_call_id,
                    is_error=is_error,
                    surface="harness",
                    session_id=self._session_id,
                ),
            ),
        )


# Type alias for callers that hand the emitter into a driver — keeps the
# Protocol signature readable.
HarnessEmit = Callable[[], Awaitable[None]]  # placeholder, currently unused


@runtime_checkable
class HarnessRuntime(Protocol):
    """One external agent harness, plugged in as a bot runtime.

    Implementations live next to this file (``claude_code.py``, future
    ``codex.py``). Register them in ``__init__.py``'s ``HARNESS_REGISTRY``.
    """

    name: str
    """Stable identifier persisted on ``bots.harness_runtime``. Renaming
    this is a migration."""

    async def start_turn(
        self,
        *,
        workdir: str,
        prompt: str,
        session_id: str | None,
        emit: ChannelEventEmitter,
    ) -> TurnResult:
        """Drive one turn against the external harness.

        ``workdir`` is the absolute path the harness should run against
        (its ``cwd``). ``session_id`` is the harness-native resume token from
        the previous turn (``None`` on first turn). ``emit`` bridges live
        progress onto our channel-events bus. Return value is persisted by
        the caller.
        """
        ...

    def auth_status(self) -> AuthStatus:
        """Report whether this harness is logged in / ready to run."""
        ...
