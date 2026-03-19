import logging
from app.db.engine import async_session
from app.db.models import BotKnowledge
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


async def upsert_knowledge(
    name: str,
    content: str,
    bot_id: str,
    client_id: str,
    shared: bool = False,  # True = bot_id NULL (cross-bot)
) -> tuple[bool, str | None]:
    scoped_bot_id = None if shared else bot_id
    scoped_client_id = client_id  # always client-scoped for now
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
    return (True, None)


    


async def retrieve_knowledge(
    query: str,
    bot_id: str,
    client_id: str,
    cross_bot: bool = False,
    cross_client: bool = False,
    similarity_threshold: float = 0.45,
) -> list[str]:
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
    return [
        f"[Knowledge: {name}]\n\n{content}"
        for name, content, distance in rows
        if (1.0 - distance) >= similarity_threshold
    ]


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
