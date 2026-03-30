"""Slide deck generator using Marp (Markdown → HTML/PDF/PPTX).

Requires: npx @marp-team/marp-cli (installed automatically if Node.js is available)
"""

import asyncio
import base64
import json
import logging
import mimetypes
import shutil
import tempfile
from pathlib import Path

from integrations._register import register

logger = logging.getLogger(__name__)


async def _ensure_marp() -> str | None:
    """Return the marp command path, installing via npx if needed."""
    if shutil.which("marp"):
        return "marp"

    if not shutil.which("npx"):
        return None

    proc = await asyncio.create_subprocess_exec(
        "npx", "--yes", "@marp-team/marp-cli", "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode == 0:
        return "npx --yes @marp-team/marp-cli"
    return None


@register({
    "type": "function",
    "function": {
        "name": "create_slides",
        "description": (
            "Create a slide deck using Marp (https://marp.app) — an open-source Markdown presentation ecosystem "
            "by @marp-team. Slides are separated by '---'. The file is saved as an attachment and "
            "delivered to the channel (Slack, web UI, etc.) without entering the conversation context. "
            "Supports HTML (self-contained), PDF, and PPTX output. "
            "Use Marp directives in YAML frontmatter for theming (theme, class, paginate, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "markdown": {
                    "type": "string",
                    "description": (
                        "Marp-flavored Markdown content. Use '---' to separate slides. "
                        "Include a YAML frontmatter block with 'marp: true' and optional directives."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": ["html", "pdf", "pptx"],
                    "description": "Output format. html = self-contained HTML file, pdf = PDF document, pptx = PowerPoint. Default: html.",
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename (without extension). Default: slides.",
                },
            },
            "required": ["markdown"],
        },
    },
})
async def create_slides(
    markdown: str,
    format: str = "html",
    filename: str = "slides",
) -> str:
    from app.agent.context import current_bot_id, current_channel_id, current_dispatch_type
    from app.services.attachments import create_attachment

    marp_cmd = await _ensure_marp()
    if not marp_cmd:
        return json.dumps({
            "error": (
                "Marp CLI is not available. Install it with: "
                "npm install -g @marp-team/marp-cli — "
                "or ensure Node.js/npx is on PATH for automatic install."
            )
        })

    if format not in ("html", "pdf", "pptx"):
        return json.dumps({"error": f"Unsupported format: {format}. Use html, pdf, or pptx."})

    # Ensure marp: true is in frontmatter
    if "marp: true" not in markdown:
        if markdown.startswith("---"):
            markdown = markdown.replace("---", "---\nmarp: true", 1)
        else:
            markdown = f"---\nmarp: true\n---\n\n{markdown}"

    ext = format if format != "html" else "html"

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "input.md"
        output_path = Path(tmpdir) / f"{filename}.{ext}"
        input_path.write_text(markdown, encoding="utf-8")

        cmd = f"{marp_cmd} {input_path} --{format} --allow-local-files -o {output_path}"

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            return json.dumps({"error": f"Marp conversion failed: {error_msg}"})

        if not output_path.exists():
            return json.dumps({"error": "Marp produced no output file."})

        data = output_path.read_bytes()

    display_name = f"{filename}.{ext}"
    mime, _ = mimetypes.guess_type(display_name)
    mime = mime or "application/octet-stream"

    # Save to DB so it persists across clients
    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    source = current_dispatch_type.get() or "web"

    att = await create_attachment(
        message_id=None,
        channel_id=channel_id,
        filename=display_name,
        mime_type=mime,
        size_bytes=len(data),
        posted_by=bot_id or "slides",
        source_integration=source,
        file_data=data,
        attachment_type="file",
        bot_id=bot_id,
    )

    # Also emit client_action for immediate delivery (stripped from LLM context)
    b64 = base64.b64encode(data).decode("ascii")
    size_kb = len(data) / 1024

    return json.dumps({
        "message": f"Created {display_name} ({size_kb:.0f} KB)",
        "client_action": {
            "type": "upload_file",
            "data": b64,
            "filename": display_name,
            "caption": "",
        },
    })
