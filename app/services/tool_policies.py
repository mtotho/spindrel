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


def _match_conditions(conditions: dict | None, arguments: dict[str, Any]) -> bool:
    """Check if rule conditions match the tool arguments.

    conditions format:
    {
        "arguments": {
            "command": {"pattern": "^rm "},    # regex
            "path": {"prefix": "/etc/"},       # string prefix
            "mode": {"in": ["delete", "force"]}  # value in list
        }
    }

    Empty/null conditions always match.
    """
    if not conditions:
        return True
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
) -> PolicyDecision:
    """Evaluate policy rules for a tool call. Returns the decision.

    Evaluation order:
    1. Collect enabled rules where bot_id matches OR bot_id IS NULL (global)
    2. Filter by tool_name match (exact or glob)
    3. Order by priority ASC (already sorted from DB)
    4. Bot-specific rules take precedence over global at same priority
    5. First matching rule wins
    6. No match → default allow
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
        if _match_conditions(rule.conditions, arguments):
            return PolicyDecision(
                action=rule.action,
                rule_id=str(rule.id),
                reason=rule.reason,
                timeout=rule.approval_timeout,
            )

    # No rule matched — use configured default
    default_action = settings.TOOL_POLICY_DEFAULT_ACTION
    return PolicyDecision(
        action=default_action,
        reason=f"No matching policy rule (default: {default_action})",
    )
