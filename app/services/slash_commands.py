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
import logging
import uuid

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.agent.context_profiles import get_context_profile, resolve_context_profile
from app.db.models import Bot as BotRow, Channel, Project, Session, Task
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
    args_text: str | None
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


def _runtime_native_command_lookup(runtime) -> dict[str, object]:
    """Map direct slash names and aliases to runtime-owned command specs."""
    if runtime is None or not hasattr(runtime, "capabilities"):
        return {}
    caps = runtime.capabilities()
    lookup: dict[str, object] = {}
    for command in getattr(caps, "native_commands", ()) or ():
        names = [getattr(command, "id", ""), *(getattr(command, "aliases", ()) or ())]
        for name in names:
            normalized = str(name or "").strip().lower()
            if normalized:
                lookup[normalized] = command
    return lookup


def _native_command_catalog_entries(runtime) -> list[dict]:
    """Build picker/help entries for runtime-native slash commands.

    These entries are intentionally not registered in ``COMMANDS`` because the
    runtime owns the set. ``execute_slash_command`` resolves them dynamically
    for harness sessions.
    """
    entries: list[dict] = []
    seen: set[str] = set()
    for slash_name, command in _runtime_native_command_lookup(runtime).items():
        if slash_name in seen or slash_name in COMMANDS:
            continue
        seen.add(slash_name)
        entries.append(
            {
                "id": slash_name,
                "label": f"/{slash_name}",
                "description": getattr(command, "description", "") or f"Run native /{slash_name}",
                "surfaces": ["channel", "session"],
                "local_only": False,
                "args": [
                    {
                        "name": "args",
                        "source": "free_text",
                        "required": False,
                        "enum": None,
                    }
                ],
                "runtime_native": True,
                "runtime_command_id": getattr(command, "id", slash_name),
                "runtime_command_readonly": bool(getattr(command, "readonly", True)),
                "runtime_command_mutability": getattr(command, "mutability", "readonly"),
                "runtime_command_interaction_kind": getattr(command, "interaction_kind", "structured"),
                "runtime_command_fallback_behavior": getattr(command, "fallback_behavior", "none"),
            }
        )
    return entries


def _session_native_slash_catalog_entries(
    metadata: dict[str, Any] | None,
    *,
    runtime,
) -> list[dict]:
    """Build picker entries from runtime-reported per-session slash inventory."""

    if not metadata:
        return []
    raw_commands = metadata.get("claude_native_slash_commands")
    if not isinstance(raw_commands, list):
        return []
    runtime_lookup = _runtime_native_command_lookup(runtime)
    entries: list[dict] = []
    seen: set[str] = set()
    for item in raw_commands:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("name")
            or item.get("command")
            or item.get("id")
            or item.get("title")
        )
        if not isinstance(name, str):
            continue
        slash_name = name.strip().lstrip("/").lower()
        if not slash_name or slash_name in seen or slash_name in COMMANDS or slash_name in runtime_lookup:
            continue
        seen.add(slash_name)
        description = item.get("description")
        entries.append(
            {
                "id": slash_name,
                "label": f"/{slash_name}",
                "description": description if isinstance(description, str) and description.strip() else f"Run native /{slash_name}",
                "surfaces": ["channel", "session"],
                "local_only": False,
                "args": [
                    {
                        "name": "args",
                        "source": "free_text",
                        "required": False,
                        "enum": None,
                    }
                ],
                "runtime_native": True,
                "runtime_command_id": slash_name,
                "runtime_command_readonly": True,
                "runtime_command_mutability": "readonly",
                "runtime_command_interaction_kind": "native_session",
                "runtime_command_fallback_behavior": "session",
            }
        )
    return entries


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
    profile = resolve_context_profile(session=session, channel=channel)
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


