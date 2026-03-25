"""Embed tool schemas and retrieve a relevant subset per user message (tool RAG)."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agent.embeddings import embed_text as _embed_query
from app.config import settings
from app.db.engine import async_session
from app.db.models import ToolEmbedding

logger = logging.getLogger(__name__)


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


async def _upsert_tool_row(
    *,
    tool_key: str,
    tool_name: str,
    server_name: str | None,
    source_dir: str | None,
    source_integration: str | None = None,
    source_file: str | None = None,
    schema: dict[str, Any],
    embed_text_value: str,
    embedding: list[float],
) -> None:
    h = content_hash(embed_text_value)
    stmt = (
        pg_insert(ToolEmbedding)
        .values(
            tool_key=tool_key,
            tool_name=tool_name,
            server_name=server_name,
            source_dir=source_dir,
            source_integration=source_integration,
            source_file=source_file,
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

    current_tools = list(iter_registered_tools())
    current_keys = {tool_key_for(None, tool_name) for tool_name, _, _, _, _ in current_tools}

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
    for tool_name, _, _, source_integration, source_file in current_tools:
        tkey = tool_key_for(None, tool_name)
        if tkey in existing_hashes:
            metadata_updates.append((tkey, source_integration, source_file))
    if metadata_updates:
        async with async_session() as db:
            for tkey, si, sf in metadata_updates:
                await db.execute(
                    update(ToolEmbedding)
                    .where(ToolEmbedding.tool_key == tkey)
                    .values(source_integration=si, source_file=sf)
                )
            await db.commit()

    skipped = 0
    for tool_name, schema, source_dir, source_integration, source_file in current_tools:
        tkey = tool_key_for(None, tool_name)
        embed_txt = build_embed_text(schema, tool_name, None)
        h = content_hash(embed_txt)
        if existing_hashes.get(tkey) == h:
            skipped += 1
            continue
        try:
            emb = await _embed_query(embed_txt)
        except Exception:
            logger.exception("Failed to embed local tool %s", tool_name)
            continue
        try:
            await _upsert_tool_row(
                tool_key=tkey,
                tool_name=tool_name,
                server_name=None,
                source_dir=source_dir,
                source_integration=source_integration,
                source_file=source_file,
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
        try:
            emb = await _embed_query(embed_txt)
        except Exception:
            logger.exception("Failed to embed MCP tool %s/%s", server_name, tool_name)
            continue
        try:
            await _upsert_tool_row(
                tool_key=tkey,
                tool_name=tool_name,
                server_name=server_name,
                source_dir=None,
                schema=sch,
                embed_text_value=embed_txt,
                embedding=emb,
            )
        except Exception:
            logger.exception("Failed to persist MCP tool %s/%s", server_name, tool_name)
    if skipped:
        logger.info("Skipped %d unchanged MCP tool(s) for '%s'", skipped, server_name)


async def retrieve_tools(
    query: str,
    local_tool_names: list[str],
    mcp_server_names: list[str],
    *,
    top_k: int | None = None,
    threshold: float | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """Return (tool_dicts, best_similarity) for local + MCP tools above threshold."""
    top_k = settings.TOOL_RETRIEVAL_TOP_K if top_k is None else top_k
    threshold = settings.TOOL_RETRIEVAL_THRESHOLD if threshold is None else threshold

    filters: list[Any] = []
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

    distance_expr = ToolEmbedding.embedding.cosine_distance(query_embedding)

    stmt = (
        select(ToolEmbedding.schema_, distance_expr.label("distance"))
        .where(or_(*filters))
        .order_by(distance_expr)
        .limit(top_k)
    )

    try:
        async with async_session() as db:
            result = await db.execute(stmt)
            rows = result.all()
    except Exception:
        logger.exception("Tool retrieval query failed")
        return [], 0.0, []

    if not rows:
        return [], 0.0, []

    best_sim = 1.0 - rows[0][1]
    logger.info(
        "Tool retrieval: best_similarity=%.3f threshold=%.3f query=%s...",
        best_sim,
        threshold,
        query[:60],
    )

    out: list[dict[str, Any]] = []
    top_candidates: list[dict[str, Any]] = []  # top 5 regardless of threshold, for diagnostics
    for schema_obj, distance in rows:
        similarity = 1.0 - distance
        if isinstance(schema_obj, dict) and len(top_candidates) < 5:
            top_candidates.append({"name": schema_obj.get("function", {}).get("name", "?"), "sim": round(similarity, 4)})
        if similarity < threshold:
            continue
        if isinstance(schema_obj, dict):
            out.append(schema_obj)
    return out, best_sim, top_candidates


async def warm_mcp_tool_index_for_all_bots() -> None:
    """Fetch and index MCP tools for every server referenced by a loaded bot."""
    from app.agent.bots import list_bots
    from app.tools.mcp import fetch_mcp_tools

    servers: set[str] = set()
    for bot in list_bots():
        servers.update(bot.mcp_servers)

    for name in sorted(servers):
        tools = await fetch_mcp_tools([name])
        await index_mcp_tools(name, tools)


async def validate_pinned_tools() -> None:
    """Log a warning if a bot lists a pinned tool that is not in its allowed tool set."""
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
                logger.warning(
                    "Bot %r: pinned_tools %r is not in local_tools, client_tools, or MCP tools for this bot",
                    bot.id,
                    pin,
                )
