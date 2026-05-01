import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.agent.bots import BotConfig
from app.agent.context_pruning import STICKY_TOOL_NAMES
from app.agent.hooks import HookContext, fire_hook
from app.agent.loop_cycle_detection import make_signature
from app.agent.loop_helpers import _append_transcript_tool_entry
from app.agent.loop_state import LoopDispatchState, LoopRunContext, LoopRunState
from app.agent.message_utils import _event_with_compaction_tag
from app.agent.tracing import _trace
from app.agent.tool_dispatch import ToolCallResult, dispatch_tool_call, enforce_turn_aggregate_cap
from app.config import settings
from app.services import session_locks
from app.tools.client_tools import is_client_tool
from app.tools.registry import get_tool_safety_tier
from app.utils import safe_create_task

logger = logging.getLogger(__name__)


_PARALLEL_UNSAFE_TIERS = {"mutating", "exec_capable", "control_plane"}
_READ_ONLY_CACHEABLE_TOOLS = {
    "get_memory_file",
    "search_memory",
    "read_conversation_history",
    "read_sub_session",
    "search_workspace",
    "search_channel_archive",
    "search_channel_workspace",
    "search_channel_knowledge",
    "search_bot_knowledge",
    "sonarr_queue",
    "radarr_queue",
    "sonarr_calendar",
    "qbit_torrents",
    "arr_heartbeat_snapshot",
    "jellyfin_library",
    "jellyfin_now_playing",
    "jellyseerr_requests",
    "prowlarr_search",
    "sonarr_wanted",
    "sonarr_indexers",
    "sonarr_quality_profiles",
    "frigate_list_cameras",
    "frigate_get_events",
}


def _tool_calls_are_parallel_safe(tool_calls: list[dict[str, Any]]) -> bool:
    for tc in tool_calls:
        name = tc["function"]["name"]
        if get_tool_safety_tier(name) in _PARALLEL_UNSAFE_TIERS:
            return False
    return True


def _tool_call_cache_key(tc: dict[str, Any]) -> Any:
    return make_signature(tc["function"]["name"], tc["function"]["arguments"])


def _tool_call_is_cacheable(name: str, args: Any = None) -> bool:
    if name == "file":
        parsed = _parse_tool_args(args)
        operation = parsed.get("operation") if isinstance(parsed, dict) else None
        return operation in {None, "read", "history"}
    if name == "memory":
        parsed = _parse_tool_args(args)
        action = parsed.get("action") if isinstance(parsed, dict) else None
        return action in {None, "get", "list", "search", "read"}
    return name in _READ_ONLY_CACHEABLE_TOOLS or get_tool_safety_tier(name) == "read_only"


def _tool_batch_has_cache_pressure(tool_calls: list[dict[str, Any]], state: LoopRunState) -> bool:
    seen: set[Any] = set()
    for tc in tool_calls:
        name = tc["function"]["name"]
        if not _tool_call_is_cacheable(name, tc["function"].get("arguments")):
            continue
        key = _tool_call_cache_key(tc)
        if key in seen or key in state.tool_result_cache:
            return True
        seen.add(key)
    return False


def _parse_tool_args(args: Any) -> Any:
    """Normalize the raw ``tc["function"]["arguments"]`` payload.

    The loop dispatch sees a JSON-string coming back from the LLM, while
    local paths may already hold a dict. Return the parsed value or None
    on malformed JSON. Used by sticky detection helpers below.
    """
    if isinstance(args, str):
        try:
            return json.loads(args)
        except (TypeError, ValueError):
            return None
    return args


def _is_tool_id_refetch(args: Any) -> bool:
    """True when a read_conversation_history call targets a prior tool result
    by ID (section="tool:<uuid>")."""
    parsed = _parse_tool_args(args)
    if not isinstance(parsed, dict):
        return False
    section = parsed.get("section")
    if not isinstance(section, str):
        return False
    return section.strip().lower().startswith("tool:")


def _is_skill_get(args: Any) -> bool:
    """True when a manage_bot_skill call is the read-only ``action="get"`` path.

    Skill bodies returned via ``manage_bot_skill(action="get", ...)`` are
    reference material the bot keeps consulting — same justification as
    ``get_skill`` in ``STICKY_TOOL_NAMES``. Covers both single-name and
    batch (``names=[...]``) variants.
    """
    parsed = _parse_tool_args(args)
    if not isinstance(parsed, dict):
        return False
    action = parsed.get("action")
    return isinstance(action, str) and action.strip().lower() == "get"


