"""Backend-owned slash command registry and execution helpers.

The command contract is client-agnostic: each command returns a typed result
payload plus plain-text fallback so web, Slack, and CLI can all render the
same semantic output in their own surfaces.

The registry itself (`COMMANDS`) is a dict of `SlashCommandSpec` — each entry
carries its own metadata, handler, and arg schema, so adding a new command is
a single entry instead of touching a dispatcher `if/elif` chain and two
hardcoded registries.
"""
from __future__ import annotations

import copy as _copy
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.agent.context_profiles import get_context_profile, resolve_context_profile
from app.db.models import Bot as BotRow, Channel, Session, Task
from app.services import session_locks
from app.services.context_breakdown import compute_context_breakdown, fetch_latest_context_budget
from app.services.session_plan_mode import (
    enter_session_plan_mode,
    exit_session_plan_mode,
    get_session_plan_mode,
    load_session_plan,
    resume_session_plan_mode,
)


# ============================================================================
# Payload types
# ============================================================================


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


class ContextPinnedWidgetRow(BaseModel):
    pin_id: str
    label: str
    summary: str
    hint: str | None = None
    line: str
    chars: int


class ContextPinnedWidgetSkipped(BaseModel):
    pin_id: str
    label: str
    reason: str


class ContextPinnedWidgetSummary(BaseModel):
    enabled: bool
    total_pins: int
    exported_count: int
    skipped_count: int
    total_chars: int
    truncated: bool = False
    rows: list[ContextPinnedWidgetRow] = []
    skipped: list[ContextPinnedWidgetSkipped] = []
    block_text: str | None = None


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
    pinned_widget_context: ContextPinnedWidgetSummary | None = None


class SlashCommandResult(BaseModel):
    command_id: str
    result_type: str
    payload: dict
    fallback_text: str


class SideEffectPayload(BaseModel):
    effect: Literal["stop", "compact", "plan", "effort", "rename", "style"]
    scope_kind: Literal["channel", "session"]
    scope_id: str
    title: str
    detail: str
    status: Literal["queued", "started"] | None = None
    message_id: str | None = None


class FindMatch(BaseModel):
    message_id: str
    session_id: str
    role: str
    preview: str
    created_at: str | None = None


class FindResultsPayload(BaseModel):
    scope_kind: Literal["channel", "session"]
    scope_id: str
    query: str
    matches: list[FindMatch] = []
    truncated: bool = False


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


EFFORT_LEVELS: tuple[str, ...] = ("off", "low", "medium", "high")
CHAT_MODES: tuple[str, ...] = ("default", "terminal")
THEMES: tuple[str, ...] = ("light", "dark")
FIND_LIMIT = 20


# ============================================================================
# Registry types
# ============================================================================


@dataclass(frozen=True)
class SlashCommandArgSpec:
    """Single positional argument for a slash command.

    `source` controls how the frontend resolves completions:
      - "free_text": no completion; raw user input (e.g. /rename <title>)
      - "enum": one of `enum`; completions are the enum values
      - "model": dynamic completion from the model catalog (useCompletions)
    """

    name: str
    source: Literal["free_text", "enum", "model"]
    required: bool = True
    enum: tuple[str, ...] | None = None


@dataclass
class SlashCommandContext:
    """Resolved context passed to a slash command handler."""

    command_id: str
    surface: Literal["channel", "session"]
    channel: Channel | None
    session: Session | None
    channel_id: uuid.UUID | None
    session_id: uuid.UUID | None
    args: list[str]
    db: AsyncSession


SlashCommandHandler = Callable[[SlashCommandContext], Awaitable[SlashCommandResult]]


@dataclass
class SlashCommandSpec:
    """One slash command.

    Backend commands supply a `handler`. Client-only commands (clear, scratch,
    model, theme) set `local_only=True` and have no handler — the router
    refuses to execute them and the frontend handles them entirely.
    """

    id: str
    label: str
    description: str
    surfaces: tuple[Literal["channel", "session"], ...]
    handler: SlashCommandHandler | None = None
    local_only: bool = False
    args: tuple[SlashCommandArgSpec, ...] = ()


