"""FastAPI router for GitHub webhook endpoint."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from integrations.github.dispatcher import dispatch
from integrations.github.validator import validate_signature

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive and process GitHub webhook events.

    Validates HMAC-SHA256 signature, then dispatches to the appropriate handler.
    No auth dependency — GitHub authenticates via the webhook secret.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not validate_signature(body, signature):
        raise HTTPException(status_code= 403, detail="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    if not event_type:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    payload = await request.json()

    # Respond to GitHub ping events
    if event_type == "ping":
        return {"status": "pong"}

    result = await dispatch(event_type, payload, db)
    return {"status": "processed", "event": event_type, "result": result}
