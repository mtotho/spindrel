"""FastAPI router for Frigate webhook endpoint.

The MQTT listener POSTs raw Frigate event payloads here. The router parses
the event, resolves all channels bound to frigate:events, applies per-binding
filters (cameras, labels, min_score), and injects messages into matching channels.
"""
from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from integrations import utils
from integrations.sdk import get_db, resolve_all_channels_by_client_id, ensure_active_session

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_webhook_token() -> str | None:
    """Get the Frigate webhook token from env or integration settings."""
    # Check env var first (fast path)
    token = os.environ.get("FRIGATE_WEBHOOK_TOKEN")
    if token:
        return token
    # Fall back to DB-backed integration settings
    try:
        from app.services.integration_settings import get_value
        val = get_value("frigate", "FRIGATE_WEBHOOK_TOKEN")
        return val if val else None
    except Exception:
        return None

CLIENT_ID = "frigate:events"


def _build_execution_config(event: "ParsedEvent") -> dict:
    """Build webhook-specific execution_config for a Frigate detection event."""
    preamble = (
        "You are responding to a Frigate security camera detection event.\n"
        f"Camera: {event.camera} | Detected: {event.label} (score: {event.score:.0%})\n"
        "Use frigate_event_snapshot to view the detection image before responding.\n"
        "Describe what you see and assess whether this requires attention."
    )
    return {
        "system_preamble": preamble,
        "skills": ["integrations/frigate/frigate"],
        "tools": ["frigate_event_snapshot"],
    }


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
    from integrations.sdk import sanitize_unicode
    message = sanitize_unicode(format_event_message(payload))

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
    # Optional webhook token authentication
    expected_token = _get_webhook_token()
    if expected_token:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(token, expected_token):
            raise HTTPException(status_code=401, detail="Invalid webhook token")

    payload = await request.json()

    event = parse_event(payload)
    if event is None:
        return {"status": "ignored"}

    # Fan-out to all channels bound to this client_id
    pairs = await resolve_all_channels_by_client_id(db, CLIENT_ID)

    execution_config = _build_execution_config(event)

    if not pairs:
        # Backward compat: legacy single-session flow
        session_id = await utils.get_or_create_session(
            CLIENT_ID, "default", db=db,
        )
        result = await utils.inject_message(
            session_id, event.message, source="frigate",
            run_agent=True, notify=False,
            execution_config=execution_config, db=db,
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
            run_agent=True, notify=False,
            execution_config=execution_config, db=db,
        )
        results.append(result)

    # Fire task triggers for this integration event (fire-and-forget)
    from integrations.sdk import safe_create_task, emit_integration_event
    safe_create_task(emit_integration_event(
        "frigate", "object_detected",
        {"camera": event.camera, "label": event.label, "score": event.score},
        client_id=CLIENT_ID, category="webhook",
    ))

    if not results:
        return {"status": "filtered", "channels": len(pairs)}

    return {
        "status": "processed",
        "channels": len(results),
        "results": results,
    }
