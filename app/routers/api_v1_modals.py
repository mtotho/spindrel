"""Modal submission API — /api/v1/modals/{callback_id}/submit

Integrations (Slack view handler, Discord modal callback, …) post here
when a user fills out a form opened by the ``open_modal`` tool. We
resolve the matching waiter in ``app.services.modal_waiter`` so the
paused tool call can continue.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import require_scopes
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import ModalSubmittedPayload
from app.services import modal_waiter
from app.services.channel_events import publish_typed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/modals", tags=["Modals"])


class ModalSubmitRequest(BaseModel):
    values: dict = Field(
        ..., description="Flat dict of field-id → submitted value",
    )
    submitted_by: str = Field(
        ..., description="Integration-native id of the submitting user",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Opaque metadata passed through the OpenModal action",
    )
    channel_id: str | None = Field(
        default=None,
        description="Server channel uuid — used for the MODAL_SUBMITTED bus event",
    )


class ModalSubmitResponse(BaseModel):
    accepted: bool
    reason: str | None = None


@router.post(
    "/{callback_id}/submit",
    response_model=ModalSubmitResponse,
)
async def submit_modal(
    callback_id: str,
    body: ModalSubmitRequest,
    _auth=Depends(require_scopes("integrations:write")),
) -> ModalSubmitResponse:
    """Resolve the waiter for ``callback_id``.

    Returns ``accepted=False`` when the callback_id has no waiter
    (stale submission, server restarted mid-turn). The integration-side
    handler treats this as a silent no-op — the user sees the modal
    close and nothing happens.
    """
    ok = modal_waiter.submit(
        callback_id,
        values=body.values,
        submitted_by=body.submitted_by,
        metadata=body.metadata,
    )
    if not ok:
        return ModalSubmitResponse(accepted=False, reason="unknown_callback_id")

    # Emit a bus event too so subscribers (future Discord, web UI live
    # preview of submissions, …) can observe modal submissions without
    # polling the waiter.
    if body.channel_id:
        import uuid as _uuid
        try:
            channel_uuid = _uuid.UUID(body.channel_id)
        except ValueError:
            channel_uuid = None
        if channel_uuid is not None:
            try:
                publish_typed(
                    channel_uuid,
                    ChannelEvent(
                        channel_id=channel_uuid,
                        kind=ChannelEventKind.MODAL_SUBMITTED,
                        payload=ModalSubmittedPayload(
                            callback_id=callback_id,
                            submitted_by=body.submitted_by,
                            values=body.values,
                            metadata=body.metadata,
                        ),
                    ),
                )
            except Exception:
                logger.debug(
                    "modal_submit bus publish failed for %s",
                    callback_id, exc_info=True,
                )

    return ModalSubmitResponse(accepted=True)


@router.post(
    "/{callback_id}/cancel",
    response_model=ModalSubmitResponse,
)
async def cancel_modal(
    callback_id: str,
    _auth=Depends(require_scopes("integrations:write")),
) -> ModalSubmitResponse:
    """Release the waiter without a value (user dismissed the modal)."""
    modal_waiter.cancel(callback_id, reason="user_dismissed")
    return ModalSubmitResponse(accepted=True)
