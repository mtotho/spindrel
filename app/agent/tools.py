"""Embed tool schemas and retrieve a relevant subset per user message (tool RAG)."""

from __future__ import annotations

import hashlib
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agent.embeddings import embed_text as _embed_query
from app.config import settings
from app.db.engine import async_session
from app.db.models import ToolEmbedding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool retrieval cache — avoids embedding API call + pgvector query per request
# ---------------------------------------------------------------------------
_TOOL_CACHE_TTL = 300  # 5 minutes
_tool_cache: dict[str, tuple[float, list[dict[str, Any]], float, list[dict[str, Any]]]] = {}


def _cache_key(
    query: str,
    local_tool_names: list[str],
    mcp_server_names: list[str],
    top_k: int,
    threshold: float,
    respect_exposure: bool = False,
) -> str:
    """Build a deterministic cache key from retrieval parameters."""
    parts = [
        query,
        ",".join(sorted(local_tool_names)),
        ",".join(sorted(mcp_server_names)),
        str(top_k),
        f"{threshold:.4f}",
        "exposure" if respect_exposure else "",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def invalidate_tool_cache() -> None:
    """Clear the tool retrieval cache (call after tool index changes)."""
    _tool_cache.clear()


def tool_key_for(server_name: str | None, tool_name: str) -> str:
    if server_name:
        return f"mcp:{server_name}:{tool_name}"
    return f"local:{tool_name}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_embed_text(openai_tool: dict[str, Any], tool_name: str, server_name: str | None) -> str:
    fn = openai_tool.get("function") or {}
    name = fn.get("name") or tool_name
    desc = (fn.get("description") or "").strip()
    params = fn.get("parameters") or {}
    props = params.get("properties") or {}
    req = set(params.get("required") or [])
    parts: list[str] = [f"Tool: {name}"]
    if server_name:
        parts.append(f"Server: {server_name}")
    parts.append(f"Description: {desc or '(no description)'}")

    param_bits: list[str] = []
    if isinstance(props, dict):
        for pname, pschema in props.items():
            if not isinstance(pschema, dict):
                continue
            ptype = pschema.get("type", "string")
            req_mark = "required" if pname in req else "optional"
            pdesc = (pschema.get("description") or "").strip()
            param_bits.append(f"{pname} ({req_mark}, {ptype}){(': ' + pdesc) if pdesc else ''}")

    if param_bits:
        parts.append("Parameters: " + " | ".join(param_bits))

    return "\n".join(parts)


def _metadata_embed_text(metadata: dict[str, Any] | None) -> str:
    if not isinstance(metadata, dict) or not metadata:
        return ""
    parts: list[str] = []
    for key in ("domains", "intent_tags", "capabilities", "exposure", "surface"):
        value = metadata.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            rendered = ", ".join(str(v) for v in value if v)
        else:
            rendered = str(value)
        if rendered:
            parts.append(f"{key}: {rendered}")
    return "\n".join(parts)


def _tool_exposure(metadata: dict[str, Any] | None) -> str:
    if not isinstance(metadata, dict):
        return "ambient"
    value = metadata.get("exposure")
    return str(value or "ambient").strip().lower()


async def _upsert_tool_row(
    *,
    tool_key: str,
    tool_name: str,
    server_name: str | None,
    source_dir: str | None,
    source_integration: str | None = None,
    source_file: str | None = None,
    metadata: dict[str, Any] | None = None,
    schema: dict[str, Any],
    embed_text_value: str,
    embedding: list[float] | None,
) -> None:
    h = content_hash(embed_text_value)
    # When embedding failed, store a sentinel hash so the next index pass
    # treats the row as stale and retries the embed. The tool still
    # appears in the Tool Pool / bot editor (rows are selected regardless
    # of embedding state) so it's usable via manual enrollment.
    if embedding is None:
        h = f"noembed:{h}"
    stmt = (
        pg_insert(ToolEmbedding)
        .values(
            tool_key=tool_key,
            tool_name=tool_name,
            server_name=server_name,
            source_dir=source_dir,
            source_integration=source_integration,
            source_file=source_file,
            metadata=metadata or {},
            embed_text=embed_text_value,
            content_hash=h,
            embedding=embedding,
            **{"schema": schema},  # "schema" is the DB column name; schema_ is the ORM attr
        )
        .on_conflict_do_update(
            index_elements=["tool_key"],
            set_={
                "tool_name": tool_name,
                "server_name": server_name,
                "source_dir": source_dir,
                "source_integration": source_integration,
                "source_file": source_file,
                "metadata": metadata or {},
                "schema": schema,
                "embed_text": embed_text_value,
                "content_hash": h,
                "embedding": embedding,
                "indexed_at": datetime.now(timezone.utc),
            },
            where=ToolEmbedding.content_hash != h,
        )
    )
    async with async_session() as db:
        await db.execute(stmt)
        await db.commit()


async def index_local_tools() -> None:
    from app.tools.registry import iter_registered_tools

    invalidate_tool_cache()
    current_tools = list(iter_registered_tools())
    current_keys = {tool_key_for(None, tool_name) for tool_name, _, _, _, _, _ in current_tools}

    # Fetch existing hashes in one query to avoid re-embedding unchanged tools
    async with async_session() as db:
        rows = (await db.execute(
            select(ToolEmbedding.tool_key, ToolEmbedding.content_hash)
            .where(ToolEmbedding.server_name.is_(None))
        )).all()
    existing_hashes = {row.tool_key: row.content_hash for row in rows}

    # Remove stale local tools no longer registered
    stale_keys = set(existing_hashes) - current_keys
    if stale_keys:
        async with async_session() as db:
            await db.execute(
                delete(ToolEmbedding).where(ToolEmbedding.tool_key.in_(stale_keys))
            )
            await db.commit()
        logger.info("Removed %d stale local tool embedding(s): %s", len(stale_keys), sorted(stale_keys))

    # Update source metadata (source_file, source_integration) for all existing tools
    # regardless of content hash — these columns are not part of the hash.
    metadata_updates = []
    for tool_name, _, _, source_integration, source_file, metadata in current_tools:
        tkey = tool_key_for(None, tool_name)
        if tkey in existing_hashes:
            metadata_updates.append((tkey, source_integration, source_file, metadata or {}))
    if metadata_updates:
        async with async_session() as db:
            for tkey, si, sf, metadata in metadata_updates:
                await db.execute(
                    update(ToolEmbedding)
                    .where(ToolEmbedding.tool_key == tkey)
                    .values(source_integration=si, source_file=sf, metadata_=metadata)
                )
            await db.commit()

    skipped = 0
    embed_disabled = False
    for tool_name, schema, source_dir, source_integration, source_file, metadata in current_tools:
        tkey = tool_key_for(None, tool_name)
        metadata = metadata or {}
        embed_txt = build_embed_text(schema, tool_name, None)
        metadata_txt = _metadata_embed_text(metadata)
        if metadata_txt:
            embed_txt = f"{embed_txt}\nMetadata:\n{metadata_txt}"
        h = content_hash(embed_txt)
        if existing_hashes.get(tkey) == h:
            skipped += 1
            continue
        emb: list[float] | None = None
        if not embed_disabled:
            try:
                emb = await _embed_query(embed_txt)
            except Exception as exc:
                logger.exception("Failed to embed local tool %s", tool_name)
                # Circuit breaker: if quota exhausted or auth error, skip
                # remaining embed calls but still persist the rows below so
                # tools show up in the bot editor / Tool Pool UI. RAG similarity
                # search won't match them until a later re-index, but the
                # tools remain usable via manual enrollment.
                exc_str = str(exc).lower()
                if "insufficient_quota" in exc_str or "invalid_api_key" in exc_str:
                    logger.warning("Embedding provider quota/auth error — skipping remaining tool embeddings")
                    embed_disabled = True
        try:
            await _upsert_tool_row(
                tool_key=tkey,
                tool_name=tool_name,
                server_name=None,
                source_dir=source_dir,
                source_integration=source_integration,
                source_file=source_file,
                metadata=metadata,
                schema=schema,
                embed_text_value=embed_txt,
                embedding=emb,
            )
        except Exception:
            logger.exception("Failed to persist embedding for local tool %s", tool_name)
    if skipped:
        logger.info("Skipped %d unchanged local tool(s)", skipped)


async def index_mcp_tools(server_name: str, schemas: list[dict[str, Any]]) -> None:
    """Replace index rows for this MCP server; embed new/changed tools only."""
    invalidate_tool_cache()
    current_names = [s["function"]["name"] for s in schemas if s.get("function", {}).get("name")]

    async with async_session() as db:
        if current_names:
            await db.execute(
                delete(ToolEmbedding).where(
                    ToolEmbedding.server_name == server_name,
                    ToolEmbedding.tool_name.not_in(current_names),
                )
            )
        else:
            await db.execute(delete(ToolEmbedding).where(ToolEmbedding.server_name == server_name))
        await db.commit()

        # Fetch existing hashes to skip unchanged tools
        rows = (await db.execute(
            select(ToolEmbedding.tool_key, ToolEmbedding.content_hash)
            .where(ToolEmbedding.server_name == server_name)
        )).all()
    existing_hashes = {row.tool_key: row.content_hash for row in rows}

    skipped = 0
    embed_disabled = False
    for sch in schemas:
        fn = sch.get("function") or {}
        tool_name = fn.get("name")
        if not tool_name:
            continue
        tkey = tool_key_for(server_name, tool_name)
        embed_txt = build_embed_text(sch, tool_name, server_name)
        h = content_hash(embed_txt)
        if existing_hashes.get(tkey) == h:
            skipped += 1
            continue
        if embed_disabled:
            continue
        try:
            emb = await _embed_query(embed_txt)
        except Exception as exc:
            logger.exception("Failed to embed MCP tool %s/%s", server_name, tool_name)
            exc_str = str(exc).lower()
            if "insufficient_quota" in exc_str or "invalid_api_key" in exc_str:
                logger.warning("Embedding provider quota/auth error — skipping remaining MCP tool embeddings")
                embed_disabled = True
            continue
        try:
            await _upsert_tool_row(
                tool_key=tkey,
                tool_name=tool_name,
                server_name=server_name,
                source_dir=None,
                metadata={},
                schema=sch,
                embed_text_value=embed_txt,
                embedding=emb,
            )
        except Exception:
            logger.exception("Failed to persist MCP tool %s/%s", server_name, tool_name)
    if skipped:
        logger.info("Skipped %d unchanged MCP tool(s) for '%s'", skipped, server_name)


async def remove_integration_embeddings(integration_id: str) -> int:
    """Delete ToolEmbedding rows for an integration and invalidate cache. Returns count deleted."""
    invalidate_tool_cache()
    async with async_session() as db:
        result = await db.execute(
            delete(ToolEmbedding).where(ToolEmbedding.source_integration == integration_id)
        )
        await db.commit()
        count = result.rowcount
    if count:
        logger.info("Removed %d tool embedding(s) for integration %s", count, integration_id)
    return count


async def _bm25_tool_search(
    db,
    query: str,
    local_tool_names: list[str],
    mcp_server_names: list[str],
    discover_all: bool,
    limit: int,
) -> list[tuple[dict, str, float, dict]]:
    """Run BM25 full-text search on tool_embeddings."""
    from sqlalchemy import text as sa_text

    try:
        # Build WHERE clause matching the same filter logic as the vector query
        filter_parts: list[str] = []
        params: dict[str, Any] = {"q": query, "lim": limit}

        if discover_all:
            filter_parts.append("server_name IS NULL")
            if mcp_server_names:
                params["mcp_servers"] = list(mcp_server_names)
                filter_parts.append("server_name = ANY(:mcp_servers)")
        else:
            if local_tool_names:
                params["local_names"] = list(local_tool_names)
                filter_parts.append("(server_name IS NULL AND tool_name = ANY(:local_names))")
            if mcp_server_names:
                params["mcp_servers"] = list(mcp_server_names)
                filter_parts.append("server_name = ANY(:mcp_servers)")

        if not filter_parts:
            return []

        where_clause = " OR ".join(filter_parts)
        # `websearch_to_tsquery` uses OR semantics (each term contributes
        # independently to ts_rank) so a single high-signal token like
        # "weather" can rescue a retrieval that conversational noise
        # ("rolland", "hte", "test") would otherwise sink under the
        # AND-by-default behavior of `plainto_tsquery`.
        sql = sa_text(f"""
            SELECT "schema", tool_name,
                   ts_rank(to_tsvector('english', embed_text), websearch_to_tsquery('english', :q)) AS rank
                   , metadata
            FROM tool_embeddings
            WHERE ({where_clause})
              AND to_tsvector('english', embed_text) @@ websearch_to_tsquery('english', :q)
            ORDER BY rank DESC
            LIMIT :lim
        """)
        result = await db.execute(sql, params)
        return [(row[0], row[1], float(row[2]), row[3] or {}) for row in result.all()]
    except Exception:
        logger.debug("BM25 tool search failed, falling back to vector-only", exc_info=True)
        return []


def _vector_only_tool_results(
    rows: list,
    threshold: float,
    declared_names: set[str],
    discover_threshold: float,
    discover_all: bool,
    respect_exposure: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Process cosine-only results with threshold filtering."""
    out: list[dict[str, Any]] = []
    top_candidates: list[dict[str, Any]] = []
    for schema_obj, tool_name, distance, metadata in rows:
        similarity = 1.0 - distance
        if not math.isfinite(similarity):
            similarity = 0.0
        if isinstance(schema_obj, dict) and len(top_candidates) < 5:
            top_candidates.append({"name": schema_obj.get("function", {}).get("name", "?"), "sim": round(similarity, 4)})
        _eff_threshold = threshold if (not discover_all or tool_name in declared_names) else discover_threshold
        if similarity < _eff_threshold:
            continue
        if (
            respect_exposure
            and discover_all
            and tool_name not in declared_names
            and _tool_exposure(metadata) == "explicit"
        ):
            continue
        if isinstance(schema_obj, dict):
            out.append(schema_obj)
    return out, top_candidates


def _fuse_tool_results(
    vector_rows: list,
    bm25_rows: list[tuple[dict, str, float, dict]],
    threshold: float,
    declared_names: set[str],
    discover_threshold: float,
    discover_all: bool,
    respect_exposure: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fuse vector + BM25 tool results using Reciprocal Rank Fusion."""
    from app.agent.hybrid_search import reciprocal_rank_fusion

    k = settings.HYBRID_SEARCH_RRF_K

    # Build ranked lists keyed by tool_name for dedup
    vector_list = [(tool_name,) for _, tool_name, _, _ in vector_rows]
    bm25_list = [(tool_name,) for _, tool_name, _, _ in bm25_rows]

    fused = reciprocal_rank_fusion(vector_list, bm25_list, k=k)

    # Build lookups
    vector_sims: dict[str, float] = {}
    vector_schemas: dict[str, dict] = {}
    metadata_by_name: dict[str, dict] = {}
    for schema_obj, tool_name, distance, metadata in vector_rows:
        if tool_name not in vector_sims:
            sim = 1.0 - distance
            vector_sims[tool_name] = sim if math.isfinite(sim) else 0.0
            vector_schemas[tool_name] = schema_obj
            metadata_by_name[tool_name] = metadata or {}
    bm25_names = {tool_name for _, tool_name, _, _ in bm25_rows}
    bm25_schemas: dict[str, dict] = {}
    for schema_obj, tool_name, _, metadata in bm25_rows:
        if tool_name not in bm25_schemas:
            bm25_schemas[tool_name] = schema_obj
            metadata_by_name.setdefault(tool_name, metadata or {})

    out: list[dict[str, Any]] = []
    top_candidates: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for item, rrf_score in fused:
        tool_name = item[0]
        if tool_name in seen_names:
            continue

        schema_obj = vector_schemas.get(tool_name) or bm25_schemas.get(tool_name)
        if not isinstance(schema_obj, dict):
            continue

        vec_sim = vector_sims.get(tool_name)
        _eff_threshold = threshold if (not discover_all or tool_name in declared_names) else discover_threshold
        if (
            respect_exposure
            and discover_all
            and tool_name not in declared_names
            and _tool_exposure(metadata_by_name.get(tool_name)) == "explicit"
        ):
            continue

        if len(top_candidates) < 5:
            _display_sim = vec_sim if vec_sim is not None else 0.0
            top_candidates.append({"name": schema_obj.get("function", {}).get("name", "?"), "sim": round(_display_sim, 4)})

        # Include if: above vector threshold, OR has BM25 match (keyword relevance)
        if vec_sim is not None and vec_sim >= _eff_threshold:
            out.append(schema_obj)
            seen_names.add(tool_name)
        elif tool_name in bm25_names:
            # BM25 matched — include even if below vector threshold
            out.append(schema_obj)
            seen_names.add(tool_name)

    logger.info("Tool hybrid search: %d vector + %d bm25 → %d fused results", len(vector_rows), len(bm25_rows), len(out))
    return out, top_candidates


async def retrieve_tools(
    query: str,
    local_tool_names: list[str],
    mcp_server_names: list[str],
    *,
    top_k: int | None = None,
    threshold: float | None = None,
    discover_all: bool = False,
    respect_exposure: bool = False,
) -> tuple[list[dict[str, Any]], float, list[dict[str, Any]]]:
    """Return (tool_dicts, best_similarity, top_candidates) for local + MCP tools above threshold.

    Results are cached for 5 minutes keyed on (query, tool_names, server_names, top_k, threshold)
    to avoid redundant embedding API calls and pgvector queries.

    When discover_all=True, searches the full tool pool (all indexed local tools)
    in addition to the declared tools, surfacing relevant tools the bot didn't
    explicitly declare. Declared tools are filtered by threshold; discovered
    tools use a stricter threshold (threshold + 0.1) to avoid noise.
    """
    top_k = settings.TOOL_RETRIEVAL_TOP_K if top_k is None else top_k
    threshold = settings.TOOL_RETRIEVAL_THRESHOLD if threshold is None else threshold

    # Check cache
    _discover_tag = "d" if discover_all else ""
    ck = _cache_key(query, local_tool_names, mcp_server_names, top_k, threshold, respect_exposure) + _discover_tag
    cached = _tool_cache.get(ck)
    if cached is not None:
        ts, c_out, c_sim, c_cand = cached
        if time.monotonic() - ts < _TOOL_CACHE_TTL:
            logger.debug("Tool retrieval cache hit for query=%s...", query[:40])
            return c_out, c_sim, c_cand
        else:
            del _tool_cache[ck]

    filters: list[Any] = []
    if discover_all:
        # Search entire local tool pool + declared MCP servers
        _local_filter = ToolEmbedding.server_name.is_(None)
        filters.append(_local_filter)
        if mcp_server_names:
            filters.append(ToolEmbedding.server_name.in_(mcp_server_names))
    else:
        if local_tool_names:
            filters.append(
                and_(ToolEmbedding.server_name.is_(None), ToolEmbedding.tool_name.in_(local_tool_names))
            )
        if mcp_server_names:
            filters.append(ToolEmbedding.server_name.in_(mcp_server_names))

    if not filters:
        return [], 0.0, []

    try:
        query_embedding = await _embed_query(query)
    except Exception:
        logger.exception("Failed to embed query for tool retrieval")
        return [], 0.0, []

    from app.agent.vector_ops import halfvec_cosine_distance
    distance_expr = halfvec_cosine_distance(ToolEmbedding.embedding, query_embedding)

    # Increase limit when discovering to get a wider pool
    _limit = top_k * 2 if discover_all else top_k
    stmt = (
        select(ToolEmbedding.schema_, ToolEmbedding.tool_name, distance_expr.label("distance"), ToolEmbedding.metadata_)
        .where(or_(*filters))
        .order_by(distance_expr)
        .limit(_limit)
    )

    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            rows = result.all()

            # Hybrid search: BM25 + RRF fusion (PostgreSQL only)
            bm25_rows: list[tuple[dict, str, float, dict]] = []
            if settings.HYBRID_SEARCH_ENABLED and rows:
                from app.agent.hybrid_search import is_postgres_dialect
                if is_postgres_dialect(db.bind):
                    bm25_rows = await _bm25_tool_search(
                        db, query, local_tool_names, mcp_server_names, discover_all, _limit,
                    )

    except Exception:
        logger.exception("Tool retrieval query failed")
        return [], 0.0, []

    if not rows:
        return [], 0.0, []

    best_sim = 1.0 - rows[0][2]
    logger.info(
        "Tool retrieval: best_similarity=%.3f threshold=%.3f discover=%s query=%s...",
        best_sim,
        threshold,
        discover_all,
        query[:60],
    )

    # When discovering, undeclared tools get a stricter threshold to avoid noise
    _declared_names = set(local_tool_names) if discover_all else set()
    _discover_threshold = min(threshold + 0.1, 0.65) if discover_all else threshold

    # Fuse vector + BM25 results if hybrid search produced results
    if bm25_rows:
        out, top_candidates = _fuse_tool_results(
            rows, bm25_rows, threshold, _declared_names, _discover_threshold, discover_all, respect_exposure,
        )
    else:
        out, top_candidates = _vector_only_tool_results(
            rows, threshold, _declared_names, _discover_threshold, discover_all, respect_exposure,
        )

    # Store in cache
    _tool_cache[ck] = (time.monotonic(), out, best_sim, top_candidates)

    # Evict stale entries periodically (every ~100 calls, scan and remove expired)
    if len(_tool_cache) > 200:
        now = time.monotonic()
        stale = [k for k, (ts, *_) in _tool_cache.items() if now - ts >= _TOOL_CACHE_TTL]
        for k in stale:
            del _tool_cache[k]

    return out, best_sim, top_candidates


async def warm_mcp_tool_index_for_all_bots() -> None:
    """Fetch and index MCP tools for every server referenced by a loaded bot."""
    from app.agent.bots import list_bots
    from app.tools.mcp import fetch_mcp_tools

    servers: set[str] = set()
    for bot in list_bots():
        servers.update(bot.mcp_servers)

    import asyncio

    async def _fetch_and_index(server: str) -> None:
        try:
            tools = await fetch_mcp_tools([server])
            await index_mcp_tools(server, tools)
        except Exception:
            logger.exception("Failed to warm MCP tool index for server '%s'", server)

    await asyncio.gather(*[_fetch_and_index(s) for s in sorted(servers)])


async def validate_pinned_tools() -> None:
    """Log pins that aren't also declared in local/client/MCP.

    Runtime honors pins regardless (see message_utils._all_tool_schemas_by_name),
    so this is informational — it highlights bots whose DB state drifted from
    the "pin ⊆ declared" invariant, not a functional problem.
    """
    from app.agent.bots import list_bots
    from app.tools.mcp import fetch_mcp_tools

    for bot in list_bots():
        if not bot.pinned_tools:
            continue
        mcp = await fetch_mcp_tools(bot.mcp_servers)
        mcp_names = {t["function"]["name"] for t in mcp}
        allowed = set(bot.local_tools) | set(bot.client_tools) | mcp_names
        for pin in bot.pinned_tools:
            if pin not in allowed:
                logger.info(
                    "Bot %r: pinned_tools entry %r not in declared local/client/MCP; "
                    "runtime will load it from the pin directly.",
                    bot.id,
                    pin,
                )
