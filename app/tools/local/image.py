import base64
import json
import logging

import httpx

from app.config import settings
from app.tools.registry import register

logger = logging.getLogger(__name__)


def _is_openai_model(model: str) -> bool:
    """True for OpenAI-native image models (gpt-image, dall-e)."""
    m = (model or "").lower()
    return any(t in m for t in ("gpt-image", "dall-e"))


def _is_gpt_image_model(model: str) -> bool:
    """True for GPT Image family (gpt-image-1, gpt-image-1.5, etc.)."""
    return "gpt-image" in (model or "").lower()


def _is_dalle_model(model: str) -> bool:
    """True for DALL-E family (dall-e-2, dall-e-3)."""
    return "dall-e" in (model or "").lower()


def _is_gemini_model(model: str) -> bool:
    m = (model or "").lower()
    return "gemini" in m or "imagen" in m


def _supports_edit(model: str) -> bool:
    """Whether the model supports the images.edit() endpoint.

    OpenAI models support it; Gemini does not (image editing goes through
    chat completions, which isn't wired here).
    """
    return _is_openai_model(model)


def _generate_kwargs(model: str, n: int = 1) -> dict:
    """Build provider-optimal kwargs for images.generate()."""
    kw: dict = {}
    if _is_gpt_image_model(model):
        # GPT Image family: supports n>1, uses output_format not response_format
        kw["n"] = n
    elif _is_dalle_model(model):
        # dall-e-3 only supports n=1; dall-e-2 supports n but is legacy
        kw["n"] = 1 if "dall-e-3" in model.lower() else n
        kw["response_format"] = "b64_json"
    # Gemini / unknown: no extra params — n, response_format, style all rejected
    return kw


def _edit_kwargs(model: str, n: int = 1) -> dict:
    """Build provider-optimal kwargs for images.edit()."""
    kw: dict = {}
    if _is_gpt_image_model(model):
        kw["n"] = n
    elif _is_dalle_model(model):
        kw["n"] = 1 if "dall-e-3" in model.lower() else n
    return kw


def _resolve_image_client(provider_id: str | None = None):
    """Get an AsyncOpenAI-compatible client for image generation.

    Resolution order:
    1. Explicit provider_id parameter (from tool call)
    2. IMAGE_GENERATION_PROVIDER_ID config setting
    3. Current bot's model_provider_id (from context)
    4. .env fallback (LLM_BASE_URL / LLM_API_KEY)
    """
    from app.services.providers import get_llm_client

    effective_pid = provider_id or settings.IMAGE_GENERATION_PROVIDER_ID or None

    if not effective_pid:
        # Try to inherit from the current bot's provider
        try:
            from app.agent.bots import get_bot
            from app.agent.context import current_bot_id
            bot_id = current_bot_id.get()
            if bot_id:
                bot = get_bot(bot_id)
                if bot and bot.model_provider_id:
                    effective_pid = bot.model_provider_id
        except Exception:
            pass

    return get_llm_client(effective_pid)


async def _resolve_attachments(attachment_ids: list[str]) -> tuple[list, str | None]:
    """Fetch attachment objects from IDs. Returns (list_of_Attachment, error_or_None)."""
    import uuid as _uuid
    from app.services.attachments import get_attachment_by_id

    attachments = []
    for aid in attachment_ids:
        try:
            att = await get_attachment_by_id(_uuid.UUID(aid))
        except ValueError:
            return [], f"Invalid attachment_id '{aid}' — must be a valid UUID."
        if att is None:
            return [], f"Attachment {aid} not found."
        if not att.file_data:
            return [], f"Attachment {aid} has no stored file data."
        attachments.append(att)
    return attachments, None


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
                "model": {
                    "type": "string",
                    "description": (
                        "Image model to use (e.g. 'gpt-image-1', 'dall-e-3', 'gemini/gemini-2.5-flash-image'). "
                        "Omit to use the server default."
                    ),
                },
                "provider_id": {
                    "type": "string",
                    "description": (
                        "Provider to route the request to (e.g. 'openai-prod', 'gemini'). "
                        "Required when two providers serve models with the same name. "
                        "Omit to use the default provider."
                    ),
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
}, safety_tier="mutating")
async def generate_image_tool(
    prompt: str,
    model: str | None = None,
    provider_id: str | None = None,
    n: int = 1,
    attachment_ids: list[str] | None = None,
    source_image_b64: str | None = None,
) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"})

    # Resolve source images from attachment_ids (preferred) or legacy source_image_b64
    image_files: list[tuple] = []
    attachment_descriptions: list[str] = []
    if attachment_ids:
        attachments, err = await _resolve_attachments(attachment_ids)
        if err:
            return json.dumps({"error": err})
        for i, att in enumerate(attachments):
            image_files.append((f"image_{i}.png", att.file_data, "image/png"))
            if att.description:
                attachment_descriptions.append(att.description)
    elif source_image_b64:
        image_files.append(("image.png", base64.b64decode(source_image_b64), "image/png"))

    n = max(1, min(n, 10))
    effective_model = model or settings.IMAGE_GENERATION_MODEL
    client = _resolve_image_client(provider_id)

    gemini_fallback = False
    try:
        if image_files:
            if not _supports_edit(effective_model):
                # Gemini doesn't support images.edit() — fall back to generation
                # with attachment descriptions baked into the prompt.
                if attachment_descriptions:
                    desc_block = "\n".join(
                        f"- Reference image {i+1}: {d}"
                        for i, d in enumerate(attachment_descriptions)
                    )
                    prompt = (
                        f"Based on these reference images:\n{desc_block}\n\n"
                        f"Generate: {prompt}"
                    )
                gemini_fallback = True
                logger.info(
                    "Model %s doesn't support edit — falling back to generate "
                    "(descriptions=%d, prompt=%s)",
                    effective_model, len(attachment_descriptions), prompt[:120],
                )
                resp = await client.images.generate(
                    model=effective_model,
                    prompt=prompt,
                    **_generate_kwargs(effective_model, n),
                )
            else:
                # Single image → pass directly; multiple → pass as list
                image_param = image_files[0] if len(image_files) == 1 else image_files
                resp = await client.images.edit(
                    model=effective_model,
                    image=image_param,
                    prompt=prompt,
                    **_edit_kwargs(effective_model, n),
                )
        else:
            resp = await client.images.generate(
                model=effective_model,
                prompt=prompt,
                **_generate_kwargs(effective_model, n),
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
        # GPT Image family returns base64 directly in .b64_json or .b64
        # DALL-E returns .b64_json or .url
        # Gemini via LiteLLM returns .b64_json
        b64: str | None = getattr(item, "b64_json", None) or getattr(item, "b64", None)
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

    msg = f"{len(results)} image(s) generated successfully."
    if gemini_fallback:
        msg += (
            " Note: this model doesn't support direct image editing, so a new image "
            "was generated using descriptions of the reference images. The result may "
            "not exactly match the originals."
        )
    return json.dumps({
        "message": msg,
        "client_action": results[0] if len(results) == 1 else results,
    })
