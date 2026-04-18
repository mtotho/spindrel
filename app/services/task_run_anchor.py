"""Task-run envelope anchor — one Message row per pipeline/task execution.

When a channel-bound task starts running, this module persists a single
Message row that the web UI renders as a `TaskRunEnvelope` (progress card
showing steps, status, context, and actions). Subsequent step-state
transitions mutate the row's metadata and publish `MESSAGE_UPDATED` on the
typed channel bus so open tabs re-render in place.

Anchor messages are UI-only:
  - Persisted in the session's message stream (so channel history survives).
  - Published to the SSE bus via ``publish_to_bus`` — web clients receive
    and render.
  - NOT enqueued to the outbox — Slack/Discord/etc. do NOT see the envelope.
    Integrations still see the separate ``post_final_to_channel`` summary
    Message when that flag is set on the task.

The anchor is keyed on ``task_id``. Recurring tasks spawn a fresh Task row
per occurrence (see ``tasks.py:_spawn_from_schedule``), so each run gets
its own anchor and scrolls into history as a distinct event.
"""
from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.engine import async_session
from app.db.models import Channel, Message, Task
from app.services.sub_sessions import spawn_sub_session

logger = logging.getLogger(__name__)

# Metadata key — renderMessage dispatches to TaskRunEnvelope on this.
ANCHOR_KIND = "task_run"

# Persisted on ``Task.execution_config`` so every update jumps straight to
# the right Message row instead of scanning history. Each run of a recurring
# task gets a fresh Task row (see ``tasks._spawn_from_schedule``) so the key
# naturally resets per run — plus we validate with a metadata.task_id check
# in case ``execution_config`` was deep-copied from the schedule template.
ANCHOR_MSG_KEY = "task_run_anchor_msg_id"


def _step_summary(task: Task) -> list[dict]:
    """Shape step definitions + current states into the envelope payload."""
    steps = list(task.steps or [])
    states = list(task.step_states or [])
    out: list[dict] = []
    for i, sdef in enumerate(steps):
        state = states[i] if i < len(states) else {}
        result = state.get("result")
        if result and len(result) > 400:
            result = result[:400] + "…"
        entry: dict = {
            "index": i,
            "type": sdef.get("type", "agent"),
            "label": sdef.get("label") or sdef.get("id") or f"Step {i + 1}",
            "status": state.get("status", "pending"),
            "duration_ms": _duration_ms(state),
            "result_preview": result,
            "error": state.get("error"),
        }
        # When paused for user input, carry the rendered widget envelope
        # + response schema + step title into the anchor payload so the
        # web client can render the approval UI inline in chat without
        # a second fetch. Data already lives on step_states[i].
        if state.get("status") == "awaiting_user_input":
            env = state.get("widget_envelope")
            if env is not None:
                entry["widget_envelope"] = env
            schema = state.get("response_schema")
            if schema is not None:
                entry["response_schema"] = schema
            step_title = sdef.get("title")
            if step_title:
                entry["title"] = step_title
        out.append(entry)
    return out


def _duration_ms(state: dict) -> int | None:
    started = state.get("started_at")
    completed = state.get("completed_at")
    if not started or not completed:
        return None
    try:
        s = datetime.fromisoformat(started)
        c = datetime.fromisoformat(completed)
        return int((c - s).total_seconds() * 1000)
    except (ValueError, TypeError):
        return None


_SUMMARY_MAX_CHARS = 400


def _fallback_text(task: Task, status: str, steps: list[dict]) -> str:
    """Plain-text rendering + summary line that appears in the parent session.

    This text IS what the parent bot sees when it reads its conversation
    history (the anchor Message sits in the parent channel's session). For
    ``sub_session`` runs we append a condensed result excerpt so the parent
    bot can reference what happened ("what did analyze find?") without us
    needing to splice in sub-session Messages — those stay invisible to
    the parent prompt.
    """
    title = task.title or task.task_type or "Task"
    done = sum(1 for s in steps if s["status"] in ("done", "skipped"))
    total = len(steps)
    if total:
        header = f"[{title} · {status} · {done}/{total} steps]"
    else:
        header = f"[{title} · {status}]"

    if getattr(task, "run_isolation", "inline") != "sub_session":
        return header

    # Summary source (cheapest path first):
    # 1. task.result if the pipeline finalized with one.
    # 2. Otherwise the most-recent terminal step's result_preview or error.
    summary: str | None = None
    if task.result:
        summary = task.result
    elif task.error:
        summary = f"error: {task.error}"
    else:
        for s in reversed(steps):
            preview = s.get("result_preview") or s.get("error")
            if preview:
                summary = str(preview)
                break

    if not summary:
        return header

    snippet = summary.strip().replace("\n", " ")
    if len(snippet) > _SUMMARY_MAX_CHARS:
        snippet = snippet[:_SUMMARY_MAX_CHARS - 1] + "…"
    return f"{header} {snippet}"


