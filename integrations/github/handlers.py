"""Event handlers for GitHub webhook events.

Each handler formats a message and posts it to a Slack channel
via integrations.slack.client.post_message.
"""

from __future__ import annotations

import logging
from typing import Any

from integrations.github.config import github_config
from integrations.slack.client import post_message

logger = logging.getLogger(__name__)


async def handle_workflow_run(payload: dict[str, Any], db=None) -> dict | None:
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
        f"🔴 *GitHub CI failure* — `{repo}`\n"
        f"Workflow *{workflow_name}* failed on branch `{branch}`\n"
        f"Run #{run_id}: {url}"
    )

    return await _post_to_slack(message)


async def handle_check_run(payload: dict[str, Any], db=None) -> dict | None:
    """Handle check_run events — notify on failure."""
    check_run = payload.get("check_run", {})
    if check_run.get("conclusion") != "failure":
        return None

    repo = payload.get("repository", {}).get("full_name", "unknown")
    check_name = check_run.get("name", "unknown")
    url = check_run.get("html_url", "")

    message = (
        f"🔴 *GitHub check failure* — `{repo}`\n"
        f"Check *{check_name}* failed\n"
        f"{url}"
    )

    return await _post_to_slack(message)


async def _post_to_slack(message: str) -> dict | None:
    """Post a notification message to the configured Slack channel."""
    channel_id = github_config.SLACK_CHANNEL_ID
    token = github_config.SLACK_BOT_TOKEN
    if not channel_id:
        logger.warning("SLACK_CHANNEL_ID not configured — dropping GitHub notification")
        return None
    if not token:
        logger.warning("SLACK_BOT_TOKEN not configured — dropping GitHub notification")
        return None

    success = await post_message(
        token=token,
        channel_id=channel_id,
        text=message,
        username="GitHub",
        icon_emoji=":github:",
    )

    if success:
        logger.info("Posted GitHub notification to Slack channel %s", channel_id)
        return {"channel_id": channel_id, "ok": True}
    return None
