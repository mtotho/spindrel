"""Event handlers for GitHub webhook events.

Each handler parses a GitHub event payload into a human-readable message,
a run_agent flag, a comment_target for reply delivery, and an optional
component-vocabulary envelope for rich UI rendering.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from integrations.sdk import sanitize_unicode

logger = logging.getLogger(__name__)

_COMPONENTS_CT = "application/vnd.spindrel.components+json"


@dataclass
class ParsedEvent:
    """Result of parsing a GitHub webhook event."""
    message: str
    run_agent: bool
    comment_target: dict | None  # {"type": "issue_comment", "issue_number": N} or None
    owner: str
    repo: str
    sender: str
    envelope: dict | None = field(default=None)  # Component-vocabulary envelope for UI


def parse_event(event_type: str, payload: dict[str, Any]) -> ParsedEvent | None:
    """Parse a GitHub webhook payload into a ParsedEvent.

    Returns None if the event should be ignored entirely.
    """
    handler = _HANDLERS.get(event_type)
    if handler is None:
        logger.debug("No handler for GitHub event type: %s", event_type)
        return None
    result = handler(payload)
    if result is not None:
        result.message = sanitize_unicode(result.message)
    return result


def _repo_info(payload: dict) -> tuple[str, str]:
    """Extract owner/repo from payload."""
    repo = payload.get("repository", {})
    full_name = repo.get("full_name", "unknown/unknown")
    parts = full_name.split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else "unknown"


def _sender(payload: dict) -> str:
    return payload.get("sender", {}).get("login", "unknown")


def _gh_url(owner: str, repo: str, path: str = "") -> str:
    base = f"https://github.com/{owner}/{repo}"
    return f"{base}/{path}" if path else base


def _envelope(plain_body: str, components: list[dict]) -> dict:
    """Build a component-vocabulary envelope."""
    return {
        "content_type": _COMPONENTS_CT,
        "display": "inline",
        "plain_body": plain_body,
        "body": json.dumps({"v": 1, "components": components}),
        "truncated": False,
        "record_id": None,
        "byte_size": 0,
    }


def _state_color(state: str, merged: bool = False) -> str:
    if merged:
        return "accent"
    return "success" if state == "open" else "muted"


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

        components: list[dict] = [
            {"type": "heading", "text": f"PR #{number}: {title}", "level": 2},
            {"type": "status", "text": "opened", "color": "success"},
            {"type": "properties", "items": [
                {"label": "Author", "value": f"@{sender}"},
                {"label": "Branch", "value": f"{head_ref} → {base_ref}"},
                {"label": "Stats", "value": f"+{additions} −{deletions} across {changed} files"},
            ], "layout": "inline"},
            {"type": "links", "items": [
                {"url": pr.get("html_url", _gh_url(owner, repo, f"pull/{number}")),
                 "title": f"View PR #{number}", "icon": "github"},
            ]},
        ]
        if body:
            components.append({
                "type": "section", "label": "Description",
                "collapsible": True, "defaultOpen": False,
                "children": [{"type": "text", "content": _truncate(body, 1000), "markdown": True}],
            })

        return ParsedEvent(
            message=msg,
            run_agent=True,
            comment_target={"type": "issue_comment", "issue_number": number},
            owner=owner, repo=repo, sender=sender,
            envelope=_envelope(f"PR #{number}: {title} opened by @{sender}", components),
        )

    if action == "synchronize":
        commits = payload.get("after", "")[:7]
        msg = f"PR #{number} updated ({title}) — new head: {commits}"
        components = [
            {"type": "properties", "items": [
                {"label": "PR", "value": f"#{number} {title}"},
                {"label": "New head", "value": commits},
            ], "layout": "inline"},
            {"type": "links", "items": [
                {"url": pr.get("html_url", _gh_url(owner, repo, f"pull/{number}")),
                 "title": f"View PR #{number}", "icon": "github"},
            ]},
        ]
        return ParsedEvent(
            message=msg, run_agent=False, comment_target=None,
            owner=owner, repo=repo, sender=sender,
            envelope=_envelope(msg, components),
        )

    if action in ("closed",):
        merged = pr.get("merged", False)
        verb = "merged" if merged else "closed"
        msg = f"PR #{number} {verb}: {title}"
        components = [
            {"type": "heading", "text": f"PR #{number}: {title}", "level": 3},
            {"type": "status", "text": verb, "color": _state_color("closed", merged)},
            {"type": "links", "items": [
                {"url": pr.get("html_url", _gh_url(owner, repo, f"pull/{number}")),
                 "title": f"View PR #{number}", "icon": "github"},
            ]},
        ]
        return ParsedEvent(
            message=msg, run_agent=False, comment_target=None,
            owner=owner, repo=repo, sender=sender,
            envelope=_envelope(msg, components),
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

        props = [{"label": "Author", "value": f"@{sender}"}]
        if labels:
            props.append({"label": "Labels", "value": labels})

        components: list[dict] = [
            {"type": "heading", "text": f"Issue #{number}: {title}", "level": 2},
            {"type": "status", "text": "opened", "color": "success"},
            {"type": "properties", "items": props, "layout": "inline"},
            {"type": "links", "items": [
                {"url": issue.get("html_url", _gh_url(owner, repo, f"issues/{number}")),
                 "title": f"View issue #{number}", "icon": "github"},
            ]},
        ]
        if body:
            components.append({
                "type": "section", "label": "Description",
                "collapsible": True, "defaultOpen": False,
                "children": [{"type": "text", "content": _truncate(body, 1000), "markdown": True}],
            })

        return ParsedEvent(
            message=msg,
            run_agent=True,
            comment_target={"type": "issue_comment", "issue_number": number},
            owner=owner, repo=repo, sender=sender,
            envelope=_envelope(f"Issue #{number}: {title} opened by @{sender}", components),
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

    components: list[dict] = [
        {"type": "heading", "text": f"Comment on {context} #{number}: {title}", "level": 3},
        {"type": "properties", "items": [
            {"label": "Author", "value": f"@{sender}"},
        ], "layout": "inline"},
        {"type": "links", "items": [
            {"url": comment.get("html_url", _gh_url(owner, repo, f"issues/{number}")),
             "title": f"View comment on {context} #{number}", "icon": "github"},
        ]},
    ]
    if body:
        components.append({"type": "text", "content": _truncate(body, 1000), "markdown": True})

    return ParsedEvent(
        message=msg,
        run_agent=True,
        comment_target={"type": "issue_comment", "issue_number": number},
        owner=owner, repo=repo, sender=sender,
        envelope=_envelope(f"Comment on {context} #{number} by @{sender}", components),
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

    state_color = "danger" if state == "changes_requested" else "success" if state == "approved" else "muted"
    state_label = state.replace("_", " ")

    components: list[dict] = [
        {"type": "heading", "text": f"Review on PR #{number}: {title}", "level": 3},
        {"type": "status", "text": state_label, "color": state_color},
        {"type": "properties", "items": [
            {"label": "Reviewer", "value": f"@{sender}"},
        ], "layout": "inline"},
        {"type": "links", "items": [
            {"url": review.get("html_url", _gh_url(owner, repo, f"pull/{number}")),
             "title": f"View review on PR #{number}", "icon": "github"},
        ]},
    ]
    if body:
        components.append({"type": "text", "content": _truncate(body, 1000), "markdown": True})

    return ParsedEvent(
        message=msg,
        run_agent=state == "changes_requested",
        comment_target={"type": "issue_comment", "issue_number": number} if state == "changes_requested" else None,
        owner=owner, repo=repo, sender=sender,
        envelope=_envelope(f"PR #{number} review: {state_label} by @{sender}", components),
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

    file_ref = path
    if line:
        file_ref += f":{line}"

    components: list[dict] = [
        {"type": "heading", "text": f"Inline comment on PR #{number}: {title}", "level": 3},
        {"type": "properties", "items": [
            {"label": "Author", "value": f"@{sender}"},
            {"label": "File", "value": file_ref},
        ], "layout": "inline"},
        {"type": "links", "items": [
            {"url": comment.get("html_url", _gh_url(owner, repo, f"pull/{number}")),
             "title": f"View comment on PR #{number}", "icon": "github"},
        ]},
    ]
    if body:
        components.append({"type": "text", "content": _truncate(body, 1000), "markdown": True})

    return ParsedEvent(
        message=msg,
        run_agent=True,
        comment_target={"type": "issue_comment", "issue_number": number},
        owner=owner, repo=repo, sender=sender,
        envelope=_envelope(f"Inline comment on PR #{number} by @{sender}", components),
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

    # Rich components
    components: list[dict] = [
        {"type": "heading", "text": f"Push to {branch}{force_tag}", "level": 3},
    ]
    if forced:
        components.append({"type": "status", "text": "force push", "color": "warning"})
    components.append({"type": "properties", "items": [
        {"label": "Author", "value": f"@{sender}"},
        {"label": "Commits", "value": str(len(commits))},
        {"label": "Branch", "value": branch},
    ], "layout": "inline"})

    if commits:
        rows = [
            [c.get("id", "")[:7], c.get("message", "").splitlines()[0][:80]]
            for c in commits[:10]
        ]
        components.append(
            {"type": "table", "columns": ["SHA", "Message"], "rows": rows, "compact": True}
        )

    compare_url = payload.get("compare", "")
    if compare_url:
        components.append({"type": "links", "items": [
            {"url": compare_url, "title": "View diff on GitHub", "icon": "github"},
        ]})

    return ParsedEvent(
        message=msg, run_agent=False, comment_target=None,
        owner=owner, repo=repo, sender=sender,
        envelope=_envelope(f"Push to {branch}: {len(commits)} commit(s)", components),
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

    components: list[dict] = [
        {"type": "heading", "text": f"Release {tag}: {name}", "level": 2},
        {"type": "status", "text": "published", "color": "success"},
        {"type": "properties", "items": [
            {"label": "Author", "value": f"@{sender}"},
            {"label": "Tag", "value": tag},
        ], "layout": "inline"},
        {"type": "links", "items": [
            {"url": release.get("html_url", _gh_url(owner, repo, f"releases/tag/{tag}")),
             "title": f"View release {tag}", "icon": "github"},
        ]},
    ]
    if body:
        components.append({
            "type": "section", "label": "Release Notes",
            "collapsible": True, "defaultOpen": False,
            "children": [{"type": "text", "content": _truncate(body, 1000), "markdown": True}],
        })

    return ParsedEvent(
        message=msg, run_agent=False, comment_target=None,
        owner=owner, repo=repo, sender=sender,
        envelope=_envelope(f"Release {tag}: {name}", components),
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

    components: list[dict] = [
        {"type": "heading", "text": f"Discussion: {title}", "level": 3},
        {"type": "properties", "items": [
            {"label": "Author", "value": f"@{sender}"},
        ], "layout": "inline"},
        {"type": "links", "items": [
            {"url": discussion.get("html_url", _gh_url(owner, repo, "discussions")),
             "title": "View discussion", "icon": "github"},
        ]},
    ]
    if body:
        components.append({"type": "text", "content": _truncate(body, 1000), "markdown": True})

    return ParsedEvent(
        message=msg, run_agent=False, comment_target=None,
        owner=owner, repo=repo, sender=sender,
        envelope=_envelope(f"Discussion: {title} by @{sender}", components),
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

    components: list[dict] = [
        {"type": "heading", "text": f"Comment on discussion: {title}", "level": 3},
        {"type": "properties", "items": [
            {"label": "Author", "value": f"@{sender}"},
        ], "layout": "inline"},
    ]
    if body:
        components.append({"type": "text", "content": _truncate(body, 1000), "markdown": True})

    return ParsedEvent(
        message=msg, run_agent=False, comment_target=None,
        owner=owner, repo=repo, sender=sender,
        envelope=_envelope(f"Discussion comment by @{sender}", components),
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
