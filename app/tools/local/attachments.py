"""Local tools: get_attachment, list_attachments, post_attachment — attachment access for the agent."""

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
            "Fetch attachment metadata by ID. Returns description, filename, posted_by, "
            "posted_at, type, mime_type, and has_file_data (whether raw bytes are stored). "
            "To edit an image, pass the attachment_id directly to generate_image — "
            "do NOT use this tool to get base64 data for image editing."
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
        "has_file_data": att.file_data is not None,
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
                    "description": "OPTIONAL: Channel UUID to list attachments for. Defaults to current channel if omitted.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of attachments to return per page (default 5, max 50).",
                    "default": 5,
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based, default 1). Use with limit to paginate through results.",
                    "default": 1,
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
    page: int = 1,
    type_filter: str | None = None,
) -> str:
    from sqlalchemy import func, select

    from app.agent.context import current_channel_id
    from app.db.engine import async_session
    from app.db.models import Attachment

    limit = max(1, min(limit, 50))
    page = max(1, page)
    offset = (page - 1) * limit

    # Resolve channel_id
    ch_id: uuid.UUID | None = None
    if channel_id:
        try:
            ch_id = uuid.UUID(channel_id)
        except ValueError:
            # LLM may pass a Slack channel ID (e.g. C06RY3YBSLE) — fall back to current context
            logger.warning("list_attachments: invalid UUID %r, falling back to current_channel_id", channel_id)
            ch_id = current_channel_id.get()
    else:
        ch_id = current_channel_id.get()

    if ch_id is None:
        return json.dumps({"error": "No channel_id provided and no current channel context."})

    async with async_session() as db:
        # Total count
        count_stmt = select(func.count()).select_from(Attachment).where(Attachment.channel_id == ch_id)
        if type_filter:
            count_stmt = count_stmt.where(Attachment.type == type_filter)
        total = (await db.execute(count_stmt)).scalar() or 0

        # Page of results
        stmt = (
            select(Attachment)
            .where(Attachment.channel_id == ch_id)
            .order_by(Attachment.created_at.desc())
        )
        if type_filter:
            stmt = stmt.where(Attachment.type == type_filter)
        stmt = stmt.offset(offset).limit(limit)

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
    total_pages = (total + limit - 1) // limit
    return json.dumps({
        "attachments": items,
        "page": page,
        "total_pages": total_pages,
        "total_count": total,
        "showing": f"{offset + 1}-{offset + len(items)} of {total}",
    })


@register({
    "type": "function",
    "function": {
        "name": "post_attachment",
        "description": (
            "Post an attachment (image, video, or file) into the chat. "
            "Looks up the attachment by ID and uploads it inline. "
            "Works with any attachment — Frigate snapshots/clips, generated images, "
            "uploaded files, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "The UUID of the attachment to post.",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption to display with the attachment.",
                },
            },
            "required": ["attachment_id"],
        },
    },
})
async def post_attachment(attachment_id: str, caption: str = "") -> str:
    from app.services.attachments import get_attachment_by_id

    try:
        att_uuid = uuid.UUID(attachment_id)
    except ValueError:
        return json.dumps({"error": "Invalid attachment_id — must be a valid UUID."})

    att = await get_attachment_by_id(att_uuid)
    if att is None:
        return json.dumps({"error": f"Attachment {attachment_id} not found."})

    if not att.file_data:
        return json.dumps({"error": f"Attachment {attachment_id} has no stored file data."})

    mime = att.mime_type or ""
    action_type = "upload_image" if mime.startswith("image/") else "upload_file"

    b64 = base64.b64encode(att.file_data).decode("ascii")
    return json.dumps({
        "message": f"Posted {att.filename or attachment_id}" + (f": {caption}" if caption else ""),
        "client_action": {
            "type": action_type,
            "data": b64,
            "filename": att.filename or "attachment",
            "caption": caption,
        },
    })
