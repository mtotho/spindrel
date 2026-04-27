"""Background turn worker — drives the agent loop after start_turn() returns 202.

Phase E of the Integration Delivery refactor. The HTTP /chat handler used
to be a 250-line ``event_generator`` that drove ``run_stream`` in-band and
yielded raw SSE bytes back to the client. That coupled the request lifetime
to the agent run, mixed transport with domain logic, and double-published
every event (once to the long-poll, once to the channel-events bus).

This module is the proper home for the agent-loop side of the chat
lifecycle. It runs as a background asyncio task spawned by
``app/services/turns.py:start_turn``. It owns its own DB session, sets the
agent ContextVars (per-task scoping), drives ``run_stream``, maps each event
to a typed ``ChannelEvent``, and publishes onto the channel-events bus.
``persist_turn`` lands the messages and enqueues outbox rows for the drainer
to fan out to integration renderers.

Subscribers (web UI, future Slack/Discord renderers via ``subscribe_all``)
tail the bus. The HTTP request returned 202 long ago.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import uuid
from contextlib import suppress
from datetime import datetime, timezone

from app.agent.bots import BotConfig, get_bot
from app.agent.context import (
    current_invoked_member_bots,
    set_agent_context,
)
from app.agent.loop import run_stream
from app.agent.recording import _record_trace_event
from app.db.engine import async_session
from app.db.models import Message as MessageModel, Session as SessionRow
from app.domain.actor import ActorRef
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    MessagePayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamToolResultPayload,
)
from app.routers.chat._context import BotContext
from app.routers.chat._multibot import (
    _background_tasks,
    _detect_member_mentions,
    _run_member_bot_reply,
    _trigger_member_bot_replies,
)
from app.routers.chat._schemas import ChatRequest
from app.services import session_locks
from app.services import presence
from app.services.agent_harnesses import ChannelEventEmitter, get_runtime
from app.services.channel_events import publish_typed
from app.services.compaction import maybe_compact
from app.services.delegation import delegation_service as _ds
from app.services.sessions import persist_turn
from app.services.turn_event_emit import emit_run_stream_events
from app.services.turn_supervisors import TurnEndContext, run_turn_supervisors
from app.services.turns import TurnHandle
from app.utils import safe_create_task

logger = logging.getLogger(__name__)

_HARNESS_SKILL_TAG_RE = re.compile(r"(?<![<\w@])@skill:([A-Za-z_][\w\-\./]*)")
_HARNESS_TOOL_TAG_RE = re.compile(r"(?<![<\w@])@tool:([A-Za-z_][\w\-\./]*)")


def _format_turn_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {message[:500]}"


def _build_turn_failure_message(error_text: str, partial_text: str = "") -> str:
    marker = f"[Turn failed: {error_text}]"
    if partial_text.strip():
        return f"{partial_text.rstrip()}\n\n{marker}"
    return f"The turn failed before producing a response.\n\n{marker}"


class _HarnessTurnCancelled(Exception):
    """Raised when a harness turn sees the session cancellation flag."""


def _parse_harness_explicit_tags(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    def _unique(matches: list[str]) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for value in matches:
            value = value.rstrip(".,;:!?")
            if value and value not in seen:
                seen.add(value)
                out.append(value)
        return tuple(out)

    return (
        _unique([m.group(1) for m in _HARNESS_TOOL_TAG_RE.finditer(text or "")]),
        _unique([m.group(1) for m in _HARNESS_SKILL_TAG_RE.finditer(text or "")]),
    )


async def _run_harness_turn(
    *,
    channel_id: uuid.UUID | None,
    bus_key: uuid.UUID,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    bot: BotConfig,
    user_message: str,
    correlation_id: uuid.UUID,
    msg_metadata: dict | None,
    pre_user_msg_id: uuid.UUID | None,
    suppress_outbox: bool,
    harness_model_override: str | None = None,
    harness_effort_override: str | None = None,
) -> tuple[str, str | None]:
    """Drive a turn against an external agent harness (Claude Code, Codex, ...).

    Bypasses run_stream entirely: the harness owns the agent loop, we own
    the chat surface. SDK messages stream onto the existing channel-events
    bus via ``ChannelEventEmitter`` so the UI renders them with no new code.

    Persistence: builds a synthetic assistant message tagged with
    ``_harness`` metadata, hands it to ``persist_turn`` (which strips the
    underscore-prefixed key into ``Message.metadata.harness``). The next
    turn reads the resume id from the most recent assistant message in
    THIS Spindrel session — keying per-session, not per-bot, so two
    channels using the same harness bot don't trample each other.

    Returns ``(response_text, error_text)``. ``error_text`` is None on
    success.
    """
    try:
        runtime = get_runtime(bot.harness_runtime)  # type: ignore[arg-type]
    except KeyError:
        msg = (
            f"Harness runtime '{bot.harness_runtime}' is not registered. "
            f"The integration may be inactive or its Python deps may be missing — "
            f"open /admin/integrations and click 'Reinstall (upgrade)'."
        )
        return await _persist_harness_failure(
            channel_id=channel_id, session_id=session_id, turn_id=turn_id,
            bot=bot, user_message=user_message, correlation_id=correlation_id,
            msg_metadata=msg_metadata, pre_user_msg_id=pre_user_msg_id,
            suppress_outbox=suppress_outbox, error_text=msg,
            prior_session_id=None,
        )
    prior_session_id = await _load_prior_harness_session_id(session_id)

    # Per-session approval mode (default ``bypassPermissions``) and per-session
    # harness settings (model / effort / opaque runtime knobs). Captured at
    # turn start and immutable for this turn — pill changes apply to the next
    # turn. Phase 3 (mode) + Phase 4 (settings).
    from app.services.agent_harnesses.approvals import (
        load_session_mode,
        revoke_turn_bypass,
    )
    from app.services.agent_harnesses.base import HarnessContextHint
    from app.services.agent_harnesses.context import build_turn_context
    from app.services.agent_harnesses.session_state import (
        clear_consumed_context_hints,
        hint_preview,
        load_context_hints,
        load_latest_harness_metadata,
    )
    from app.services.agent_harnesses.project import (
        build_workspace_files_memory_hint,
        project_directory_payload,
        resolve_harness_paths,
    )
    from app.services.agent_harnesses.settings import load_session_settings
    from app.services.session_plan_mode import get_session_plan_mode

    async with async_session() as db:
        try:
            harness_paths = await resolve_harness_paths(db, channel_id=channel_id, bot=bot)
        except Exception as exc:
            return "", f"could not resolve harness workspace for bot: {exc}"
        workdir = harness_paths.workdir
        permission_mode = await load_session_mode(db, session_id)
        harness_settings = await load_session_settings(db, session_id)
        harness_model = harness_model_override if harness_model_override is not None else harness_settings.model
        harness_effort = harness_effort_override if harness_effort_override is not None else harness_settings.effort
        context_hints = list(await load_context_hints(db, session_id))
        harness_meta, _last_turn_at = await load_latest_harness_metadata(db, session_id)
        session_row = await db.get(SessionRow, session_id)
        session_plan_mode = get_session_plan_mode(session_row) if session_row is not None else "chat"

    explicit_tool_names, tagged_skill_ids = _parse_harness_explicit_tags(user_message)
    if tagged_skill_ids:
        from sqlalchemy import select
        from app.db.models import Skill

        async with async_session() as db:
            rows = (await db.execute(
                select(Skill.id, Skill.name, Skill.description).where(
                    Skill.id.in_(list(tagged_skill_ids)),
                    Skill.archived_at.is_(None),
                )
            )).all()
        by_id = {row.id: row for row in rows}
        lines = [
            "The user explicitly tagged these Spindrel skills for this harness turn.",
            "Use the bridged get_skill(skill_id=\"...\") tool to fetch full skill bodies progressively; these lines are an index, not the full content.",
        ]
        for skill_id in tagged_skill_ids:
            row = by_id.get(skill_id)
            if row is None:
                lines.append(f"- {skill_id} — not found or archived")
                continue
            desc = f": {row.description}" if row.description else ""
            lines.append(f"- {row.id} — {row.name}{desc}")
        context_hints.append(
            HarnessContextHint(
                kind="tagged_skills",
                source="composer",
                created_at=datetime.now(timezone.utc).isoformat(),
                consume_after_next_turn=True,
                text="\n".join(lines),
            )
        )

    memory_hint = build_workspace_files_memory_hint(bot, harness_paths.bot_workspace_dir)
    if memory_hint is not None:
        context_hints.append(memory_hint)

    emitter = ChannelEventEmitter(
        channel_id=bus_key,
        turn_id=turn_id,
        bot_id=bot.id,
        session_id=session_id,
    )

    ctx = build_turn_context(
        spindrel_session_id=session_id,
        channel_id=channel_id,
        bot_id=bot.id,
        turn_id=turn_id,
        workdir=workdir,
        harness_session_id=prior_session_id,
        permission_mode=permission_mode,
        db_session_factory=async_session,
        model=harness_model,
        effort=harness_effort,
        runtime_settings=harness_settings.runtime_settings,
        context_hints=tuple(context_hints),
        ephemeral_tool_names=explicit_tool_names,
        tagged_skill_ids=tagged_skill_ids,
        session_plan_mode=session_plan_mode,
        harness_metadata=harness_meta or {},
    )

    error_text: str | None = None
    runtime_accepted_turn = False
    try:
        try:
            result = await _start_harness_turn_with_cancel(
                runtime=runtime,
                ctx=ctx,
                prompt=user_message,
                emit=emitter,
                session_id=session_id,
            )
            runtime_accepted_turn = True
        finally:
            # Per-turn bypass grants ("Approve all this turn") are scoped to
            # this turn ONLY. Always revoke — covers success, error, cancel.
            revoke_turn_bypass(turn_id)
    except _HarnessTurnCancelled:
        persisted_tool_calls = emitter.persisted_tool_calls()
        assistant_turn_body = emitter.assistant_turn_body(text="")
        cancelled_assistant_msg: dict = {
            "role": "assistant",
            "content": "",
            "_turn_cancelled": True,
            "_harness": {
                "runtime": bot.harness_runtime,
                "session_id": prior_session_id,
                "interrupted": True,
                "effective_cwd": workdir,
                "effective_cwd_source": harness_paths.source,
                "bot_workspace_dir": harness_paths.bot_workspace_dir,
                "project_dir": project_directory_payload(harness_paths.project_dir),
                "last_hints_sent": [hint_preview(hint) for hint in context_hints],
            },
        }
        if persisted_tool_calls:
            cancelled_assistant_msg["tool_calls"] = persisted_tool_calls
            cancelled_assistant_msg["_tools_used"] = [
                call["function"]["name"] for call in persisted_tool_calls
            ]
        if assistant_turn_body:
            cancelled_assistant_msg["_assistant_turn_body"] = assistant_turn_body
        synthetic_messages: list[dict] = [
            {"role": "user", "content": user_message},
            cancelled_assistant_msg,
        ]
        try:
            async with async_session() as db:
                await persist_turn(
                    db, session_id, bot, synthetic_messages, from_index=0,
                    correlation_id=correlation_id,
                    msg_metadata=msg_metadata,
                    channel_id=channel_id,
                    pre_user_msg_id=pre_user_msg_id,
                    suppress_outbox=suppress_outbox,
                )
        except Exception:
            logger.exception(
                "harness '%s': failed to persist cancelled row for session %s",
                bot.harness_runtime, session_id,
            )
        return "", "cancelled"
    except Exception as exc:
        logger.exception(
            "harness '%s' turn %s failed for bot %s",
            bot.harness_runtime, turn_id, bot.id,
        )
        error_text = _format_turn_exception(exc)
        persisted_tool_calls = emitter.persisted_tool_calls()
        assistant_turn_body = emitter.assistant_turn_body(text="")
        # Persist the failure as the assistant message so the chat shows
        # what went wrong instead of a silent empty turn.
        assistant_msg: dict = {
            "role": "user",
            "content": user_message,
        }
        error_assistant_msg: dict = {
            "role": "assistant",
            "content": _build_turn_failure_message(error_text, ""),
            "_turn_error": True,
            "_turn_error_message": error_text,
            "_harness": {
                "runtime": bot.harness_runtime,
                "session_id": prior_session_id,
                "error": error_text,
                "effective_cwd": workdir,
                "effective_cwd_source": harness_paths.source,
                "bot_workspace_dir": harness_paths.bot_workspace_dir,
                "project_dir": project_directory_payload(harness_paths.project_dir),
                "last_hints_sent": [hint_preview(hint) for hint in context_hints],
            },
        }
        if persisted_tool_calls:
            error_assistant_msg["tool_calls"] = persisted_tool_calls
            error_assistant_msg["_tools_used"] = [
                call["function"]["name"] for call in persisted_tool_calls
            ]
        if assistant_turn_body:
            error_assistant_msg["_assistant_turn_body"] = assistant_turn_body
        synthetic_messages: list[dict] = [assistant_msg, error_assistant_msg]
        try:
            async with async_session() as db:
                await persist_turn(
                    db, session_id, bot, synthetic_messages, from_index=0,
                    correlation_id=correlation_id,
                    msg_metadata=msg_metadata,
                    channel_id=channel_id,
                    pre_user_msg_id=pre_user_msg_id,
                    suppress_outbox=suppress_outbox,
                )
        except Exception:
            logger.exception(
                "harness '%s': failed to persist error row for session %s",
                bot.harness_runtime, session_id,
            )
        return "", error_text

    # Success path: persist the assistant message + update session state.
    from app.services.secret_registry import redact as _redact_secrets

    final_text = _redact_secrets(result.final_text)
    persisted_tool_calls = emitter.persisted_tool_calls()
    assistant_turn_body = emitter.assistant_turn_body(text=final_text)
    if runtime_accepted_turn and context_hints:
        try:
            async with async_session() as db:
                await clear_consumed_context_hints(db, session_id)
        except Exception:
            logger.exception(
                "harness '%s': failed to clear consumed context hints for session %s",
                bot.harness_runtime,
                session_id,
            )
    assistant_msg: dict = {
        "role": "assistant",
        "content": final_text,
        "_harness": {
            "runtime": bot.harness_runtime,
            "session_id": result.session_id,
            "cost_usd": result.cost_usd,
            "usage": result.usage,
            "effective_cwd": workdir,
            "effective_cwd_source": harness_paths.source,
            "bot_workspace_dir": harness_paths.bot_workspace_dir,
            "project_dir": project_directory_payload(harness_paths.project_dir),
            "last_hints_sent": [hint_preview(hint) for hint in context_hints],
            **(result.metadata or {}),
        },
    }
    if persisted_tool_calls:
        assistant_msg["tool_calls"] = persisted_tool_calls
        assistant_msg["_tools_used"] = [
            call["function"]["name"] for call in persisted_tool_calls
        ]
    if assistant_turn_body:
        assistant_msg["_assistant_turn_body"] = assistant_turn_body
    synthetic_messages = [{
        "role": "user",
        "content": user_message,
    }, assistant_msg]
    try:
        async with async_session() as db:
            await persist_turn(
                db, session_id, bot, synthetic_messages, from_index=0,
                correlation_id=correlation_id,
                msg_metadata=msg_metadata,
                channel_id=channel_id,
                pre_user_msg_id=pre_user_msg_id,
                suppress_outbox=suppress_outbox,
            )
    except Exception:
        logger.exception(
            "harness '%s': persist_turn failed for session %s",
            bot.harness_runtime, session_id,
        )
        return final_text, "persist_turn failed"

    # No bookkeeping write-back: resume state lives ON the persisted assistant
    # message (`metadata.harness.session_id`), and per-session cumulative cost
    # is computed from the same metadata when the UI asks for it. The bot row's
    # `harness_session_state` column is intentionally ignored — it was a single
    # global pointer that broke the moment the same harness bot was used in two
    # channels. See `_load_prior_harness_session_id`.

    return final_text, None


async def _start_harness_turn_with_cancel(
    *,
    runtime,
    ctx,
    prompt: str,
    emit: ChannelEventEmitter,
    session_id: uuid.UUID,
):
    """Run a harness turn while honoring the shared session cancel flag."""
    task = asyncio.create_task(
        runtime.start_turn(ctx=ctx, prompt=prompt, emit=emit),
        name=f"harness-turn:{session_id}",
    )
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=0.2)
            if task in done:
                return task.result()
            if session_locks.is_cancel_requested(session_id):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                raise _HarnessTurnCancelled()
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def _load_prior_harness_session_id(session_id: uuid.UUID) -> str | None:
    """Most recent assistant message in this Spindrel session whose metadata
    carries a harness session_id. Returns None on first-turn or sessions
    that have no harness history.

    The query is cheap (indexed by session_id, ordered by created_at desc,
    limited). We scan up to 50 rows so a sequence of `_turn_error` messages
    without `session_id` doesn't mask the real prior id.
    """
    from sqlalchemy import select
    from app.db.models import Message as MessageRow
    from app.services.agent_harnesses.session_state import load_resume_reset_at

    async with async_session() as db:
        reset_at = await load_resume_reset_at(db, session_id)
        rows = (
            await db.execute(
                select(MessageRow.metadata_, MessageRow.created_at)
                .where(MessageRow.session_id == session_id)
                .where(MessageRow.role == "assistant")
                .order_by(MessageRow.created_at.desc())
                .limit(50)
            )
        ).all()
    for meta, created_at in rows:
        if reset_at is not None and created_at is not None:
            try:
                if created_at <= reset_at:
                    continue
            except TypeError:
                if created_at.replace(tzinfo=timezone.utc) <= reset_at:
                    continue
        if not isinstance(meta, dict):
            continue
        harness = meta.get("harness")
        if not isinstance(harness, dict):
            continue
        sid = harness.get("session_id")
        if sid:
            return str(sid)
    return None


async def _persist_harness_failure(
    *,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    bot: BotConfig,
    user_message: str,
    correlation_id: uuid.UUID,
    msg_metadata: dict | None,
    pre_user_msg_id: uuid.UUID | None,
    suppress_outbox: bool,
    error_text: str,
    prior_session_id: str | None,
) -> tuple[str, str]:
    """Persist a turn-error assistant row when the harness can't run at all.

    Mirrors the in-flight error path used when ``runtime.start_turn`` raises;
    factored out so the up-front ``get_runtime`` failure can use the same
    persistence shape and the user actually SEES what went wrong in chat.
    """
    synthetic_messages: list[dict] = [
        {"role": "user", "content": user_message},
        {
            "role": "assistant",
            "content": _build_turn_failure_message(error_text, ""),
            "_turn_error": True,
            "_turn_error_message": error_text,
            "_harness": {
                "runtime": bot.harness_runtime,
                "session_id": prior_session_id,
                "error": error_text,
            },
        },
    ]
    try:
        async with async_session() as db:
            await persist_turn(
                db, session_id, bot, synthetic_messages, from_index=0,
                correlation_id=correlation_id,
                msg_metadata=msg_metadata,
                channel_id=channel_id,
                pre_user_msg_id=pre_user_msg_id,
                suppress_outbox=suppress_outbox,
            )
    except Exception:
        logger.exception(
            "harness '%s': failed to persist pre-flight error row for session %s",
            bot.harness_runtime, session_id,
        )
    logger.error("harness pre-flight failure for bot %s: %s", bot.id, error_text)
    return "", error_text


async def run_turn(
    handle: TurnHandle,
    *,
    bot: BotConfig,
    primary_bot_id: str,
    messages: list[dict],
    user_message: str,
    ctx: BotContext,
    req: ChatRequest,
    user,
    audio_data: str | None,
    audio_format: str | None,
    att_payload: list[dict] | None,
) -> None:
    """Drive a single agent turn to completion in the background.

    Publishes typed ``ChannelEvent``s for the entire lifecycle:

    * ``NEW_MESSAGE`` (user message, pre-persisted)
    * ``TURN_STARTED``
    * ``TURN_STREAM_TOKEN`` / ``TURN_STREAM_TOOL_START`` / ``TURN_STREAM_TOOL_RESULT``
    * ``APPROVAL_REQUESTED`` / ``APPROVAL_RESOLVED``
    * ``NEW_MESSAGE`` (assistant message, via persist_turn)
    * ``TURN_ENDED``

    Releases the session lock unconditionally on the way out.
    """
    channel_id = handle.channel_id
    session_id = handle.session_id
    bus_key = handle.bus_key  # channel_id if present, else session_id (channel-less ephemeral)
    has_channel = channel_id is not None
    turn_id = handle.turn_id
    session_scoped = handle.session_scoped
    correlation_id = turn_id  # turn_id IS the correlation_id — threads through SSE→synthetic→DB for reliable dedup
    response_text = ""
    response_actions: list | None = None
    _intermediate_texts: list[str] = []
    _budget_utilization: float | None = None
    _budget_snapshot: dict | None = None
    was_cancelled = False
    error_text: str | None = None
    pre_user_msg_id: uuid.UUID | None = None
    persisted_turn = False
    from_index: int | None = None
    streamed_text_parts: list[str] = []

    try:
        # Per-task ContextVars — safe because asyncio tasks each see their
        # own ContextVar copy.
        set_agent_context(
            session_id=session_id,
            client_id=req.client_id,
            user_id=getattr(user, "id", None),
            bot_id=bot.id,
            correlation_id=correlation_id,
            channel_id=channel_id,
            memory_cross_channel=None,
            memory_cross_client=None,
            memory_cross_bot=None,
            memory_similarity_threshold=None,
            dispatch_type=None,
            dispatch_config=None,
        )
        # ``current_turn_id`` is set separately because ``set_agent_context``
        # doesn't know the turn_id (it's a per-task value, not a request
        # value). Tool-dispatch reads this when publishing
        # APPROVAL_REQUESTED so the UI can route the approval back to the
        # right in-flight turn slot.
        from app.agent.context import current_turn_id
        current_turn_id.set(turn_id)
        if getattr(user, "id", None) is not None:
            presence.mark_active(user.id)

        # 1. Pre-persist the user message and publish NEW_MESSAGE so the bus
        #    sees the user input before the agent starts emitting tokens.
        _meta = req.msg_metadata or {}
        _pre_id_str = _meta.pop("_pre_user_msg_id", None)
        pre_user_msg_id = await _persist_and_publish_user_message(
            session_id=session_id,
            channel_id=channel_id,
            bus_key=bus_key,
            text=user_message,
            correlation_id=correlation_id,
            metadata=_meta,
            pre_allocated_id=uuid.UUID(_pre_id_str) if _pre_id_str else None,
            suppress_outbox=session_scoped or not has_channel,
        )
        if getattr(user, "id", None) is not None:
            try:
                from app.services.unread import mark_session_read

                async with async_session() as db:
                    await mark_session_read(
                        db,
                        user_id=user.id,
                        session_id=session_id,
                        source="web_send",
                        surface="chat",
                        message_id=pre_user_msg_id,
                    )
                    await db.commit()
            except Exception:
                logger.warning(
                    "turn_worker: failed to mark session %s read for user %s after send",
                    session_id,
                    getattr(user, "id", None),
                    exc_info=True,
                )

        # 2. Publish TURN_STARTED so renderers can post a "thinking..."
        #    placeholder. Tag every lifecycle event with session_id so
        #    channel-scoped scratch/thread subscribers can reject sibling
        #    events carried on the same parent channel bus.
        publish_typed(
            bus_key,
            ChannelEvent(
                channel_id=bus_key,
                kind=ChannelEventKind.TURN_STARTED,
                payload=TurnStartedPayload(
                    bot_id=bot.id,
                    turn_id=turn_id,
                    reason="user_message",
                    session_id=session_id,
                ),
            ),
        )

        # Persistent lifecycle signal for the /state snapshot. Without this,
        # `_snapshot_active_turns` only sees turns that produce a ToolCall or
        # skill_index TraceEvent — a text-only streaming reply is invisible,
        # and any snapshot refetch mid-stream (window focus, reconnect) fires
        # the UI ghost reconciler and kills the live turn slot.
        safe_create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=req.client_id,
            event_type="turn_started",
            data={"bot_id": bot.id},
        ))

        # 2b. Harness-runtime branch — bot delegates to an external agent
        #     harness (Claude Code, Codex, ...) instead of run_stream. The
        #     harness owns the agent loop end-to-end; we own the chat
        #     surface. Skips @-mention fanout, supervisors, and compaction
        #     because the harness has no Spindrel-side context to manage.
        if bot.harness_runtime:
            # Pre-initialize names the finally block references so its
            # ``extra_metadata`` builder doesn't NameError on the harness path.
            _auto_injected_skills = []
            response_text, error_text = await _run_harness_turn(
                channel_id=channel_id,
                bus_key=bus_key,
                session_id=session_id,
                turn_id=turn_id,
                bot=bot,
                user_message=user_message,
                correlation_id=correlation_id,
                msg_metadata=req.msg_metadata,
                pre_user_msg_id=pre_user_msg_id,
                suppress_outbox=session_scoped or not has_channel,
            )
            persisted_turn = error_text is None or error_text == "persist_turn failed"
            # Skip steps 3-8 entirely; finally-block publishes TURN_ENDED.
            return

        # 3. Detect parallel multi-bot @-mentions BEFORE the primary bot
        #    starts so the auto-invoked bots run lock-free in parallel.
        #    Skipped for channel-less sessions — @-mention fanout is a
        #    channel-scoped feature (requires channel membership resolution).
        _user_mentioned: list[tuple[str, dict]] = []
        if user_message and has_channel:
            _user_mentioned = await _detect_member_mentions(
                channel_id, bot.id, user_message, _depth=0,
            )
            if _user_mentioned:
                _user_snap = ctx.raw_snapshot
                _auto_invoked_ids: set[str] = set()
                for _um_bot_id, _um_config in _user_mentioned:
                    _um_task = asyncio.create_task(
                        _run_member_bot_reply(
                            channel_id, session_id, _um_bot_id, _um_config,
                            bot.id, _depth=1,
                            messages_snapshot=_user_snap,
                            turn_id=uuid.uuid4(),
                        )
                    )
                    _background_tasks.add(_um_task)
                    _um_task.add_done_callback(_background_tasks.discard)
                    _auto_invoked_ids.add(_um_bot_id)

                current_invoked_member_bots.set(_auto_invoked_ids)

                _auto_names = []
                for _ai_id, _ in _user_mentioned:
                    try:
                        _ai_bot = get_bot(_ai_id)
                        _auto_names.append(f"{_ai_bot.name} (@{_ai_id})")
                    except Exception:
                        _auto_names.append(f"@{_ai_id}")
                messages.append({
                    "role": "system",
                    "content": (
                        f"The following bots were auto-invoked by the user's @-mentions and are "
                        f"already responding in parallel: {', '.join(_auto_names)}. "
                        f"Do NOT @-mention them again in your response."
                    ),
                })

        # 4. Drive run_stream and map events onto the typed bus.
        from_index = len(messages)
        _effective_model_override = req.model_override or ctx.model_override

        _run_stream_iter = run_stream(
            messages, bot, user_message,
            session_id=session_id,
            client_id=req.client_id,
            audio_data=audio_data,
            audio_format=audio_format,
            attachments=att_payload,
            correlation_id=correlation_id,
            dispatch_type=None,
            dispatch_config=None,
            channel_id=channel_id,
            model_override=_effective_model_override,
            provider_id_override=req.model_provider_id_override or ctx.provider_id_override,
            system_preamble=ctx.system_preamble,
        )
        _auto_injected_skills: list[dict] = []
        _active_skills: list[dict] = []
        _skills_in_context: list[dict] = []
        _llm_retries: int = 0
        _llm_fallback_model: str | None = None
        _vision_fallback: bool = False
        async for event in emit_run_stream_events(
            _run_stream_iter,
            channel_id=bus_key,
            bot_id=bot.id,
            turn_id=turn_id,
            session_id=session_id,
        ):
            etype = event.get("type")

            if etype == "auto_inject":
                _auto_injected_skills.append({
                    "skill_id": event.get("skill_id", ""),
                    "skill_name": event.get("skill_name", ""),
                    "similarity": event.get("similarity", 0.0),
                    "source": event.get("source", ""),
                })
                continue

            if etype == "text_delta":
                delta = event.get("delta", "")
                if delta:
                    streamed_text_parts.append(delta)
                continue

            if etype == "active_skills":
                _skills_in_context = list(event.get("skills", []))
                _active_skills = [
                    s for s in _skills_in_context
                    if isinstance(s, dict) and s.get("source") == "loaded"
                ]
                continue

            if etype == "cancelled":
                was_cancelled = True
                messages.append({"role": "user", "content": "[STOP]"})
                messages.append({"role": "assistant", "content": "[Cancelled by user]"})
                # Surface cancellation on TURN_ENDED so the UI can render a
                # cancelled state instead of an empty graceful turn. The
                # ``error`` field is the only payload slot that distinguishes
                # cancel from a successful empty response.
                error_text = "cancelled"
                break

            if etype == "context_budget":
                _budget_utilization = event.get("utilization")
                _budget_snapshot = dict(event)
                continue

            if etype == "response":
                final_text = event.get("text", "")
                if not (final_text or "").strip() and _intermediate_texts:
                    response_text = "\n\n".join(_intermediate_texts)
                else:
                    response_text = final_text
                response_actions = event.get("client_actions")
                continue

            if etype == "assistant_text":
                _intermediate_texts.append(event.get("text", ""))
                continue

            if etype == "delegation_post":
                # Delegation posts are channel-scoped integration writes —
                # skip entirely for channel-less ephemeral sessions.
                if not has_channel:
                    continue
                try:
                    await _ds.post_child_response(
                        channel_id=channel_id,
                        text=event.get("text", ""),
                        bot_id=event.get("bot_id") or "",
                        reply_in_thread=event.get("reply_in_thread", False),
                    )
                except Exception as exc:
                    # Surface the failure on the bus so the UI / future
                    # renderers can render an error chip. The legacy path
                    # would have surfaced this via the dispatcher mirror;
                    # the typed bus needs the explicit publish.
                    logger.exception(
                        "turn_worker: delegation_post failed for bot %s",
                        event.get("bot_id"),
                    )
                    publish_typed(
                        bus_key,
                        ChannelEvent(
                            channel_id=bus_key,
                            kind=ChannelEventKind.TURN_STREAM_TOOL_RESULT,
                            payload=TurnStreamToolResultPayload(
                                bot_id=bot.id,
                                turn_id=turn_id,
                                tool_name="delegation_post",
                                result_summary=(
                                    f"delegation_post failed for "
                                    f"{event.get('bot_id') or 'unknown'}: "
                                    f"{type(exc).__name__}: {str(exc)[:300]}"
                                ),
                                is_error=True,
                            ),
                        ),
                    )
                continue

            if etype == "llm_retry":
                _llm_retries += 1
                if event.get("reason") == "vision_not_supported":
                    _vision_fallback = True
                continue

            if etype == "llm_fallback":
                _llm_fallback_model = event.get("to_model")
                continue

            if etype == "llm_cooldown_skip":
                _llm_fallback_model = event.get("using")
                continue

            # Anything else (transcript, thinking_content, warning, fallback,
            # context_pruning, rate_limit_wait) — forwarded but no caller-side
            # action needed.

        from app.agent.context import current_skills_in_context as _current_skills_in_context
        _runtime_skills_in_context = list(_current_skills_in_context.get() or [])
        if _runtime_skills_in_context:
            _skills_in_context = _runtime_skills_in_context
            _active_skills = [
                s for s in _skills_in_context
                if isinstance(s, dict) and s.get("source") == "loaded"
            ]

        # 4b. Tag the last assistant message with auto-injected skill info
        #     so persist_turn can carry it into the DB row's metadata.
        if _auto_injected_skills:
            for _m in reversed(messages[from_index:]):
                if _m.get("role") == "assistant":
                    _m["_auto_injected_skills"] = _auto_injected_skills
                    break

        # 4b.2. Tag the last assistant message with active skills (still in
        #       context from prior get_skill calls) for the UI skill orb.
        if _skills_in_context or _active_skills:
            for _m in reversed(messages[from_index:]):
                if _m.get("role") == "assistant":
                    _m["_active_skills"] = _active_skills
                    _m["_skills_in_context"] = _skills_in_context or _active_skills
                    break

        # 4c. Tag the last assistant message with LLM retry/fallback info
        #     so persist_turn can carry it into the DB row's metadata.
        if _llm_retries > 0 or _llm_fallback_model or _vision_fallback:
            _llm_info: dict = {}
            if _llm_retries > 0:
                _llm_info["retries"] = _llm_retries
            if _llm_fallback_model:
                _llm_info["fallback_model"] = _llm_fallback_model
            if _vision_fallback:
                _llm_info["vision_fallback"] = True
            for _m in reversed(messages[from_index:]):
                if _m.get("role") == "assistant":
                    _m["_llm_status"] = _llm_info
                    break

        # 5. Persist the turn (DB write + outbox enqueue + bus publish).
        #    Runs unconditionally — cancelled turns must persist the [STOP] /
        #    [Cancelled by user] markers that the cancellation branch above
        #    appended to ``messages``, so the conversation history reflects
        #    the cancellation. The legacy event_generator (deleted in Phase E)
        #    called persist_turn unconditionally for the same reason.
        try:
            async with async_session() as db:
                await persist_turn(
                    db, session_id, bot, messages, from_index,
                    correlation_id=correlation_id,
                    msg_metadata=req.msg_metadata,
                    channel_id=channel_id,
                    pre_user_msg_id=pre_user_msg_id,
                    suppress_outbox=session_scoped or not has_channel,
                )
                persisted_turn = True
        except Exception:
            logger.exception(
                "turn_worker: persist_turn failed for session %s — messages will be lost",
                session_id,
            )
            error_text = "persist_turn failed"

        # 6. Run deterministic internal supervisors after persistence and
        #    before TURN_ENDED so state changes reach the UI with the final
        #    turn signal.
        if persisted_turn:
            await run_turn_supervisors(TurnEndContext(
                session_id=session_id,
                channel_id=channel_id,
                bot_id=bot.id,
                turn_id=turn_id,
                correlation_id=correlation_id,
                result=response_text or None,
                error=error_text,
                client_actions=list(response_actions or []),
            ))

        # 7. Trigger compaction in the background.
        maybe_compact(
            session_id, bot, messages,
            correlation_id=correlation_id,
            budget_utilization=_budget_utilization,
            budget_snapshot=_budget_snapshot,
        )

        # 8. Bot-to-bot @-mention chain: trigger member bot replies for
        #    bots the primary bot mentioned in its response.
        #    Channel-less ephemeral sessions skip — @-mention fanout requires
        #    channel membership resolution.
        if not was_cancelled and response_text and has_channel:
            _already_invoked = set(current_invoked_member_bots.get() or ())
            if _user_mentioned:
                _already_invoked.update(bid for bid, _ in _user_mentioned)
            _messages_snapshot = copy.deepcopy(ctx.raw_snapshot) if ctx.raw_snapshot else []
            _messages_snapshot.append({
                "role": "assistant",
                "content": response_text,
                "_metadata": {
                    "sender_id": f"bot:{bot.id}",
                    "sender_display_name": bot.name,
                },
            })
            try:
                await _trigger_member_bot_replies(
                    channel_id, session_id, bot.id, response_text,
                    _depth=1,
                    messages_snapshot=_messages_snapshot,
                    already_invoked=_already_invoked,
                )
            except Exception:
                logger.warning(
                    "turn_worker: member-bot fanout failed for channel %s",
                    channel_id, exc_info=True,
                )

    except Exception as exc:
        logger.exception(
            "turn_worker: turn %s failed for session %s",
            turn_id, session_id,
        )
        error_text = _format_turn_exception(exc)
        if from_index is not None and not persisted_turn:
            messages.append({
                "role": "assistant",
                "content": _build_turn_failure_message(
                    error_text,
                    "".join(streamed_text_parts),
                ),
                "_turn_error": True,
                "_turn_error_message": error_text,
            })
            try:
                async with async_session() as db:
                    await persist_turn(
                        db, session_id, bot, messages, from_index,
                        correlation_id=correlation_id,
                        msg_metadata=req.msg_metadata,
                        channel_id=channel_id,
                        pre_user_msg_id=pre_user_msg_id,
                        suppress_outbox=session_scoped or not has_channel,
                    )
                    persisted_turn = True
            except Exception:
                logger.exception(
                    "turn_worker: failed to persist turn error row for session %s",
                    session_id,
                )
    finally:
        # 9. Always publish TURN_ENDED. Subscribers (renderers + UI) rely
        #    on it to finalize their per-turn state.
        try:
            publish_typed(
                bus_key,
                ChannelEvent(
                    channel_id=bus_key,
                    kind=ChannelEventKind.TURN_ENDED,
                    payload=TurnEndedPayload(
                        bot_id=bot.id,
                        turn_id=turn_id,
                        result=response_text or None,
                        # Always surface error_text. The legacy guard
                        # `if not response_text else None` swallowed
                        # persist_turn / fanout failures whenever the
                        # agent had already produced a response, so the
                        # UI saw a green turn while the messages were
                        # actually lost. Renderers + UI handle result
                        # and error being independent.
                        error=error_text or None,
                        client_actions=list(response_actions or []),
                        session_id=session_id,
                        extra_metadata=(
                            {"auto_injected_skills": _auto_injected_skills}
                            if _auto_injected_skills else {}
                        ),
                    ),
                ),
            )
        except Exception:
            logger.warning(
                "turn_worker: failed to publish TURN_ENDED for turn %s",
                turn_id, exc_info=True,
            )

        # 10. Always release the session lock so the next turn can run.
        session_locks.release(session_id)


async def _persist_and_publish_user_message(
    *,
    session_id: uuid.UUID,
    channel_id: uuid.UUID | None,
    bus_key: uuid.UUID,
    text: str,
    correlation_id: uuid.UUID,
    metadata: dict,
    pre_allocated_id: uuid.UUID | None = None,
    suppress_outbox: bool = False,
) -> uuid.UUID | None:
    """Insert the user message row and publish a NEW_MESSAGE event.

    Returns the row id so ``persist_turn`` can avoid double-inserting it.
    A failure here is logged and swallowed — persist_turn will create a
    fresh row and the bus subscriber sees a (delayed) NEW_MESSAGE later.

    If *pre_allocated_id* is set (e.g. because attachments were already
    linked to this ID), the message row will use that UUID instead of
    auto-generating one.
    """
    try:
        async with async_session() as db:
            row: MessageModel | None = None
            if pre_allocated_id:
                # The POST handler pre-persists a stub row so attachment FKs
                # resolve before the worker runs. Detect that row and update
                # it in place with the worker-only fields (correlation_id,
                # final metadata) instead of re-inserting.
                row = await db.get(MessageModel, pre_allocated_id)
                if row is not None:
                    row.content = text
                    row.correlation_id = correlation_id
                    row.metadata_ = metadata
                    await db.commit()
                    await db.refresh(row)
            if row is None:
                kw: dict = dict(
                    session_id=session_id,
                    role="user",
                    content=text,
                    correlation_id=correlation_id,
                    metadata_=metadata,
                    created_at=datetime.now(timezone.utc),
                )
                if pre_allocated_id:
                    kw["id"] = pre_allocated_id
                row = MessageModel(**kw)
                db.add(row)
                await db.commit()
                await db.refresh(row)

            domain_msg = DomainMessage(
                id=row.id,
                session_id=session_id,
                role="user",
                content=text,
                created_at=row.created_at,
                actor=ActorRef.user(
                    metadata.get("sender_id", "user"),
                    display_name=metadata.get("sender_display_name"),
                ),
                metadata=dict(metadata),
                correlation_id=correlation_id,
                channel_id=channel_id if channel_id is not None else bus_key,
            )
            # NEW_MESSAGE is outbox-durable: enqueue an outbox row so the
            # drainer is the single delivery path to renderers, and call
            # publish_typed so SSE subscribers (web UI) still see the
            # event live. The Slack renderer's echo filter then catches
            # this on the outbox path the same way it would on the bus
            # path.
            if not suppress_outbox and channel_id is not None:
                from app.services.outbox_publish import enqueue_new_message_for_channel
                await enqueue_new_message_for_channel(channel_id, domain_msg)
            elif channel_id is None:
                # Thread sub-sessions: walk up to the parent channel and
                # fan the user message through its integrations with
                # thread-ref overrides so Slack/etc. see it in the thread.
                # Ephemeral / pipeline follow-ups stay suppressed — their
                # surface is the modal, not an external platform. Helper
                # no-ops for non-thread sessions so this is safe as a
                # channel-less catch-all.
                from app.services.outbox_publish import (
                    enqueue_new_message_for_thread_session,
                )
                await enqueue_new_message_for_thread_session(session_id, domain_msg)
            publish_typed(
                bus_key,
                ChannelEvent(
                    channel_id=bus_key,
                    kind=ChannelEventKind.NEW_MESSAGE,
                    payload=MessagePayload(message=domain_msg),
                ),
            )
            return row.id
    except Exception:
        logger.warning(
            "turn_worker: failed to pre-persist user message for session %s",
            session_id, exc_info=True,
        )
        return None
