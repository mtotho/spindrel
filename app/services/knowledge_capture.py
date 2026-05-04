"""Review-first user knowledge capture pipeline primitives."""
from __future__ import annotations

import logging
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import KnowledgeCapturedPayload
from app.services.knowledge_documents import create_document, default_session_binding, user_knowledge_surface
from app.services.shared_workspace import shared_workspace_service

logger = logging.getLogger(__name__)

AUTONOMOUS_ORIGINS = {"heartbeat", "task", "cron", "pipeline", "standing_order", "subagent", "hygiene", "skill_review"}
MIN_NOVEL_ASSISTANT_CHARS = 80


@dataclass(frozen=True)
class KnowledgeCandidate:
    title: str
    body: str
    type: str = "note"
    extra: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    source_message_id: str | None = None


@dataclass(frozen=True)
class CaptureDecision:
    should_run: bool
    reason: str = "eligible"


def should_run_knowledge_capture(
    *,
    bot: Any,
    channel: Any | None,
    message_metadata: dict[str, Any] | None,
    run_origin: str | None,
    assistant_content: str | None,
) -> CaptureDecision:
    """Return whether Phase 1 capture may run for this turn."""
    if not _bot_capture_enabled(bot):
        return CaptureDecision(False, "bot_capture_disabled")
    if not getattr(bot, "user_id", None):
        return CaptureDecision(False, "ownerless_bot")
    channel_config = getattr(channel, "config", None) or {}
    if channel_config.get("knowledge_capture") == "off":
        return CaptureDecision(False, "channel_capture_disabled")
    metadata = message_metadata or {}
    if metadata.get("context_visibility") == "background":
        return CaptureDecision(False, "background_context")
    if str(metadata.get("sender_type") or "").lower() in {"bot", "pipeline", "project_run_launcher", "project_review_launcher"}:
        return CaptureDecision(False, "non_human_origin")
    if run_origin in AUTONOMOUS_ORIGINS:
        return CaptureDecision(False, "autonomous_origin")
    if metadata.get("delegation_task_id") or metadata.get("delegation_child_bot_id"):
        return CaptureDecision(False, "delegation_turn")
    if _looks_like_tool_ack(assistant_content or ""):
        return CaptureDecision(False, "tool_ack")
    return CaptureDecision(True)


def _bot_capture_enabled(bot: Any) -> bool:
    if bool(getattr(bot, "knowledge_capture_enabled", False)):
        return True
    config = getattr(bot, "integration_config", None) or {}
    if isinstance(config, dict) and config.get("knowledge_capture_enabled") is True:
        return True
    raw = getattr(bot, "_workspace_raw", None) or {}
    if isinstance(raw, dict) and raw.get("knowledge_capture_enabled") is True:
        return True
    return False


def _looks_like_tool_ack(content: str) -> bool:
    text = " ".join(content.split())
    if len(text) >= MIN_NOVEL_ASSISTANT_CHARS:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in (
        "done",
        "updated",
        "saved",
        "created",
        "deleted",
        "i'll take care of it",
        "completed",
    ))


async def extract_knowledge_candidates(*args: Any, **kwargs: Any) -> list[KnowledgeCandidate]:
    """Extract review-first Knowledge Document candidates from a persisted turn."""
    bot = kwargs.get("bot")
    channel = kwargs.get("channel")
    user_message = kwargs.get("user_message")
    assistant_message = kwargs.get("assistant_message")
    if bot is None or channel is None or user_message is None or assistant_message is None:
        return []
    user_text = str(getattr(user_message, "content", "") or "").strip()
    assistant_text = str(getattr(assistant_message, "content", "") or "").strip()
    if not user_text or not assistant_text:
        return []

    try:
        from app.services.providers import get_llm_client, resolve_effective_provider

        model = _capture_model(bot, channel)
        if not model:
            return []
        provider_id = _capture_model_provider_id(bot, channel, resolve_effective_provider)
        client = get_llm_client(provider_id)
        response = await client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=1800,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract durable user knowledge candidates from one assistant turn. "
                        "Return only JSON: {\"candidates\":[{\"type\":\"note\",\"title\":\"...\","
                        "\"body\":\"markdown\",\"extra\":{},\"confidence\":0.0}]}. "
                        "Return an empty candidates array for transient task progress, tool acknowledgements, "
                        "generic advice, facts not about the user or their durable context, or uncertain guesses. "
                        "Use free-form type strings; default to note. Body must be concise Markdown. "
                        "Do not invent facts."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_message": user_text[:6000],
                            "assistant_message": assistant_text[:8000],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        raw = response.choices[0].message.content or ""
        parsed = _parse_json_object(raw)
        raw_candidates = parsed.get("candidates") if isinstance(parsed, dict) else None
        if not isinstance(raw_candidates, list):
            return []
        candidates: list[KnowledgeCandidate] = []
        for item in raw_candidates[:3]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            body = str(item.get("body") or "").strip()
            if not title or not body:
                continue
            try:
                confidence = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            candidates.append(KnowledgeCandidate(
                type=str(item.get("type") or "note").strip() or "note",
                title=title[:160],
                body=body + ("\n" if not body.endswith("\n") else ""),
                extra=extra,
                confidence=max(0.0, min(1.0, confidence)),
                source_message_id=str(getattr(assistant_message, "id", "")),
            ))
        return candidates
    except Exception:
        logger.warning("knowledge capture extractor failed", exc_info=True)
        return []


