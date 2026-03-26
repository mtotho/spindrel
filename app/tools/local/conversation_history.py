"""Tool for navigating archived conversation history sections (file mode)."""
import uuid

from sqlalchemy import select

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
            "of all archived sections, or pass a section UUID to read the full transcript of that section."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Either 'index' to list all sections, or a section UUID to read its full content.",
                },
            },
            "required": ["section"],
        },
    },
}


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
            lines.append(
                f"- [{s.id}] Section {s.sequence}: {s.title} "
                f"({s.message_count} msgs, {date_str})\n"
                f"  {s.summary}"
            )
        return "\n".join(lines)

    # Try to parse as UUID
    try:
        section_id = uuid.UUID(section)
    except ValueError:
        return f"Invalid section ID: '{section}'. Pass 'index' or a valid UUID."

    async with async_session() as db:
        sec = await db.get(ConversationSection, section_id)

    if not sec or sec.channel_id != channel_id:
        return f"Section not found: {section}"

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
        f"{sec.transcript}"
    )
