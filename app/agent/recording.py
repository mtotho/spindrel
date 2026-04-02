"""Fire-and-forget DB helpers for recording tool calls and trace events."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.db.engine import async_session
from app.db.models import ToolCall, TraceEvent

logger = logging.getLogger(__name__)


def schedule_exec_completion_record(
    *,
    command: str,
    task_id: uuid.UUID,
    session_id: uuid.UUID | None,
    client_id: str | None,
    bot_id: str | None,
    correlation_id: uuid.UUID | None,
    exit_code: int,
    duration_ms: int,
    truncated: bool,
    result_text: str,
    error: str | None = None,
) -> None:
    """Log deferred exec worker results to tool_calls + trace_events."""
    asyncio.create_task(
        _record_exec_completion(
            command=command,
            task_id=task_id,
            session_id=session_id,
            client_id=client_id,
            bot_id=bot_id,
            correlation_id=correlation_id,
            exit_code=exit_code,
            duration_ms=duration_ms,
            truncated=truncated,
            result_text=result_text,
            error=error,
        )
    )


async def _record_exec_completion(
    *,
    command: str,
    task_id: uuid.UUID,
    session_id: uuid.UUID | None,
    client_id: str | None,
    bot_id: str | None,
    correlation_id: uuid.UUID | None,
    exit_code: int,
    duration_ms: int,
    truncated: bool,
    result_text: str,
    error: str | None,
) -> None:
    preview = (result_text or "")[:3800]
    args: dict = {
        "task_id": str(task_id),
        "command": command,
        "exit_code": exit_code,
        "truncated": truncated,
    }
    try:
        await _record_tool_call(
            session_id=session_id,
            client_id=client_id,
            bot_id=bot_id,
            tool_name=f"exec_complete:{command}",
            tool_type="exec",
            server_name=None,
            iteration=0,
            arguments=args,
            result=preview if preview else None,
            error=error,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )
        await _record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot_id,
            client_id=client_id,
            event_type="exec",
            event_name=command,
            data={
                "task_id": str(task_id),
                "exit_code": exit_code,
                "truncated": truncated,
                "result_preview": preview[:2000],
            },
            duration_ms=duration_ms,
        )
    except Exception:
        logger.exception("Failed to record exec completion for task %s", task_id)


async def _record_tool_call(
    *,
    id: uuid.UUID | None = None,
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
    store_full_result: bool = False,
) -> None:
    """Fire-and-forget: write a ToolCall row to the DB.

    If store_full_result is True, the result is stored without truncation
    (used when summarization occurred so the full output is retrievable).
    """
    try:
        stored_result = result
        if stored_result and not store_full_result:
            stored_result = stored_result[:4000]
        kwargs: dict = dict(
            session_id=session_id,
            client_id=client_id,
            bot_id=bot_id,
            tool_name=tool_name,
            tool_type=tool_type,
            server_name=server_name,
            iteration=iteration,
            arguments=arguments,
            result=stored_result,
            error=error,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            created_at=datetime.now(timezone.utc),
        )
        if id is not None:
            kwargs["id"] = id
        async with async_session() as db:
            db.add(ToolCall(**kwargs))
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