async def write_pending_user_knowledge_candidates(
    *,
    bot: Any,
    session_id: str,
    candidates: list[KnowledgeCandidate],
    source_message_id: str,
) -> list[dict[str, Any]]:
    """Persist candidates as pending-review user-scope Knowledge Documents."""
    user_id = str(getattr(bot, "user_id", "") or "")
    workspace_id = getattr(bot, "shared_workspace_id", None)
    if not user_id or not workspace_id or not candidates:
        return []
    workspace_root = shared_workspace_service.ensure_host_dirs(str(workspace_id))
    surface = user_knowledge_surface(workspace_root=workspace_root, user_id=user_id)
    written: list[dict[str, Any]] = []
    for candidate in candidates:
        frontmatter = {
            "type": candidate.type or "note",
            "status": "pending_review",
            "user_id": user_id,
            "captured_by_bot_ids": [str(getattr(bot, "id", ""))],
            "source_message_id": candidate.source_message_id or source_message_id,
            "confidence": candidate.confidence,
            "extra": candidate.extra or {},
        }
        doc = create_document(
            surface,
            title=candidate.title.strip() or "Untitled knowledge",
            content=candidate.body,
            frontmatter=frontmatter,
            session_binding=default_session_binding("inline", session_id),
        )
        written.append(doc)
    return written


async def reindex_user_knowledge_documents(*, bot: Any, user_id: str) -> dict | None:
    """Index user-scope Knowledge Documents as cross-bot chunks."""
    workspace_id = getattr(bot, "shared_workspace_id", None)
    if not workspace_id:
        return None
    indexing = getattr(getattr(bot, "workspace", None), "indexing", None)
    return await reindex_user_knowledge_workspace(
        workspace_id=str(workspace_id),
        user_id=user_id,
        embedding_model=getattr(indexing, "embedding_model", None),
    )


async def reindex_user_knowledge_workspace(
    *,
    workspace_id: str,
    user_id: str,
    embedding_model: str | None = None,
) -> dict:
    """Index one user's Knowledge Documents inside a shared workspace."""
    from app.agent.fs_indexer import index_directory

    workspace_root = shared_workspace_service.ensure_host_dirs(workspace_id)
    prefix = f"users/{user_id}/knowledge-base/notes"
    return await index_directory(
        workspace_root,
        None,
        [f"{prefix}/**/*.md"],
        force=True,
        embedding_model=embedding_model,
        skip_stale_cleanup=True,
    )


async def delete_user_knowledge_index_entry(*, workspace_id: str, user_id: str, slug: str) -> int:
    """Remove indexed chunks for a deleted user Knowledge Document."""
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import FilesystemChunk

    workspace_root = shared_workspace_service.ensure_host_dirs(workspace_id)
    rel = f"users/{user_id}/knowledge-base/notes/{slug.removesuffix('.md')}.md"
    async with async_session() as cleanup_db:
        result = await cleanup_db.execute(
            delete(FilesystemChunk).where(
                FilesystemChunk.root == workspace_root,
                FilesystemChunk.bot_id.is_(None),
                FilesystemChunk.client_id.is_(None),
                FilesystemChunk.file_path == rel,
            )
        )
        await cleanup_db.commit()
        return int(result.rowcount or 0)


