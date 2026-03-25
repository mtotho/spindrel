import logging
import uuid
from typing import Any

from app.agent.embeddings import embed_text as _embed
from app.db.engine import async_session
from app.db.models import BotKnowledge, KnowledgeAccess, KnowledgePin, KnowledgeWrite
from app.config import settings
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
logger = logging.getLogger(__name__)

_MISSING_ST = object()


# ---------------------------------------------------------------------------
# Legacy scoping filters (kept for admin and backward compat)
# ---------------------------------------------------------------------------

def _knowledge_bot_client_filter(bot_id: str, client_id: str):
    """Match rows visible to this bot+client (ignores session_id). Legacy filter."""
    bot_ok = (BotKnowledge.bot_id == bot_id) | (BotKnowledge.bot_id.is_(None))
    client_ok = (BotKnowledge.client_id == client_id) | (BotKnowledge.client_id.is_(None))
    return bot_ok & client_ok


def _knowledge_visibility_filter(
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None,
):
    """Legacy visibility filter for backward compat (used by admin)."""
    session_ok = (
        BotKnowledge.session_id.is_(None)
        if session_id is None
        else (BotKnowledge.session_id == session_id) | (BotKnowledge.session_id.is_(None))
    )
    return _knowledge_bot_client_filter(bot_id, client_id) & session_ok


# ---------------------------------------------------------------------------
# knowledge_access-based scoping
# ---------------------------------------------------------------------------

def _ka_scope_filter(
    bot_id: str,
    channel_id: uuid.UUID | None,
):
    """Build knowledge_access scope filter for automatic RAG retrieval.

    Matches:
    - channel scope: scope_type='channel' AND scope_key=channel_id
    - bot scope: scope_type='bot' AND scope_key=bot_id
    - global scope: scope_type='global' (but NOT tag_only mode)
    """
    filters = [
        (KnowledgeAccess.scope_type == "bot") & (KnowledgeAccess.scope_key == bot_id),
        (KnowledgeAccess.scope_type == "global") & (KnowledgeAccess.mode != "tag_only"),
    ]
    if channel_id is not None:
        filters.append(
            (KnowledgeAccess.scope_type == "channel") & (KnowledgeAccess.scope_key == str(channel_id))
        )
    return or_(*filters)


def _ka_name_scope_filter(
    bot_id: str,
    channel_id: uuid.UUID | None,
):
    """Scope filter for explicit @name retrieval — all modes allowed."""
    filters = [
        (KnowledgeAccess.scope_type == "bot") & (KnowledgeAccess.scope_key == bot_id),
        (KnowledgeAccess.scope_type == "global"),
    ]
    if channel_id is not None:
        filters.append(
            (KnowledgeAccess.scope_type == "channel") & (KnowledgeAccess.scope_key == str(channel_id))
        )
    return or_(*filters)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def _record_knowledge_write(
    db: AsyncSession,
    *,
    bot_knowledge_id: uuid.UUID,
    knowledge_name: str,
    bot_id: str | None,
    client_id: str | None,
    session_id: uuid.UUID | None,
    channel_id: uuid.UUID | None = None,
) -> None:
    """Append an audit row to ``knowledge_writes``."""
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
            channel_id=channel_id,
            correlation_id=correlation_id,
            created_at=datetime.now(timezone.utc),
        )
    )


# ---------------------------------------------------------------------------
# Upsert / Append / Update
# ---------------------------------------------------------------------------

