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
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.db.models import Project

from app.db.models import Channel, Message, Session, Task

logger = logging.getLogger(__name__)

SESSION_TYPE_CHANNEL = "channel"
SESSION_TYPE_PIPELINE_RUN = "pipeline_run"
SESSION_TYPE_EVAL = "eval"
SESSION_TYPE_EPHEMERAL = "ephemeral"
SESSION_TYPE_THREAD = "thread"

THREAD_CONTEXT_PRECEDING = 5


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


async def spawn_ephemeral_session(
    db: AsyncSession,
    *,
    bot_id: str,
    parent_channel_id: uuid.UUID | None = None,
    context: dict | None = None,
    owner_user_id: uuid.UUID | None = None,
    is_current: bool = False,
) -> Session:
    """Create a stand-alone ephemeral sub-session not tied to any Task.

    Used by interactive surfaces (widget dashboard etc.) to open ad-hoc
    bot conversations without first navigating to a channel.

    parent_channel_id, if supplied, links the session to a parent channel's
    active session for SSE bus routing (same mechanism as pipeline sub-sessions).
    When ``owner_user_id`` + ``parent_channel_id`` are both set and
    ``is_current=True``, the row also serves as the cross-device scratch
    pointer for that (user, channel) pair (migration 232). Partial unique
    index prevents two concurrent current-scratch rows.
    context, if supplied, is persisted as a system message with
    metadata.kind="ephemeral_context" so the agent's first turn sees it.

    Caller is responsible for committing.
    """
    from app.db.models import Message

    parent_session_id: uuid.UUID | None = None
    root_session_id: uuid.UUID | None = None
    depth = 0

    if parent_channel_id is not None:
        channel = await db.get(Channel, parent_channel_id)
        if channel is not None and channel.active_session_id is not None:
            parent_session_id = channel.active_session_id
            parent = await db.get(Session, parent_session_id)
            if parent is not None:
                depth = parent.depth + 1
                root_session_id = parent.root_session_id or parent_session_id

    sub = Session(
        id=uuid.uuid4(),
        client_id="ephemeral",
        bot_id=bot_id,
        channel_id=None,  # ephemeral sessions are never directly channel-bound
        parent_session_id=parent_session_id,
        root_session_id=root_session_id,
        depth=depth,
        source_task_id=None,
        session_type=SESSION_TYPE_EPHEMERAL,
        parent_channel_id=parent_channel_id,
        owner_user_id=owner_user_id,
        is_current=is_current,
    )
    db.add(sub)

    from app.db.models import Message

    if context:
        ctx_msg = Message(
            id=uuid.uuid4(),
            session_id=sub.id,
            role="system",
            content=str(context),
            metadata_={"kind": "ephemeral_context", **{k: v for k, v in context.items() if v is not None}},
            created_at=datetime.now(timezone.utc),
        )
        db.add(ctx_msg)
    if parent_channel_id is not None and channel is not None and channel.project_id is not None:
        from app.services.projects import project_session_bootstrap_text

        project = await db.get(Project, channel.project_id)
        if project is not None:
            db.add(Message(
                id=uuid.uuid4(),
                session_id=sub.id,
                role="system",
                content=project_session_bootstrap_text(project),
                metadata_={
                    "kind": "project_session_bootstrap",
                    "project_id": str(project.id),
                    "context_visibility": "session",
                    "ui_hidden": True,
                },
                created_at=datetime.now(timezone.utc),
            ))

    logger.info(
        "ephemeral_session spawned: session=%s bot=%s parent_channel=%s",
        sub.id, bot_id, parent_channel_id,
    )
    return sub


