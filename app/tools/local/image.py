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
    
@register({
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate or edit an image. Pass only `prompt` to generate from scratch. "
            "Pass `source_image_b64` (base64 PNG/JPEG from get_attachment) plus a `prompt` "
            "describing the changes to edit an existing image."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate, or the changes to apply when editing.",
                },
                "source_image_b64": {
                    "type": "string",
                    "description": "Base64-encoded source image for editing (PNG or JPEG). Omit for generation from scratch.",
                },
            },
            "required": ["prompt"],
        },
    },
})
async def generate_image_tool(prompt: str, source_image_b64: str | None = None) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"})

    model = settings.IMAGE_GENERATION_MODEL

    try:
        if source_image_b64:
            image_bytes = base64.b64decode(source_image_b64)
            image_file = ("image.png", image_bytes, "image/png")
            resp = await _client.images.edit(
                model=model,
                image=image_file,
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