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

import asyncio
import copy as _copy
import logging
import uuid

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel
from sqlalchemy import select, update
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
from app.services.sub_sessions import SESSION_TYPE_CHANNEL


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
    effect: Literal["stop", "compact", "plan", "effort", "rename", "style", "model"]
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
    current_session_id: uuid.UUID | None
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
# Harness-aware filter helpers (Phase 4)
# ============================================================================


async def _resolve_harness_runtime_for_bot(
    db: AsyncSession, bot_id: str | None,
):
    """Look up a bot's harness runtime, or ``None`` if non-harness/missing.

    Returns the registered ``HarnessRuntime`` so callers can read its
    ``capabilities()``. Used by ``/help`` filtering, the ``/model`` and
    ``/effort`` harness branches, and ``list_supported_slash_commands``.
    """
    if bot_id is None:
        return None
    from app.services.agent_harnesses import HARNESS_REGISTRY

    bot_row = await db.get(BotRow, bot_id)
    if bot_row is None or not bot_row.harness_runtime:
        return None
    return HARNESS_REGISTRY.get(bot_row.harness_runtime)


def _filter_specs_for_runtime(specs, runtime) -> list:
    """Intersect a list of specs with a runtime's slash policy.

    Non-harness (runtime is None): pass through unchanged.
    Harness: keep only specs whose id is in the runtime's allowlist.
    """
    if runtime is None or not hasattr(runtime, "capabilities"):
        return list(specs)
    allowed = runtime.capabilities().slash_policy.allowed_command_ids
    return [s for s in specs if s.id in allowed]


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
    # Phase 3: also expire any pending harness approvals on this session so the
    # UI flips them to expired immediately instead of waiting on the 300s row
    # timeout. Cheap when nothing is pending.
    from app.services.agent_harnesses.approvals import (
        cancel_pending_harness_approvals_for_session,
    )
    try:
        await cancel_pending_harness_approvals_for_session(session_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "stop-session: failed to cancel pending harness approvals for %s",
            session_id,
        )
    from app.services.agent_harnesses.interactions import (
        cancel_pending_harness_questions_for_session,
    )
    try:
        await cancel_pending_harness_questions_for_session(session_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "stop-session: failed to cancel pending harness questions for %s",
            session_id,
        )
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
    if getattr(bot, "harness_runtime", None):
        from app.services.agent_harnesses.session_state import run_native_harness_compact

        payload = await run_native_harness_compact(db, session_id, source="/compact")
        ok = payload.get("status") == "completed"
        detail = str(payload.get("detail") or (
            "Native harness compaction completed."
            if ok
            else "Native harness compaction failed."
        ))
        return SlashCommandResult(
            command_id="compact",
            result_type="harness_native_compaction",
            payload={
                "session_id": str(session_id),
                "scope_kind": scope_kind,
                "scope_id": str(scope_id),
                "title": "Native compaction completed" if ok else "Native compaction failed",
                "detail": detail,
                "status": payload.get("status"),
                "usage": payload.get("usage"),
                "native_session_id": payload.get("session_id"),
                "error": payload.get("error"),
                "metadata": payload.get("metadata") or {},
            },
            fallback_text=f"{'Native compaction completed' if ok else 'Native compaction failed'}\n\n{detail}",
        )

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


def _session_belongs_to_channel(session: Session, channel_id: uuid.UUID) -> bool:
    return session.channel_id == channel_id or session.parent_channel_id == channel_id


async def _resolve_current_session(ctx: SlashCommandContext) -> Session:
    """Resolve the UI-current session for session-scoped work.

    ``Channel.active_session_id`` is only the primary/default session. Channel
    surfaces may carry ``current_session_id`` when a scratch, split, or thread
    pane is focused; that explicit id wins.
    """
    if ctx.surface == "session":
        if ctx.session is None:
            raise LookupError("Session not found")
        return ctx.session

    assert ctx.channel is not None and ctx.channel_id is not None
    target_id = ctx.current_session_id or ctx.channel.active_session_id
    if target_id is None:
        raise LookupError("Channel has no current conversation")

    session = await ctx.db.get(Session, target_id)
    if session is None:
        raise LookupError("Session not found")
    if not _session_belongs_to_channel(session, ctx.channel_id):
        raise ValueError("Current session does not belong to this channel")
    return session


