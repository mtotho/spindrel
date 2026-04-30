"""State-poll refresh runtime for interactive widgets.

This module owns state-poll argument substitution, identity ContextVars, poll
result caching, batch coalescing, and dashboard-pin envelope write-back.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.agent.tool_dispatch import ToolResultEnvelope
from app.schemas.widget_actions import (
    WidgetActionRequest,
    WidgetActionResponse,
    WidgetRefreshBatchItem,
    WidgetRefreshBatchRequest,
    WidgetRefreshBatchResponse,
    WidgetRefreshBatchResult,
    WidgetRefreshRequest,
)
from app.services.widget_templates import (
    apply_state_poll,
    get_state_poll_config,
    substitute_vars,
)
from app.tools.mcp import call_mcp_tool, is_mcp_tool
from app.tools.registry import call_local_tool, is_local_tool

logger = logging.getLogger(__name__)


_poll_cache: dict[tuple[str, str, str | None, str | None], tuple[float, str]] = {}
_POLL_CACHE_TTL = 30.0


def _resolve_tool_name(name: str) -> str:
    from app.services.tool_execution import resolve_tool_name

    return resolve_tool_name(name)


def _evict_stale_cache() -> None:
    now = time.monotonic()
    stale = [k for k, (ts, _) in _poll_cache.items() if now - ts >= _POLL_CACHE_TTL]
    for key in stale:
        del _poll_cache[key]


def invalidate_poll_cache_for(poll_cfg: dict) -> None:
    poll_tool = poll_cfg.get("tool")
    if not poll_tool:
        return
    resolved = _resolve_tool_name(poll_tool)
    for key in [k for k in _poll_cache if k[0] == resolved]:
        _poll_cache.pop(key, None)


async def _do_state_poll(
    *,
    tool_name: str,
    display_label: str,
    poll_cfg: dict,
    widget_config: dict | None = None,
    bot_id: str | None = None,
    channel_id: uuid.UUID | None = None,
) -> ToolResultEnvelope | None:
    from app.agent.context import current_bot_id, current_channel_id

    poll_tool = poll_cfg.get("tool")
    if not poll_tool:
        return None

    resolved_poll_tool = _resolve_tool_name(poll_tool)
    raw_args = poll_cfg.get("args", {}) or {}
    widget_meta = {
        "display_label": display_label,
        "tool_name": tool_name,
        "widget_config": widget_config or {},
        "config": widget_config or {},
        "source_bot_id": bot_id,
        "source_channel_id": str(channel_id) if channel_id else None,
    }
    substituted_args = substitute_vars(raw_args, widget_meta)
    poll_args = json.dumps(substituted_args, sort_keys=True)
    cache_key = _poll_cache_key(
        resolved_poll_tool,
        poll_args,
        bot_id=bot_id,
        channel_id=channel_id,
    )

    raw_result = await _fetch_state_poll_raw(
        resolved_poll_tool=resolved_poll_tool,
        poll_args=poll_args,
        cache_key=cache_key,
        bot_id=bot_id,
        channel_id=channel_id,
        current_bot_id=current_bot_id,
        current_channel_id=current_channel_id,
    )
    if raw_result is None:
        return None
    return apply_state_poll(tool_name, raw_result, widget_meta)


def _poll_cache_key(
    resolved_poll_tool: str,
    poll_args: str,
    *,
    bot_id: str | None,
    channel_id: uuid.UUID | None,
) -> tuple[str, str, str | None, str | None]:
    return (
        resolved_poll_tool,
        poll_args,
        bot_id,
        str(channel_id) if channel_id else None,
    )


async def _fetch_state_poll_raw(
    *,
    resolved_poll_tool: str,
    poll_args: str,
    cache_key: tuple[str, str, str | None, str | None],
    bot_id: str | None,
    channel_id: uuid.UUID | None,
    current_bot_id: Any,
    current_channel_id: Any,
) -> str | None:
    now = time.monotonic()
    cached = _poll_cache.get(cache_key)
    if cached and (now - cached[0]) < _POLL_CACHE_TTL:
        return cached[1]

    raw_result = None
    bot_token = current_bot_id.set(bot_id) if bot_id else None
    channel_token = current_channel_id.set(channel_id) if channel_id else None
    try:
        if is_local_tool(resolved_poll_tool):
            raw_result = await asyncio.wait_for(
                call_local_tool(resolved_poll_tool, poll_args),
                timeout=settings.TOOL_DISPATCH_TIMEOUT,
            )
        elif is_mcp_tool(resolved_poll_tool):
            raw_result = await asyncio.wait_for(
                call_mcp_tool(resolved_poll_tool, poll_args),
                timeout=settings.TOOL_DISPATCH_TIMEOUT,
            )
        else:
            logger.warning("Unknown poll tool: %s", resolved_poll_tool)
            return None
    except asyncio.TimeoutError:
        logger.warning("Poll tool '%s' timed out", resolved_poll_tool)
        return None
    except Exception:
        logger.warning("Poll tool '%s' failed", resolved_poll_tool, exc_info=True)
        return None
    finally:
        if bot_token is not None:
            current_bot_id.reset(bot_token)
        if channel_token is not None:
            current_channel_id.reset(channel_token)

    if raw_result is None:
        return None

    _poll_cache[cache_key] = (now, raw_result)
    return raw_result


async def _load_refresh_pin_contexts(
    requests: list[WidgetRefreshRequest],
) -> dict[uuid.UUID, tuple[str | None, uuid.UUID | None]]:
    pin_ids = sorted(
        {req.dashboard_pin_id for req in requests if req.dashboard_pin_id is not None},
        key=str,
    )
    if not pin_ids:
        return {}

    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import WidgetDashboardPin

    contexts: dict[uuid.UUID, tuple[str | None, uuid.UUID | None]] = {}
    try:
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(
                        WidgetDashboardPin.id,
                        WidgetDashboardPin.source_bot_id,
                        WidgetDashboardPin.source_channel_id,
                    ).where(WidgetDashboardPin.id.in_(pin_ids))
                )
            ).all()
            for pin_id, source_bot_id, source_channel_id in rows:
                contexts[pin_id] = (source_bot_id, source_channel_id)
    except Exception:
        logger.warning("Dashboard pin batch lookup for refresh context failed", exc_info=True)
    return contexts


async def _persist_refreshed_pin_envelopes(updates: dict[uuid.UUID, dict]) -> None:
    if not updates:
        return

    from app.db.engine import async_session
    from app.services.dashboard_pins import update_pin_envelope

    try:
        async with async_session() as db:
            for pin_id, env_dict in updates.items():
                await update_pin_envelope(db, pin_id, env_dict)
    except Exception:
        logger.warning("Dashboard pin envelope batch write-back failed", exc_info=True)


async def refresh_widget_states_batch(
    req: WidgetRefreshBatchRequest,
    *,
    db: AsyncSession | None = None,
    auth: object | None = None,
) -> WidgetRefreshBatchResponse:
    _evict_stale_cache()
    from app.agent.context import current_bot_id, current_channel_id

    if auth is not None:
        if db is None:
            raise RuntimeError("db is required when auth is provided")
        from app.services.widget_action_auth import authorize_widget_refresh_request

        for item in req.requests:
            await authorize_widget_refresh_request(db, auth, item)

    pin_contexts = await _load_refresh_pin_contexts(req.requests)
    results: dict[str, WidgetRefreshBatchResult] = {}
    persist_updates: dict[uuid.UUID, dict] = {}
    groups: dict[tuple[str, str, str | None, str | None], dict[str, Any]] = {}

    for item in req.requests:
        poll_cfg = get_state_poll_config(item.tool_name)
        if not poll_cfg:
            results[item.request_id] = WidgetRefreshBatchResult(
                request_id=item.request_id,
                ok=False,
                error=f"No state_poll config for {item.tool_name}",
            )
            continue
        poll_tool = poll_cfg.get("tool")
        if not poll_tool:
            results[item.request_id] = WidgetRefreshBatchResult(
                request_id=item.request_id,
                ok=False,
                error="state_poll missing 'tool' field",
            )
            continue

        pin_bot_id: str | None = None
        pin_channel_id: uuid.UUID | None = None
        if item.dashboard_pin_id is not None:
            pin_bot_id, pin_channel_id = pin_contexts.get(item.dashboard_pin_id, (None, None))

        bot_id = pin_bot_id or item.bot_id
        channel_id = pin_channel_id or item.channel_id
        resolved_poll_tool = _resolve_tool_name(poll_tool)
        raw_args = poll_cfg.get("args", {}) or {}
        widget_meta = {
            "display_label": item.display_label,
            "tool_name": item.tool_name,
            "widget_config": item.widget_config or {},
            "config": item.widget_config or {},
            "source_bot_id": bot_id,
            "source_channel_id": str(channel_id) if channel_id else None,
        }
        substituted_args = substitute_vars(raw_args, widget_meta)
        poll_args = json.dumps(substituted_args, sort_keys=True)
        cache_key = _poll_cache_key(
            resolved_poll_tool,
            poll_args,
            bot_id=bot_id,
            channel_id=channel_id,
        )
        group = groups.setdefault(
            cache_key,
            {
                "resolved_poll_tool": resolved_poll_tool,
                "poll_args": poll_args,
                "bot_id": bot_id,
                "channel_id": channel_id,
                "items": [],
            },
        )
        group["items"].append((item, poll_cfg, widget_meta, pin_bot_id, pin_channel_id))

    for cache_key, group in groups.items():
        raw_result = await _fetch_state_poll_raw(
            resolved_poll_tool=group["resolved_poll_tool"],
            poll_args=group["poll_args"],
            cache_key=cache_key,
            bot_id=group["bot_id"],
            channel_id=group["channel_id"],
            current_bot_id=current_bot_id,
            current_channel_id=current_channel_id,
        )
        if raw_result is None:
            for item, *_ in group["items"]:
                results[item.request_id] = WidgetRefreshBatchResult(
                    request_id=item.request_id,
                    ok=False,
                    error="State poll failed to produce an envelope",
                )
            continue

        for item, _poll_cfg, widget_meta, pin_bot_id, pin_channel_id in group["items"]:
            envelope = apply_state_poll(item.tool_name, raw_result, widget_meta)
            if envelope is None:
                results[item.request_id] = WidgetRefreshBatchResult(
                    request_id=item.request_id,
                    ok=False,
                    error="State poll failed to produce an envelope",
                )
                continue
            env_dict = envelope.compact_dict()
            if item.dashboard_pin_id is not None:
                if pin_bot_id is not None:
                    env_dict["source_bot_id"] = pin_bot_id
                else:
                    env_dict.pop("source_bot_id", None)
                if pin_channel_id is not None:
                    env_dict["source_channel_id"] = str(pin_channel_id)
                else:
                    env_dict.pop("source_channel_id", None)
                persist_updates[item.dashboard_pin_id] = env_dict
            results[item.request_id] = WidgetRefreshBatchResult(
                request_id=item.request_id,
                ok=True,
                envelope=env_dict,
            )

    await _persist_refreshed_pin_envelopes(persist_updates)
    ordered = [
        results.get(item.request_id)
        or WidgetRefreshBatchResult(
            request_id=item.request_id,
            ok=False,
            error="Refresh was not scheduled",
        )
        for item in req.requests
    ]
    return WidgetRefreshBatchResponse(ok=all(item.ok for item in ordered), results=ordered)


async def refresh_widget_state(
    req: WidgetRefreshRequest,
    *,
    db: AsyncSession | None = None,
    auth: object | None = None,
) -> WidgetActionResponse:
    _evict_stale_cache()

    if auth is not None:
        if db is None:
            raise RuntimeError("db is required when auth is provided")
        from app.services.widget_action_auth import authorize_widget_refresh_request

        await authorize_widget_refresh_request(db, auth, req)

    poll_cfg = get_state_poll_config(req.tool_name)
    if not poll_cfg:
        return WidgetActionResponse(ok=False, error=f"No state_poll config for {req.tool_name}")
    if not poll_cfg.get("tool"):
        return WidgetActionResponse(ok=False, error="state_poll missing 'tool' field")

    pin_bot_id: str | None = None
    pin_channel_id: uuid.UUID | None = None
    if req.dashboard_pin_id is not None:
        from app.db.engine import async_session
        from app.db.models import WidgetDashboardPin

        try:
            async with async_session() as db:
                pin_row = await db.get(WidgetDashboardPin, req.dashboard_pin_id)
                if pin_row is not None:
                    pin_bot_id = pin_row.source_bot_id
                    pin_channel_id = pin_row.source_channel_id
        except Exception:
            logger.warning(
                "Dashboard pin lookup for refresh context failed: pin=%s",
                req.dashboard_pin_id,
                exc_info=True,
            )

    envelope = await _do_state_poll(
        tool_name=req.tool_name,
        display_label=req.display_label,
        poll_cfg=poll_cfg,
        widget_config=req.widget_config,
        bot_id=pin_bot_id or req.bot_id,
        channel_id=pin_channel_id or req.channel_id,
    )
    if envelope is None:
        return WidgetActionResponse(ok=False, error="State poll failed to produce an envelope")

    env_dict = envelope.compact_dict()
    if req.dashboard_pin_id is not None:
        if pin_bot_id is not None:
            env_dict["source_bot_id"] = pin_bot_id
        else:
            env_dict.pop("source_bot_id", None)
        if pin_channel_id is not None:
            env_dict["source_channel_id"] = str(pin_channel_id)
        else:
            env_dict.pop("source_channel_id", None)

    if req.dashboard_pin_id is not None:
        from app.db.engine import async_session
        from app.services.dashboard_pins import update_pin_envelope

        try:
            async with async_session() as db:
                await update_pin_envelope(db, req.dashboard_pin_id, env_dict)
        except Exception:
            logger.warning(
                "Dashboard pin envelope write-back failed: pin=%s",
                req.dashboard_pin_id,
                exc_info=True,
            )

    logger.info("Widget refresh: tool=%s display_label=%s", req.tool_name, req.display_label)
    return WidgetActionResponse(ok=True, envelope=env_dict)