async def _execute_native_runtime_command(
    ctx: SlashCommandContext,
    *,
    slash_command_id: str,
    native_command_id: str,
    command_args: tuple[str, ...],
) -> SlashCommandResult:
    if ctx.surface == "channel":
        session = await _resolve_current_session(ctx)
        scope_kind: Literal["channel", "session"] = "channel"
        assert ctx.channel_id is not None
        scope_id = ctx.channel_id
    else:
        assert ctx.session is not None and ctx.session_id is not None
        session = ctx.session
        scope_kind = "session"
        scope_id = ctx.session_id

    from app.agent.bots import get_bot
    from app.services.agent_harnesses import HARNESS_REGISTRY
    from app.services.agent_harnesses.approvals import load_session_mode
    from app.services.agent_harnesses.session_state import load_latest_harness_metadata
    from app.services.agent_harnesses.settings import load_session_settings

    bot = get_bot(session.bot_id)
    runtime_name = getattr(bot, "harness_runtime", None)
    if not runtime_name:
        raise ValueError("/runtime is only available for harness-backed sessions")
    runtime = HARNESS_REGISTRY.get(runtime_name)
    if runtime is None:
        raise ValueError(f"Harness runtime {runtime_name!r} is not registered")
    native_lookup = _runtime_native_command_lookup(runtime)
    command_spec = native_lookup.get(native_command_id.strip().lower())
    if command_spec is None:
        raise ValueError(
            f"Runtime command {native_command_id!r} is not available for {runtime_name}. "
            f"Available: {', '.join(sorted(native_lookup)) or 'none'}"
        )
    command_id = str(getattr(command_spec, "id", native_command_id)).strip()
    if not hasattr(runtime, "execute_native_command"):
        raise ValueError(f"Harness runtime {runtime_name!r} does not support native commands")

    settings = await load_session_settings(ctx.db, session.id)
    mode = await load_session_mode(ctx.db, session.id)
    harness_meta, _last_turn_at = await load_latest_harness_metadata(ctx.db, session.id)
    turn_ctx = await _build_harness_turn_context_for_session(
        ctx,
        session=session,
        bot=bot,
        settings=settings,
        mode=mode,
        harness_meta=harness_meta,
    )
    requires_approval = not bool(getattr(command_spec, "readonly", True))
    classifier = getattr(runtime, "native_command_requires_approval", None)
    if callable(classifier):
        requires_approval = bool(
            classifier(command_id=command_id, args=command_args, args_text=ctx.args_text)
        )
    if requires_approval:
        from app.services.agent_harnesses.approvals import request_harness_approval

        decision = await request_harness_approval(
            ctx=turn_ctx,
            runtime=runtime,
            tool_name=f"/{command_id}",
            tool_input={
                "args": list(command_args),
                "args_text": ctx.args_text,
                "runtime_command": command_id,
            },
        )
        if not decision.allow:
            return SlashCommandResult(
                command_id=slash_command_id,
                result_type="harness_runtime_command",
                payload={
                    "runtime": runtime_name,
                    "command": command_id,
                    "status": "denied",
                    "title": "Native command denied",
                    "detail": decision.reason or "User denied this native command.",
                    "scope_kind": scope_kind,
                    "scope_id": str(scope_id),
                    "data": {},
                },
                fallback_text=decision.reason or "User denied this native command.",
            )
    result = await runtime.execute_native_command(
        command_id=command_id,
        args=command_args,
        ctx=turn_ctx,
    )
    payload = {
        "runtime": runtime_name,
        "command": result.command_id,
        "status": result.status,
        "title": result.title,
        "detail": result.detail,
        "scope_kind": scope_kind,
        "scope_id": str(scope_id),
        "data": dict(result.payload or {}),
    }
    return SlashCommandResult(
        command_id=slash_command_id,
        result_type="harness_runtime_command",
        payload=payload,
        fallback_text="\n".join(
            part for part in (
                f"{runtime_name} {result.command_id}: {result.title}",
                result.detail,
            )
            if part
        ),
    )


