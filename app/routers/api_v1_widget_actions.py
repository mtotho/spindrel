"""Widget action endpoint — dispatches interactive widget actions."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth_or_user
from app.schemas.widget_actions import (
    WidgetActionRequest,
    WidgetActionResponse,
    WidgetRefreshBatchRequest,
    WidgetRefreshBatchResponse,
    WidgetRefreshRequest,
)
from app.services.widget_action_dispatch import dispatch_widget_action as dispatch_widget_action_service
from app.services.widget_action_state_poll import (
    refresh_widget_state as refresh_widget_state_service,
    refresh_widget_states_batch as refresh_widget_states_batch_service,
)

# Widget-actions is a dispatch proxy; each mode enforces its own authorization:
# tool dispatch uses tool policy, API dispatch delegates to proxied endpoints,
# and widget_config/native/db/widget-handler dispatches validate their own pin
# or instance scope. The router-level gate is authentication-only.
router = APIRouter(
    prefix="/widget-actions",
    tags=["widget-actions"],
    dependencies=[Depends(verify_auth_or_user)],
)


@router.post("", response_model=WidgetActionResponse)
async def dispatch_widget_action(
    req: WidgetActionRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
) -> WidgetActionResponse:
    return await dispatch_widget_action_service(req, db, auth=auth)


@router.get("/stream")
async def widget_event_stream_endpoint(
    channel_id: uuid.UUID = Query(..., description="Channel whose event bus to tail"),
    kinds: str | None = Query(
        None,
        description="Comma-separated ChannelEventKind values. Omit for no filter.",
    ),
    since: int | None = Query(
        None,
        description="Last seq seen; replay ring-buffered events after this seq.",
    ),
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """SSE stream of channel events, consumable by ``window.spindrel.stream``."""
    from app.services.widget_action_stream import (
        parse_kinds_csv,
        widget_event_stream,
    )

    try:
        kind_set = parse_kinds_csv(kinds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    from app.services.widget_action_auth import authorize_widget_channel_access

    await authorize_widget_channel_access(
        db,
        auth,
        channel_id,
        required_scope="channels:read",
    )
    # Release the pool connection BEFORE entering the long-lived stream.
    # `Depends(get_db)`'s session would otherwise stay open for the full
    # SSE lifetime (hours), pinning a connection in `idle in transaction`
    # and exhausting the pool — same trap channel_events already avoids.
    await db.close()

    return StreamingResponse(
        widget_event_stream(
            channel_id=channel_id,
            kinds=kind_set,
            since=since,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/refresh-batch", response_model=WidgetRefreshBatchResponse)
async def refresh_widget_states_batch(
    req: WidgetRefreshBatchRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
) -> WidgetRefreshBatchResponse:
    return await refresh_widget_states_batch_service(req, db=db, auth=auth)


@router.post("/refresh", response_model=WidgetActionResponse)
async def refresh_widget_state(
    req: WidgetRefreshRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
) -> WidgetActionResponse:
    return await refresh_widget_state_service(req, db=db, auth=auth)
