"""Local tool: get_attachment — fetch full attachment metadata + description."""

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
            "Fetch full attachment metadata and description by ID. "
            "Returns url, description, filename, posted_by, posted_at, type, mime_type. "
            "For text files, includes the description/summary. "
            "For images, returns url + vision description."
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
        "url": att.url,
        "size_bytes": att.size_bytes,
        "posted_by": att.posted_by,
        "posted_at": att.created_at.isoformat() if att.created_at else None,
        "source_integration": att.source_integration,
        "description": att.description,
        "description_model": att.description_model,
        "described_at": att.described_at.isoformat() if att.described_at else None,
    })
