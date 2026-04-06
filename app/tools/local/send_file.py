"""send_file — deliver a file to the current chat channel.

Two modes:
  1. path       → read from disk, create a new DB attachment, deliver to channel
  2. attachment_id → re-post an existing DB attachment to the current channel

Both modes create a channel-linked attachment (for web UI download links) AND
emit a client_action for immediate Slack delivery.
"""

import base64
import json
import mimetypes
import uuid
from pathlib import Path

from app.agent.context import current_bot_id, current_channel_id, current_dispatch_type
from app.services.attachments import create_attachment, find_orphan_duplicate, get_attachment_by_id
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "send_file",
        "description": (
            "Send a file to the current chat channel. Provide EITHER `path` (file on disk) "
            "OR `attachment_id` (existing attachment UUID from list_attachments). "
            "The file is saved as a persistent attachment visible on all clients "
            "(Slack, web UI, etc.). Works with any file type — images, PDFs, PPTX, CSV, etc. "
            "Workspace paths (e.g. /workspace/...) are translated automatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file on disk. Workspace paths like /workspace/... are translated automatically.",
                },
                "attachment_id": {
                    "type": "string",
                    "description": "UUID of an existing attachment to re-post (from list_attachments). Use instead of path.",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption to display with the file.",
                },
                "filename": {
                    "type": "string",
                    "description": "Override the filename shown to the user. Defaults to the original filename.",
                },
            },
            "required": [],
        },
    },
}, safety_tier="mutating")
async def send_file(
    path: str = "",
    attachment_id: str = "",
    caption: str = "",
    filename: str = "",
) -> str:
    if not path and not attachment_id:
        return json.dumps({"error": "Provide either `path` or `attachment_id`."})

    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    source = current_dispatch_type.get() or "web"

    # --- Mode 2: re-post an existing attachment ---
    if attachment_id:
        try:
            att_uuid = uuid.UUID(attachment_id)
        except ValueError:
            return json.dumps({"error": "Invalid attachment_id — must be a valid UUID."})

        att = await get_attachment_by_id(att_uuid)
        if att is None:
            return json.dumps({"error": f"Attachment {attachment_id} not found."})
        if not att.file_data:
            return json.dumps({"error": f"Attachment {attachment_id} has no stored file data."})

        display_name = filename or att.filename or "attachment"
        mime = att.mime_type or "application/octet-stream"
        data = att.file_data

        # Create a new channel-linked attachment so persist_turn's
        # orphan-linking attaches it to the assistant message — but only when
        # needed.  If the original attachment is already orphaned (no
        # message_id) in the same channel, it will be linked automatically
        # and creating a copy would cause a duplicate image in the UI.
        already_orphaned_here = (
            att.message_id is None
            and att.channel_id is not None
            and str(att.channel_id) == str(channel_id)
        )
        if channel_id and not already_orphaned_here:
            await create_attachment(
                message_id=None,
                channel_id=channel_id,
                filename=display_name,
                mime_type=mime,
                size_bytes=len(data),
                posted_by=bot_id or "agent",
                source_integration=source,
                file_data=data,
                attachment_type=att.type or ("image" if mime.startswith("image/") else "file"),
                bot_id=bot_id,
            )

        size_kb = len(data) / 1024
        msg = f"Sent {display_name} ({size_kb:.0f} KB)" + (f": {caption}" if caption else "")

        # If the attachment is already orphaned in this channel, another tool
        # (e.g. frigate_snapshot) created it in this same turn and already
        # emitted a client_action for immediate display.  Returning a second
        # client_action would cause Slack to upload the image twice.
        if already_orphaned_here:
            return json.dumps({"message": msg})

        b64 = base64.b64encode(data).decode("ascii")
        is_image = mime.startswith("image/")

        return json.dumps({
            "message": msg,
            "client_action": {
                "type": "upload_image" if is_image else "upload_file",
                "data": b64,
                "filename": display_name,
                "caption": caption,
            },
        })

    # --- Mode 1: read from disk ---
    from app.config import settings
    max_bytes = settings.ATTACHMENT_MAX_SIZE_BYTES or 50 * 1024 * 1024

    file_path = Path(path).expanduser()

    # Translate workspace container paths
    if not file_path.is_file():
        if bot_id:
            try:
                from app.agent.bots import get_bot
                from app.services.workspace import workspace_service
                bot = get_bot(bot_id)
                if bot:
                    translated = workspace_service.translate_path(bot_id, path, bot.workspace, bot=bot)
                    if translated != path:
                        file_path = Path(translated)
            except Exception:
                pass

    if not file_path.is_file():
        return json.dumps({"error": f"File not found: {path}"})

    size = file_path.stat().st_size
    if size == 0:
        return json.dumps({"error": f"File is empty: {path}"})
    if size > max_bytes:
        return json.dumps({"error": f"File too large: {size / 1024 / 1024:.1f} MB (max {max_bytes / 1024 / 1024:.0f} MB)"})

    data = file_path.read_bytes()

    display_name = filename or file_path.name
    mime, _ = mimetypes.guess_type(display_name)
    mime = mime or "application/octet-stream"
    is_image = mime.startswith("image/")
    size_kb = len(data) / 1024

    # Dedup: if another tool (e.g. generate_image) already created an orphan
    # attachment with matching size+mime in this channel, skip the duplicate.
    # This prevents the same image appearing twice when generate_image +
    # send_file run in the same turn (common in delegation flows).
    if channel_id:
        try:
            existing = await find_orphan_duplicate(channel_id, len(data), mime)
        except Exception:
            existing = None
        if existing:
            msg = f"Sent {display_name} ({size_kb:.0f} KB)" + (f": {caption}" if caption else "")
            return json.dumps({"message": msg})

    await create_attachment(
        message_id=None,
        channel_id=channel_id,
        filename=display_name,
        mime_type=mime,
        size_bytes=len(data),
        posted_by=bot_id or "agent",
        source_integration=source,
        file_data=data,
        attachment_type="image" if is_image else "file",
        bot_id=bot_id,
    )

    b64 = base64.b64encode(data).decode("ascii")

    return json.dumps({
        "message": f"Sent {display_name} ({size_kb:.0f} KB)" + (f": {caption}" if caption else ""),
        "client_action": {
            "type": "upload_image" if is_image else "upload_file",
            "data": b64,
            "filename": display_name,
            "caption": caption,
        },
    })
