"""Finalization of the exposed tool surface.

Runs after heartbeat/retrieval composition. Merges dynamically injected
tools (from `current_injected_tools` contextvar), surfaces widget-handler
bridge tools for the active bot/channel, and applies the capability gate
that drops tools whose required capabilities/integrations the channel's
bindings cannot satisfy.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)


async def _finalize_exposed_tools(
    *,
    bot: BotConfig,
    channel_id: Any,
    ch_row: Any,
    tool_surface_policy: str | None,
    state: Any,
) -> None:
    pre_selected_tools = state.pre_selected_tools
    authorized_names = state.authorized_names
    # --- merge dynamically injected tools (e.g. post_heartbeat_to_channel) ---
    from app.agent.context import current_injected_tools
    _injected = current_injected_tools.get()
    if _injected:
        _injected_names = [t["function"]["name"] for t in _injected]
        logger.info("Injecting tools: %s", _injected_names)
        if pre_selected_tools is not None:
            _existing = {t["function"]["name"] for t in pre_selected_tools}
            for t in _injected:
                if t["function"]["name"] not in _existing:
                    pre_selected_tools.append(t)

    # Include dynamically injected tool names in the authorized set
    if _injected and authorized_names is not None:
        authorized_names.update(t["function"]["name"] for t in _injected)

    # --- widget-handler tools (bot↔widget bridge) ---
    # For every pinned widget whose manifest declares bot-callable handlers,
    # surface them as `widget__<slug>__<handler>` tools. Visibility is the
    # caller's channel dashboard + any dashboard the calling bot authored.
    # See `app/services/widget_handler_tools.py` for visibility + dispatch.
    if (channel_id or bot.id) and tool_surface_policy not in {"focused_escape", "strict"}:
        try:
            from app.db.engine import async_session as _wh_session_factory
            from app.services.widget_handler_tools import list_widget_handler_tools
            async with _wh_session_factory() as _wh_db:
                _wh_schemas, _ = await list_widget_handler_tools(
                    _wh_db, bot.id, str(channel_id) if channel_id else None,
                )
            if _wh_schemas:
                if pre_selected_tools is None:
                    pre_selected_tools = list(_wh_schemas)
                else:
                    _existing = {t["function"]["name"] for t in pre_selected_tools}
                    for _sch in _wh_schemas:
                        if _sch["function"]["name"] not in _existing:
                            pre_selected_tools.append(_sch)
                if authorized_names is None:
                    authorized_names = set()
                authorized_names.update(
                    t["function"]["name"] for t in _wh_schemas
                )
                logger.debug(
                    "widget_handler_tools: injected %d handler(s) for bot=%s channel=%s",
                    len(_wh_schemas), bot.id, channel_id,
                )
        except Exception:
            logger.warning(
                "widget_handler_tools: enumeration failed; widget tools will not be surfaced this turn",
                exc_info=True,
            )

    # --- capability-gated tool exposure ---
    # Drop tools whose required_capabilities / required_integrations the
    # current channel's bindings can't satisfy. Keeps respond_privately,
    # open_modal, and slack_* surface tools out of the LLM's tool list
    # on channels that can't honor them — rather than letting the agent
    # call the tool and hit a runtime "unsupported" error. Structural
    # fix for the Phase 3/4 Slack-depth bug documented in
    # project-notes/Architecture Decisions.md (Channel binding model).
    if ch_row is not None:
        try:
            from app.agent.capability_gate import build_view
            from app.integrations import renderer_registry as _rreg
            from app.services.dispatch_resolution import resolve_targets as _resolve_targets
            from app.tools.registry import get_tool_capability_requirements

            _targets = await _resolve_targets(ch_row)
            _bound_ids = [iid for iid, _t in _targets]
            _caps_map = {
                iid: getattr(_rreg.get(iid), "capabilities", frozenset())
                for iid in _bound_ids
                if _rreg.get(iid) is not None
            }
            _view = build_view(_bound_ids, _caps_map)

            def _tool_is_exposable(_name: str) -> bool:
                _req_caps, _req_ints = get_tool_capability_requirements(_name)
                return _view.tool_is_exposable(_req_caps, _req_ints)

            if authorized_names is not None:
                _dropped = {n for n in authorized_names if not _tool_is_exposable(n)}
                if _dropped:
                    authorized_names -= _dropped
                    logger.debug(
                        "capability_gate: dropped %d tools on channel=%s (bound=%s): %s",
                        len(_dropped), channel_id,
                        sorted(_view.bound_integrations), sorted(_dropped),
                    )
            if pre_selected_tools is not None:
                pre_selected_tools = [
                    _t for _t in pre_selected_tools
                    if _tool_is_exposable(_t.get("function", {}).get("name", ""))
                ]
        except Exception:
            logger.warning(
                "capability_gate: filter failed for channel %s — continuing without gate",
                channel_id, exc_info=True,
            )

    state.pre_selected_tools = pre_selected_tools
    state.authorized_names = authorized_names
