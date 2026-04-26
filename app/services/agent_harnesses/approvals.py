"""Harness approval helper — bridges the harness's `can_use_tool` callback
into Spindrel's existing tool-approval system.

Harness drivers (claude_code, future codex) call ``request_harness_approval``
from their `can_use_tool`-equivalent. The helper:

1. Checks the per-turn bypass set (set by "Approve all this turn" button).
2. Short-circuits for ``bypassPermissions`` mode and runtime-classified
   read-only tools.
3. Otherwise writes a ``ToolApproval`` row (``tool_type='harness'``,
   ``tool_call_id=None`` — no linked ToolCall, see Architecture Decisions),
   registers a Future via ``approval_pending``, publishes
   ``APPROVAL_REQUESTED`` on the channel bus, and awaits.

Decisions feed back through the standard
``POST /api/v1/approvals/{id}/decide`` → ``resolve_approval`` path.

Codex compatibility: harnesses each implement their own
``can_use_tool``-equivalent. They all call this helper with the same
``TurnContext`` and a ``runtime`` whose tool-classification methods describe
its native tool vocabulary. The four modes themselves stay portable.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agent.approval_pending import cancel_approval, create_approval_pending
from app.db.engine import async_session
from app.db.models import ToolApproval
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import ApprovalRequestedPayload, ApprovalResolvedPayload
from app.services.agent_harnesses.base import HarnessRuntime, TurnContext
from app.services.channel_events import publish_typed
from app.utils import safe_create_task

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

HARNESS_APPROVAL_MODE_KEY = "harness_approval_mode"
DEFAULT_MODE = "bypassPermissions"
VALID_MODES: frozenset[str] = frozenset(
    {"bypassPermissions", "acceptEdits", "default", "plan"}
)

# Default approval-row timeout. Must match the user-facing copy on the
# expired card.
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300


# ---------------------------------------------------------------------------
# Public dataclass — what the harness driver translates to its native shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllowDeny:
    """The helper's harness-agnostic allow/deny verdict."""

    allow: bool
    reason: str | None = None

    @classmethod
    def allow_(cls) -> "AllowDeny":
        return cls(allow=True)

    @classmethod
    def deny(cls, reason: str) -> "AllowDeny":
        return cls(allow=False, reason=reason)


# ---------------------------------------------------------------------------
# Per-turn allow-all (set by "Approve all this turn" button)
# ---------------------------------------------------------------------------
#
# Process-local set of turn ids granted bypass for the rest of their turn.
# Cleared by ``_run_harness_turn``'s try/finally regardless of outcome.
# Not persisted — we don't want a crashed turn leaving a session permanently
# bypassed via Session.metadata, and the bypass only ever needs to live for
# the lifetime of a single SDK loop.

_TURN_BYPASS: set[str] = set()


def grant_turn_bypass(turn_id: uuid.UUID | str) -> None:
    """Bypass approvals for the rest of the named turn."""
    _TURN_BYPASS.add(str(turn_id))


def revoke_turn_bypass(turn_id: uuid.UUID | str) -> None:
    """Drop a turn from the bypass set. Always safe to call (no-op if absent)."""
    _TURN_BYPASS.discard(str(turn_id))


def is_turn_bypassed(turn_id: uuid.UUID | str) -> bool:
    return str(turn_id) in _TURN_BYPASS


# ---------------------------------------------------------------------------
# Snapshot used by the SSE emit task — primitives only, no ORM across await.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ApprovalSnapshot:
    approval_id: str
    bot_id: str
    tool_name: str
    arguments: dict
    reason: str
    turn_id: uuid.UUID
    session_id: uuid.UUID
    channel_id: uuid.UUID


# ---------------------------------------------------------------------------
# Mode read/write — stored on Session.metadata
# ---------------------------------------------------------------------------


async def load_session_mode(db, session_id: uuid.UUID) -> str:
    """Return the per-session approval mode, defaulting to ``DEFAULT_MODE``."""
    from app.db.models import Session  # local import to avoid cycle on app boot

    session = await db.get(Session, session_id)
    if session is None:
        return DEFAULT_MODE
    meta = session.metadata_ or {}
    mode = meta.get(HARNESS_APPROVAL_MODE_KEY)
    return mode if mode in VALID_MODES else DEFAULT_MODE


