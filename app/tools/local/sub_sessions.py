"""Discovery tools for task sub-sessions (pipeline / eval / ephemeral runs).

A sub-session is a child Session spawned alongside a pipeline run (or eval
or widget-dashboard ad-hoc chat) so the run's own messages stay separate
from the parent channel transcript. The parent channel sees a compact
"anchor" card; the timeline lives on ``task.run_session_id``.

Also surfaces message-anchored *thread* sub-sessions (session_type=
'thread', parent_message_id set) and standalone ephemeral scratch
sessions (parent_channel_id set, session_type='ephemeral'). Neither is
backed by a Task — the listing unions Task-driven runs with these
Session-only variants so dreaming / memory-hygiene / skill-review bots
see every child conversation hanging off a channel.

These tools let an orchestrator bot discover past runs on a channel and
read what happened inside a specific run — including any follow-up
questions the user typed into the run-view modal after the pipeline
terminated.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_, select

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
            "List recent child sessions on a channel, most recent first. "
            "Includes pipeline runs, evals, message-anchored thread replies, "
            "and standalone scratch-chat sessions. Use this to discover past "
            "work the user may want to reference, resume, or push back on. "
            "Each entry carries kind (pipeline/eval/thread/scratch), the "
            "session_id, a task_id if applicable, title/preview, status, "
            "follow-up count, and ISO timestamps. Call "
            "read_sub_session(session_id) to see the full transcript of any "
            "entry."
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
                "channel_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional. List multiple channels in one call; results are "
                        "concatenated with per-channel headers. Cap 10. Prefer this "
                        "over N sequential single-channel calls during hygiene runs."
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


@dataclass
class _SubSessionRow:
    kind: str  # "pipeline" | "eval" | "thread" | "scratch"
    session_id: uuid.UUID
    created_at: datetime
    title: str
    status: str
    follow_ups: int
    task_id: uuid.UUID | None = None


async def _collect_task_rows(
    db, resolved_channel_id: uuid.UUID
) -> list[_SubSessionRow]:
    tasks = (await db.execute(
        select(Task)
        .where(
            Task.channel_id == resolved_channel_id,
            Task.run_isolation == "sub_session",
            Task.run_session_id.is_not(None),
        )
        .order_by(Task.created_at.desc())
    )).scalars().all()

    rows: list[_SubSessionRow] = []
    for t in tasks:
        follow_ups = 0
        if t.run_session_id is not None:
            user_msgs = (await db.execute(
                select(Message).where(
                    Message.session_id == t.run_session_id,
                    Message.role == "user",
                )
            )).scalars().all()
            follow_ups = sum(
                1 for m in user_msgs
                if (m.metadata_ or {}).get("sender_type") != "pipeline"
            )
        kind = "eval" if t.task_type == "eval" else "pipeline"
        rows.append(_SubSessionRow(
            kind=kind,
            session_id=t.run_session_id,  # type: ignore[arg-type]
            created_at=t.created_at,
            title=t.title or (t.prompt[:60] if t.prompt else "(untitled)"),
            status=t.status or "unknown",
            follow_ups=follow_ups,
            task_id=t.id,
        ))
    return rows


async def _collect_thread_rows(
    db, resolved_channel_id: uuid.UUID
) -> list[_SubSessionRow]:
    """Thread sessions anchored at messages that live in this channel."""
    # Two-step resolution: fetch threads, then filter by the parent
    # message's session's channel. Cheap enough at N=10 to avoid a tricky
    # triple-self-join.
    threads = (await db.execute(
        select(Session)
        .where(
            Session.session_type == "thread",
            Session.parent_message_id.is_not(None),
        )
        .order_by(Session.created_at.desc())
    )).scalars().all()

    rows: list[_SubSessionRow] = []
    for s in threads:
        # Resolve the parent message → its session → its channel.
        parent_msg = await db.get(Message, s.parent_message_id)
        if parent_msg is None:
            continue
        parent_sess = await db.get(Session, parent_msg.session_id)
        if parent_sess is None or parent_sess.channel_id != resolved_channel_id:
            continue
        user_msgs = (await db.execute(
            select(Message).where(
                Message.session_id == s.id,
                Message.role == "user",
            )
        )).scalars().all()
        follow_ups = len(user_msgs)
        preview = (parent_msg.content or "").strip().replace("\n", " ")
        if len(preview) > 60:
            preview = preview[:60] + "…"
        rows.append(_SubSessionRow(
            kind="thread",
            session_id=s.id,
            created_at=s.created_at,
            title=f"Thread on msg {parent_msg.id}: {preview}",
            status="active" if s.locked is False else "locked",
            follow_ups=follow_ups,
        ))
    return rows


async def _collect_scratch_rows(
    db, resolved_channel_id: uuid.UUID
) -> list[_SubSessionRow]:
    """Ephemeral scratch sessions anchored at this channel."""
    scratches = (await db.execute(
        select(Session)
        .where(
            Session.session_type == "ephemeral",
            Session.parent_channel_id == resolved_channel_id,
        )
        .order_by(Session.created_at.desc())
    )).scalars().all()

    rows: list[_SubSessionRow] = []
    for s in scratches:
        user_msgs = (await db.execute(
            select(Message).where(
                Message.session_id == s.id,
                Message.role == "user",
            )
        )).scalars().all()
        follow_ups = len(user_msgs)
        first_preview = ""
        if user_msgs:
            first = sorted(user_msgs, key=lambda m: m.created_at)[0]
            first_preview = (first.content or "").strip().replace("\n", " ")
            if len(first_preview) > 60:
                first_preview = first_preview[:60] + "…"
        marker = " [current]" if s.is_current else ""
        base_title = (s.title or "").strip() or first_preview or "(empty)"
        if s.summary:
            base_title = f"{base_title} — {s.summary.strip()[:80]}"
        rows.append(_SubSessionRow(
            kind="scratch",
            session_id=s.id,
            created_at=s.created_at,
            title=f"Scratch{marker}: {base_title}",
            status="current" if s.is_current else "archived",
            follow_ups=follow_ups,
        ))
    return rows


_MULTI_CHANNEL_CAP = 10


@register(_LIST_SCHEMA, requires_channel_context=True)
async def list_sub_sessions(
    channel_id: str | None = None,
    limit: int = 10,
    only_with_follow_ups: bool = False,
    channel_ids: list[str] | None = None,
) -> str:
    # Multi-channel fan-out: loop the single-channel path and concat the
    # markdown outputs with per-channel headers. Saves iterations in hygiene
    # runs that sweep 3–5 channels.
    if channel_ids:
        ids = [str(cid) for cid in channel_ids if str(cid or "").strip()]
        if not ids:
            return "channel_ids was provided but empty — pass at least one channel ID."
        if len(ids) > _MULTI_CHANNEL_CAP:
            return (
                f"channel_ids too large ({len(ids)} > {_MULTI_CHANNEL_CAP}). "
                "Chunk the list or drop channels not relevant to this run."
            )
        blocks: list[str] = []
        for cid in ids:
            sub = await list_sub_sessions(
                channel_id=cid,
                limit=limit,
                only_with_follow_ups=only_with_follow_ups,
            )
            blocks.append(f"### Channel {cid}\n\n{sub}")
        return "\n\n".join(blocks)

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
        all_rows: list[_SubSessionRow] = []
        all_rows.extend(await _collect_task_rows(db, resolved_channel_id))
        all_rows.extend(await _collect_thread_rows(db, resolved_channel_id))
        all_rows.extend(await _collect_scratch_rows(db, resolved_channel_id))

    if not all_rows:
        return f"No sub-sessions found on channel {resolved_channel_id}."

    all_rows.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    if only_with_follow_ups:
        all_rows = [r for r in all_rows if r.follow_ups > 0]

    capped = all_rows[:limit]
    if not capped:
        return f"No sub-sessions on channel {resolved_channel_id} match the filter."

    header = (
        f"Sub-sessions on channel {resolved_channel_id} "
        f"(newest first, {len(capped)} of up to {limit}):"
    )
    lines: list[str] = []
    for r in capped:
        task_part = f"task_id={r.task_id}  " if r.task_id else ""
        lines.append(
            f"- kind={r.kind}  {task_part}session_id={r.session_id}  "
            f"status={r.status}  follow_ups={r.follow_ups}  "
            f"started={_ago(r.created_at)}  title={r.title!r}"
        )
    return header + "\n" + "\n".join(lines)


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
