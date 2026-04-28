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
import json
import logging
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
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
        tool_envelopes = emitter.tool_envelopes()
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
            if tool_envelopes:
                cancelled_assistant_msg["_tool_envelopes"] = tool_envelopes
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
        tool_envelopes = emitter.tool_envelopes()
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
            if tool_envelopes:
                error_assistant_msg["_tool_envelopes"] = tool_envelopes
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
    tool_envelopes = emitter.tool_envelopes()
    assistant_turn_body = emitter.assistant_turn_body(text=final_text)
    await _mirror_harness_native_plan_state(
        session_id=session_id,
        runtime_name=bot.harness_runtime,
        result_metadata=result.metadata or {},
        persisted_tool_calls=persisted_tool_calls,
    )
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
        if tool_envelopes:
            assistant_msg["_tool_envelopes"] = tool_envelopes
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

    try:
        async with async_session() as db:
            from app.services.agent_harnesses.session_state import (
                maybe_run_harness_auto_compaction,
            )

            await maybe_run_harness_auto_compaction(
                db,
                session_id,
                runtime=bot.harness_runtime,
                usage=result.usage if isinstance(result.usage, dict) else None,
            )
    except Exception:
        logger.exception(
            "harness '%s': auto-compaction check failed for session %s",
            bot.harness_runtime,
            session_id,
        )

    # No bookkeeping write-back: resume state lives ON the persisted assistant
    # message (`metadata.harness.session_id`), and per-session cumulative cost
    # is computed from the same metadata when the UI asks for it. The bot row's
    # `harness_session_state` column is intentionally ignored — it was a single
    # global pointer that broke the moment the same harness bot was used in two
    # channels. See `_load_prior_harness_session_id`.

    return final_text, None


async def _mirror_harness_native_plan_state(
    *,
    session_id: uuid.UUID,
    runtime_name: str | None,
    result_metadata: dict,
    persisted_tool_calls: list[dict],
) -> None:
    """Reflect runtime-native plan signals into Spindrel session plan state."""
    if not result_metadata and not persisted_tool_calls:
        return
    try:
        async with async_session() as db:
            session = await db.get(SessionRow, session_id)
            if session is None:
                return
            changed = False
            if runtime_name == "codex" and _metadata_has_codex_plan_signal(result_metadata):
                from app.services.session_plan_mode import (
                    enter_session_plan_mode,
                    get_session_plan_mode,
                    publish_session_plan_event,
                    update_planning_state,
                )

                if get_session_plan_mode(session) == "chat":
                    enter_session_plan_mode(session)
                    changed = True
                evidence = _codex_plan_evidence(result_metadata)
                if evidence:
                    update_planning_state(
                        session,
                        evidence=evidence,
                        reason="codex_native_plan",
                    )
                    changed = True
                if changed:
                    await db.commit()
                    await db.refresh(session)
                    publish_session_plan_event(session, "codex_native_plan")
                return

            if runtime_name == "claude-code" and _tool_calls_include_exit_plan_mode(persisted_tool_calls):
                from app.services.session_plan_mode import (
                    exit_session_plan_mode,
                    get_session_plan_mode,
                    publish_session_plan_event,
                )

                if get_session_plan_mode(session) != "chat":
                    exit_session_plan_mode(session)
                    await db.commit()
                    await db.refresh(session)
                    publish_session_plan_event(session, "claude_exit_plan_mode")
    except Exception:
        logger.exception("harness native plan mirroring failed for session %s", session_id)


def _metadata_has_codex_plan_signal(metadata: dict) -> bool:
    return any(
        key in metadata
        for key in ("codex_native_plan", "codex_native_plan_text", "codex_native_plan_delta")
    )


