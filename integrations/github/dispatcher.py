"""Routes GitHub webhook event types to their handlers."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from integrations.github.handlers import handle_check_run, handle_workflow_run

logger = logging.getLogger(__name__)

# Map of event type → handler function
EVENT_HANDLERS: dict[str, Any] = {
    "workflow_run": handle_workflow_run,
    "check_run": handle_check_run,
}


async def dispatch(event_type: str, payload: dict[str, Any], db: AsyncSession) -> dict | None:
    """Dispatch a GitHub event to the appropriate handler.

    Returns the handler result or None if no handler matched.
    """
    handler = EVENT_HANDLERS.get(event_type)
    if handler is None:
        logger.debug("No handler for GitHub event type: %s", event_type)
        return None

    logger.info("Dispatching GitHub event: %s", event_type)
    return await handler(payload, db)
