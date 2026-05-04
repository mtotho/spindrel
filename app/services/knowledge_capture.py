"""Review-first user knowledge capture pipeline primitives."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

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
    """Placeholder extractor seam.

    The LLM-backed extractor is intentionally separate from skip-rule logic so
    Phase 1 dogfood can tune prompts without touching persistence and security
    gates. Until wired, capture emits no candidates.
    """
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
