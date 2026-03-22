import logging
import uuid
from typing import Any

from app.db.engine import async_session
from app.db.models import BotKnowledge, KnowledgePin, KnowledgeWrite
from app.config import settings
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI
from datetime import datetime, timezone
logger = logging.getLogger(__name__)

_MISSING_ST = object()

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=30.0,
)

def _knowledge_bot_client_filter(bot_id: str, client_id: str):
    """Match rows visible to this bot+client (ignores session_id)."""
    bot_ok = (BotKnowledge.bot_id == bot_id) | (BotKnowledge.bot_id.is_(None))
    client_ok = (BotKnowledge.client_id == client_id) | (BotKnowledge.client_id.is_(None))
    return bot_ok & client_ok


def _knowledge_visibility_filter(
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None,
):
    """Rows visible for automatic RAG: matching bot/client, and this session or legacy (no session)."""
    session_ok = (
        BotKnowledge.session_id.is_(None)
        if session_id is None
        else (BotKnowledge.session_id == session_id) | (BotKnowledge.session_id.is_(None))
    )
    return _knowledge_bot_client_filter(bot_id, client_id) & session_ok


async def _embed(text: str) -> list[float]:
    """Embed text via LiteLLM embeddings endpoint."""
    response = await _client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=[text],
    )
    return response.data[0].embedding


def _record_knowledge_write(
    db: AsyncSession,
    *,
    bot_knowledge_id: uuid.UUID,
    knowledge_name: str,
    bot_id: str | None,
    client_id: str | None,
    session_id: uuid.UUID | None,
) -> None:
    """Append an audit row to ``knowledge_writes`` (same transaction as the mutation)."""
    try:
        from app.agent.context import current_correlation_id

        correlation_id = current_correlation_id.get()
    except Exception:
        correlation_id = None
    db.add(
        KnowledgeWrite(
            bot_knowledge_id=bot_knowledge_id,
            knowledge_name=knowledge_name,
            bot_id=bot_id,
            client_id=client_id,
            session_id=session_id,
            correlation_id=correlation_id,
            created_at=datetime.now(timezone.utc),
        )
    )


