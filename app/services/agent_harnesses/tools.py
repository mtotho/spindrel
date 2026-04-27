"""Bridge Spindrel tools into external harness runtimes.

This module exposes the same effective local/MCP tool set the normal loop
would see, then executes calls through ``dispatch_tool_call`` so policy,
approval rows, audit logging, secret redaction, and result summarization stay
centralized.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agent.bots import get_bot
from app.agent.channel_overrides import apply_auto_injections, resolve_effective_tools
from app.agent.context import current_resolved_skill_ids, current_skills_in_context, set_agent_context
from app.agent.loop_dispatch import SummarizeSettings, _resolve_approval_verdict
from app.agent.tool_dispatch import ToolCallResult, dispatch_tool_call
from app.config import settings
from app.db.models import Channel, ChannelSkillEnrollment
from app.services.agent_harnesses.base import TurnContext
from app.tools.mcp import fetch_mcp_tools
from app.tools.registry import get_local_tool_schemas


@dataclass(frozen=True)
class HarnessToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    schema: dict[str, Any]


@dataclass(frozen=True)
class HarnessBridgeInventory:
    specs: tuple[HarnessToolSpec, ...]
    ignored_client_tools: tuple[str, ...]


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
    )
    return inventory.specs


async def resolve_harness_bridge_inventory(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
    explicit_tool_names: tuple[str, ...] | list[str] = (),
) -> HarnessBridgeInventory:
    specs = await list_harness_spindrel_tools_for(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        explicit_tool_names=explicit_tool_names,
    )
    bot = get_bot(bot_id)
    channel = await db.get(Channel, channel_id) if channel_id else None
    if channel is not None:
        await _attach_channel_skill_ids(db, channel)
    eff = apply_auto_injections(resolve_effective_tools(bot, channel), bot)
    return HarnessBridgeInventory(
        specs=specs,
        ignored_client_tools=tuple(eff.client_tools),
    )


async def list_harness_spindrel_tools_for(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
    explicit_tool_names: tuple[str, ...] | list[str] = (),
) -> tuple[HarnessToolSpec, ...]:
    """Return effective server-executable Spindrel bridge tools."""
    bot = get_bot(bot_id)
    channel = await db.get(Channel, channel_id) if channel_id else None
    if channel is not None:
        await _attach_channel_skill_ids(db, channel)
    eff = apply_auto_injections(resolve_effective_tools(bot, channel), bot)
    schemas: list[dict[str, Any]] = []
    local_names = list(dict.fromkeys(list(eff.local_tools) + list(explicit_tool_names or ())))
    schemas.extend(get_local_tool_schemas(local_names))
    schemas.extend(await fetch_mcp_tools(list(eff.mcp_servers)))

    seen: set[str] = set()
    specs: list[HarnessToolSpec] = []
    for schema in schemas:
        spec = _spec_from_schema(schema)
        if spec is None or spec.name in seen:
            continue
        seen.add(spec.name)
        specs.append(spec)
    return tuple(specs)


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
    channel = await db.get(Channel, channel_id) if channel_id else None
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
        allowed_tool_names=set(allowed_tool_names) if allowed_tool_names is not None else set(),
    )
    if result.needs_approval and result.approval_id:
        verdict = await _resolve_approval_verdict(
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
                allowed_tool_names=set(allowed_tool_names) if allowed_tool_names is not None else set(),
            )
        else:
            return f"Tool call denied or expired: {verdict}"
    if result.result_for_llm:
        return result.result_for_llm
    if result.result:
        return result.result
    return ""
