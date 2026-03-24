"""
Utility helpers for integrations.

Integrations should use these instead of importing app internals directly.
All functions require a live AsyncSession (inject via FastAPI `Depends(get_db)`).
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import IntegrationDocument, Message, Session, Task
from app.services.sessions import load_or_create, store_passive_message
from datetime import datetime, timezone

_embed_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=30.0,
)


async def embed_text(text: str) -> list[float]:
    """Embed text using the configured embedding model."""
    response = await _embed_client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=[text],
    )
    return response.data[0].embedding


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
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Inject an external message into a session.

    - notify=True: fans out to the session's dispatch_config (Slack, etc.)
    - run_agent=True: creates an async Task to run the agent on this message

    Returns {"message_id": ..., "session_id": ..., "task_id": ... or None}
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    metadata = {"source": source}
    await store_passive_message(db, session_id, content, metadata)

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

    task_id: uuid.UUID | None = None
    if run_agent:
        task = Task(
            bot_id=session.bot_id,
            client_id=session.client_id,
            session_id=session_id,
            prompt=content,
            status="pending",
            task_type="api",
            dispatch_type=(session.dispatch_config or {}).get("type") or "none",
            dispatch_config=session.dispatch_config or {},
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
