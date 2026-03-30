"""Event handlers for GitHub webhook events.

Each handler parses a GitHub event payload into a human-readable message,
a run_agent flag, and a comment_target for reply delivery.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedEvent:
    """Result of parsing a GitHub webhook event."""
    message: str
    run_agent: bool
    comment_target: dict | None  # {"type": "issue_comment", "issue_number": N} or None
    owner: str
    repo: str
    sender: str


def parse_event(event_type: str, payload: dict[str, Any]) -> ParsedEvent | None:
    """Parse a GitHub webhook payload into a ParsedEvent.

    Returns None if the event should be ignored entirely.
    """
    handler = _HANDLERS.get(event_type)
    if handler is None:
        logger.debug("No handler for GitHub event type: %s", event_type)
        return None
    return handler(payload)


def _repo_info(payload: dict) -> tuple[str, str]:
    """Extract owner/repo from payload."""
    repo = payload.get("repository", {})
    full_name = repo.get("full_name", "unknown/unknown")
    parts = full_name.split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else "unknown"


def _sender(payload: dict) -> str:
    return payload.get("sender", {}).get("login", "unknown")


# ---------------------------------------------------------------------------
# Individual event handlers
# ---------------------------------------------------------------------------

def _handle_pull_request(payload: dict) -> ParsedEvent | None:
    action = payload.get("action", "")
    pr = payload.get("pull_request", {})
    owner, repo = _repo_info(payload)
    number = pr.get("number", 0)
    title = pr.get("title", "")
    sender = _sender(payload)

    if action == "opened":
        body = pr.get("body") or ""
        changed = pr.get("changed_files", 0)
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        head_ref = pr.get("head", {}).get("ref", "")
        base_ref = pr.get("base", {}).get("ref", "")
        msg = (
            f"New PR #{number}: {title}\n"
            f"By @{sender} | {head_ref} -> {base_ref}\n"
            f"+{additions} -{deletions} across {changed} files\n"
        )
        if body:
            msg += f"\n{_truncate(body, 2000)}"
        return ParsedEvent(
            message=msg,
            run_agent=True,
            comment_target={"type": "issue_comment", "issue_number": number},
            owner=owner, repo=repo, sender=sender,
        )

    if action == "synchronize":
        commits = payload.get("after", "")[:7]
        msg = f"PR #{number} updated ({title}) — new head: {commits}"
        return ParsedEvent(
            message=msg, run_agent=False, comment_target=None,
            owner=owner, repo=repo, sender=sender,
        )

    if action in ("closed",):
        merged = pr.get("merged", False)
        verb = "merged" if merged else "closed"
        msg = f"PR #{number} {verb}: {title}"
        return ParsedEvent(
            message=msg, run_agent=False, comment_target=None,
            owner=owner, repo=repo, sender=sender,
        )

    return None


def _handle_issues(payload: dict) -> ParsedEvent | None:
    action = payload.get("action", "")
    issue = payload.get("issue", {})
    owner, repo = _repo_info(payload)
    number = issue.get("number", 0)
    title = issue.get("title", "")
    sender = _sender(payload)

    if action == "opened":
        body = issue.get("body") or ""
        labels = ", ".join(l.get("name", "") for l in issue.get("labels", []))
        msg = f"New issue #{number}: {title}\nBy @{sender}"
        if labels:
            msg += f"\nLabels: {labels}"
        if body:
            msg += f"\n\n{_truncate(body, 2000)}"
        return ParsedEvent(
            message=msg,
            run_agent=True,
            comment_target={"type": "issue_comment", "issue_number": number},
            owner=owner, repo=repo, sender=sender,
        )

    return None


def _handle_issue_comment(payload: dict) -> ParsedEvent | None:
    action = payload.get("action", "")
    if action != "created":
        return None

    comment = payload.get("comment", {})
    issue = payload.get("issue", {})
    owner, repo = _repo_info(payload)
    number = issue.get("number", 0)
    title = issue.get("title", "")
    sender = _sender(payload)
    body = comment.get("body", "")
    is_pr = "pull_request" in issue

    context = "PR" if is_pr else "Issue"
    msg = (
        f"Comment on {context} #{number} ({title}) by @{sender}:\n\n"
        f"{_truncate(body, 3000)}"
    )
    return ParsedEvent(
        message=msg,
        run_agent=True,
        comment_target={"type": "issue_comment", "issue_number": number},
        owner=owner, repo=repo, sender=sender,
    )


def _handle_pull_request_review(payload: dict) -> ParsedEvent | None:
    review = payload.get("review", {})
    pr = payload.get("pull_request", {})
    owner, repo = _repo_info(payload)
    number = pr.get("number", 0)
    title = pr.get("title", "")
    sender = _sender(payload)
    state = review.get("state", "")
    body = review.get("body") or ""

    msg = (
        f"PR review on #{number} ({title}) by @{sender}: {state}\n"
    )
    if body:
        msg += f"\n{_truncate(body, 2000)}"

    return ParsedEvent(
        message=msg,
        run_agent=state == "changes_requested",
        comment_target={"type": "issue_comment", "issue_number": number} if state == "changes_requested" else None,
        owner=owner, repo=repo, sender=sender,
    )


def _handle_pull_request_review_comment(payload: dict) -> ParsedEvent | None:
    action = payload.get("action", "")
    if action != "created":
        return None

    comment = payload.get("comment", {})
    pr = payload.get("pull_request", {})
    owner, repo = _repo_info(payload)
    number = pr.get("number", 0)
    title = pr.get("title", "")
    sender = _sender(payload)
    body = comment.get("body", "")
    path = comment.get("path", "")
    line = comment.get("line") or comment.get("original_line", "")

    msg = (
        f"Inline review comment on PR #{number} ({title}) by @{sender}\n"
        f"File: {path}"
    )
    if line:
        msg += f":{line}"
    msg += f"\n\n{_truncate(body, 2000)}"

    return ParsedEvent(
        message=msg,
        run_agent=True,
        comment_target={"type": "issue_comment", "issue_number": number},
        owner=owner, repo=repo, sender=sender,
    )


def _handle_push(payload: dict) -> ParsedEvent | None:
    owner, repo = _repo_info(payload)
    sender = _sender(payload)
    ref = payload.get("ref", "")
    commits = payload.get("commits", [])
    forced = payload.get("forced", False)

    branch = ref.removeprefix("refs/heads/")
    commit_list = "\n".join(
        f"  - {c.get('id', '')[:7]} {c.get('message', '').splitlines()[0]}"
        for c in commits[:10]
    )
    extra = f"\n  ... and {len(commits) - 10} more" if len(commits) > 10 else ""
    force_tag = " (force push)" if forced else ""

    msg = (
        f"Push to {branch}{force_tag}: {len(commits)} commit(s) by @{sender}\n"
        f"{commit_list}{extra}"
    )
    return ParsedEvent(
        message=msg, run_agent=False, comment_target=None,
        owner=owner, repo=repo, sender=sender,
    )


def _handle_release(payload: dict) -> ParsedEvent | None:
    action = payload.get("action", "")
    if action != "published":
        return None

    release = payload.get("release", {})
    owner, repo = _repo_info(payload)
    sender = _sender(payload)
    tag = release.get("tag_name", "")
    name = release.get("name") or tag
    body = release.get("body") or ""

    msg = f"Release {tag}: {name}\nBy @{sender}"
    if body:
        msg += f"\n\n{_truncate(body, 2000)}"

    return ParsedEvent(
        message=msg, run_agent=False, comment_target=None,
        owner=owner, repo=repo, sender=sender,
    )


def _handle_discussion(payload: dict) -> ParsedEvent | None:
    action = payload.get("action", "")
    if action != "created":
        return None

    discussion = payload.get("discussion", {})
    owner, repo = _repo_info(payload)
    sender = _sender(payload)
    title = discussion.get("title", "")
    body = discussion.get("body") or ""

    msg = f"New discussion: {title}\nBy @{sender}"
    if body:
        msg += f"\n\n{_truncate(body, 2000)}"

    return ParsedEvent(
        message=msg, run_agent=False, comment_target=None,
        owner=owner, repo=repo, sender=sender,
    )


def _handle_discussion_comment(payload: dict) -> ParsedEvent | None:
    action = payload.get("action", "")
    if action != "created":
        return None

    comment = payload.get("comment", {})
    discussion = payload.get("discussion", {})
    owner, repo = _repo_info(payload)
    sender = _sender(payload)
    title = discussion.get("title", "")
    body = comment.get("body", "")

    msg = (
        f"Comment on discussion \"{title}\" by @{sender}:\n\n"
        f"{_truncate(body, 2000)}"
    )
    return ParsedEvent(
        message=msg, run_agent=False, comment_target=None,
        owner=owner, repo=repo, sender=sender,
    )


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_HANDLERS = {
    "pull_request": _handle_pull_request,
    "issues": _handle_issues,
    "issue_comment": _handle_issue_comment,
    "pull_request_review": _handle_pull_request_review,
    "pull_request_review_comment": _handle_pull_request_review_comment,
    "push": _handle_push,
    "release": _handle_release,
    "discussion": _handle_discussion,
    "discussion_comment": _handle_discussion_comment,
}


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... (truncated)"