COMMANDS: dict[str, SlashCommandSpec] = {}


def _register(spec: SlashCommandSpec) -> SlashCommandSpec:
    COMMANDS[spec.id] = spec
    return spec


# ============================================================================
# Shared helpers (unchanged behavior from the pre-refactor code)
# ============================================================================


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
    if payload.pinned_widget_context is not None:
        pinned = payload.pinned_widget_context
        if not pinned.enabled:
            lines.append("- Pinned widgets: disabled for this channel")
        elif pinned.exported_count > 0:
            lines.append(
                f"- Pinned widgets: {pinned.exported_count} exported"
                + (f", {pinned.skipped_count} skipped" if pinned.skipped_count else "")
            )
        elif pinned.total_pins > 0:
            lines.append("- Pinned widgets: no exportable rows")
    for note in payload.notes[:2]:
        lines.append(f"- {note}")
    return "\n".join(lines)


async def _build_pinned_widget_context_summary(
    *,
    db: AsyncSession,
    channel: Channel | None,
    bot_id: str,
    profile_name: str = "chat",
) -> ContextPinnedWidgetSummary | None:
    from app.services.widget_context import (
        build_pinned_widget_context_snapshot,
        fetch_channel_pin_dicts,
        is_pinned_widget_context_enabled,
    )

    if channel is None:
        return None
    pins = await fetch_channel_pin_dicts(db, channel.id)
    profile = get_context_profile(profile_name)
    enabled = profile.allow_pinned_widgets and is_pinned_widget_context_enabled(channel.config or {})
    disabled_reason = "profile_disabled" if not profile.allow_pinned_widgets else "channel_disabled"
    snapshot = await build_pinned_widget_context_snapshot(
        db,
        pins,
        bot_id=bot_id,
        channel_id=str(channel.id),
        enabled=enabled,
        disabled_reason=disabled_reason,
    )
    return ContextPinnedWidgetSummary(**snapshot)


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
    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise LookupError("Channel not found")
    breakdown = await compute_context_breakdown(str(channel_id), db, mode="last_turn")
    budget_dict = await fetch_latest_context_budget(channel_id, db)
    pinned_widget_context = await _build_pinned_widget_context_summary(
        db=db,
        channel=channel,
        bot_id=breakdown.bot_id,
        profile_name="chat",
    )
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
        pinned_widget_context=pinned_widget_context,
    )
    payload.notes = [note for note in payload.notes if note]
    return SlashCommandResult(
        command_id="context",
        result_type="context_summary",
        payload=payload.model_dump(),
        fallback_text=_payload_to_fallback(payload),
    )


def _summarize_session_context(
    debug: _ContextDebugOut,
    *,
    pinned_widget_context: ContextPinnedWidgetSummary | None = None,
) -> SlashCommandResult:
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
        pinned_widget_context=pinned_widget_context,
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
    from app.services.sessions import _load_messages

    session = await db.get(Session, session_id)
    if session is None:
        raise LookupError("Session not found")

    bot = get_bot(session.bot_id)
    channel = await db.get(Channel, session.channel_id) if session.channel_id else None
    profile = resolve_context_profile(session=session)
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
        context_profile_name=profile.name,
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
    pinned_widget_context = await _build_pinned_widget_context_summary(
        db=db,
        channel=channel,
        bot_id=session.bot_id,
        profile_name=profile.name,
    )
    return _summarize_session_context(debug, pinned_widget_context=pinned_widget_context)


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
    from app.services.compaction import request_manual_compaction

    session = await db.get(Session, session_id)
    if session is None:
        raise LookupError("Session not found")

    bot = get_bot(session.bot_id)
    request = await request_manual_compaction(session_id, bot, db)
    status: Literal["queued", "started"] = (
        "queued" if request.get("status") == "queued" else "started"
    )
    queued = status == "queued"
    payload = SideEffectPayload(
        effect="compact",
        scope_kind=scope_kind,
        scope_id=str(scope_id),
        title="Compaction queued" if queued else "Compaction started",
        detail=(
            "Compaction will start after the current response finishes."
            if queued
            else "Compaction started."
        ),
        status=status,
        message_id=request.get("message_id") or None,
    )
    return _side_effect_result(payload, command_id="compact")


