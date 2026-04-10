"""Capability (carapace) RAG index — embed and retrieve capabilities by semantic similarity.

Mirrors the tool RAG pattern in app/agent/tools.py but uses a separate
``capability_embeddings`` table with fields tuned for capabilities rather than tools.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agent.embeddings import embed_text as _embed_query
from app.config import settings
from app.db.engine import async_session
from app.db.models import CapabilityEmbedding

logger = logging.getLogger(__name__)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_embed_text(carapace: dict) -> str:
    """Build text for embedding from a carapace dict (registry format).

    Includes name, description, system_prompt_fragment excerpt, skills, and tags
    to give the embedding model enough signal for semantic matching.
    """
    parts: list[str] = []

    name = carapace.get("name") or carapace.get("id", "")
    parts.append(f"Capability: {name}")

    desc = (carapace.get("description") or "").strip()
    if desc:
        parts.append(f"Description: {desc}")

    fragment = (carapace.get("system_prompt_fragment") or "").strip()
    if fragment:
        # Take first 500 chars of the fragment — enough for embedding signal
        excerpt = fragment[:500]
        parts.append(f"Expertise: {excerpt}")

    tags = carapace.get("tags") or []
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")

    tools = carapace.get("local_tools") or []
    if tools:
        parts.append(f"Tools: {', '.join(tools)}")

    return "\n".join(parts)


async def _upsert_capability_row(
    *,
    carapace_id: str,
    name: str,
    embed_text_value: str,
    embedding: list[float],
    source_type: str,
    precomputed_hash: str | None = None,
) -> None:
    """Insert or update a capability embedding row."""
    h = precomputed_hash or content_hash(embed_text_value)
    stmt = (
        pg_insert(CapabilityEmbedding)
        .values(
            carapace_id=carapace_id,
            name=name,
            embed_text=embed_text_value,
            content_hash=h,
            embedding=embedding,
            source_type=source_type,
        )
        .on_conflict_do_update(
            index_elements=["carapace_id"],
            set_={
                "name": name,
                "embed_text": embed_text_value,
                "content_hash": h,
                "embedding": embedding,
                "source_type": source_type,
                "indexed_at": datetime.now(timezone.utc),
            },
            where=CapabilityEmbedding.content_hash != h,
        )
    )
    async with async_session() as db:
        await db.execute(stmt)
        await db.commit()


async def index_capabilities() -> None:
    """Bulk index all capabilities from the carapace registry.

    Skips unchanged capabilities (content_hash match) and removes stale rows.
    """
    from app.agent.carapaces import list_carapaces

    all_caps = list_carapaces()
    current_ids = {c["id"] for c in all_caps}

    # Fetch existing hashes
    async with async_session() as db:
        rows = (await db.execute(
            select(CapabilityEmbedding.carapace_id, CapabilityEmbedding.content_hash)
        )).all()
    existing_hashes = {row.carapace_id: row.content_hash for row in rows}

    # Remove stale capabilities no longer in registry
    stale_ids = set(existing_hashes) - current_ids
    if stale_ids:
        async with async_session() as db:
            await db.execute(
                delete(CapabilityEmbedding).where(
                    CapabilityEmbedding.carapace_id.in_(stale_ids)
                )
            )
            await db.commit()
        logger.info("Removed %d stale capability embedding(s): %s", len(stale_ids), sorted(stale_ids))

    skipped = 0
    embedded = 0
    embed_disabled = False
    for cap in all_caps:
        cid = cap["id"]
        embed_txt = build_embed_text(cap)
        h = content_hash(embed_txt)
        if existing_hashes.get(cid) == h:
            skipped += 1
            continue
        if embed_disabled:
            continue
        try:
            emb = await _embed_query(embed_txt)
        except Exception as exc:
            logger.exception("Failed to embed capability %s", cid)
            exc_str = str(exc).lower()
            if "insufficient_quota" in exc_str or "invalid_api_key" in exc_str:
                logger.warning("Embedding provider quota/auth error — skipping remaining capability embeddings")
                embed_disabled = True
            continue
        try:
            await _upsert_capability_row(
                carapace_id=cid,
                name=cap.get("name") or cid,
                embed_text_value=embed_txt,
                embedding=emb,
                source_type=cap.get("source_type", "manual"),
                precomputed_hash=h,
            )
            embedded += 1
        except Exception:
            logger.exception("Failed to persist capability embedding for %s", cid)

    logger.info(
        "Capability index: %d embedded, %d unchanged, %d stale removed",
        embedded, skipped, len(stale_ids),
    )


async def reindex_capability(carapace_id: str) -> None:
    """Re-embed a single capability. Call after create/update."""
    from app.agent.carapaces import get_carapace

    cap = get_carapace(carapace_id)
    if cap is None:
        # Capability was deleted — remove from index
        async with async_session() as db:
            await db.execute(
                delete(CapabilityEmbedding).where(
                    CapabilityEmbedding.carapace_id == carapace_id
                )
            )
            await db.commit()
        return

    embed_txt = build_embed_text(cap)
    try:
        emb = await _embed_query(embed_txt)
    except Exception:
        logger.exception("Failed to embed capability %s for reindex", carapace_id)
        return

    try:
        await _upsert_capability_row(
            carapace_id=carapace_id,
            name=cap.get("name") or carapace_id,
            embed_text_value=embed_txt,
            embedding=emb,
            source_type=cap.get("source_type", "manual"),
        )
    except Exception:
        logger.exception("Failed to persist reindexed capability %s", carapace_id)


async def retrieve_capabilities(
    query: str,
    excluded_ids: set[str] | None = None,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """Retrieve capabilities by semantic similarity to user query.

    Returns (list_of_dicts, best_similarity) where each dict has:
    id, name, description, similarity.

    excluded_ids: carapace IDs to skip (already active, disabled, etc.)
    """
    top_k = settings.CAPABILITY_RETRIEVAL_TOP_K if top_k is None else top_k
    threshold = settings.CAPABILITY_RETRIEVAL_THRESHOLD if threshold is None else threshold
    excluded_ids = excluded_ids or set()

    try:
        query_embedding = await _embed_query(query)
    except Exception:
        logger.exception("Failed to embed query for capability retrieval")
        return [], 0.0

    from app.agent.vector_ops import halfvec_cosine_distance
    distance_expr = halfvec_cosine_distance(CapabilityEmbedding.embedding, query_embedding)

    stmt = (
        select(
            CapabilityEmbedding.carapace_id,
            CapabilityEmbedding.name,
            distance_expr.label("distance"),
        )
        .order_by(distance_expr)
        .limit(top_k + len(excluded_ids))  # fetch extra to account for exclusions
    )

    try:
        async with async_session() as db:
            rows = (await db.execute(stmt)).all()
    except Exception:
        logger.exception("Capability retrieval query failed")
        return [], 0.0

    # Load full carapace data for returned results
    from app.agent.carapaces import get_carapace

    results: list[dict[str, Any]] = []
    best_sim = 0.0
    for row in rows:
        cid = row.carapace_id
        if cid in excluded_ids:
            continue
        similarity = 1.0 - row.distance
        if similarity < threshold:
            continue
        if similarity > best_sim:
            best_sim = similarity

        cap = get_carapace(cid)
        results.append({
            "id": cid,
            "name": row.name,
            "description": (cap.get("description") or "") if cap else "",
            "similarity": round(similarity, 4),
        })
        if len(results) >= top_k:
            break

    return results, best_sim