def _build_metadata(task: Task) -> dict:
    """Build the anchor Message's metadata_ blob.

    Two shapes depending on ``task.run_isolation``:

    - ``inline``: today's shape — embeds the full ``steps[]`` summary in
      the anchor. The UI renders the step list directly from metadata.
    - ``sub_session``: slim shape — carries ``run_session_id`` +
      ``step_count`` + ``awaiting_count`` only. The UI opens the run-view
      modal at the sub-session; it does NOT read steps[] from here.

    Both shapes carry the status/result/error fields the envelope renders
    regardless of isolation mode.
    """
    ecfg = task.execution_config or {}
    # getattr fallbacks tolerate SimpleNamespace-based test mocks that were
    # written before run_isolation/run_session_id existed on the ORM.
    run_isolation = getattr(task, "run_isolation", "inline") or "inline"
    run_session_id = getattr(task, "run_session_id", None)
    base = {
        "kind": ANCHOR_KIND,
        "trigger": ANCHOR_KIND,  # also matched by SUPPORTED_TRIGGERS-style filters
        "task_id": str(task.id),
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "task_type": task.task_type,
        "bot_id": task.bot_id,
        "title": task.title,
        "status": task.status,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "context_mode": ecfg.get("history_mode", "none"),
        "context_recent_count": ecfg.get("history_recent_count", 10),
        "post_final_to_channel": bool(ecfg.get("post_final_to_channel", False)),
        "result": (task.result or "")[:1000] if task.result else None,
        "error": (task.error or "")[:1000] if task.error else None,
        # UI-only marker: outbox enqueue paths should skip rows with this flag.
        "ui_only": True,
        "run_isolation": run_isolation,
    }

    states = list(task.step_states or [])
    if run_isolation == "sub_session":
        awaiting = sum(
            1 for s in states if isinstance(s, dict) and s.get("status") == "awaiting_user_input"
        )
        base["run_session_id"] = str(run_session_id) if run_session_id else None
        base["step_count"] = len(states)
        base["awaiting_count"] = awaiting
        # No steps[] — the modal reads the sub-session's Messages directly.
    else:
        steps = _step_summary(task)
        base["steps"] = steps
        base["step_count"] = len(steps)

    return base


async def _resolve_session_id(db, task: Task) -> uuid.UUID | None:
    """Find the session to anchor to: task.session_id, else channel.active_session_id."""
    if task.session_id:
        return task.session_id
    if task.channel_id is None:
        return None
    channel = await db.get(Channel, task.channel_id)
    return channel.active_session_id if channel else None


