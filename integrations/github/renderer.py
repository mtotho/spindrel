"""GitHubRenderer — Phase G of the Integration Delivery refactor.

The single, in-process GitHub delivery path. Replaces
``integrations/github/dispatcher.py`` (the legacy task-based path)
which was a consumer of ``app/agent/dispatchers.py``.

GitHub is reply-only — the integration posts agent responses as
top-level issue / PR comments. There's no streaming edit equivalent on
the API surface (you can edit a comment, but the use case here is
"reply with the agent's response", not "stream tokens"), so the
renderer only handles the final ``TURN_ENDED`` and free-form
``NEW_MESSAGE`` events. Token streaming is silently skipped via
capability gating upstream.

Self-registers via ``_register()`` at module import time. The
integration discovery loop in ``integrations/__init__.py:_load_single_integration``
auto-imports this file alongside ``dispatcher.py``/``hooks.py``, so
``app/main.py`` does not need any explicit import.
"""
from __future__ import annotations

import logging
from typing import ClassVar

import httpx

from integrations.sdk import (
    Capability, ChannelEvent, ChannelEventKind,
    DispatchTarget, OutboundAction, DeliveryReceipt,
    renderer_registry,
)
from integrations.github.target import GitHubTarget

logger = logging.getLogger(__name__)


_GITHUB_API = "https://api.github.com"
_MAX_COMMENT_LEN = 65536  # GitHub's hard cap on comment body length

_http = httpx.AsyncClient(timeout=30.0)


def _split_body(text: str, max_len: int = _MAX_COMMENT_LEN) -> list[str]:
    """Split a comment body that exceeds GitHub's max length.

    Ported verbatim from the legacy dispatcher. Prefers a newline split
    near the boundary so chunks break cleanly on paragraph edges.
    """
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def _get_token() -> str:
    """Read the GitHub bot token from integration config.

    Lazily imported so the renderer module loads cleanly even when
    the github integration's config isn't available (e.g. running
    unrelated tests with the integration disabled).
    """
    from integrations.github.config import settings
    return settings.GITHUB_TOKEN


async def _post_comment(
    token: str, owner: str, repo: str, issue_number: int, body: str,
) -> bool:
    """Post (or split-post) a comment on a GitHub issue / PR."""
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
                "GitHubRenderer: failed to post comment on %s/%s#%s",
                owner, repo, issue_number,
            )
            return False
    return True


class GitHubRenderer:
    """Channel renderer for GitHub issue / PR comment delivery."""

    integration_id: ClassVar[str] = "github"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.TEXT,
        Capability.RICH_TEXT,  # GitHub markdown
        Capability.MENTIONS,    # @user
    })
    # Notably absent: STREAMING_EDIT, INLINE_BUTTONS, ATTACHMENTS,
    # APPROVAL_BUTTONS, REACTIONS — none of these map cleanly to a
    # comment-only delivery surface.

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, GitHubTarget):
            return DeliveryReceipt.failed(
                f"GitHubRenderer received non-github target: "
                f"{type(target).__name__}",
                retryable=False,
            )

        # Issue number is the comment thread we'd reply on. Without it,
        # the event is informational (e.g. a push event with no PR
        # context) — silently skip.
        if target.issue_number is None:
            return DeliveryReceipt.skipped(
                "github target has no issue_number — informational event"
            )

        kind = event.kind
        try:
            if kind == ChannelEventKind.TURN_ENDED:
                return await self._handle_turn_ended(event, target)
            if kind == ChannelEventKind.NEW_MESSAGE:
                return await self._handle_new_message(event, target)
        except Exception as exc:
            logger.exception(
                "GitHubRenderer.render: unexpected failure for %s",
                kind.value,
            )
            return DeliveryReceipt.failed(f"unexpected: {exc}", retryable=True)

        return DeliveryReceipt.skipped(
            f"github does not handle {kind.value}"
        )

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped(
            "github outbound actions are not wired"
        )

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        return False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_turn_ended(
        self, event: ChannelEvent, target: GitHubTarget,
    ) -> DeliveryReceipt:
        payload = event.payload
        result_text = (getattr(payload, "result", None) or "").strip()
        error_text = (getattr(payload, "error", None) or "").strip()

        if result_text:
            body = result_text
        elif error_text:
            body = f"⚠️ Agent error: {error_text}"
        else:
            return DeliveryReceipt.skipped("turn_ended with empty body")

        token = _get_token()
        if not token:
            return DeliveryReceipt.failed(
                "GITHUB_TOKEN not configured", retryable=False,
            )

        # ``target.issue_number`` is non-None here — checked at the top of render().
        ok = await _post_comment(
            token, target.owner, target.repo, target.issue_number, body,  # type: ignore[arg-type]
        )
        if not ok:
            return DeliveryReceipt.failed(
                f"github comment post failed for {target.owner}/{target.repo}#{target.issue_number}",
                retryable=True,
            )
        return DeliveryReceipt.ok()

    async def _handle_new_message(
        self, event: ChannelEvent, target: GitHubTarget,
    ) -> DeliveryReceipt:
        payload = event.payload
        msg = getattr(payload, "message", None)
        if msg is None:
            return DeliveryReceipt.skipped("new_message without message payload")

        role = getattr(msg, "role", "") or ""
        if role in ("tool", "system"):
            return DeliveryReceipt.skipped(f"github skips internal role={role}")
        if role == "user":
            msg_metadata = getattr(msg, "metadata", None) or {}
            if msg_metadata.get("source") == "github":
                return DeliveryReceipt.skipped(
                    "github skips own-origin user message (echo prevention)"
                )

        text = (getattr(msg, "content", "") or "").strip()
        if not text:
            return DeliveryReceipt.skipped("new_message with empty content")

        token = _get_token()
        if not token:
            return DeliveryReceipt.failed(
                "GITHUB_TOKEN not configured", retryable=False,
            )

        ok = await _post_comment(
            token, target.owner, target.repo, target.issue_number, text,  # type: ignore[arg-type]
        )
        if not ok:
            return DeliveryReceipt.failed(
                f"github comment post failed for {target.owner}/{target.repo}#{target.issue_number}",
                retryable=True,
            )
        return DeliveryReceipt.ok()


# ---------------------------------------------------------------------------
# Self-registration — same idempotent pattern as the other renderers
# ---------------------------------------------------------------------------


def _register() -> None:
    if renderer_registry.get(GitHubRenderer.integration_id) is None:
        renderer_registry.register(GitHubRenderer())


_register()
