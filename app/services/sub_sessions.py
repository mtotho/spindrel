"""Sub-session spawn + lookup helpers.

A *sub-session* is a Session whose Messages form the rich, chat-native
timeline of a single Task run (`task_type="pipeline"`, `"eval"`, or any
Task with `run_isolation="sub_session"`). The parent channel's session
hosts a single compact anchor Message that points at the sub-session;
all step output — LLM thinking, tool calls, widget envelopes, approvals —
lands on the sub-session's Messages and is rendered by the ordinary
`ChatMessageArea` machinery when the run-view modal is open.

The sub-session re-uses the columns already on `sessions` from the
sub-agent delegation path:
- ``parent_session_id`` links back to the parent channel's session
- ``root_session_id`` mirrors the parent's root (or the parent itself)
- ``depth`` = parent's depth + 1
- ``source_task_id`` back-references the Task that owns the run
- ``session_type`` discriminates `channel` / `pipeline_run` / `eval`

Invariants:
- ``channel_id`` on the sub-session is NULL. A sub-session is reachable
  only through its parent's authorization — no direct channel binding,
  no outbox, no per-user visibility list.
- A sub-session is never the ``active_session_id`` of a Channel.
- One sub-session per Task run. The id is also stored on
  ``tasks.run_session_id`` so callers can resolve in either direction.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session, Task

logger = logging.getLogger(__name__)

SESSION_TYPE_CHANNEL = "channel"
SESSION_TYPE_PIPELINE_RUN = "pipeline_run"
SESSION_TYPE_EVAL = "eval"


def _session_type_for_task(task: Task) -> str:
    if task.task_type == "eval":
        return SESSION_TYPE_EVAL
    return SESSION_TYPE_PIPELINE_RUN


async def spawn_sub_session(
    db: AsyncSession,
    *,
    task: Task,
    parent_session_id: uuid.UUID | None,
) -> Session:
    """Create a sub-session for ``task`` and persist ``run_session_id``.

    Caller is responsible for committing. The new Session is added to the
    db but not flushed here — the anchor helper commits it together with
    the anchor Message it writes to the parent session.

    ``parent_session_id`` is the parent channel's session (where the anchor
    Message will live); may be None for Tasks that have no parent channel
    (eval cases invoked directly, system prompts, etc.) — the sub-session
    is still useful as an isolated container.
    """
    parent: Session | None = None
    if parent_session_id is not None:
        parent = await db.get(Session, parent_session_id)

    depth = (parent.depth + 1) if parent is not None else 0
    root_id = (
        parent.root_session_id if (parent and parent.root_session_id) else parent_session_id
    )

    sub = Session(
        id=uuid.uuid4(),
        client_id=task.client_id or "task",
        bot_id=task.bot_id,
        channel_id=None,  # sub-sessions are never directly channel-bound
        parent_session_id=parent_session_id,
        root_session_id=root_id,
        depth=depth,
        source_task_id=task.id,
        session_type=_session_type_for_task(task),
        title=task.title,
    )
    db.add(sub)

    task.run_session_id = sub.id
    logger.info(
        "sub_session spawned: task=%s session=%s type=%s parent=%s depth=%d",
        task.id, sub.id, sub.session_type, parent_session_id, depth,
    )
    return sub


async def resolve_sub_session(
    db: AsyncSession, task: Task
) -> Session | None:
    """Return this task's sub-session, or None if not isolated / not yet spawned."""
    if task.run_isolation != "sub_session":
        return None
    if task.run_session_id is None:
        return None
    return await db.get(Session, task.run_session_id)