async def _set_channel_effort(
    *,
    channel: Channel,
    channel_id: uuid.UUID,
    args: list[str],
    db: AsyncSession,
) -> SlashCommandResult:
    """Persist `channel.config['effort_override']` based on `/effort <level>`.

    Level `off` clears the override so the bot falls back to its configured
    default. Any other level must be one of the canonical EFFORT_LEVELS.
    """
    level = (args[0].strip().lower() if args else "").strip()
    if not level:
        raise ValueError(
            f"/effort requires one argument: {'/'.join(EFFORT_LEVELS)}"
        )
    if level not in EFFORT_LEVELS:
        raise ValueError(
            f"Unknown effort level {level!r}. Must be one of: {', '.join(EFFORT_LEVELS)}"
        )

    # Only `off` always succeeds (clears state). Any real effort level must
    # be validated against the channel's primary bot's model capability so the
    # user gets a signal instead of a silent drop in `filter_model_params`.
    if level != "off" and channel.bot_id:
        from app.services.providers import supports_reasoning as _supports_reasoning

        bot_row = await db.get(BotRow, channel.bot_id)
        if bot_row is not None and not _supports_reasoning(bot_row.model):
            raise ValueError(
                f"Bot {bot_row.name!r} uses model {bot_row.model!r}, which is not marked "
                f"as reasoning-capable. Try a Claude (Opus/Sonnet/Haiku-4.5), Codex/gpt-5, "
                f"Gemini 2.5, o-series, or DeepSeek R1 model, or toggle the Reasoning flag "
                f"on the model in the admin providers page."
            )

    cfg = _copy.deepcopy(channel.config or {})
    if level == "off":
        cfg.pop("effort_override", None)
        detail = "Reasoning effort cleared. Bot will use its configured default."
        title = "Effort cleared"
    else:
        cfg["effort_override"] = level
        detail = f"Reasoning effort set to {level} for this channel."
        title = f"Effort: {level}"
    channel.config = cfg
    flag_modified(channel, "config")
    await db.commit()

    payload = SideEffectPayload(
        effect="effort",
        scope_kind="channel",
        scope_id=str(channel_id),
        title=title,
        detail=detail,
    )
    return _side_effect_result(payload, command_id="effort")


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


# ============================================================================
# Handlers — thin ctx adapters over the shared helpers above
# ============================================================================


async def _context_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    if ctx.surface == "channel":
        assert ctx.channel_id is not None
        return await _build_channel_context_summary(ctx.channel_id, ctx.db)
    assert ctx.session_id is not None
    return await _build_session_context_summary(ctx.session_id, ctx.db)


async def _stop_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    if ctx.surface == "channel":
        assert ctx.channel is not None and ctx.channel_id is not None
        if ctx.channel.active_session_id is None:
            raise LookupError("Channel has no active conversation")
        return await _stop_session(
            session_id=ctx.channel.active_session_id,
            scope_kind="channel",
            scope_id=ctx.channel_id,
            db=ctx.db,
        )
    assert ctx.session_id is not None
    return await _stop_session(
        session_id=ctx.session_id,
        scope_kind="session",
        scope_id=ctx.session_id,
        db=ctx.db,
    )


async def _compact_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    if ctx.surface == "channel":
        assert ctx.channel is not None and ctx.channel_id is not None
        if ctx.channel.active_session_id is None:
            raise LookupError("Channel has no active conversation")
        return await _compact_session(
            session_id=ctx.channel.active_session_id,
            scope_kind="channel",
            scope_id=ctx.channel_id,
            db=ctx.db,
        )
    assert ctx.session_id is not None
    return await _compact_session(
        session_id=ctx.session_id,
        scope_kind="session",
        scope_id=ctx.session_id,
        db=ctx.db,
    )


