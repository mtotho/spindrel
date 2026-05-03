"""Tool retrieval surface composition."""
from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import AsyncGenerator
from typing import Any

from app.agent.bots import BotConfig
from app.agent.channel_overrides import (
    auto_injected_pin_names,
    plan_mode_control_tool_names,
)
from app.agent.message_utils import (
    _all_tool_schemas_by_name,
    _merge_tool_schemas,
)
from app.agent.recording import _record_trace_event
from app.agent.tool_surface.heartbeat import _compose_heartbeat_tool_surface
from app.agent.tools import retrieve_tools
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas
from app.tools.mcp import get_mcp_server_for_tool
from app.tools.registry import (
    get_local_tool_names_by_metadata,
    get_local_tool_schemas,
    get_local_tool_schemas_by_metadata,
)

logger = logging.getLogger(__name__)

_MEMORY_FLUSH_TOOL_CAPABILITIES = (
    "memory.read",
    "memory.write",
    "workspace_memory.write",
)
_MEMORY_HYGIENE_TOOL_CAPABILITIES = (
    "memory.read",
    "memory.write",
    "workspace_memory.write",
    "conversation_history.read",
    "subsessions.read",
    "skill.write",
)
_SKILL_REVIEW_TOOL_CAPABILITIES = (
    "memory.read",
    "memory.write",
    "workspace_memory.write",
    "conversation_history.read",
    "subsessions.read",
    "skill.read",
    "skill.write",
)


def _safe_sim(value: float) -> float | None:
    """Sanitize similarity score for JSONB serialization (NaN is invalid JSON)."""
    if math.isnan(value):
        return None
    return round(value, 4)


def _plan_mode_active_from_messages(messages: list[dict[str, Any]]) -> bool:
    return any(
        message.get("role") == "system"
        and "Plan mode is active" in str(message.get("content") or "")
        for message in messages
    )


