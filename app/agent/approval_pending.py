"""Coordination layer for tool approval requests.

When a tool policy returns require_approval, the agent loop yields an
approval_request event and awaits a Future here. The POST /api/v1/approvals/{id}/decide
endpoint resolves the future so the loop can continue.

Mirrors the pattern in pending.py (client tool execution).
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_pending: dict[str, asyncio.Future[str]] = {}


def create_approval_pending(approval_id: str) -> asyncio.Future[str]:
    """Create a Future for an approval request. Returns the Future to await."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending[approval_id] = future
    logger.debug("Created approval pending %s (%d active)", approval_id, len(_pending))
    return future


def resolve_approval(approval_id: str, verdict: str) -> bool:
    """Resolve an approval Future with 'approved' or 'denied'. Returns False if not found."""
    future = _pending.pop(approval_id, None)
    if future is None:
        logger.warning("No pending approval for %s", approval_id)
        return False
    if future.done():
        logger.warning("Approval %s already resolved", approval_id)
        return False
    future.set_result(verdict)
    logger.debug("Resolved approval %s → %s", approval_id, verdict)
    return True


def cancel_approval(approval_id: str) -> bool:
    """Cancel a pending approval (e.g. on expiry). Returns False if not found."""
    future = _pending.pop(approval_id, None)
    if future is None:
        return False
    if future.done():
        return False
    future.set_result("expired")
    logger.debug("Cancelled approval %s", approval_id)
    return True


def pending_count() -> int:
    return len(_pending)
