"""Bridge Spindrel tools into external harness runtimes.

This module exposes the same effective local/MCP tool set the normal loop
would see, then executes calls through ``dispatch_tool_call`` so policy,
approval rows, audit logging, secret redaction, and result summarization stay
centralized.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent.bots import get_bot
from app.agent.channel_overrides import apply_auto_injections, resolve_effective_tools
from app.agent.context import current_resolved_skill_ids, current_skills_in_context, set_agent_context
from app.agent.loop_dispatch import SummarizeSettings, resolve_approval_verdict
from app.agent.tool_dispatch import ToolCallResult, dispatch_tool_call
from app.config import settings
from app.db.models import Channel, ChannelSkillEnrollment
from app.services.agent_harnesses.base import (
    HarnessBridgeInventory,
    HarnessToolSpec,
    TurnContext,
)
from app.services.agent_harnesses.approvals import AllowDeny, request_harness_approval
from app.tools.mcp import fetch_mcp_tools
from app.tools.registry import get_local_tool_schemas

logger = logging.getLogger(__name__)

_PLAN_DRAFT_TOOL_NAMES: tuple[str, ...] = ("ask_plan_questions", "publish_plan")
_PLAN_EXECUTION_TOOL_NAMES: tuple[str, ...] = ("record_plan_progress", "request_plan_replan")
_PLAN_CONTROL_TOOL_NAMES: frozenset[str] = frozenset(
    (*_PLAN_DRAFT_TOOL_NAMES, *_PLAN_EXECUTION_TOOL_NAMES)
)

__all__ = [
    "HarnessBridgeInventory",
    "HarnessToolSpec",
    "apply_tool_bridge",
    "execute_harness_spindrel_tool",
    "execute_harness_spindrel_tool_result",
    "HarnessSpindrelToolResult",
    "list_harness_spindrel_tools",
    "list_harness_spindrel_tools_for",
    "resolve_harness_bridge_inventory",
]


HarnessAttach = Callable[[tuple[HarnessToolSpec, ...]], Awaitable[list[str]]]


@dataclass(frozen=True)
class HarnessSpindrelToolResult:
    """Result of a Spindrel tool executed through a harness bridge."""

    text: str
    envelope: dict[str, Any] | None = None
    surface: str | None = None
    summary: dict[str, Any] | None = None
    is_error: bool = False


class _SpindrelBridgeApprovalRuntime:
    """Harness-approval classifier for host-provided bridge tools.

    Native runtimes classify their own tool names (Claude ``Write``, Codex
    shell/apply-patch, etc.). Bridge tools need the same mode semantics before
    they enter Spindrel's normal dispatcher; otherwise a runtime can bypass
    ``default`` approval mode by choosing ``mcp__spindrel__file`` instead of
    its native file-write tool.
    """

    def __init__(self, *, tool_name: str, arguments: dict[str, Any], safety_tier: str) -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self._safety_tier = safety_tier

    def readonly_tools(self) -> frozenset[str]:
        if self._tool_name in _PLAN_CONTROL_TOOL_NAMES:
            return frozenset({self._tool_name})
        if self._safety_tier == "readonly":
            return frozenset({self._tool_name})
        return frozenset()

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        return not _bridge_accept_edits_autoapproves(
            tool_name,
            self._arguments,
            safety_tier=self._safety_tier,
        )

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        return False


_FILE_ACCEPT_EDITS_OPS: frozenset[str] = frozenset({
    "create",
    "overwrite",
    "append",
    "edit",
    "json_patch",
    "restore",
    "mkdir",
    "move",
})


def _bridge_accept_edits_autoapproves(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    safety_tier: str,
) -> bool:
    if safety_tier == "readonly":
        return True
    if tool_name != "file":
        return False
    operation = str(arguments.get("operation") or "").strip()
    return operation in _FILE_ACCEPT_EDITS_OPS


async def apply_tool_bridge(
    ctx: TurnContext,
    runtime: Any,
    *,
    attach: HarnessAttach,
) -> tuple[list[str], list[str]]:
    """Resolve the Spindrel bridge inventory and let the runtime attach it.

    The runtime supplies an ``attach(specs)`` coroutine that wraps each spec
    into its SDK-native shape (Claude in-process MCP server, Codex
    ``dynamicTools``, etc.) and returns the list of tool names the runtime
    actually exported. The host owns inventory resolution and bridge-status
    bookkeeping so each runtime adapter only handles its own SDK shape.

    Returns ``(exported_tool_names, ignored_client_tool_names)``.
    """
    runtime_name = getattr(runtime, "name", None) or runtime.__class__.__name__
    bridge_namespace = _bridge_namespace(runtime_name)
    if ctx.channel_id is None:
        from app.services.agent_harnesses.session_state import set_bridge_status

        async with ctx.db_session_factory() as db:
            await set_bridge_status(
                db,
                ctx.spindrel_session_id,
                status="no_channel",
                error="Spindrel bridge tools require a channel-scoped harness turn.",
                namespace=bridge_namespace,
            )
        return [], []
    from app.services.agent_harnesses.session_state import set_bridge_status

    ignored_client_tools: tuple[str, ...] = ()
    inventory_errors: tuple[str, ...] = ()
    required_baseline_tools: tuple[str, ...] = ()
    missing_baseline_tools: tuple[str, ...] = ()
    specs: tuple[HarnessToolSpec, ...] = ()
    try:
        async with ctx.db_session_factory() as db:
            inventory = await resolve_harness_bridge_inventory(
                db,
                bot_id=ctx.bot_id,
                channel_id=ctx.channel_id,
                explicit_tool_names=ctx.ephemeral_tool_names,
                session_plan_mode=ctx.session_plan_mode,
            )
        specs = inventory.specs
        ignored_client_tools = inventory.ignored_client_tools
        inventory_errors = inventory.errors
        required_baseline_tools = inventory.required_baseline_tools
        missing_baseline_tools = inventory.missing_baseline_tools
    except Exception:
        logger.exception("%s: failed to list Spindrel bridge tools", runtime_name)
        async with ctx.db_session_factory() as db:
            await set_bridge_status(
                db,
                ctx.spindrel_session_id,
                status="error",
                ignored_client_tools=ignored_client_tools,
                namespace=bridge_namespace,
                error="failed to list Spindrel bridge tools",
            )
        return [], list(ignored_client_tools)

    if not specs:
        async with ctx.db_session_factory() as db:
            await set_bridge_status(
                db,
                ctx.spindrel_session_id,
                status="no_tools_selected",
                ignored_client_tools=ignored_client_tools,
                explicit_tool_names=ctx.ephemeral_tool_names,
                tagged_skill_ids=ctx.tagged_skill_ids,
                inventory_errors=inventory_errors,
                required_baseline_tools=required_baseline_tools,
                missing_baseline_tools=missing_baseline_tools,
                namespace=bridge_namespace,
                error="; ".join(inventory_errors) if inventory_errors else None,
            )
        return [], list(ignored_client_tools)

    try:
        exported = await attach(specs)
    except Exception as exc:
        logger.exception("%s: bridge attach failed", runtime_name)
        async with ctx.db_session_factory() as db:
            await set_bridge_status(
                db,
                ctx.spindrel_session_id,
                status="error",
                exported_tools=[spec.name for spec in specs],
                ignored_client_tools=ignored_client_tools,
                explicit_tool_names=ctx.ephemeral_tool_names,
                tagged_skill_ids=ctx.tagged_skill_ids,
                inventory_errors=inventory_errors,
                required_baseline_tools=required_baseline_tools,
                missing_baseline_tools=missing_baseline_tools,
                namespace=bridge_namespace,
                error=str(exc) or "bridge attach failed",
            )
        return [], list(ignored_client_tools)

    if not exported:
        async with ctx.db_session_factory() as db:
            await set_bridge_status(
                db,
                ctx.spindrel_session_id,
                status="unsupported",
                exported_tools=[spec.name for spec in specs],
                ignored_client_tools=ignored_client_tools,
                explicit_tool_names=ctx.ephemeral_tool_names,
                tagged_skill_ids=ctx.tagged_skill_ids,
                inventory_errors=inventory_errors,
                required_baseline_tools=required_baseline_tools,
                missing_baseline_tools=missing_baseline_tools,
                namespace=bridge_namespace,
                error="runtime did not export any bridge tools",
            )
        return [], list(ignored_client_tools)

    async with ctx.db_session_factory() as db:
        await set_bridge_status(
            db,
            ctx.spindrel_session_id,
            status="enabled",
            exported_tools=list(exported),
            ignored_client_tools=ignored_client_tools,
            explicit_tool_names=ctx.ephemeral_tool_names,
            tagged_skill_ids=ctx.tagged_skill_ids,
            inventory_errors=inventory_errors,
            required_baseline_tools=required_baseline_tools,
            missing_baseline_tools=missing_baseline_tools,
            namespace=bridge_namespace,
        )
    return list(exported), list(ignored_client_tools)


def _bridge_namespace(runtime_name: str) -> str:
    if runtime_name == "codex":
        return "spindrel"
    if runtime_name == "claude-code":
        return "spindrel"
    return runtime_name


def _spec_from_schema(schema: dict[str, Any]) -> HarnessToolSpec | None:
    fn = schema.get("function")
    if not isinstance(fn, dict):
        return None
    name = fn.get("name")
    if not isinstance(name, str) or not name:
        return None
    return HarnessToolSpec(
        name=name,
        description=fn.get("description") if isinstance(fn.get("description"), str) else "",
        parameters=fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {},
        schema=schema,
    )


async def list_harness_spindrel_tools(
    db: AsyncSession,
    ctx: TurnContext,
) -> tuple[HarnessToolSpec, ...]:
    """Return effective Spindrel tools for this harness turn.

    Client/browser-only tools are intentionally excluded: the harness SDK runs
    in the server process and cannot satisfy browser callbacks.
    """
    inventory = await resolve_harness_bridge_inventory(
        db,
        bot_id=ctx.bot_id,
        channel_id=ctx.channel_id,
        explicit_tool_names=ctx.ephemeral_tool_names,
        session_plan_mode=ctx.session_plan_mode,
    )
    return inventory.specs


async def resolve_harness_bridge_inventory(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
    explicit_tool_names: tuple[str, ...] | list[str] = (),
    session_plan_mode: str = "chat",
) -> HarnessBridgeInventory:
    specs, errors = await _collect_harness_spindrel_tools_for(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        explicit_tool_names=explicit_tool_names,
        session_plan_mode=session_plan_mode,
    )
    bot = get_bot(bot_id)
    channel = await _load_channel_for_effective_tools(db, channel_id)
    if channel is not None:
        await _attach_channel_skill_ids(db, channel)
    eff = apply_auto_injections(resolve_effective_tools(bot, channel), bot)
    spec_names = {spec.name for spec in specs}
    required_baseline_tools = tuple(
        name for name in _required_baseline_candidates(bot)
        if name in set(eff.local_tools) or name in set(eff.pinned_tools or ())
    )
    missing_baseline_tools = tuple(
        name for name in required_baseline_tools if name not in spec_names
    )
    return HarnessBridgeInventory(
        specs=specs,
        ignored_client_tools=tuple(eff.client_tools),
        errors=errors,
        required_baseline_tools=required_baseline_tools,
        missing_baseline_tools=missing_baseline_tools,
    )


def _required_baseline_candidates(bot: Any) -> tuple[str, ...]:
    names = [
        "list_channels",
        "read_conversation_history",
        "list_sub_sessions",
        "read_sub_session",
    ]
    if getattr(bot, "memory_scheme", None) == "workspace-files":
        try:
            from app.services.memory_scheme import MEMORY_SCHEME_TOOLS

            names.extend(MEMORY_SCHEME_TOOLS)
        except Exception:
            names.extend(["search_memory", "get_memory_file", "file", "manage_bot_skill"])
    return tuple(dict.fromkeys(names))


async def list_harness_spindrel_tools_for(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
    explicit_tool_names: tuple[str, ...] | list[str] = (),
    session_plan_mode: str = "chat",
) -> tuple[HarnessToolSpec, ...]:
    """Return effective server-executable Spindrel bridge tools."""
    specs, _errors = await _collect_harness_spindrel_tools_for(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        explicit_tool_names=explicit_tool_names,
        session_plan_mode=session_plan_mode,
    )
    return specs


async def _collect_harness_spindrel_tools_for(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
    explicit_tool_names: tuple[str, ...] | list[str] = (),
    session_plan_mode: str = "chat",
) -> tuple[tuple[HarnessToolSpec, ...], tuple[str, ...]]:
    """Return bridgeable tools plus non-fatal inventory errors."""
    bot = get_bot(bot_id)
    channel = await _load_channel_for_effective_tools(db, channel_id)
    if channel is not None:
        await _attach_channel_skill_ids(db, channel)
    eff = apply_auto_injections(resolve_effective_tools(bot, channel), bot)
    schemas: list[dict[str, Any]] = []
    errors: list[str] = []
    enrolled_names: list[str] = []
    if bot_id:
        try:
            from app.services.tool_enrollment import enroll_many, get_enrolled_tool_names

            if explicit_tool_names:
                await enroll_many(bot_id, explicit_tool_names, source="manual", db=db)
            enrolled_names = await get_enrolled_tool_names(bot_id)
        except Exception:
            logger.warning("harness bridge: failed to load enrolled tools for %s", bot_id, exc_info=True)
    local_names = list(dict.fromkeys(
        list(eff.local_tools)
        + list(eff.pinned_tools or ())
        + enrolled_names
        + list(explicit_tool_names or ())
        + list(_plan_control_tools_for_mode(session_plan_mode))
    ))
    try:
        local_schemas = get_local_tool_schemas(local_names)
        schemas.extend(local_schemas)
        if local_names:
            resolved_local_names = {
                spec.name
                for schema in local_schemas
                if (spec := _spec_from_schema(schema)) is not None
            }
            missing_local_names = [
                name for name in local_names if name not in resolved_local_names
            ]
            if missing_local_names:
                errors.append(
                    "local tools not registered: "
                    + ", ".join(missing_local_names[:20])
                    + (" ..." if len(missing_local_names) > 20 else "")
                )
    except Exception as exc:
        logger.exception("harness bridge: failed to resolve local tool schemas")
        errors.append(f"local tools: {exc}")
    for server_name in eff.mcp_servers:
        try:
            schemas.extend(await fetch_mcp_tools([server_name]))
        except Exception as exc:
            logger.exception("harness bridge: failed to resolve MCP tools from %s", server_name)
            errors.append(f"MCP {server_name}: {exc}")

    seen: set[str] = set()
    specs: list[HarnessToolSpec] = []
    for schema in schemas:
        spec = _spec_from_schema(schema)
        if spec is None or spec.name in seen:
            continue
        seen.add(spec.name)
        specs.append(spec)
    return tuple(specs), tuple(errors)


def _plan_control_tools_for_mode(session_plan_mode: str) -> tuple[str, ...]:
    if session_plan_mode == "planning":
        return _PLAN_DRAFT_TOOL_NAMES
    if session_plan_mode in {"executing", "blocked"}:
        return _PLAN_EXECUTION_TOOL_NAMES
    return ()


async def _load_channel_for_effective_tools(
    db: AsyncSession,
    channel_id: uuid.UUID | None,
) -> Channel | None:
    if channel_id is None:
        return None
    return (await db.execute(
        select(Channel)
        .where(Channel.id == channel_id)
        .options(selectinload(Channel.integrations))
    )).scalar_one_or_none()


async def _attach_channel_skill_ids(db: AsyncSession, channel: Channel) -> None:
    rows = (await db.execute(
        select(ChannelSkillEnrollment.skill_id).where(
            ChannelSkillEnrollment.channel_id == channel.id
        )
    )).scalars().all()
    setattr(channel, "_channel_skill_enrollment_ids", list(rows))


async def resolved_skill_ids_for(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
) -> set[str]:
    bot = get_bot(bot_id)
    channel = await _load_channel_for_effective_tools(db, channel_id)
    if channel is not None:
        await _attach_channel_skill_ids(db, channel)
    eff = apply_auto_injections(resolve_effective_tools(bot, channel), bot)
    return {skill.id for skill in eff.skills}


def _summarize_settings_for(bot_model: str | None) -> SummarizeSettings:
    return SummarizeSettings(
        enabled=settings.TOOL_RESULT_SUMMARIZE_ENABLED,
        threshold=settings.TOOL_RESULT_SUMMARIZE_THRESHOLD,
        model=settings.TOOL_RESULT_SUMMARIZE_MODEL or bot_model or "",
        max_tokens=settings.TOOL_RESULT_SUMMARIZE_MAX_TOKENS,
        exclude=frozenset(settings.TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS),
    )


async def execute_harness_spindrel_tool(
    ctx: TurnContext,
    *,
    tool_name: str,
    arguments: dict[str, Any] | None,
    allowed_tool_names: set[str] | frozenset[str] | None = None,
) -> str:
    """Execute one bridged Spindrel tool and return LLM-visible text."""
    result = await execute_harness_spindrel_tool_result(
        ctx,
        tool_name=tool_name,
        arguments=arguments,
        allowed_tool_names=allowed_tool_names,
    )
    return result.text


async def execute_harness_spindrel_tool_result(
    ctx: TurnContext,
    *,
    tool_name: str,
    arguments: dict[str, Any] | None,
    allowed_tool_names: set[str] | frozenset[str] | None = None,
) -> HarnessSpindrelToolResult:
    """Execute one bridged Spindrel tool and keep its UI presentation data."""
    if allowed_tool_names is None:
        raise ValueError("allowed_tool_names is required for harness bridge tool execution")
    approval = await _request_bridge_tool_approval(
        ctx,
        tool_name=tool_name,
        arguments=arguments or {},
    )
    if not approval.allow:
        return HarnessSpindrelToolResult(
            text=f"Tool call denied or expired: {approval.reason or 'denied'}",
            is_error=True,
        )
    bot = get_bot(ctx.bot_id)
    args = json.dumps(arguments or {})
    tool_call_id = f"harness-spindrel:{uuid.uuid4()}"
    summarize = _summarize_settings_for(ctx.model or bot.model)

    set_agent_context(
        session_id=ctx.spindrel_session_id,
        bot_id=ctx.bot_id,
        correlation_id=ctx.turn_id,
        channel_id=ctx.channel_id,
        dispatch_type="harness",
    )
    async with ctx.db_session_factory() as db:
        current_resolved_skill_ids.set(
            await resolved_skill_ids_for(
                db,
                bot_id=ctx.bot_id,
                channel_id=ctx.channel_id,
            )
        )
    if current_skills_in_context.get() is None:
        current_skills_in_context.set([])
    result: ToolCallResult = await dispatch_tool_call(
        name=tool_name,
        args=args,
        tool_call_id=tool_call_id,
        bot_id=ctx.bot_id,
        bot_memory=bot.memory,
        session_id=ctx.spindrel_session_id,
        client_id=None,
        correlation_id=ctx.turn_id,
        channel_id=ctx.channel_id,
        iteration=0,
        provider_id=None,
        summarize_enabled=summarize.enabled,
        summarize_threshold=summarize.threshold,
        summarize_model=summarize.model,
        summarize_max_tokens=summarize.max_tokens,
        summarize_exclude=set(summarize.exclude),
        compaction=False,
        skip_policy=True,
        allowed_tool_names=set(allowed_tool_names),
    )
    if result.needs_approval and result.approval_id:
        verdict = await resolve_approval_verdict(
            result.approval_id,
            timeout_seconds=result.approval_timeout,
        )
        if verdict == "approved":
            result = await dispatch_tool_call(
                name=tool_name,
                args=args,
                tool_call_id=tool_call_id,
                bot_id=ctx.bot_id,
                bot_memory=bot.memory,
                session_id=ctx.spindrel_session_id,
                client_id=None,
                correlation_id=ctx.turn_id,
                channel_id=ctx.channel_id,
                iteration=0,
                provider_id=None,
                summarize_enabled=summarize.enabled,
                summarize_threshold=summarize.threshold,
                summarize_model=summarize.model,
                summarize_max_tokens=summarize.max_tokens,
                summarize_exclude=set(summarize.exclude),
                compaction=False,
                skip_policy=True,
                existing_record_id=result.record_id,
                allowed_tool_names=set(allowed_tool_names),
            )
        else:
            return HarnessSpindrelToolResult(
                text=f"Tool call denied or expired: {verdict}",
                is_error=True,
            )
    text = result.result_for_llm or result.result or ""
    event = result.tool_event or {}
    envelope = event.get("envelope")
    summary = event.get("summary")
    return HarnessSpindrelToolResult(
        text=text,
        envelope=envelope if isinstance(envelope, dict) else None,
        surface=event.get("surface") if isinstance(event.get("surface"), str) else None,
        summary=summary if isinstance(summary, dict) else None,
        is_error=bool(event.get("error")),
    )


async def _request_bridge_tool_approval(
    ctx: TurnContext,
    *,
    tool_name: str,
    arguments: dict[str, Any],
) -> AllowDeny:
    from app.tools.registry import get_tool_safety_tier

    permission_mode = "plan" if ctx.session_plan_mode == "planning" else ctx.permission_mode
    approval_ctx = ctx if permission_mode == ctx.permission_mode else replace(
        ctx,
        permission_mode=permission_mode,
    )
    runtime = _SpindrelBridgeApprovalRuntime(
        tool_name=tool_name,
        arguments=arguments,
        safety_tier=get_tool_safety_tier(tool_name),
    )
    return await request_harness_approval(
        ctx=approval_ctx,
        runtime=runtime,
        tool_name=tool_name,
        tool_input=arguments,
    )
