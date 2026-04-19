"""Discovery tools for task sub-sessions (pipeline / eval / ephemeral runs).

A sub-session is a child Session spawned alongside a pipeline run (or eval
or widget-dashboard ad-hoc chat) so the run's own messages stay separate
from the parent channel transcript. The parent channel sees a compact
"anchor" card; the timeline lives on ``task.run_session_id``.

These tools let an orchestrator bot discover past runs on a channel and
read what happened inside a specific run — including any follow-up
questions the user typed into the run-view modal after the pipeline
terminated.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.agent.context import current_channel_id
from app.db.engine import async_session
from app.db.models import Message, Session, Task
from app.tools.registry import register

logger = logging.getLogger(__name__)


def _fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return "—"
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _ago(ts: datetime | None) -> str:
    if ts is None:
        return "—"
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


# ---------------------------------------------------------------------------
# list_sub_sessions
# ---------------------------------------------------------------------------

_LIST_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_sub_sessions",
        "description": (
            "List recent task sub-sessions (pipeline runs, evals) on a channel, "
            "most recent first. Use this to discover past runs the user may want "
            "to reference, resume, or push back on. Each entry carries the run's "
            "task_id, title, status, step count, follow-up count (user messages "
            "sent into the run-view modal after the pipeline terminated), and "
            "ISO timestamps. Call read_sub_session(session_id) to see the full "
            "transcript of any entry."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": (
                        "Channel UUID to list runs for. Omit to use the current "
                        "channel."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default 10, cap 50).",
                },
                "only_with_follow_ups": {
                    "type": "boolean",
                    "description": (
                        "If true, return only runs the user has followed up on "
                        "(has at least one non-pipeline user message in the "
                        "sub-session). Useful for 'what have I pushed back on?'."
                    ),
                },
            },
            "required": [],
        },
    },
}


@register(_LIST_SCHEMA, requires_channel_context=True)
async def list_sub_sessions(
    channel_id: str | None = None,
    limit: int = 10,
    only_with_follow_ups: bool = False,
) -> str:
    resolved_channel_id: uuid.UUID | None
    if channel_id:
        try:
            resolved_channel_id = uuid.UUID(str(channel_id))
        except ValueError:
            return f"Invalid channel_id: {channel_id!r} (expected UUID)."
    else:
        resolved_channel_id = current_channel_id.get()
        if resolved_channel_id is None:
            return "No channel context available; pass channel_id explicitly."

    limit = max(1, min(int(limit or 10), 50))

    async with async_session() as db:
        tasks = (await db.execute(
            select(Task)
            .where(
                Task.channel_id == resolved_channel_id,
                Task.run_isolation == "sub_session",
                Task.run_session_id.is_not(None),
            )
            .order_by(Task.created_at.desc())
            .limit(limit * 3 if only_with_follow_ups else limit)
        )).scalars().all()

        if not tasks:
            return f"No sub-sessions found on channel {resolved_channel_id}."

        rows: list[str] = []
        for t in tasks:
            follow_ups = 0
            if t.run_session_id is not None:
                user_msgs = (await db.execute(
                    select(Message)
                    .where(
                        Message.session_id == t.run_session_id,
                        Message.role == "user",
                    )
                )).scalars().all()
                follow_ups = sum(
                    1 for m in user_msgs
                    if (m.metadata_ or {}).get("sender_type") != "pipeline"
                )

            if only_with_follow_ups and follow_ups == 0:
                continue

            title = t.title or (t.prompt[:60] if t.prompt else "(untitled)")
            rows.append(
                f"- task_id={t.id}  session_id={t.run_session_id}  "
                f"status={t.status}  type={t.task_type}  "
                f"follow_ups={follow_ups}  "
                f"started={_ago(t.created_at)}  "
                f"title={title!r}"
            )
            if len(rows) >= limit:
                break

        if not rows:
            return (
                f"No sub-sessions on channel {resolved_channel_id} match the filter."
            )

        header = (
            f"Sub-sessions on channel {resolved_channel_id} "
            f"(newest first, {len(rows)} of up to {limit}):"
        )
        return header + "\n" + "\n".join(rows)


# ---------------------------------------------------------------------------
# read_sub_session
# ---------------------------------------------------------------------------

_READ_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_sub_session",
        "description": (
            "Read the full transcript of a task sub-session — every user "
            "message, assistant response, and step-output card that appeared "
            "in the run-view modal. Use after list_sub_sessions to inspect a "
            "specific run, see what step emitted what, or review the user's "
            "follow-up conversation with the orchestrator."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": (
                        "The sub-session's session_id (UUID). Get this from "
                        "list_sub_sessions, or from a TaskRun anchor's metadata."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max messages to return (default 50, cap 200). Oldest first."
                    ),
                },
            },
            "required": ["session_id"],
        },
    },
}


@register(_READ_SCHEMA)
async def read_sub_session(session_id: str, limit: int = 50) -> str:
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        return f"Invalid session_id: {session_id!r} (expected UUID)."

    limit = max(1, min(int(limit or 50), 200))

    async with async_session() as db:
        sess = await db.get(Session, sid)
        if sess is None:
            return f"Session not found: {sid}"
        if sess.channel_id is not None:
            return (
                f"Session {sid} is a channel session, not a sub-session. "
                "Use read_conversation_history for channel transcripts."
            )

        source_task: Task | None = None
        if sess.source_task_id is not None:
            source_task = await db.get(Task, sess.source_task_id)

        messages = (await db.execute(
            select(Message)
            .where(Message.session_id == sid)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )).scalars().all()

    header_lines: list[str] = [
        f"Sub-session {sid}  (type={sess.session_type})",
    ]
    if source_task is not None:
        header_lines.append(
            f"Source task: {source_task.id}  "
            f"status={source_task.status}  type={source_task.task_type}  "
            f"title={source_task.title or '(untitled)'!r}"
        )
        if source_task.result:
            excerpt = source_task.result[:400]
            ellipsis = "..." if len(source_task.result) > 400 else ""
            header_lines.append(f"Result excerpt: {excerpt}{ellipsis}")
        if source_task.error:
            header_lines.append(f"Error: {source_task.error[:400]}")

    if not messages:
        return "\n".join(header_lines + ["", "(no messages in this sub-session)"])

    body_lines: list[str] = ["", f"Messages ({len(messages)} shown):"]
    for m in messages:
        meta = m.metadata_ or {}
        sender_type = meta.get("sender_type", "")
        kind = meta.get("kind", "")
        label = m.role
        if sender_type == "pipeline":
            label = f"pipeline-step[{meta.get('pipeline_step_index', '?')}]"
        elif kind == "step_output":
            label = f"step-output"
        elif m.role == "user":
            label = "user"
        elif m.role == "assistant":
            label = "assistant"
        content = (m.content or "").strip()
        if len(content) > 600:
            content = content[:600] + "... [truncated]"
        body_lines.append(f"[{_fmt_ts(m.created_at)}] {label}: {content}")

    return "\n".join(header_lines + body_lines)
