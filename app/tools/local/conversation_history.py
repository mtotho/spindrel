"""Tool for navigating archived conversation history sections (file mode)."""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select, update

from app.agent.context import current_bot_id, current_channel_id, current_session_id
from app.db.engine import async_session
from app.db.models import Channel, ConversationSection, Message, Session, ToolCall
from app.tools.registry import register

logger = logging.getLogger(__name__)

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_conversation_history",
        "description": (
            "Read conversation history. Pass section='recent' for the latest messages (useful for new channels "
            "or catching up), 'index' for a table of contents of archived sections, "
            "a section number (e.g. '12') to read the full transcript, "
            "'search:<query>' to find sections by topic, content, or semantic similarity, "
            "or 'tool:<id>' to retrieve full output of a summarized tool call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "'recent' for latest messages, 'index' to list archived sections, "
                        "a section number (e.g. '12'), "
                        "'search:<query>' to find sections by topic/content/similarity, "
                        "or 'tool:<id>' to retrieve full tool call output."
                    ),
                },
                "channel_id": {
                    "type": "string",
                    "description": "Optional. Only needed for cross-channel reads (from list_channels). Omit to read the current channel.",
                },
                "channel_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional. Pass a list of channel IDs to read the same section "
                        "across multiple channels in one tool call. Results are concatenated "
                        "with per-channel headers. Cap 10. Prefer this to issuing N sequential "
                        "single-channel calls during hygiene / dreaming runs. Ignored when "
                        "`section` targets a prior tool result (`tool:<id>`)."
                    ),
                },
            },
            "required": ["section"],
        },
    },
}


def _read_section_transcript(sec: ConversationSection, owner_bot_id: str | None = None) -> str:
    """Read the transcript from DB column, filesystem fallback, or summary fallback."""
    # Prefer DB column (new sections always have this)
    if sec.transcript:
        return sec.transcript

    # Fallback: read from file (pre-migration sections)
    if sec.transcript_path:
        import os
        from app.agent.context import current_bot_id
        from app.agent.bots import get_bot

        try:
            resolve_bot_id = owner_bot_id or current_bot_id.get()
            bot = get_bot(resolve_bot_id)

            if sec.transcript_path.startswith("channels/"):
                from app.services.channel_workspace import _get_ws_root
                ws_root = _get_ws_root(bot)
            else:
                from app.services.workspace import workspace_service
                ws_root = workspace_service.get_workspace_root(bot.id, bot)

            filepath = os.path.join(ws_root, sec.transcript_path)
            with open(filepath) as f:
                return f.read()
        except FileNotFoundError:
            return f"Transcript file not found: {sec.transcript_path}. Re-run backfill."
        except Exception:
            return f"Error reading transcript file: {sec.transcript_path}"

    # Fallback: no transcript available at all
    period = ""
    if sec.period_start:
        period += f"From: {sec.period_start.strftime('%Y-%m-%d %H:%M')}"
    if sec.period_end:
        period += f"  To: {sec.period_end.strftime('%Y-%m-%d %H:%M')}"

    return (
        f"# {sec.title}\n"
        f"{period}\n"
        f"Messages: {sec.message_count}\n\n"
        f"Summary: {sec.summary}\n\n"
        f"---\n\n"
        f"Transcript not available for this section."
    )


async def _backfill_transcript(sec_id: uuid.UUID, transcript_text: str) -> None:
    """Lazily backfill the DB transcript column from a file-read."""
    try:
        async with async_session() as db:
            await db.execute(
                update(ConversationSection)
                .where(ConversationSection.id == sec_id)
                .values(transcript=transcript_text)
            )
            await db.commit()
    except Exception:
        logger.debug("Failed to backfill transcript for section %s", sec_id, exc_info=True)


