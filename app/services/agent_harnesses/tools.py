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

from app.agent.bots import get_bot
from app.agent.channel_overrides import apply_auto_injections, resolve_effective_tools
from app.agent.context import set_agent_context
from app.agent.loop_dispatch import SummarizeSettings, _resolve_approval_verdict
from app.agent.tool_dispatch import ToolCallResult, dispatch_tool_call
from app.config import settings
from app.db.models import Channel
from app.services.agent_harnesses.base import TurnContext
from app.tools.mcp import fetch_mcp_tools
from app.tools.registry import get_local_tool_schemas


@dataclass(frozen=True)
class HarnessToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    schema: dict[str, Any]


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
    return await list_harness_spindrel_tools_for(
        db,
        bot_id=ctx.bot_id,
        channel_id=ctx.channel_id,
    )


async def list_harness_spindrel_tools_for(
    db: AsyncSession,
    *,
    bot_id: str,
    channel_id: uuid.UUID | None,
) -> tuple[HarnessToolSpec, ...]:
    """Return effective server-executable Spindrel bridge tools."""
    bot = get_bot(bot_id)
    channel = await db.get(Channel, channel_id) if channel_id else None
    eff = apply_auto_injections(resolve_effective_tools(bot, channel), bot)
    schemas: list[dict[str, Any]] = []
    schemas.extend(get_local_tool_schemas(list(eff.local_tools)))
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
        allowed_tool_names=None,
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
                allowed_tool_names=None,
            )
        else:
            return f"Tool call denied or expired: {verdict}"
    if result.result_for_llm:
        return result.result_for_llm
    if result.result:
        return result.result
    return ""