@dataclass(frozen=True)
class SummarizeSettings:
    enabled: bool
    threshold: int
    model: str
    max_tokens: int
    exclude: frozenset[str]


def _make_dispatch_kwargs(
    *,
    name: str,
    args: str,
    tool_call_id: str,
    bot: BotConfig,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    iteration: int,
    provider_id: str | None,
    summarize_settings: SummarizeSettings,
    compaction: bool,
    skip_policy: bool,
    effective_allowed: set[str] | None,
    existing_record_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "name": name,
        "args": args,
        "tool_call_id": tool_call_id,
        "bot_id": bot.id,
        "bot_memory": bot.memory,
        "session_id": session_id,
        "client_id": client_id,
        "correlation_id": correlation_id,
        "channel_id": channel_id,
        "iteration": iteration,
        "provider_id": provider_id,
        "summarize_enabled": summarize_settings.enabled,
        "summarize_threshold": summarize_settings.threshold,
        "summarize_model": summarize_settings.model,
        "summarize_max_tokens": summarize_settings.max_tokens,
        "summarize_exclude": set(summarize_settings.exclude),
        "compaction": compaction,
        "skip_policy": skip_policy,
        "allowed_tool_names": effective_allowed,
    }
    if existing_record_id is not None:
        kwargs["existing_record_id"] = existing_record_id
    return kwargs


async def _dispatch_tool(
    *,
    name: str,
    args: str,
    tool_call_id: str,
    bot: BotConfig,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    iteration: int,
    provider_id: str | None,
    summarize_settings: SummarizeSettings,
    compaction: bool,
    skip_policy: bool,
    effective_allowed: set[str] | None,
    dispatch_tool_call_fn: Any,
    existing_record_id: uuid.UUID | None = None,
) -> ToolCallResult:
    return await dispatch_tool_call_fn(**_make_dispatch_kwargs(
        name=name,
        args=args,
        tool_call_id=tool_call_id,
        bot=bot,
        session_id=session_id,
        client_id=client_id,
        correlation_id=correlation_id,
        channel_id=channel_id,
        iteration=iteration,
        provider_id=provider_id,
        summarize_settings=summarize_settings,
        compaction=compaction,
        skip_policy=skip_policy,
        effective_allowed=effective_allowed,
        existing_record_id=existing_record_id,
    ))


