"""Fire-and-forget DB helpers for recording tool calls and trace events."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import update

from app.db.engine import async_session
from app.db.models import ToolCall, TraceEvent
from app.services.tool_presentation import derive_tool_presentation

logger = logging.getLogger(__name__)

# DB-storage cap for raw tool results when the caller didn't opt in to
# ``store_full_result`` (the dispatch path sets that flag for summarized +
# large results so retrieval pointers work). The cap exists to keep the
# tool_calls row reasonable in the common case where a tool returns a huge
# blob the UI never needs to re-parse.
_STORED_RESULT_CAP_CHARS = 4000


def _trim_stored_result(result: str | None, store_full: bool) -> str | None:
    """Decide what to persist on the ToolCall row's ``result`` column.

    Preserves the full payload when the caller opted in, or when the payload
    is a tool-authored envelope (``{"_envelope": ...}``) — those are structured
    JSON that the dev panel and import-into-templates flow re-parse, and mid-JSON
    truncation collapses them to unparseable strings (which then renders as
    "—" with Import disabled). Envelope size is already bounded upstream
    (``INLINE_BODY_CAP_BYTES``; HTML widgets are rendering-critical and
    intentionally exempt from that cap), so this is a safe exemption.
    """
    if result is None:
        return None
    if store_full:
        return result
    # Cheap prefix sniff — avoids parsing JSON just to decide how to store.
    # Anchored start-only so payloads that happen to contain the string deeper
    # in a body don't accidentally slip through.
    stripped = result.lstrip()
    if stripped.startswith('{"_envelope"') or stripped.startswith("{'_envelope'"):
        return result
    return result[:_STORED_RESULT_CAP_CHARS]


def _derive_error_contract_fields(
    result: str | None,
    *,
    error: str | None,
    error_code: str | None,
    error_kind: str | None,
    retryable: bool | None,
    retry_after_seconds: int | None,
    fallback: str | None,
) -> dict:
    if not error:
        return {
            "error_code": error_code,
            "error_kind": error_kind,
            "retryable": retryable,
            "retry_after_seconds": retry_after_seconds,
            "fallback": fallback,
        }
    payload = None
    if result:
        try:
            import json

            parsed = json.loads(result)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = None
    if payload is None:
        payload = {"error": error}
    from app.services.tool_error_contract import enrich_tool_error_payload

    enriched = enrich_tool_error_payload(
        payload,
        default_code=error_code or "tool_error",
        default_kind=error_kind,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
        fallback=fallback,
    )
    return {
        "error_code": enriched.get("error_code"),
        "error_kind": enriched.get("error_kind"),
        "retryable": enriched.get("retryable"),
        "retry_after_seconds": enriched.get("retry_after_seconds"),
        "fallback": enriched.get("fallback"),
    }


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
    status: str = "done",
    envelope: dict | None = None,
    error_code: str | None = None,
    error_kind: str | None = None,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
    fallback: str | None = None,
) -> None:
    """Fire-and-forget: write a complete ToolCall row in one shot.

    Used for terminal-state inserts where the call never reaches the regular
    dispatch path — auth/policy denials and the deferred exec-completion
    worker. Live dispatches use ``_start_tool_call`` + ``_complete_tool_call``
    so the row exists in 'running' state before completion.

    If ``store_full_result`` is True, the result is stored without truncation
    (used when summarization occurred so the full output is retrievable).
    """
    try:
        stored_result = _trim_stored_result(result, store_full_result)
        error_fields = _derive_error_contract_fields(
            result,
            error=error,
            error_code=error_code,
            error_kind=error_kind,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            fallback=fallback,
        )
        surface, summary = derive_tool_presentation(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            envelope=envelope,
            error=error,
        )
        now = datetime.now(timezone.utc)
        kwargs: dict = dict(
            session_id=session_id,
            client_id=client_id,
            bot_id=bot_id,
            tool_name=tool_name,
            tool_type=tool_type,
            server_name=server_name,
            iteration=iteration,
            arguments=arguments,
            surface=surface,
            summary=summary,
            result=stored_result,
            error=error,
            error_code=error_fields["error_code"],
            error_kind=error_fields["error_kind"],
            retryable=error_fields["retryable"],
            retry_after_seconds=error_fields["retry_after_seconds"],
            fallback=error_fields["fallback"],
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            created_at=now,
            status=status,
            completed_at=now,
        )
        if id is not None:
            kwargs["id"] = id
        async with async_session() as db:
            db.add(ToolCall(**kwargs))
            await db.commit()
    except Exception:
        logger.exception("Failed to record tool call for %s", tool_name)


async def _start_tool_call(
    *,
    id: uuid.UUID,
    session_id: uuid.UUID | None,
    client_id: str | None,
    bot_id: str | None,
    tool_name: str,
    tool_type: str,
    server_name: str | None,
    iteration: int,
    arguments: dict,
    correlation_id: uuid.UUID | None = None,
    status: str = "running",
    strict: bool = False,
) -> bool:
    """Fire-and-forget: insert a ToolCall row at dispatch entry.

    Status defaults to 'running' for normal dispatch, or 'awaiting_approval'
    when the policy engine gates the call. ``_complete_tool_call`` updates
    this same row id when the call resolves.
    """
    try:
        async with async_session() as db:
            db.add(ToolCall(
                id=id,
                session_id=session_id,
                client_id=client_id,
                bot_id=bot_id,
                tool_name=tool_name,
                tool_type=tool_type,
                server_name=server_name,
                iteration=iteration,
                arguments=arguments,
                surface=None,
                summary=None,
                result=None,
                error=None,
                duration_ms=None,
                correlation_id=correlation_id,
                created_at=datetime.now(timezone.utc),
                status=status,
                completed_at=None,
            ))
            await db.commit()
        return True
    except Exception:
        logger.exception("Failed to insert in-flight tool call for %s", tool_name)
        if strict:
            raise
        return False


async def _complete_tool_call(
    row_id: uuid.UUID,
    *,
    tool_name: str,
    arguments: dict,
    result: str | None,
    error: str | None,
    duration_ms: int,
    status: str = "done",
    store_full_result: bool = False,
    envelope: dict | None = None,
    strict: bool = False,
    error_kind: str | None = None,
    error_code: str | None = None,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
    fallback: str | None = None,
) -> bool:
    """Fire-and-forget: UPDATE an existing ToolCall row on completion.

    Pairs with ``_start_tool_call`` — the row was inserted in 'running'
    (or 'awaiting_approval') state at dispatch entry; this flips it to a
    terminal state and stamps the result.
    """
    try:
        stored_result = _trim_stored_result(result, store_full_result)
        error_fields = _derive_error_contract_fields(
            result,
            error=error,
            error_code=error_code,
            error_kind=error_kind,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            fallback=fallback,
        )
        surface, summary = derive_tool_presentation(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            envelope=envelope,
            error=error,
        )
        async with async_session() as db:
            result = await db.execute(
                update(ToolCall)
                .where(ToolCall.id == row_id)
                .values(
                    surface=surface,
                    summary=summary,
                    result=stored_result,
                    error=error,
                    error_kind=error_fields["error_kind"],
                    error_code=error_fields["error_code"],
                    retryable=error_fields["retryable"],
                    retry_after_seconds=error_fields["retry_after_seconds"],
                    fallback=error_fields["fallback"],
                    duration_ms=duration_ms,
                    status=status,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            if result.rowcount == 0:
                raise RuntimeError(f"ToolCall {row_id} missing during completion")
            await db.commit()
        return True
    except Exception:
        logger.exception("Failed to complete tool call row %s", row_id)
        if strict:
            raise
        return False


async def _set_tool_call_status(row_id: uuid.UUID, status: str, *, strict: bool = False) -> bool:
    """Fire-and-forget: flip a ToolCall row's status (e.g. on approve/deny).

    Used by the approval decide endpoint to transition an
    'awaiting_approval' row back to 'running' (approve) or to 'denied'
    (deny). Doesn't touch result/duration — those are written by the next
    ``_complete_tool_call`` call when dispatch actually finishes.
    """
    try:
        async with async_session() as db:
            result = await db.execute(
                update(ToolCall)
                .where(ToolCall.id == row_id)
                .values(status=status)
            )
            if result.rowcount == 0:
                raise RuntimeError(f"ToolCall {row_id} missing during status update")
            await db.commit()
        return True
    except Exception:
        logger.exception("Failed to set tool call %s status to %s", row_id, status)
        if strict:
            raise
        return False


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
