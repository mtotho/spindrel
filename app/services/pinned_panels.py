"""Pinned file helpers backed by the channel-scoped native widget instance.

The legacy ``channel.config["pinned_panels"]`` rail is retired. A channel now
owns a single ``core/pinned_files_native`` widget instance whose state stores
every pinned path. The chat/dashboard surface renders that widget through the
normal dashboard-pin pipeline, while file writes still consult the in-memory
reverse index below to decide whether to emit ``pinned_file_updated`` events.
"""
from __future__ import annotations

import copy
import logging
import mimetypes
import uuid
from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.engine import async_session

logger = logging.getLogger(__name__)

PINNED_FILES_WIDGET_REF = "core/pinned_files_native"
PINNED_FILES_DISPLAY_LABEL = "Pinned files"

# path → set of channel_ids that have this path pinned
_pinned_paths: dict[str, set[uuid.UUID]] = defaultdict(set)
_loaded: bool = False


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _channel_dashboard_key(channel_id: uuid.UUID) -> str:
    return f"channel:{channel_id}"


def _normalize_pinned_files_state(state: dict[str, Any] | None) -> dict[str, Any]:
    raw = copy.deepcopy(state or {})
    items: list[dict[str, str]] = []
    for item in raw.get("pinned_files") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        items.append(
            {
                "path": path,
                "pinned_at": str(item.get("pinned_at") or ""),
                "pinned_by": str(item.get("pinned_by") or "user"),
            }
        )
    active_path = str(raw.get("active_path") or "").strip() or None
    valid_paths = {item["path"] for item in items}
    if active_path not in valid_paths:
        active_path = items[0]["path"] if items else None
    created_at = str(raw.get("created_at") or "") or _now_iso()
    updated_at = str(raw.get("updated_at") or "") or created_at
    return {
        "pinned_files": items,
        "active_path": active_path,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _iter_paths_from_state(state: dict[str, Any] | None) -> list[str]:
    return [item["path"] for item in _normalize_pinned_files_state(state)["pinned_files"]]


def replace_channel_paths(channel_id: uuid.UUID, paths: list[str]) -> None:
    """Replace the cached pinned-path set for one channel without re-querying DB."""
    for path_set in _pinned_paths.values():
        path_set.discard(channel_id)
    empty_keys = [k for k, v in _pinned_paths.items() if not v]
    for key in empty_keys:
        del _pinned_paths[key]
    for path in paths:
        _pinned_paths[path].add(channel_id)


async def _get_pinned_files_instance(
    db: AsyncSession,
    channel_id: uuid.UUID,
):
    from app.db.models import WidgetInstance

    return (
        await db.execute(
            select(WidgetInstance).where(
                WidgetInstance.widget_kind == "native_app",
                WidgetInstance.widget_ref == PINNED_FILES_WIDGET_REF,
                WidgetInstance.scope_kind == "channel",
                WidgetInstance.scope_ref == str(channel_id),
            )
        )
    ).scalar_one_or_none()


async def _require_channel(db: AsyncSession, channel_id: uuid.UUID):
    from app.db.models import Channel

    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(404, "Channel not found")
    return channel


async def list_pinned_files_for_channel(
    db: AsyncSession,
    channel_id: uuid.UUID,
) -> list[dict[str, str]]:
    instance = await _get_pinned_files_instance(db, channel_id)
    if instance is None:
        return []
    return _normalize_pinned_files_state(instance.state).get("pinned_files", [])


async def ensure_pinned_files_widget_pin(
    db: AsyncSession,
    channel_id: uuid.UUID,
):
    from app.db.models import WidgetDashboardPin
    from app.services.dashboard_pins import create_pin
    from app.services.native_app_widgets import build_native_widget_preview_envelope

    instance = await _get_pinned_files_instance(db, channel_id)
    if instance is None:
        raise HTTPException(404, "Pinned files widget instance not found")

    dashboard_key = _channel_dashboard_key(channel_id)
    existing_pin = (
        await db.execute(
            select(WidgetDashboardPin).where(
                WidgetDashboardPin.dashboard_key == dashboard_key,
                WidgetDashboardPin.widget_instance_id == instance.id,
            )
        )
    ).scalar_one_or_none()
    if existing_pin is not None:
        return existing_pin

    return await create_pin(
        db,
        source_kind="channel",
        tool_name=PINNED_FILES_WIDGET_REF,
        envelope=build_native_widget_preview_envelope(PINNED_FILES_WIDGET_REF),
        source_channel_id=channel_id,
        widget_origin={
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "widget_ref": PINNED_FILES_WIDGET_REF,
        },
        display_label=PINNED_FILES_DISPLAY_LABEL,
        dashboard_key=dashboard_key,
        zone="dock",
    )


async def pin_file_for_channel(
    db: AsyncSession,
    channel_id: uuid.UUID,
    path: str,
    *,
    actor: str = "user",
) -> dict[str, str]:
    from app.services.native_app_widgets import get_or_create_native_widget_instance

    normalized_path = str(path or "").strip()
    if not normalized_path:
        raise HTTPException(422, "path is required")

    await _require_channel(db, channel_id)
    instance = await get_or_create_native_widget_instance(
        db,
        widget_ref=PINNED_FILES_WIDGET_REF,
        dashboard_key=_channel_dashboard_key(channel_id),
        source_channel_id=channel_id,
    )

    state = _normalize_pinned_files_state(instance.state)
    items = [item for item in state["pinned_files"] if item["path"] != normalized_path]
    entry = {
        "path": normalized_path,
        "pinned_at": _now_iso(),
        "pinned_by": actor or "user",
    }
    items.insert(0, entry)
    state["pinned_files"] = items
    state["active_path"] = normalized_path
    state["updated_at"] = entry["pinned_at"]
    instance.state = state
    flag_modified(instance, "state")

    await ensure_pinned_files_widget_pin(db, channel_id)
    await db.commit()
    replace_channel_paths(channel_id, [item["path"] for item in items])
    return entry


async def unpin_file_for_channel(
    db: AsyncSession,
    channel_id: uuid.UUID,
    path: str,
) -> dict[str, Any]:
    normalized_path = str(path or "").strip()
    if not normalized_path:
        raise HTTPException(422, "path is required")

    await _require_channel(db, channel_id)
    instance = await _get_pinned_files_instance(db, channel_id)
    if instance is None:
        raise HTTPException(404, "File is not pinned")

    state = _normalize_pinned_files_state(instance.state)
    items = [item for item in state["pinned_files"] if item["path"] != normalized_path]
    if len(items) == len(state["pinned_files"]):
        raise HTTPException(404, "File is not pinned")
    state["pinned_files"] = items
    if state.get("active_path") == normalized_path:
        state["active_path"] = items[0]["path"] if items else None
    state["updated_at"] = _now_iso()
    instance.state = state
    flag_modified(instance, "state")

    await db.commit()
    replace_channel_paths(channel_id, [item["path"] for item in items])
    return {"ok": True}


async def clear_pinned_files_for_channel(
    db: AsyncSession,
    channel_id: uuid.UUID,
) -> bool:
    instance = await _get_pinned_files_instance(db, channel_id)
    if instance is None:
        return False
    await clear_pinned_files_instance(instance)
    return True


async def clear_pinned_files_instance(instance) -> None:
    state = _normalize_pinned_files_state(instance.state)
    state["pinned_files"] = []
    state["active_path"] = None
    state["updated_at"] = _now_iso()
    instance.state = state
    flag_modified(instance, "state")


async def load_pinned_paths() -> None:
    """Load all pinned paths from DB into the in-memory cache."""
    global _loaded
    _pinned_paths.clear()

    from app.db.models import WidgetInstance

    async with async_session() as db:
        rows = (
            await db.execute(
                select(WidgetInstance.scope_ref, WidgetInstance.state).where(
                    WidgetInstance.widget_kind == "native_app",
                    WidgetInstance.widget_ref == PINNED_FILES_WIDGET_REF,
                    WidgetInstance.scope_kind == "channel",
                )
            )
        ).all()

    count = 0
    for scope_ref, state in rows:
        try:
            channel_id = uuid.UUID(str(scope_ref))
        except ValueError:
            continue
        for path in _iter_paths_from_state(state):
            _pinned_paths[path].add(channel_id)
            count += 1

    _loaded = True
    if count:
        logger.info("Loaded %d pinned-path mapping(s) across %d channel(s)", count, len(rows))


def is_path_pinned(path: str) -> set[uuid.UUID]:
    """Return set of channel_ids that have this path pinned. O(1)."""
    return _pinned_paths.get(path, set())


async def invalidate_channel(channel_id: uuid.UUID) -> None:
    """Re-query a single channel's pinned paths and rebuild its entries."""
    async with async_session() as db:
        instance = await _get_pinned_files_instance(db, channel_id)

    if instance is None:
        replace_channel_paths(channel_id, [])
        return
    replace_channel_paths(channel_id, _iter_paths_from_state(instance.state))


def _mimetype_for_path(path: str) -> str:
    """Infer content_type from file extension."""
    mt, _ = mimetypes.guess_type(path)
    if mt:
        return mt
    if path.endswith((".md", ".mdx")):
        return "text/markdown"
    return "text/plain"


async def notify_pinned_file_changed(path: str) -> None:
    """If *path* is pinned in any channel, publish PINNED_FILE_UPDATED events."""
    channel_ids = is_path_pinned(path)
    if not channel_ids:
        return

    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.payloads import PinnedFileUpdatedPayload
    from app.services.channel_events import publish_typed

    content_type = _mimetype_for_path(path)

    for cid in channel_ids:
        publish_typed(
            cid,
            ChannelEvent(
                channel_id=cid,
                kind=ChannelEventKind.PINNED_FILE_UPDATED,
                payload=PinnedFileUpdatedPayload(
                    channel_id=cid,
                    path=path,
                    content_type=content_type,
                ),
            ),
        )