def _codex_plan_evidence(metadata: dict) -> list[str]:
    text = metadata.get("codex_native_plan_text")
    if isinstance(text, str) and text.strip():
        return [f"Codex native plan: {text.strip()[:2000]}"]
    delta = metadata.get("codex_native_plan_delta")
    if isinstance(delta, str) and delta.strip():
        return [f"Codex native plan draft: {delta.strip()[:2000]}"]
    plan = metadata.get("codex_native_plan")
    if isinstance(plan, list):
        steps = []
        for item in plan[:8]:
            if isinstance(item, dict):
                step = str(item.get("step") or item.get("text") or "").strip()
                status = str(item.get("status") or "").strip()
                if step:
                    steps.append(f"{status}: {step}" if status else step)
        if steps:
            return ["Codex native plan steps: " + "; ".join(steps)]
    if isinstance(plan, dict):
        return [f"Codex native plan updated: {json.dumps(plan, sort_keys=True)[:2000]}"]
    return []


def _tool_calls_include_exit_plan_mode(tool_calls: list[dict]) -> bool:
    for call in tool_calls:
        fn = call.get("function") if isinstance(call, dict) else None
        if isinstance(fn, dict) and fn.get("name") == "ExitPlanMode":
            return True
    return False


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


@dataclass(frozen=True)
class _TurnScope:
    session_id: uuid.UUID
    channel_id: uuid.UUID | None
    bus_key: uuid.UUID
    turn_id: uuid.UUID
    session_scoped: bool
    correlation_id: uuid.UUID

    @classmethod
    def from_handle(cls, handle: TurnHandle) -> "_TurnScope":
        return cls(
            session_id=handle.session_id,
            channel_id=handle.channel_id,
            bus_key=handle.bus_key,
            turn_id=handle.turn_id,
            session_scoped=handle.session_scoped,
            correlation_id=handle.turn_id,
        )

    @property
    def has_channel(self) -> bool:
        return self.channel_id is not None

    @property
    def suppress_outbox(self) -> bool:
        return self.session_scoped or not self.has_channel


@dataclass
class _TurnRunState:
    response_text: str = ""
    response_actions: list | None = None
    intermediate_texts: list[str] = field(default_factory=list)
    budget_utilization: float | None = None
    budget_snapshot: dict | None = None
    was_cancelled: bool = False
    error_text: str | None = None
    pre_user_msg_id: uuid.UUID | None = None
    persisted_turn: bool = False
    from_index: int | None = None
    streamed_text_parts: list[str] = field(default_factory=list)
    auto_injected_skills: list[dict] = field(default_factory=list)
    active_skills: list[dict] = field(default_factory=list)
    skills_in_context: list[dict] = field(default_factory=list)
    llm_retries: int = 0
    llm_fallback_model: str | None = None
    vision_fallback: bool = False
    user_mentioned: list[tuple[str, dict]] = field(default_factory=list)


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
    scope = _TurnScope.from_handle(handle)
    state = _TurnRunState()

    try:
        _setup_turn_context(scope, bot=bot, req=req, user=user)
        await _start_turn_lifecycle(
            scope,
            state,
            bot=bot,
            req=req,
            user=user,
            user_message=user_message,
        )
        if await _run_harness_branch_if_needed(
            scope,
            state,
            bot=bot,
            req=req,
            user_message=user_message,
        ):
            return

        await _prepare_user_mention_fanout(
            scope,
            state,
            bot=bot,
            messages=messages,
            user_message=user_message,
            ctx=ctx,
        )
        await _drive_normal_turn_stream(
            scope,
            state,
            bot=bot,
            messages=messages,
            user_message=user_message,
            ctx=ctx,
            req=req,
            audio_data=audio_data,
            audio_format=audio_format,
            att_payload=att_payload,
        )
        _tag_assistant_metadata(messages, state)
        await _persist_completed_turn(scope, state, bot=bot, messages=messages, req=req)
        await _run_after_persist_side_effects(scope, state, bot=bot, messages=messages, ctx=ctx)

    except Exception as exc:
        logger.exception(
            "turn_worker: turn %s failed for session %s",
            scope.turn_id, scope.session_id,
        )
        state.error_text = _format_turn_exception(exc)
        await _persist_error_turn_if_possible(scope, state, bot=bot, messages=messages, req=req)
    finally:
        _publish_turn_ended(scope, state, bot)
        session_locks.release(scope.session_id)