async def _track_view(section_id: uuid.UUID) -> None:
    """Increment view_count and update last_viewed_at."""
    async with async_session() as db:
        await db.execute(
            update(ConversationSection)
            .where(ConversationSection.id == section_id)
            .values(
                view_count=ConversationSection.view_count + 1,
                last_viewed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def search_sections(session_id: uuid.UUID, query: str) -> list[dict]:
    """Smart search: keyword + transcript grep + semantic. Returns deduplicated results.

    Each result dict has: section (ConversationSection), source (str), snippet (str|None).
    """
    from sqlalchemy import or_, cast, String, func as sa_func

    seen_ids: set[uuid.UUID] = set()
    results: list[dict] = []

    # Escape LIKE wildcards in the query
    escaped_query = query.replace("%", r"\%").replace("_", r"\_")

    # 1. Metadata keyword match (title, summary, tags)
    keywords = query.split()
    filters = []
    for kw in keywords:
        escaped_kw = kw.replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{escaped_kw}%"
        filters.append(or_(
            ConversationSection.title.ilike(pattern),
            ConversationSection.summary.ilike(pattern),
            cast(ConversationSection.tags, String).ilike(pattern),
        ))

    async with async_session() as db:
        # --- Phase 1: metadata keyword ---
        meta_result = await db.execute(
            select(ConversationSection)
            .where(ConversationSection.session_id == session_id, *filters)
            .order_by(ConversationSection.sequence.desc())
            .limit(10)
        )
        for s in meta_result.scalars().all():
            if s.id not in seen_ids:
                seen_ids.add(s.id)
                results.append({"section": s, "source": "metadata", "snippet": None})

        # --- Phase 2: transcript text grep ---
        if len(results) < 10:
            grep_result = await db.execute(
                select(ConversationSection)
                .where(
                    ConversationSection.session_id == session_id,
                    ConversationSection.transcript.ilike(f"%{escaped_query}%"),
                )
                .order_by(ConversationSection.sequence.desc())
                .limit(10)
            )
            for s in grep_result.scalars().all():
                if s.id not in seen_ids:
                    seen_ids.add(s.id)
                    snippet = _extract_snippet(s.transcript, query) if s.transcript else None
                    results.append({"section": s, "source": "content", "snippet": snippet})

        # --- Phase 3: semantic ranking ---
        if len(results) < 10:
            try:
                from app.agent.embeddings import embed_text
                from app.agent.vector_ops import halfvec_cosine_distance
                query_vec = await embed_text(query)
                sem_result = await db.execute(
                    select(ConversationSection)
                    .where(
                        ConversationSection.session_id == session_id,
                        ConversationSection.embedding.is_not(None),
                    )
                    .order_by(halfvec_cosine_distance(ConversationSection.embedding, query_vec))
                    .limit(5)
                )
                for s in sem_result.scalars().all():
                    if s.id not in seen_ids:
                        seen_ids.add(s.id)
                        results.append({"section": s, "source": "semantic", "snippet": None})
            except Exception:
                logger.debug("Semantic search failed for query: %s", query, exc_info=True)

    return results[:10]


def _extract_snippet(text: str, query: str, context_chars: int = 100) -> str | None:
    """Extract a snippet around the first occurrence of query in text."""
    lower_text = text.lower()
    idx = lower_text.find(query.lower())
    if idx < 0:
        return None
    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(query) + context_chars)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


_MULTI_CHANNEL_CAP = 10
_RECENT_LIMIT = 50

_HistorySectionKind = Literal["index", "recent", "search", "tool", "section", "invalid"]


@dataclass(frozen=True)
class _ParsedSection:
    kind: _HistorySectionKind
    value: str | int | None = None
    raw: str = ""


@dataclass(frozen=True)
class _HistoryScope:
    bot_id: str | None
    requested_channel_id: uuid.UUID
    owner_bot_id: str | None
    current_session: Session
    primary_session: Session | None
    nearby_scratches: list[Session]

    @property
    def target_session_id(self) -> uuid.UUID:
        return self.current_session.id


def _parse_section(section: str) -> _ParsedSection:
    lower = section.lower()
    if section == "index":
        return _ParsedSection("index", raw=section)
    if lower == "recent":
        return _ParsedSection("recent", raw=section)
    if lower.startswith("search:"):
        return _ParsedSection("search", section[7:].strip(), raw=section)
    if lower.startswith("tool:"):
        return _ParsedSection("tool", section[len("tool:"):].strip(), raw=section)
    if section.isdigit():
        return _ParsedSection("section", int(section), raw=section)
    return _ParsedSection("invalid", raw=section)


def _normalize_channel_ids(channel_ids: list[str] | None) -> tuple[list[str] | None, str | None]:
    if not channel_ids:
        return None, None

    ids = [str(cid) for cid in channel_ids if str(cid or "").strip()]
    if not ids:
        return None, "channel_ids was provided but empty — pass at least one channel ID."
    if len(ids) > _MULTI_CHANNEL_CAP:
        return None, (
            f"channel_ids too large ({len(ids)} > {_MULTI_CHANNEL_CAP}). "
            "Chunk the list or drop channels not relevant to this run."
        )
    return ids, None


async def _resolve_requested_channel_id(channel_id: str | None) -> tuple[uuid.UUID | None, str | None]:
    if not channel_id:
        return None, None

    try:
        return uuid.UUID(str(channel_id)), None
    except ValueError:
        pass

    async with async_session() as db:
        result = await db.execute(
            select(Channel.id).where(Channel.client_id == str(channel_id)).limit(1)
        )
        row = result.scalar_one_or_none()
    if row:
        return row, None
    return None, f"Unknown channel: {channel_id}"


async def _authorize_channel_read(
    requested_channel_id: uuid.UUID,
    my_channel_id: uuid.UUID | None,
    bot_id: str | None,
) -> tuple[str | None, str | None]:
    from app.services.worksurface_access import (
        authorize_channel_worksurface,
        record_worksurface_boundary_event,
    )
    async with async_session() as db:
        decision = await authorize_channel_worksurface(
            db,
            actor_bot_id=bot_id,
            channel_id=requested_channel_id,
        )
        should_trace = (
            requested_channel_id != my_channel_id
            or decision.reason == "member"
            or not decision.allowed
        )
        if should_trace:
            await record_worksurface_boundary_event(
                decision,
                mode="history",
                source_tool="read_conversation_history",
            )
    if not decision.allowed:
        return None, decision.error
    return decision.owner_bot_id, None


async def _load_session_context(
    requested_channel_id: uuid.UUID,
    my_session_id: uuid.UUID | None,
    *,
    prefer_current_session: bool,
) -> tuple[Session | None, Session | None, list[Session]]:
    current_session: Session | None = None
    primary_session: Session | None = None

    async with async_session() as db:
        channel_row = await db.get(Channel, requested_channel_id)
        if channel_row and channel_row.active_session_id:
            primary_session = await db.get(Session, channel_row.active_session_id)

        if my_session_id and prefer_current_session:
            current_session = await db.get(Session, my_session_id)
            if (
                current_session
                and current_session.parent_channel_id != requested_channel_id
                and current_session.channel_id != requested_channel_id
            ):
                current_session = primary_session
        else:
            current_session = primary_session

        if current_session is None:
            current_session = primary_session

        nearby_scratches = (await db.execute(
            select(Session)
            .where(
                Session.session_type == "ephemeral",
                Session.parent_channel_id == requested_channel_id,
            )
            .order_by(Session.last_active.desc(), Session.created_at.desc())
            .limit(5)
        )).scalars().all()

    return current_session, primary_session, nearby_scratches


async def _resolve_history_scope(channel_id: str | None) -> tuple[_HistoryScope | None, str | None]:
    my_channel_id = current_channel_id.get()
    my_session_id = current_session_id.get()
    bot_id = current_bot_id.get()

    requested_channel_id, error = await _resolve_requested_channel_id(channel_id)
    if error:
        return None, error
    if requested_channel_id is None:
        requested_channel_id = my_channel_id
    if not requested_channel_id:
        return None, "No channel context available. This tool requires a channel-based conversation."

    owner_bot_id, error = await _authorize_channel_read(requested_channel_id, my_channel_id, bot_id)
    if error:
        return None, error

    current_session, primary_session, nearby_scratches = await _load_session_context(
        requested_channel_id,
        my_session_id,
        prefer_current_session=channel_id is None,
    )
    if current_session is None:
        return None, "No conversation found for this channel."

    return (
        _HistoryScope(
            bot_id=bot_id,
            requested_channel_id=requested_channel_id,
            owner_bot_id=owner_bot_id,
            current_session=current_session,
            primary_session=primary_session,
            nearby_scratches=nearby_scratches,
        ),
        None,
    )


def _session_label(session: Session | None, fallback: str) -> str:
    if session is None:
        return fallback
    return (session.title or fallback).strip() or fallback


def _session_summary(session: Session | None) -> str:
    return (session.summary or "").strip() if session else ""


def _same_session(a: Session | None, b: Session | None) -> bool:
    return bool(a and b and a.id == b.id)


def _nearby_lines(scope: _HistoryScope) -> list[str]:
    current_session = scope.current_session
    primary_session = scope.primary_session
    lines: list[str] = []
    if (
        current_session
        and current_session.session_type == "ephemeral"
        and primary_session is not None
        and not _same_session(current_session, primary_session)
    ):
        title = _session_label(primary_session, "Primary session")
        summary = _session_summary(primary_session)
        lines.append(
            f"Primary session nearby: session_id={primary_session.id} title={title!r}"
        )
        if summary:
            lines.append(f"Summary: {summary}")
    elif scope.nearby_scratches:
        lines.append("Recent scratch sessions nearby:")
        for scratch in scope.nearby_scratches[:3]:
            if scratch.id == scope.target_session_id:
                continue
            label = _session_label(scratch, "Untitled scratch")
            summary = _session_summary(scratch)
            lines.append(
                f"  - session_id={scratch.id} title={label!r} last_active={scratch.last_active.isoformat()}"
            )
            if summary:
                lines.append(f"    summary={summary}")
    return lines


async def _render_index(scope: _HistoryScope) -> str:
    from sqlalchemy.orm import defer

    async with async_session() as db:
        result = await db.execute(
            select(ConversationSection)
            .where(ConversationSection.session_id == scope.target_session_id)
            .order_by(ConversationSection.sequence)
            .options(defer(ConversationSection.transcript), defer(ConversationSection.embedding))
        )
        sections = result.scalars().all()

    if not sections:
        lines = ["No archived conversation sections found for this session. Try section='recent' to see the latest messages."]
        nearby = _nearby_lines(scope)
        if nearby:
            lines.extend(["", *nearby])
        return "\n".join(lines)

    lines = [f"Archived conversation sections for session {scope.target_session_id}:\n"]
    for s in sections:
        date_str = s.period_start.strftime("%Y-%m-%d %H:%M") if s.period_start else "unknown"
        tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
        lines.append(
            f"- Section #{s.sequence}: {s.title} "
            f"({s.message_count} msgs, {date_str}){tag_str}\n"
            f"  {s.summary}"
        )
    nearby = _nearby_lines(scope)
    if nearby:
        lines.extend(["", *nearby])
    return "\n".join(lines)


async def _render_recent(scope: _HistoryScope) -> str:
    from app.db.models import Session as SessionModel

    async with async_session() as db:
        msg_result = await db.execute(
            select(Message)
            .where(
                Message.session_id == scope.target_session_id,
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(Message.created_at.desc())
            .limit(_RECENT_LIMIT)
        )
        messages = list(reversed(msg_result.scalars().all()))

        shown_msg_ids = {m.id for m in messages}
        sub_rows: list[tuple[str, str, SessionModel, Message | None]] = []
        if shown_msg_ids:
            thread_sessions = (await db.execute(
                select(SessionModel)
                .where(
                    SessionModel.session_type == "thread",
                    SessionModel.parent_message_id.in_(shown_msg_ids),
                )
                .order_by(SessionModel.created_at.desc())
                .limit(10)
            )).scalars().all()
            for s in thread_sessions:
                parent = await db.get(Message, s.parent_message_id) if s.parent_message_id else None
                sub_rows.append(("thread", str(s.id), s, parent))

        for s in scope.nearby_scratches:
            sub_rows.append(("scratch", str(s.id), s, None))

    if not messages:
        return "No messages found in this session."

    session_label = "scratch session" if scope.current_session.session_type == "ephemeral" else "primary session"
    lines = [
        f"Recent messages from the current {session_label} ({len(messages)} shown):",
        f"Session: {_session_label(scope.current_session, 'Untitled session')} ({scope.target_session_id})",
    ]
    current_summary = _session_summary(scope.current_session)
    if current_summary:
        lines.append(f"Summary: {current_summary}")
    lines.append("")
    for msg in messages:
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else "?"
        content = msg.content or ""
        if not content.strip() and msg.role == "assistant":
            continue
        if len(content) > 500:
            content = content[:500] + "..."
        sender = msg.metadata_.get("sender_id") or msg.role
        lines.append(f"[{ts}] {sender}: {content}")

    if sub_rows:
        lines.append("\n--- Sub-sessions ---")
        lines.append(
            "Thread replies and scratch-pad chats live off this channel. "
            "Call read_sub_session(session_id=<id>) to read one."
        )
        for kind, sid, s, parent in sub_rows[:10]:
            ts = s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "?"
            if kind == "thread" and parent is not None:
                preview = (parent.content or "").strip().replace("\n", " ")
                if len(preview) > 60:
                    preview = preview[:60] + "…"
                lines.append(
                    f"[{ts}] thread on msg {parent.id}: {preview!r} — "
                    f"read with read_sub_session(session_id='{sid}')"
                )
            else:
                marker = " [current]" if getattr(s, "is_current", False) else ""
                lines.append(
                    f"[{ts}] scratch{marker} session={sid} — "
                    f"read with read_sub_session(session_id='{sid}')"
                )

    async with async_session() as db:
        section_count = (await db.execute(
            select(ConversationSection.id)
            .where(ConversationSection.session_id == scope.target_session_id)
            .limit(1)
        )).scalar_one_or_none()
    if section_count:
        lines.append("\nOlder history available — use section='index' to browse archived sections.")
    nearby = _nearby_lines(scope)
    if nearby:
        lines.extend(["", *nearby])

    return "\n".join(lines)


async def _render_search(scope: _HistoryScope, query: str) -> str:
    if not query:
        return "Please provide a search query, e.g. 'search:database migration'."

    results = await search_sections(scope.target_session_id, query)
    if not results:
        return f"No sections found matching '{query}'."

    lines = [f"Sections matching '{query}':\n"]
    for r in results:
        s = r["section"]
        source = r["source"]
        date_str = s.period_start.strftime("%Y-%m-%d %H:%M") if s.period_start else "unknown"
        tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
        source_tag = ""
        if source == "content":
            source_tag = " [content match]"
        elif source == "semantic":
            source_tag = " [semantic match]"
        lines.append(
            f"- Section #{s.sequence}: {s.title} "
            f"({s.message_count} msgs, {date_str}){tag_str}{source_tag}\n"
            f"  {s.summary}"
        )
        if r.get("snippet"):
            lines.append(f"  > {r['snippet']}")
    lines.append("\nUse read_conversation_history with a section number to read the full transcript.")
    nearby = _nearby_lines(scope)
    if nearby:
        lines.extend(["", *nearby])
    return "\n".join(lines)


async def _render_tool_call(tool_call_id: str) -> str:
    if not tool_call_id:
        return "Please provide a tool call ID, e.g. 'tool:abc123'."

    try:
        tc_uuid = uuid.UUID(tool_call_id)
    except ValueError:
        return f"Invalid tool call ID: '{tool_call_id}'. Expected a UUID."

    async with async_session() as db:
        tc = await db.get(ToolCall, tc_uuid)

    if not tc:
        return f"Tool call not found: {tool_call_id}"

    result_text = tc.result or "(no output)"
    return (
        f"Tool: {tc.tool_name}\n"
        f"Called: {tc.created_at.strftime('%Y-%m-%d %H:%M') if tc.created_at else '?'}\n"
        f"Duration: {tc.duration_ms}ms\n\n"
        f"{result_text}"
    )


async def _render_section_number(scope: _HistoryScope, seq_num: int) -> str:
    async with async_session() as db:
        result = await db.execute(
            select(ConversationSection)
            .where(
                ConversationSection.session_id == scope.target_session_id,
                ConversationSection.sequence == seq_num,
            )
        )
        sec_obj = result.scalar_one_or_none()
    if not sec_obj:
        return f"Section #{seq_num} not found."
    await _track_view(sec_obj.id)
    transcript_text = _read_section_transcript(sec_obj, owner_bot_id=scope.owner_bot_id)

    if (
        not sec_obj.transcript
        and sec_obj.transcript_path
        and transcript_text
        and "Transcript file not found" not in transcript_text
        and "Transcript not available" not in transcript_text
        and "Error reading transcript file" not in transcript_text
    ):
        await _backfill_transcript(sec_obj.id, transcript_text)

    return transcript_text


async def _read_single_channel_history(section: str, channel_id: str | None = None) -> str:
    parsed = _parse_section(section)
    if parsed.kind == "invalid":
        return (
            f"Invalid section: '{section}'. Pass 'recent', 'index', a section number (e.g. '12'), "
            "'search:<query>', or 'tool:<id>'."
        )
    if parsed.kind == "tool":
        return await _render_tool_call(str(parsed.value or ""))
    if parsed.kind == "search" and not parsed.value:
        return "Please provide a search query, e.g. 'search:database migration'."

    scope, error = await _resolve_history_scope(channel_id)
    if error:
        return error
    assert scope is not None

    if parsed.kind == "index":
        return await _render_index(scope)
    if parsed.kind == "recent":
        return await _render_recent(scope)
    if parsed.kind == "search":
        return await _render_search(scope, str(parsed.value or ""))
    if parsed.kind == "section":
        return await _render_section_number(scope, int(parsed.value))
    raise AssertionError(f"Unhandled conversation history section kind: {parsed.kind}")


async def _read_multi_channel_history(section: str, channel_ids: list[str]) -> str:
    ids, error = _normalize_channel_ids(channel_ids)
    if error:
        return error
    assert ids is not None

    if section.strip().lower().startswith("tool:"):
        return (
            "channel_ids is not supported when section targets a prior tool "
            "result (tool:<id>). Use a single channel_id instead."
        )

    blocks: list[str] = []
    for cid in ids:
        sub = await _read_single_channel_history(section=section, channel_id=cid)
        blocks.append(f"### Channel {cid}\n\n{sub}")
    return "\n\n".join(blocks)


@register(_SCHEMA, requires_bot_context=True, requires_channel_context=True)
async def read_conversation_history(
    section: str,
    channel_id: str | None = None,
    channel_ids: list[str] | None = None,
) -> str:
    if channel_ids:
        return await _read_multi_channel_history(section, channel_ids)
    return await _read_single_channel_history(section, channel_id)
