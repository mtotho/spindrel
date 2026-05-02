"""Security audit logging for the agent server.

Structured logging for outbound HTTP requests and high-privilege tool executions.
All entries go to the ``security.audit`` logger at INFO level.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("security.audit")

_MAX_ARGS_LEN = 200


def _is_enabled() -> bool:
    try:
        from app.config import settings
        return settings.SECURITY_AUDIT_ENABLED
    except Exception:
        return True  # fail-open for logging


def log_outbound_request(
    *,
    url: str,
    method: str,
    tool_name: str | None = None,
    bot_id: str | None = None,
    channel_id: str | None = None,
) -> None:
    """Log an outbound HTTP request made by a tool or dispatcher."""
    if not _is_enabled():
        return
    logger.info(
        "outbound_request method=%s url=%s tool=%s bot=%s channel=%s",
        method,
        url,
        tool_name or "-",
        bot_id or "-",
        channel_id or "-",
    )


def log_tool_execution(
    *,
    tool_name: str,
    safety_tier: str,
    bot_id: str | None = None,
    channel_id: str | None = None,
    arguments_summary: str = "",
) -> None:
    """Log execution of an exec_capable or control_plane tool."""
    if not _is_enabled():
        return
    truncated_args = arguments_summary[:_MAX_ARGS_LEN] if arguments_summary else "-"
    logger.info(
        "tool_exec tool=%s tier=%s bot=%s channel=%s args=%s",
        tool_name,
        safety_tier,
        bot_id or "-",
        channel_id or "-",
        truncated_args,
    )


def log_self_mutation(
    *,
    bot_id: str,
    field: str,
    before: object,
    after: object,
    rationale: str,
    origin_kind: str | None,
    refused: bool = False,
    reason: str = "",
) -> None:
    """Log a bot proposing a config change to its own row.

    Self-mutation is allowed by design (the configurator skill needs it), but
    every event lands in this audit stream so an operator can review history
    and catch drift even if individual approvals looked reasonable.
    """
    if not _is_enabled():
        return
    truncated_rat = (rationale or "")[:_MAX_ARGS_LEN]
    logger.info(
        "bot_self_mutation bot=%s field=%s before=%r after=%r origin=%s refused=%s reason=%s rationale=%s",
        bot_id,
        field,
        before,
        after,
        origin_kind or "-",
        refused,
        reason or "-",
        truncated_rat,
    )