def _setup_turn_context(
    scope: _TurnScope,
    *,
    bot: BotConfig,
    req: ChatRequest,
    user,
) -> None:
    # Per-task ContextVars are safe here because asyncio tasks each get their
    # own ContextVar copy.
    set_agent_context(
        session_id=scope.session_id,
        client_id=req.client_id,
        user_id=getattr(user, "id", None),
        bot_id=bot.id,
        correlation_id=scope.correlation_id,
        channel_id=scope.channel_id,
        memory_cross_channel=None,
        memory_cross_client=None,
        memory_cross_bot=None,
        memory_similarity_threshold=None,
        dispatch_type=None,
        dispatch_config=None,
    )
    # ``set_agent_context`` does not know the per-task turn id. Tool dispatch
    # reads this when publishing approval events for the live turn slot.
    from app.agent.context import current_turn_id

    current_turn_id.set(scope.turn_id)
    if getattr(user, "id", None) is not None:
        presence.mark_active(user.id)


async def _start_turn_lifecycle(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    req: ChatRequest,
    user,
    user_message: str,
) -> None:
    state.pre_user_msg_id = await _pre_persist_user_message(
        scope,
        req=req,
        user_message=user_message,
    )
    await _mark_sender_session_read(
        scope,
        user=user,
        message_id=state.pre_user_msg_id,
    )
    _publish_turn_started(scope, bot)
    _record_turn_started_trace(scope, bot=bot, req=req)


async def _pre_persist_user_message(
    scope: _TurnScope,
    *,
    req: ChatRequest,
    user_message: str,
) -> uuid.UUID | None:
    # Preserve existing behavior: the private preallocated message id is
    # consumed from request metadata before later persist_turn receives it.
    metadata = req.msg_metadata or {}
    pre_id_str = metadata.pop("_pre_user_msg_id", None)
    return await _persist_and_publish_user_message(
        session_id=scope.session_id,
        channel_id=scope.channel_id,
        bus_key=scope.bus_key,
        text=user_message,
        correlation_id=scope.correlation_id,
        metadata=metadata,
        pre_allocated_id=uuid.UUID(pre_id_str) if pre_id_str else None,
        suppress_outbox=scope.suppress_outbox,
    )


async def _mark_sender_session_read(
    scope: _TurnScope,
    *,
    user,
    message_id: uuid.UUID | None,
) -> None:
    if getattr(user, "id", None) is None:
        return
    try:
        from app.services.unread import mark_session_read

        async with async_session() as db:
            await mark_session_read(
                db,
                user_id=user.id,
                session_id=scope.session_id,
                source="web_send",
                surface="chat",
                message_id=message_id,
            )
            await db.commit()
    except Exception:
        logger.warning(
            "turn_worker: failed to mark session %s read for user %s after send",
            scope.session_id,
            getattr(user, "id", None),
            exc_info=True,
        )


def _publish_turn_started(scope: _TurnScope, bot: BotConfig) -> None:
    publish_typed(
        scope.bus_key,
        ChannelEvent(
            channel_id=scope.bus_key,
            kind=ChannelEventKind.TURN_STARTED,
            payload=TurnStartedPayload(
                bot_id=bot.id,
                turn_id=scope.turn_id,
                reason="user_message",
                session_id=scope.session_id,
            ),
        ),
    )


def _record_turn_started_trace(
    scope: _TurnScope,
    *,
    bot: BotConfig,
    req: ChatRequest,
) -> None:
    # Persistent lifecycle signal for /state snapshots. Without it, text-only
    # streaming replies are invisible to `_snapshot_active_turns`.
    safe_create_task(_record_trace_event(
        correlation_id=scope.correlation_id,
        session_id=scope.session_id,
        bot_id=bot.id,
        client_id=req.client_id,
        event_type="turn_started",
        data={"bot_id": bot.id},
    ))