async def emit_step_output_message(
    *,
    task: Task,
    step_def: dict,
    step_index: int,
    state: dict,
    db: AsyncSession | None = None,
) -> None:
    """Persist a step's output as a Message on the sub-session.

    No-op for ``inline`` runs — their output already flows to the parent
    session through existing paths (anchor updates for controller-side
    state, child-task Messages for agent steps).

    For ``sub_session`` runs, every non-agent step gets an assistant
    Message on the sub-session so the run-view modal's ordinary chat
    renderer surfaces the result. Agent steps are skipped here because
    they already produce Messages via their child Task's turn.

    Message shape:
      role = "assistant"
      content = state.result (or a rendered error) — raw enough that
        Markdown / JSON / plain-text auto-detection in the chat renderer
        picks the right rendering.
      metadata_ = {
        kind: "step_output",
        step_index, step_type, step_name, tool_name?,
        status, error, duration_ms, args?
      }

    The chat renderer uses ``kind == "step_output"`` to pick the rich
    widget for tool-output results (WidgetCard templates, JSON cards,
    Markdown) — that UI wiring lands in the envelope-refactor phase.
    """
    # Local imports to dodge circular dependency with task_run_anchor.
    import uuid as _uuid
    from datetime import datetime, timezone as _tz

    from sqlalchemy.orm.attributes import flag_modified  # noqa: F401

    from app.db.engine import async_session as _async_session
    from app.db.models import Message

    if task.run_isolation != "sub_session":
        return
    if task.run_session_id is None:
        logger.debug(
            "emit_step_output_message: task %s isolated but no run_session_id",
            task.id,
        )
        return

    step_type = step_def.get("type", "agent")
    # Agent steps are already represented by their child Task's own
    # turn Messages on the sub-session — skip to avoid duplicates.
    if step_type in ("agent", "bot_invoke"):
        return

    status = state.get("status") or "done"
    result_text = state.get("result")
    error_text = state.get("error")

    content = result_text if isinstance(result_text, str) and result_text else (
        f"[{step_def.get('name') or step_type} · {status}]"
    )
    if error_text and (not result_text):
        content = f"[error] {error_text}"

    started = state.get("started_at")
    completed = state.get("completed_at")
    duration_ms = None
    try:
        if started and completed:
            ds = datetime.fromisoformat(started.replace("Z", "+00:00"))
            dc = datetime.fromisoformat(completed.replace("Z", "+00:00"))
            duration_ms = int((dc - ds).total_seconds() * 1000)
    except Exception:
        pass

    metadata = {
        "kind": "step_output",
        "step_index": step_index,
        "step_type": step_type,
        "step_name": step_def.get("name") or step_type,
        "status": status,
        "ui_only": True,
    }
    if step_def.get("tool_name"):
        metadata["tool_name"] = step_def["tool_name"]
    if error_text:
        metadata["error"] = error_text[:2000]
    if duration_ms is not None:
        metadata["duration_ms"] = duration_ms

    msg = Message(
        id=_uuid.uuid4(),
        session_id=task.run_session_id,
        role="assistant",
        content=content,
        metadata_=metadata,
        created_at=datetime.now(_tz.utc),
    )

    if db is not None:
        # Caller owns the transaction (e.g. test or same-txn chain).
        db.add(msg)
        await db.flush()
        await _publish_to_parent_bus(db, msg)
        return

    async with _async_session() as _db:
        _db.add(msg)
        await _db.commit()
        await _publish_to_parent_bus(_db, msg)


async def _publish_to_parent_bus(db: AsyncSession, msg) -> None:
    """Republish a sub-session Message on the parent channel's bus.

    Lets the UI (run-view modal) subscribe to the parent channel's SSE
    stream and filter by ``payload.session_id``. Swallows exceptions so a
    broken bus doesn't block the step executor — the Message row is the
    source of truth; a missed bus event surfaces on the next
    refetch/reconnect.
    """
    try:
        from app.services.channel_events import publish_message
        from app.services.sub_session_bus import resolve_bus_channel_id

        bus_ch = await resolve_bus_channel_id(db, msg.session_id)
        if bus_ch is not None:
            publish_message(bus_ch, msg)
    except Exception:
        logger.exception(
            "emit_step_output_message: publish to parent bus failed for msg %s",
            getattr(msg, "id", "?"),
        )