def _dedupe_tool_names(*groups: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for raw in group:
            name = str(raw).strip() if raw is not None else ""
            if name and name not in seen:
                names.append(name)
                seen.add(name)
    return names


def _operator_pinned_tool_names(bot: BotConfig) -> list[str]:
    """Manual pins only; auto-injected chat baseline tools are availability,
    not schema pins for focused/global tool surfaces."""
    return _dedupe_tool_names(
        n for n in (bot.pinned_tools or []) if n not in auto_injected_pin_names()
    )


def _add_local_tool_schemas(
    by_name: dict[str, dict[str, Any]],
    names: tuple[str, ...],
) -> None:
    missing = [name for name in names if name not in by_name]
    if not missing:
        return
    for schema in get_local_tool_schemas(missing):
        tool_name = schema.get("function", {}).get("name")
        if tool_name:
            by_name[tool_name] = schema


def _tool_schemas_for_metadata_domain(domain: str, exposure: str = "ambient") -> list[dict[str, Any]]:
    return get_local_tool_schemas_by_metadata(domain=domain, exposure=exposure)


def _tool_names_for_metadata_domain(domain: str, exposure: str = "ambient") -> list[str]:
    return [
        schema["function"]["name"]
        for schema in _tool_schemas_for_metadata_domain(domain, exposure)
        if schema.get("function", {}).get("name")
    ]


def _compact_tool_usage(name: str, fn: dict[str, Any]) -> str:
    """Compact usage hint with types + enums so the bot can skip get_tool_info.

    Shape: ``tool_name(required: type, [optional: type=default]) — description``.
    Small enums inline as ``mode: a|b|c``; longer enums fall back to the raw
    type. Kept to one line per tool so a ~20-tool index stays under ~5 KB.
    """
    params = fn.get("parameters", {}) or {}
    props = params.get("properties", {}) or {}
    required = set(params.get("required", []) or [])
    parts: list[str] = []
    for p, spec in props.items():
        if not isinstance(spec, dict):
            parts.append(p if p in required else f"[{p}]")
            continue
        t = spec.get("type")
        enum = spec.get("enum")
        if isinstance(enum, list) and 1 <= len(enum) <= 5:
            type_hint = "|".join(str(v) for v in enum)
        elif isinstance(t, list):
            type_hint = "|".join(str(x) for x in t)
        elif isinstance(t, str):
            type_hint = t
        else:
            type_hint = ""
        label = f"{p}: {type_hint}" if type_hint else p
        parts.append(label if p in required else f"[{label}]")
    sig = f"{name}({', '.join(parts)})" if parts else f"{name}()"
    desc = fn.get("description", "")
    # First sentence only, capped at 80 chars
    dot = desc.find(". ")
    if dot > 0:
        desc = desc[:dot]
    if len(desc) > 80:
        desc = desc[:77] + "..."
    return f"{sig} — {desc}" if desc else sig


def _mark_injection_decision(
    inject_decisions: dict[str, str],
    key: str,
    decision: str,
) -> None:
    inject_decisions[key] = decision


async def _run_tool_retrieval(
    *,
    messages: list[dict],
    bot: BotConfig,
    user_message: Any,
    ch_row: Any,
    state: Any,
    correlation_id: Any,
    session_id: Any,
    client_id: Any,
    context_profile: Any,
    tool_surface_policy: str | None,
    required_tool_names: list[str] | tuple[str, ...] | None,
    ledger: Any,
) -> AsyncGenerator[dict[str, Any], None]:
    """Tool-RAG retrieval + policy gate + pinned/retrieved merge + compact
    unretrieved-tool index injection. Writes `pre_selected_tools`,
    `authorized_names`, `tool_discovery_info` to ``out_state``. Only called
    when `bot.tool_retrieval` is on — caller keeps the gate."""
    tagged_tool_names = state.tagged_tool_names
    tagged_skill_names = state.tagged_skill_names
    inject_decisions = ledger.inject_decisions
    budget_can_afford = ledger.can_afford
    budget_consume = ledger.consume
    out_state = state
    _enrolled_tool_names: list[str] = []
    if bot.id:
        try:
            from app.services.tool_enrollment import get_enrolled_tool_names as _get_enrolled_tools
            _enrolled_tool_names = await _get_enrolled_tools(bot.id)
        except Exception:
            logger.warning("Failed to load enrolled tools for %s", bot.id, exc_info=True)

    by_name = await _all_tool_schemas_by_name(
        bot, enrolled_tool_names=_enrolled_tool_names,
    ) if (
        bot.local_tools or bot.mcp_servers or bot.client_tools
        or bot.pinned_tools or _enrolled_tool_names or required_tool_names
    ) else {}
    if required_tool_names:
        _add_local_tool_schemas(by_name, tuple(str(n) for n in required_tool_names if n))
    if bot.tool_retrieval or bot.tool_discovery:
        for _schema in _tool_schemas_for_metadata_domain("tool_schema"):
            by_name[_schema["function"]["name"]] = _schema
    if bot.tool_discovery:
        for _schema in _tool_schemas_for_metadata_domain("tool_discovery"):
            by_name[_schema["function"]["name"]] = _schema
    for _skill_schema in get_local_tool_schemas_by_metadata(
        domain="skill_access",
        exposure="ambient",
    ):
        by_name[_skill_schema["function"]["name"]] = _skill_schema
    _plan_mode_active = _plan_mode_active_from_messages(messages)
    _plan_mode_pins = list(plan_mode_control_tool_names()) if _plan_mode_active else []
    if _plan_mode_active:
        _add_local_tool_schemas(by_name, tuple(_plan_mode_pins))

    _surface_policy = (
        tool_surface_policy
        if tool_surface_policy in {"focused_escape", "strict", "full"}
        else "focused_escape"
    )
    deterministic_capability_surfaces = {
        "memory_flush": _MEMORY_FLUSH_TOOL_CAPABILITIES,
        "memory_hygiene": _MEMORY_HYGIENE_TOOL_CAPABILITIES,
        "skill_review": _SKILL_REVIEW_TOOL_CAPABILITIES,
    }
    profile_surface_name = getattr(context_profile, "name", None)
    surface_capabilities = deterministic_capability_surfaces.get(profile_surface_name)
    if surface_capabilities:
        for capability in surface_capabilities:
            for _schema in get_local_tool_schemas_by_metadata(capability=capability):
                by_name[_schema["function"]["name"]] = _schema
    _authorized_names: set[str] = set(by_name.keys())
    out_state["authorized_names"] = _authorized_names

    th = (
        bot.tool_similarity_threshold
        if bot.tool_similarity_threshold is not None
        else settings.TOOL_RETRIEVAL_THRESHOLD
    )

    # Heartbeat surfaces are deterministic: pinned ∪ tagged ∪ injected always
    # survive; enrolled tools fill remaining budget; retrieval only narrows
    # the over-cap remainder; discovery hatches are suppressed entirely. See
    # _compose_heartbeat_tool_surface() and the heartbeat-tool-surface entry
    # in docs/architecture-decisions.md.
    is_heartbeat_surface = (
        getattr(context_profile, "name", None) == "heartbeat"
    )

    if is_heartbeat_surface and by_name:
        (
            pre_selected_tools,
            _hb_authorized,
            retrieved,
            tool_sim,
            tool_candidates,
            heartbeat_trace,
        ) = await _compose_heartbeat_tool_surface(
            bot=bot,
            by_name=by_name,
            enrolled_tool_names=_enrolled_tool_names,
            tagged_tool_names=tagged_tool_names,
            tagged_skill_names=tagged_skill_names,
            required_tool_names=required_tool_names,
            plan_mode_active=_plan_mode_active,
            user_message=user_message,
            threshold=th,
            ch_row=ch_row,
        )
        _authorized_names = _hb_authorized
        out_state["authorized_names"] = _authorized_names

        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="tool_retrieval",
                count=len(retrieved),
                data={
                    "best_similarity": _safe_sim(tool_sim),
                    "threshold": th,
                    "selected": [t["function"]["name"] for t in retrieved],
                    "skipped": None if heartbeat_trace["retrieval_ran"] else "pinned_sufficient",
                    "heartbeat_surface": heartbeat_trace,
                },
            ))

        out_state["tool_discovery_info"] = {
            "tool_retrieval_enabled": True,
            "tool_discovery_enabled": bool(bot.tool_discovery),
            "threshold": th,
            "pool_total": len(by_name),
            "pinned": list(bot.pinned_tools or []),
            "included": sorted(by_name.keys()),
            "enrolled_working_set": list(_enrolled_tool_names),
            "retrieved": [t["function"]["name"] for t in retrieved],
            "retrieved_count": len(retrieved),
            "tool_surface": _surface_policy,
            "excluded_broad_pin_count": 0,
            "top_candidates": tool_candidates[:5] if tool_candidates else [],
            "best_similarity": _safe_sim(tool_sim),
            "unretrieved_count": 0,
            "heartbeat_surface": heartbeat_trace,
        }
        out_state["pre_selected_tools"] = pre_selected_tools
        return

    if surface_capabilities and by_name:
        allowed_names = _dedupe_tool_names(*(
            get_local_tool_names_by_metadata(capability=capability)
            for capability in surface_capabilities
        ))
        pre_selected_tools = [by_name[name] for name in allowed_names if name in by_name]
        _authorized_names = {tool["function"]["name"] for tool in pre_selected_tools}
        out_state["authorized_names"] = _authorized_names
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="tool_retrieval",
                count=0,
                data={
                    "best_similarity": None,
                    "threshold": th,
                    "selected": [],
                    "skipped": f"{profile_surface_name}_metadata_surface",
                    "metadata_capabilities": list(surface_capabilities),
                },
            ))
        out_state["tool_discovery_info"] = {
            "tool_retrieval_enabled": False,
            "tool_discovery_enabled": False,
            "threshold": th,
            "pool_total": len(by_name),
            "pinned": list(bot.pinned_tools or []),
            "required_tools": list(required_tool_names or []),
            "required_tools_missing": [],
            "included": sorted(by_name.keys()),
            "enrolled_working_set": list(_enrolled_tool_names),
            "retrieved": [],
            "retrieved_count": 0,
            "tool_surface": str(profile_surface_name),
            "metadata_capabilities": list(surface_capabilities),
            "top_candidates": [],
            "best_similarity": None,
            "unretrieved_count": max(0, len(by_name) - len(_authorized_names)),
        }
        out_state["pre_selected_tools"] = pre_selected_tools
        return

    retrieved, tool_sim, tool_candidates = await retrieve_tools(
        user_message,
        bot.local_tools,
        bot.mcp_servers,
        threshold=th,
        discover_all=bot.tool_discovery,
        respect_exposure=True,
    )
    _ch_disabled_tools = set(getattr(ch_row, "local_tools_disabled", None) or []) if ch_row else set()
    if _ch_disabled_tools:
        retrieved = [t for t in retrieved if t.get("function", {}).get("name") not in _ch_disabled_tools]
    if settings.TOOL_POLICY_ENABLED and retrieved:
        from app.db.engine import async_session as _policy_session_factory
        from app.services.tool_policies import evaluate_tool_policy
        async with _policy_session_factory() as _pol_db:
            _policy_allowed = []
            for _rt in retrieved:
                _rn = _rt.get("function", {}).get("name")
                if _rn and _rn not in _authorized_names:
                    _decision = await evaluate_tool_policy(_pol_db, bot.id, _rn, {})
                    if _decision.action == "deny":
                        continue
                _policy_allowed.append(_rt)
            retrieved = _policy_allowed
    for _rt in retrieved:
        _rn = _rt.get("function", {}).get("name")
        if _rn:
            _authorized_names.add(_rn)
            if _rn not in by_name:
                by_name[_rn] = _rt

    if correlation_id is not None:
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="tool_retrieval",
            count=len(retrieved),
            data={"best_similarity": _safe_sim(tool_sim), "threshold": th,
                  "selected": [t["function"]["name"] for t in retrieved],
                  "top_candidates": tool_candidates},
        ))

    pre_selected_tools: list[dict[str, Any]] | None = None
    if by_name:
        _operator_pinned = _operator_pinned_tool_names(bot)
        if _surface_policy == "full":
            _effective_pinned = _dedupe_tool_names(
                required_tool_names,
                _operator_pinned,
                tagged_tool_names,
            )
            if bot.tool_retrieval or bot.tool_discovery:
                _effective_pinned = _dedupe_tool_names(
                    _effective_pinned,
                    _tool_names_for_metadata_domain("tool_schema"),
                )
            if bot.tool_discovery:
                _effective_pinned = _dedupe_tool_names(
                    _effective_pinned,
                    _tool_names_for_metadata_domain("tool_discovery"),
                )
            if _enrolled_tool_names:
                _effective_pinned = _dedupe_tool_names(_effective_pinned, _enrolled_tool_names)
            if bot.skills and (context_profile.allow_skill_index or tagged_skill_names):
                _effective_pinned = _dedupe_tool_names(
                    _effective_pinned,
                    [
                        schema["function"]["name"]
                        for schema in get_local_tool_schemas_by_metadata(
                            domain="skill_access",
                            exposure="ambient",
                        )
                    ],
                )
        elif _surface_policy == "focused_escape":
            _effective_pinned = _dedupe_tool_names(
                required_tool_names,
                _operator_pinned,
                tagged_tool_names,
            )
            if bot.tool_retrieval or bot.tool_discovery:
                _effective_pinned = _dedupe_tool_names(
                    _effective_pinned,
                    _tool_names_for_metadata_domain("tool_schema"),
                )
            if bot.tool_discovery:
                _effective_pinned = _dedupe_tool_names(
                    _effective_pinned,
                    _tool_names_for_metadata_domain("tool_discovery"),
                )
            if tagged_skill_names or (bot.skills and context_profile.allow_skill_index):
                _effective_pinned = _dedupe_tool_names(
                    _effective_pinned,
                    [
                        schema["function"]["name"]
                        for schema in get_local_tool_schemas_by_metadata(
                            domain="skill_access",
                            exposure="ambient",
                        )
                    ],
                )
        else:
            _effective_pinned = _dedupe_tool_names(
                required_tool_names,
                _operator_pinned,
                tagged_tool_names,
            )
            if tagged_skill_names:
                _effective_pinned = _dedupe_tool_names(
                    _effective_pinned,
                    [
                        schema["function"]["name"]
                        for schema in get_local_tool_schemas_by_metadata(
                            domain="skill_access",
                            exposure="ambient",
                        )
                    ],
                )
        if _plan_mode_pins:
            _effective_pinned = list(dict.fromkeys([*_effective_pinned, *_plan_mode_pins]))
        pinned_list = [by_name[n] for n in _effective_pinned if n in by_name]
        _server_pins = {n for n in _effective_pinned if n not in by_name}
        if _server_pins:
            for _tool_name, _schema in by_name.items():
                if get_mcp_server_for_tool(_tool_name) in _server_pins:
                    pinned_list.append(_schema)
        client_only = get_client_tool_schemas(bot.client_tools)
        merged = _merge_tool_schemas(pinned_list, retrieved, client_only)
        if not merged:
            pre_selected_tools = list(by_name.values()) if _surface_policy == "full" else []
        else:
            pre_selected_tools = merged

        _retrieved_names = {t["function"]["name"] for t in pre_selected_tools}
        if _surface_policy != "full":
            _authorized_names = set(_retrieved_names)
            out_state["authorized_names"] = _authorized_names
        _discovery_tool_names = {
            *_tool_names_for_metadata_domain("tool_schema"),
            *_tool_names_for_metadata_domain("tool_discovery"),
        }
        _unretrieved = [
            (n, s["function"])
            for n, s in by_name.items()
            if n not in _retrieved_names and n not in _discovery_tool_names
        ]
        if _unretrieved:
            _index_lines = "\n".join(
                f"  • {_compact_tool_usage(n, fn)}" for n, fn in _unretrieved
            )
            _header = (
                "You have MORE tools available than what's currently loaded. "
                "BEFORE producing a best-effort answer — or saying you don't have a tool — "
                "call get_tool_info(tool_name=\"<name>\") for any entry below that could "
                "plausibly apply. These lines are an index; the full schema is only accessible "
                "via get_tool_info."
            )
            if bot.tool_discovery:
                _header += (
                    " If the right tool isn't in this list, call "
                    "search_tools(query=\"...\") to semantically search the full pool "
                    "BEFORE giving up."
                )
            _header += (
                " Acting without fetching the schema when a relevant tool exists "
                "is the primary source of wrong/missing actions.\n"
            )
            _tool_idx_content = _header + _index_lines
            if not context_profile.allow_tool_index:
                _mark_injection_decision(inject_decisions, "tool_index", "skipped_by_profile")
            elif budget_can_afford(_tool_idx_content):
                messages.append({"role": "system", "content": _tool_idx_content})
                budget_consume("tool_index", _tool_idx_content)
                _mark_injection_decision(inject_decisions, "tool_index", "admitted")
                yield {"type": "tool_index", "unretrieved_count": len(_unretrieved)}
            else:
                _mark_injection_decision(inject_decisions, "tool_index", "skipped_by_budget")
                logger.info("Budget: skipping tool index hints (%d tools)", len(_unretrieved))
        elif context_profile.allow_tool_index:
            _mark_injection_decision(inject_decisions, "tool_index", "skipped_empty")

        out_state["tool_discovery_info"] = {
            "tool_retrieval_enabled": True,
            "tool_discovery_enabled": bool(bot.tool_discovery),
            "threshold": th,
            "pool_total": len(by_name),
            "pinned": list(bot.pinned_tools or []),
            "required_tools": list(required_tool_names or []),
            "required_tools_missing": [
                str(n) for n in (required_tool_names or [])
                if str(n) not in by_name
            ],
            "included": sorted(by_name.keys()),
            "enrolled_working_set": list(_enrolled_tool_names),
            "retrieved": [t["function"]["name"] for t in retrieved],
            "retrieved_count": len(retrieved),
            "tool_surface": _surface_policy,
            "excluded_broad_pin_count": len({
                n for n in (bot.pinned_tools or [])
                if n in by_name and n not in _retrieved_names
            }) if _surface_policy != "full" else 0,
            "baseline_pins_filtered": [
                n for n in (bot.pinned_tools or [])
                if n in auto_injected_pin_names() and n in by_name
            ],
            "operator_pins": list(_operator_pinned),
            "top_candidates": tool_candidates[:5] if tool_candidates else [],
            "best_similarity": _safe_sim(tool_sim),
            "unretrieved_count": len(_unretrieved) if _unretrieved else 0,
        }

    out_state["pre_selected_tools"] = pre_selected_tools