async def upsert_knowledge(
    name: str,
    content: str,
    bot_id: str | None,
    client_id: str | None,
    *,
    session_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    created_by_bot: str | None = None,
    similarity_threshold: float | None = None,
    scope: str = "channel",
) -> tuple[bool, str | None]:
    """Create or update a knowledge document.

    scope: 'channel' (default), 'bot', or 'global' — determines the knowledge_access entry.
    """
    scoped_bot_id, scoped_client_id = bot_id, client_id
    embedding = await _embed(content)
    async with async_session() as db:
        # Find existing by name + legacy scope (backward compat lookup)
        existing = await db.execute(
            select(BotKnowledge).where(
                BotKnowledge.name == name,
                BotKnowledge.bot_id == scoped_bot_id,
                BotKnowledge.client_id == scoped_client_id,
                BotKnowledge.session_id == session_id,
            )
        )
        row = existing.scalar_one_or_none()

        # Also try lookup via knowledge_access if not found by legacy scope
        if row is None and channel_id is not None:
            ka_stmt = (
                select(BotKnowledge)
                .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
                .where(
                    BotKnowledge.name == name,
                    KnowledgeAccess.scope_type == "channel",
                    KnowledgeAccess.scope_key == str(channel_id),
                )
                .limit(1)
            )
            row = (await db.execute(ka_stmt)).scalar_one_or_none()

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

        # Ensure knowledge_access entry exists
        scope_type, scope_key = _resolve_scope(scope, bot_id, channel_id)
        existing_ka = await db.execute(
            select(KnowledgeAccess).where(
                KnowledgeAccess.knowledge_id == row.id,
                KnowledgeAccess.scope_type == scope_type,
                KnowledgeAccess.scope_key == scope_key,
            )
        )
        if existing_ka.scalar_one_or_none() is None:
            db.add(KnowledgeAccess(
                knowledge_id=row.id,
                scope_type=scope_type,
                scope_key=scope_key,
                mode="rag",
            ))

        _record_knowledge_write(
            db,
            bot_knowledge_id=row.id,
            knowledge_name=row.name,
            bot_id=row.bot_id,
            client_id=row.client_id,
            session_id=row.session_id,
            channel_id=channel_id,
        )
        await db.commit()
    return (True, None)


def _resolve_scope(scope: str, bot_id: str | None, channel_id: uuid.UUID | None) -> tuple[str, str | None]:
    """Map scope string to (scope_type, scope_key)."""
    if scope == "bot" and bot_id:
        return "bot", bot_id
    if scope == "global":
        return "global", None
    if scope == "channel" and channel_id:
        return "channel", str(channel_id)
    # Fallback: bot scope if channel not available
    if bot_id:
        return "bot", bot_id
    return "global", None


async def append_to_knowledge(
    name: str,
    content: str,
    bot_id: str | None,
    client_id: str | None,
    session_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    scoped_bot_id, scoped_client_id = bot_id, client_id
    async with async_session() as db:
        # Try legacy lookup first
        existing = await db.execute(
            select(BotKnowledge).where(
                BotKnowledge.name == name,
                BotKnowledge.bot_id == scoped_bot_id,
                BotKnowledge.client_id == scoped_client_id,
                BotKnowledge.session_id == session_id,
            )
        )
        row = existing.scalar_one_or_none()

        # Fallback: knowledge_access lookup
        if row is None and channel_id is not None:
            ka_stmt = (
                select(BotKnowledge)
                .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
                .where(
                    BotKnowledge.name == name,
                    _ka_name_scope_filter(bot_id or "", channel_id),
                )
                .limit(1)
            )
            row = (await db.execute(ka_stmt)).scalar_one_or_none()

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
            channel_id=channel_id,
        )
        await db.commit()
        return (True, None)


