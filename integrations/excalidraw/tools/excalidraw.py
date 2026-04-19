"""Excalidraw diagram generator — JSON or Mermaid → SVG/PNG.

Requires: Node.js + Chrome/Chromium (same as the slides/Marp integration).
Dependencies auto-install on first use via npm.
"""

import asyncio
import base64
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from integrations.sdk import register_tool as register

logger = logging.getLogger(__name__)

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_NODE_MODULES = _SCRIPTS_DIR / "node_modules"
_M2E_BUNDLE = _SCRIPTS_DIR / "mermaid-to-excalidraw.bundle.js"
_INSTALL_LOCK = asyncio.Lock()


def _find_chrome_path() -> str | None:
    """Find a usable Chromium/Chrome binary.

    Check order: integration setting → env vars → well-known paths.
    """
    # 1. Integration setting (configured via admin UI)
    try:
        from app.services.integration_settings import get_value
        val = get_value("excalidraw", "EXCALIDRAW_CHROME_PATH")
        if val and shutil.which(val):
            return val
    except Exception:
        pass

    # 2. Environment variables
    for env in ("CHROME_PATH", "PUPPETEER_EXECUTABLE_PATH"):
        val = os.environ.get(env)
        if val and shutil.which(val):
            return val

    # 3. Well-known paths
    for candidate in (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


async def _ensure_deps() -> str | None:
    """Install Node dependencies if needed. Returns error string or None."""
    if _NODE_MODULES.is_dir():
        return None

    if not shutil.which("npm"):
        return "npm is not available. Install Node.js to use Excalidraw tools."

    async with _INSTALL_LOCK:
        # Double-check after acquiring lock
        if _NODE_MODULES.is_dir():
            return None

        logger.info("Installing Excalidraw export dependencies in %s", _SCRIPTS_DIR)
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", "--no-audit", "--no-fund",
            cwd=str(_SCRIPTS_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            return f"Failed to install dependencies: {err}"

        # Build the mermaid-to-excalidraw browser bundle if missing
        if not _M2E_BUNDLE.exists():
            logger.info("Building mermaid-to-excalidraw browser bundle")
            entry = _SCRIPTS_DIR / "_bundle_entry.mjs"
            entry.write_text(
                'import { parseMermaidToExcalidraw } from "@excalidraw/mermaid-to-excalidraw";\n'
                'window.parseMermaidToExcalidraw = parseMermaidToExcalidraw;\n',
            )
            proc = await asyncio.create_subprocess_exec(
                "npx", "--yes", "esbuild", str(entry),
                "--bundle", "--format=iife", "--platform=browser",
                f"--outfile={_M2E_BUNDLE}", "--minify",
                cwd=str(_SCRIPTS_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            entry.unlink(missing_ok=True)
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace").strip()
                logger.warning("Failed to build mermaid bundle: %s", err)
                # Non-fatal: mermaid_to_excalidraw tool won't work, but create_excalidraw will

        logger.info("Excalidraw dependencies installed successfully")
        return None


async def _export_scene(scene: dict, output_path: Path) -> str | None:
    """Export an Excalidraw scene to SVG or PNG. Returns error or None."""
    err = await _ensure_deps()
    if err:
        return err

    chrome = _find_chrome_path()
    if not chrome:
        return (
            "No Chrome/Chromium found. Install chromium or google-chrome, "
            "or set CHROME_PATH environment variable."
        )

    export_script = _SCRIPTS_DIR / "export.mjs"
    input_path = output_path.parent / "input.excalidraw"
    input_path.write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")

    proc = await asyncio.create_subprocess_exec(
        "node", str(export_script),
        str(input_path), str(output_path),
        "--chrome", chrome,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_msg = stderr.decode("utf-8", errors="replace").strip()
        out_msg = stdout.decode("utf-8", errors="replace").strip()
        return f"{err_msg}\n{out_msg}".strip() or "Export failed with no error message"

    if not output_path.exists():
        return "Export produced no output file"
    return None


def _normalize_element(el: dict, idx: int) -> dict:
    """Fill in required Excalidraw element fields that the LLM may omit."""
    import random
    defaults = {
        "id": el.get("id", f"el_{idx}"),
        "type": el.get("type", "rectangle"),
        "x": 0,
        "y": 0,
        "width": 100,
        "height": 50,
        "angle": 0,
        "opacity": 100,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "hachure",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "seed": random.randint(1, 2**31),
        "version": 1,
        "versionNonce": random.randint(1, 2**31),
        "isDeleted": False,
        "groupIds": [],
        "boundElements": None,
        "roundness": None,
    }
    # Text elements need extra defaults
    if el.get("type") == "text":
        defaults.update({
            "text": el.get("text", ""),
            "fontSize": 20,
            "fontFamily": 1,
            "textAlign": "left",
            "verticalAlign": "top",
            "baseline": 18,
            "containerId": None,
            "originalText": el.get("text", ""),
        })
    # Arrow/line elements need points
    if el.get("type") in ("arrow", "line"):
        defaults["points"] = el.get("points", [[0, 0], [100, 0]])
        defaults["startBinding"] = el.get("startBinding", None)
        defaults["endBinding"] = el.get("endBinding", None)
        defaults["startArrowhead"] = None
        defaults["endArrowhead"] = "arrow" if el.get("type") == "arrow" else None

    # Merge: user values override defaults
    merged = {**defaults, **el}
    # Ensure originalText stays in sync with text
    if merged.get("type") == "text" and "originalText" not in el:
        merged["originalText"] = merged.get("text", "")
    return merged


def _expand_labels(elements: list) -> list:
    """Expand mermaid-to-excalidraw label objects into separate text elements.

    The @excalidraw/mermaid-to-excalidraw library puts text in a ``label``
    property on shape/arrow elements instead of creating standalone text
    elements.  This function extracts those labels into proper text elements
    bound to their parent shape.
    """
    expanded = []
    for el in elements:
        label = el.pop("label", None)
        expanded.append(el)
        if label and isinstance(label, dict) and label.get("text"):
            text_id = f"{el.get('id', 'el')}_label"
            # Center the label inside the parent shape
            parent_x = el.get("x", 0)
            parent_y = el.get("y", 0)
            parent_w = el.get("width", 100)
            parent_h = el.get("height", 50)
            font_size = label.get("fontSize", 20)
            # Mermaid uses <br> for line breaks — convert to real newlines
            text_val = label["text"].replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            # Estimate text dimensions
            est_w = len(text_val) * font_size * 0.6
            est_h = font_size * 1.4
            text_el = {
                "id": text_id,
                "type": "text",
                "x": parent_x + (parent_w - est_w) / 2,
                "y": parent_y + (parent_h - est_h) / 2,
                "width": est_w,
                "height": est_h,
                "text": text_val,
                "fontSize": font_size,
                "containerId": el.get("id"),
                "groupIds": label.get("groupIds", []),
            }
            expanded.append(text_el)
            # Link parent to the text element
            bound = el.get("boundElements") or []
            bound.append({"id": text_id, "type": "text"})
            el["boundElements"] = bound
    return expanded


def _wrap_elements(elements: list, app_state: dict | None = None) -> dict:
    """Wrap an elements array into a full Excalidraw document, normalizing each element."""
    normalized = [_normalize_element(el, i) for i, el in enumerate(elements)]
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "spindrel",
        "elements": normalized,
        "appState": app_state or {"viewBackgroundColor": "#ffffff"},
    }


def _validate_scene(scene: dict) -> str | None:
    """Light validation. Returns error string or None."""
    if not isinstance(scene.get("elements"), list):
        return "elements must be a list"
    if scene.get("type") != "excalidraw":
        return "missing or wrong 'type' field (expected 'excalidraw')"
    return None


async def _deliver(data: bytes, filename: str, mime: str, *, tool_name: str) -> str:
    """Persist attachment → return attachment_id + client_action JSON.

    ``tool_name`` routes through ``create_widget_backed_attachment`` so the
    web UI renders via the registered HTML widget (fetching by id) instead
    of through orphan-linking. ``client_action`` still carries the base64
    payload for Slack/Discord renderers — those surfaces don't render the
    widget and rely on ``client_action`` as their only display path.
    """
    from app.agent.context import current_bot_id, current_channel_id, current_dispatch_type
    from app.services.attachments import create_widget_backed_attachment

    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    source = current_dispatch_type.get() or "web"

    att = await create_widget_backed_attachment(
        tool_name=tool_name,
        channel_id=channel_id,
        filename=filename,
        mime_type=mime,
        size_bytes=len(data),
        posted_by=bot_id or "excalidraw",
        source_integration=source,
        file_data=data,
        attachment_type="image",
        bot_id=bot_id,
    )

    b64 = base64.b64encode(data).decode("ascii")
    size_kb = len(data) / 1024

    return json.dumps({
        "message": f"Created {filename} ({size_kb:.0f} KB)",
        "attachment_id": str(att.id),
        "filename": filename,
        "mime_type": mime,
        "size_bytes": len(data),
        "client_action": {
            "type": "upload_file",
            "data": b64,
            "filename": filename,
            "caption": "",
        },
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 1: create_excalidraw
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "create_excalidraw",
        "description": (
            "Create a hand-drawn-style diagram using Excalidraw. Provide an array of "
            "Excalidraw element objects and receive a rendered image delivered directly "
            "to the chat. Each element needs: id, type, x, y, width, height. "
            "Supported types: rectangle, ellipse, diamond, line, arrow, text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "elements": {
                    "type": "array",
                    "description": (
                        "Array of Excalidraw element objects. Each needs at minimum: "
                        "id (string), type (rectangle|ellipse|diamond|line|arrow|text), "
                        "x, y, width, height. Arrows use a 'points' array of [dx,dy] "
                        "pairs and optional startBinding/endBinding."
                    ),
                    "items": {"type": "object"},
                },
                "app_state": {
                    "type": "object",
                    "description": "Optional. Keys: viewBackgroundColor (default '#ffffff'), theme ('light'|'dark').",
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename without extension. Default: diagram.",
                },
                "format": {
                    "type": "string",
                    "enum": ["svg", "png"],
                    "description": "Output format. Default: png.",
                },
            },
            "required": ["elements"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True)
async def create_excalidraw(
    elements: list,
    app_state: dict | None = None,
    filename: str = "diagram",
    format: str = "png",
) -> str:
    # Some models serialize the array as a JSON string
    if isinstance(elements, str):
        try:
            elements = json.loads(elements)
        except json.JSONDecodeError:
            return json.dumps({"error": "elements must be a JSON array, got unparseable string"}, ensure_ascii=False)

    if format not in ("svg", "png"):
        return json.dumps({"error": f"Unsupported format: {format}. Use svg or png."}, ensure_ascii=False)

    scene = _wrap_elements(elements, app_state)
    err = _validate_scene(scene)
    if err:
        return json.dumps({"error": f"Invalid Excalidraw data: {err}"}, ensure_ascii=False)

    display_name = f"{filename}.{format}"
    mime = "image/svg+xml" if format == "svg" else "image/png"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / display_name
        err = await _export_scene(scene, output_path)
        if err:
            return json.dumps({"error": f"Export failed: {err}"}, ensure_ascii=False)
        data = output_path.read_bytes()

    return await _deliver(data, display_name, mime, tool_name="create_excalidraw")


# ---------------------------------------------------------------------------
# Tool 2: mermaid_to_excalidraw
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "mermaid_to_excalidraw",
        "description": (
            "Convert a Mermaid diagram to a hand-drawn Excalidraw image. "
            "Write standard Mermaid syntax (flowchart, sequence, ER, etc.) and "
            "receive a rendered image delivered directly to the chat. "
            "Best for flowcharts and sequence diagrams."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mermaid": {
                    "type": "string",
                    "description": (
                        "Mermaid diagram definition. Example: "
                        "'flowchart TD\\n    A[Start] --> B{Decision}\\n    B -->|Yes| C[Done]'"
                    ),
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename without extension. Default: diagram.",
                },
                "format": {
                    "type": "string",
                    "enum": ["svg", "png"],
                    "description": "Output format. Default: png.",
                },
            },
            "required": ["mermaid"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True)
async def mermaid_to_excalidraw(
    mermaid: str,
    filename: str = "diagram",
    format: str = "png",
) -> str:
    if format not in ("svg", "png"):
        return json.dumps({"error": f"Unsupported format: {format}. Use svg or png."}, ensure_ascii=False)

    # Ensure export deps are installed (also validates Node availability)
    err = await _ensure_deps()
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    convert_script = _SCRIPTS_DIR / "mermaid_convert.mjs"
    if not convert_script.exists():
        return json.dumps({"error": "mermaid_convert.mjs script is missing."}, ensure_ascii=False)

    display_name = f"{filename}.{format}"
    mime = "image/svg+xml" if format == "svg" else "image/png"

    with tempfile.TemporaryDirectory() as tmpdir:
        mmd_path = Path(tmpdir) / "input.mmd"
        excalidraw_path = Path(tmpdir) / "converted.excalidraw"
        output_path = Path(tmpdir) / display_name

        mmd_path.write_text(mermaid, encoding="utf-8")

        # Step 1: Mermaid → Excalidraw JSON (uses Puppeteer + headless Chrome)
        chrome = _find_chrome_path()
        if not chrome:
            return json.dumps({
                "error": (
                    "No Chrome/Chromium found. Install chromium or google-chrome, "
                    "or set CHROME_PATH environment variable."
                )
            }, ensure_ascii=False)

        mermaid_cmd = ["node", str(convert_script),
                       str(mmd_path), str(excalidraw_path),
                       "--chrome", chrome]
        proc = await asyncio.create_subprocess_exec(
            *mermaid_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            out_msg = stdout.decode("utf-8", errors="replace").strip()
            combined = f"{err_msg}\n{out_msg}".strip()
            return json.dumps({"error": f"Mermaid conversion failed: {combined}"}, ensure_ascii=False)

        if not excalidraw_path.exists():
            return json.dumps({"error": "Mermaid conversion produced no output."}, ensure_ascii=False)

        # Step 2: Expand labels into text elements, normalize missing fields,
        #         then export to SVG/PNG
        scene = json.loads(excalidraw_path.read_text(encoding="utf-8"))
        scene["elements"] = _expand_labels(scene.get("elements", []))
        scene["elements"] = [
            _normalize_element(el, i) for i, el in enumerate(scene["elements"])
        ]
        err = await _export_scene(scene, output_path)
        if err:
            return json.dumps({"error": f"Export failed: {err}"}, ensure_ascii=False)

        data = output_path.read_bytes()

    return await _deliver(data, display_name, mime, tool_name="mermaid_to_excalidraw")
