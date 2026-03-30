"""GitHub API tools for the agent."""
from __future__ import annotations

import httpx

from integrations import _register as reg
from integrations.github.config import settings

_GITHUB_API = "https://api.github.com"
_http = httpx.AsyncClient(timeout=30.0)


def _headers(accept: str = "application/vnd.github+json") -> dict:
    return {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


@reg.register({"type": "function", "function": {
    "name": "github_get_pr",
    "description": "Get details of a GitHub pull request including title, body, state, changed files, and diff.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "pull_number": {"type": "integer", "description": "PR number"},
        },
        "required": ["owner", "repo", "pull_number"],
    },
}})
async def github_get_pr(owner: str, repo: str, pull_number: int) -> str:
    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}",
        headers=_headers(),
    )
    r.raise_for_status()
    pr = r.json()

    r_diff = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}",
        headers=_headers("application/vnd.github.v3.diff"),
    )
    diff = r_diff.text if r_diff.status_code == 200 else "(diff unavailable)"
    if len(diff) > 50_000:
        diff = diff[:50_000] + "\n... (diff truncated at 50K chars)"

    r_files = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/files",
        headers=_headers(),
        params={"per_page": 100},
    )
    files = []
    if r_files.status_code == 200:
        files = [
            f"{f['filename']} (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
            for f in r_files.json()
        ]

    lines = [
        f"# PR #{pull_number}: {pr.get('title', '')}",
        f"State: {pr.get('state', '')} | Merged: {pr.get('merged', False)}",
        f"Author: @{pr.get('user', {}).get('login', '')}",
        f"Base: {pr.get('base', {}).get('ref', '')} <- {pr.get('head', {}).get('ref', '')}",
        f"+{pr.get('additions', 0)} -{pr.get('deletions', 0)} across {pr.get('changed_files', 0)} files",
        "",
        "## Body",
        pr.get("body") or "(no description)",
        "",
        "## Changed Files",
        "\n".join(files) or "(none)",
        "",
        "## Diff",
        diff,
    ]
    return "\n".join(lines)


@reg.register({"type": "function", "function": {
    "name": "github_search_issues",
    "description": "Search GitHub issues and pull requests. Returns top 10 results with title, number, state, labels, and URL.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (GitHub search syntax)"},
            "repo": {"type": "string", "description": "Limit to repo (owner/repo format). Optional."},
        },
        "required": ["query"],
    },
}})
async def github_search_issues(query: str, repo: str = "") -> str:
    q = query
    if repo:
        q = f"repo:{repo} {q}"

    r = await _http.get(
        f"{_GITHUB_API}/search/issues",
        headers=_headers(),
        params={"q": q, "per_page": 10, "sort": "updated", "order": "desc"},
    )
    r.raise_for_status()
    data = r.json()

    items = data.get("items", [])
    if not items:
        return f"No results for: {q}"

    lines = [f"Found {data.get('total_count', 0)} results (showing top {len(items)}):\n"]
    for item in items:
        labels = ", ".join(l["name"] for l in item.get("labels", []))
        kind = "PR" if "pull_request" in item else "Issue"
        line = f"- [{kind}] #{item['number']} {item['title']} ({item['state']})"
        if labels:
            line += f" [{labels}]"
        line += f"\n  {item['html_url']}"
        lines.append(line)

    return "\n".join(lines)


@reg.register({"type": "function", "function": {
    "name": "github_post_comment",
    "description": "Post a comment on a GitHub issue or pull request.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "issue_number": {"type": "integer", "description": "Issue or PR number"},
            "body": {"type": "string", "description": "Comment body (Markdown)"},
        },
        "required": ["owner", "repo", "issue_number", "body"],
    },
}})
async def github_post_comment(owner: str, repo: str, issue_number: int, body: str) -> str:
    r = await _http.post(
        f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
        headers=_headers(),
        json={"body": body},
    )
    r.raise_for_status()
    data = r.json()
    return f"Comment posted: {data.get('html_url', '(no url)')}"


