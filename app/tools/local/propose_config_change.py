"""propose_config_change — ambient config-fix tool used by the configurator skill.

Bot emits a single narrow proposal (one scope, one field, one new_value) with
rationale + evidence. Registered as ``safety_tier="mutating"`` so the standard
tool-policy approval gate fires on every call — the user sees the args and
decides Approve/Reject inline. On approve, the tool performs the PATCH against
the matching admin surface. On reject, the tool never runs.

Per-scope allowlists mirror the shape of the existing orchestrator audit
pipeline PATCH whitelists (``app/data/system_pipelines/orchestrator.*.yaml``).
They are intentionally narrow — fields outside the list are refused rather than
silently ignored.
"""
from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.tools.registry import register

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-scope field allowlists. Any field not listed here is refused at
# validation time. Keep these in lock-step with the skill sub-pages under
# ``skills/configurator/``.
# ---------------------------------------------------------------------------

_BOT_ALLOWED: dict[str, type | tuple[type, ...]] = {
    "pinned_tools": list,
    "tool_similarity_threshold": (int, float),
    "system_prompt": str,
    "memory_scheme": str,
    "model": str,
    "provider_id": str,
    "tool_discovery": bool,
}

_CHANNEL_ALLOWED_TOPLEVEL: dict[str, type | tuple[type, ...]] = {
    "pipeline_mode": str,   # "auto" | "on" | "off"
    "layout_mode": str,     # "full" | "rail-header-chat" | "rail-chat" | "dashboard-only"
}

_CHANNEL_ALLOWED_CONFIG: frozenset[str] = frozenset({
    "pinned_widgets",
    "heartbeat_interval_minutes",
    "heartbeat_context_lookback",
})

_PIPELINE_MODE_VALUES = {"auto", "on", "off"}
_LAYOUT_MODE_VALUES = {"full", "rail-header-chat", "rail-chat", "dashboard-only"}
_MEMORY_SCHEME_VALUES = {"workspace-files"}
_TOOL_DISCOVERY_VALUES = {"on", "off"}


def _refuse(scope: str, field: str, reason: str) -> str:
    return json.dumps({
        "applied": False,
        "error": f"Refused: scope={scope} field={field}: {reason}",
    }, ensure_ascii=False)


