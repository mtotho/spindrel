"""Tool policy evaluation engine.

Evaluates tool_policy_rules against a (bot_id, tool_name, arguments) triple.
Rules are loaded from DB, cached briefly, and evaluated in priority order.
"""
import fnmatch
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import ToolPolicyRule

logger = logging.getLogger(__name__)

# In-memory cache: list of enabled rules, refreshed every N seconds
_cache: list[ToolPolicyRule] | None = None
_cache_ts: float = 0.0
_CACHE_TTL = 10.0  # seconds


@dataclass
class PolicyDecision:
    action: str  # "allow" | "deny" | "require_approval"
    rule_id: str | None = None
    reason: str | None = None
    timeout: int = 300
    tier: str | None = None  # safety tier that triggered the decision


# Tier-based default actions (when no explicit rule matches)
_TIER_DEFAULTS: dict[str, str] = {
    "exec_capable": "require_approval",
    "control_plane": "require_approval",
}

# Autonomous-context defaults: when the agent is running unattended
# (heartbeat/task/subagent/hygiene), certain mutating ops require approval by
# default even though the same ops are fine in interactive chat. A user-
# installed ToolPolicyRule still wins — these are only applied when no DB
# rule matches.
_AUTONOMOUS_ORIGINS: frozenset[str] = frozenset({"heartbeat", "task", "subagent", "hygiene"})

# Each entry: (tool_name, arg_matcher, reason). arg_matcher is a callable
# taking the tool arguments dict and returning True if the rule applies.
_ORIGIN_DEFAULTS: list[tuple[str, Any, str]] = [
    (
        "file",
        lambda args: args.get("operation") in {"overwrite", "delete"},
        "Destructive file ops (overwrite/delete) from autonomous runs require approval.",
    ),
    (
        "exec_command",
        lambda _args: True,
        "Shell execution from autonomous runs requires approval.",
    ),
]