async def _context_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    if ctx.surface == "channel":
        session = await _resolve_current_session(ctx)
    else:
        session = ctx.session
        if session is None and ctx.session_id is not None:
            session = await ctx.db.get(Session, ctx.session_id)
    if session is None:
        raise LookupError("Session not found")
    from app.agent.bots import get_bot

    bot = get_bot(session.bot_id)
    if getattr(bot, "harness_runtime", None):
        from app.services.agent_harnesses.approvals import load_session_mode
        from app.services.agent_harnesses.session_state import (
            HARNESS_RESUME_RESET_AT_KEY,
            context_window_from_usage,
            estimate_context_remaining_pct,
            hint_preview,
            load_bridge_status,
            load_context_hints,
            load_latest_harness_metadata,
            load_native_compaction,
        )
        from app.services.agent_harnesses.settings import load_session_settings
        from app.services.agent_harnesses.tools import resolve_harness_bridge_inventory
        from app.services.agent_harnesses import HARNESS_REGISTRY

        settings = await load_session_settings(ctx.db, session.id)
        mode = await load_session_mode(ctx.db, session.id)
        hints = await load_context_hints(ctx.db, session.id)
        bridge_status = await load_bridge_status(ctx.db, session.id)
        harness_meta, last_turn_at = await load_latest_harness_metadata(ctx.db, session.id)
        runtime = HARNESS_REGISTRY.get(bot.harness_runtime)
        caps = runtime.capabilities() if runtime and hasattr(runtime, "capabilities") else None
        native_compaction = await load_native_compaction(ctx.db, session.id)
        inventory_error: str | None = None
        bridge_tool_items: list[dict[str, str]] = []
        try:
            bridge_inventory = await asyncio.wait_for(
                resolve_harness_bridge_inventory(
                    ctx.db,
                    bot_id=bot.id,
                    channel_id=session.channel_id or session.parent_channel_id,
                ),
                timeout=3.0,
            )
            bridge_tool_items = [
                {"name": spec.name, "description": spec.description}
                for spec in bridge_inventory.specs
            ]
            if bridge_inventory.errors:
                inventory_error = "; ".join(bridge_inventory.errors)
        except asyncio.TimeoutError:
            exported = bridge_status.get("exported_tools")
            if isinstance(exported, list):
                bridge_tool_items = [
                    {"name": str(name), "description": ""}
                    for name in exported
                    if isinstance(name, str) and name
                ]
            inventory_error = "live bridge inventory timed out; showing last recorded bridge status"
        except Exception as exc:
            inventory_error = f"failed to list Spindrel bridge tools: {exc}"
        reset_at = (session.metadata_ or {}).get(HARNESS_RESUME_RESET_AT_KEY)
        lines = [
            f"Harness: {bot.harness_runtime}",
            f"Model: {settings.model or 'runtime default'}",
            f"Effort: {settings.effort or 'default'}",
            f"Approval mode: {mode}",
            f"Native resume id: {(harness_meta or {}).get('session_id') or 'none'}",
            f"Pending host hints: {len(hints)}",
            f"Spindrel bridge tools: {len(bridge_tool_items)}",
            f"Bridge status: {bridge_status.get('status') or ('enabled' if bridge_tool_items else 'none_selected')}",
        ]
        if last_turn_at:
            lines.append(f"Last harness turn: {last_turn_at.isoformat()}")
        if isinstance(reset_at, str):
            lines.append(f"Last compact reset: {reset_at}")
        usage = (harness_meta or {}).get("usage") if harness_meta else None
        context_window_tokens = (
            context_window_from_usage(usage)
            or (getattr(caps, "context_window_tokens", None) if caps else None)
        )
        if usage:
            lines.append(f"Last usage: {usage}")
        remaining_pct = estimate_context_remaining_pct(
            usage,
            context_window_tokens=context_window_tokens,
        )
        if (
            remaining_pct is None
            and native_compaction
            and native_compaction.get("status") == "completed"
            and not native_compaction.get("usage")
        ):
            remaining_pct = 100.0
        if remaining_pct is not None:
            lines.append(f"Estimated context remaining: {remaining_pct}%")
        if native_compaction:
            lines.append(f"Last native compact: {native_compaction.get('status')} at {native_compaction.get('created_at')}")
        return SlashCommandResult(
            command_id="context",
            result_type="harness_context_summary",
            payload={
                "session_id": str(session.id),
                "bot_id": bot.id,
                "runtime": bot.harness_runtime,
                "model": settings.model,
                "effort": settings.effort,
                "permission_mode": mode,
                "harness_session_id": (harness_meta or {}).get("session_id") if harness_meta else None,
                "pending_hint_count": len(hints),
                "hints": [hint_preview(hint) for hint in hints],
                "bridge_tools": bridge_tool_items,
                "bridge_status": bridge_status.get("status") or ("enabled" if bridge_tool_items else "none_selected"),
                "bridge_status_detail": {
                    **bridge_status,
                    **({"inventory_errors": [inventory_error]} if inventory_error else {}),
                },
                "native_token_budget_available": remaining_pct is not None,
                "native_compaction_available": bool(getattr(caps, "native_compaction", False)) if caps else False,
                "context_window_tokens": context_window_tokens,
                "context_remaining_pct": remaining_pct,
                "last_turn_at": last_turn_at.isoformat() if last_turn_at else None,
                "last_compacted_at": reset_at if isinstance(reset_at, str) else None,
                "native_compaction": native_compaction,
                "usage": usage,
            },
            fallback_text="\n".join(lines),
        )
    return await _build_session_context_summary(session.id, ctx.db)