async def resolve_approval_verdict(
    approval_id: str,
    *,
    timeout_seconds: int,
) -> str:
    """Await approval resolution, expiring pending rows and reconciling DB truth."""
    from app.agent.approval_pending import cancel_approval, create_approval_pending
    from app.db.engine import async_session as _ap_session
    from app.db.models import ToolApproval as _TA, ToolCall as _TC

    future = create_approval_pending(approval_id)
    try:
        return await asyncio.wait_for(future, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        cancel_approval(approval_id)
        async with _ap_session() as approval_db:
            approval_row = await approval_db.get(_TA, uuid.UUID(approval_id))
            if approval_row is None:
                return "expired"
            if approval_row.status == "pending":
                approval_row.status = "expired"
                if approval_row.tool_call_id:
                    tool_call_row = await approval_db.get(_TC, approval_row.tool_call_id)
                    if tool_call_row and tool_call_row.status == "awaiting_approval":
                        tool_call_row.status = "expired"
                        tool_call_row.completed_at = datetime.now(timezone.utc)
                await approval_db.commit()
                return "expired"
            return str(approval_row.status)


async def _process_tool_call_result(
    *,
    tc: dict,
    tc_result: ToolCallResult,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    provider_id: str | None,
    summarize_settings: SummarizeSettings,
    effective_allowed: set[str] | None,
    dispatch_tool_call_fn: Any,
) -> AsyncGenerator[dict[str, Any], None]:
    bot = ctx.bot
    name = tc["function"]["name"]
    args = tc["function"]["arguments"]

    if tc_result.needs_approval:
        approval_event = {
            "type": "approval_request",
            "approval_id": tc_result.approval_id,
            "tool": name,
            "arguments": args,
            "reason": tc_result.approval_reason,
        }
        capability = tc_result.tool_event.get("_capability") if tc_result.tool_event else None
        if capability:
            approval_event["capability"] = capability
        yield _event_with_compaction_tag(approval_event, ctx.compaction)
        try:
            verdict = await resolve_approval_verdict(
                tc_result.approval_id,
                timeout_seconds=tc_result.approval_timeout,
            )
        except Exception:
            logger.warning(
                "Failed to reconcile approval %s after timeout",
                tc_result.approval_id,
                exc_info=True,
            )
            verdict = "expired"
        if verdict == "approved":
            tc_result = await _dispatch_tool(
                name=name,
                args=args,
                tool_call_id=tc["id"],
                bot=bot,
                session_id=ctx.session_id,
                client_id=ctx.client_id,
                correlation_id=ctx.correlation_id,
                channel_id=ctx.channel_id,
                iteration=iteration,
                provider_id=provider_id,
                summarize_settings=summarize_settings,
                compaction=ctx.compaction,
                skip_policy=True,
                effective_allowed=effective_allowed,
                dispatch_tool_call_fn=dispatch_tool_call_fn,
                existing_record_id=tc_result.record_id,
            )
        else:
            tc_result.result_for_llm = json.dumps({"error": f"Tool call {verdict} by admin"})
            tc_result.tool_event = {"type": "tool_result", "tool": name, "error": f"Tool call {verdict}"}
        yield _event_with_compaction_tag({
            "type": "approval_resolved",
            "approval_id": tc_result.approval_id,
            "tool": name,
            "verdict": verdict,
        }, ctx.compaction)

    state.tool_calls_made.append(name)
    tc_result.envelope.tool_call_id = tc["id"]
    state.tool_envelopes_made.append(tc_result.envelope.compact_dict())
    state.tool_call_trace.append(make_signature(name, args))
    for pre_event in tc_result.pre_events:
        yield pre_event
    if tc_result.embedded_client_action is not None:
        state.embedded_client_actions.append(tc_result.embedded_client_action)
    if tc_result.injected_images:
        state.iteration_injected_images.extend(tc_result.injected_images)

    cache_key = make_signature(name, args)
    if (
        _tool_call_is_cacheable(name, args)
        and not tc_result.needs_approval
        and not tc_result.tool_event.get("error")
        and tc_result.result_for_llm is not None
    ):
        state.tool_result_cache[cache_key] = tc_result.result_for_llm

    tool_message: dict[str, Any] = {
        "role": "tool",
        "tool_call_id": tc["id"],
        "content": tc_result.result_for_llm,
    }
    if tc_result.record_id is not None:
        tool_message["_tool_record_id"] = str(tc_result.record_id)
    if name in STICKY_TOOL_NAMES:
        tool_message["_no_prune"] = True
    elif name == "read_conversation_history" and _is_tool_id_refetch(args):
        # When used to hydrate a prior tool result by ID (section="tool:<uuid>"),
        # mark the rehydrated result sticky so the next pruning pass doesn't
        # strip it again. Otherwise models loop: prune → re-fetch → prune.
        tool_message["_no_prune"] = True
    elif name == "manage_bot_skill" and _is_skill_get(args):
        # manage_bot_skill(action="get") returns skill bodies — same reference
        # material as get_skill(), which is already in STICKY_TOOL_NAMES. Keep
        # across prune cycles so hygiene / skill-review bots don't refetch.
        tool_message["_no_prune"] = True
    state.messages.append(tool_message)
    yield _event_with_compaction_tag(tc_result.tool_event, ctx.compaction)

    if (
        bot.id
        and name not in STICKY_TOOL_NAMES
        and not tc_result.needs_approval
        and not tc_result.tool_event.get("error")
    ):
        state.tools_to_enroll.append(name)

    safe_create_task(fire_hook("after_tool_call", HookContext(
        bot_id=bot.id, session_id=ctx.session_id, channel_id=ctx.channel_id,
        client_id=ctx.client_id, correlation_id=ctx.correlation_id,
        extra={"tool_name": name, "tool_args": args, "duration_ms": tc_result.duration_ms},
    )))


async def dispatch_iteration_tool_calls(
    *,
    accumulated_tool_calls: list[dict[str, Any]],
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    provider_id: str | None,
    summarize_settings: SummarizeSettings,
    skip_tool_policy: bool,
    effective_allowed: set[str] | None,
    settings_obj: Any,
    session_lock_manager: Any,
    dispatch_tool_call_fn: Any = dispatch_tool_call,
    is_client_tool_fn: Any = is_client_tool,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run all tool calls for one iteration."""
    bot = ctx.bot
    state.iteration_injected_images.clear()

    has_client_tool = any(
        is_client_tool_fn(tc["function"]["name"]) for tc in accumulated_tool_calls
    )
    use_parallel = (
        settings_obj.PARALLEL_TOOL_EXECUTION
        and len(accumulated_tool_calls) >= 2
        and not has_client_tool
        and _tool_calls_are_parallel_safe(accumulated_tool_calls)
        and not _tool_batch_has_cache_pressure(accumulated_tool_calls, state)
    )

    if use_parallel:
        if ctx.session_id and session_lock_manager.is_cancel_requested(ctx.session_id):
            logger.info("Cancellation requested for session %s (before parallel batch)", ctx.session_id)
            for remaining_tc in accumulated_tool_calls:
                state.messages.append({
                    "role": "tool",
                    "tool_call_id": remaining_tc["id"],
                    "content": "[Cancelled by user]",
                })
            yield _event_with_compaction_tag({"type": "cancelled"}, ctx.compaction)
            return

        for tc in accumulated_tool_calls:
            name = tc["function"]["name"]
            args = tc["function"]["arguments"]
            _append_transcript_tool_entry(state.transcript_entries, tc["id"])
            logger.info("Tool call: %s", name)
            logger.debug("Tool call %s args: %s", name, args)
            _trace("→ %s", name)
            yield _event_with_compaction_tag({
                "type": "tool_start",
                "tool": name,
                "args": args,
                "tool_call_id": tc["id"],
            }, ctx.compaction)

        sem = asyncio.Semaphore(settings_obj.PARALLEL_TOOL_MAX_CONCURRENT)

        async def _dispatch_one(tc: dict) -> tuple[dict, ToolCallResult, bool]:
            async with sem:
                if ctx.session_id and session_lock_manager.is_cancel_requested(ctx.session_id):
                    return (tc, ToolCallResult(
                        result_for_llm="[Cancelled by user]",
                        tool_event={"type": "tool_result", "tool": tc["function"]["name"], "result": "[Cancelled by user]"},
                    ), True)
                try:
                    return (tc, await _dispatch_tool(
                        name=tc["function"]["name"],
                        args=tc["function"]["arguments"],
                        tool_call_id=tc["id"],
                        bot=bot,
                        session_id=ctx.session_id,
                        client_id=ctx.client_id,
                        correlation_id=ctx.correlation_id,
                        channel_id=ctx.channel_id,
                        iteration=iteration,
                        provider_id=provider_id,
                        summarize_settings=summarize_settings,
                        compaction=ctx.compaction,
                        skip_policy=skip_tool_policy,
                        effective_allowed=effective_allowed,
                        dispatch_tool_call_fn=dispatch_tool_call_fn,
                    ), False)
                except Exception:
                    tool_name = tc["function"]["name"]
                    logger.exception("Unhandled error dispatching tool %s in parallel batch", tool_name)
                    error_message = json.dumps({"error": f"Internal error dispatching {tool_name}"})
                    return (tc, ToolCallResult(
                        result=error_message,
                        result_for_llm=error_message,
                        tool_event={"type": "tool_result", "tool": tool_name, "error": f"Internal error dispatching {tool_name}"},
                    ), False)

        parallel_results: list[tuple[dict, ToolCallResult, bool]] = await asyncio.gather(
            *[_dispatch_one(tc) for tc in accumulated_tool_calls],
        )

        aggregate_cap = getattr(settings_obj, "TOOL_TURN_AGGREGATE_CAP_CHARS", 0)
        if isinstance(aggregate_cap, (int, float)) and aggregate_cap > 0:
            trim_targets = [
                result for _tc, result, was_cancelled in parallel_results if not was_cancelled
            ]
            trimmed_chars = enforce_turn_aggregate_cap(trim_targets, aggregate_cap)
            if trimmed_chars:
                logger.warning(
                    "turn_aggregate_cap_hit bot=%s session=%s trimmed_chars=%d cap=%d tools=%s",
                    bot.id, ctx.session_id, trimmed_chars, aggregate_cap,
                    [tc["function"]["name"] for tc, _, _ in parallel_results],
                )

        cancelled_during_parallel = False
        for tc, tc_result, was_cancelled in parallel_results:
            if was_cancelled:
                cancelled_during_parallel = True

            if cancelled_during_parallel:
                state.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": "[Cancelled by user]",
                })
                continue

            async for event in _process_tool_call_result(
                tc=tc,
                tc_result=tc_result,
                ctx=ctx,
                state=state,
                iteration=iteration,
                provider_id=provider_id,
                summarize_settings=summarize_settings,
                effective_allowed=effective_allowed,
                dispatch_tool_call_fn=dispatch_tool_call_fn,
            ):
                yield event

        if cancelled_during_parallel:
            yield _event_with_compaction_tag({"type": "cancelled"}, ctx.compaction)
            return

    else:
        for index, tc in enumerate(accumulated_tool_calls):
            if ctx.session_id and session_lock_manager.is_cancel_requested(ctx.session_id):
                logger.info(
                    "Cancellation requested for session %s (before tool %s)",
                    ctx.session_id,
                    tc["function"]["name"],
                )
                for remaining_tc in accumulated_tool_calls[index:]:
                    state.messages.append({
                        "role": "tool",
                        "tool_call_id": remaining_tc["id"],
                        "content": "[Cancelled by user]",
                    })
                yield _event_with_compaction_tag({"type": "cancelled"}, ctx.compaction)
                return

            name = tc["function"]["name"]
            args = tc["function"]["arguments"]
            _append_transcript_tool_entry(state.transcript_entries, tc["id"])
            logger.info("Tool call: %s", name)
            logger.debug("Tool call %s args: %s", name, args)
            _trace("→ %s", name)
            yield _event_with_compaction_tag({
                "type": "tool_start",
                "tool": name,
                "args": args,
                "tool_call_id": tc["id"],
            }, ctx.compaction)

            cache_key = _tool_call_cache_key(tc)
            if _tool_call_is_cacheable(name, args) and cache_key in state.tool_result_cache:
                cached_content = state.tool_result_cache[cache_key]
                state.tool_calls_made.append(name)
                state.tool_call_trace.append(cache_key)
                state.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": cached_content,
                    "_cache_hit": True,
                })
                yield _event_with_compaction_tag({
                    "type": "tool_result",
                    "tool": name,
                    "result": cached_content,
                    "cache_hit": True,
                }, ctx.compaction)
                continue

            if get_tool_safety_tier(name) in _PARALLEL_UNSAFE_TIERS:
                if cache_key in state.mutating_tool_call_seen:
                    error = json.dumps({
                        "error": (
                            "Duplicate mutating/control-plane tool call blocked. "
                            "Use the existing result or fetch fresh read-only state before retrying."
                        )
                    })
                    state.tool_calls_made.append(name)
                    state.tool_call_trace.append(cache_key)
                    state.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": error,
                    })
                    yield _event_with_compaction_tag({
                        "type": "tool_result",
                        "tool": name,
                        "error": "Duplicate mutating/control-plane tool call blocked",
                    }, ctx.compaction)
                    continue
                state.mutating_tool_call_seen.add(cache_key)

            tc_result = await _dispatch_tool(
                name=name,
                args=args,
                tool_call_id=tc["id"],
                bot=bot,
                session_id=ctx.session_id,
                client_id=ctx.client_id,
                correlation_id=ctx.correlation_id,
                channel_id=ctx.channel_id,
                iteration=iteration,
                provider_id=provider_id,
                summarize_settings=summarize_settings,
                compaction=ctx.compaction,
                skip_policy=skip_tool_policy,
                effective_allowed=effective_allowed,
                dispatch_tool_call_fn=dispatch_tool_call_fn,
            )

            async for event in _process_tool_call_result(
                tc=tc,
                tc_result=tc_result,
                ctx=ctx,
                state=state,
                iteration=iteration,
                provider_id=provider_id,
                summarize_settings=summarize_settings,
                effective_allowed=effective_allowed,
                dispatch_tool_call_fn=dispatch_tool_call_fn,
            ):
                yield event