@reg.register({"type": "function", "function": {
    "name": "github_list_prs",
    "description": "List pull requests for a GitHub repository.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "PR state filter (default: open)"},
        },
        "required": ["owner", "repo"],
    },
}})
async def github_list_prs(owner: str, repo: str, state: str = "open") -> str:
    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/pulls",
        headers=_headers(),
        params={"state": state, "per_page": 30, "sort": "updated", "direction": "desc"},
    )
    r.raise_for_status()
    prs = r.json()

    if not prs:
        return f"No {state} PRs in {owner}/{repo}"

    lines = [f"{len(prs)} {state} PR(s) in {owner}/{repo}:\n"]
    for pr in prs:
        author = pr.get("user", {}).get("login", "")
        labels = ", ".join(l["name"] for l in pr.get("labels", []))
        line = f"- #{pr['number']} {pr['title']} by @{author}"
        if labels:
            line += f" [{labels}]"
        lines.append(line)

    return "\n".join(lines)


@reg.register({"type": "function", "function": {
    "name": "github_list_commits",
    "description": "List commits on a branch, PR, or path. Returns SHA, author, date, and message.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "sha": {"type": "string", "description": "Branch name, tag, or SHA to list commits from. Default: repo default branch."},
            "path": {"type": "string", "description": "Only commits touching this file path."},
            "author": {"type": "string", "description": "GitHub username or email to filter by."},
            "since": {"type": "string", "description": "Only commits after this ISO 8601 date (e.g. 2026-03-01T00:00:00Z)."},
            "until": {"type": "string", "description": "Only commits before this ISO 8601 date."},
            "per_page": {"type": "integer", "description": "Number of commits to return (default 20, max 100)."},
        },
        "required": ["owner", "repo"],
    },
}})
async def github_list_commits(
    owner: str,
    repo: str,
    sha: str = "",
    path: str = "",
    author: str = "",
    since: str = "",
    until: str = "",
    per_page: int = 20,
) -> str:
    params: dict = {"per_page": min(per_page, 100)}
    if sha:
        params["sha"] = sha
    if path:
        params["path"] = path
    if author:
        params["author"] = author
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/commits",
        headers=_headers(),
        params=params,
    )
    r.raise_for_status()
    commits = r.json()

    if not commits:
        return f"No commits found in {owner}/{repo} with the given filters."

    lines = [f"{len(commits)} commit(s) in {owner}/{repo}:\n"]
    for c in commits:
        sha_short = c["sha"][:7]
        commit = c.get("commit", {})
        author_info = commit.get("author", {})
        name = author_info.get("name", "")
        date = author_info.get("date", "")[:10]
        msg = commit.get("message", "").split("\n")[0]
        lines.append(f"- `{sha_short}` {msg} — {name} ({date})")

    return "\n".join(lines)


@reg.register({"type": "function", "function": {
    "name": "github_get_commit",
    "description": "Get full details of a single commit including message, stats, changed files, and diff.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "ref": {"type": "string", "description": "Commit SHA, branch name, or tag."},
        },
        "required": ["owner", "repo", "ref"],
    },
}})
async def github_get_commit(owner: str, repo: str, ref: str) -> str:
    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/commits/{ref}",
        headers=_headers(),
    )
    r.raise_for_status()
    data = r.json()

    commit = data.get("commit", {})
    author = commit.get("author", {})
    stats = data.get("stats", {})

    files = [
        f"{f['filename']} (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
        for f in data.get("files", [])
    ]

    # Fetch diff format
    r_diff = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/commits/{ref}",
        headers=_headers("application/vnd.github.v3.diff"),
    )
    diff = r_diff.text if r_diff.status_code == 200 else "(diff unavailable)"
    if len(diff) > 50_000:
        diff = diff[:50_000] + "\n... (diff truncated at 50K chars)"

    lines = [
        f"# Commit {data['sha'][:7]}",
        f"Author: {author.get('name', '')} <{author.get('email', '')}>",
        f"Date: {author.get('date', '')}",
        f"+{stats.get('additions', 0)} -{stats.get('deletions', 0)} across {len(data.get('files', []))} files",
        "",
        "## Message",
        commit.get("message", "(no message)"),
        "",
        "## Changed Files",
        "\n".join(files) or "(none)",
        "",
        "## Diff",
        diff,
    ]
    return "\n".join(lines)


