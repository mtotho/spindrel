"""FastAPI router for Frigate webhook endpoint.

The MQTT listener POSTs raw Frigate event payloads here. The router parses
the event, resolves all channels bound to frigate:events, applies per-binding
filters (cameras, labels, min_score), and injects messages into matching channels.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.channels import resolve_all_channels_by_client_id, ensure_active_session
from integrations import utils

logger = logging.getLogger(__name__)

router = APIRouter()

CLIENT_ID = "frigate:events"


@dataclass
class ParsedEvent:
    camera: str
    label: str
    score: float
    message: str


def parse_event(payload: dict) -> ParsedEvent | None:
    """Parse a Frigate MQTT event payload into a ParsedEvent.

    Returns None if the event should be ignored (not type "new", missing data).
    """
    event_type = payload.get("type", "")
    if event_type != "new":
        return None

    after = payload.get("after", {})
    data = after if after else payload.get("before", {})
    if not data:
        return None

    camera = data.get("camera", "")
    label = data.get("label", "")
    score = data.get("top_score") or data.get("score") or 0.0
    if isinstance(score, str):
        score = float(score)

    if not camera or not label:
        return None

    # Format the message (same logic as mqtt_listener.format_event_message)
    from integrations.frigate.mqtt_listener import format_event_message
    message = format_event_message(payload)

    return ParsedEvent(camera=camera, label=label, score=score, message=message)


def matches_binding_filter(event: ParsedEvent, dispatch_config: dict | None) -> bool:
    """Check if a parsed event matches a binding's dispatch_config filters.

    Filter fields in dispatch_config:
      - cameras: comma-separated or list of camera names
      - labels: comma-separated or list of label names
      - min_score: minimum detection score (0-1)

    Empty/missing fields = accept all.
    """
    if not dispatch_config:
        return True

    # Camera filter
    cameras = dispatch_config.get("cameras")
    if cameras:
        if isinstance(cameras, str):
            cameras = [c.strip() for c in cameras.split(",") if c.strip()]
        if event.camera not in cameras:
            return False

    # Label filter
    labels = dispatch_config.get("labels")
    if labels:
        if isinstance(labels, str):
            labels = [lb.strip() for lb in labels.split(",") if lb.strip()]
        if event.label not in labels:
            return False

    # Min score filter
    min_score = dispatch_config.get("min_score")
    if min_score is not None:
        if event.score < float(min_score):
            return False

    return True


@router.post("/webhook")
async def frigate_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive a Frigate event payload and fan out to bound channels.

    The MQTT listener POSTs raw Frigate event payloads here. Per-binding
    filters (cameras, labels, min_score) narrow which channels receive events.
    """
    payload = await request.json()

    event = parse_event(payload)
    if event is None:
        return {"status": "ignored"}

    # Fan-out to all channels bound to this client_id
    pairs = await resolve_all_channels_by_client_id(db, CLIENT_ID)

    if not pairs:
        # Backward compat: legacy single-session flow
        session_id = await utils.get_or_create_session(
            CLIENT_ID, "default", db=db,
        )
        result = await utils.inject_message(
            session_id, event.message, source="frigate",
            run_agent=True, notify=False, db=db,
        )
        return {
            "status": "processed",
            "session_id": result["session_id"],
            "task_id": result.get("task_id"),
        }

    results = []
    for channel, binding in pairs:
        if not matches_binding_filter(event, binding.dispatch_config):
            continue

        session_id = await ensure_active_session(db, channel)
        result = await utils.inject_message(
            session_id, event.message, source="frigate",
            run_agent=True, notify=False, db=db,
        )
        results.append(result)

    if not results:
        return {"status": "filtered", "channels": len(pairs)}

    return {
        "status": "processed",
        "channels": len(results),
        "results": results,
    }
