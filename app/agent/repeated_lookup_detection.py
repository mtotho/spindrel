"""Detect repeated search queries across agent runs and suggest skill creation."""

import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Simple per-bot cache: bot_id -> (monotonic_time, result_list)
# Avoids hitting the DB on every single message.
_cache: dict[str, tuple[float, list[str]]] = {}
_CACHE_TTL = 3600  # 1 hour — repeated lookups don't change fast

# Tools whose `arguments["query"]` field is used for repeated-lookup tracking.
# Excludes web_search (too noisy/generic) and get_memory_file (uses "name" not "query").
_TRACKED_TOOLS = ["search_memory", "search_channel_workspace", "search_channel_archive"]


async def find_repeated_lookups(
    bot_id: str,
    correlation_id: str | None = None,
    min_runs: int = 3,
    window_days: int = 14,
) -> list[str]:
    """Return search queries the bot has repeated across multiple agent runs.

    Queries the tool_calls table for search_memory, search_channel_workspace,
    and search_channel_archive calls, groups by normalized query text, and
    returns queries that appear in >= min_runs distinct correlation_ids
    (agent runs) within the lookback window.

    Results are cached for 1 hour per bot to avoid hitting the DB on
    every message.
    """
    # Check cache first
    cached = _cache.get(bot_id)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[1]

    try:
        from sqlalchemy import func, select, text
        from app.db.engine import async_session
        from app.db.models import ToolCall

        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        async with async_session() as db:
            query_expr = func.lower(func.trim(
                ToolCall.arguments["query"].as_string()
            ))
            stmt = (
                select(
                    query_expr.label("query_text"),
                    func.count(func.distinct(ToolCall.correlation_id)).label("run_count"),
                )
                .where(
                    ToolCall.tool_name.in_(_TRACKED_TOOLS),
                    ToolCall.bot_id == bot_id,
                    ToolCall.created_at >= cutoff,
                    ToolCall.arguments["query"].as_string().isnot(None),
                    ToolCall.correlation_id.isnot(None),
                )
                .group_by(query_expr)
                .having(func.count(func.distinct(ToolCall.correlation_id)) >= min_runs)
                .order_by(text("run_count DESC"))
                .limit(5)
            )
            # Exclude current agent run so we only detect historical patterns
            if correlation_id:
                import uuid as _uuid
                try:
                    cid = _uuid.UUID(str(correlation_id))
                    stmt = stmt.where(ToolCall.correlation_id != cid)
                except (ValueError, AttributeError):
                    pass

            rows = (await db.execute(stmt)).all()

        result = [r.query_text for r in rows if r.query_text]
        _cache[bot_id] = (time.monotonic(), result)
        return result

    except Exception:
        logger.debug("Repeated lookup detection failed (non-blocking)", exc_info=True)
        return []
