"""Coordination layer for tool approval requests.

When a tool policy returns require_approval, the agent loop yields an
approval_request event and awaits a Future here. The POST /api/v1/approvals/{id}/decide
endpoint resolves the future so the loop can continue.

Mirrors the pattern in pending.py (client tool execution).
"""

import asyncio
import logging

from app.agent.pending_registry import PendingRegistry

logger = logging.getLogger(__name__)

_pending: dict[str, asyncio.Future[str]] = {}
_registry = PendingRegistry[str](label="approval", logger=logger)
_registry.bind(_pending)


def _sync_registry() -> PendingRegistry[str]:
    if _registry.pending is not _pending:
        _registry.bind(_pending)
    return _registry


def create_approval_pending(approval_id: str) -> asyncio.Future[str]:
    """Create a Future for an approval request. Returns the Future to await."""
    return _sync_registry().create(approval_id)


def resolve_approval(approval_id: str, verdict: str) -> bool:
    """Resolve an approval Future with 'approved' or 'denied'. Returns False if not found."""
    return _sync_registry().resolve(approval_id, verdict)


def cancel_approval(approval_id: str) -> bool:
    """Cancel a pending approval (e.g. on expiry). Returns False if not found."""
    return _sync_registry().cancel(approval_id, "expired")


def pending_count() -> int:
    return _sync_registry().count()
