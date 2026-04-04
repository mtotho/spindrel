"""Bot tool to query ingestion feed stores (quarantine, stats, recent items)."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from integrations import _register as reg
from integrations.ingestion.config import INGESTION_DB_DIR
from integrations.ingestion.store import IngestionStore

logger = logging.getLogger(__name__)


def _discover_stores() -> dict[str, Path]:
    """Scan the ingestion directory for *.db files. Returns {name: path}."""
    base = Path(INGESTION_DB_DIR)
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


def _open_readwrite(db_path: Path) -> IngestionStore:
    """Open a store in read-write mode."""
    return IngestionStore(db_path)


@reg.register({"type": "function", "function": {
    "name": "query_feed_store",
    "description": (
        "Query ingestion feed stores for stats, recent items, quarantine entries, "
        "discovered feed sources, and reprocess quarantined items. Each content feed "
        "(gmail, rss, etc.) has its own SQLite store. "
        "Actions: stats, recent, quarantine, sources, reprocess."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["stats", "recent", "quarantine", "sources", "reprocess"],
                "description": (
                    "stats — aggregate counts (total processed, quarantined, 24h activity, last cursor). "
                    "recent — list recently passed items from audit log. "
                    "quarantine — list quarantined items with risk level, flags, and reason. "
                    "sources — list all discovered feed stores and their sources. "
                    "reprocess — release quarantined items so they can be re-ingested. "
                    "Use reason_pattern (e.g. 'classifier error:%') or quarantine_ids (comma-separated)."
                ),
            },
            "store": {
                "type": "string",
                "description": "Feed store name (e.g. 'gmail', 'rss'). Required for stats/recent/quarantine/reprocess. Omit for sources action.",
            },
            "source": {
                "type": "string",
                "description": "Filter by source within a store (optional). If omitted, returns data for all sources in the store.",
            },
            "limit": {
                "type": "integer",
                "description": "Max items to return for recent/quarantine actions. Default 20.",
            },
            "reason_pattern": {
                "type": "string",
                "description": "SQL LIKE pattern to match quarantine reason for reprocess action (e.g. 'classifier error:%').",
            },
            "quarantine_ids": {
                "type": "string",
                "description": "Comma-separated quarantine row IDs to release for reprocess action (e.g. '1,2,3').",
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
    reason_pattern: str | None = None,
    quarantine_ids: str | None = None,
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

    if action == "reprocess":
        return _handle_reprocess(stores[store], source, reason_pattern, quarantine_ids)

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
            return f"Unknown action '{action}'. Use: stats, recent, quarantine, sources, reprocess."
    finally:
        db.close()


def _handle_reprocess(
    db_path: Path,
    source: str | None,
    reason_pattern: str | None,
    quarantine_ids: str | None,
) -> str:
    """Release quarantined items so they can be re-ingested."""
    if not reason_pattern and not quarantine_ids:
        return "Reprocess requires either reason_pattern or quarantine_ids parameter."

    db = _open_readwrite(db_path)
    try:
        if quarantine_ids:
            try:
                ids = [int(x.strip()) for x in quarantine_ids.split(",") if x.strip()]
            except ValueError:
                return "quarantine_ids must be comma-separated integers."
            count = db.unquarantine(ids)
        else:
            count = db.unquarantine_by_reason(reason_pattern, source)  # type: ignore[arg-type]
        return json.dumps({"released": count})
    except Exception as exc:
        logger.error("Reprocess failed: %s", exc)
        return f"Reprocess failed: {exc}"
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
        except (sqlite3.Error, OSError) as e:
            result.append({"store": name, "error": str(e), "path": str(path)})

    return json.dumps(result, indent=2)
