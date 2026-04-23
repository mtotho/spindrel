"""Backend-owned slash command registry and execution helpers.

The command contract is client-agnostic: each command returns a typed result
payload plus plain-text fallback so web, Slack, and CLI can all render the
same semantic output in their own surfaces.
"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Session, Task
from app.services import session_locks
from app.services.context_breakdown import compute_context_breakdown, fetch_latest_context_budget
from app.services.session_plan_mode import (
    enter_session_plan_mode,
    exit_session_plan_mode,
    get_session_plan_mode,
    load_session_plan,
    resume_session_plan_mode,
)


class ContextSummaryBudget(BaseModel):
    utilization: float | None = None
    consumed_tokens: int | None = None
    total_tokens: int | None = None
    gross_prompt_tokens: int | None = None
    current_prompt_tokens: int | None = None
    cached_prompt_tokens: int | None = None
    completion_tokens: int | None = None
    context_profile: str | None = None
    context_origin: str | None = None
    live_history_turns: int | None = None
    source: str | None = None


class ContextSummaryCategory(BaseModel):
    key: str
    label: str
    tokens_approx: int
    percentage: float
    description: str


class ContextSummaryPayload(BaseModel):
    scope_kind: Literal["channel", "session"]
    scope_id: str
    session_id: str | None = None
    bot_id: str
    title: str
    headline: str
    budget: ContextSummaryBudget | None = None
    top_categories: list[ContextSummaryCategory] = []
    message_count: int | None = None
    total_chars: int | None = None
    notes: list[str] = []


class SlashCommandResult(BaseModel):
    command_id: str
    result_type: str
    payload: dict
    fallback_text: str


class SideEffectPayload(BaseModel):
    effect: Literal["stop", "compact", "plan"]
    scope_kind: Literal["channel", "session"]
    scope_id: str
    title: str
    detail: str


class _ContextDebugMessage(BaseModel):
    role: str
    content: str | None = None
    chars: int = 0


class _ContextDebugOut(BaseModel):
    session_id: uuid.UUID
    bot_id: str
    message_count: int
    total_chars: int
    messages: list[_ContextDebugMessage]


def list_supported_slash_commands() -> list[dict[str, str]]:
    return [
        {
            "id": "context",
            "label": "/context",
            "description": "Show a compact summary of the current context",
        },
        {
            "id": "stop",
            "label": "/stop",
            "description": "Stop the current response",
        },
        {
            "id": "compact",
            "label": "/compact",
            "description": "Compress conversation",
        },
        {
            "id": "plan",
            "label": "/plan",
            "description": "Toggle plan mode",
        },
    ]


def _format_budget_headline(budget: ContextSummaryBudget | None, headline: str) -> str:
    if budget is None or budget.total_tokens is None:
        return headline
    gross = budget.gross_prompt_tokens or budget.consumed_tokens
    if gross is None:
        return headline
    pct = (
        round((gross / budget.total_tokens) * 100)
        if budget.total_tokens > 0
        else None
    )
    if pct is None:
        return headline
    return f"{headline} ({gross:,}/{budget.total_tokens:,} tokens, {pct}%)"


def _payload_to_fallback(payload: ContextSummaryPayload) -> str:
    headline = _format_budget_headline(payload.budget, payload.headline)
    lines = [headline]
    for cat in payload.top_categories[:3]:
        lines.append(f"- {cat.label}: {cat.tokens_approx:,} tok ({round(cat.percentage * 100)}%)")
    for note in payload.notes[:2]:
        lines.append(f"- {note}")
    return "\n".join(lines)


def _side_effect_result(payload: SideEffectPayload, *, command_id: str) -> SlashCommandResult:
    return SlashCommandResult(
        command_id=command_id,
        result_type="side_effect",
        payload=payload.model_dump(),
        fallback_text=payload.detail,
    )


async def _build_channel_context_summary(
    channel_id: uuid.UUID,
    db: AsyncSession,
) -> SlashCommandResult:
    breakdown = await compute_context_breakdown(str(channel_id), db, mode="last_turn")
    budget_dict = await fetch_latest_context_budget(channel_id, db)
    top_categories = sorted(
        [c for c in breakdown.categories if c.tokens_approx > 0],
        key=lambda c: c.tokens_approx,
        reverse=True,
    )[:4]
    budget = ContextSummaryBudget(**budget_dict)
    payload = ContextSummaryPayload(
        scope_kind="channel",
        scope_id=str(channel_id),
        session_id=breakdown.session_id,
        bot_id=breakdown.bot_id,
        title="Context snapshot",
        headline="Current channel context",
        budget=budget,
        top_categories=[
            ContextSummaryCategory(
                key=cat.key,
                label=cat.label,
                tokens_approx=cat.tokens_approx,
                percentage=cat.percentage,
                description=cat.description,
            )
            for cat in top_categories
        ],
        total_chars=breakdown.total_chars,
        notes=[
            breakdown.disclaimer,
            (f"Profile: {budget.context_profile}" if budget.context_profile else ""),
            (
                f"Prompt split: {budget.gross_prompt_tokens:,} gross, {budget.current_prompt_tokens:,} current"
                + (
                    f", {budget.cached_prompt_tokens:,} cached"
                    if budget.cached_prompt_tokens is not None
                    else ""
                )
                if budget.gross_prompt_tokens is not None and budget.current_prompt_tokens is not None
                else ""
            ),
            f"Compaction {'on' if breakdown.compaction.enabled else 'off'}",
        ],
    )
    payload.notes = [note for note in payload.notes if note]
    return SlashCommandResult(
        command_id="context",
        result_type="context_summary",
        payload=payload.model_dump(),
        fallback_text=_payload_to_fallback(payload),
    )


def _summarize_session_context(debug: _ContextDebugOut) -> SlashCommandResult:
    assistant_like = [m for m in debug.messages if m.role in {"assistant", "system"}]
    top_messages = sorted(assistant_like, key=lambda m: m.chars, reverse=True)[:4]
    notes: list[str] = []
    system_count = sum(1 for m in debug.messages if m.role == "system")
    if system_count:
        notes.append(f"{system_count} system blocks currently assembled")
    if top_messages:
        notes.append(f"Largest block: {top_messages[0].role} ({top_messages[0].chars:,} chars)")
    payload = ContextSummaryPayload(
        scope_kind="session",
        scope_id=str(debug.session_id),
        session_id=str(debug.session_id),
        bot_id=debug.bot_id,
        title="Context snapshot",
        headline="Current session context",
        budget=None,
        top_categories=[
            ContextSummaryCategory(
                key=f"{msg.role}:{idx}",
                label=f"{msg.role.title()} block {idx + 1}",
                tokens_approx=round(msg.chars / 3.5),
                percentage=(msg.chars / debug.total_chars) if debug.total_chars else 0.0,
                description=(msg.content or "").strip().splitlines()[0][:120] or "No preview",
            )
            for idx, msg in enumerate(top_messages)
        ],
        message_count=debug.message_count,
        total_chars=debug.total_chars,
        notes=notes,
    )
    return SlashCommandResult(
        command_id="context",
        result_type="context_summary",
        payload=payload.model_dump(),
        fallback_text=_payload_to_fallback(payload),
    )


async def _build_session_context_summary(
    session_id: uuid.UUID,
    db: AsyncSession,
) -> SlashCommandResult:
    from app.agent.bots import get_bot
    from app.agent.context_assembly import AssemblyResult, assemble_context
    from app.agent.context_profiles import resolve_context_profile
    from app.services.sessions import _load_messages

    session = await db.get(Session, session_id)
    if session is None:
        raise LookupError("Session not found")

    bot = get_bot(session.bot_id)
    messages = await _load_messages(db, session)
    result = AssemblyResult()
    async for _event in assemble_context(
        messages=messages,
        bot=bot,
        user_message="hello",
        session_id=session_id,
        client_id=session.client_id,
        correlation_id=None,
        channel_id=session.channel_id,
        audio_data=None,
        audio_format=None,
        attachments=None,
        native_audio=False,
        result=result,
        context_profile_name=resolve_context_profile(session=session).name,
    ):
        pass

    out_messages: list[_ContextDebugMessage] = []
    total_chars = 0
    for message in messages:
        content = message.get("content")
        content_str = str(content) if content is not None else None
        chars = len(content_str) if content_str else 0
        total_chars += chars
        out_messages.append(
            _ContextDebugMessage(
                role=message.get("role", "unknown"),
                content=content_str,
                chars=chars,
            )
        )

    debug = _ContextDebugOut(
        session_id=session_id,
        bot_id=session.bot_id,
        message_count=len(out_messages),
        total_chars=total_chars,
        messages=out_messages,
    )
    return _summarize_session_context(debug)


async def _stop_session(
    *,
    session_id: uuid.UUID,
    scope_kind: Literal["channel", "session"],
    scope_id: uuid.UUID,
    db: AsyncSession,
) -> SlashCommandResult:
    cancelled = session_locks.request_cancel(session_id)
    result = await db.execute(
        update(Task)
        .where(Task.session_id == session_id, Task.status == "pending")
        .values(status="failed")
    )
    queued_cancelled = result.rowcount or 0
    await db.commit()
    payload = SideEffectPayload(
        effect="stop",
        scope_kind=scope_kind,
        scope_id=str(scope_id),
        title="Response stopped" if cancelled else "Nothing to stop",
        detail=(
            f"Stopped the current response and cancelled {queued_cancelled} queued task(s)."
            if cancelled or queued_cancelled
            else "No active or queued response was running."
        ),
    )
    return _side_effect_result(payload, command_id="stop")


async def _compact_session(
    *,
    session_id: uuid.UUID,
    scope_kind: Literal["channel", "session"],
    scope_id: uuid.UUID,
    db: AsyncSession,
) -> SlashCommandResult:
    from app.agent.bots import get_bot
    from app.services.compaction import run_compaction_forced

    session = await db.get(Session, session_id)
    if session is None:
        raise LookupError("Session not found")

    bot = get_bot(session.bot_id)
    title, summary = await run_compaction_forced(session_id, bot, db)
    await db.commit()
    payload = SideEffectPayload(
        effect="compact",
        scope_kind=scope_kind,
        scope_id=str(scope_id),
        title=title,
        detail=f"Compacted the active conversation into a {len(summary):,}-character summary.",
    )
    return _side_effect_result(payload, command_id="compact")


async def _toggle_plan_mode(
    *,
    session: Session,
    scope_kind: Literal["channel", "session"],
    scope_id: uuid.UUID,
    channel: Channel | None,
    db: AsyncSession,
) -> SlashCommandResult:
    existing = load_session_plan(session, required=False)
    mode = get_session_plan_mode(session)
    if existing is None:
        enter_session_plan_mode(session)
        await db.commit()
        payload = SideEffectPayload(
            effect="plan",
            scope_kind=scope_kind,
            scope_id=str(scope_id),
            title="Plan mode started",
            detail="Started session plan mode. The agent can now discuss and publish a plan in-chat.",
        )
        return _side_effect_result(payload, command_id="plan")
    if mode == "chat":
        resume_session_plan_mode(session)
        await db.commit()
        payload = SideEffectPayload(
            effect="plan",
            scope_kind=scope_kind,
            scope_id=str(scope_id),
            title="Plan mode resumed",
            detail=f"Resumed plan mode for {existing.title!r}.",
        )
        return _side_effect_result(payload, command_id="plan")

    exit_session_plan_mode(session)
    await db.commit()
    payload = SideEffectPayload(
        effect="plan",
        scope_kind=scope_kind,
        scope_id=str(scope_id),
        title="Plan mode exited",
        detail=f"Exited plan mode for {existing.title!r}.",
    )
    return _side_effect_result(payload, command_id="plan")


async def execute_slash_command(
    *,
    command_id: str,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    db: AsyncSession,
) -> SlashCommandResult:
    if bool(channel_id) == bool(session_id):
        raise ValueError("Exactly one of channel_id or session_id is required")

    if channel_id is not None:
        channel = await db.get(Channel, channel_id)
        if channel is None:
            raise LookupError("Channel not found")
        if command_id == "context":
            return await _build_channel_context_summary(channel_id, db)
        if command_id == "stop":
            if channel.active_session_id is None:
                raise LookupError("Channel has no active conversation")
            return await _stop_session(
                session_id=channel.active_session_id,
                scope_kind="channel",
                scope_id=channel_id,
                db=db,
            )
        if command_id == "compact":
            if channel.active_session_id is None:
                raise LookupError("Channel has no active conversation")
            return await _compact_session(
                session_id=channel.active_session_id,
                scope_kind="channel",
                scope_id=channel_id,
                db=db,
            )
        if command_id == "plan":
            if channel.active_session_id is None:
                raise LookupError("Channel has no active conversation")
            session = await db.get(Session, channel.active_session_id)
            if session is None:
                raise LookupError("Session not found")
            return await _toggle_plan_mode(
                session=session,
                scope_kind="channel",
                scope_id=channel_id,
                channel=channel,
                db=db,
            )
        raise ValueError(f"Unsupported slash command: {command_id}")

    if command_id == "context":
        return await _build_session_context_summary(session_id, db)
    if command_id == "stop":
        return await _stop_session(
            session_id=session_id,
            scope_kind="session",
            scope_id=session_id,
            db=db,
        )
    if command_id == "compact":
        return await _compact_session(
            session_id=session_id,
            scope_kind="session",
            scope_id=session_id,
            db=db,
        )
    if command_id == "plan":
        session = await db.get(Session, session_id)
        if session is None:
            raise LookupError("Session not found")
        channel = await db.get(Channel, session.channel_id) if session.channel_id else None
        return await _toggle_plan_mode(
            session=session,
            scope_kind="session",
            scope_id=session_id,
            channel=channel,
            db=db,
        )
    raise ValueError(f"Unsupported slash command: {command_id}")
