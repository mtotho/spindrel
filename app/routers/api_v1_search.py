"""Core search API — /api/v1/search/

Agnostic search endpoints (not MC-specific). Any integration or UI page can use these.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import require_scopes, verify_auth_or_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MemorySearchRequest(BaseModel):
    query: str
    bot_ids: Optional[list[str]] = None
    top_k: int = 10


class MemorySearchResult(BaseModel):
    file_path: str
    content: str
    score: float
    bot_id: str
    bot_name: str


class MemorySearchResponse(BaseModel):
    results: list[MemorySearchResult]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/memory",
    response_model=MemorySearchResponse,
    dependencies=[Depends(require_scopes("bots:read"))],
)
async def search_memory(
    body: MemorySearchRequest,
    auth=Depends(verify_auth_or_user),
):
    """Semantic search over bot memory files using hybrid vector + BM25."""
    from pathlib import Path

    from app.agent.bots import get_bot, list_bots
    from app.services.memory_scheme import get_memory_index_prefix
    from app.services.memory_search import hybrid_memory_search
    from app.services.workspace_indexing import get_all_roots, resolve_indexing

    if not body.query.strip():
        return MemorySearchResponse(results=[])

    # Resolve which bots to search
    if body.bot_ids:
        bots = []
        for bid in body.bot_ids:
            try:
                bots.append(get_bot(bid))
            except Exception:
                logger.debug("Bot %s not found for memory search", bid)
    else:
        bots = [b for b in list_bots() if b.memory_scheme == "workspace-files"]

    all_results: list[MemorySearchResult] = []

    for bot in bots:
        if bot.memory_scheme != "workspace-files":
            continue
        try:
            roots = [str(Path(r).resolve()) for r in get_all_roots(bot)]
            prefix = get_memory_index_prefix(bot)
            _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
            embedding_model = _resolved["embedding_model"]
            hits = await hybrid_memory_search(
                body.query,
                bot.id,
                roots=roots,
                memory_prefix=prefix,
                embedding_model=embedding_model,
                top_k=body.top_k,
            )
            for h in hits:
                all_results.append(MemorySearchResult(
                    file_path=h.file_path,
                    content=h.content,
                    score=h.score,
                    bot_id=bot.id,
                    bot_name=bot.name,
                ))
        except Exception:
            logger.warning("Memory search failed for bot %s", bot.id, exc_info=True)

    # Sort by score descending, limit to top_k
    all_results.sort(key=lambda r: r.score, reverse=True)
    return MemorySearchResponse(results=all_results[: body.top_k])
