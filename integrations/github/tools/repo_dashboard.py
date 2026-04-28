"""GitHub repository dashboard tools."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
from sqlalchemy import select

from integrations import sdk as reg
from integrations.github.config import settings

_GITHUB_API = "https://api.github.com"
_http = httpx.AsyncClient(timeout=30.0)
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _split_repository(repository: str) -> tuple[str, str]:
    repo = (repository or "").strip()
    if repo.startswith("github:"):
        repo = repo.split(":", 1)[1]
    if not _REPOSITORY_RE.match(repo):
        raise ValueError("Repository must be in owner/repo form.")
    owner, name = repo.split("/", 1)
    return owner, name


def _repo_from_client_id(client_id: str | None) -> str | None:
    if not client_id or not client_id.startswith("github:"):
        return None
    repo = client_id.split(":", 1)[1].strip()
    return repo if _REPOSITORY_RE.match(repo) else None


async def _current_channel_repository() -> str | None:
    channel_id = reg.current_channel_id.get()
    if channel_id is None:
        return None
    async with reg.async_session() as db:
        stmt = (
            select(reg.ChannelIntegration)
            .where(
                reg.ChannelIntegration.channel_id == channel_id,
                reg.ChannelIntegration.integration_type == "github",
                reg.ChannelIntegration.client_id.like("github:%"),
            )
            .order_by(reg.ChannelIntegration.created_at.asc())
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
    return _repo_from_client_id(row.client_id if row else None)


async def _resolve_repository(repository: str | None) -> tuple[str, str, str]:
    repo = (repository or "").strip()
    if not repo:
        repo = await _current_channel_repository() or ""
    owner, name = _split_repository(repo)
    return owner, name, f"{owner}/{name}"


async def _get_json(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    optional: bool = False,
) -> tuple[Any, dict[str, str]]:
    resp = await _http.get(f"{_GITHUB_API}{path}", headers=_headers(), params=params)
    if optional and resp.status_code in {403, 404}:
        return None, dict(resp.headers)
    resp.raise_for_status()
    return resp.json(), dict(resp.headers)


def _rate_limit(headers: dict[str, str]) -> dict[str, int | None]:
    def _int(name: str) -> int | None:
        try:
            return int(headers.get(name, ""))
        except ValueError:
            return None

    return {
        "remaining": _int("x-ratelimit-remaining"),
        "limit": _int("x-ratelimit-limit"),
        "reset": _int("x-ratelimit-reset"),
    }


def _as_bool(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _commit_row(item: dict[str, Any]) -> dict[str, Any]:
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    gh_author = item.get("author") or {}
    message = str(commit.get("message") or "").splitlines()[0]
    return {
        "sha": str(item.get("sha") or "")[:12],
        "message": message,
        "author": gh_author.get("login") or author.get("name") or "unknown",
        "date": author.get("date"),
        "url": item.get("html_url"),
    }


def _pr_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title") or "",
        "author": (item.get("user") or {}).get("login") or "unknown",
        "updated_at": item.get("updated_at"),
        "created_at": item.get("created_at"),
        "draft": bool(item.get("draft")),
        "head": (item.get("head") or {}).get("ref"),
        "base": (item.get("base") or {}).get("ref"),
        "labels": [label.get("name") for label in item.get("labels") or [] if label.get("name")],
        "url": item.get("html_url"),
    }


def _issue_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title") or "",
        "state": item.get("state") or "open",
        "author": (item.get("user") or {}).get("login") or "unknown",
        "updated_at": item.get("updated_at"),
        "created_at": item.get("created_at"),
        "comments": item.get("comments") or 0,
        "assignees": [
            assignee.get("login")
            for assignee in item.get("assignees") or []
            if assignee.get("login")
        ],
        "labels": [label.get("name") for label in item.get("labels") or [] if label.get("name")],
        "url": item.get("html_url"),
    }


def _workflow_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name") or item.get("display_title") or "Workflow",
        "status": item.get("status"),
        "conclusion": item.get("conclusion"),
        "branch": item.get("head_branch"),
        "event": item.get("event"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "url": item.get("html_url"),
    }


def _release_row(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "name": item.get("name") or item.get("tag_name"),
        "tag_name": item.get("tag_name"),
        "published_at": item.get("published_at"),
        "draft": bool(item.get("draft")),
        "prerelease": bool(item.get("prerelease")),
        "url": item.get("html_url"),
    }


def _dashboard_payload(
    *,
    repository: dict[str, Any],
    commits: list[dict[str, Any]],
    prs: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
    release: dict[str, Any] | None,
    rate_limit: dict[str, int | None],
    actions_error: str | None = None,
) -> dict[str, Any]:
    latest_workflow = workflows[0] if workflows else None
    return {
        "repository": repository,
        "health": {
            "open_prs": len(prs),
            "open_issues": len(issues),
            "latest_commit": commits[0] if commits else None,
            "latest_workflow": latest_workflow,
            "latest_release": release,
            "rate_limit": rate_limit,
            "actions_error": actions_error,
        },
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "actions": workflows,
        "latest_release": release,
    }


@reg.register({"type": "function", "function": {
    "name": "github_repo_dashboard",
    "description": "Build a rich GitHub repository dashboard with recent commits, open PRs, open issues, latest workflow runs, release info, and health counts.",
    "parameters": {
        "type": "object",
        "properties": {
            "repository": {
                "type": "string",
                "description": "Repository in owner/repo form. If omitted, uses the current channel's GitHub binding.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum commits, PRs, and issues to return.",
                "default": 20,
            },
            "include_actions": {
                "type": "boolean",
                "description": "Include recent GitHub Actions workflow runs.",
                "default": True,
            },
        },
    },
}}, returns={
    "type": "object",
    "properties": {
        "repository": {"type": "object"},
        "health": {"type": "object"},
        "commits": {"type": "array"},
        "prs": {"type": "array"},
        "issues": {"type": "array"},
        "actions": {"type": "array"},
        "latest_release": {"type": ["object", "null"]},
        "error": {"type": "string"},
    },
})
async def github_repo_dashboard(
    repository: str | None = None,
    limit: int = 20,
    include_actions: bool = True,
) -> str:
    try:
        owner, repo, full_name = await _resolve_repository(repository)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    per_page = max(1, min(int(limit or 20), 50))
    include_actions_bool = _as_bool(include_actions, default=True)
    try:
        repo_json, repo_headers = await _get_json(f"/repos/{owner}/{repo}")
        default_branch = repo_json.get("default_branch") or "main"
        repo_info = {
            "owner": owner,
            "name": repo,
            "full_name": full_name,
            "default_branch": default_branch,
            "description": repo_json.get("description"),
            "private": bool(repo_json.get("private")),
            "archived": bool(repo_json.get("archived")),
            "html_url": repo_json.get("html_url") or f"https://github.com/{full_name}",
            "stars": repo_json.get("stargazers_count") or 0,
            "forks": repo_json.get("forks_count") or 0,
            "open_issues_count": repo_json.get("open_issues_count") or 0,
        }

        commits_task = _get_json(
            f"/repos/{owner}/{repo}/commits",
            params={"per_page": per_page, "sha": default_branch},
        )
        prs_task = _get_json(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "open", "sort": "updated", "direction": "desc", "per_page": per_page},
        )
        issues_task = _get_json(
            f"/repos/{owner}/{repo}/issues",
            params={"state": "open", "sort": "updated", "direction": "desc", "per_page": per_page},
        )
        release_task = _get_json(f"/repos/{owner}/{repo}/releases/latest", optional=True)
        actions_task = (
            _get_json(
                f"/repos/{owner}/{repo}/actions/runs",
                params={"per_page": min(per_page, 20)},
                optional=True,
            )
            if include_actions_bool
            else asyncio.sleep(0, result=(None, {}))
        )
        raw_commits, raw_prs, raw_issues, raw_release, raw_actions = await asyncio.gather(
            commits_task,
            prs_task,
            issues_task,
            release_task,
            actions_task,
        )
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300] if exc.response is not None else str(exc)
        return json.dumps({"error": f"GitHub API error: {detail}"}, ensure_ascii=False)
    except httpx.HTTPError as exc:
        return json.dumps({"error": f"GitHub request failed: {exc}"}, ensure_ascii=False)

    commits = [_commit_row(item) for item in (raw_commits[0] or [])]
    prs = [_pr_row(item) for item in (raw_prs[0] or [])]
    issues = [
        _issue_row(item)
        for item in (raw_issues[0] or [])
        if not item.get("pull_request")
    ]
    workflows_payload = raw_actions[0] or {}
    workflows = [_workflow_row(item) for item in workflows_payload.get("workflow_runs", [])] if workflows_payload else []
    actions_error = "GitHub Actions unavailable for this token or repository." if include_actions_bool and raw_actions[0] is None else None

    payload = _dashboard_payload(
        repository=repo_info,
        commits=commits,
        prs=prs,
        issues=issues,
        workflows=workflows,
        release=_release_row(raw_release[0]),
        rate_limit=_rate_limit(repo_headers),
        actions_error=actions_error,
    )
    return json.dumps(payload, ensure_ascii=False)


@reg.register({"type": "function", "function": {
    "name": "github_repo_options",
    "description": "List GitHub repositories from active channel bindings for widget preset pickers.",
    "parameters": {"type": "object", "properties": {}},
}}, returns={
    "type": "object",
    "properties": {
        "repositories": {"type": "array"},
        "count": {"type": "integer"},
    },
})
async def github_repo_options() -> str:
    current_channel = reg.current_channel_id.get()
    async with reg.async_session() as db:
        stmt = (
            select(reg.ChannelIntegration)
            .where(
                reg.ChannelIntegration.integration_type == "github",
                reg.ChannelIntegration.client_id.like("github:%"),
            )
            .order_by(reg.ChannelIntegration.created_at.asc())
        )
        rows = list((await db.execute(stmt)).scalars().all())

    seen: set[str] = set()
    repos: list[dict[str, Any]] = []
    for row in rows:
        repo = _repo_from_client_id(row.client_id)
        if not repo or repo in seen:
            continue
        seen.add(repo)
        is_current = current_channel is not None and row.channel_id == current_channel
        repos.append({
            "repository": repo,
            "label": row.display_name or repo,
            "channel_id": str(row.channel_id),
            "current_channel": is_current,
            "group": "Current channel" if is_current else "GitHub bindings",
        })

    repos.sort(key=lambda item: (not item["current_channel"], item["repository"].lower()))
    return json.dumps({"repositories": repos, "count": len(repos)}, ensure_ascii=False)


@reg.register({"type": "function", "function": {
    "name": "github_set_issue_state",
    "description": "Close or reopen a GitHub issue from a confirmed widget action, optionally posting a comment first.",
    "parameters": {
        "type": "object",
        "properties": {
            "repository": {"type": "string", "description": "Repository in owner/repo form."},
            "issue_number": {"type": "integer", "description": "Issue number."},
            "state": {"type": "string", "enum": ["open", "closed"], "description": "New issue state."},
            "comment": {"type": "string", "description": "Optional issue comment to post before changing state."},
            "confirmed": {"type": "boolean", "description": "Must be true for widget-initiated state changes."},
        },
        "required": ["repository", "issue_number", "state", "confirmed"],
    },
}}, safety_tier="mutating", returns={
    "type": "object",
    "properties": {
        "issue": {"type": "object"},
        "comment_posted": {"type": "boolean"},
        "error": {"type": "string"},
    },
})
async def github_set_issue_state(
    repository: str,
    issue_number: int,
    state: str,
    comment: str | None = None,
    confirmed: bool = False,
) -> str:
    if not confirmed:
        return json.dumps({"error": "Issue state changes require explicit confirmation."}, ensure_ascii=False)
    if state not in {"open", "closed"}:
        return json.dumps({"error": "state must be 'open' or 'closed'."}, ensure_ascii=False)
    try:
        owner, repo = _split_repository(repository)
        comment_posted = False
        if comment and comment.strip():
            comment_resp = await _http.post(
                f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
                headers=_headers(),
                json={"body": comment.strip()},
            )
            comment_resp.raise_for_status()
            comment_posted = True

        issue_resp = await _http.patch(
            f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}",
            headers=_headers(),
            json={"state": state},
        )
        issue_resp.raise_for_status()
        return json.dumps({
            "issue": _issue_row(issue_resp.json()),
            "comment_posted": comment_posted,
        }, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300] if exc.response is not None else str(exc)
        return json.dumps({"error": f"GitHub API error: {detail}"}, ensure_ascii=False)
    except httpx.HTTPError as exc:
        return json.dumps({"error": f"GitHub request failed: {exc}"}, ensure_ascii=False)
