"""Coordination layer for client-side tool execution.

When the agent loop encounters a client tool, it yields a tool_request event
over SSE and awaits a Future here.  The POST /chat/tool_result endpoint
resolves the future so the loop can continue.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_pending: dict[str, asyncio.Future[str]] = {}

CLIENT_TOOL_TIMEOUT = 120.0  # seconds


def create_pending(request_id: str) -> asyncio.Future[str]:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending[request_id] = future
    logger.debug("Created pending request %s (%d active)", request_id, len(_pending))
    return future


def resolve_pending(request_id: str, result: str) -> bool:
    future = _pending.pop(request_id, None)
    if future is None:
        logger.warning("No pending request for %s", request_id)
        return False
    if future.done():
        logger.warning("Pending request %s already resolved", request_id)
        return False
    future.set_result(result)
    logger.debug("Resolved pending request %s", request_id)
    return True