async def upsert_knowledge(
    name: str,
    content: str,
    bot_id: str | None,
    client_id: str | None,
    *,
    session_id: uuid.UUID | None = None,
    created_by_bot: str | None = None,
    similarity_threshold: float | None = None,
) -> tuple[bool, str | None]:
    scoped_bot_id, scoped_client_id = bot_id, client_id
    embedding = await _embed(content)
    async with async_session() as db:
        existing = await db.execute(
            select(BotKnowledge).where(
                BotKnowledge.name == name,
                BotKnowledge.bot_id == scoped_bot_id,
                BotKnowledge.client_id == scoped_client_id,
                BotKnowledge.session_id == session_id,
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            row.content = content
            row.embedding = embedding
            row.updated_at = datetime.now(timezone.utc)
            if similarity_threshold is not None:
                row.similarity_threshold = similarity_threshold
        else:
            author = created_by_bot if created_by_bot is not None else scoped_bot_id
            if not author:
                author = "admin"
            row = BotKnowledge(
                name=name, content=content, embedding=embedding,
                bot_id=scoped_bot_id, client_id=scoped_client_id,
                session_id=session_id,
                created_by_bot=author,
                similarity_threshold=similarity_threshold,
            )
            db.add(row)
        await db.flush()
        _record_knowledge_write(
            db,
            bot_knowledge_id=row.id,
            knowledge_name=row.name,
            bot_id=row.bot_id,
            client_id=row.client_id,
            session_id=row.session_id,
        )
        await db.commit()
    return (True, None)


async def append_to_knowledge(
    name: str,
    content: str,
    bot_id: str | None,
    client_id: str | None,
    session_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    scoped_bot_id, scoped_client_id = bot_id, client_id
    async with async_session() as db:
        existing = await db.execute(
            select(BotKnowledge).where(
                BotKnowledge.name == name,
                BotKnowledge.bot_id == scoped_bot_id,
                BotKnowledge.client_id == scoped_client_id,
                BotKnowledge.session_id == session_id,
            )
        )
        row = existing.scalar_one_or_none()
        if not row:
            return (False, "Knowledge document not found")
        row.content += content
        row.updated_at = datetime.now(timezone.utc)
        _record_knowledge_write(
            db,
            bot_knowledge_id=row.id,
            knowledge_name=row.name,
            bot_id=scoped_bot_id,
            client_id=scoped_client_id,
            session_id=session_id,
        )
        await db.commit()
        return (True, None)

async def update_knowledge_entry(
    entry_id: uuid.UUID,
    content: str,
    bot_id: str | None,
    client_id: str | None,
    session_id: uuid.UUID | None = None,
    similarity_threshold: float | None | Any = _MISSING_ST,
) -> bool:
    """Update content, scope, and re-embed an existing knowledge doc by ID.

    Pass ``similarity_threshold`` explicitly (including ``None`` to clear per-row override)
    when updating from admin full save; omit to leave the column unchanged.
    """
    embedding = await _embed(content)
    async with async_session() as db:
        row = await db.get(BotKnowledge, entry_id)
        if not row:
            return False
        row.content = content
        row.bot_id = bot_id
        row.client_id = client_id
        row.session_id = session_id
        row.embedding = embedding
        row.updated_at = datetime.now(timezone.utc)
        if similarity_threshold is not _MISSING_ST:
            row.similarity_threshold = similarity_threshold
        _record_knowledge_write(
            db,
            bot_knowledge_id=row.id,
            knowledge_name=row.name,
            bot_id=row.bot_id,
            client_id=row.client_id,
            session_id=row.session_id,
        )
        await db.commit()
    return True


async def retrieve_knowledge(
    query: str,
    bot_id: str,
    client_id: str,
    *,
    fallback_threshold: float | None = None,
    session_id: uuid.UUID | None = None,
) -> tuple[list[str], float]:
    """Semantic RAG: only rows visible via ``_knowledge_visibility_filter``.

    Each row may set ``similarity_threshold``; if NULL, ``fallback_threshold`` (default: settings) is used.
    """
    fb = (
        fallback_threshold
        if fallback_threshold is not None
        else settings.KNOWLEDGE_SIMILARITY_THRESHOLD
    )
    embedding = await _embed(query)
    distance_expr = BotKnowledge.embedding.cosine_distance(embedding)
    stmt = (
        select(
            BotKnowledge.name,
            BotKnowledge.content,
            distance_expr.label("distance"),
            BotKnowledge.similarity_threshold,
        )
        .order_by(distance_expr)
        .limit(3)
        .where(_knowledge_visibility_filter(bot_id, client_id, session_id))
    )
    async with async_session() as db:
        rows = (await db.execute(stmt)).all()
    if not rows:
        return [], 0.0
    best_similarity = 1.0 - rows[0][2]
    chunks = []
    for name, content, distance, row_thr in rows:
        thr = row_thr if row_thr is not None else fb
        if (1.0 - distance) >= thr:
            chunks.append(f"[Knowledge: {name}]\n\n{content}")
    return chunks, best_similarity


async def get_knowledge_row_by_name(
    name: str,
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None = None,
    *,
    ignore_session_scope: bool = False,
) -> BotKnowledge | None:
    async with async_session() as db:
        if ignore_session_scope:
            stmt = select(BotKnowledge).where(
                BotKnowledge.name == name,
                _knowledge_bot_client_filter(bot_id, client_id),
            )
            if session_id is not None:
                prefer = case(
                    (BotKnowledge.session_id == session_id, 0),
                    (BotKnowledge.session_id.is_(None), 1),
                    else_=2,
                )
            else:
                prefer = case((BotKnowledge.session_id.is_(None), 0), else_=1)
        else:
            stmt = select(BotKnowledge).where(
                BotKnowledge.name == name,
                _knowledge_visibility_filter(bot_id, client_id, session_id),
            )
            prefer = (
                case((BotKnowledge.session_id == session_id, 0), else_=1)
                if session_id is not None
                else case((BotKnowledge.session_id.is_(None), 0), else_=1)
            )
        stmt = stmt.order_by(
            prefer,
            BotKnowledge.bot_id.asc().nulls_last(),
            BotKnowledge.client_id.asc().nulls_last(),
        ).limit(1)
        return (await db.execute(stmt)).scalar_one_or_none()


async def get_knowledge_by_name(
    name: str,
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None = None,
    *,
    ignore_session_scope: bool = False,
) -> str | None:
    """Fetch one doc by name.

    Automatic RAG uses session visibility (``ignore_session_scope=False``): only this session
    plus legacy rows without ``session_id``.

    Explicit ``@knowledge:name`` / ``@name`` tags use ``ignore_session_scope=True``: any row
    for this bot+client matches, preferring current session, then legacy, then other sessions.
    """
    row = await get_knowledge_row_by_name(
        name, bot_id, client_id, session_id=session_id, ignore_session_scope=ignore_session_scope
    )
    return f"[Knowledge: {row.name}]\n\n{row.content}" if row else None


async def set_knowledge_similarity_for_match(
    name: str,
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None,
    threshold: float,
) -> tuple[bool, str | None]:
    """Set per-row similarity for the document that automatic RAG would pick for this scope."""
    target = await get_knowledge_row_by_name(
        name, bot_id, client_id, session_id=session_id, ignore_session_scope=False
    )
    if not target:
        return False, f"No knowledge document named {name!r} in this session scope."
    async with async_session() as db:
        row = await db.get(BotKnowledge, target.id)
        if not row:
            return False, "Document disappeared."
        row.similarity_threshold = threshold
        row.updated_at = datetime.now(timezone.utc)
        _record_knowledge_write(
            db,
            bot_knowledge_id=row.id,
            knowledge_name=row.name,
            bot_id=row.bot_id,
            client_id=row.client_id,
            session_id=row.session_id,
        )
        await db.commit()
    return True, None


async def list_knowledge_candidates_for_bot(bot_id: str, limit: int = 150) -> list[BotKnowledge]:
    """Rows this bot could ever match (bot_id matches or row is cross-bot)."""
    async with async_session() as db:
        stmt = (
            select(BotKnowledge)
            .where((BotKnowledge.bot_id == bot_id) | (BotKnowledge.bot_id.is_(None)))
            .order_by(BotKnowledge.updated_at.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())


async def get_pinned_knowledge_docs(
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None = None,
) -> tuple[list[str], list[str]]:
    """Return (formatted_docs, names) for all pins matching this bot+client context."""
    async with async_session() as db:
        stmt = (
            select(KnowledgePin.knowledge_name)
            .where(
                (KnowledgePin.bot_id == bot_id) | (KnowledgePin.bot_id.is_(None)),
                (KnowledgePin.client_id == client_id) | (KnowledgePin.client_id.is_(None)),
            )
            .distinct()
        )
        pin_names = list((await db.execute(stmt)).scalars().all())

    if not pin_names:
        return [], []

    docs = []
    for name in pin_names:
        doc = await get_knowledge_by_name(name, bot_id, client_id, session_id=session_id)
        if doc:
            docs.append(doc)

    return docs, pin_names


async def create_knowledge_pin(
    knowledge_name: str,
    bot_id: str | None,
    client_id: str | None,
) -> tuple[bool, str | None]:
    """Create a pin. At least one of bot_id/client_id must be set."""
    if not bot_id and not client_id:
        return False, "At least one of bot_id or client_id must be provided."
    try:
        async with async_session() as db:
            db.add(KnowledgePin(
                knowledge_name=knowledge_name,
                bot_id=bot_id or None,
                client_id=client_id or None,
            ))
            await db.commit()
        return True, None
    except Exception as exc:
        if "uq_knowledge_pins" in str(exc):
            return False, "Pin already exists for this scope."
        return False, str(exc)


async def delete_knowledge_pin(
    knowledge_name: str,
    bot_id: str | None,
    client_id: str | None,
) -> bool:
    async with async_session() as db:
        stmt = select(KnowledgePin).where(KnowledgePin.knowledge_name == knowledge_name)
        if bot_id:
            stmt = stmt.where(KnowledgePin.bot_id == bot_id)
        else:
            stmt = stmt.where(KnowledgePin.bot_id.is_(None))
        if client_id:
            stmt = stmt.where(KnowledgePin.client_id == client_id)
        else:
            stmt = stmt.where(KnowledgePin.client_id.is_(None))
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row:
            return False
        await db.delete(row)
        await db.commit()
    return True


async def list_knowledge_bases(
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None = None,
    *,
    ignore_session_scope: bool = False,
) -> list[dict]:
    """Return list of dicts with name, source_type, editable_from_tool for each accessible knowledge base."""
    async with async_session() as db:
        vis = (
            _knowledge_bot_client_filter(bot_id, client_id)
            if ignore_session_scope
            else _knowledge_visibility_filter(bot_id, client_id, session_id)
        )
        stmt = (
            select(BotKnowledge.name, BotKnowledge.source_type, BotKnowledge.editable_from_tool)
            .where(vis)
            .distinct(BotKnowledge.name)
            .order_by(BotKnowledge.name)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [{"name": r.name, "source_type": r.source_type, "editable_from_tool": r.editable_from_tool} for r in rows]