async def _load_rules(db: AsyncSession) -> list[ToolPolicyRule]:
    """Load all enabled rules ordered by priority."""
    global _cache, _cache_ts
    now = time.monotonic()
    if _cache is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cache
    stmt = (
        select(ToolPolicyRule)
        .where(ToolPolicyRule.enabled.is_(True))
        .order_by(ToolPolicyRule.priority.asc(), ToolPolicyRule.created_at.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    # Detach from session so cache survives session close
    for r in rows:
        db.expunge(r)
    _cache = rows
    _cache_ts = now
    return rows


def invalidate_cache() -> None:
    """Force reload on next evaluate call (call after rule CRUD)."""
    global _cache, _cache_ts
    _cache = None
    _cache_ts = 0.0


def _match_tool_name(rule_pattern: str, tool_name: str) -> bool:
    """Match rule tool_name against actual tool name. Supports exact, '*' (all), and glob."""
    if rule_pattern == "*":
        return True
    if "*" in rule_pattern or "?" in rule_pattern:
        return fnmatch.fnmatch(tool_name, rule_pattern)
    return rule_pattern == tool_name


def _match_conditions(
    conditions: dict | None,
    arguments: dict[str, Any],
    origin_kind: str | None = None,
) -> bool:
    """Check if rule conditions match the tool arguments + run origin.

    conditions format:
    {
        "arguments": {
            "command": {"pattern": "^rm "},    # regex
            "path": {"prefix": "/etc/"},       # string prefix
            "mode": {"in": ["delete", "force"]}  # value in list
        },
        "origin_kind": {"in": ["heartbeat", "task", "subagent", "hygiene"]},
        "apply_to_autonomous": false,  # shortcut: opt-in to autonomous origins
    }

    **Origin-kind default (since 2026-05):** a rule that does not declare
    ``origin_kind`` (or ``apply_to_autonomous``) is treated as interactive-
    only. Autonomous origins (heartbeat, task, subagent, hygiene) must
    either match a rule with explicit autonomous opt-in or fall through to
    autonomous defaults / tier defaults. This prevents an interactive
    "allow exec_command" rule from silently auto-approving the same tool
    in unattended runs. Override via ``apply_to_autonomous: true`` (matches
    every origin) or an explicit ``origin_kind`` matcher.
    """
    effective_origin = origin_kind or "chat"

    if not conditions:
        # No conditions at all → interactive-only by default (safer post-fix).
        return effective_origin == "chat"

    origin_match = conditions.get("origin_kind")
    apply_to_autonomous = bool(conditions.get("apply_to_autonomous"))

    if origin_match:
        if "in" in origin_match and effective_origin not in origin_match["in"]:
            return False
        if "eq" in origin_match and effective_origin != origin_match["eq"]:
            return False
    elif not apply_to_autonomous and effective_origin != "chat":
        # Rule has no origin_kind matcher and isn't opted into autonomous
        # → only matches interactive chat origin.
        return False

    arg_conditions = conditions.get("arguments")
    if not arg_conditions:
        return True
    for arg_name, matchers in arg_conditions.items():
        arg_value = arguments.get(arg_name)
        if arg_value is None:
            return False
        arg_str = str(arg_value)
        if "pattern" in matchers:
            try:
                if not re.search(matchers["pattern"], arg_str):
                    return False
            except re.error:
                logger.warning("Invalid regex in policy rule condition: %s", matchers["pattern"])
                return False
        if "prefix" in matchers:
            if not arg_str.startswith(matchers["prefix"]):
                return False
        if "in" in matchers:
            if arg_value not in matchers["in"]:
                return False
    return True


async def evaluate_tool_policy(
    db: AsyncSession,
    bot_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    origin_kind: str | None = None,
) -> PolicyDecision:
    """Evaluate policy rules for a tool call. Returns the decision.

    Evaluation order:
    1. Collect enabled rules where bot_id matches OR bot_id IS NULL (global)
    2. Filter by tool_name match (exact or glob)
    3. Order by priority ASC (already sorted from DB)
    4. Bot-specific rules take precedence over global at same priority
    5. First matching rule wins
    6. No match → tier defaults (exec_capable/control_plane → require_approval)
    7. No tier match → global default (TOOL_POLICY_DEFAULT_ACTION)

    *origin_kind* identifies where the call came from (chat/heartbeat/task/
    subagent/hygiene). Rules may target it via `conditions.origin_kind`.
    """
    rules = await _load_rules(db)

    # Filter applicable rules
    candidates = []
    for rule in rules:
        # bot_id filter: rule applies if it's global (NULL) or matches this bot
        if rule.bot_id is not None and rule.bot_id != bot_id:
            continue
        # tool_name filter
        if not _match_tool_name(rule.tool_name, tool_name):
            continue
        candidates.append(rule)

    # Sort: priority ASC, then bot-specific before global at same priority
    candidates.sort(key=lambda r: (r.priority, 0 if r.bot_id is not None else 1))

    for rule in candidates:
        if _match_conditions(rule.conditions, arguments, origin_kind=origin_kind):
            return PolicyDecision(
                action=rule.action,
                rule_id=str(rule.id),
                reason=rule.reason,
                timeout=rule.approval_timeout,
            )

    # No rule matched — apply autonomous-context defaults (if origin is an
    # autonomous run) before falling back to tier defaults and global default.
    if origin_kind in _AUTONOMOUS_ORIGINS:
        for rule_tool, rule_args_matcher, rule_reason in _ORIGIN_DEFAULTS:
            if rule_tool != tool_name and not _match_tool_name(rule_tool, tool_name):
                continue
            try:
                if rule_args_matcher(arguments):
                    return PolicyDecision(
                        action="require_approval",
                        reason=f"[{origin_kind}] {rule_reason}",
                    )
            except Exception:
                # Defensive: never let a matcher bug break tool dispatch.
                logger.warning(
                    "origin-default matcher raised for %s; skipping", rule_tool,
                )

    # Tier defaults — only applied when default_action is NOT "allow".
    default_action = settings.TOOL_POLICY_DEFAULT_ACTION
    if settings.TOOL_POLICY_TIER_GATING and default_action != "allow":
        from app.tools.registry import get_tool_safety_tier
        tier = get_tool_safety_tier(tool_name)
        tier_action = _TIER_DEFAULTS.get(tier)
        if tier_action:
            return PolicyDecision(
                action=tier_action,
                reason=f"Tool safety tier '{tier}' defaults to {tier_action}",
                tier=tier,
            )
    return PolicyDecision(
        action=default_action,
        reason=f"No matching policy rule (default: {default_action})",
    )
