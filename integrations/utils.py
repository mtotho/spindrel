"""
Utility helpers for integrations.

Integrations should use these instead of importing app internals directly.
All functions require a live AsyncSession (inject via FastAPI `Depends(get_db)`).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.embeddings import embed_text
from app.config import settings
from app.db.models import IntegrationDocument, Message, Session, Task
from app.services.sessions import load_or_create, store_passive_message
from datetime import datetime, timezone


async def ingest_document(
    integration_id: str,
    title: str | None,
    content: str,
    *,
    session_id: uuid.UUID | None = None,
    metadata: dict | None = None,
    db: AsyncSession,
) -> uuid.UUID:
    """Embed and store a document in integration_documents. Returns the document id."""
    embed_input = f"{title}\n{content}" if title else content
    embedding = await embed_text(embed_input)

    doc = IntegrationDocument(
        id=uuid.uuid4(),
        integration_id=integration_id,
        session_id=session_id,
        title=title,
        content=content,
        embedding=embedding,
        metadata_=metadata or {},
    )
    db.add(doc)
    await db.commit()
    return doc.id


async def search_documents(
    q: str,
    *,
    integration_id: str | None = None,
    session_id: uuid.UUID | None = None,
    limit: int = 10,
    db: AsyncSession,
) -> list[dict]:
    """Semantic search over integration_documents. Returns list of dicts."""
    from sqlalchemy import text as sa_text

    query_embedding = await embed_text(q)
    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    stmt = (
        select(IntegrationDocument)
        .where(IntegrationDocument.embedding.isnot(None))
        .order_by(sa_text(f"embedding <=> '{embedding_str}'::vector"))
        .limit(limit)
    )
    if integration_id is not None:
        stmt = stmt.where(IntegrationDocument.integration_id == integration_id)
    if session_id is not None:
        stmt = stmt.where(IntegrationDocument.session_id == session_id)

    result = await db.execute(stmt)
    return [
        {
            "id": str(doc.id),
            "integration_id": doc.integration_id,
            "session_id": str(doc.session_id) if doc.session_id else None,
            "title": doc.title,
            "content": doc.content,
            "metadata": doc.metadata_,
        }
        for doc in result.scalars().all()
    ]


async def get_or_create_session(
    client_id: str,
    bot_id: str,
    *,
    dispatch_config: dict | None = None,
    db: AsyncSession,
) -> uuid.UUID:
    """
    Get or create a session for the given client_id/bot_id pair.
    Optionally persist dispatch_config so injected messages know where to fan-out.
    """
    session_id, _ = await load_or_create(db, None, client_id, bot_id, locked=True)

    if dispatch_config:
        session = await db.get(Session, session_id)
        if session and not session.dispatch_config:
            session.dispatch_config = dispatch_config
            await db.commit()

    return session_id


async def inject_message(
    session_id: uuid.UUID,
    content: str,
    source: str,
    *,
    run_agent: bool = False,
    notify: bool = True,
    dispatch_config: dict | None = None,
    execution_config: dict | None = None,
    extra_metadata: dict | None = None,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Inject an external message into a session.

    - notify=True: fans out to the session's dispatch_config (Slack, etc.)
    - run_agent=True: creates an async Task to run the agent on this message
    - dispatch_config: if provided, used on the Task instead of session.dispatch_config
      (allows per-event data like comment_target to be passed through)
    - extra_metadata: additional metadata merged into the message (sender info, etc.)

    Returns {"message_id": ..., "session_id": ..., "task_id": ... or None}
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    # Sanitize inbound content from external integrations
    from app.security.prompt_sanitize import sanitize_unicode
    content = sanitize_unicode(content)

    metadata = {"source": source}
    if extra_metadata:
        metadata.update(extra_metadata)
    await store_passive_message(db, session_id, content, metadata, channel_id=session.channel_id)

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    msg = result.scalar_one()
    await db.commit()

    if notify:
        from app.routers.api_v1_sessions import _fanout
        await _fanout(session, content, source)

    # Fire integration event triggers if this message comes from an integration
    if source and source not in ("web", "api", "system"):
        from app.utils import safe_create_task
        safe_create_task(emit_integration_event(
            source, "message_received",
            {"session_id": str(session_id), "source": source},
            client_id=session.client_id or None, category="message",
        ))

    task_id: uuid.UUID | None = None
    if run_agent:
        effective_dispatch = dispatch_config or session.dispatch_config or {}
        # Forward the pre-persisted user message id so persist_turn skips it
        # at the end of the agent loop. Without this, the channel ends up
        # with two identical user rows (one from store_passive_message above,
        # one from persist_turn after the agent runs). See app/agent/tasks.py
        # _run_one_task for the consumer side.
        _ecfg = dict(execution_config or {})
        _ecfg["pre_user_msg_id"] = str(msg.id)
        task = Task(
            bot_id=session.bot_id,
            client_id=session.client_id,
            session_id=session_id,
            channel_id=session.channel_id,
            prompt=content,
            status="pending",
            task_type="api",
            dispatch_type=effective_dispatch.get("type") or "none",
            dispatch_config=effective_dispatch,
            execution_config=_ecfg,
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_id = task.id

    return {
        "message_id": str(msg.id),
        "session_id": str(session_id),
        "task_id": str(task_id) if task_id else None,
    }


# ---------------------------------------------------------------------------
# Integration event emission — fires task triggers for integration events
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)
_event_cooldowns: dict[str, float] = {}
_COOLDOWN_MAX_SIZE = 500  # evict oldest entries when exceeded

# Default cooldowns by event category (seconds)
_CATEGORY_COOLDOWNS: dict[str, float] = {
    "webhook": 0,       # discrete events, no cooldown
    "message": 300,     # 5 min — high-frequency messaging
    "poll": 60,         # 1 min — naturally rate-limited by poll interval
    "device": 30,       # 30s — hardware events
}


async def emit_integration_event(
    integration_type: str,
    event_type: str,
    event_data: dict,
    *,
    client_id: str | None = None,
    cooldown_seconds: float | None = None,
    category: str = "webhook",
) -> int:
    """Fire task triggers for an integration event.

    Fires for both integration-wide triggers (e.g. "any github event") and
    binding-specific triggers (e.g. "events from github:mtotho/spindrel").

    ``cooldown_seconds`` overrides the default per-category cooldown.
    """
    effective_cooldown = (
        cooldown_seconds if cooldown_seconds is not None
        else _CATEGORY_COOLDOWNS.get(category, 0)
    )

    now = time.monotonic()
    key = f"{client_id or integration_type}:{event_type}"
    if effective_cooldown > 0:
        last = _event_cooldowns.get(key, 0)
        if now - last < effective_cooldown:
            return 0
    _event_cooldowns[key] = now

    # Evict oldest entries to prevent unbounded growth
    if len(_event_cooldowns) > _COOLDOWN_MAX_SIZE:
        sorted_keys = sorted(_event_cooldowns, key=_event_cooldowns.get)  # type: ignore[arg-type]
        for k in sorted_keys[: len(_event_cooldowns) - _COOLDOWN_MAX_SIZE // 2]:
            _event_cooldowns.pop(k, None)

    from app.agent.tasks import fire_event_triggers

    spawned = 0
    try:
        spawned += await fire_event_triggers(integration_type, event_type, event_data)
        if client_id:
            spawned += await fire_event_triggers(
                f"binding:{client_id}", event_type, event_data,
            )
    except Exception:
        _logger.exception(
            "emit_integration_event failed: %s/%s", integration_type, event_type,
        )

    return spawned