def _applied(scope: str, target_id: str, field: str, before: Any, after: Any, rationale: str) -> str:
    return json.dumps({
        "applied": True,
        "scope": scope,
        "target_id": target_id,
        "field": field,
        "before": before,
        "after": after,
        "rationale": rationale,
    }, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Scope handlers
# ---------------------------------------------------------------------------

async def _apply_bot(target_id: str, field: str, new_value: Any, rationale: str) -> str:
    if field not in _BOT_ALLOWED:
        return _refuse("bot", field, f"not in bot allowlist {sorted(_BOT_ALLOWED)}")

    expected_types = _BOT_ALLOWED[field]
    if not isinstance(new_value, expected_types):
        return _refuse("bot", field, f"expected {expected_types}, got {type(new_value).__name__}")

    if field == "memory_scheme" and new_value not in _MEMORY_SCHEME_VALUES:
        return _refuse("bot", field, f"value must be one of {sorted(_MEMORY_SCHEME_VALUES)}")
    if field == "tool_discovery":
        # Accept bool (as declared) but also tolerate the "on"/"off" string form
        # the skill uses in its examples.
        if isinstance(new_value, str):
            if new_value not in _TOOL_DISCOVERY_VALUES:
                return _refuse("bot", field, f"value must be one of {sorted(_TOOL_DISCOVERY_VALUES)}")
            new_value = (new_value == "on")
    if field == "tool_similarity_threshold":
        if not (0.0 <= float(new_value) <= 1.0):
            return _refuse("bot", field, "threshold must be between 0.0 and 1.0")

    from app.db.engine import async_session
    from app.db.models import Bot

    async with async_session() as db:
        row = await db.get(Bot, target_id)
        if row is None:
            return _refuse("bot", field, f"bot '{target_id}' not found")
        before = getattr(row, field, None)
        setattr(row, field, new_value)
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    # Reload in-process bot cache so subsequent turns see the change.
    try:
        from app.agent.bots import reload_bots
        await reload_bots()
    except Exception:
        logger.debug("reload_bots failed after propose_config_change", exc_info=True)

    return _applied("bot", target_id, field, before, new_value, rationale)


async def _apply_channel(target_id: str, field: str, new_value: Any, rationale: str) -> str:
    from sqlalchemy.orm.attributes import flag_modified
    from app.db.engine import async_session
    from app.db.models import Channel

    # Support both top-level fields (pipeline_mode, layout_mode) and config.<key>
    is_config_key = field.startswith("config.")
    if is_config_key:
        config_key = field[len("config."):]
        if config_key not in _CHANNEL_ALLOWED_CONFIG:
            return _refuse("channel", field, f"config key not in allowlist {sorted(_CHANNEL_ALLOWED_CONFIG)}")
    else:
        if field not in _CHANNEL_ALLOWED_TOPLEVEL:
            return _refuse("channel", field, f"not in channel allowlist {sorted(_CHANNEL_ALLOWED_TOPLEVEL)} or config.<key>")
        expected_types = _CHANNEL_ALLOWED_TOPLEVEL[field]
        if not isinstance(new_value, expected_types):
            return _refuse("channel", field, f"expected {expected_types}, got {type(new_value).__name__}")
        if field == "pipeline_mode" and new_value not in _PIPELINE_MODE_VALUES:
            return _refuse("channel", field, f"value must be one of {sorted(_PIPELINE_MODE_VALUES)}")
        if field == "layout_mode" and new_value not in _LAYOUT_MODE_VALUES:
            return _refuse("channel", field, f"value must be one of {sorted(_LAYOUT_MODE_VALUES)}")

    async with async_session() as db:
        # target_id may be a UUID string or channel slug — try UUID first
        import uuid
        row = None
        try:
            row = await db.get(Channel, uuid.UUID(target_id))
        except (ValueError, TypeError):
            pass
        if row is None:
            from sqlalchemy import select
            row = (await db.execute(select(Channel).where(Channel.client_id == target_id))).scalar_one_or_none()
        if row is None:
            return _refuse("channel", field, f"channel '{target_id}' not found")

        # All the allowed channel fields live inside channel.config JSONB
        # (pipeline_mode, layout_mode, and config.<key> entries). Mirrors the
        # storage pattern at app/routers/api_v1_admin/channels.py.
        cfg = copy.deepcopy(row.config or {})
        if field in ("pipeline_mode", "layout_mode"):
            key = field
        else:
            key = field[len("config."):]
        before = cfg.get(key)
        cfg[key] = new_value
        row.config = cfg
        flag_modified(row, "config")
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return _applied("channel", target_id, field, before, new_value, rationale)


async def _apply_integration(target_id: str, field: str, new_value: Any, rationale: str) -> str:
    from app.db.engine import async_session
    from app.services.integration_settings import set_status, update_settings

    if field == "enabled":
        if not isinstance(new_value, bool):
            return _refuse("integration", field, f"expected bool, got {type(new_value).__name__}")
        before = None
        try:
            from app.services.integration_settings import get_status
            before = get_status(target_id)
        except Exception:
            pass
        await set_status(target_id, "enabled" if new_value else "available")
        return _applied("integration", target_id, field, before, "enabled" if new_value else "available", rationale)

    if not field.startswith("config."):
        return _refuse("integration", field, "only 'enabled' or 'config.<key>' allowed")

    config_key = field[len("config."):]
    if not config_key:
        return _refuse("integration", field, "config key missing")
    if not isinstance(new_value, str):
        # integration_settings stores strings only; cast numerics, refuse dicts.
        if isinstance(new_value, (int, float, bool)):
            new_value = str(new_value)
        else:
            return _refuse("integration", field, f"value must be a string, got {type(new_value).__name__}")

    # Pull setup_vars from the integration manifest so the secret flag is honoured.
    setup_vars: list[dict] = []
    try:
        from app.routers.api_v1_admin.integrations import _get_setup_vars
        setup_vars = _get_setup_vars(target_id)
    except Exception:
        logger.debug("setup_vars lookup failed for integration %s", target_id, exc_info=True)

    async with async_session() as db:
        try:
            from app.services.integration_settings import get_value
            before = get_value(target_id, config_key, "")
        except Exception:
            before = None
        await update_settings(
            integration_id=target_id,
            updates={config_key: new_value},
            setup_vars=setup_vars,
            db=db,
        )

    return _applied("integration", target_id, field, before, new_value, rationale)


# ---------------------------------------------------------------------------
# Tool entry point
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "propose_config_change",
        "description": (
            "Propose ONE narrow change to a bot's, channel's, or integration's "
            "configuration. The user is prompted to approve or reject inline — "
            "on approve, the PATCH fires; on reject, nothing happens. Every call "
            "MUST include concrete evidence (≥2 correlation_ids from get_trace, "
            "or a concrete settings-drift signal). Fields are per-scope "
            "allowlisted — see the configurator skill for the allowed list. Do "
            "NOT bundle multiple changes into one call; emit one proposal at a "
            "time and wait for the user's decision."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["bot", "channel", "integration"],
                    "description": "Which kind of config to change.",
                },
                "target_id": {
                    "type": "string",
                    "description": (
                        "Identifier for the target: bot id (e.g. 'crumb'), "
                        "channel UUID or client_id, or integration slug (e.g. 'frigate')."
                    ),
                },
                "field": {
                    "type": "string",
                    "description": (
                        "Which field to change. Must be in the per-scope allowlist. "
                        "For channel/integration, use 'config.<key>' form to target a "
                        "JSONB config entry (e.g. 'config.heartbeat_interval_minutes')."
                    ),
                },
                "new_value": {
                    "description": "Proposed new value. Type depends on the field.",
                },
                "rationale": {
                    "type": "string",
                    "description": "One sentence explaining why this change will help.",
                },
                "evidence": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "correlation_id": {"type": "string"},
                            "bot_id": {"type": "string"},
                            "signal": {"type": "string"},
                        },
                        "required": ["signal"],
                    },
                    "description": (
                        "Concrete evidence for this proposal. Prefer ≥2 real "
                        "correlation_ids from get_trace, each with a quoted signal."
                    ),
                },
                "diff_preview": {
                    "type": "string",
                    "description": "Short human-readable 'before: ... / after: ...' string.",
                },
            },
            "required": ["scope", "target_id", "field", "new_value", "rationale", "evidence", "diff_preview"],
        },
    },
}, safety_tier="mutating", returns={
    "type": "object",
    "properties": {
        "applied": {"type": "boolean"},
        "scope": {"type": "string"},
        "target_id": {"type": "string"},
        "field": {"type": "string"},
        "before": {},
        "after": {},
        "rationale": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["applied"],
})
async def propose_config_change(
    scope: str,
    target_id: str,
    field: str,
    new_value: Any,
    rationale: str,
    evidence: list[dict],
    diff_preview: str,
) -> str:
    """Apply one narrow config change. Approval is enforced by tool policy."""
    if not isinstance(evidence, list) or len(evidence) < 1:
        return _refuse(scope, field, "evidence must be a non-empty list")
    for item in evidence:
        if not isinstance(item, dict) or not item.get("signal"):
            return _refuse(scope, field, "each evidence item needs a 'signal' string")

    if scope == "bot":
        return await _apply_bot(target_id, field, new_value, rationale)
    if scope == "channel":
        return await _apply_channel(target_id, field, new_value, rationale)
    if scope == "integration":
        return await _apply_integration(target_id, field, new_value, rationale)
    return _refuse(scope, field, f"unknown scope '{scope}'; must be bot | channel | integration")