async def edit_knowledge(
    name: str,
    old_text: str,
    new_text: str,
    bot_id: str | None,
    client_id: str | None,
    session_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    """Find-and-replace within a knowledge document, then re-embed."""
    scoped_bot_id, scoped_client_id = bot_id, client_id
    async with async_session() as db:
        # Try legacy lookup first
        existing = await db.execute(
            select(BotKnowledge).where(
                BotKnowledge.name == name,
                BotKnowledge.bot_id == scoped_bot_id,
                BotKnowledge.client_id == scoped_client_id,
                BotKnowledge.session_id == session_id,
            )
        )
        row = existing.scalar_one_or_none()

        # Fallback: knowledge_access lookup
        if row is None and channel_id is not None:
            ka_stmt = (
                select(BotKnowledge)
                .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
                .where(
                    BotKnowledge.name == name,
                    _ka_name_scope_filter(bot_id or "", channel_id),
                )
                .limit(1)
            )
            row = (await db.execute(ka_stmt)).scalar_one_or_none()

        if not row:
            return (False, "Knowledge document not found.")
        if old_text not in row.content:
            return (False, "old_text not found in document. Use get_knowledge to see current content.")
        updated = row.content.replace(old_text, new_text, 1)
        row.content = updated
        row.embedding = await _embed(updated)
        row.updated_at = datetime.now(timezone.utc)
        _record_knowledge_write(
            db,
            bot_knowledge_id=row.id,
            knowledge_name=row.name,
            bot_id=scoped_bot_id,
            client_id=scoped_client_id,
            session_id=session_id,
            channel_id=channel_id,
        )
        await db.commit()
        return (True, None)


async def delete_knowledge(
    name: str,
    bot_id: str | None,
    client_id: str | None,
    session_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    """Delete a knowledge document and its associated access entries."""
    scoped_bot_id, scoped_client_id = bot_id, client_id
    async with async_session() as db:
        # Try legacy lookup first
        existing = await db.execute(
            select(BotKnowledge).where(
                BotKnowledge.name == name,
                BotKnowledge.bot_id == scoped_bot_id,
                BotKnowledge.client_id == scoped_client_id,
                BotKnowledge.session_id == session_id,
            )
        )
        row = existing.scalar_one_or_none()

        # Fallback: knowledge_access lookup
        if row is None and channel_id is not None:
            ka_stmt = (
                select(BotKnowledge)
                .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
                .where(
                    BotKnowledge.name == name,
                    _ka_name_scope_filter(bot_id or "", channel_id),
                )
                .limit(1)
            )
            row = (await db.execute(ka_stmt)).scalar_one_or_none()

        if not row:
            return (False, "Knowledge document not found.")

        # Delete associated knowledge_access entries
        await db.execute(
            delete(KnowledgeAccess).where(KnowledgeAccess.knowledge_id == row.id)
        )
        # Delete associated knowledge_pin entries (legacy)
        await db.execute(
            delete(KnowledgePin).where(KnowledgePin.knowledge_name == name)
        )
        # Delete the knowledge document itself
        await db.delete(row)
        await db.commit()
        logger.info("Deleted knowledge document '%s' (id=%s)", name, row.id)
        return (True, None)


async def update_knowledge_entry(
    entry_id: uuid.UUID,
    content: str,
    bot_id: str | None,
    client_id: str | None,
    session_id: uuid.UUID | None = None,
    similarity_threshold: float | None | Any = _MISSING_ST,
) -> bool:
    """Update content, scope, and re-embed an existing knowledge doc by ID (admin use)."""
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


# ---------------------------------------------------------------------------
# Retrieval (knowledge_access-based)
# ---------------------------------------------------------------------------

async def retrieve_knowledge(
    query: str,
    bot_id: str,
    client_id: str,
    *,
    fallback_threshold: float | None = None,
    session_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
) -> tuple[list[str], float]:
    """Semantic RAG via knowledge_access. Falls back to legacy filter if no access entries exist."""
    fb = fallback_threshold if fallback_threshold is not None else settings.KNOWLEDGE_SIMILARITY_THRESHOLD
    embedding = await _embed(query)
    distance_expr = BotKnowledge.embedding.cosine_distance(embedding)

    # Primary: knowledge_access-based retrieval
    stmt = (
        select(
            BotKnowledge.name,
            BotKnowledge.content,
            distance_expr.label("distance"),
            BotKnowledge.similarity_threshold,
        )
        .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
        .where(
            KnowledgeAccess.mode.in_(["rag", "pinned"]),
            _ka_scope_filter(bot_id, channel_id),
        )
        .order_by(distance_expr)
        .limit(3)
    )
    async with async_session() as db:
        rows = (await db.execute(stmt)).all()

    # Fallback to legacy if no knowledge_access entries found
    if not rows:
        stmt_legacy = (
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
            rows = (await db.execute(stmt_legacy)).all()

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
    channel_id: uuid.UUID | None = None,
) -> BotKnowledge | None:
    async with async_session() as db:
        # Try knowledge_access-based lookup first
        if channel_id is not None:
            ka_stmt = (
                select(BotKnowledge)
                .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
                .where(
                    BotKnowledge.name == name,
                    _ka_name_scope_filter(bot_id, channel_id),
                )
                .limit(1)
            )
            row = (await db.execute(ka_stmt)).scalar_one_or_none()
            if row is not None:
                return row

        # Fallback to legacy lookup
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
    channel_id: uuid.UUID | None = None,
) -> str | None:
    """Fetch one doc by name."""
    row = await get_knowledge_row_by_name(
        name, bot_id, client_id, session_id=session_id,
        ignore_session_scope=ignore_session_scope,
        channel_id=channel_id,
    )
    return f"[Knowledge: {row.name}]\n\n{row.content}" if row else None


async def set_knowledge_similarity_for_match(
    name: str,
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None,
    threshold: float,
    channel_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    """Set per-row similarity for the document that automatic RAG would pick."""
    target = await get_knowledge_row_by_name(
        name, bot_id, client_id, session_id=session_id,
        ignore_session_scope=False, channel_id=channel_id,
    )
    if not target:
        return False, f"No knowledge document named {name!r} in scope."
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
            channel_id=channel_id,
        )
        await db.commit()
    return True, None


async def list_knowledge_candidates_for_bot(bot_id: str, limit: int = 150) -> list[BotKnowledge]:
    """Rows this bot could ever match (bot_id matches or row is cross-bot). Used by admin."""
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
    channel_id: uuid.UUID | None = None,
) -> tuple[list[str], list[str]]:
    """Return (formatted_docs, names) for all pinned knowledge in scope.

    Uses knowledge_access with mode='pinned', falling back to legacy KnowledgePin table.
    """
    docs: list[str] = []
    names: list[str] = []

    async with async_session() as db:
        # Primary: knowledge_access pinned entries
        _ka_sub = (
            select(
                BotKnowledge.name,
                BotKnowledge.content,
                func.row_number().over(
                    partition_by=BotKnowledge.name,
                    order_by=BotKnowledge.id,
                ).label("_rn"),
            )
            .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
            .where(
                KnowledgeAccess.mode == "pinned",
                _ka_scope_filter(bot_id, channel_id),
            )
            .subquery()
        )
        ka_stmt = select(_ka_sub.c.name, _ka_sub.c.content).where(_ka_sub.c._rn == 1)
        ka_rows = (await db.execute(ka_stmt)).all()

        if ka_rows:
            for name, content in ka_rows:
                docs.append(f"[Knowledge: {name}]\n\n{content}")
                names.append(name)
            return docs, names

    # Fallback: legacy KnowledgePin
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

    for pname in pin_names:
        doc = await get_knowledge_by_name(pname, bot_id, client_id, session_id=session_id, channel_id=channel_id)
        if doc:
            docs.append(doc)
            names.append(pname)

    return docs, names


