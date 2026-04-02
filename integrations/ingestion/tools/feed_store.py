"""Bot tool to query ingestion feed stores (quarantine, stats, recent items)."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from integrations import _register as reg
from integrations.ingestion.store import IngestionStore

logger = logging.getLogger(__name__)

_INGESTION_DIR = os.path.expanduser("~/.agent-workspaces/.ingestion")


def _discover_stores() -> dict[str, Path]:
    """Scan the ingestion directory for *.db files. Returns {name: path}."""
    base = Path(_INGESTION_DIR)
    if not base.is_dir():
        return {}
    return {p.stem: p for p in sorted(base.glob("*.db"))}


def _open_readonly(db_path: Path) -> IngestionStore:
    """Open a store in read-only mode (uses file URI with mode=ro)."""
    uri = f"file:{db_path}?mode=ro"
    store = object.__new__(IngestionStore)
    store.db_path = db_path
    store._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    store._conn.row_factory = sqlite3.Row
    return store


@reg.register({"type": "function", "function": {
    "name": "query_feed_store",
    "description": (
        "Query ingestion feed stores for stats, recent items, quarantine entries, "
        "and discovered feed sources. Each content feed (gmail, rss, etc.) has its "
        "own SQLite store. Actions: stats, recent, quarantine, sources."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["stats", "recent", "quarantine", "sources"],
                "description": (
                    "stats — aggregate counts (total processed, quarantined, 24h activity, last cursor). "
                    "recent — list recently passed items from audit log. "
                    "quarantine — list quarantined items with risk level, flags, and reason. "
                    "sources — list all discovered feed stores and their sources."
                ),
            },
            "store": {
                "type": "string",
                "description": "Feed store name (e.g. 'gmail', 'rss'). Required for stats/recent/quarantine. Omit for sources action.",
            },
            "source": {
                "type": "string",
                "description": "Filter by source within a store (optional). If omitted, returns data for all sources in the store.",
            },
            "limit": {
                "type": "integer",
                "description": "Max items to return for recent/quarantine actions. Default 20.",
            },
        },
        "required": ["action"],
    },
}})
async def query_feed_store(
    action: str,
    store: str | None = None,
    source: str | None = None,
    limit: int = 20,
) -> str:
    """Query ingestion feed stores."""
    if action == "sources":
        return _handle_sources()

    if not store:
        available = _discover_stores()
        if not available:
            return "No feed stores found. Content feeds may not be configured yet."
        return f"Missing required 'store' parameter. Available stores: {', '.join(available.keys())}"

    stores = _discover_stores()
    if store not in stores:
        if not stores:
            return "No feed stores found. Content feeds may not be configured yet."
        return f"Store '{store}' not found. Available: {', '.join(stores.keys())}"

    db = _open_readonly(stores[store])
    try:
        if action == "stats":
            return json.dumps(db.get_feed_stats(source), indent=2)
        elif action == "recent":
            items = db.get_recent_items(source, limit=limit)
            if not items:
                return f"No recent passed items{f' for source {source}' if source else ''}."
            return json.dumps(items, indent=2)
        elif action == "quarantine":
            items = db.get_quarantine_items(source, limit=limit)
            if not items:
                return f"No quarantined items{f' for source {source}' if source else ''}."
            return json.dumps(items, indent=2)
        else:
            return f"Unknown action '{action}'. Use: stats, recent, quarantine, sources."
    finally:
        db.close()


def _handle_sources() -> str:
    """List all discovered feed stores and their sources."""
    stores = _discover_stores()
    if not stores:
        return "No feed stores found. Content feeds may not be configured yet."

    result = []
    for name, path in stores.items():
        try:
            db = _open_readonly(path)
            sources = db.list_sources()
            db.close()
            result.append({"store": name, "sources": sources, "path": str(path)})
        except Exception as e:
            result.append({"store": name, "error": str(e), "path": str(path)})

    return json.dumps(result, indent=2)
