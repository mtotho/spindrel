"""generate_image — single canonical entrypoint for image generation and editing.

Routing is driven by **model family**, not strings:

* ``openai``               — call ``client.images.generate`` / ``client.images.edit``
* ``openai-subscription``  — same surface, but the underlying client is the
  ``OpenAIResponsesAdapter._Images`` namespace, which translates to the
  Codex Responses API + built-in ``image_generation`` tool.
* ``gemini``               — call ``client.chat.completions.create`` with
  multimodal output (``modalities=["text","image"]``) so reference images
  are passed natively as ``image_url`` content parts.

The capability flag ``ProviderModel.supports_image_generation`` is the
authoritative gate: unknown / unflagged models route via a defensive string
sniff with a WARNING log so admins can see what to flag.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Literal

import httpx

from app.config import settings
from app.tools.registry import register

logger = logging.getLogger(__name__)


ImageFamily = Literal["openai", "openai-subscription", "gemini"]


_GEMINI_PATTERNS = ("gemini", "imagen", "flash-image", "pro-image")
_OPENAI_PATTERNS = ("gpt-image", "dall-e")


def _image_family(model: str, provider_id: str | None) -> ImageFamily:
    """Resolve which API call shape ``model`` requires.

    Order:
      1. If the resolved provider's ``provider_type`` is ``openai-subscription``,
         the call MUST go through the Responses API adapter.
      2. Otherwise look at the model name itself — model name determines the
         wire format regardless of which provider proxies it (LiteLLM, direct,
         OpenAI-compatible, etc.).
      3. Fallback: log WARNING + return ``"openai"`` so we never crash on an
         unknown model that happens to be flagged.
    """
    from app.services.providers import get_provider, supports_image_generation

    if provider_id:
        provider = get_provider(provider_id)
        if provider and provider.provider_type == "openai-subscription":
            return "openai-subscription"

    m = (model or "").lower()
    if any(p in m for p in _GEMINI_PATTERNS):
        return "gemini"
    if any(p in m for p in _OPENAI_PATTERNS):
        return "openai"

    if not supports_image_generation(model):
        logger.warning(
            "generate_image: model %r has no recognized family and is not "
            "flagged supports_image_generation=true — defaulting to 'openai' "
            "routing. Flag the model in admin UI or rename to a known prefix.",
            model,
        )
    return "openai"


def _generate_kwargs(family: ImageFamily, model: str, n: int, size: str | None, seed: int | None) -> dict:
    """Provider-optimal kwargs for ``client.images.generate``."""
    if family == "openai-subscription":
        kw: dict = {"n": max(1, n)}
        if size:
            kw["size"] = size
        return kw
    if family == "openai":
        m = (model or "").lower()
        if "gpt-image" in m:
            kw = {"n": max(1, n)}
            if size:
                kw["size"] = size
            return kw
        # dall-e family
        kw = {
            "n": 1 if "dall-e-3" in m else max(1, n),
            "response_format": "b64_json",
        }
        if size:
            kw["size"] = size
        return kw
    # Gemini goes through chat.completions; no kwargs apply here.
    return {}


def _edit_kwargs(family: ImageFamily, model: str, n: int, size: str | None) -> dict:
    """Provider-optimal kwargs for ``client.images.edit``."""
    if family == "openai-subscription":
        kw: dict = {"n": max(1, n)}
        if size:
            kw["size"] = size
        return kw
    if family == "openai":
        m = (model or "").lower()
        kw: dict = {"n": 1 if "dall-e-3" in m else max(1, n)}
        if size:
            kw["size"] = size
        return kw
    return {}


def _aspect_to_size(aspect_ratio: str | None) -> str | None:
    """Map a Gemini-style ``aspect_ratio`` to an OpenAI-style ``size``.

    Used so callers can pass one provider-agnostic param and the right one
    reaches each family.  Conservative mapping — falls back to ``None`` for
    ratios OpenAI doesn't natively accept (caller can still pass ``size``).
    """
    if not aspect_ratio:
        return None
    table = {
        "1:1": "1024x1024",
        "3:2": "1536x1024",
        "2:3": "1024x1536",
        "16:9": "1792x1024",
        "9:16": "1024x1792",
    }
    return table.get(aspect_ratio.strip())


def _resolve_image_client(provider_id: str | None = None):
    """Get an AsyncOpenAI-compatible client for image generation.

    Resolution order:
      1. Explicit ``provider_id`` parameter (from tool call)
      2. ``IMAGE_GENERATION_PROVIDER_ID`` config setting
      3. Current bot's ``model_provider_id`` (from context)
      4. ``.env`` fallback (``LLM_BASE_URL`` / ``LLM_API_KEY``)
    """
    from app.services.providers import get_llm_client

    effective_pid = provider_id or settings.IMAGE_GENERATION_PROVIDER_ID or None

    if not effective_pid:
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


def _resolve_effective_provider_id(provider_id: str | None) -> str | None:
    """Same cascade as ``_resolve_image_client`` but returns the provider_id.

    Lets ``_image_family`` consult ``provider_type`` even when the caller
    omitted ``provider_id``.
    """
    if provider_id:
        return provider_id
    if settings.IMAGE_GENERATION_PROVIDER_ID:
        return settings.IMAGE_GENERATION_PROVIDER_ID
    try:
        from app.agent.bots import get_bot
        from app.agent.context import current_bot_id
        bot_id = current_bot_id.get()
        if bot_id:
            bot = get_bot(bot_id)
            if bot and bot.model_provider_id:
                return bot.model_provider_id
    except Exception:
        pass
    return None


async def _resolve_attachments(attachment_ids: list[str]) -> tuple[list, str | None]:
    """Fetch attachment objects from IDs. Returns ``(list_of_Attachment, error_or_None)``."""
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


def _extract_b64_from_completion_message(message) -> list[str]:
    """Pull base64-encoded images out of a chat.completions message.

    Different LiteLLM versions surface multimodal output differently.  We
    handle the two shapes seen in the wild:

      * ``message.images`` — a list of dicts with ``image_url.url`` values
        that may be ``data:image/png;base64,...`` URIs or remote URLs.
      * ``message.content`` — a string OR a list of content parts where
        each part can be ``{"type": "image_url", "image_url": {...}}``.

    Remote URLs are NOT downloaded here; the caller should pass them
    through the SSRF guard (``assert_public_url``) and fetch separately.
    """
    out: list[str] = []

    images = getattr(message, "images", None) or []
    for item in images:
        url = None
        if isinstance(item, dict):
            url = (item.get("image_url") or {}).get("url") or item.get("url")
        else:
            url = getattr(getattr(item, "image_url", None), "url", None) or getattr(item, "url", None)
        if isinstance(url, str) and url.startswith("data:"):
            try:
                out.append(url.split(",", 1)[1])
            except IndexError:
                continue

    content = getattr(message, "content", None)
    if isinstance(content, list):
        for part in content:
            ptype = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
            if ptype != "image_url":
                continue
            iu = part.get("image_url") if isinstance(part, dict) else getattr(part, "image_url", None)
            url = iu.get("url") if isinstance(iu, dict) else getattr(iu, "url", None)
            if isinstance(url, str) and url.startswith("data:"):
                try:
                    out.append(url.split(",", 1)[1])
                except IndexError:
                    continue

    return out


async def _gemini_generate_or_edit(
    client,
    model: str,
    prompt: str,
    image_files: list[tuple],
) -> list[str]:
    """Run Gemini multimodal generate/edit via ``chat.completions.create``.

    Reference images are passed as ``image_url`` content parts on the user
    message; the response carries inline base64 image data (PNG).  Returns
    a list of raw base64 strings (one per generated image).
    """
    if len(image_files) > 3:
        raise ValueError("Gemini accepts at most 3 reference images per call.")

    user_parts: list[dict] = [{"type": "text", "text": prompt}]
    for _name, data, mime in image_files:
        b64 = base64.b64encode(data).decode("ascii")
        user_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": user_parts}],
        modalities=["text", "image"],
    )

    if not resp.choices:
        return []
    return _extract_b64_from_completion_message(resp.choices[0].message)


@register({
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate or edit an image. Pass ``prompt`` alone to generate from "
            "scratch, or pass ``attachment_ids`` (UUIDs from list_attachments) "
            "with a prompt describing the changes to edit/combine existing "
            "images. Image bytes are read from the attachment store directly — "
            "do not call get_attachment first. Generated images are persisted "
            "as channel attachments and delivered to every connected client "
            "(web, Slack, Discord) automatically."
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
                        "Override the server-default image model "
                        "(e.g. ``gpt-image-1``, ``dall-e-3``, "
                        "``gemini/gemini-2.5-flash-image``). Omit to use the "
                        "server default."
                    ),
                },
                "provider_id": {
                    "type": "string",
                    "description": (
                        "Route the request to a specific provider. Required "
                        "only when two providers serve models with the same "
                        "name. Omit to use the default provider."
                    ),
                },
                "n": {
                    "type": "integer",
                    "description": "Number of images to generate (1-10). Honored where the provider supports batch.",
                    "default": 1,
                },
                "size": {
                    "type": "string",
                    "description": "Output size, e.g. ``1024x1024``, ``1792x1024``. OpenAI-style.",
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "Aspect ratio, e.g. ``1:1``, ``16:9``. Mapped to ``size`` for OpenAI providers when ``size`` is omitted.",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducible output where the provider supports it.",
                },
                "attachment_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "UUIDs of attachments to use as source/reference images for editing or combining. Get IDs from list_attachments.",
                },
            },
            "required": ["prompt"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "prompt": {"type": "string"},
        "model": {"type": "string"},
        "images": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "attachment_id": {"type": "string"},
                    "filename": {"type": "string"},
                },
            },
        },
        "error": {"type": "string"},
    },
})
async def generate_image_tool(
    prompt: str,
    model: str | None = None,
    provider_id: str | None = None,
    n: int = 1,
    size: str | None = None,
    aspect_ratio: str | None = None,
    seed: int | None = None,
    attachment_ids: list[str] | None = None,
) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"}, ensure_ascii=False)

    image_files: list[tuple] = []
    if attachment_ids:
        attachments, err = await _resolve_attachments(attachment_ids)
        if err:
            return json.dumps({"error": err}, ensure_ascii=False)
        for i, att in enumerate(attachments):
            mime = att.mime_type or "image/png"
            image_files.append((f"image_{i}.png", att.file_data, mime))

    n = max(1, min(int(n or 1), 10))
    effective_model = model or settings.IMAGE_GENERATION_MODEL
    effective_provider_id = _resolve_effective_provider_id(provider_id)
    family = _image_family(effective_model, effective_provider_id)
    client = _resolve_image_client(provider_id)

    # If caller passed only aspect_ratio, derive a size for OpenAI-shaped calls.
    effective_size = size or (_aspect_to_size(aspect_ratio) if family != "gemini" else None)

    try:
        if family == "gemini":
            extra: dict = {}
            if seed is not None:
                extra["seed"] = seed
            b64_list = await _gemini_generate_or_edit(
                client, effective_model, prompt, image_files,
            )
            data_items = [type("Img", (), {"b64_json": b, "url": None})() for b in b64_list]
            resp = type("Resp", (), {"data": data_items})()
        elif image_files:
            kw = _edit_kwargs(family, effective_model, n, effective_size)
            if seed is not None and family == "openai":
                # OpenAI Images API accepts ``user`` but not ``seed`` — drop silently.
                pass
            image_param = image_files[0] if len(image_files) == 1 else image_files
            resp = await client.images.edit(
                model=effective_model,
                image=image_param,
                prompt=prompt,
                **kw,
            )
        else:
            kw = _generate_kwargs(family, effective_model, n, effective_size, seed)
            resp = await client.images.generate(
                model=effective_model,
                prompt=prompt,
                **kw,
            )
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.exception("Image generation/edit failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    data_items = getattr(resp, "data", None) or []
    if not data_items:
        return json.dumps({"error": "No image returned"}, ensure_ascii=False)

    from app.agent.context import current_bot_id, current_channel_id, current_dispatch_type
    from app.services.attachments import create_widget_backed_attachment

    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    source = current_dispatch_type.get() or "web"

    results: list[dict] = []
    images: list[dict] = []
    for idx, item in enumerate(data_items):
        b64: str | None = getattr(item, "b64_json", None) or getattr(item, "b64", None)
        if not b64 and getattr(item, "url", None):
            from app.services.url_safety import UnsafePublicURLError, assert_public_url

            try:
                await assert_public_url(item.url)
            except UnsafePublicURLError as e:
                logger.warning("Refusing unsafe image URL %d (%s): %s", idx, item.url, e)
                continue
            try:
                async with httpx.AsyncClient(timeout=60.0) as ac:
                    r = await ac.get(item.url)
                    r.raise_for_status()
                    b64 = base64.b64encode(r.content).decode("ascii")
            except Exception as e:
                logger.warning("Could not download image %d URL: %s", idx, e)
                continue
        if not b64:
            continue

        img_bytes = base64.b64decode(b64)
        filename = f"generated_{idx}.png" if len(data_items) > 1 else "generated.png"

        gen_att_id = None
        try:
            gen_att = await create_widget_backed_attachment(
                tool_name="generate_image",
                channel_id=channel_id,
                filename=filename,
                mime_type="image/png",
                size_bytes=len(img_bytes),
                posted_by=bot_id or "system",
                source_integration=source,
                file_data=img_bytes,
                attachment_type="image",
                bot_id=bot_id,
            )
            gen_att_id = str(gen_att.id)
        except Exception:
            logger.warning("Failed to persist generated image %d as attachment", idx, exc_info=True)

        action_dict: dict = {
            "type": "upload_image",
            "data": b64,
            "filename": filename,
            "caption": "",
        }
        if gen_att_id:
            action_dict["attachment_id"] = gen_att_id
            images.append({"attachment_id": gen_att_id, "filename": filename})
        results.append(action_dict)

    if not results:
        return json.dumps({"error": "No images could be retrieved from response"}, ensure_ascii=False)

    return json.dumps({
        "message": f"{len(results)} image(s) generated successfully.",
        "prompt": prompt,
        "model": effective_model,
        "images": images,
        "client_action": results[0] if len(results) == 1 else results,
    }, ensure_ascii=False)
