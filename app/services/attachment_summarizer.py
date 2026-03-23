"""Async attachment summarization — eager per-attachment + fallback sweep."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.config import settings
from app.db.engine import async_session
from app.db.models import Attachment

logger = logging.getLogger(__name__)

# Semaphore limits concurrent vision/LLM calls
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.ATTACHMENT_VISION_CONCURRENCY)
    return _semaphore


_IMAGE_PROMPT = (
    "Describe this image concisely in 1-3 sentences. Focus on the key visual content, "
    "any text visible, and the overall purpose or context of the image."
)

_TEXT_PROMPT = (
    "Summarize the following text content concisely in 1-3 sentences. "
    "Focus on the key information, structure, and purpose of the document.\n\n"
    "Content:\n{content}"
)


async def _summarize_image(url: str | None, model: str, file_data: bytes | None = None) -> str:
    """Use vision model to describe an image by URL or stored bytes."""
    import base64
    from app.services.providers import get_llm_client

    if file_data:
        # Prefer stored bytes — no HTTP fetch needed
        b64 = base64.b64encode(file_data).decode()
        image_url = f"data:image/png;base64,{b64}"
    elif url:
        image_url = url
    else:
        return ""

    response = await get_llm_client().chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _IMAGE_PROMPT},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
        max_tokens=300,
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()


async def _summarize_text_content(content: str, model: str) -> str:
    """Use LLM to summarize text file content."""
    from app.services.providers import get_llm_client

    truncated = content[:settings.ATTACHMENT_TEXT_MAX_CHARS]
    response = await get_llm_client().chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": _TEXT_PROMPT.format(content=truncated),
        }],
        max_tokens=300,
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()


def _get_bot_semaphore(concurrency: int) -> asyncio.Semaphore:
    """Return a semaphore for the given concurrency level (cached per value)."""
    if concurrency == settings.ATTACHMENT_VISION_CONCURRENCY:
        return _get_semaphore()
    # For bot-specific concurrency, create a new semaphore (not cached — acceptable for rare case)
    return asyncio.Semaphore(concurrency)


async def summarize_attachment(
    attachment_id: uuid.UUID,
    bot_overrides: dict | None = None,
) -> None:
    """Summarize a single attachment (image via vision, text via LLM)."""
    overrides = bot_overrides or {}
    concurrency = overrides.get("vision_concurrency", settings.ATTACHMENT_VISION_CONCURRENCY)
    sem = _get_bot_semaphore(concurrency)
    async with sem:
        try:
            async with async_session() as db:
                att = await db.get(Attachment, attachment_id)
                if att is None or att.described_at is not None:
                    return

            model = overrides.get("model", settings.ATTACHMENT_SUMMARY_MODEL)
            text_max_chars = overrides.get("text_max_chars", settings.ATTACHMENT_TEXT_MAX_CHARS)
            description: str | None = None

            if att.type == "image":
                description = await _summarize_image(att.url, model, file_data=att.file_data)
            elif att.type in ("text", "file"):
                try:
                    if att.file_data:
                        text_content = att.file_data.decode("utf-8", errors="replace")[:text_max_chars]
                    elif att.url:
                        import httpx
                        async with httpx.AsyncClient(timeout=30) as client:
                            resp = await client.get(att.url)
                            resp.raise_for_status()
                            text_content = resp.text[:text_max_chars]
                    else:
                        return
                    description = await _summarize_text_content(text_content, model)
                except Exception:
                    logger.warning(
                        "Could not fetch text content for attachment %s (%s)",
                        attachment_id, att.url,
                    )
                    return
            else:
                # audio/video deferred to Phase 2
                return

            if description:
                async with async_session() as db:
                    await db.execute(
                        update(Attachment)
                        .where(Attachment.id == attachment_id)
                        .values(
                            description=description,
                            description_model=model,
                            described_at=datetime.now(timezone.utc),
                        )
                    )
                    await db.commit()
                logger.info(
                    "Summarized attachment %s (%s): %s",
                    attachment_id, att.type, description[:80],
                )
        except Exception:
            logger.exception("Failed to summarize attachment %s", attachment_id)


async def attachment_sweep_worker() -> None:
    """Background sweep: poll for unsummarized attachments and summarize them."""
    logger.info("Attachment sweep worker started (interval=%ds)", settings.ATTACHMENT_SWEEP_INTERVAL_S)
    while True:
        try:
            await asyncio.sleep(settings.ATTACHMENT_SWEEP_INTERVAL_S)
            if not settings.ATTACHMENT_SUMMARY_ENABLED:
                continue

            async with async_session() as db:
                result = await db.execute(
                    select(Attachment.id)
                    .where(Attachment.described_at.is_(None))
                    .where(Attachment.type.in_(["image", "text", "file"]))
                    .order_by(Attachment.created_at)
                    .limit(10)
                )
                unsummarized_ids = result.scalars().all()

            if not unsummarized_ids:
                continue

            logger.info("Sweep: %d unsummarized attachments found", len(unsummarized_ids))
            tasks = [summarize_attachment(aid) for aid in unsummarized_ids]
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            logger.exception("Attachment sweep worker error")