async def _plan_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    if ctx.surface == "channel":
        assert ctx.channel is not None and ctx.channel_id is not None
        if ctx.channel.active_session_id is None:
            raise LookupError("Channel has no active conversation")
        session = await ctx.db.get(Session, ctx.channel.active_session_id)
        if session is None:
            raise LookupError("Session not found")
        return await _toggle_plan_mode(
            session=session,
            scope_kind="channel",
            scope_id=ctx.channel_id,
            channel=ctx.channel,
            db=ctx.db,
        )
    assert ctx.session is not None and ctx.session_id is not None
    channel = (
        await ctx.db.get(Channel, ctx.session.channel_id)
        if ctx.session.channel_id
        else None
    )
    return await _toggle_plan_mode(
        session=ctx.session,
        scope_kind="session",
        scope_id=ctx.session_id,
        channel=channel,
        db=ctx.db,
    )


async def _effort_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    if ctx.surface != "channel":
        raise ValueError("/effort is a channel setting; not available on sessions")
    assert ctx.channel is not None and ctx.channel_id is not None
    return await _set_channel_effort(
        channel=ctx.channel,
        channel_id=ctx.channel_id,
        args=ctx.args,
        db=ctx.db,
    )


# ============================================================================
# New handlers: /help, /find, /rename, /mode
# ============================================================================


async def _help_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    """List commands available on the current surface as a context_summary.

    Reusing the existing `context_summary` renderer means `/help` doesn't
    require a new frontend component — each command becomes a "category" row.
    """
    available = [s for s in COMMANDS.values() if ctx.surface in s.surfaces]
    categories = [
        ContextSummaryCategory(
            key=s.id,
            label=s.label,
            tokens_approx=0,
            percentage=0.0,
            description=s.description,
        )
        for s in available
    ]
    scope_id = str(ctx.channel_id if ctx.surface == "channel" else ctx.session_id)
    bot_id = ""
    if ctx.channel is not None and ctx.channel.bot_id:
        bot_id = str(ctx.channel.bot_id)
    elif ctx.session is not None:
        bot_id = str(ctx.session.bot_id)
    payload = ContextSummaryPayload(
        scope_kind=ctx.surface,
        scope_id=scope_id,
        session_id=str(ctx.session_id) if ctx.session_id else None,
        bot_id=bot_id,
        title="Available commands",
        headline=f"{len(available)} slash commands available here",
        top_categories=categories,
        notes=[],
    )
    fallback = "\n".join(f"{c.label} — {c.description}" for c in categories)
    return SlashCommandResult(
        command_id="help",
        result_type="context_summary",
        payload=payload.model_dump(),
        fallback_text=fallback,
    )


async def _find_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    """Keyword search over recent messages in the current channel.

    Returns a `find_results` payload the frontend renders as a clickable
    list; clicking a row scrolls the chat feed to that message.
    """
    from app.tools.local.search_history import _build_query, _serialize_messages

    if ctx.surface != "channel":
        raise ValueError("/find is only available in channel scope")
    assert ctx.channel is not None and ctx.channel_id is not None

    query = " ".join(ctx.args).strip()
    if not query:
        raise ValueError("/find requires a search query")

    stmt = _build_query(
        channel_id=ctx.channel_id,
        bot_id=ctx.channel.bot_id,
        query=query,
        limit=FIND_LIMIT,
    )
    rows = (await ctx.db.execute(stmt)).scalars().all()
    serialized = _serialize_messages(rows)
    matches = [
        FindMatch(
            message_id=r["id"],
            session_id=r["session_id"],
            role=r["role"],
            preview=r["content_preview"],
            created_at=r["created_at"],
        )
        for r in serialized
    ]
    payload = FindResultsPayload(
        scope_kind="channel",
        scope_id=str(ctx.channel_id),
        query=query,
        matches=matches,
        truncated=len(matches) >= FIND_LIMIT,
    )
    count = len(matches)
    fallback = (
        f"{count} match{'es' if count != 1 else ''} for {query!r}"
        + (" (more results truncated)" if payload.truncated else "")
    )
    return SlashCommandResult(
        command_id="find",
        result_type="find_results",
        payload=payload.model_dump(),
        fallback_text=fallback,
    )


