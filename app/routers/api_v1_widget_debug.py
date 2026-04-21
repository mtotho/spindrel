"""Widget debug event ring — ambient trace capture + readback.

POST /api/v1/widget-debug/events — iframes post structured events (tool
calls, attachment loads, JS errors, unhandled rejections, console
output, author logs) here. The router is permissive by design: debug
telemetry from a broken widget is exactly when you most need it to
land, so failures never cascade into the widget's runtime. Authz is
minimal — authenticated caller + a coarse pin-ownership check for
widget-minted tokens (a widget JWT can only post under its own pin).

GET /api/v1/widget-debug/events — Inspector panel + ``inspect_widget_pin``
bot tool both read from this.
"""
from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.dependencies import ApiKeyAuth, verify_auth_or_user
from app.services import widget_debug

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget-debug", tags=["widget-debug"])


# Event kinds the preamble emits. Kept open-ended (Literal includes an
# escape hatch) so new capture hooks can be added client-side without a
# backend pin update.
EventKind = Literal[
    "tool-call",
    "load-attachment",
    "load-asset",
    "error",
    "rejection",
    "console",
    "log",
]


class EventIn(BaseModel):
    pin_id: UUID
    kind: str = Field(..., description="tool-call | load-attachment | load-asset | error | rejection | console | log")
    ts: float | None = Field(default=None, description="Client-side wall-clock timestamp (ms since epoch).")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Kind-specific fields (tool name, response JSON, stack trace, console args, etc.).",
    )


class EventOut(BaseModel):
    ok: bool


class EventsResponse(BaseModel):
    pin_id: UUID
    events: list[dict[str, Any]]


def _widget_pin_id(auth: object) -> UUID | None:
    """Extract pin_id from a widget-scoped JWT; None for user / admin / bot keys."""
    if isinstance(auth, ApiKeyAuth):
        return auth.pin_id
    return None


@router.post("/events", response_model=EventOut)
async def post_event(body: EventIn, auth=Depends(verify_auth_or_user)) -> EventOut:
    """Record one event for a pinned widget.

    Widget-scoped tokens can only write under their own ``pin_id``. User
    and admin tokens can write under any pin (supports test/dev flows
    where a page-level helper posts synthetic events). Unknown caller
    types fall through to a 401 at the dependency layer.
    """
    widget_pin = _widget_pin_id(auth)
    if widget_pin is not None and widget_pin != body.pin_id:
        raise HTTPException(
            status_code=403,
            detail="Widget token cannot post debug events for a different pin.",
        )
    widget_debug.record_event(body.pin_id, {"kind": body.kind, "ts": body.ts, **body.payload})
    return EventOut(ok=True)


@router.get("/events", response_model=EventsResponse)
async def list_events(
    pin_id: UUID = Query(..., description="Dashboard pin id whose events to return."),
    limit: int = Query(50, ge=1, le=200),
    auth=Depends(verify_auth_or_user),
) -> EventsResponse:
    """Return recent events for a pin, newest first.

    Any authenticated caller can read. Widget-scoped tokens are scoped
    to their own pin; everything else (user, admin, bot keys) can read
    any pin — the event ring is debug telemetry, not sensitive data.
    """
    widget_pin = _widget_pin_id(auth)
    if widget_pin is not None and widget_pin != pin_id:
        raise HTTPException(
            status_code=403,
            detail="Widget token cannot read debug events for a different pin.",
        )
    events = widget_debug.get_events(pin_id, limit=limit)
    return EventsResponse(pin_id=pin_id, events=events)


@router.delete("/events", response_model=EventOut)
async def clear_events(
    pin_id: UUID = Query(..., description="Dashboard pin id whose events to drop."),
    auth=Depends(verify_auth_or_user),
) -> EventOut:
    """Drop the event ring for a pin. Triggered by the Inspector's Clear button."""
    widget_pin = _widget_pin_id(auth)
    if widget_pin is not None and widget_pin != pin_id:
        raise HTTPException(
            status_code=403,
            detail="Widget token cannot clear debug events for a different pin.",
        )
    widget_debug.clear_events(pin_id)
    return EventOut(ok=True)
