"""GitHubTarget — typed dispatch destination for the GitHub integration.

Self-registers with ``app.domain.target_registry`` at module import.
The integration discovery loop auto-imports this module before
``renderer.py``.

The github webhook router stores ``dispatch_config`` with a nested
``comment_target: {"type": "issue_comment", "issue_number": N}`` shape
plus arbitrary event metadata (``token``, ``sender``, ``action``, …).
``GitHubTarget.from_dispatch_config`` flattens that into the typed
fields the dataclass actually carries — keeping the dispatch_config
massaging inside the integration package, not inside ``app/``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from integrations.sdk import target_registry, BaseTarget as _BaseTarget


@dataclass(frozen=True)
class GitHubTarget(_BaseTarget):
    """GitHub issue / PR comment destination.

    The token is NOT carried on the target — it's a global env var
    (``GITHUB_TOKEN``) read by ``GitHubRenderer`` at render time. The
    legacy ``GitHubDispatcher`` did the same.

    ``issue_number`` is None for events that don't have a comment thread
    to reply on (e.g. push events). The renderer treats those as
    informational and skips the network call.
    """

    type: ClassVar[Literal["github"]] = "github"
    integration_id: ClassVar[str] = "github"

    owner: str
    repo: str
    issue_number: int | None = None

    @classmethod
    def from_dispatch_config(cls, payload: dict) -> "GitHubTarget":
        """Flatten the github webhook's dispatch_config shape into the typed target.

        The webhook stores ``comment_target.issue_number`` as a nested
        dict so future event metadata can land alongside it. The typed
        target only cares about ``issue_number``. Strips ``token`` and
        any event-only metadata that aren't part of the destination.
        """
        owner = payload.get("owner", "")
        repo = payload.get("repo", "")
        issue_number = payload.get("issue_number")
        if issue_number is None:
            comment_target = payload.get("comment_target") or {}
            issue_number = comment_target.get("issue_number")
        return cls(owner=owner, repo=repo, issue_number=issue_number)


target_registry.register(GitHubTarget)