async def _rename_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    """Rename the channel (surface=channel) or session (surface=session)."""
    new_title = " ".join(ctx.args).strip()
    if not new_title:
        raise ValueError("/rename requires a title")
    new_title = new_title[:200]

    if ctx.surface == "channel":
        assert ctx.channel is not None and ctx.channel_id is not None
        ctx.channel.name = new_title
        await ctx.db.commit()
        scope_id = str(ctx.channel_id)
        noun = "Channel"
    else:
        assert ctx.session is not None and ctx.session_id is not None
        ctx.session.title = new_title
        await ctx.db.commit()
        scope_id = str(ctx.session_id)
        noun = "Session"

    payload = SideEffectPayload(
        effect="rename",
        scope_kind=ctx.surface,
        scope_id=scope_id,
        title=f"Renamed to {new_title!r}",
        detail=f"{noun} renamed to {new_title!r}.",
    )
    return _side_effect_result(payload, command_id="rename")


async def _mode_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    """Set or toggle `channel.config['chat_mode']`.

    No arg → toggle between default and terminal. With arg → set explicitly.
    `default` is stored as "no key" (mirrors the PATCH config endpoint's
    treatment so the channel config stays tidy).
    """
    if ctx.surface != "channel":
        raise ValueError("/style is a channel setting; not available on sessions")
    assert ctx.channel is not None and ctx.channel_id is not None

    current = (ctx.channel.config or {}).get("chat_mode", "default")
    if ctx.args:
        target = ctx.args[0].strip().lower()
        if target not in CHAT_MODES:
            raise ValueError(
                f"Unknown chat mode {target!r}. Must be one of: {', '.join(CHAT_MODES)}"
            )
    else:
        target = "terminal" if current == "default" else "default"

    cfg = _copy.deepcopy(ctx.channel.config or {})
    if target == "default":
        cfg.pop("chat_mode", None)
    else:
        cfg["chat_mode"] = target
    ctx.channel.config = cfg
    flag_modified(ctx.channel, "config")
    await ctx.db.commit()

    payload = SideEffectPayload(
        effect="style",
        scope_kind="channel",
        scope_id=str(ctx.channel_id),
        title=f"Chat style: {target}",
        detail=f"Chat style set to {target}.",
    )
    return _side_effect_result(payload, command_id="style")


# ============================================================================
# Registry — ordering here controls `/help` output and dropdown order
# ============================================================================


_register(SlashCommandSpec(
    id="help",
    label="/help",
    description="List available commands",
    surfaces=("channel", "session"),
    handler=_help_handler,
))

_register(SlashCommandSpec(
    id="context",
    label="/context",
    description="Show a compact summary of the current context",
    surfaces=("channel", "session"),
    handler=_context_handler,
))

_register(SlashCommandSpec(
    id="find",
    label="/find",
    description="Search recent messages in this channel",
    surfaces=("channel",),
    handler=_find_handler,
    args=(SlashCommandArgSpec(name="query", source="free_text", required=True),),
))

_register(SlashCommandSpec(
    id="rename",
    label="/rename",
    description="Rename this channel or session",
    surfaces=("channel", "session"),
    handler=_rename_handler,
    args=(SlashCommandArgSpec(name="title", source="free_text", required=True),),
))

_register(SlashCommandSpec(
    id="model",
    label="/model",
    description="Set the model for this chat",
    surfaces=("channel", "session"),
    local_only=True,
    args=(SlashCommandArgSpec(name="model_id", source="model", required=True),),
))

_register(SlashCommandSpec(
    id="style",
    label="/style",
    description="Switch chat style (default / terminal)",
    surfaces=("channel",),
    handler=_mode_handler,
    args=(SlashCommandArgSpec(name="style", source="enum", required=False, enum=CHAT_MODES),),
))

_register(SlashCommandSpec(
    id="theme",
    label="/theme",
    description="Toggle or set the theme (light / dark)",
    surfaces=("channel", "session"),
    local_only=True,
    args=(SlashCommandArgSpec(name="theme", source="enum", required=False, enum=THEMES),),
))

_register(SlashCommandSpec(
    id="stop",
    label="/stop",
    description="Stop the current response",
    surfaces=("channel", "session"),
    handler=_stop_handler,
))

