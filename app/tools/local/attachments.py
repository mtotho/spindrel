"""Local tools: get_attachment, list_attachments, save_attachment — attachment access for the agent."""

import base64
import json
import logging
import uuid
from pathlib import Path

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
        return json.dumps({"error": "Invalid attachment_id — must be a valid UUID."}, ensure_ascii=False)

    att = await get_attachment_by_id(att_uuid)
    if att is None:
        return json.dumps({"error": f"Attachment {attachment_id} not found."}, ensure_ascii=False)

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
    }, ensure_ascii=False)


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
}, requires_channel_context=True)
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

    limit = max(1, min(int(limit), 50))
    page = max(1, int(page))
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
        return json.dumps({"error": "No channel_id provided and no current channel context."}, ensure_ascii=False)

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
    }, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "view_attachment",
        "description": (
            "Load an image attachment into the conversation so YOU can see it directly. "
            "Unlike describe_attachment (which uses a separate vision model call), this "
            "injects the image into your own context — you see the actual pixels and can "
            "analyze them with your full capabilities. Use this for detailed visual "
            "assessment where your own judgment matters (e.g. dough assessment, plant "
            "health, photo comparison). Works with image attachments only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "The UUID of the image attachment to view.",
                },
            },
            "required": ["attachment_id"],
        },
    },
})
async def view_attachment(attachment_id: str) -> str:
    from app.services.attachments import get_attachment_by_id

    try:
        att_uuid = uuid.UUID(attachment_id)
    except ValueError:
        return json.dumps({"error": "Invalid attachment_id — must be a valid UUID."}, ensure_ascii=False)

    att = await get_attachment_by_id(att_uuid)
    if att is None:
        return json.dumps({"error": f"Attachment {attachment_id} not found."}, ensure_ascii=False)

    mime = att.mime_type or ""
    if not mime.startswith("image/"):
        return json.dumps({"error": f"view_attachment only supports images, got {mime}"}, ensure_ascii=False)

    if not att.file_data:
        return json.dumps({"error": f"Attachment {attachment_id} has no stored file data."}, ensure_ascii=False)

    b64 = base64.b64encode(att.file_data).decode("ascii")
    return json.dumps({
        "injected_images": [{"mime_type": mime, "base64": b64}],
        "message": f"Image '{att.filename}' loaded — analyze it and respond.",
    }, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "describe_attachment",
        "description": (
            "Describe or answer questions about an image attachment. "
            "Without a prompt, returns the existing auto-generated description (no extra LLM call). "
            "With a prompt, makes a fresh vision model call to answer the specific question "
            "(e.g. 'Is there anyone at the front door?', 'How many cars are in the driveway?'). "
            "Works with image attachments only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "The UUID of the image attachment to analyze.",
                },
                "prompt": {
                    "type": "string",
                    "description": "Specific question for the vision model. If omitted, returns the existing auto-generated description.",
                },
            },
            "required": ["attachment_id"],
        },
    },
})
async def describe_attachment(attachment_id: str, prompt: str = "") -> str:
    from app.services.attachments import get_attachment_by_id

    try:
        att_uuid = uuid.UUID(attachment_id)
    except ValueError:
        return json.dumps({"error": "Invalid attachment_id — must be a valid UUID."}, ensure_ascii=False)

    att = await get_attachment_by_id(att_uuid)
    if att is None:
        return json.dumps({"error": f"Attachment {attachment_id} not found."}, ensure_ascii=False)

    mime = att.mime_type or ""
    if not mime.startswith("image/"):
        return json.dumps({"error": f"describe_attachment only supports images, got {mime}"}, ensure_ascii=False)

    text_prompt = (prompt or "").strip()

    # No custom prompt — return existing description if available
    if not text_prompt:
        if att.description:
            return json.dumps({
                "attachment_id": attachment_id,
                "filename": att.filename,
                "description": att.description,
            }, ensure_ascii=False)
        # No description yet (sweep hasn't run) — fall back to a vision call
        text_prompt = (
            "Describe what you see in this image in detail. Include objects, people, "
            "text, colors, and any notable features."
        )

    # Custom prompt or missing description — make a fresh vision call
    if not att.file_data:
        return json.dumps({"error": f"Attachment {attachment_id} has no stored file data."}, ensure_ascii=False)

    from app.config import settings
    from app.services.providers import get_llm_client

    b64 = base64.b64encode(att.file_data).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    model = settings.ATTACHMENT_SUMMARY_MODEL
    provider_id = settings.ATTACHMENT_SUMMARY_MODEL_PROVIDER_ID or None

    try:
        response = await get_llm_client(provider_id).chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_tokens=1000,
            temperature=0.3,
        )
        description = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("describe_attachment vision call failed")
        return json.dumps({"error": f"Vision model error: {e}"}, ensure_ascii=False)

    return json.dumps({
        "attachment_id": attachment_id,
        "filename": att.filename,
        "description": description,
    }, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "delete_attachment",
        "description": (
            "Permanently delete an attachment from the database and from any "
            "connected integration (e.g. Slack). Use list_attachments to find "
            "the attachment ID first. This is irreversible."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "The UUID of the attachment to delete.",
                },
            },
            "required": ["attachment_id"],
        },
    },
})
async def delete_attachment(attachment_id: str) -> str:
    from app.services.attachments import delete_attachment as _delete

    try:
        att_uuid = uuid.UUID(attachment_id)
    except ValueError:
        return json.dumps({"error": "Invalid attachment_id — must be a valid UUID."}, ensure_ascii=False)

    result = await _delete(att_uuid)
    return json.dumps(result, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "delete_recent_attachments",
        "description": (
            "Delete all attachments in the current channel that were created within "
            "the last max_age_seconds. Useful for cleaning up temporary files "
            "(e.g. photos sent for assessment) without needing to look up individual IDs. "
            "Also deletes from connected integrations (e.g. Slack). Returns a list of "
            "what was deleted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "max_age_seconds": {
                    "type": "integer",
                    "description": "Only delete attachments created within this many seconds ago. Default 120 (2 minutes). Max 600 (10 minutes).",
                    "default": 120,
                },
                "type_filter": {
                    "type": "string",
                    "description": "Only delete attachments of this type: 'image', 'file', 'text', 'audio', 'video'. Omit for all types.",
                },
            },
            "required": [],
        },
    },
}, requires_channel_context=True)
async def delete_recent_attachments(
    max_age_seconds: int = 120,
    type_filter: str | None = None,
) -> str:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.agent.context import current_channel_id
    from app.db.engine import async_session
    from app.db.models import Attachment
    from app.services.attachments import delete_attachment as _delete

    ch_id = current_channel_id.get()
    if ch_id is None:
        return json.dumps({"error": "No current channel context."}, ensure_ascii=False)

    max_age_seconds = max(1, min(int(max_age_seconds), 600))
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)

    async with async_session() as db:
        stmt = (
            select(Attachment.id, Attachment.filename, Attachment.type, Attachment.created_at)
            .where(
                Attachment.channel_id == ch_id,
                Attachment.created_at >= cutoff,
            )
            .order_by(Attachment.created_at.desc())
        )
        if type_filter:
            stmt = stmt.where(Attachment.type == type_filter)

        rows = (await db.execute(stmt)).all()

    if not rows:
        return json.dumps({
            "message": f"No attachments found in this channel within the last {max_age_seconds} seconds.",
            "deleted_count": 0,
        }, ensure_ascii=False)

    deleted = []
    for row in rows:
        result = await _delete(row.id)
        if "error" not in result:
            deleted.append({
                "id": str(row.id),
                "filename": row.filename,
                "type": row.type,
                "integration_deleted": result.get("integration_deleted", False),
            })

    return json.dumps({
        "message": f"Deleted {len(deleted)} attachment(s).",
        "deleted_count": len(deleted),
        "deleted": deleted,
    }, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "save_attachment",
        "description": (
            "Save an attachment's file data to a path on disk. "
            "Use this to download images or files from the conversation to the filesystem — "
            "for example, to include Slack images in a slide deck or process uploaded files locally."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "The UUID of the attachment to save.",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Destination file path. If a directory, the original filename is used. "
                        "Parent directories are created automatically."
                    ),
                },
            },
            "required": ["attachment_id", "path"],
        },
    },
}, requires_bot_context=True)
async def save_attachment(attachment_id: str, path: str) -> str:
    from app.agent.context import current_bot_id
    from app.services.attachments import get_attachment_by_id

    try:
        att_uuid = uuid.UUID(attachment_id)
    except ValueError:
        return json.dumps({"error": "Invalid attachment_id — must be a valid UUID."}, ensure_ascii=False)

    att = await get_attachment_by_id(att_uuid)
    if att is None:
        return json.dumps({"error": f"Attachment {attachment_id} not found."}, ensure_ascii=False)

    if not att.file_data:
        return json.dumps({"error": f"Attachment {attachment_id} has no stored file data."}, ensure_ascii=False)

    # Translate workspace container paths (e.g. /workspace/...) to server-local paths
    resolved_path = path
    bot_id = current_bot_id.get()
    if bot_id:
        try:
            from app.agent.bots import get_bot
            from app.services.workspace import workspace_service
            bot = get_bot(bot_id)
            if bot:
                translated = workspace_service.translate_path(bot_id, path, bot.workspace, bot=bot)
                if translated != path:
                    resolved_path = translated
        except Exception:
            pass

    dest = Path(resolved_path).expanduser()
    if dest.is_dir():
        dest = dest / (att.filename or f"attachment_{attachment_id}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(att.file_data)

    return json.dumps({
        "saved": str(dest),
        "filename": att.filename,
        "size_bytes": len(att.file_data),
    }, ensure_ascii=False)
