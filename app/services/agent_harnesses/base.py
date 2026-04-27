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
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import (
    TurnStreamThinkingPayload,
    TurnStreamTokenPayload,
    TurnStreamToolResultPayload,
    TurnStreamToolStartPayload,
)
from app.services.channel_events import publish_typed


def _redact_text(text: str) -> str:
    """Apply the server's known-secret redactor at the harness host boundary."""
    from app.services.secret_registry import redact

    return redact(text)


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


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


@dataclass
class HarnessToolTranscriptEntry:
    id: str
    name: str
    arguments: dict
    result_summary: str | None = None
    is_error: bool = False


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
        self._tool_entries: list[HarnessToolTranscriptEntry] = []

    def token(self, delta: str) -> None:
        if not delta:
            return
        delta = _redact_text(delta)
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
        delta = _redact_text(delta)
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
        call_id = tool_call_id or f"harness:{len(self._tool_entries) + 1}"
        redacted_args = _redact_value(arguments or {})
        self._tool_entries.append(
            HarnessToolTranscriptEntry(
                id=call_id,
                name=tool_name,
                arguments=redacted_args if isinstance(redacted_args, dict) else {},
            )
        )
        publish_typed(
            self._channel_id,
            ChannelEvent(
                channel_id=self._channel_id,
                kind=ChannelEventKind.TURN_STREAM_TOOL_START,
                payload=TurnStreamToolStartPayload(
                    bot_id=self._bot_id,
                    turn_id=self._turn_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    arguments=redacted_args if isinstance(redacted_args, dict) else {},
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
        result_summary = _redact_text(result_summary)
        if tool_call_id:
            for entry in reversed(self._tool_entries):
                if entry.id == tool_call_id:
                    entry.result_summary = result_summary
                    entry.is_error = is_error
                    break
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

    def persisted_tool_calls(self) -> list[dict[str, Any]]:
        """Return live harness tools in the existing persisted ToolCall shape."""
        calls: list[dict[str, Any]] = []
        for entry in self._tool_entries:
            calls.append(
                {
                    "id": entry.id,
                    "type": "function",
                    "function": {
                        "name": entry.name,
                        "arguments": entry.arguments,
                    },
                    "surface": "transcript",
                    "summary": {
                        "kind": "error" if entry.is_error else "result",
                        "subject_type": "tool",
                        "label": entry.name,
                        "preview_text": entry.result_summary,
                    },
                }
            )
        return calls

    def assistant_turn_body(self, *, text: str) -> dict[str, Any] | None:
        items: list[dict[str, Any]] = []
        if text.strip():
            items.append({"id": "text:final", "kind": "text", "text": text})
        for entry in self._tool_entries:
            items.append({"id": f"tool:{entry.id}", "kind": "tool_call", "toolCallId": entry.id})
        return {"version": 1, "items": items} if items else None


# Type alias for callers that hand the emitter into a driver — keeps the
# Protocol signature readable.
HarnessEmit = Callable[[], Awaitable[None]]  # placeholder, currently unused


# Factory type: a zero-arg callable that returns an async context manager
# yielding an AsyncSession. Threaded into the harness driver so it can open
# short DB scopes for approval-row writes without holding a session across
# the SDK loop.
DbSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True)
class HarnessContextHint:
    """Ephemeral host-provided context for the next harness turn.

    Harnesses own their native transcript, so Spindrel cannot splice context
    sections into a provider-managed prompt the way the normal loop does. This
    is the small portable shape we thread into runtime adapters for one-shot
    host hints such as heartbeat summaries, compact continuity summaries, and
    future memory recalls.
    """

    kind: str
    text: str
    created_at: str
    source: str | None = None
    consume_after_next_turn: bool = True


@dataclass(frozen=True)
class TurnContext:
    """Everything a harness driver needs to run one turn against the SDK.

    Constructed once by ``turn_worker._run_harness_turn`` and passed to the
    runtime's ``start_turn``. Carries the Spindrel session/channel/turn ids
    so the driver can request approvals through ``request_harness_approval``
    (which writes a ``ToolApproval`` row scoped to this session/channel).

    ``permission_mode`` is captured at turn start and immutable for this
    turn — mode changes via the channel header pill apply to the *next*
    turn, not the in-flight one.
    """

    spindrel_session_id: uuid.UUID
    """Spindrel's ``Session.id`` — distinct from the harness-native resume id."""
    channel_id: uuid.UUID | None
    """``None`` for channel-less harness turns. Approval ask paths must guard
    on ``None`` (no UI to resolve through) and deny safely."""
    bot_id: str
    turn_id: uuid.UUID
    workdir: str
    """Absolute path the harness uses as its cwd."""
    harness_session_id: str | None
    """Harness-native resume token from the previous turn (``None`` on first turn)."""
    permission_mode: str
    """One of ``bypassPermissions`` | ``acceptEdits`` | ``default`` | ``plan``."""
    db_session_factory: DbSessionFactory
    """Open a short DB scope: ``async with ctx.db_session_factory() as db: ...``."""
    model: str | None = None
    """Per-session harness model id, or ``None`` to let the runtime pick its
    default. Runtime adapters translate to the SDK-native kwarg
    (``ClaudeAgentOptions(model=...)`` for Claude). Stored on
    ``Session.metadata['harness_settings']['model']``."""
    effort: str | None = None
    """Per-session reasoning-effort hint. Only meaningful when the runtime
    declares non-empty ``effort_values`` in ``RuntimeCapabilities``. Claude
    Code currently has no effort knob, so this is unused for that runtime."""
    runtime_settings: Mapping[str, Any] = field(default_factory=dict)
    """Opaque per-runtime settings bag for knobs that don't fit the generic
    model/effort shape. Each runtime adapter owns the schema; the host stores
    and threads the dict without inspection."""
    context_hints: tuple[HarnessContextHint, ...] = ()
    """One-shot host context hints to prepend/inject into this harness turn.
    The turn worker clears consumed hints after the runtime accepts the turn."""


@dataclass(frozen=True)
class HarnessSlashCommandPolicy:
    """Per-runtime allowlist of generic Spindrel slash commands.

    The slash-command catalog endpoint and ``/help`` intersect this with the
    surface-filtered registry when a harness bot is in scope. Commands
    outside this set are hidden from picker and ``/help``, but typed
    invocations still reach their handlers (which can return a friendly
    no-op for harness sessions).
    """

    allowed_command_ids: frozenset[str]


@dataclass(frozen=True)
class HarnessModelOption:
    """One runtime-native model choice plus its reasoning-effort values."""

    id: str
    label: str | None = None
    effort_values: tuple[str, ...] = ()
    default_effort: str | None = None


@dataclass(frozen=True)
class RuntimeCapabilities:
    """What a harness runtime exposes to the UI / slash dispatcher.

    Static per process — capabilities are computed once and cached by the
    UI for the runtime's lifetime. Bumping a runtime's capabilities
    requires a process restart, which matches how runtimes register today.
    """

    display_name: str
    """Human-readable name shown in the header runtime badge."""
    supported_models: tuple[str, ...] = ()
    """Curated suggestion list for the model pill. Empty = no curation."""
    model_options: tuple[HarnessModelOption, ...] = ()
    """Preferred model picker contract. Each runtime owns model ids and the
    effort values valid for that model. ``supported_models`` remains a
    compatibility projection for older clients."""
    model_is_freeform: bool = True
    """``True`` → the model pill renders a freeform text input (with
    ``supported_models`` as suggestions if non-empty). ``False`` → strict
    dropdown of ``supported_models`` only."""
    effort_values: tuple[str, ...] = ()
    """Compatibility projection: union/default effort values for older
    clients. New UI should read ``model_options[*].effort_values`` first."""
    approval_modes: tuple[str, ...] = (
        "bypassPermissions",
        "acceptEdits",
        "default",
        "plan",
    )
    """Allowed values for the approval-mode pill."""
    slash_policy: "HarnessSlashCommandPolicy" = field(
        default_factory=lambda: HarnessSlashCommandPolicy(
            allowed_command_ids=frozenset()
        ),
    )
    """Generic-slash allowlist for harness sessions on this runtime."""


@runtime_checkable
class HarnessRuntime(Protocol):
    """One external agent harness, plugged in as a bot runtime.

    Implementations live in ``integrations/<name>/harness.py`` and self-register
    via ``register_runtime`` (see ``integrations.sdk``).
    """

    name: str
    """Stable identifier persisted on ``bots.harness_runtime``. Renaming
    this is a migration."""

    async def start_turn(
        self,
        *,
        ctx: TurnContext,
        prompt: str,
        emit: ChannelEventEmitter,
    ) -> TurnResult:
        """Drive one turn against the external harness.

        ``ctx`` carries Spindrel session/channel/turn ids, workdir, harness
        resume token, permission_mode, and a db session factory. ``emit``
        bridges live progress onto our channel-events bus. Return value is
        persisted by the caller.
        """
        ...

    def auth_status(self) -> AuthStatus:
        """Report whether this harness is logged in / ready to run."""
        ...

    def readonly_tools(self) -> frozenset[str]:
        """Tools that auto-approve in every mode.

        Read-only tools stay allowed in ``plan`` mode too — the SDK's plan
        ``permission_mode`` independently restricts writes, so listing them
        here is safe and avoids prompting on filesystem reads.
        """
        ...

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        """True if this tool should ask in ``acceptEdits`` mode.

        ``acceptEdits`` lets the SDK auto-approve Edit/Write writes, but the
        runtime still has to opt other side-effecting tools (e.g. ``Bash``,
        ``WebFetch``, ``ExitPlanMode``) into the ask path.
        """
        ...

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        """True if this tool auto-approves in ``plan`` mode.

        For Claude this is ``ExitPlanMode`` — the SDK renders the plan
        natively and exiting plan mode is the natural end-of-step, not a
        write the user needs to gate on.
        """
        ...

    def capabilities(self) -> "RuntimeCapabilities":
        """Static control surface this runtime exposes.

        Returns a frozen ``RuntimeCapabilities`` describing which model,
        effort, approval-mode, and slash-command controls the UI should
        render for sessions on this runtime. The host treats every field
        opaquely — runtime-specific names live here, never in ``app/``.
        """
        ...

    async def list_models(self) -> tuple[str, ...]:
        """Models this runtime can drive right now.

        Distinct from ``capabilities().supported_models``: that field is a
        UI hint (curated short list, may be empty for freeform runtimes);
        this method is the *live* list — the runtime can introspect the
        SDK, the underlying CLI, or its own catalog. The capabilities
        endpoint calls this on demand and returns the result as
        ``available_models``. Default: empty.
        """
        return ()