async def run_knowledge_capture_for_persisted_turn(
    db: AsyncSession,
    *,
    bot: Any,
    session_id: Any,
    channel_id: Any | None,
    first_user_message_id: Any | None,
    last_assistant_message_id: Any | None,
    run_origin: str | None,
    is_heartbeat: bool = False,
    hide_messages: bool = False,
) -> list[dict[str, Any]]:
    """Run capture after a turn has been durably persisted."""
    if channel_id is None or first_user_message_id is None or last_assistant_message_id is None:
        return []
    channel = await db.get(Channel, channel_id)
    user_message = await db.get(Message, first_user_message_id)
    assistant_message = await db.get(Message, last_assistant_message_id)
    if channel is None or user_message is None or assistant_message is None:
        return []
    metadata = dict(user_message.metadata_ or {})
    if is_heartbeat:
        metadata["context_visibility"] = "background"
    decision = should_run_knowledge_capture(
        bot=bot,
        channel=channel,
        message_metadata=metadata,
        run_origin=run_origin,
        assistant_content=str(assistant_message.content or ""),
    )
    if hide_messages and decision.should_run:
        decision = CaptureDecision(False, "hidden_turn")
    if not decision.should_run:
        logger.debug("knowledge capture skipped: %s", decision.reason)
        return []

    candidates = await extract_knowledge_candidates(
        bot=bot,
        channel=channel,
        user_message=user_message,
        assistant_message=assistant_message,
    )
    if not candidates:
        return []
    source_message_id = str(assistant_message.id)
    docs = await write_pending_user_knowledge_candidates(
        bot=bot,
        session_id=str(session_id),
        source_message_id=source_message_id,
        candidates=candidates,
    )
    if not docs:
        return []
    try:
        await reindex_user_knowledge_documents(bot=bot, user_id=str(bot.user_id))
    except Exception:
        logger.warning("knowledge capture wrote docs but user-scope reindex failed", exc_info=True)
    _publish_knowledge_captured_events(channel_id=channel_id, user_id=str(bot.user_id), source_message_id=source_message_id, docs=docs)
    return docs


def _publish_knowledge_captured_events(*, channel_id: Any, user_id: str, source_message_id: str, docs: list[dict[str, Any]]) -> None:
    from app.services.outbox_publish import publish_to_bus

    for doc in docs:
        frontmatter = doc.get("frontmatter") or {}
        payload = KnowledgeCapturedPayload(
            entry_id=str(doc.get("entry_id") or frontmatter.get("entry_id") or ""),
            type=str(doc.get("type") or frontmatter.get("type") or "note"),
            title=str(doc.get("title") or frontmatter.get("title") or "Untitled knowledge"),
            user_id=user_id,
            source_message_id=source_message_id,
            confidence=float(frontmatter.get("confidence") or doc.get("confidence") or 0.0),
        )
        publish_to_bus(channel_id, ChannelEvent(channel_id=channel_id, kind=ChannelEventKind.KNOWLEDGE_CAPTURED, payload=payload))


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            return {}
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _capture_model(bot: Any, channel: Any | None) -> str | None:
    """Resolve the model used for extraction, falling back to the chat model."""
    direct = getattr(bot, "knowledge_capture_model", None)
    if direct:
        return str(direct)
    config = getattr(bot, "integration_config", None) or {}
    if isinstance(config, dict) and config.get("knowledge_capture_model"):
        return str(config["knowledge_capture_model"])
    raw = getattr(bot, "_workspace_raw", None) or {}
    if isinstance(raw, dict) and raw.get("knowledge_capture_model"):
        return str(raw["knowledge_capture_model"])
    return str(getattr(channel, "model_override", None) or getattr(bot, "model", None) or "") or None


def _capture_model_provider_id(bot: Any, channel: Any | None, resolve_effective_provider: Any) -> str | None:
    direct = getattr(bot, "knowledge_capture_model_provider_id", None)
    if direct:
        return str(direct)
    config = getattr(bot, "integration_config", None) or {}
    if isinstance(config, dict) and config.get("knowledge_capture_model_provider_id"):
        return str(config["knowledge_capture_model_provider_id"])
    raw = getattr(bot, "_workspace_raw", None) or {}
    if isinstance(raw, dict) and raw.get("knowledge_capture_model_provider_id"):
        return str(raw["knowledge_capture_model_provider_id"])
    return resolve_effective_provider(
        getattr(channel, "model_override", None),
        getattr(channel, "model_provider_id_override", None),
        getattr(bot, "model_provider_id", None),
    )
