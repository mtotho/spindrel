"""send_file — upload a file from disk to the current chat channel.

Saves as a DB attachment (persistent across clients) and emits a client_action
for immediate delivery. The file bytes never enter the LLM context.
"""

import base64
import json
import mimetypes
from pathlib import Path

from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "send_file",
        "description": (
            "Send a file from disk to the current chat. The file is saved as an "
            "attachment and delivered to the channel (Slack, web UI, etc.). "
            "Works with any file type — images, PDFs, HTML, PPTX, CSV, etc. "
            "The file persists in message history across all clients."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file on disk.",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption or message to display with the file.",
                },
                "filename": {
                    "type": "string",
                    "description": "Override the filename shown to the user. Defaults to the file's basename.",
                },
            },
            "required": ["path"],
        },
    },
})
async def send_file(path: str, caption: str = "", filename: str = "") -> str:
    from app.agent.context import current_bot_id, current_channel_id, current_dispatch_type
    from app.services.attachments import create_attachment

    from app.config import settings
    max_bytes = settings.ATTACHMENT_MAX_SIZE_BYTES or 50 * 1024 * 1024  # fallback 50 MB

    file_path = Path(path).expanduser()
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

    # Save to DB for persistence
    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    source = current_dispatch_type.get() or "web"

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

    # Emit client_action for immediate delivery (stripped from LLM context)
    b64 = base64.b64encode(data).decode("ascii")
    size_kb = len(data) / 1024

    return json.dumps({
        "message": f"Sent {display_name} ({size_kb:.0f} KB)" + (f": {caption}" if caption else ""),
        "client_action": {
            "type": "upload_image" if is_image else "upload_file",
            "data": b64,
            "filename": display_name,
            "caption": caption,
        },
    })