@reg.register({"type": "function", "function": {
    "name": "github_get_file",
    "description": "Read a file's contents from a GitHub repository at a specific ref (branch, tag, or SHA).",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "path": {"type": "string", "description": "File path within the repo (e.g. src/main.py)."},
            "ref": {"type": "string", "description": "Branch, tag, or commit SHA. Default: repo default branch."},
        },
        "required": ["owner", "repo", "path"],
    },
}})
async def github_get_file(owner: str, repo: str, path: str, ref: str = "") -> str:
    params = {}
    if ref:
        params["ref"] = ref

    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=_headers("application/vnd.github.raw+json"),
        params=params,
    )
    if r.status_code == 404:
        return f"File not found: {path}" + (f" at ref {ref}" if ref else "")
    r.raise_for_status()

    content = r.text
    if len(content) > 100_000:
        content = content[:100_000] + "\n... (truncated at 100K chars)"

    ref_label = ref or "default branch"
    return f"# {path} ({ref_label})\n\n```\n{content}\n```"


@reg.register({"type": "function", "function": {
    "name": "github_compare",
    "description": "Compare two git refs (branches, tags, or SHAs). Shows commits between them and the combined diff.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "base": {"type": "string", "description": "Base ref (branch, tag, or SHA)."},
            "head": {"type": "string", "description": "Head ref (branch, tag, or SHA)."},
        },
        "required": ["owner", "repo", "base", "head"],
    },
}})
async def github_compare(owner: str, repo: str, base: str, head: str) -> str:
    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/compare/{base}...{head}",
        headers=_headers(),
    )
    r.raise_for_status()
    data = r.json()

    status = data.get("status", "")
    ahead = data.get("ahead_by", 0)
    behind = data.get("behind_by", 0)
    total_commits = data.get("total_commits", 0)

    commits = []
    for c in data.get("commits", [])[:30]:
        sha_short = c["sha"][:7]
        msg = c.get("commit", {}).get("message", "").split("\n")[0]
        author_name = c.get("commit", {}).get("author", {}).get("name", "")
        commits.append(f"- `{sha_short}` {msg} — {author_name}")

    files = [
        f"{f['filename']} (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
        for f in data.get("files", [])
    ]

    # Fetch diff
    r_diff = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/compare/{base}...{head}",
        headers=_headers("application/vnd.github.v3.diff"),
    )
    diff = r_diff.text if r_diff.status_code == 200 else "(diff unavailable)"
    if len(diff) > 50_000:
        diff = diff[:50_000] + "\n... (diff truncated at 50K chars)"

    lines = [
        f"# Compare: {base}...{head}",
        f"Status: {status} | {ahead} ahead, {behind} behind | {total_commits} commits",
        "",
        "## Commits",
        "\n".join(commits) or "(none)",
    ]
    if total_commits > 30:
        lines.append(f"... and {total_commits - 30} more commits")
    lines += [
        "",
        "## Changed Files",
        "\n".join(files) or "(none)",
        "",
        "## Diff",
        diff,
    ]
    return "\n".join(lines)


@reg.register({"type": "function", "function": {
    "name": "github_list_branches",
    "description": "List branches for a GitHub repository.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
        },
        "required": ["owner", "repo"],
    },
}})
async def github_list_branches(owner: str, repo: str) -> str:
    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/branches",
        headers=_headers(),
        params={"per_page": 100},
    )
    r.raise_for_status()
    branches = r.json()

    if not branches:
        return f"No branches in {owner}/{repo}"

    lines = [f"{len(branches)} branch(es) in {owner}/{repo}:\n"]
    for b in branches:
        protected = " (protected)" if b.get("protected") else ""
        lines.append(f"- {b['name']}{protected}")

    return "\n".join(lines)
