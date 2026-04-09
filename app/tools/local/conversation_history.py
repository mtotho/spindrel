"""Tool for navigating archived conversation history sections (file mode)."""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.agent.context import current_bot_id, current_channel_id
from app.db.engine import async_session
from app.db.models import Channel, ConversationSection, ToolCall
from app.tools.registry import register

logger = logging.getLogger(__name__)

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_conversation_history",
        "description": (
            "Read archived conversation history. Pass section='index' for a table of contents, "
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
                        "'index' to list all sections, a section number (e.g. '12'), "
                        "'search:<query>' to find sections by topic/content/similarity, "
                        "or 'tool:<id>' to retrieve full tool call output."
                    ),
                },
                "channel_id": {
                    "type": "string",
                    "description": "Optional. Only needed for cross-channel reads (from list_channels). Omit to read the current channel.",
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


async def search_sections(channel_id: uuid.UUID, query: str) -> list[dict]:
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
            .where(ConversationSection.channel_id == channel_id, *filters)
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
                    ConversationSection.channel_id == channel_id,
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
                        ConversationSection.channel_id == channel_id,
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


@register(_SCHEMA)
async def read_conversation_history(section: str, channel_id: str | None = None) -> str:
    my_channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    owner_bot_id = None  # set when reading another bot's channel via cross_workspace_access

    # Resolve channel_id: accept UUID strings or client_id (e.g. Slack channel IDs)
    resolved_channel_id: uuid.UUID | None = None
    if channel_id:
        try:
            resolved_channel_id = uuid.UUID(str(channel_id))
        except ValueError:
            # Not a UUID — try looking up by client_id
            from sqlalchemy import select as _select
            async with async_session() as db:
                _result = await db.execute(
                    _select(Channel.id).where(Channel.client_id == str(channel_id)).limit(1)
                )
                _row = _result.scalar_one_or_none()
            if _row:
                resolved_channel_id = _row
            else:
                return f"Unknown channel: {channel_id}"

    if resolved_channel_id and resolved_channel_id != my_channel_id:
        # Verify the bot has access: primary owner, member, or cross_workspace_access
        async with async_session() as db:
            ch = await db.get(Channel, resolved_channel_id)
        if not ch:
            return "Access denied: channel not found."
        if str(ch.bot_id) != bot_id:
            # Not the primary bot — check membership
            from app.db.models import ChannelBotMember
            from sqlalchemy import select as _sel, exists as _exists
            async with async_session() as db:
                is_member = await db.scalar(
                    _sel(_exists().where(
                        ChannelBotMember.channel_id == resolved_channel_id,
                        ChannelBotMember.bot_id == bot_id,
                    ))
                )
            if is_member:
                pass  # member access — bot reads its own sessions
            else:
                from app.agent.bots import get_bot
                caller_bot = get_bot(bot_id)
                if caller_bot and caller_bot.cross_workspace_access:
                    owner_bot_id = ch.bot_id
                else:
                    return "Access denied: this bot is not a member of the requested channel."
    else:
        resolved_channel_id = my_channel_id

    if not resolved_channel_id:
        return "No channel context available. This tool requires a channel-based conversation."

    if section == "index":
        from sqlalchemy.orm import defer
        async with async_session() as db:
            result = await db.execute(
                select(ConversationSection)
                .where(ConversationSection.channel_id == resolved_channel_id)
                .order_by(ConversationSection.sequence)
                .options(defer(ConversationSection.transcript), defer(ConversationSection.embedding))
            )
            sections = result.scalars().all()

        if not sections:
            return "No archived conversation sections found for this channel."

        lines = ["Archived conversation sections:\n"]
        for s in sections:
            date_str = s.period_start.strftime("%Y-%m-%d %H:%M") if s.period_start else "unknown"
            tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
            lines.append(
                f"- Section #{s.sequence}: {s.title} "
                f"({s.message_count} msgs, {date_str}){tag_str}\n"
                f"  {s.summary}"
            )
        return "\n".join(lines)

    # Smart search: keyword + transcript grep + semantic
    if section.lower().startswith("search:"):
        query = section[7:].strip()
        if not query:
            return "Please provide a search query, e.g. 'search:database migration'."

        results = await search_sections(resolved_channel_id, query)

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
        return "\n".join(lines)

    # Retrieve full tool call output by ID
    if section.lower().startswith("tool:"):
        tool_call_id = section[len("tool:"):].strip()
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

    # Try sequence number (bare integer)
    if section.isdigit():
        seq_num = int(section)
        async with async_session() as db:
            result = await db.execute(
                select(ConversationSection)
                .where(ConversationSection.channel_id == resolved_channel_id, ConversationSection.sequence == seq_num)
            )
            sec_obj = result.scalar_one_or_none()
        if not sec_obj:
            return f"Section #{seq_num} not found."
        await _track_view(sec_obj.id)
        transcript_text = _read_section_transcript(sec_obj, owner_bot_id=owner_bot_id)

        # Lazy backfill: if we read from file but DB column is empty, populate it
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

    return (
        f"Invalid section: '{section}'. Pass 'index', a section number (e.g. '12'), "
        "'search:<query>', or 'tool:<id>'."
    )