async def spawn_thread_session(
    db: AsyncSession,
    *,
    parent_message_id: uuid.UUID,
    bot_id: str,
) -> Session:
    """Create a thread sub-session anchored at ``parent_message_id``.

    Seeds ``session_type="thread"`` and ``parent_message_id`` so the parent
    channel can render a compact thread-anchor card beneath the message.
    Walks the parent Message's Session to inherit ``parent_session_id`` +
    ``root_session_id`` + ``depth`` so the parent-channel bus bridge
    routes streaming events the same way pipeline sub-sessions do.

    Seeds a ``thread_context`` system message built from the parent
    Message plus up to ``THREAD_CONTEXT_PRECEDING`` messages that
    immediately precede it in the same session (chronological order).
    The seeded text is what the thread bot sees before the user's first
    reply.

    Caller owns the transaction.
    """
    parent_msg = await db.get(Message, parent_message_id)
    if parent_msg is None:
        raise ValueError(f"parent message {parent_message_id} not found")

    parent_session = await db.get(Session, parent_msg.session_id)
    parent_session_id: uuid.UUID | None = None
    root_session_id: uuid.UUID | None = None
    depth = 0
    if parent_session is not None:
        parent_session_id = parent_session.id
        depth = (parent_session.depth or 0) + 1
        root_session_id = parent_session.root_session_id or parent_session.id

    sub = Session(
        id=uuid.uuid4(),
        client_id="thread",
        bot_id=bot_id,
        channel_id=None,
        parent_session_id=parent_session_id,
        root_session_id=root_session_id,
        depth=depth,
        source_task_id=None,
        session_type=SESSION_TYPE_THREAD,
        parent_message_id=parent_message_id,
    )
    db.add(sub)

    preceding_rows = []
    if parent_session_id is not None:
        preceding_stmt = (
            select(Message)
            .where(
                Message.session_id == parent_session_id,
                Message.created_at < parent_msg.created_at,
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.created_at.desc())
            .limit(THREAD_CONTEXT_PRECEDING)
        )
        res = await db.execute(preceding_stmt)
        preceding_rows = list(reversed(res.scalars().all()))

    context_lines: list[str] = []
    context_lines.append("# Thread context")
    context_lines.append(
        "You are replying in a sub-thread anchored at the message below. "
        "The preceding messages are included for grounding; the user will "
        "send their actual reply after this system prompt."
    )
    if preceding_rows:
        context_lines.append("")
        context_lines.append("## Preceding messages")
        for m in preceding_rows:
            content = (m.content or "").strip()
            if len(content) > 800:
                content = content[:800] + " …"
            context_lines.append(f"[{m.role}]: {content}")
    context_lines.append("")
    context_lines.append("## Parent message (the one being replied to)")
    parent_content = (parent_msg.content or "").strip()
    if len(parent_content) > 2000:
        parent_content = parent_content[:2000] + " …"
    context_lines.append(f"[{parent_msg.role}]: {parent_content}")

    ctx_msg = Message(
        id=uuid.uuid4(),
        session_id=sub.id,
        role="system",
        content="\n".join(context_lines),
        metadata_={
            "kind": "thread_context",
            "parent_message_id": str(parent_message_id),
            "seeded_messages": len(preceding_rows),
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(ctx_msg)

    logger.info(
        "thread_session spawned: session=%s bot=%s parent_msg=%s parent_session=%s depth=%d seeded=%d",
        sub.id, bot_id, parent_message_id, parent_session_id, depth, len(preceding_rows),
    )
    return sub


async def _find_external_thread_session(
    db: AsyncSession, integration_id: str, ref: dict,
) -> Session | None:
    """Return an existing thread Session matching ``(integration_id, ref)``, or None.

    Extracted from ``resolve_or_spawn_external_thread_session`` so the
    IntegrityError-retry path can re-run the same lookup after a DB-level
    uniqueness conflict surfaces the winner.
    """
    refs_col = Session.integration_thread_refs
    stmt = (
        select(Session)
        .where(
            Session.session_type == SESSION_TYPE_THREAD,
            refs_col[integration_id].isnot(None),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    for candidate in rows:
        existing = (candidate.integration_thread_refs or {}).get(integration_id)
        if existing == ref:
            return candidate
    return None


async def resolve_or_spawn_external_thread_session(
    db: AsyncSession,
    *,
    integration_id: str,
    channel: Channel,
    ref: dict,
    bot_id: str,
) -> Session:
    """Find or lazily create a thread sub-session bound to a native integration thread.

    Called when an inbound integration event (Slack ``thread_ts``, Discord
    thread message, etc.) needs to be routed into a Spindrel thread
    session. Resolution order:

    1. Look up an existing Session with matching
       ``integration_thread_refs[integration_id]`` contents and
       ``session_type="thread"``. If found, return it — the inbound
       thread has already been mirrored.
    2. Try to find a Spindrel Message in the parent channel's active
       session whose ``metadata_`` maps back to this ref (via the
       integration's ``build_thread_ref_from_message`` hook). If found,
       spawn a thread anchored at that Message.
    3. Orphan fallback: spawn a thread with ``parent_message_id=NULL``,
       seeded with a placeholder context system message so the bot isn't
       completely ungrounded.

    In every spawn path, ``integration_thread_refs[integration_id] = ref``
    is stamped before return so future inbound lookups short-circuit at
    step 1.

    Race safety: the spawn path is wrapped in a SAVEPOINT. If two inbound
    replies for the same external thread land concurrently, the DB-level
    partial unique index (migration 231 for Slack) rejects the loser's
    insert with ``IntegrityError``; the savepoint rolls back and the
    loser re-reads the now-visible winner, preserving the "one Spindrel
    session per external thread" invariant.

    Caller owns the outer transaction.
    """
    from sqlalchemy.exc import IntegrityError

    from app.agent.hooks import get_integration_meta

    # Step 1 — existing thread for this ref?
    existing = await _find_external_thread_session(db, integration_id, ref)
    if existing is not None:
        return existing

    try:
        async with db.begin_nested():
            # Step 2 — try to find the Spindrel Message that mirrors the
            # native parent, so we can anchor a proper thread session at it.
            meta = get_integration_meta(integration_id)
            parent_msg: Message | None = None
            if (
                meta
                and meta.build_thread_ref_from_message
                and channel.active_session_id
            ):
                msgs = (await db.execute(
                    select(Message).where(
                        Message.session_id == channel.active_session_id,
                    )
                )).scalars().all()
                for m in msgs:
                    try:
                        candidate_ref = meta.build_thread_ref_from_message(
                            dict(m.metadata_ or {})
                        )
                    except Exception:
                        continue
                    if candidate_ref == ref:
                        parent_msg = m
                        break

            if parent_msg is not None:
                sub = await spawn_thread_session(
                    db, parent_message_id=parent_msg.id, bot_id=bot_id,
                )
                sub.integration_thread_refs = {integration_id: dict(ref)}
                await db.flush()
                return sub

            # Step 3 — orphan spawn. No parent_message_id; seeded with a
            # minimal context block so the bot understands it's replying
            # in a foreign thread whose anchor we don't know about.
            parent_session_id: uuid.UUID | None = channel.active_session_id
            parent_session: Session | None = None
            if parent_session_id is not None:
                parent_session = await db.get(Session, parent_session_id)
            root_session_id = (
                (parent_session.root_session_id or parent_session.id)
                if parent_session is not None
                else None
            )
            depth = (parent_session.depth + 1) if parent_session is not None else 0

            sub = Session(
                id=uuid.uuid4(),
                client_id="thread",
                bot_id=bot_id,
                channel_id=None,
                parent_session_id=parent_session_id,
                root_session_id=root_session_id,
                depth=depth,
                source_task_id=None,
                session_type=SESSION_TYPE_THREAD,
                parent_message_id=None,
                integration_thread_refs={integration_id: dict(ref)},
            )
            db.add(sub)

            ctx_msg = Message(
                id=uuid.uuid4(),
                session_id=sub.id,
                role="system",
                content=(
                    "# Thread context\n"
                    f"You are replying in an external {integration_id} thread. The "
                    "anchor message is not mirrored in Spindrel — use the user's "
                    "reply text for grounding."
                ),
                metadata_={
                    "kind": "thread_context",
                    "orphan_parent": True,
                    "integration_id": integration_id,
                },
                created_at=datetime.now(timezone.utc),
            )
            db.add(ctx_msg)
            await db.flush()
    except IntegrityError:
        # A concurrent inbound reply won the insert race. The partial
        # unique index rejected our duplicate; the savepoint has rolled
        # back and the winner is now visible via the normal lookup.
        logger.info(
            "external thread_session race detected; returning winner "
            "(integration=%s ref=%s)",
            integration_id, ref,
        )
        winner = await _find_external_thread_session(db, integration_id, ref)
        if winner is None:
            # Uniqueness fired but the winner isn't queryable — surface the
            # error rather than silently spawning a third session.
            raise
        return winner

    logger.info(
        "external thread_session spawned: session=%s integration=%s ref=%s bot=%s",
        sub.id, integration_id, ref, bot_id,
    )
    return sub


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
      content = state.result (or a rendered error) — kept for historical
        consumers; UI suppresses this when ``metadata.envelope`` is set.
      metadata_ = {
        kind: "step_output",
        step_index, step_type, step_name, tool_name?,
        status, error, duration_ms,
        envelope?: ToolResultEnvelope.compact_dict(),
        source?: tool_name or step_type,
      }

    For successful non-agent steps with textual output, we stamp a full
    ``ToolResultEnvelope`` onto ``metadata.envelope`` so ``MessageBubble``
    dispatches to the same ``RichToolResult`` renderer that chat uses —
    JSON tree, markdown, diff, file-listing, components, etc. Agent steps
    are skipped because their child Task's turn already produces the
    normal assistant/tool-call Messages on the sub-session.
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

    metadata: dict = {
        "kind": "step_output",
        "step_index": step_index,
        "step_type": step_type,
        "step_name": step_def.get("name") or step_type,
        "status": status,
        "ui_only": True,
    }
    tool_name = step_def.get("tool_name")
    if tool_name:
        metadata["tool_name"] = tool_name
    if error_text:
        metadata["error"] = error_text[:2000]
    if duration_ms is not None:
        metadata["duration_ms"] = duration_ms

    # Build a ToolResultEnvelope so the UI dispatches through the same
    # RichToolResult renderer as normal chat (JSON tree, markdown, diff,
    # file-listing, components, ...). Local import to avoid pulling the
    # agent stack on module load — step_executor runs in a tight loop and
    # this helper is on the hot path.
    if (
        status == "done"
        and isinstance(result_text, str)
        and result_text
    ):
        try:
            from app.agent.tool_dispatch import _build_default_envelope  # type: ignore

            envelope = _build_default_envelope(result_text)
            envelope.display = "inline"
            if tool_name:
                envelope.tool_name = tool_name
            metadata["envelope"] = envelope.compact_dict()
            # Label on the envelope chip — tool_name for tool steps, the
            # step type otherwise ("exec", "evaluate").
            metadata["source"] = tool_name or step_type
        except Exception:
            logger.exception(
                "emit_step_output_message: envelope build failed for task %s step %d",
                task.id,
                step_index,
            )

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
