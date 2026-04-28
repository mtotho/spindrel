"""Coordination layer for client-side tool execution.

When the agent loop encounters a client tool, it yields a tool_request event
over SSE and awaits a Future here.  The POST /chat/tool_result endpoint
resolves the future so the loop can continue.
"""

import asyncio
import logging

from app.agent.pending_registry import PendingRegistry

logger = logging.getLogger(__name__)

_pending: dict[str, asyncio.Future[str]] = {}
_registry = PendingRegistry[str](label="request", logger=logger)
_registry.bind(_pending)

CLIENT_TOOL_TIMEOUT = 120.0  # seconds


def _sync_registry() -> PendingRegistry[str]:
    if _registry.pending is not _pending:
        _registry.bind(_pending)
    return _registry


def create_pending(request_id: str) -> asyncio.Future[str]:
    return _sync_registry().create(request_id)


def resolve_pending(request_id: str, result: str) -> bool:
    return _sync_registry().resolve(request_id, result)


def expire_pending(request_id: str) -> bool:
    """Remove a timed-out client-tool request from the rendezvous registry."""
    return _sync_registry().discard(request_id)


def pending_count() -> int:
    return _sync_registry().count()


def clear_pending() -> None:
    _sync_registry().clear()
