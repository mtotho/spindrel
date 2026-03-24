import base64
import json
import logging

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.tools.registry import register

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=120.0,
)

def _is_openai_model(model: str) -> bool:
    """True for OpenAI-native image models (gpt-image, dall-e)."""
    m = (model or "").lower()
    return any(t in m for t in ("gpt-image", "dall-e"))


def _is_gemini_model(model: str) -> bool:
    m = (model or "").lower()
    return "gemini" in m or "imagen" in m


def _generate_kwargs(model: str, n: int = 1) -> dict:
    """Build provider-optimal kwargs for images.generate()."""
    kw: dict = {}
    if _is_openai_model(model):
        kw["n"] = n
        kw["response_format"] = "b64_json"
    # Gemini: no extra params — n, response_format, style all rejected
    return kw


def _edit_kwargs(model: str, n: int = 1) -> dict:
    """Build provider-optimal kwargs for images.edit()."""
    kw: dict = {}
    if _is_openai_model(model):
        kw["n"] = n
    return kw



async def _resolve_attachment_images(attachment_ids: list[str]) -> tuple[list[bytes], str | None]:
    """Fetch image bytes from attachment IDs. Returns (list_of_bytes, error_or_None)."""
    import uuid as _uuid
    from app.services.attachments import get_attachment_by_id

    images: list[bytes] = []
    for aid in attachment_ids:
        try:
            att = await get_attachment_by_id(_uuid.UUID(aid))
        except ValueError:
            return [], f"Invalid attachment_id '{aid}' — must be a valid UUID."
        if att is None:
            return [], f"Attachment {aid} not found."
        if not att.file_data:
            return [], f"Attachment {aid} has no stored file data."
        images.append(att.file_data)
    return images, None


@register({
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate or edit an image. Pass only `prompt` to generate from scratch. "
            "To edit an existing image, pass one or more `attachment_ids` (from list_attachments) "
            "plus a prompt describing the changes. Image bytes are fetched directly "
            "from the database — do NOT use get_attachment first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate, or the changes to apply when editing.",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of images to generate (1-10). Only supported by OpenAI models (gpt-image, dall-e). Ignored for Gemini.",
                    "default": 1,
                },
                "attachment_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "UUIDs of attachments to use as source/reference images for editing. Get IDs from list_attachments.",
                },
                "source_image_b64": {
                    "type": "string",
                    "description": "DEPRECATED: use attachment_ids instead. Base64-encoded source image for editing.",
                },
            },
            "required": ["prompt"],
        },
    },
})
async def generate_image_tool(
    prompt: str,
    n: int = 1,
    attachment_ids: list[str] | None = None,
    source_image_b64: str | None = None,
) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"})

    # Resolve source images from attachment_ids (preferred) or legacy source_image_b64
    image_files: list[tuple] = []
    if attachment_ids:
        images, err = await _resolve_attachment_images(attachment_ids)
        if err:
            return json.dumps({"error": err})
        for i, img_bytes in enumerate(images):
            image_files.append((f"image_{i}.png", img_bytes, "image/png"))
    elif source_image_b64:
        image_files.append(("image.png", base64.b64decode(source_image_b64), "image/png"))

    n = max(1, min(n, 10))
    model = settings.IMAGE_GENERATION_MODEL

    try:
        if image_files:
            # Single image → pass directly; multiple → pass as list
            image_param = image_files[0] if len(image_files) == 1 else image_files
            resp = await _client.images.edit(
                model=model,
                image=image_param,
                prompt=prompt,
                **_edit_kwargs(model, n),
            )
        else:
            resp = await _client.images.generate(
                model=model,
                prompt=prompt,
                **_generate_kwargs(model, n),
            )
    except Exception as e:
        logger.exception("Image generation/edit failed")
        return json.dumps({"error": str(e)})

    if not resp.data:
        return json.dumps({"error": "No image returned"})

    # Collect all returned images and persist as attachments
    from app.agent.context import current_bot_id, current_channel_id, current_dispatch_type
    from app.services.attachments import create_attachment

    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    source = current_dispatch_type.get() or "web"

    results: list[dict] = []
    for idx, item in enumerate(resp.data):
        b64: str | None = getattr(item, "b64_json", None)
        if not b64 and getattr(item, "url", None):
            try:
                async with httpx.AsyncClient(timeout=60.0) as ac:
                    r = await ac.get(item.url)
                    r.raise_for_status()
                    b64 = base64.b64encode(r.content).decode("ascii")
            except Exception as e:
                logger.warning("Could not download image %d URL: %s", idx, e)
                continue
        if b64:
            img_bytes = base64.b64decode(b64)
            filename = f"generated_{idx}.png" if len(resp.data) > 1 else "generated.png"

            # Persist to attachments table so it's available for future edits/references
            try:
                await create_attachment(
                    message_id=None,
                    channel_id=channel_id,
                    filename=filename,
                    mime_type="image/png",
                    size_bytes=len(img_bytes),
                    posted_by=bot_id or "image-bot",
                    source_integration=source,
                    file_data=img_bytes,
                    attachment_type="image",
                    bot_id=bot_id,
                )
            except Exception:
                logger.warning("Failed to persist generated image %d as attachment", idx, exc_info=True)

            results.append({
                "type": "upload_image",
                "data": b64,
                "filename": filename,
                "caption": "",
            })

    if not results:
        return json.dumps({"error": "No images could be retrieved from response"})

    return json.dumps({
        "message": f"{len(results)} image(s) generated successfully.",
        "client_action": results[0] if len(results) == 1 else results,
    })