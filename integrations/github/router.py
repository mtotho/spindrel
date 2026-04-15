"""FastAPI router for GitHub webhook endpoint."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from integrations import utils
from integrations.sdk import get_db, resolve_all_channels_by_client_id, ensure_active_session
from integrations.github.config import settings
from integrations.github.handlers import parse_event
from integrations.github.validator import validate_signature

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_execution_config(event_type: str, parsed) -> dict | None:
    """Build webhook-specific execution_config with preamble and tools for the event."""
    if not parsed.run_agent:
        return None

    preamble = None
    tools = None

    if event_type == "pull_request":
        preamble = (
            "You are responding to a GitHub pull request that was just opened.\n"
            "Review the code changes, provide constructive feedback, and highlight "
            "any issues or improvements. Use github_get_pr to fetch the full diff."
        )
        tools = ["github_get_pr"]

    elif event_type == "issues":
        preamble = (
            "You are responding to a newly opened GitHub issue.\n"
            "Triage the issue, suggest possible causes or solutions, "
            "and ask clarifying questions if needed."
        )

    elif event_type == "issue_comment":
        preamble = (
            "You are responding to a comment on a GitHub issue or pull request.\n"
            "Read the conversation context and respond relevantly. "
            "Be helpful and concise."
        )

    elif event_type == "pull_request_review":
        preamble = (
            "You are responding to a pull request review that requested changes.\n"
            "Address the reviewer's concerns and suggest specific fixes. "
            "Use github_get_pr to review the current state of the PR."
        )
        tools = ["github_get_pr"]

    elif event_type == "pull_request_review_comment":
        preamble = (
            "You are responding to an inline review comment on a pull request.\n"
            "Focus on the specific code being discussed. "
            "Use github_get_pr to see the full context of the change."
        )
        tools = ["github_get_pr"]

    if preamble is None:
        return None

    config: dict = {
        "system_preamble": preamble,
        "skills": ["integrations/github/github"],
    }
    if tools:
        config["tools"] = tools
    return config


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

    if not body:
        logger.error("GitHub webhook received empty body (event=%s, content-length=%s)",
                      event_type, request.headers.get("content-length"))
        raise HTTPException(status_code=400, detail="Empty request body")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.error("GitHub webhook received invalid JSON (event=%s, body_len=%d, first_100=%r)",
                      event_type, len(body), body[:100])
        raise HTTPException(status_code=400, detail="Invalid JSON body")

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

    execution_config = _build_execution_config(event_type, parsed)

    # Rich UI envelope for component-vocabulary rendering
    extra_metadata: dict | None = None
    if parsed.envelope:
        extra_metadata = {
            "envelope": parsed.envelope,
            "sender_display_name": f"@{parsed.sender}",
        }

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
            dispatch_config=dispatch_config,
            execution_config=execution_config,
            extra_metadata=extra_metadata, db=db,
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
            dispatch_config=dispatch_config,
            execution_config=execution_config,
            extra_metadata=extra_metadata, db=db,
        )
        results.append(result)

    # Fire task triggers for this integration event (fire-and-forget)
    from integrations.sdk import safe_create_task, emit_integration_event
    safe_create_task(emit_integration_event(
        "github", event_type,
        {"owner": parsed.owner, "repo": parsed.repo,
         "action": payload.get("action"), "sender": parsed.sender},
        client_id=client_id, category="webhook",
    ))

    if not results:
        return {"status": "filtered", "event": event_type, "channels": len(pairs)}

    return {
        "status": "processed",
        "event": event_type,
        "run_agent": parsed.run_agent,
        "channels": len(results),
        "results": results,
    }
