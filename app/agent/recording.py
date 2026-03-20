"""Fire-and-forget DB helpers for recording tool calls and trace events."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.db.engine import async_session
from app.db.models import ToolCall, TraceEvent

logger = logging.getLogger(__name__)


async def _record_tool_call(
    *,
    session_id: uuid.UUID | None,
    client_id: str | None,
    bot_id: str | None,
    tool_name: str,
    tool_type: str,
    server_name: str | None,
    iteration: int,
    arguments: dict,
    result: str | None,
    error: str | None,
    duration_ms: int,
    correlation_id: uuid.UUID | None = None,
) -> None:
    """Fire-and-forget: write a ToolCall row to the DB."""
    try:
        async with async_session() as db:
            db.add(ToolCall(
                session_id=session_id,
                client_id=client_id,
                bot_id=bot_id,
                tool_name=tool_name,
                tool_type=tool_type,
                server_name=server_name,
                iteration=iteration,
                arguments=arguments,
                result=result[:4000] if result else None,
                error=error,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                created_at=datetime.now(timezone.utc),
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to record tool call for %s", tool_name)


async def _record_trace_event(
    *,
    correlation_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    bot_id: str | None,
    client_id: str | None,
    event_type: str,
    event_name: str | None = None,
    count: int | None = None,
    data: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    """Fire-and-forget: write a TraceEvent row to the DB."""
    try:
        async with async_session() as db:
            db.add(TraceEvent(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot_id,
                client_id=client_id,
                event_type=event_type,
                event_name=event_name,
                count=count,
                data=data,
                duration_ms=duration_ms,
                created_at=datetime.now(timezone.utc),
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to record trace event %s", event_type)
