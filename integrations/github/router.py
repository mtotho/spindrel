"""FastAPI router for GitHub webhook endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.channels import resolve_all_channels_by_client_id, ensure_active_session
from integrations import utils
from integrations.github.config import settings
from integrations.github.handlers import parse_event
from integrations.github.validator import validate_signature

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive and process GitHub webhook events.

    Validates HMAC-SHA256 signature, parses event, then fans out the message
    to every channel that has a binding for github:{owner}/{repo}.
    Per-binding event_filter narrows which event types reach each channel.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not validate_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    if not event_type:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    payload = await request.json()

    if event_type == "ping":
        return {"status": "pong"}

    parsed = parse_event(event_type, payload)
    if parsed is None:
        return {"status": "ignored", "event": event_type}

    # Skip bot's own comments
    bot_login = settings.GITHUB_BOT_LOGIN
    if bot_login and parsed.sender == bot_login:
        logger.debug("Ignoring event from bot login: %s", bot_login)
        return {"status": "ignored", "reason": "bot_self"}

    client_id = f"github:{parsed.owner}/{parsed.repo}"

    dispatch_config = {
        "type": "github",
        "owner": parsed.owner,
        "repo": parsed.repo,
    }
    if parsed.comment_target:
        dispatch_config["comment_target"] = parsed.comment_target

    # Fan-out to all channels bound to this client_id
    pairs = await resolve_all_channels_by_client_id(db, client_id)

    if not pairs:
        # Backward compat: fall back to legacy single-session flow
        session_id = await utils.get_or_create_session(
            client_id, "default", dispatch_config=dispatch_config, db=db,
        )
        result = await utils.inject_message(
            session_id, parsed.message, source="github",
            run_agent=parsed.run_agent, notify=False,
            dispatch_config=dispatch_config, db=db,
        )
        return {
            "status": "processed",
            "event": event_type,
            "run_agent": parsed.run_agent,
            "session_id": result["session_id"],
            "task_id": result.get("task_id"),
        }

    results = []
    for channel, binding in pairs:
        # Per-binding event filtering
        event_filter = (binding.dispatch_config or {}).get("event_filter")
        if event_filter and event_type not in event_filter:
            continue

        session_id = await ensure_active_session(db, channel)

        result = await utils.inject_message(
            session_id, parsed.message, source="github",
            run_agent=parsed.run_agent, notify=False,
            dispatch_config=dispatch_config, db=db,
        )
        results.append(result)

    if not results:
        return {"status": "filtered", "event": event_type, "channels": len(pairs)}

    return {
        "status": "processed",
        "event": event_type,
        "run_agent": parsed.run_agent,
        "channels": len(results),
        "results": results,
    }
