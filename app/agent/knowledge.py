import logging
from app.db.engine import async_session
from app.db.models import BotKnowledge, KnowledgePin, KnowledgeWrite
from app.config import settings
from sqlalchemy import select
from openai import AsyncOpenAI
from datetime import datetime, timezone
logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=30.0,
)

async def _embed(text: str) -> list[float]:
    """Embed text via LiteLLM embeddings endpoint."""
    response = await _client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=[text],
    )
    return response.data[0].embedding

def _scope(
    bot_id: str,
    client_id: str,
    cross_bot: bool,
    cross_client: bool,
) -> tuple[str | None, str | None]:
    """Return (scoped_bot_id, scoped_client_id) for write operations."""
    return (None if cross_bot else bot_id), (None if cross_client else client_id)


async def upsert_knowledge(
    name: str,
    content: str,
    bot_id: str,
    client_id: str,
    cross_bot: bool = False,
    cross_client: bool = False,
) -> tuple[bool, str | None]:
    scoped_bot_id, scoped_client_id = _scope(bot_id, client_id, cross_bot, cross_client)
    embedding = await _embed(content)
    async with async_session() as db:
        existing = await db.execute(
            select(BotKnowledge).where(
                BotKnowledge.name == name,
                BotKnowledge.bot_id == scoped_bot_id,
                BotKnowledge.client_id == scoped_client_id,
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            row.content = content
            row.embedding = embedding
            row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(BotKnowledge(
                name=name, content=content, embedding=embedding,
                bot_id=scoped_bot_id, client_id=scoped_client_id,
                created_by_bot=bot_id,
            ))
        await db.commit()

        # Audit log: record this write with correlation_id from context if available
        try:
            from app.agent.context import current_correlation_id
            correlation_id = current_correlation_id.get()
        except Exception:
            correlation_id = None
        db.add(KnowledgeWrite(
            knowledge_name=name,
            bot_id=scoped_bot_id,
            client_id=scoped_client_id,
            correlation_id=correlation_id,
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()
    return (True, None)


async def append_to_knowledge(
    name: str,
    content: str,
    bot_id: str,
    client_id: str,
    cross_bot: bool = False,
    cross_client: bool = False,
) -> tuple[bool, str | None]:
    scoped_bot_id, scoped_client_id = _scope(bot_id, client_id, cross_bot, cross_client)
    async with async_session() as db:
        existing = await db.execute(
            select(BotKnowledge).where(
                BotKnowledge.name == name,
                BotKnowledge.bot_id == scoped_bot_id,
                BotKnowledge.client_id == scoped_client_id,
            )
        )
        row = existing.scalar_one_or_none()
        if not row:
            return (False, "Knowledge document not found")
        row.content += content
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return (True, None)

async def retrieve_knowledge(
    query: str,
    bot_id: str,
    client_id: str,
    cross_bot: bool = False,
    cross_client: bool = False,
    similarity_threshold: float = 0.45,
) -> tuple[list[str], float]:
    embedding = await _embed(query)
    distance_expr = BotKnowledge.embedding.cosine_distance(embedding)
    stmt = (
        select(BotKnowledge.name, BotKnowledge.content, distance_expr.label("distance"))
        .order_by(distance_expr)
        .limit(3)
    )
    if cross_bot and cross_client:
        # No restriction on bot_id or client_id
        pass
    elif cross_bot and not cross_client:
        # All bots for this client
        stmt = stmt.where(
            (BotKnowledge.client_id == client_id) | (BotKnowledge.client_id.is_(None)),
        )
    elif not cross_bot and cross_client:
        # This bot for any client
        stmt = stmt.where(
            (BotKnowledge.bot_id == bot_id) | (BotKnowledge.bot_id.is_(None)),
        )
    else:
        # Only this bot and client (or shared)
        stmt = stmt.where(
            ((BotKnowledge.bot_id == bot_id) | (BotKnowledge.bot_id.is_(None))) &
            ((BotKnowledge.client_id == client_id) | (BotKnowledge.client_id.is_(None))),
        )
    async with async_session() as db:
        rows = (await db.execute(stmt)).all()
    if not rows:
        return [], 0.0
    best_similarity = 1.0 - rows[0][2]
    chunks = [
        f"[Knowledge: {name}]\n\n{content}"
        for name, content, distance in rows
        if (1.0 - distance) >= similarity_threshold
    ]
    return chunks, best_similarity


async def get_knowledge_by_name(
    name: str,
    bot_id: str,
    client_id: str,
    is_cross_client: bool = False,
    is_cross_bot: bool = False
) -> str | None:
    async with async_session() as db:
        stmt = select(BotKnowledge).where(BotKnowledge.name == name)
        # If either flag is set, allow scope-wide (any client_id/bot_id)
        if not (is_cross_client or is_cross_bot):
            # Restrict to specific bot/client (and their "shared"/None scoping)
            stmt = stmt.where(
                (BotKnowledge.bot_id == bot_id) | (BotKnowledge.bot_id.is_(None)),
                (BotKnowledge.client_id == client_id) | (BotKnowledge.client_id.is_(None)),
            )
        # Prefer bot-specific > client-specific > fully shared
        stmt = stmt.order_by(
            BotKnowledge.bot_id.asc().nulls_last(),
            BotKnowledge.client_id.asc().nulls_last()
        ).limit(1)
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        return f"[Knowledge: {row.name}]\n\n{row.content}" if row else None


async def get_pinned_knowledge_docs(
    bot_id: str,
    client_id: str,
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
        doc = await get_knowledge_by_name(name, bot_id, client_id, is_cross_client=True, is_cross_bot=True)
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
    is_cross_client: bool = False,
    is_cross_bot: bool = False
) -> list[str]:
    async with async_session() as db:
        stmt = select(BotKnowledge.name)
        # If either flag is set, allow scope-wide (any client_id/bot_id)
        if not (is_cross_client or is_cross_bot):
            # Restrict to specific bot/client (and their "shared"/None scoping)
            stmt = stmt.where(
                (BotKnowledge.bot_id == bot_id) | (BotKnowledge.bot_id.is_(None)),
                (BotKnowledge.client_id == client_id) | (BotKnowledge.client_id.is_(None)),
            )
        # Prefer bot-specific > client-specific > fully shared
        stmt = stmt.order_by(
            BotKnowledge.bot_id.asc().nulls_last(),
            BotKnowledge.client_id.asc().nulls_last()
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [row.name for row in rows]
