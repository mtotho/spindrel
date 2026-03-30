"""GitHub task result dispatcher.

Posts agent responses as top-level issue/PR comments via the GitHub API.
Registers with the dispatcher registry at import time.
"""
from __future__ import annotations

import logging

import httpx

from app.agent.dispatchers import register

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_MAX_COMMENT_LEN = 65536  # GitHub's max comment body length
_http = httpx.AsyncClient(timeout=30.0)


async def _post_comment(token: str, owner: str, repo: str, issue_number: int, body: str) -> bool:
    """Post a comment on a GitHub issue/PR. Splits if body exceeds limit."""
    chunks = _split_body(body, _MAX_COMMENT_LEN)
    for chunk in chunks:
        try:
            r = await _http.post(
                f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
                json={"body": chunk},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            r.raise_for_status()
        except Exception:
            logger.exception(
                "Failed to post GitHub comment on %s/%s#%s", owner, repo, issue_number
            )
            return False
    return True


def _split_body(text: str, max_len: int) -> list[str]:
    """Split text into chunks that fit within max_len."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at a newline
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


class GitHubDispatcher:
    async def deliver(self, task, result: str, client_actions: list[dict] | None = None) -> None:
        cfg = task.dispatch_config or {}
        target = cfg.get("comment_target")
        if not target:
            return  # informational event, no reply needed

        token = cfg.get("token") or _get_token()
        owner = cfg.get("owner")
        repo = cfg.get("repo")
        issue_number = target.get("issue_number")

        if not all((token, owner, repo, issue_number)):
            logger.warning("GitHubDispatcher: missing config for task %s", task.id)
            return

        ok = await _post_comment(token, owner, repo, issue_number, result)
        if not ok:
            logger.error("GitHubDispatcher.deliver failed for task %s", task.id)
            return

        from app.services.sessions import store_dispatch_echo
        await store_dispatch_echo(task.session_id, task.client_id, task.bot_id, result)

    async def post_message(self, dispatch_config: dict, text: str, *,
                           bot_id: str | None = None, reply_in_thread: bool = True,
                           username: str | None = None, icon_emoji: str | None = None,
                           icon_url: str | None = None,
                           client_actions: list[dict] | None = None) -> bool:
        target = (dispatch_config or {}).get("comment_target")
        if not target:
            return False

        token = dispatch_config.get("token") or _get_token()
        owner = dispatch_config.get("owner")
        repo = dispatch_config.get("repo")
        issue_number = target.get("issue_number")

        if not all((token, owner, repo, issue_number)):
            return False

        return await _post_comment(token, owner, repo, issue_number, text)


def _get_token() -> str:
    """Get GitHub token from integration config."""
    from integrations.github.config import settings
    return settings.GITHUB_TOKEN


register("github", GitHubDispatcher())