async def set_session_mode(db, session_id: uuid.UUID, mode: str) -> None:
    """Persist a new approval mode for the session.

    Mirrors ``app/services/session_plan_mode.py`` — pop, set, flag_modified,
    commit. Raises ValueError for unknown modes (caller should 422).
    """
    from sqlalchemy.orm.attributes import flag_modified

    from app.db.models import Session

    if mode not in VALID_MODES:
        raise ValueError(f"unknown approval mode: {mode!r}")

    session = await db.get(Session, session_id)
    if session is None:
        from app.domain.errors import NotFoundError

        raise NotFoundError(f"session {session_id} not found")

    meta = dict(session.metadata_ or {})
    meta.pop(HARNESS_APPROVAL_MODE_KEY, None)
    meta[HARNESS_APPROVAL_MODE_KEY] = mode
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    await db.commit()


# ---------------------------------------------------------------------------
# Core helper
# ---------------------------------------------------------------------------


async def request_harness_approval(
    *,
    ctx: TurnContext,
    runtime: HarnessRuntime,
    tool_name: str,
    tool_input: dict,
) -> AllowDeny:
    """Decide allow/deny for one harness tool call.

    Called by the harness driver's ``can_use_tool`` callback. Returns a
    Spindrel-side ``AllowDeny`` the driver translates to its native verdict
    (``PermissionResultAllow``/``PermissionResultDeny`` for Claude, etc.).
    """
    # Per-turn bypass — set by "Approve all this turn" button. Cheap, no DB.
    if is_turn_bypassed(ctx.turn_id):
        return AllowDeny.allow_()

    if ctx.permission_mode == "bypassPermissions":
        return AllowDeny.allow_()

    if tool_name in runtime.readonly_tools():
        return AllowDeny.allow_()

    if ctx.permission_mode == "plan" and runtime.autoapprove_in_plan(tool_name):
        return AllowDeny.allow_()

    if ctx.permission_mode == "acceptEdits" and not runtime.prompts_in_accept_edits(
        tool_name
    ):
        return AllowDeny.allow_()

    # Ask path. Channel-less harness turn cannot surface an approval card.
    if ctx.channel_id is None:
        return AllowDeny.deny(
            "Cannot request approval — turn has no channel surface"
        )

    # Step 1: write row in a short DB scope, capture primitives BEFORE leaving.
    async with ctx.db_session_factory() as db:
        approval_id, snapshot = await _create_harness_approval_row(
            db=db, ctx=ctx, tool_name=tool_name, arguments=tool_input,
        )

    # Step 2: register the future BEFORE publishing the event so a fast-click
    # decide can resolve the future (otherwise the harness waits for timeout).
    future = create_approval_pending(approval_id)

    # Step 3: emit SSE event using only primitive fields (no ORM across await).
    safe_create_task(
        _publish_harness_approval_requested(snapshot),
        name=f"harness-approval-emit:{approval_id}",
    )

    # Step 4: wait without holding a DB session.
    try:
        verdict = await asyncio.wait_for(
            future, timeout=DEFAULT_APPROVAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        await expire_harness_approval(
            approval_id, reason="approval expired (5 minute timeout)",
        )
        return AllowDeny.deny(
            "Spindrel approval request expired (no decision in 5 minutes)"
        )

    if verdict == "approved":
        # If the user clicked "Approve all this turn", the decide endpoint has
        # already called grant_turn_bypass(turn_id) BEFORE resolving the future,
        # so subsequent tool calls in this turn short-circuit at the top of
        # this function via is_turn_bypassed.
        return AllowDeny.allow_()
    if verdict == "denied":
        return AllowDeny.deny("User denied this tool call")
    if verdict == "expired":
        return AllowDeny.deny("Approval expired")
    return AllowDeny.deny(f"Approval ended in unknown state: {verdict}")


async def _create_harness_approval_row(
    *,
    db,
    ctx: TurnContext,
    tool_name: str,
    arguments: dict,
) -> tuple[str, _ApprovalSnapshot]:
    """Write a ``tool_type='harness'`` ToolApproval row and return its id + snapshot.

    Build the reason string LOCALLY before commit and use it for both the row
    and the snapshot. We never read attributes off the row after commit because
    async SQLAlchemy may expire and re-fetch them.
    """
    approval_id = uuid.uuid4()
    reason = f"Harness approval ({ctx.permission_mode}): {tool_name}"
    args_snapshot = dict(arguments or {})
    row = ToolApproval(
        id=approval_id,
        session_id=ctx.spindrel_session_id,
        channel_id=ctx.channel_id,
        bot_id=ctx.bot_id,
        client_id=None,
        correlation_id=ctx.turn_id,
        tool_name=tool_name,
        tool_type="harness",
        arguments=args_snapshot,
        policy_rule_id=None,
        reason=reason,
        status="pending",
        dispatch_type="harness",
        approval_metadata={"surface": "harness"},
        tool_call_id=None,
        timeout_seconds=DEFAULT_APPROVAL_TIMEOUT_SECONDS,
    )
    db.add(row)
    await db.commit()

    # ctx.channel_id is guarded non-None by the caller's ask-path check.
    assert ctx.channel_id is not None  # noqa: S101  # defensive — checked upstream
    snapshot = _ApprovalSnapshot(
        approval_id=str(approval_id),
        bot_id=ctx.bot_id,
        tool_name=tool_name,
        arguments=args_snapshot,
        reason=reason,
        turn_id=ctx.turn_id,
        session_id=ctx.spindrel_session_id,
        channel_id=ctx.channel_id,
    )
    return str(approval_id), snapshot


async def _publish_harness_approval_requested(snapshot: _ApprovalSnapshot) -> None:
    """Background task: emit ``APPROVAL_REQUESTED`` for the harness card."""
    try:
        publish_typed(
            snapshot.channel_id,
            ChannelEvent(
                channel_id=snapshot.channel_id,
                kind=ChannelEventKind.APPROVAL_REQUESTED,
                payload=ApprovalRequestedPayload(
                    approval_id=snapshot.approval_id,
                    bot_id=snapshot.bot_id,
                    tool_name=snapshot.tool_name,
                    arguments=snapshot.arguments,
                    reason=snapshot.reason,
                    capability=None,
                    turn_id=snapshot.turn_id,
                    session_id=snapshot.session_id,
                    tool_type="harness",
                ),
            ),
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to publish APPROVAL_REQUESTED for harness approval %s",
            snapshot.approval_id,
        )


# ---------------------------------------------------------------------------
# Expire / cancel — used by timeout, Stop-turn, and chat_cancel
# ---------------------------------------------------------------------------


async def expire_harness_approval(approval_id: str, reason: str) -> None:
    """Mark a pending harness approval expired and notify the channel.

    Idempotent: returns silently if the row is already non-pending or absent.
    Updates the DB row, resolves the in-memory future (no-op if already
    resolved), and emits ``APPROVAL_RESOLVED(decision='expired')`` so the
    UI card flips to the expired state immediately rather than waiting on
    its own 300s timeout.
    """
    channel_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    async with async_session() as db:
        row = await db.get(ToolApproval, uuid.UUID(approval_id))
        if row is None or row.status != "pending":
            return
        row.status = "expired"
        row.decided_by = "system:expired"
        row.decided_at = datetime.now(timezone.utc)
        row.reason = (row.reason or "") + f" ({reason})"
        await db.commit()
        channel_id = row.channel_id
        session_id = row.session_id

    # Resolve any waiting future (no-op if already resolved by a racing decide).
    cancel_approval(approval_id)

    if channel_id is not None:
        try:
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.APPROVAL_RESOLVED,
                    payload=ApprovalResolvedPayload(
                        approval_id=approval_id,
                        decision="expired",
                        session_id=session_id,
                    ),
                ),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to publish APPROVAL_RESOLVED(expired) for %s",
                approval_id,
            )


async def cancel_pending_harness_approvals_for_session(
    session_id: uuid.UUID,
) -> int:
    """Expire every pending harness approval for the named session.

    Called by Stop-turn paths (slash command and ``/chat/cancel``) so the
    user doesn't have to wait on the 300s row timeout when they kill a turn.
    Returns the number of rows expired.
    """
    async with async_session() as db:
        rows = (
            await db.execute(
                select(ToolApproval).where(
                    ToolApproval.session_id == session_id,
                    ToolApproval.tool_type == "harness",
                    ToolApproval.status == "pending",
                )
            )
        ).scalars().all()
        ids = [str(r.id) for r in rows]

    for aid in ids:
        await expire_harness_approval(aid, reason="turn cancelled")
    return len(ids)
