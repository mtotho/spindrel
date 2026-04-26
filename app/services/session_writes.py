"""Stage Message rows for one turn behind a narrow seam.

This module owns: metadata-key vocabulary, per-row microsecond ordering,
role-default sender stamping, delegate_to_agent argument parsing,
hidden/heartbeat/skill tagging, and the assistant tool-call normalization
hook.

It does NOT own: the transaction (commit/rollback), outbox enqueue,
attachment linking, or bus publish. Those stay in
``app.services.sessions.persist_turn`` because they coordinate across
modules — keeping them out preserves the Cluster 15 invariant that bus
publish runs post-commit, fire-and-forget.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig
from app.db.models import Message
from app.services.sessions import _content_for_db
from app.services.tool_presentation import normalize_persisted_tool_calls


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnContext:
    """Per-turn context that does not vary row-to-row.

    Caller invariants:
      - ``now`` is timezone-aware UTC. Rows in the staged turn are written
        at ``now + i*µs`` for ``i = 0..len(messages)-1``; the caller MUST
        NOT mutate ``now`` between staging and the matching
        ``Session.last_active`` update.
      - ``pre_user_msg_id`` is set iff the first user row was already
        persisted upstream (pre-loop). When set, ``msg_metadata`` is NOT
        consumed here — it was already attached to the pre-persisted row.
      - ``msg_metadata``, when consumed, is attached to the FIRST user row
        only; subsequent user rows in the same turn get role-default
        metadata.
    """

    session_id: uuid.UUID
    bot: BotConfig
    correlation_id: uuid.UUID | None
    msg_metadata: dict | None
    is_heartbeat: bool
    hide_messages: bool
    pre_user_msg_id: uuid.UUID | None
    now: datetime


@dataclass(frozen=True)
class TurnWriteResult:
    """Outcome of staging one turn.

    ``records`` are already attached to the session via ``db.add(...)`` in
    the same order as the input ``messages``. The caller still owns the
    transaction boundary — flush/commit happens in ``persist_turn``.
    """

    records: list[Message]
    first_user_msg_id: uuid.UUID | None
    last_assistant_msg_id: uuid.UUID | None


def stage_turn_messages(
    db: AsyncSession,
    ctx: TurnContext,
    messages: Sequence[dict],
) -> TurnWriteResult:
    """Build metadata, materialize Message rows, and stage them on ``db``.

    ``messages`` must already be filtered (see ``_filter_messages_to_persist``).
    Each row is added to the session in order; the function never flushes,
    commits, or rolls back.

    Error modes:
      - A malformed ``delegate_to_agent`` tool-call ``arguments`` JSON is
        logged at WARNING and that single delegation entry is skipped.
        Other delegations in the same tool-call list still land. The row
        itself is always staged — losing telemetry must not lose history.
      - All other exceptions propagate; the caller's transaction rolls back.
    """

    first_user_with_metadata = ctx.pre_user_msg_id is None
    first_user_msg_id: uuid.UUID | None = ctx.pre_user_msg_id
    last_assistant_msg_id: uuid.UUID | None = None
    persisted_records: list[Message] = []

    for i, msg in enumerate(messages):
        meta = _metadata_for_row(
            msg,
            ctx=ctx,
            claim_first_user_metadata=first_user_with_metadata,
        )
        if (
            ctx.msg_metadata
            and msg.get("role") == "user"
            and first_user_with_metadata
        ):
            first_user_with_metadata = False

        record = Message(
            id=uuid.uuid4(),
            session_id=ctx.session_id,
            role=msg["role"],
            content=_content_for_db(msg),
            tool_calls=(
                normalize_persisted_tool_calls(
                    msg.get("tool_calls"),
                    envelopes=msg.get("_tool_envelopes"),
                )
                if msg.get("role") == "assistant"
                else msg.get("tool_calls")
            ),
            tool_call_id=msg.get("tool_call_id"),
            correlation_id=ctx.correlation_id,
            metadata_=meta,
            created_at=ctx.now + timedelta(microseconds=i),
        )
        db.add(record)
        persisted_records.append(record)

        if first_user_msg_id is None and msg.get("role") == "user":
            first_user_msg_id = record.id
        if msg.get("role") == "assistant":
            last_assistant_msg_id = record.id

    return TurnWriteResult(
        records=persisted_records,
        first_user_msg_id=first_user_msg_id,
        last_assistant_msg_id=last_assistant_msg_id,
    )


def _metadata_for_row(
    msg: dict,
    *,
    ctx: TurnContext,
    claim_first_user_metadata: bool,
) -> dict:
    """Compose the metadata dict for one Message row.

    ``claim_first_user_metadata`` is the per-iteration flag from
    ``stage_turn_messages``; True means this row is allowed to consume
    ``ctx.msg_metadata`` (role=user only).
    """

    meta: dict = {}
    if (
        ctx.msg_metadata
        and msg.get("role") == "user"
        and claim_first_user_metadata
    ):
        meta = dict(ctx.msg_metadata)
    if msg.get("role") == "assistant" and not meta:
        meta = {
            "sender_type": "bot",
            "sender_id": f"bot:{ctx.bot.id}",
            "sender_display_name": ctx.bot.name,
        }
    if msg.get("_tools_used"):
        meta = {**meta, "tools_used": msg["_tools_used"]}
    if msg.get("_tool_envelopes"):
        meta = {**meta, "tool_results": msg["_tool_envelopes"]}
    if msg.get("_thinking_content"):
        meta = {**meta, "thinking": msg["_thinking_content"]}
    assistant_turn_body = msg.get("_assistant_turn_body")
    if not assistant_turn_body and msg.get("_transcript_entries"):
        assistant_turn_body = {"version": 1, "items": msg["_transcript_entries"]}
    if assistant_turn_body:
        meta = {**meta, "assistant_turn_body": assistant_turn_body}
    if msg.get("_tool_record_id"):
        meta = {**meta, "tool_record_id": msg["_tool_record_id"]}
    if msg.get("_no_prune"):
        meta = {**meta, "no_prune": True}
    if msg.get("_auto_injected_skills"):
        meta = {**meta, "auto_injected_skills": msg["_auto_injected_skills"]}
    if msg.get("_active_skills"):
        meta = {**meta, "active_skills": msg["_active_skills"]}
    if msg.get("_skills_in_context"):
        meta = {**meta, "skills_in_context": msg["_skills_in_context"]}
    if msg.get("_llm_status"):
        meta = {**meta, "llm_status": msg["_llm_status"]}
    if msg.get("_turn_error"):
        meta = {**meta, "turn_error": True}
        if msg.get("_turn_error_message"):
            meta = {**meta, "turn_error_message": str(msg["_turn_error_message"])}
    if msg.get("_suppress_outbox"):
        meta = {**meta, "suppress_outbox": True}
    if msg.get("_internal_kind"):
        meta = {**meta, "internal_kind": str(msg["_internal_kind"])}

    delegations = _extract_delegations(
        msg, session_id=ctx.session_id, correlation_id=ctx.correlation_id
    )
    if delegations:
        meta = {**meta, "delegations": delegations}

    if ctx.is_heartbeat:
        meta = {**meta, "is_heartbeat": True}
    # Pipeline agent-step children: persist for session-history context but tag
    # so the web UI filter drops them (see useChannelChat.ts).
    if ctx.hide_messages:
        meta = {**meta, "hidden": True, "pipeline_step": True}
    if msg.get("_hidden"):
        meta = {**meta, "hidden": True}
    return meta


def _extract_delegations(
    msg: dict,
    *,
    session_id: uuid.UUID,
    correlation_id: uuid.UUID | None,
) -> list[dict]:
    """Pull ``delegate_to_agent`` summaries from an assistant row's tool_calls.

    Malformed JSON in ``arguments`` is logged at WARNING and that single
    entry is skipped — the surrounding row + other delegations in the same
    list still land.
    """

    if msg.get("role") != "assistant" or not msg.get("tool_calls"):
        return []

    delegations: list[dict] = []
    for tc in msg["tool_calls"]:
        fn = tc.get("function") or {}
        if fn.get("name") != "delegate_to_agent":
            continue
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Malformed delegate_to_agent arguments dropped from metadata "
                "(session=%s correlation=%s tool_call_id=%s args_preview=%r)",
                session_id,
                correlation_id,
                tc.get("id"),
                (raw_args[:120] if isinstance(raw_args, str) else type(raw_args).__name__),
            )
            continue
        if not isinstance(args, dict):
            logger.warning(
                "delegate_to_agent arguments JSON parsed to non-object — skipped "
                "(session=%s correlation=%s tool_call_id=%s type=%s)",
                session_id,
                correlation_id,
                tc.get("id"),
                type(args).__name__,
            )
            continue
        delegations.append(
            {
                "bot_id": args.get("bot_id"),
                "prompt_preview": (args.get("prompt") or "")[:200],
                "notify_parent": args.get("notify_parent", True),
            }
        )
    return delegations
