"""Slide deck generator using Marp (Markdown to HTML/PDF/PPTX)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
from pathlib import Path

from integrations.sdk import (
    create_widget_backed_attachment,
    current_bot_id,
    current_channel_id,
    current_dispatch_type,
    register_tool as register,
)

logger = logging.getLogger(__name__)


def _find_chrome_path() -> str | None:
    """Find a usable Chromium/Chrome binary, avoiding snap-packaged browsers."""
    for env in ("CHROME_PATH", "PUPPETEER_EXECUTABLE_PATH"):
        val = os.environ.get(env)
        if val and shutil.which(val):
            return val

    for candidate in (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return None


async def _ensure_marp() -> list[str] | None:
    """Return the Marp command argv, installing via npx if needed."""
    if shutil.which("marp"):
        return ["marp"]

    if not shutil.which("npx"):
        return None

    proc = await asyncio.create_subprocess_exec(
        "npx",
        "--yes",
        "@marp-team/marp-cli",
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode == 0:
        return ["npx", "--yes", "@marp-team/marp-cli"]
    return None


def _safe_filename_stem(filename: str) -> str:
    stem = Path(filename or "marp-slides").stem.strip()
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "-", stem)
    stem = stem.strip(" .-_")
    return stem[:80] or "marp-slides"


@register(
    {
        "type": "function",
        "function": {
            "name": "create_marp_slides",
            "description": (
                "Create a slide deck using Marp Markdown (https://marp.app). "
                "Slides are separated by '---'. The file is saved as an attachment and "
                "delivered to the channel without entering conversation context. Supports "
                "HTML, PDF, and PPTX output. Use Marp directives in YAML frontmatter for "
                "theme, class, paginate, size, and other presentation settings."
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
                        "description": "Output filename without extension. Default: marp-slides.",
                    },
                },
                "required": ["markdown"],
            },
        },
    },
    safety_tier="mutating",
    requires_bot_context=True,
    requires_channel_context=True,
)
async def create_marp_slides(
    markdown: str,
    format: str = "html",
    filename: str = "marp-slides",
) -> str:
    marp_cmd = await _ensure_marp()
    if not marp_cmd:
        return json.dumps({
            "error": (
                "Marp CLI is not available. Install Node.js/npx, or install it with: "
                "npm install -g @marp-team/marp-cli."
            )
        })

    if format not in ("html", "pdf", "pptx"):
        return json.dumps({"error": f"Unsupported format: {format}. Use html, pdf, or pptx."})

    if "marp: true" not in markdown:
        if markdown.startswith("---"):
            markdown = markdown.replace("---", "---\nmarp: true", 1)
        else:
            markdown = f"---\nmarp: true\n---\n\n{markdown}"

    output_stem = _safe_filename_stem(filename)

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "input.md"
        output_path = Path(tmpdir) / f"{output_stem}.{format}"
        input_path.write_text(markdown, encoding="utf-8")

        env = os.environ.copy()
        chrome = _find_chrome_path()
        if chrome:
            env["CHROME_PATH"] = chrome
            logger.info("Using browser for Marp: %s", chrome)

        proc = await asyncio.create_subprocess_exec(
            *marp_cmd,
            str(input_path),
            f"--{format}",
            "--allow-local-files",
            "-o",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            return json.dumps({"error": f"Marp conversion failed: {error_msg}"})

        if not output_path.exists():
            return json.dumps({"error": "Marp produced no output file."})

        data = output_path.read_bytes()

    display_name = f"{output_stem}.{format}"
    mime, _ = mimetypes.guess_type(display_name)
    mime = mime or "application/octet-stream"

    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    source = current_dispatch_type.get() or "web"

    att = await create_widget_backed_attachment(
        tool_name="create_marp_slides",
        channel_id=channel_id,
        filename=display_name,
        mime_type=mime,
        size_bytes=len(data),
        posted_by=bot_id or "marp_slides",
        source_integration=source,
        file_data=data,
        attachment_type="file",
        bot_id=bot_id,
    )

    b64 = base64.b64encode(data).decode("ascii")
    size_kb = len(data) / 1024

    return json.dumps({
        "message": f"Created {display_name} ({size_kb:.0f} KB)",
        "attachment_id": str(att.id),
        "filename": display_name,
        "mime_type": mime,
        "size_bytes": len(data),
        "client_action": {
            "type": "upload_file",
            "data": b64,
            "filename": display_name,
            "caption": "",
        },
    })
