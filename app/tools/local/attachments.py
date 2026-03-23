"""Local tools: get_attachment, list_attachments — attachment access for the agent."""

import base64
import json
import logging
import uuid

from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_attachment",
        "description": (
            "Fetch full attachment metadata and file bytes by ID. "
            "Returns file_data_base64 — a base64-encoded version of the file bytes. "
            "Pass this value directly as source_image_b64 to generate_image to edit the image. "
            "Also returns description, filename, posted_by, posted_at, type, mime_type."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "The UUID of the attachment to retrieve.",
                },
            },
            "required": ["attachment_id"],
        },
    },
})
async def get_attachment(attachment_id: str) -> str:
    from app.services.attachments import get_attachment_by_id

    try:
        att_uuid = uuid.UUID(attachment_id)
    except ValueError:
        return json.dumps({"error": "Invalid attachment_id — must be a valid UUID."})

    att = await get_attachment_by_id(att_uuid)
    if att is None:
        return json.dumps({"error": f"Attachment {attachment_id} not found."})

    return json.dumps({
        "id": str(att.id),
        "type": att.type,
        "filename": att.filename,
        "mime_type": att.mime_type,
        "size_bytes": att.size_bytes,
        "posted_by": att.posted_by,
        "posted_at": att.created_at.isoformat() if att.created_at else None,
        "source_integration": att.source_integration,
        "description": att.description,
        "description_model": att.description_model,
        "described_at": att.described_at.isoformat() if att.described_at else None,
        "file_data_base64": base64.b64encode(att.file_data).decode() if att.file_data else None,
    })


@register({
    "type": "function",
    "function": {
        "name": "list_attachments",
        "description": (
            "List recent attachments in the current channel. "
            "Use this to find images or files posted earlier in the conversation. "
            "Returns attachment IDs, filenames, types, descriptions, and posted_at timestamps. "
            "Pass an attachment ID to get_attachment() to retrieve the full file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Channel UUID to list attachments for. Defaults to current channel if omitted.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of attachments to return (default 5, max 20).",
                    "default": 5,
                },
                "type_filter": {
                    "type": "string",
                    "description": "Filter by type: 'image', 'file', 'text', 'audio', 'video'. Omit for all types.",
                },
            },
            "required": [],
        },
    },
})
async def list_attachments(
    channel_id: str | None = None,
    limit: int = 5,
    type_filter: str | None = None,
) -> str:
    from sqlalchemy import select

    from app.agent.context import current_channel_id
    from app.db.engine import async_session
    from app.db.models import Attachment

    limit = max(1, min(limit, 20))

    # Resolve channel_id
    ch_id: uuid.UUID | None = None
    if channel_id:
        try:
            ch_id = uuid.UUID(channel_id)
        except ValueError:
            return json.dumps({"error": "Invalid channel_id — must be a valid UUID."})
    else:
        ch_id = current_channel_id.get()

    if ch_id is None:
        return json.dumps({"error": "No channel_id provided and no current channel context."})

    async with async_session() as db:
        stmt = (
            select(Attachment)
            .where(Attachment.channel_id == ch_id)
            .order_by(Attachment.created_at.desc())
        )
        if type_filter:
            stmt = stmt.where(Attachment.type == type_filter)
        stmt = stmt.limit(limit)

        result = await db.execute(stmt)
        attachments = result.scalars().all()

    items = [
        {
            "id": str(att.id),
            "filename": att.filename,
            "type": att.type,
            "mime_type": att.mime_type,
            "size_bytes": att.size_bytes,
            "description": (att.description or "")[:200] or None,
            "posted_by": att.posted_by,
            "posted_at": att.created_at.isoformat() if att.created_at else None,
        }
        for att in attachments
    ]
    return json.dumps({"attachments": items, "count": len(items)})
