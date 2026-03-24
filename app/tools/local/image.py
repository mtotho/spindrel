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

# Only OpenAI image endpoints honor response_format=b64_json; others (e.g. Gemini via LiteLLM) return URLs.
_SUPPORTS_RESPONSE_FORMAT = frozenset({"gpt-image-1", "dall-e-3", "dall-e-2"})


def _image_model_requests_b64_json(model: str) -> bool:
    m = model or ""
    return any(token in m for token in _SUPPORTS_RESPONSE_FORMAT)
    
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

    model = settings.IMAGE_GENERATION_MODEL

    try:
        if image_files:
            # Single image → pass directly; multiple → pass as list
            image_param = image_files[0] if len(image_files) == 1 else image_files
            resp = await _client.images.edit(
                model=model,
                image=image_param,
                prompt=prompt,
                n=1,
            )
        else:
            extra = (
                {"response_format": "b64_json"}
                if _image_model_requests_b64_json(model)
                else {}
            )
            resp = await _client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                **extra,
            )
    except Exception as e:
        logger.exception("Image generation/edit failed")
        return json.dumps({"error": str(e)})

    if not resp.data:
        return json.dumps({"error": "No image returned"})

    item = resp.data[0]
    b64: str | None = getattr(item, "b64_json", None)
    if not b64 and getattr(item, "url", None):
        try:
            async with httpx.AsyncClient(timeout=60.0) as ac:
                r = await ac.get(item.url)
                r.raise_for_status()
                b64 = base64.b64encode(r.content).decode("ascii")
        except Exception as e:
            return json.dumps({"error": f"Could not download image URL: {e}"})

    if not b64:
        return json.dumps({"error": "Image response had no b64_json or url"})

    return json.dumps({
        "message": "Image generated successfully.",
        "client_action": {
            "type": "upload_image",
            "data": b64,
            "filename": "generated.png",
            "caption": "",
        },
    })