async def _runtime_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    if not ctx.args:
        raise ValueError("/runtime requires a whitelisted runtime command id")
    command_id = ctx.args[0].strip()
    command_args = tuple(ctx.args[1:])
    if not command_id:
        raise ValueError("/runtime requires a whitelisted runtime command id")
    return await _execute_native_runtime_command(
        ctx,
        slash_command_id="runtime",
        native_command_id=command_id,
        command_args=command_args,
    )


# ============================================================================
# Handlers — thin ctx adapters over the shared helpers above
# ============================================================================


def _session_belongs_to_channel(session: Session, channel_id: uuid.UUID) -> bool:
    return session.channel_id == channel_id or session.parent_channel_id == channel_id


async def _build_harness_turn_context_for_session(
    ctx: SlashCommandContext,
    *,
    session: Session,
    bot,
    settings,
    mode: str,
    harness_meta: dict[str, Any] | None,
):
    from app.services.agent_harnesses.context import build_turn_context
    from app.services.agent_harnesses.project import resolve_harness_paths
    from app.services.project_runtime import load_project_runtime_environment_for_id

    paths = await resolve_harness_paths(
        ctx.db,
        channel_id=session.channel_id or session.parent_channel_id,
        bot=bot,
    )
    runtime_env = None
    work_surface = getattr(paths, "work_surface", None)
    from app.services.projects import is_project_like_surface

    if is_project_like_surface(work_surface) and work_surface.project_id:
        runtime_env = await load_project_runtime_environment_for_id(ctx.db, work_surface.project_id)
    return build_turn_context(
        spindrel_session_id=session.id,
        bot_id=bot.id,
        turn_id=uuid.uuid4(),
        channel_id=session.channel_id or session.parent_channel_id,
        workdir=paths.workdir,
        env=dict(runtime_env.env) if runtime_env is not None else None,
        harness_session_id=(harness_meta or {}).get("session_id") if harness_meta else None,
        permission_mode=mode,
        model=settings.model,
        effort=settings.effort,
        runtime_settings=settings.runtime_settings,
        session_plan_mode=get_session_plan_mode(session),
        harness_metadata=harness_meta or {},
    )


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
        from app.services.agent_harnesses import HARNESS_REGISTRY
        from app.services.agent_harnesses.base import HarnessRuntimeCommandResult
        from app.services.agent_harnesses.session_state import load_latest_harness_metadata
        from app.services.agent_harnesses.settings import load_session_settings

        settings = await load_session_settings(ctx.db, session.id)
        mode = await load_session_mode(ctx.db, session.id)
        harness_meta, _last_turn_at = await load_latest_harness_metadata(ctx.db, session.id)
        runtime = HARNESS_REGISTRY.get(bot.harness_runtime)
        if runtime is None:
            native_result = HarnessRuntimeCommandResult(
                command_id="context",
                title="Native /context unavailable",
                detail=f"Harness runtime {bot.harness_runtime!r} is not registered.",
                status="error",
            )
        else:
            try:
                turn_ctx = await _build_harness_turn_context_for_session(
                    ctx,
                    session=session,
                    bot=bot,
                    settings=settings,
                    mode=mode,
                    harness_meta=harness_meta,
                )
                if hasattr(runtime, "context_status"):
                    native_result = await runtime.context_status(ctx=turn_ctx)
                else:
                    native_result = await runtime.execute_native_command(
                        command_id="context",
                        args=tuple(ctx.args),
                        ctx=turn_ctx,
                    )
            except Exception as exc:
                logger.exception("harness native /context failed for %s", bot.harness_runtime)
                native_result = HarnessRuntimeCommandResult(
                    command_id="context",
                    title="Native /context failed",
                    detail=str(exc),
                    status="error",
                )
        if ctx.surface == "channel":
            scope_kind: Literal["channel", "session"] = "channel"
            scope_id = str(ctx.channel_id or session.channel_id or session.parent_channel_id)
        else:
            scope_kind = "session"
            scope_id = str(ctx.session_id or session.id)
        payload = {
            "runtime": bot.harness_runtime,
            "command": native_result.command_id,
            "status": native_result.status,
            "title": native_result.title,
            "detail": native_result.detail,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "data": dict(native_result.payload or {}),
        }
        return SlashCommandResult(
            command_id="context",
            result_type="harness_runtime_command",
            payload=payload,
            fallback_text="\n".join(
                part for part in (
                    f"{bot.harness_runtime} {native_result.command_id}: {native_result.title}",
                    native_result.detail,
                )
                if part
            ),
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
    # Phase 4: harness branch. If the channel's bot is a harness, dispatch
    # to the harness-aware path BEFORE touching channel.config — a runtime
    # without an effort knob (e.g. Claude Code in v1) returns a friendly
    # no-op and never mutates the channel-level effort_override that drives
    # the normal Spindrel loop.
    bot_id_str: str | None = None
    if ctx.channel is not None and ctx.channel.bot_id:
        bot_id_str = str(ctx.channel.bot_id)
    elif ctx.session is not None:
        bot_id_str = str(ctx.session.bot_id)
    runtime = await _resolve_harness_runtime_for_bot(ctx.db, bot_id_str)
    if runtime is not None:
        return await _harness_effort_handler(ctx=ctx, runtime=runtime)

    if ctx.surface != "channel":
        raise ValueError("/effort is a channel setting; not available on non-harness sessions")
    assert ctx.channel is not None and ctx.channel_id is not None
    return await _set_channel_effort(
        channel=ctx.channel,
        channel_id=ctx.channel_id,
        args=ctx.args,
        db=ctx.db,
    )


async def _harness_picker_result(
    *,
    command_id: str,
    runtime,
    session_id: uuid.UUID,
    selected_model: str | None,
    selected_effort: str | None,
) -> SlashCommandResult:
    from app.services.agent_harnesses.capabilities import resolve_runtime_model_surface

    surface = await resolve_runtime_model_surface(runtime)
    caps = surface.caps
    model_options = [
        {
            "id": opt.id,
            "label": opt.label or opt.id,
            "effort_values": list(opt.effort_values),
            "default_effort": opt.default_effort,
        }
        for opt in surface.model_options
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
        scope_kind: Literal["channel", "session"] = ctx.surface
        scope_id = ctx.channel_id if ctx.surface == "channel" else ctx.session_id
        payload = SideEffectPayload(
            effect="effort",
            scope_kind=scope_kind,
            scope_id=str(scope_id),
            title="Effort not supported",
            detail=f"{display} does not expose a reasoning-effort knob.",
        )
        return _side_effect_result(payload, command_id="effort")

    level = (ctx.args[0].strip().lower() if ctx.args else "").strip()
    if not level:
        session = await _resolve_current_session(ctx)
        settings = await load_session_settings(ctx.db, session.id)
        return await _harness_picker_result(
            command_id="effort",
            runtime=runtime,
            session_id=session.id,
            selected_model=settings.model,
            selected_effort=settings.effort,
        )
    session = await _resolve_current_session(ctx)
    settings = await load_session_settings(ctx.db, session.id)
    from app.services.agent_harnesses.capabilities import resolve_runtime_model_surface

    surface = await resolve_runtime_model_surface(runtime)
    by_model = {option.id: tuple(option.effort_values or ()) for option in surface.model_options}
    accepted = by_model.get(settings.model or "") or tuple(surface.effort_values)
    if level not in accepted:
        raise ValueError(
            f"Unknown effort level {level!r}. {display} accepts: "
            f"{', '.join(accepted)}"
        )

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
            return await _harness_picker_result(
                command_id="model",
                runtime=runtime,
                session_id=session.id,
                selected_model=settings.model,
                selected_effort=settings.effort,
            )
        raw = (ctx.args[0] or "").strip()
        if raw.lower() == "clear":
            await patch_session_settings(ctx.db, session.id, patch={"model": None})
            caps = runtime.capabilities() if hasattr(runtime, "capabilities") else None
            display = caps.display_name if caps else "harness"
            payload = SideEffectPayload(
                effect="model",
                scope_kind="session",
                scope_id=str(session.id),
                title="Model cleared",
                detail=f"{display} model override cleared for this session.",
            )
            return _side_effect_result(payload, command_id="model")
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
    if ctx.channel is None or ctx.channel_id is None:
        raise ValueError("/model requires a channel context for non-harness bots")
    if not ctx.args or not (ctx.args[0] or "").strip():
        detail = (
            f"Channel model override: {ctx.channel.model_override}"
            if ctx.channel.model_override
            else "No channel model override set. Using the bot default model."
        )
        payload = SideEffectPayload(
            effect="model",
            scope_kind="channel",
            scope_id=str(ctx.channel_id),
            title="Model override",
            detail=detail,
        )
        return _side_effect_result(payload, command_id="model")
    raw = (ctx.args[0] or "").strip()
    if raw.lower() == "clear":
        ctx.channel.model_override = None
        ctx.channel.model_provider_id_override = None
        await ctx.db.commit()
        payload = SideEffectPayload(
            effect="model",
            scope_kind="channel",
            scope_id=str(ctx.channel_id),
            title="Model cleared",
            detail="Channel model override cleared. Using the bot default model.",
        )
        return _side_effect_result(payload, command_id="model")
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
    native_entries = _native_command_catalog_entries(runtime)

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
    categories.extend(
        ContextSummaryCategory(
            key=str(entry["id"]),
            label=str(entry["label"]),
            tokens_approx=0,
            percentage=0.0,
            description=str(entry["description"]),
        )
        for entry in native_entries
    )
    payload = ContextSummaryPayload(
        scope_kind=ctx.surface,
        scope_id=scope_id,
        session_id=str(ctx.session_id) if ctx.session_id else None,
        bot_id=bot_id,
        title="Available commands",
        headline=f"{len(categories)} slash commands available here",
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


async def _project_init_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    channel = ctx.channel
    if channel is None and ctx.session is not None:
        parent_channel_id = ctx.session.channel_id or ctx.session.parent_channel_id
        channel = await ctx.db.get(Channel, parent_channel_id) if parent_channel_id else None
    project: Project | None = None
    if channel is not None and channel.project_id is not None:
        project = await ctx.db.get(Project, channel.project_id)

    if project is None:
        title = "Project init needs a Project-bound channel"
        prompt = (
            "This channel is not attached to a Project yet. Attach the channel "
            "to a Project from Project settings or create a Project for the repo, "
            "then run /project-init again."
        )
        status = "blocked"
        project_payload: dict[str, Any] | None = None
    else:
        title = f"Initialize Project: {project.name}"
        status = "ready"
        project_payload = {
            "id": str(project.id),
            "name": project.name,
            "root_path": project.root_path,
            "applied_blueprint_id": str(project.applied_blueprint_id) if project.applied_blueprint_id else None,
        }
        prompt = f"""Initialize this Project for agent work.

Project:
- id: {project.id}
- root: {project.root_path}

Use the project/setup/init skill.

Do this end to end:
1. Inspect the Project root as a normal checkout. Read repo instructions, setup docs, env examples, compose files, test scripts, and child git remotes.
2. Create or update `.spindrel/WORKFLOW.md` as the repo-owned Project workflow contract: artifact homes, branch policy, test commands, dependency stack usage, dev targets, screenshot/e2e expectations, receipt evidence, and GitHub/Linear handoff rules.
3. Check Project readiness with the Project APIs/tools: setup, runtime env, dependency stack, attached channels, and enrolled skills.
4. If there is no applied Blueprint, create one from the current Project and apply it.
5. Sanitize Blueprint repo declarations: no tokens in remote URLs, correct repo paths, intended base branches.
6. Enroll the Project workflow skills needed by the attached channels: project, project/intake, project/runs/implement, workspace/docker_stacks, and agent_readiness/operator when relevant.
7. If the repo needs Docker-backed services, configure a Project Dependency Stack from a Project-local compose file for backing services only. Do not put the app server in the stack; agents should start app/dev servers from source on assigned or unused ports.
8. Declare runtime env keys, required secret slots, setup commands, and dev targets only when the repo evidence supports them.
9. Re-check readiness and report exactly what changed, what is ready, and what still needs a user decision.
"""

    payload = {
        "status": status,
        "title": title,
        "project": project_payload,
        "prompt": prompt,
        "skill_id": "project/setup/init",
        "api_hints": [
            "GET /api/v1/projects",
            "POST /api/v1/projects/{project_id}/blueprint-from-current",
            "GET /api/v1/projects/{project_id}/setup",
            "GET /api/v1/projects/{project_id}/runtime-env",
            "GET /api/v1/projects/{project_id}/dependency-stack",
            "GET /api/v1/admin/channels/{channel_id}/enrolled-skills",
        ],
    }
    return SlashCommandResult(
        command_id="project-init",
        result_type="project_init_prompt",
        payload=payload,
        fallback_text=prompt,
    )


async def _project_status_handler(ctx: SlashCommandContext) -> SlashCommandResult:
    """Render a copyable prompt that drives the agent through the project skill
    cluster's first-action: read the factory state + orchestration policy and
    report the stage in plain language. Mirrors `/project-init` shape so the
    UI can render a single prompt-card for both."""
    channel = ctx.channel
    if channel is None and ctx.session is not None:
        parent_channel_id = ctx.session.channel_id or ctx.session.parent_channel_id
        channel = await ctx.db.get(Channel, parent_channel_id) if parent_channel_id else None
    project: Project | None = None
    if channel is not None and channel.project_id is not None:
        project = await ctx.db.get(Project, channel.project_id)

    if project is None:
        title = "Project status needs a Project-bound channel"
        prompt = (
            "This channel is not attached to a Project yet. Attach the channel "
            "to a Project from Project settings, then run /project-status again."
        )
        status = "blocked"
        project_payload: dict[str, Any] | None = None
    else:
        title = f"Project status: {project.name}"
        status = "ready"
        project_payload = {
            "id": str(project.id),
            "name": project.name,
            "root_path": project.root_path,
        }
        prompt = f"""Report the current status of this Project.

Project:
- id: {project.id}
- root: {project.root_path}

Use the project skill cluster's first-action exactly:
1. Call `get_project_factory_state` and tell me the `current_stage` in one sentence of plain language.
2. Call `get_project_orchestration_policy` and tell me whether the concurrency cap is saturated, with `in_flight` / `cap` / `headroom`.
3. List the suggested next action from the factory state's `suggested_next_action`.
4. List counts of: pending intake, proposed Run Packs, ready_for_review runs, in_flight runs, runs in the last 24h.
5. End with one short bullet list of what I can ask for next given the current stage. Do not load any other skill or take any action - this is a read-only status pass.
"""

    payload = {
        "status": status,
        "title": title,
        "project": project_payload,
        "prompt": prompt,
        "skill_id": "project",
        "api_hints": [
            "GET /api/v1/projects/{project_id}/factory-state",
            "GET /api/v1/projects/{project_id}/orchestration-policy",
        ],
    }
    return SlashCommandResult(
        command_id="project-status",
        result_type="project_init_prompt",
        payload=payload,
        fallback_text=prompt,
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
    channel = ctx.channel
    channel_id = ctx.channel_id
    if ctx.surface == "session":
        if ctx.session is None:
            raise LookupError("Session not found")
        channel_id = ctx.session.channel_id or ctx.session.parent_channel_id
        if channel_id is None:
            raise ValueError("/style is only available for sessions inside a channel")
        channel = await ctx.db.get(Channel, channel_id)
        if channel is None:
            raise LookupError("Channel not found")
    assert channel is not None and channel_id is not None

    current = (channel.config or {}).get("chat_mode", "default")
    if ctx.args:
        target = ctx.args[0].strip().lower()
        if target not in CHAT_MODES:
            raise ValueError(
                f"Unknown chat mode {target!r}. Must be one of: {', '.join(CHAT_MODES)}"
            )
    else:
        target = "terminal" if current == "default" else "default"

    cfg = _copy.deepcopy(channel.config or {})
    if target == "default":
        cfg.pop("chat_mode", None)
    else:
        cfg["chat_mode"] = target
    channel.config = cfg
    flag_modified(channel, "config")
    await ctx.db.commit()

    payload = SideEffectPayload(
        effect="style",
        scope_kind="channel",
        scope_id=str(channel_id),
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
    id="project-init",
    label="/project-init",
    description="Show a Project initialization prompt for Blueprint, skills, dependency stack, and readiness setup",
    surfaces=("channel", "session"),
    handler=_project_init_handler,
))

_register(SlashCommandSpec(
    id="project-status",
    label="/project-status",
    description="Show this Project's current stage, concurrency cap, suggested next action, and what to ask for next",
    surfaces=("channel", "session"),
    handler=_project_status_handler,
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
    surfaces=("channel", "session"),
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
    id="runtime",
    label="/runtime",
    description="Run a whitelisted native harness command",
    surfaces=("channel", "session"),
    handler=_runtime_handler,
    args=(SlashCommandArgSpec(name="command", source="free_text", required=True),),
))

_register(SlashCommandSpec(
    id="effort",
    label="/effort",
    description="Set reasoning effort",
    surfaces=("channel", "session"),
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
    session_id: uuid.UUID | None = None,
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
    native_entries: list[dict] = []
    if bot_id is not None and db is not None:
        runtime = await _resolve_harness_runtime_for_bot(db, bot_id)
        specs = _filter_specs_for_runtime(specs, runtime)
        native_entries = _native_command_catalog_entries(runtime)
        if runtime is not None and session_id is not None:
            from app.services.agent_harnesses.session_state import load_latest_harness_metadata

            harness_meta, _ = await load_latest_harness_metadata(db, session_id)
            native_entries.extend(
                _session_native_slash_catalog_entries(harness_meta, runtime=runtime)
            )
    entries = [
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
    return entries + native_entries


async def execute_slash_command(
    *,
    command_id: str,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    db: AsyncSession,
    current_session_id: uuid.UUID | None = None,
    args: list[str] | None = None,
    args_text: str | None = None,
) -> SlashCommandResult:
    if bool(channel_id) == bool(session_id):
        raise ValueError("Exactly one of channel_id or session_id is required")
    if current_session_id is not None and channel_id is None:
        raise ValueError("current_session_id is only valid with channel_id")
    args = list(args or [])
    args_text = args_text if args_text is not None else " ".join(args)

    surface: Literal["channel", "session"] = (
        "channel" if channel_id is not None else "session"
    )

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

    spec = COMMANDS.get(command_id)
    ctx = SlashCommandContext(
        command_id=command_id,
        surface=surface,
        channel=channel,
        session=session,
        channel_id=channel_id,
        session_id=session_id,
        current_session_id=current_session_id,
        args=args,
        args_text=args_text,
        db=db,
    )
    if spec is None:
        bot_id: str | None = None
        if channel is not None and channel.bot_id:
            bot_id = str(channel.bot_id)
        elif session is not None:
            bot_id = str(session.bot_id)
        runtime = await _resolve_harness_runtime_for_bot(db, bot_id)
        native_lookup = _runtime_native_command_lookup(runtime)
        native_spec = native_lookup.get(command_id.strip().lower())
        if native_spec is None:
            raise ValueError(f"Unsupported slash command: {command_id}")
        return await _execute_native_runtime_command(
            ctx,
            slash_command_id=command_id,
            native_command_id=str(getattr(native_spec, "id", command_id)),
            command_args=tuple(args),
        )

    if spec.local_only:
        raise ValueError(
            f"Command {command_id!r} is client-only and should not be executed via the backend"
        )
    if spec.handler is None:
        raise ValueError(f"Command {command_id!r} has no backend handler")
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

    return await spec.handler(ctx)
