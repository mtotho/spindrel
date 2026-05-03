"""Heartbeat-mode tool-surface composition."""
from __future__ import annotations

import json
from typing import Any

from app.agent.bots import BotConfig
from app.agent.channel_overrides import (
    auto_injected_pin_names,
    discovery_hatch_tool_names,
    plan_mode_control_tool_names,
)
from app.agent.message_utils import _merge_tool_schemas
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas
from app.tools.registry import get_local_tool_schemas_by_metadata


def _tool_schemas_for_metadata_domain(domain: str, exposure: str = "ambient") -> list[dict[str, Any]]:
    return get_local_tool_schemas_by_metadata(domain=domain, exposure=exposure)


def _tool_names_for_metadata_domain(domain: str, exposure: str = "ambient") -> list[str]:
    return [
        schema["function"]["name"]
        for schema in _tool_schemas_for_metadata_domain(domain, exposure)
        if schema.get("function", {}).get("name")
    ]


def _estimate_schema_tokens(schema: dict) -> int:
    """Rough token estimate for a single tool schema. ~4 chars/token."""
    try:
        return max(1, len(json.dumps(schema, ensure_ascii=False)) // 4)
    except Exception:
        return 200  # conservative fallback


async def _compose_heartbeat_tool_surface(
    *,
    bot: BotConfig,
    by_name: dict[str, dict],
    enrolled_tool_names: list[str],
    tagged_tool_names: list[str],
    tagged_skill_names: list[str],
    required_tool_names: list[str] | tuple[str, ...] | None,
    plan_mode_active: bool,
    user_message: Any,
    threshold: float,
    ch_row: Any,
) -> tuple[
    list[dict[str, Any]],     # pre_selected_tools
    set[str],                 # authorized_names
    list[dict[str, Any]],     # retrieved (post-narrowing, possibly empty)
    Any,                      # tool_sim
    list,                     # tool_candidates
    dict[str, Any],           # heartbeat_surface trace block
]:
    """Deterministic heartbeat tool-surface composition.

    Order:
      1. Always-included: operator-curated bot.pinned_tools ∪ tagged_tool_names
         ∪ plan-mode pins.
         These never compete in retrieval and never get dropped.
      2. Required tools from the heartbeat execution config are included even
         when they overlap the chat baseline.

    General bot tool enrollments are intentionally ignored for heartbeats.
    Those are learned from chat/task usage and are too broad for deterministic
    autonomous runs.

    Discovery hatches (`get_tool_info`, `search_tools`,
    `list_tool_signatures`) are intentionally NOT added here regardless of
    headroom — heartbeat surfaces are configured, not discovered.
    `run_script` is exposed only when explicitly pinned/tagged/required.
    """
    count_cap = max(1, int(settings.HEARTBEAT_ENROLLED_TOOL_COUNT_CAP or 25))
    token_cap = max(500, int(settings.HEARTBEAT_ENROLLED_TOOL_TOKEN_CAP or 6000))
    discovery_hatches = discovery_hatch_tool_names()
    auto_injected_pins = auto_injected_pin_names()
    plan_mode_tools = plan_mode_control_tool_names()

    # --- Step 1: always-included pin set (deterministic order) ---
    # apply_auto_injections() and context admission add chat/workspace baseline
    # helpers to bot.pinned_tools. Heartbeats treat those as availability, not
    # schema pins, because baseline helpers are high-breadth escape hatches.
    pin_set: list[str] = []
    seen: set[str] = set()

    def _add(name: str, *, allow_baseline: bool = False) -> None:
        if not name or name in seen or name not in by_name:
            return
        if name in discovery_hatches:
            return
        if not allow_baseline and name in auto_injected_pins:
            return
        pin_set.append(name)
        seen.add(name)

    for n in (bot.pinned_tools or []):
        _add(n)
    for n in (required_tool_names or []):
        _add(str(n), allow_baseline=True)
    for n in tagged_tool_names:
        _add(n, allow_baseline=True)
    if tagged_skill_names:
        for n in _tool_names_for_metadata_domain("skill_access"):
            _add(n, allow_baseline=True)
    if plan_mode_active:
        for n in plan_mode_tools:
            _add(n, allow_baseline=True)

    pin_token_total = sum(_estimate_schema_tokens(by_name[n]) for n in pin_set)

    enrolled_included: list[str] = []
    enrolled_token_total = 0
    enrolled_dropped_for_budget: list[str] = []
    enrolled_ignored = [
        name for name in enrolled_tool_names
        if name not in seen and name in by_name
    ]

    retrieved: list[dict[str, Any]] = []
    tool_sim: float = 0.0
    tool_candidates: list = []
    enrolled_recovered: list[str] = []

    # --- Build the final exposed list and authorized set ---
    pinned_schemas = [by_name[n] for n in pin_set + enrolled_included]
    client_only = get_client_tool_schemas(bot.client_tools)
    pre_selected = _merge_tool_schemas(pinned_schemas, retrieved, client_only)

    authorized_names = {t["function"]["name"] for t in pre_selected}

    enrolled_dropped_after_retrieval = [
        n for n in enrolled_dropped_for_budget if n not in set(enrolled_recovered)
    ]

    # "Curated" means an operator-set pin beyond the auto-injected baseline
    # (skill/channel/self-inspect tools that apply_auto_injections adds to
    # every bot). Without curation, the warning surfaces in the trace so
    # the operator knows budget is being burned on system defaults.
    warning = (
        "heartbeat_no_required_or_curated_tools"
        if not pin_set
        else None
    )

    heartbeat_surface = {
        "pin_set": list(pin_set),
        "required_tools": list(required_tool_names or []),
        "required_tools_missing": [
            str(n) for n in (required_tool_names or [])
            if str(n) not in by_name
        ],
        "baseline_pins_filtered": [
            n for n in (bot.pinned_tools or [])
            if n in auto_injected_pins and n in by_name
        ],
        "enrolled_included": list(enrolled_included),
        "enrolled_ignored": list(enrolled_ignored),
        "enrolled_dropped_for_budget": list(enrolled_dropped_for_budget),
        "enrolled_recovered_via_retrieval": list(enrolled_recovered),
        "enrolled_dropped_after_retrieval": list(enrolled_dropped_after_retrieval),
        "budget_used_tokens": pin_token_total + enrolled_token_total,
        "budget_count_cap": count_cap,
        "budget_token_cap": token_cap,
        "retrieval_ran": bool(enrolled_dropped_for_budget),
        "warning": warning,
    }

    return pre_selected, authorized_names, retrieved, tool_sim, tool_candidates, heartbeat_surface
