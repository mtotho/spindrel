"""Event handlers for GitHub webhook events.

Each handler formats a message and injects it into the agent session
via integrations.utils.inject_message.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from integrations import utils
from integrations.github.config import github_config

logger = logging.getLogger(__name__)


async def handle_workflow_run(payload: dict[str, Any], db: AsyncSession) -> dict | None:
    """Handle workflow_run events — notify on failure."""
    workflow_run = payload.get("workflow_run", {})
    if workflow_run.get("conclusion") != "failure":
        return None

    repo = payload.get("repository", {}).get("full_name", "unknown")
    workflow_name = workflow_run.get("name", "unknown")
    branch = workflow_run.get("head_branch", "unknown")
    url = workflow_run.get("html_url", "")
    run_id = workflow_run.get("id", "")

    message = (
        f"🔴 **GitHub CI failure** — `{repo}`\n"
        f"Workflow **{workflow_name}** failed on branch `{branch}`\n"
        f"Run #{run_id}: {url}"
    )

    return await _inject(message, db)


async def handle_check_run(payload: dict[str, Any], db: AsyncSession) -> dict | None:
    """Handle check_run events — notify on failure."""
    check_run = payload.get("check_run", {})
    if check_run.get("conclusion") != "failure":
        return None

    repo = payload.get("repository", {}).get("full_name", "unknown")
    check_name = check_run.get("name", "unknown")
    url = check_run.get("html_url", "")

    message = (
        f"🔴 **GitHub check failure** — `{repo}`\n"
        f"Check **{check_name}** failed\n"
        f"{url}"
    )

    return await _inject(message, db)


async def _inject(message: str, db: AsyncSession) -> dict | None:
    """Inject a message into the configured agent session."""
    session_id = github_config.AGENT_SESSION_ID
    if not session_id:
        logger.warning("AGENT_SESSION_ID not configured — dropping GitHub notification")
        return None

    try:
        result = await utils.inject_message(
            session_id=uuid.UUID(session_id),
            content=message,
            source="github",
            notify=True,
            run_agent=False,
            db=db,
        )
        logger.info("Injected GitHub notification into session %s", session_id)
        return result
    except Exception:
        logger.exception("Failed to inject GitHub notification")
        return None
