"""Local tool: get_attachment — fetch full attachment metadata + file bytes."""

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
            "Pass this directly to vision or image editing models. "
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