async def _find_existing_anchor(
    db, task: Task, session_id: uuid.UUID | None = None,
) -> Message | None:
    """Look up this task's anchor Message.

    Fast path: read ``task.execution_config[ANCHOR_MSG_KEY]`` and fetch the
    row directly. Validates the hit with a ``metadata.task_id`` check so a
    stale id copied from a schedule template can't point us at the wrong run.

    Fallback: scan the session's recent assistant messages and filter by
    ``metadata.kind`` + ``metadata.task_id``. Scoped to the session so we
    don't cross channels or hit the 200-row cliff on busy servers.
    """
    ec = task.execution_config or {}
    existing_id_str = ec.get(ANCHOR_MSG_KEY)
    if existing_id_str:
        try:
            existing_id = uuid.UUID(str(existing_id_str))
        except (ValueError, TypeError):
            existing_id = None
        if existing_id is not None:
            m = await db.get(Message, existing_id)
            if m is not None and (m.metadata_ or {}).get("task_id") == str(task.id):
                return m

    if session_id is None:
        return None

    stmt = (
        select(Message)
        .where(Message.session_id == session_id, Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).scalars().all()
    for m in rows:
        meta = m.metadata_ or {}
        if meta.get("kind") == ANCHOR_KIND and meta.get("task_id") == str(task.id):
            return m
    return None


async def ensure_anchor_message(task: Task) -> uuid.UUID | None:
    """Create (or look up) the task_run anchor Message for *task*.

    Returns the Message id, or None if the task has no channel/session to
    anchor to. Idempotent — calling twice returns the existing row.

    Publishes NEW_MESSAGE on the bus so the web UI renders the envelope
    immediately. Does NOT enqueue to the outbox (dispatchers skip).
    """
    if task.channel_id is None:
        return None

    async with async_session() as db:
        # Always work off a fresh Task row — step_executor hands us a
        # detached instance and execution_config may have been updated
        # since (e.g. this anchor id being persisted by a sibling call).
        t = await db.get(Task, task.id)
        if t is None:
            return None

        session_id = await _resolve_session_id(db, t)
        if session_id is None:
            logger.debug("task %s has no session to anchor to", t.id)
            return None

        existing = await _find_existing_anchor(db, t, session_id)
        if existing is not None:
            # Backfill the pointer if it wasn't written (e.g. the anchor
            # was created before this key existed).
            ec = dict(t.execution_config or {})
            if ec.get(ANCHOR_MSG_KEY) != str(existing.id):
                ec[ANCHOR_MSG_KEY] = str(existing.id)
                t.execution_config = ec
                flag_modified(t, "execution_config")
                await db.commit()
            return existing.id

        # Spawn the sub-session BEFORE building metadata so the slim
        # anchor can reference run_session_id on the very first write.
        if t.run_isolation == "sub_session" and t.run_session_id is None:
            await spawn_sub_session(db, task=t, parent_session_id=session_id)
            # Mirror the new run_session_id onto the caller's in-memory
            # Task object. ``ensure_anchor_message`` is called at the top
            # of ``run_task_pipeline``, which then threads the SAME Task
            # reference through ``_advance_pipeline`` → ``_spawn_agent_step``
            # and ``emit_step_output_message``. Without this mirror, those
            # downstream readers see a stale ``run_session_id=None``, spawn
            # child agent tasks with ``session_id=None`` (which creates an
            # orphan throwaway session via ``load_or_create``), and the
            # run-view modal renders empty because every Message landed on
            # a different session than the one linked on ``task.run_session_id``.
            task.run_session_id = t.run_session_id

        metadata = _build_metadata(t)
        fallback = _fallback_text(t, t.status or "pending", _step_summary(t))
        msg = Message(
            id=uuid.uuid4(),
            session_id=session_id,
            role="assistant",
            content=fallback,
            metadata_=metadata,
        )
        db.add(msg)

        # Persist the anchor id onto the task so update_anchor() can jump
        # straight to it without scanning history.
        ec = dict(t.execution_config or {})
        ec[ANCHOR_MSG_KEY] = str(msg.id)
        t.execution_config = ec
        flag_modified(t, "execution_config")

        await db.commit()
        await db.refresh(msg)

        await _publish_new_message(t.channel_id, msg)
        logger.info("task_run anchor created: task=%s msg=%s", t.id, msg.id)
        return msg.id


async def update_anchor(task: Task) -> None:
    """Re-snapshot *task* into its anchor message and publish MESSAGE_UPDATED.

    No-op if the task has no channel. Called after every step-state
    transition and on pipeline finalization. Creates the anchor lazily if
    it's somehow missing (e.g. pipeline started before the ensure call).
    """
    if task.channel_id is None:
        return
    async with async_session() as db:
        # Re-fetch the task so we see the freshly-persisted step_states
        # (step_executor commits them before calling us).
        t = await db.get(Task, task.id)
        if t is None:
            return

        session_id = await _resolve_session_id(db, t)
        existing = await _find_existing_anchor(db, t, session_id)
        if existing is None:
            # Lazy-create — close this session first to avoid holding two.
            await db.rollback()
            await ensure_anchor_message(t)
            return

        metadata = _build_metadata(t)
        existing.metadata_ = copy.deepcopy(metadata)
        existing.content = _fallback_text(
            t, t.status or metadata["status"], _step_summary(t),
        )
        # ORM attribute name (underscore) — NOT the DB column name. SQLAlchemy
        # uses the Python attribute to locate the instrumented attribute;
        # passing "metadata" silently does nothing for JSONB mutation tracking.
        flag_modified(existing, "metadata_")
        await db.commit()
        await db.refresh(existing)

        await _publish_message_updated(t.channel_id, existing)


async def _publish_new_message(channel_id: uuid.UUID, msg: Message) -> None:
    """Bus-only NEW_MESSAGE for the anchor (no outbox)."""
    try:
        from app.domain.channel_events import ChannelEvent, ChannelEventKind
        from app.domain.message import Message as DomainMessage
        from app.domain.payloads import MessagePayload
        from app.services.outbox_publish import publish_to_bus

        dm = DomainMessage.from_orm(msg, channel_id=channel_id)
        publish_to_bus(
            channel_id,
            ChannelEvent(
                channel_id=channel_id,
                kind=ChannelEventKind.NEW_MESSAGE,
                payload=MessagePayload(message=dm),
            ),
        )
    except Exception:
        logger.warning("task_run anchor bus publish failed for channel %s", channel_id, exc_info=True)


async def _publish_message_updated(channel_id: uuid.UUID, msg: Message) -> None:
    """Bus-only MESSAGE_UPDATED so the envelope re-renders in place."""
    try:
        from app.domain.channel_events import ChannelEvent, ChannelEventKind
        from app.domain.message import Message as DomainMessage
        from app.domain.payloads import MessageUpdatedPayload
        from app.services.outbox_publish import publish_to_bus

        dm = DomainMessage.from_orm(msg, channel_id=channel_id)
        publish_to_bus(
            channel_id,
            ChannelEvent(
                channel_id=channel_id,
                kind=ChannelEventKind.MESSAGE_UPDATED,
                payload=MessageUpdatedPayload(message=dm),
            ),
        )
    except Exception:
        logger.debug(
            "task_run anchor MESSAGE_UPDATED publish failed for channel %s",
            channel_id, exc_info=True,
        )


async def create_summary_message(task: Task) -> uuid.UUID | None:
    """Post a condensed summary Message for a completed pipeline.

    Called only when ``task.execution_config.post_final_to_channel`` is True.
    This message IS routed through the outbox (Slack, etc.) — it's the
    dispatcher-visible footprint of the run. Separate from the envelope
    anchor which remains UI-only.
    """
    if task.channel_id is None:
        return None
    async with async_session() as db:
        session_id = await _resolve_session_id(db, task)
        if session_id is None:
            return None

        steps = _step_summary(task)
        title = task.title or task.task_type or "Task"
        status = task.status or "complete"
        final_step_result = None
        for s in reversed(steps):
            if s.get("result_preview"):
                final_step_result = s["result_preview"]
                break
        duration_total = sum(s.get("duration_ms") or 0 for s in steps)
        duration_s = duration_total / 1000 if duration_total else None
        ok = status == "complete"

        # Plain-text body — dispatchers render Markdown; web UI uses the
        # metadata to add the compact summary card styling.
        header = f"{'✓' if ok else '✕'} {title} · {status}"
        lines = [header]
        if final_step_result:
            lines.append(final_step_result)
        meta_row_parts = [f"steps: {len(steps)}"]
        if duration_s is not None:
            meta_row_parts.append(f"{duration_s:.1f}s")
        lines.append(" · ".join(meta_row_parts))
        content = "\n".join(lines)

        msg = Message(
            id=uuid.uuid4(),
            session_id=session_id,
            role="assistant",
            content=content,
            metadata_={
                "kind": "task_run_summary",
                "task_id": str(task.id),
                "status": status,
                "title": title,
                "duration_ms": duration_total or None,
                "step_count": len(steps),
            },
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)

        # Full outbox + bus so dispatchers pick it up.
        try:
            from app.domain.channel_events import ChannelEvent, ChannelEventKind
            from app.domain.message import Message as DomainMessage
            from app.domain.payloads import MessagePayload
            from app.services.outbox_publish import (
                enqueue_new_message_for_channel,
                publish_to_bus,
            )

            dm = DomainMessage.from_orm(msg, channel_id=task.channel_id)
            publish_to_bus(
                task.channel_id,
                ChannelEvent(
                    channel_id=task.channel_id,
                    kind=ChannelEventKind.NEW_MESSAGE,
                    payload=MessagePayload(message=dm),
                ),
            )
            await enqueue_new_message_for_channel(task.channel_id, dm)
        except Exception:
            logger.warning(
                "task_run summary dispatch failed for channel %s msg %s",
                task.channel_id, msg.id, exc_info=True,
            )

        logger.info("task_run summary posted: task=%s msg=%s", task.id, msg.id)
        return msg.id