async def _stop_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    if ctx.surface == "channel":
        assert ctx.channel is not None and ctx.channel_id is not None
        session = await _resolve_current_session(ctx)
        return await _stop_session(
            session_id=session.id,
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
        session = await _resolve_current_session(ctx)
        return await _compact_session(
            session_id=session.id,
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
        session = await _resolve_current_session(ctx)
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

    # Phase 4: harness branch. If the channel's bot is a harness, dispatch
    # to the harness-aware path BEFORE touching channel.config — a runtime
    # without an effort knob (e.g. Claude Code in v1) returns a friendly
    # no-op and never mutates the channel-level effort_override that drives
    # the normal Spindrel loop.
    runtime = await _resolve_harness_runtime_for_bot(ctx.db, ctx.channel.bot_id)
    if runtime is not None:
        return await _harness_effort_handler(ctx=ctx, runtime=runtime)

    return await _set_channel_effort(
        channel=ctx.channel,
        channel_id=ctx.channel_id,
        args=ctx.args,
        db=ctx.db,
    )


def _harness_picker_result(
    *,
    command_id: str,
    runtime,
    session_id: uuid.UUID,
    selected_model: str | None,
    selected_effort: str | None,
) -> SlashCommandResult:
    caps = runtime.capabilities()
    model_options = [
        {
            "id": opt.id,
            "label": opt.label or opt.id,
            "effort_values": list(opt.effort_values),
            "default_effort": opt.default_effort,
        }
        for opt in getattr(caps, "model_options", ())
    ]
    if not model_options:
        model_options = [
            {
                "id": model,
                "label": model,
                "effort_values": list(caps.effort_values),
                "default_effort": None,
            }
            for model in caps.supported_models
        ]
    return SlashCommandResult(
        command_id=command_id,
        result_type="harness_model_effort_picker",
        payload={
            "session_id": str(session_id),
            "runtime": getattr(runtime, "name", None),
            "display_name": caps.display_name,
            "model_is_freeform": caps.model_is_freeform,
            "model_options": model_options,
            "selected_model": selected_model,
            "selected_effort": selected_effort,
        },
        fallback_text=(
            f"{caps.display_name} model: {selected_model or 'runtime default'}; "
            f"effort: {selected_effort or 'default'}"
        ),
    )


async def _harness_effort_handler(
    *,
    ctx: SlashCommandContext,
    runtime,
) -> SlashCommandResult:
    """Apply ``/effort <level>`` to a harness session's per-session settings.

    If the runtime declares no ``effort_values`` (Claude Code today),
    return a friendly info result without touching anything. This is the
    "discovered via typing" path; the picker/help filter hides ``/effort``
    from harness sessions on this runtime, so users won't normally see it.
    """
    from app.services.agent_harnesses.settings import patch_session_settings
    from app.services.agent_harnesses.settings import load_session_settings

    caps = runtime.capabilities() if hasattr(runtime, "capabilities") else None
    display = caps.display_name if caps else "This harness"

    if not caps or not caps.effort_values:
        payload = SideEffectPayload(
            effect="effort",
            scope_kind="channel",
            scope_id=str(ctx.channel_id),
            title="Effort not supported",
            detail=f"{display} does not expose a reasoning-effort knob.",
        )
        return _side_effect_result(payload, command_id="effort")

    level = (ctx.args[0].strip().lower() if ctx.args else "").strip()
    if not level:
        session = await _resolve_current_session(ctx)
        settings = await load_session_settings(ctx.db, session.id)
        return _harness_picker_result(
            command_id="effort",
            runtime=runtime,
            session_id=session.id,
            selected_model=settings.model,
            selected_effort=settings.effort,
        )
    if level not in caps.effort_values:
        raise ValueError(
            f"Unknown effort level {level!r}. {display} accepts: "
            f"{', '.join(caps.effort_values)}"
        )

    session = await _resolve_current_session(ctx)
    await patch_session_settings(ctx.db, session.id, patch={"effort": level})

    payload = SideEffectPayload(
        effect="effort",
        scope_kind="session",
        scope_id=str(session.id),
        title=f"Effort: {level}",
        detail=f"{display} effort set to {level} for this session.",
    )
    return _side_effect_result(payload, command_id="effort")


async def _model_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    """Set the model for this chat. Phase 4: server-handled, harness-aware.

    Harness bots → write per-session ``harness_settings.model`` (channel
    override is meaningless for harness, which uses session resume).
    Non-harness bots → write ``channel.model_override`` (was UI-only;
    centralizing here lets terminal/API callers behave identically).
    """
    from app.services.agent_harnesses.settings import (
        load_session_settings,
        patch_session_settings,
    )

    bot_id_str: str | None = None
    if ctx.channel is not None and ctx.channel.bot_id:
        bot_id_str = str(ctx.channel.bot_id)
    elif ctx.session is not None:
        bot_id_str = str(ctx.session.bot_id)

    runtime = await _resolve_harness_runtime_for_bot(ctx.db, bot_id_str)
    if runtime is not None:
        try:
            session = await _resolve_current_session(ctx)
        except LookupError:
            raise ValueError(
                "/model in a harness channel needs an active session — "
                "open or send a message to a session first, then retry"
            )
        if not ctx.args or not (ctx.args[0] or "").strip():
            settings = await load_session_settings(ctx.db, session.id)
            return _harness_picker_result(
                command_id="model",
                runtime=runtime,
                session_id=session.id,
                selected_model=settings.model,
                selected_effort=settings.effort,
            )
        raw = (ctx.args[0] or "").strip()
        try:
            await patch_session_settings(ctx.db, session.id, patch={"model": raw})
        except ValueError as exc:
            raise ValueError(f"/model: {exc}")
        caps = runtime.capabilities() if hasattr(runtime, "capabilities") else None
        display = caps.display_name if caps else "harness"
        payload = SideEffectPayload(
            effect="model",
            scope_kind="session",
            scope_id=str(session.id),
            title=f"Model: {raw}",
            detail=f"{display} model set to {raw} for this session.",
        )
        return _side_effect_result(payload, command_id="model")

    # Non-harness path: channel override.
    if not ctx.args or not (ctx.args[0] or "").strip():
        raise ValueError("/model requires one argument: <model_id>")
    raw = (ctx.args[0] or "").strip()
    if ctx.channel is None or ctx.channel_id is None:
        raise ValueError("/model requires a channel context for non-harness bots")
    if len(raw) > 256:
        raise ValueError("/model: model id exceeds 256-character limit")
    ctx.channel.model_override = raw
    await ctx.db.commit()
    payload = SideEffectPayload(
        effect="model",
        scope_kind="channel",
        scope_id=str(ctx.channel_id),
        title=f"Model: {raw}",
        detail=f"Channel model override set to {raw}.",
    )
    return _side_effect_result(payload, command_id="model")


# ============================================================================
# New handlers: /help, /find, /rename, /mode
# ============================================================================


async def _help_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    """List commands available on the current surface as a context_summary.

    Reusing the existing `context_summary` renderer means `/help` doesn't
    require a new frontend component — each command becomes a "category" row.
    """
    available = [s for s in COMMANDS.values() if ctx.surface in s.surfaces]
    scope_id = str(ctx.channel_id if ctx.surface == "channel" else ctx.session_id)
    bot_id = ""
    if ctx.channel is not None and ctx.channel.bot_id:
        bot_id = str(ctx.channel.bot_id)
    elif ctx.session is not None:
        bot_id = str(ctx.session.bot_id)

    # Phase 4: harness sessions only see commands the runtime allowlists.
    runtime = await _resolve_harness_runtime_for_bot(ctx.db, bot_id or None)
    available = _filter_specs_for_runtime(available, runtime)

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
    from app.tools.local.search_history import _build_session_query, _serialize_messages

    if ctx.surface != "channel":
        raise ValueError("/find is only available in channel scope")
    assert ctx.channel is not None and ctx.channel_id is not None

    args = list(ctx.args)
    search_all = bool(args and args[0].strip().lower() in {"--all", "-a"})
    if search_all:
        args = args[1:]
    query = " ".join(args).strip()
    if not query:
        raise ValueError("/find requires a search query")

    session_ids: list[uuid.UUID]
    current_session_id: uuid.UUID | None = None
    if search_all:
        session_ids = list((await ctx.db.execute(
            select(Session.id)
            .where(
                Session.channel_id == ctx.channel_id,
                Session.bot_id == ctx.channel.bot_id,
                Session.session_type == SESSION_TYPE_CHANNEL,
                Session.source_task_id.is_(None),
                Session.parent_session_id.is_(None),
                Session.parent_message_id.is_(None),
            )
            .order_by(Session.last_active.desc())
            .limit(200)
        )).scalars().all())
    else:
        try:
            current_session = await _resolve_current_session(ctx)
        except LookupError:
            current_session = None
        current_session_id = current_session.id if current_session else None
        session_ids = [current_session.id] if current_session else []

    stmt = _build_session_query(
        session_ids,
        query=query,
        role="all",
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
        scope_kind="channel" if search_all else "session",
        scope_id=str(ctx.channel_id if search_all else (current_session_id or ctx.channel_id)),
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
    description="Search the current session; use --all to search visible channel sessions",
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
    # Phase 4: server-handled. Harness bots write per-session harness_settings;
    # non-harness bots write channel.model_override. Header pills bypass the
    # slash command and POST to /sessions/{id}/harness-settings directly.
    handler=_model_handler,
    args=(SlashCommandArgSpec(name="model_id", source="model", required=False),),
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
    description="Set reasoning effort",
    surfaces=("channel",),
    handler=_effort_handler,
    args=(SlashCommandArgSpec(name="level", source="enum", required=False, enum=("off", "low", "medium", "high", "xhigh", "max")),),
))

_register(SlashCommandSpec(
    id="clear",
    label="/clear",
    description="Open a new session (local)",
    surfaces=("channel", "session"),
    local_only=True,
))

_register(SlashCommandSpec(
    id="new",
    label="/new",
    description="Open a new session (local)",
    surfaces=("channel", "session"),
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
    description="Switch sessions in this channel (local)",
    surfaces=("channel", "session"),
    local_only=True,
))

_register(SlashCommandSpec(
    id="split",
    label="/split",
    description="Add a session split pane (local)",
    surfaces=("channel", "session"),
    local_only=True,
))

_register(SlashCommandSpec(
    id="focus",
    label="/focus",
    description="Toggle focused chat layout (local)",
    surfaces=("channel", "session"),
    local_only=True,
))


# ============================================================================
# Public API
# ============================================================================


async def list_supported_slash_commands(
    *,
    db: AsyncSession | None = None,
    bot_id: str | None = None,
) -> list[dict]:
    """Canonical slash-command registry.

    The frontend fetches this at load time via `GET /api/v1/slash-commands`
    so there is one source of truth. Shape:

        {
            id, label, description,
            surfaces: ["channel"|"session", ...],
            local_only: bool,
            args: [{ name, source, required, enum | null }, ...]
        }

    When ``bot_id`` is given (and ``db`` is provided), the result is
    intersected with the bot's runtime slash policy if the bot is a
    harness — so harness sessions only see commands the runtime allowlists.
    Non-harness bots / no ``bot_id`` / unknown runtime → full catalog.
    """
    specs = list(COMMANDS.values())
    if bot_id is not None and db is not None:
        runtime = await _resolve_harness_runtime_for_bot(db, bot_id)
        specs = _filter_specs_for_runtime(specs, runtime)
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
        for s in specs
    ]


async def execute_slash_command(
    *,
    command_id: str,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    db: AsyncSession,
    current_session_id: uuid.UUID | None = None,
    args: list[str] | None = None,
) -> SlashCommandResult:
    if bool(channel_id) == bool(session_id):
        raise ValueError("Exactly one of channel_id or session_id is required")
    if current_session_id is not None and channel_id is None:
        raise ValueError("current_session_id is only valid with channel_id")
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
        if current_session_id is not None:
            current_session = await db.get(Session, current_session_id)
            if current_session is None:
                raise LookupError("Current session not found")
            if not _session_belongs_to_channel(current_session, channel_id):
                raise ValueError("Current session does not belong to this channel")
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
        current_session_id=current_session_id,
        args=args,
        db=db,
    )
    return await spec.handler(ctx)
