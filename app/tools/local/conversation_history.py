"""Tool for navigating archived conversation history sections (file mode)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.agent.context import current_channel_id
from app.db.engine import async_session
from app.db.models import ConversationSection
from app.tools.registry import register

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_conversation_history",
        "description": (
            "Read archived conversation history. Pass section='index' to see a table of contents "
            "of all archived sections, a section number (e.g. '12') to read by sequence, "
            "a section UUID to read the full transcript, or 'search:query' to semantically "
            "search all sections (e.g. 'search:database migration issue')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Either 'index' to list all sections, a section number (e.g. '12'), "
                        "a section UUID, or 'search:<query>' to find sections by topic."
                    ),
                },
            },
            "required": ["section"],
        },
    },
}


def _read_section_transcript(sec: ConversationSection) -> str:
    """Read the transcript for a section from filesystem or return summary fallback."""
    if sec.transcript_path:
        import os
        from app.agent.context import current_bot_id
        from app.agent.bots import get_bot
        from app.services.workspace import workspace_service

        try:
            bot = get_bot(current_bot_id.get())
            ws_root = workspace_service.get_workspace_root(bot.id, bot)
            filepath = os.path.join(ws_root, sec.transcript_path)
            with open(filepath) as f:
                return f.read()
        except FileNotFoundError:
            return f"Transcript file not found: {sec.transcript_path}. Re-run backfill."
        except Exception:
            return f"Error reading transcript file: {sec.transcript_path}"

    # Fallback: no transcript file available
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
        f"Transcript file not available for this section."
    )


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


@register(_SCHEMA)
async def read_conversation_history(section: str) -> str:
    channel_id = current_channel_id.get()
    if not channel_id:
        return "No channel context available. This tool requires a channel-based conversation."

    if section == "index":
        async with async_session() as db:
            result = await db.execute(
                select(ConversationSection)
                .where(ConversationSection.channel_id == channel_id)
                .order_by(ConversationSection.sequence)
            )
            sections = result.scalars().all()

        if not sections:
            return "No archived conversation sections found for this channel."

        lines = ["Archived conversation sections:\n"]
        for s in sections:
            date_str = s.period_start.strftime("%Y-%m-%d %H:%M") if s.period_start else "unknown"
            tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
            lines.append(
                f"- [{s.id}] Section {s.sequence}: {s.title} "
                f"({s.message_count} msgs, {date_str}){tag_str}\n"
                f"  {s.summary}"
            )
        return "\n".join(lines)

    # Keyword search across archived sections
    if section.lower().startswith("search:"):
        query = section[7:].strip()
        if not query:
            return "Please provide a search query, e.g. 'search:database migration'."

        # Build ILIKE filter: every word must appear in title, summary, or tags
        from sqlalchemy import or_, cast, String
        keywords = query.split()
        filters = []
        for kw in keywords:
            pattern = f"%{kw}%"
            filters.append(or_(
                ConversationSection.title.ilike(pattern),
                ConversationSection.summary.ilike(pattern),
                cast(ConversationSection.tags, String).ilike(pattern),
            ))

        async with async_session() as db:
            result = await db.execute(
                select(ConversationSection)
                .where(
                    ConversationSection.channel_id == channel_id,
                    *filters,
                )
                .order_by(ConversationSection.sequence.desc())
                .limit(10)
            )
            matches = result.scalars().all()

        if not matches:
            return f"No sections found matching '{query}'."

        lines = [f"Sections matching '{query}':\n"]
        for s in matches:
            date_str = s.period_start.strftime("%Y-%m-%d %H:%M") if s.period_start else "unknown"
            tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
            lines.append(
                f"- Section #{s.sequence}: {s.title} "
                f"({s.message_count} msgs, {date_str}){tag_str}\n"
                f"  {s.summary}"
            )
        lines.append("\nUse read_conversation_history with a section number to read the full transcript.")
        return "\n".join(lines)

    # Try sequence number (bare integer)
    if section.isdigit():
        seq_num = int(section)
        async with async_session() as db:
            result = await db.execute(
                select(ConversationSection)
                .where(ConversationSection.channel_id == channel_id, ConversationSection.sequence == seq_num)
            )
            sec = result.scalar_one_or_none()
        if not sec:
            return f"Section #{seq_num} not found."
        await _track_view(sec.id)
        return _read_section_transcript(sec)

    # Try to parse as UUID
    try:
        section_id = uuid.UUID(section)
    except ValueError:
        return f"Invalid section ID: '{section}'. Pass 'index', a section number, or a valid UUID."

    async with async_session() as db:
        sec = await db.get(ConversationSection, section_id)

    if not sec or sec.channel_id != channel_id:
        return f"Section not found: {section}"

    await _track_view(sec.id)
    return _read_section_transcript(sec)
