"""FastAPI router for ingestion pipeline — feed health dashboard API."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.dependencies import verify_auth
from integrations.ingestion.config import INGESTION_DB_DIR
from integrations.ingestion.store import IngestionStore

logger = logging.getLogger(__name__)

router = APIRouter()


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


@router.get("/hud/status")
async def hud_status(_auth=Depends(verify_auth)) -> dict[str, Any]:
    """Return standardized HudData for the chat status strip."""
    stores_map = _discover_stores()
    if not stores_map:
        return {"visible": False, "items": []}

    total_processed = 0
    total_quarantined = 0
    total_classifier_errors = 0

    for name, path in stores_map.items():
        try:
            db = _open_readonly(path)
            try:
                stats = db.get_feed_stats()
                total_processed += stats.get("total_processed", 0)
                total_quarantined += stats.get("total_quarantined", 0)
                total_classifier_errors += db.count_by_reason_prefix(None, "classifier error:")
            finally:
                db.close()
        except Exception:
            logger.warning("Failed to read store %s for HUD", name, exc_info=True)

    items: list[dict[str, Any]] = [
        {
            "type": "badge",
            "label": "Processed",
            "value": str(total_processed),
            "icon": "CheckCircle",
            "variant": "default",
            "on_click": {"type": "link", "href": "/integration/ingestion"},
        },
    ]

    if total_quarantined > 0:
        variant = "danger" if total_quarantined > 20 else "warning"
        items.append({
            "type": "badge",
            "label": "Quarantined",
            "value": str(total_quarantined),
            "icon": "AlertTriangle",
            "variant": variant,
            "on_click": {"type": "link", "href": "/integration/ingestion"},
        })

    if total_classifier_errors > 0:
        items.append({"type": "divider"})
        items.append({
            "type": "action",
            "label": "Release Errors",
            "icon": "ShieldAlert",
            "variant": "warning",
            "on_click": {
                "type": "action",
                "endpoint": "/integrations/ingestion/stores/all/reprocess",
                "method": "POST",
                "body": {"reason_pattern": "classifier error:%"},
                "confirm": f"Release {total_classifier_errors} classifier error(s) across all stores?",
            },
        })

    return {"visible": True, "items": items}


@router.post("/stores/all/reprocess")
async def reprocess_all_stores(
    body: dict[str, Any],
    _auth=Depends(verify_auth),
) -> dict[str, Any]:
    """Release quarantined items across ALL stores by reason pattern."""
    reason_pattern: str | None = body.get("reason_pattern")
    if not reason_pattern:
        return {"error": "Provide reason_pattern", "released": 0}

    stores_map = _discover_stores()
    total_released = 0
    for name, path in stores_map.items():
        try:
            db = _open_readwrite(path)
            try:
                count = db.unquarantine_by_reason(reason_pattern, None)
                total_released += count
            finally:
                db.close()
        except Exception:
            logger.error("Reprocess failed for store %s", name, exc_info=True)

    return {"released": total_released}


@router.get("/ping")
async def ping():
    return {"status": "ok", "service": "ingestion"}


@router.get("/overview")
async def overview(_auth=Depends(verify_auth)) -> dict[str, Any]:
    """Return all stores with stats, classifier error count, quarantine preview."""
    stores_map = _discover_stores()
    result: list[dict[str, Any]] = []

    for name, path in stores_map.items():
        try:
            db = _open_readonly(path)
            try:
                stats = db.get_feed_stats()
                classifier_error_count = db.count_by_reason_prefix(None, "classifier error:")
                preview = db.get_quarantine_items(limit=5)
            finally:
                db.close()
            result.append({
                "name": name,
                "stats": stats,
                "quarantine_preview": preview,
                "classifier_error_count": classifier_error_count,
            })
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Failed to read store %s: %s", name, exc)
            result.append({
                "name": name,
                "stats": None,
                "quarantine_preview": [],
                "classifier_error_count": 0,
                "error": str(exc),
            })

    return {"stores": result}


@router.get("/stores/{name}/quarantine")
async def get_quarantine(
    name: str,
    limit: int = Query(default=50, ge=1, le=500),
    source: str | None = Query(default=None),
    _auth=Depends(verify_auth),
) -> dict[str, Any]:
    """Return quarantine items for a specific store."""
    stores = _discover_stores()
    if name not in stores:
        return {"error": f"Store '{name}' not found", "items": []}

    db = _open_readonly(stores[name])
    try:
        items = db.get_quarantine_items(source=source, limit=limit)
    finally:
        db.close()

    return {"items": items, "store": name}


@router.post("/stores/{name}/reprocess")
async def reprocess(
    name: str,
    body: dict[str, Any],
    _auth=Depends(verify_auth),
) -> dict[str, Any]:
    """Release quarantined items by IDs or reason pattern."""
    stores = _discover_stores()
    if name not in stores:
        return {"error": f"Store '{name}' not found", "released": 0}

    quarantine_ids: list[int] | None = body.get("quarantine_ids")
    reason_pattern: str | None = body.get("reason_pattern")
    source: str | None = body.get("source")

    if not quarantine_ids and not reason_pattern:
        return {"error": "Provide quarantine_ids or reason_pattern", "released": 0}

    db = _open_readwrite(stores[name])
    try:
        if quarantine_ids:
            count = db.unquarantine(quarantine_ids)
        else:
            count = db.unquarantine_by_reason(reason_pattern, source)  # type: ignore[arg-type]
    except Exception as exc:
        logger.error("Reprocess failed for store %s: %s", name, exc)
        return {"error": str(exc), "released": 0}
    finally:
        db.close()

    return {"released": count}