# ---------------------------------------------------------------------------
# knowledge_access management (for tools and API)
# ---------------------------------------------------------------------------

async def set_knowledge_mode(
    knowledge_id: uuid.UUID,
    scope_type: str,
    scope_key: str | None,
    mode: str,
) -> tuple[bool, str | None]:
    """Set the mode (rag/pinned/tag_only) for a knowledge_access entry."""
    if mode not in ("rag", "pinned", "tag_only"):
        return False, f"Invalid mode: {mode}"
    if scope_type not in ("channel", "bot", "global"):
        return False, f"Invalid scope_type: {scope_type}"

    async with async_session() as db:
        stmt = select(KnowledgeAccess).where(
            KnowledgeAccess.knowledge_id == knowledge_id,
            KnowledgeAccess.scope_type == scope_type,
            KnowledgeAccess.scope_key == scope_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            # Create new access entry
            db.add(KnowledgeAccess(
                knowledge_id=knowledge_id,
                scope_type=scope_type,
                scope_key=scope_key,
                mode=mode,
            ))
        else:
            row.mode = mode
        await db.commit()
    return True, None


async def create_knowledge_pin(
    knowledge_name: str,
    bot_id: str | None,
    client_id: str | None,
    channel_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    """Create a pin via knowledge_access with mode='pinned'."""
    # Determine scope
    if channel_id:
        scope_type, scope_key = "channel", str(channel_id)
    elif bot_id:
        scope_type, scope_key = "bot", bot_id
    else:
        return False, "At least one of bot_id, client_id, or channel_id must be provided."

    async with async_session() as db:
        # Find the knowledge doc
        stmt = select(BotKnowledge).where(BotKnowledge.name == knowledge_name).limit(1)
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row:
            return False, f"Knowledge document '{knowledge_name}' not found."

        # Check for existing access entry
        existing = await db.execute(
            select(KnowledgeAccess).where(
                KnowledgeAccess.knowledge_id == row.id,
                KnowledgeAccess.scope_type == scope_type,
                KnowledgeAccess.scope_key == scope_key,
            )
        )
        ka = existing.scalar_one_or_none()
        if ka:
            if ka.mode == "pinned":
                return False, "Already pinned for this scope."
            ka.mode = "pinned"
        else:
            db.add(KnowledgeAccess(
                knowledge_id=row.id,
                scope_type=scope_type,
                scope_key=scope_key,
                mode="pinned",
            ))

        # Also create legacy pin for backward compat
        try:
            db.add(KnowledgePin(
                knowledge_name=knowledge_name,
                bot_id=bot_id or None,
                client_id=client_id or None,
            ))
        except Exception:
            pass  # Ignore duplicate legacy pin

        await db.commit()
    return True, None


async def delete_knowledge_pin(
    knowledge_name: str,
    bot_id: str | None,
    client_id: str | None,
    channel_id: uuid.UUID | None = None,
) -> bool:
    """Remove a pin by setting mode back to 'rag'."""
    # Determine scope
    if channel_id:
        scope_type, scope_key = "channel", str(channel_id)
    elif bot_id:
        scope_type, scope_key = "bot", bot_id
    else:
        scope_type, scope_key = "global", None

    async with async_session() as db:
        # Find knowledge doc
        stmt = select(BotKnowledge).where(BotKnowledge.name == knowledge_name).limit(1)
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row:
            return False

        # Update knowledge_access
        ka_stmt = select(KnowledgeAccess).where(
            KnowledgeAccess.knowledge_id == row.id,
            KnowledgeAccess.scope_type == scope_type,
            KnowledgeAccess.scope_key == scope_key,
            KnowledgeAccess.mode == "pinned",
        )
        ka = (await db.execute(ka_stmt)).scalar_one_or_none()
        if ka:
            ka.mode = "rag"

        # Also remove legacy pin
        legacy_stmt = select(KnowledgePin).where(KnowledgePin.knowledge_name == knowledge_name)
        if bot_id:
            legacy_stmt = legacy_stmt.where(KnowledgePin.bot_id == bot_id)
        else:
            legacy_stmt = legacy_stmt.where(KnowledgePin.bot_id.is_(None))
        if client_id:
            legacy_stmt = legacy_stmt.where(KnowledgePin.client_id == client_id)
        else:
            legacy_stmt = legacy_stmt.where(KnowledgePin.client_id.is_(None))
        legacy_row = (await db.execute(legacy_stmt)).scalar_one_or_none()
        if legacy_row:
            await db.delete(legacy_row)

        await db.commit()
    return ka is not None or legacy_row is not None


async def list_knowledge_bases(
    bot_id: str,
    client_id: str,
    session_id: uuid.UUID | None = None,
    *,
    ignore_session_scope: bool = False,
    channel_id: uuid.UUID | None = None,
) -> list[dict]:
    """Return list of dicts with name, source_type, editable_from_tool, scope, mode."""
    async with async_session() as db:
        # Try knowledge_access-based listing first
        if channel_id is not None:
            _ka_sub = (
                select(
                    BotKnowledge.name,
                    BotKnowledge.source_type,
                    BotKnowledge.editable_from_tool,
                    KnowledgeAccess.scope_type,
                    KnowledgeAccess.scope_key,
                    KnowledgeAccess.mode,
                    func.row_number().over(
                        partition_by=BotKnowledge.name,
                        order_by=BotKnowledge.name,
                    ).label("_rn"),
                )
                .join(KnowledgeAccess, KnowledgeAccess.knowledge_id == BotKnowledge.id)
                .where(_ka_name_scope_filter(bot_id, channel_id))
                .subquery()
            )
            stmt = (
                select(
                    _ka_sub.c.name,
                    _ka_sub.c.source_type,
                    _ka_sub.c.editable_from_tool,
                    _ka_sub.c.scope_type,
                    _ka_sub.c.scope_key,
                    _ka_sub.c.mode,
                )
                .where(_ka_sub.c._rn == 1)
                .order_by(_ka_sub.c.name)
            )
            result = await db.execute(stmt)
            rows = result.all()
            if rows:
                return [
                    {
                        "name": r.name,
                        "source_type": r.source_type,
                        "editable_from_tool": r.editable_from_tool,
                        "scope_type": r.scope_type,
                        "scope_key": r.scope_key,
                        "mode": r.mode,
                    }
                    for r in rows
                ]

        # Fallback to legacy listing
        vis = (
            _knowledge_bot_client_filter(bot_id, client_id)
            if ignore_session_scope
            else _knowledge_visibility_filter(bot_id, client_id, session_id)
        )
        _legacy_sub = (
            select(
                BotKnowledge.name,
                BotKnowledge.source_type,
                BotKnowledge.editable_from_tool,
                func.row_number().over(
                    partition_by=BotKnowledge.name,
                    order_by=BotKnowledge.name,
                ).label("_rn"),
            )
            .where(vis)
            .subquery()
        )
        stmt = (
            select(_legacy_sub.c.name, _legacy_sub.c.source_type, _legacy_sub.c.editable_from_tool)
            .where(_legacy_sub.c._rn == 1)
            .order_by(_legacy_sub.c.name)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [{"name": r.name, "source_type": r.source_type, "editable_from_tool": r.editable_from_tool} for r in rows]