_register(SlashCommandSpec(
    id="compact",
    label="/compact",
    description="Compress conversation",
    surfaces=("channel", "session"),
    handler=_compact_handler,
))

_register(SlashCommandSpec(
    id="plan",
    label="/plan",
    description="Toggle plan mode",
    surfaces=("channel", "session"),
    handler=_plan_handler,
))

_register(SlashCommandSpec(
    id="effort",
    label="/effort",
    description="Set reasoning effort (off / low / medium / high)",
    surfaces=("channel",),
    handler=_effort_handler,
    args=(SlashCommandArgSpec(name="level", source="enum", required=True, enum=EFFORT_LEVELS),),
))

_register(SlashCommandSpec(
    id="clear",
    label="/clear",
    description="Start fresh (local)",
    surfaces=("channel",),
    local_only=True,
))

_register(SlashCommandSpec(
    id="scratch",
    label="/scratch",
    description="Open the scratch pad (local)",
    surfaces=("channel",),
    local_only=True,
))

_register(SlashCommandSpec(
    id="sessions",
    label="/sessions",
    description="Switch or split sessions in this channel (local)",
    surfaces=("channel", "session"),
    local_only=True,
))


# ============================================================================
# Public API
# ============================================================================


def list_supported_slash_commands() -> list[dict]:
    """Canonical slash-command registry.

    The frontend fetches this at load time via `GET /api/v1/slash-commands`
    so there is one source of truth. Shape:

        {
            id, label, description,
            surfaces: ["channel"|"session", ...],
            local_only: bool,
            args: [{ name, source, required, enum | null }, ...]
        }
    """
    return [
        {
            "id": s.id,
            "label": s.label,
            "description": s.description,
            "surfaces": list(s.surfaces),
            "local_only": s.local_only,
            "args": [
                {
                    "name": a.name,
                    "source": a.source,
                    "required": a.required,
                    "enum": list(a.enum) if a.enum else None,
                }
                for a in s.args
            ],
        }
        for s in COMMANDS.values()
    ]


async def execute_slash_command(
    *,
    command_id: str,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    db: AsyncSession,
    args: list[str] | None = None,
) -> SlashCommandResult:
    if bool(channel_id) == bool(session_id):
        raise ValueError("Exactly one of channel_id or session_id is required")
    args = list(args or [])

    spec = COMMANDS.get(command_id)
    if spec is None:
        raise ValueError(f"Unsupported slash command: {command_id}")
    if spec.local_only:
        raise ValueError(
            f"Command {command_id!r} is client-only and should not be executed via the backend"
        )
    if spec.handler is None:
        raise ValueError(f"Command {command_id!r} has no backend handler")

    surface: Literal["channel", "session"] = (
        "channel" if channel_id is not None else "session"
    )
    if surface not in spec.surfaces:
        raise ValueError(
            f"/{command_id} is not available in {surface} scope"
        )

    required_count = sum(1 for a in spec.args if a.required)
    if len(args) < required_count:
        required_names = ", ".join(a.name for a in spec.args if a.required)
        raise ValueError(
            f"/{command_id} requires {required_count} arg(s): {required_names}"
        )
    if spec.args:
        for i, arg_spec in enumerate(spec.args):
            if i >= len(args):
                break
            if arg_spec.source == "enum" and arg_spec.enum:
                if args[i].strip().lower() not in arg_spec.enum:
                    raise ValueError(
                        f"Invalid {arg_spec.name} {args[i]!r}. "
                        f"Must be one of: {', '.join(arg_spec.enum)}"
                    )
    elif args:
        raise ValueError(f"/{command_id} takes no arguments")

    channel: Channel | None = None
    session: Session | None = None
    if channel_id is not None:
        channel = await db.get(Channel, channel_id)
        if channel is None:
            raise LookupError("Channel not found")
    else:
        session = await db.get(Session, session_id)
        if session is None:
            raise LookupError("Session not found")

    ctx = SlashCommandContext(
        command_id=command_id,
        surface=surface,
        channel=channel,
        session=session,
        channel_id=channel_id,
        session_id=session_id,
        args=args,
        db=db,
    )
    return await spec.handler(ctx)