async def _run_harness_branch_if_needed(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    req: ChatRequest,
    user_message: str,
) -> bool:
    if not bot.harness_runtime:
        return False

    state.response_text, state.error_text = await _run_harness_turn(
        channel_id=scope.channel_id,
        bus_key=scope.bus_key,
        session_id=scope.session_id,
        turn_id=scope.turn_id,
        bot=bot,
        user_message=user_message,
        correlation_id=scope.correlation_id,
        msg_metadata=req.msg_metadata,
        pre_user_msg_id=state.pre_user_msg_id,
        suppress_outbox=scope.suppress_outbox,
    )
    state.persisted_turn = (
        state.error_text is None or state.error_text == "persist_turn failed"
    )
    return True


async def _prepare_user_mention_fanout(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    messages: list[dict],
    user_message: str,
    ctx: BotContext,
) -> None:
    # User @-mention fanout is channel-scoped; channel-less sessions have no
    # membership set to resolve.
    if not user_message or not scope.has_channel:
        return
    state.user_mentioned = await _detect_member_mentions(
        scope.channel_id, bot.id, user_message, _depth=0,
    )
    if not state.user_mentioned:
        return

    auto_invoked_ids: set[str] = set()
    for member_bot_id, member_config in state.user_mentioned:
        task = asyncio.create_task(
            _run_member_bot_reply(
                scope.channel_id,
                scope.session_id,
                member_bot_id,
                member_config,
                bot.id,
                _depth=1,
                messages_snapshot=ctx.raw_snapshot,
                turn_id=uuid.uuid4(),
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        auto_invoked_ids.add(member_bot_id)

    current_invoked_member_bots.set(auto_invoked_ids)
    auto_names = []
    for member_bot_id, _ in state.user_mentioned:
        try:
            mentioned_bot = get_bot(member_bot_id)
            auto_names.append(f"{mentioned_bot.name} (@{member_bot_id})")
        except Exception:
            auto_names.append(f"@{member_bot_id}")
    messages.append({
        "role": "system",
        "content": (
            f"The following bots were auto-invoked by the user's @-mentions and are "
            f"already responding in parallel: {', '.join(auto_names)}. "
            f"Do NOT @-mention them again in your response."
        ),
    })


async def _drive_normal_turn_stream(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    messages: list[dict],
    user_message: str,
    ctx: BotContext,
    req: ChatRequest,
    audio_data: str | None,
    audio_format: str | None,
    att_payload: list[dict] | None,
) -> None:
    state.from_index = len(messages)
    run_stream_iter = run_stream(
        messages,
        bot,
        user_message,
        session_id=scope.session_id,
        client_id=req.client_id,
        audio_data=audio_data,
        audio_format=audio_format,
        attachments=att_payload,
        correlation_id=scope.correlation_id,
        dispatch_type=None,
        dispatch_config=None,
        channel_id=scope.channel_id,
        model_override=req.model_override or ctx.model_override,
        provider_id_override=req.model_provider_id_override or ctx.provider_id_override,
        system_preamble=ctx.system_preamble,
    )
    async for event in emit_run_stream_events(
        run_stream_iter,
        channel_id=scope.bus_key,
        bot_id=bot.id,
        turn_id=scope.turn_id,
        session_id=scope.session_id,
    ):
        if await _handle_run_stream_event(scope, state, bot=bot, messages=messages, event=event):
            break

    _refresh_runtime_skills_in_context(state)


async def _handle_run_stream_event(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    messages: list[dict],
    event: dict,
) -> bool:
    etype = event.get("type")

    if etype == "auto_inject":
        state.auto_injected_skills.append({
            "skill_id": event.get("skill_id", ""),
            "skill_name": event.get("skill_name", ""),
            "similarity": event.get("similarity", 0.0),
            "source": event.get("source", ""),
        })
        return False

    if etype == "text_delta":
        delta = event.get("delta", "")
        if delta:
            state.streamed_text_parts.append(delta)
        return False

    if etype == "active_skills":
        state.skills_in_context = list(event.get("skills", []))
        state.active_skills = _loaded_skills(state.skills_in_context)
        return False

    if etype == "cancelled":
        state.was_cancelled = True
        messages.append({"role": "user", "content": "[STOP]"})
        messages.append({"role": "assistant", "content": "[Cancelled by user]"})
        state.error_text = "cancelled"
        return True

    if etype == "context_budget":
        state.budget_utilization = event.get("utilization")
        state.budget_snapshot = dict(event)
        return False

    if etype == "response":
        final_text = event.get("text", "")
        if not (final_text or "").strip() and state.intermediate_texts:
            state.response_text = "\n\n".join(state.intermediate_texts)
        else:
            state.response_text = final_text
        state.response_actions = event.get("client_actions")
        return False

    if etype == "assistant_text":
        state.intermediate_texts.append(event.get("text", ""))
        return False

    if etype == "delegation_post":
        await _handle_delegation_post(scope, bot=bot, event=event)
        return False

    if etype == "llm_retry":
        state.llm_retries += 1
        if event.get("reason") == "vision_not_supported":
            state.vision_fallback = True
        return False

    if etype == "llm_fallback":
        state.llm_fallback_model = event.get("to_model")
        return False

    if etype == "llm_cooldown_skip":
        state.llm_fallback_model = event.get("using")
        return False

    return False


async def _handle_delegation_post(
    scope: _TurnScope,
    *,
    bot: BotConfig,
    event: dict,
) -> None:
    if not scope.has_channel:
        return
    try:
        await _ds.post_child_response(
            channel_id=scope.channel_id,
            text=event.get("text", ""),
            bot_id=event.get("bot_id") or "",
            reply_in_thread=event.get("reply_in_thread", False),
        )
    except Exception as exc:
        logger.exception(
            "turn_worker: delegation_post failed for bot %s",
            event.get("bot_id"),
        )
        publish_typed(
            scope.bus_key,
            ChannelEvent(
                channel_id=scope.bus_key,
                kind=ChannelEventKind.TURN_STREAM_TOOL_RESULT,
                payload=TurnStreamToolResultPayload(
                    bot_id=bot.id,
                    turn_id=scope.turn_id,
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


def _refresh_runtime_skills_in_context(state: _TurnRunState) -> None:
    from app.agent.context import current_skills_in_context

    runtime_skills = list(current_skills_in_context.get() or [])
    if runtime_skills:
        state.skills_in_context = runtime_skills
        state.active_skills = _loaded_skills(runtime_skills)


def _loaded_skills(skills: list[dict]) -> list[dict]:
    return [
        skill for skill in skills
        if isinstance(skill, dict) and skill.get("source") == "loaded"
    ]


def _tag_assistant_metadata(messages: list[dict], state: _TurnRunState) -> None:
    if state.from_index is None:
        return
    assistant = _last_assistant_message(messages[state.from_index:])
    if assistant is None:
        return

    if state.auto_injected_skills:
        assistant["_auto_injected_skills"] = state.auto_injected_skills
    if state.skills_in_context or state.active_skills:
        assistant["_active_skills"] = state.active_skills
        assistant["_skills_in_context"] = state.skills_in_context or state.active_skills

    llm_info = _llm_status_metadata(state)
    if llm_info:
        assistant["_llm_status"] = llm_info


def _last_assistant_message(messages: list[dict]) -> dict | None:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return message
    return None


def _llm_status_metadata(state: _TurnRunState) -> dict:
    llm_info: dict = {}
    if state.llm_retries > 0:
        llm_info["retries"] = state.llm_retries
    if state.llm_fallback_model:
        llm_info["fallback_model"] = state.llm_fallback_model
    if state.vision_fallback:
        llm_info["vision_fallback"] = True
    return llm_info


async def _persist_completed_turn(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    messages: list[dict],
    req: ChatRequest,
) -> None:
    try:
        async with async_session() as db:
            await persist_turn(
                db,
                scope.session_id,
                bot,
                messages,
                state.from_index,
                correlation_id=scope.correlation_id,
                msg_metadata=req.msg_metadata,
                channel_id=scope.channel_id,
                pre_user_msg_id=state.pre_user_msg_id,
                suppress_outbox=scope.suppress_outbox,
            )
            state.persisted_turn = True
    except Exception:
        logger.exception(
            "turn_worker: persist_turn failed for session %s — messages will be lost",
            scope.session_id,
        )
        state.error_text = "persist_turn failed"


async def _run_after_persist_side_effects(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    messages: list[dict],
    ctx: BotContext,
) -> None:
    if state.persisted_turn:
        await run_turn_supervisors(TurnEndContext(
            session_id=scope.session_id,
            channel_id=scope.channel_id,
            bot_id=bot.id,
            turn_id=scope.turn_id,
            correlation_id=scope.correlation_id,
            result=state.response_text or None,
            error=state.error_text,
            client_actions=list(state.response_actions or []),
        ))

    maybe_compact(
        scope.session_id,
        bot,
        messages,
        correlation_id=scope.correlation_id,
        budget_utilization=state.budget_utilization,
        budget_snapshot=state.budget_snapshot,
    )
    await _trigger_assistant_mention_fanout(scope, state, bot=bot, ctx=ctx)


async def _trigger_assistant_mention_fanout(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    ctx: BotContext,
) -> None:
    if state.was_cancelled or not state.response_text or not scope.has_channel:
        return

    already_invoked = set(current_invoked_member_bots.get() or ())
    if state.user_mentioned:
        already_invoked.update(bot_id for bot_id, _ in state.user_mentioned)
    messages_snapshot = copy.deepcopy(ctx.raw_snapshot) if ctx.raw_snapshot else []
    messages_snapshot.append({
        "role": "assistant",
        "content": state.response_text,
        "_metadata": {
            "sender_id": f"bot:{bot.id}",
            "sender_display_name": bot.name,
        },
    })
    try:
        await _trigger_member_bot_replies(
            scope.channel_id,
            scope.session_id,
            bot.id,
            state.response_text,
            _depth=1,
            messages_snapshot=messages_snapshot,
            already_invoked=already_invoked,
        )
    except Exception:
        logger.warning(
            "turn_worker: member-bot fanout failed for channel %s",
            scope.channel_id,
            exc_info=True,
        )


async def _persist_error_turn_if_possible(
    scope: _TurnScope,
    state: _TurnRunState,
    *,
    bot: BotConfig,
    messages: list[dict],
    req: ChatRequest,
) -> None:
    if state.from_index is None or state.persisted_turn:
        return
    messages.append({
        "role": "assistant",
        "content": _build_turn_failure_message(
            state.error_text or "unknown error",
            "".join(state.streamed_text_parts),
        ),
        "_turn_error": True,
        "_turn_error_message": state.error_text,
    })
    try:
        async with async_session() as db:
            await persist_turn(
                db,
                scope.session_id,
                bot,
                messages,
                state.from_index,
                correlation_id=scope.correlation_id,
                msg_metadata=req.msg_metadata,
                channel_id=scope.channel_id,
                pre_user_msg_id=state.pre_user_msg_id,
                suppress_outbox=scope.suppress_outbox,
            )
            state.persisted_turn = True
    except Exception:
        logger.exception(
            "turn_worker: failed to persist turn error row for session %s",
            scope.session_id,
        )


def _publish_turn_ended(scope: _TurnScope, state: _TurnRunState, bot: BotConfig) -> None:
    try:
        publish_typed(
            scope.bus_key,
            ChannelEvent(
                channel_id=scope.bus_key,
                kind=ChannelEventKind.TURN_ENDED,
                payload=TurnEndedPayload(
                    bot_id=bot.id,
                    turn_id=scope.turn_id,
                    result=state.response_text or None,
                    # Result and error are independent: persistence/fanout can
                    # fail after useful text has already streamed.
                    error=state.error_text or None,
                    client_actions=list(state.response_actions or []),
                    session_id=scope.session_id,
                    extra_metadata=(
                        {"auto_injected_skills": state.auto_injected_skills}
                        if state.auto_injected_skills else {}
                    ),
                ),
            ),
        )
    except Exception:
        logger.warning(
            "turn_worker: failed to publish TURN_ENDED for turn %s",
            scope.turn_id,
            exc_info=True,
        )


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
