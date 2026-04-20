"""GitHub API tools for the agent."""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil

import httpx

from integrations import sdk as reg
from integrations.github.config import settings

_GITHUB_API = "https://api.github.com"
_COMPONENTS_CT = "application/vnd.spindrel.components+json"
_http = httpx.AsyncClient(timeout=30.0)


def _headers(accept: str = "application/vnd.github+json") -> dict:
    return {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _rich(llm_text: str, plain_body: str, components: list[dict]) -> str:
    """Build a dual-payload result: LLM gets full text, UI gets rich components."""
    return json.dumps({
        "llm": llm_text,
        "_envelope": {
            "content_type": _COMPONENTS_CT,
            "display": "inline",
            "plain_body": plain_body,
            "body": json.dumps({"v": 1, "components": components}, ensure_ascii=False),
        },
    }, ensure_ascii=False)


def _state_color(state: str, merged: bool = False) -> str:
    if merged:
        return "accent"
    return "success" if state == "open" else "muted"


def _gh_link(owner: str, repo: str, number: int | None = None, path: str = "") -> str:
    base = f"https://github.com/{owner}/{repo}"
    if number is not None:
        # Works for both issues and PRs
        return f"{base}/issues/{number}"
    if path:
        return f"{base}/{path}"
    return base


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
}}, returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
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
    raw_files = r_files.json() if r_files.status_code == 200 else []
    files = [
        f"{f['filename']} (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
        for f in raw_files
    ]

    # LLM text (unchanged — full detail including diff)
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
    llm_text = "\n".join(lines)

    # Rich UI components
    state = pr.get("state", "")
    merged = pr.get("merged", False)
    state_label = "merged" if merged else state
    additions = pr.get("additions", 0)
    deletions = pr.get("deletions", 0)
    changed = pr.get("changed_files", 0)
    title = pr.get("title", "")
    author = pr.get("user", {}).get("login", "")
    head_ref = pr.get("head", {}).get("ref", "")
    base_ref = pr.get("base", {}).get("ref", "")
    labels = ", ".join(l["name"] for l in pr.get("labels", []))

    props = [
        {"label": "Author", "value": f"@{author}"},
        {"label": "Branch", "value": f"{head_ref} → {base_ref}"},
        {"label": "Stats", "value": f"+{additions} −{deletions} across {changed} files"},
    ]
    if labels:
        props.append({"label": "Labels", "value": labels})

    components: list[dict] = [
        {"type": "heading", "text": f"PR #{pull_number}: {title}", "level": 2},
        {"type": "status", "text": state_label, "color": _state_color(state, merged)},
        {"type": "properties", "items": props, "layout": "vertical"},
        {"type": "links", "items": [
            {"url": pr.get("html_url", _gh_link(owner, repo, pull_number)),
             "title": f"View PR #{pull_number} on GitHub", "icon": "github"},
        ]},
    ]
    if raw_files:
        components.append({
            "type": "section", "label": f"Changed Files ({len(raw_files)})",
            "collapsible": True, "defaultOpen": False,
            "children": [{"type": "table", "compact": True,
                          "columns": ["File", "+", "−"],
                          "rows": [[f["filename"],
                                    str(f.get("additions", 0)),
                                    str(f.get("deletions", 0))]
                                   for f in raw_files[:50]]}],
        })
    if diff and diff != "(diff unavailable)":
        components.append({
            "type": "section", "label": "Diff",
            "collapsible": True, "defaultOpen": False,
            "children": [{"type": "code", "content": diff[:3000], "language": "diff"}],
        })

    plain = f"PR #{pull_number}: {title} — {state_label}, +{additions} −{deletions}"
    return _rich(llm_text, plain, components)


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
}}, returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
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
        return json.dumps({"llm": f"No results for: {q}", "count": 0}, ensure_ascii=False)

    # LLM text
    lines = [f"Found {data.get('total_count', 0)} results (showing top {len(items)}):\n"]
    for item in items:
        labels = ", ".join(l["name"] for l in item.get("labels", []))
        kind = "PR" if "pull_request" in item else "Issue"
        line = f"- [{kind}] #{item['number']} {item['title']} ({item['state']})"
        if labels:
            line += f" [{labels}]"
        line += f"\n  {item['html_url']}"
        lines.append(line)
    llm_text = "\n".join(lines)

    # Rich UI
    total = data.get("total_count", 0)
    link_items = []
    for item in items:
        kind = "PR" if "pull_request" in item else "Issue"
        labels = ", ".join(l["name"] for l in item.get("labels", []))
        subtitle = f"{item['state']} · {kind}"
        if labels:
            subtitle += f" · {labels}"
        link_items.append({
            "url": item["html_url"],
            "title": f"#{item['number']} {item['title']}",
            "subtitle": subtitle,
            "icon": "github",
        })

    components: list[dict] = [
        {"type": "heading", "text": f"{total} results for: {query}", "level": 3},
        {"type": "links", "items": link_items},
    ]
    plain = f"{total} results for: {query}"
    return _rich(llm_text, plain, components)


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
}}, returns={
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "comment_url": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def github_post_comment(owner: str, repo: str, issue_number: int, body: str) -> str:
    r = await _http.post(
        f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
        headers=_headers(),
        json={"body": body},
    )
    r.raise_for_status()
    data = r.json()
    return json.dumps({"ok": True, "comment_url": data.get("html_url", "")}, ensure_ascii=False)


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
}}, returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
async def github_list_prs(owner: str, repo: str, state: str = "open") -> str:
    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/pulls",
        headers=_headers(),
        params={"state": state, "per_page": 30, "sort": "updated", "direction": "desc"},
    )
    r.raise_for_status()
    prs = r.json()

    if not prs:
        return json.dumps({"llm": f"No {state} PRs in {owner}/{repo}", "count": 0}, ensure_ascii=False)

    # LLM text
    lines = [f"{len(prs)} {state} PR(s) in {owner}/{repo}:\n"]
    for pr in prs:
        author = pr.get("user", {}).get("login", "")
        labels = ", ".join(l["name"] for l in pr.get("labels", []))
        line = f"- #{pr['number']} {pr['title']} by @{author}"
        if labels:
            line += f" [{labels}]"
        lines.append(line)
    llm_text = "\n".join(lines)

    # Rich UI
    link_items = []
    for pr in prs:
        author = pr.get("user", {}).get("login", "")
        labels = ", ".join(l["name"] for l in pr.get("labels", []))
        subtitle = f"by @{author}"
        if labels:
            subtitle += f" · {labels}"
        link_items.append({
            "url": pr.get("html_url", _gh_link(owner, repo, pr["number"])),
            "title": f"#{pr['number']} {pr['title']}",
            "subtitle": subtitle,
            "icon": "github",
        })

    components: list[dict] = [
        {"type": "heading", "text": f"{len(prs)} {state} PRs in {owner}/{repo}", "level": 3},
        {"type": "links", "items": link_items},
    ]
    plain = f"{len(prs)} {state} PRs in {owner}/{repo}"
    return _rich(llm_text, plain, components)


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
}}, returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
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
        return json.dumps({"llm": f"No commits found in {owner}/{repo} with the given filters.", "count": 0}, ensure_ascii=False)

    # LLM text
    lines = [f"{len(commits)} commit(s) in {owner}/{repo}:\n"]
    for c in commits:
        sha_short = c["sha"][:7]
        commit = c.get("commit", {})
        author_info = commit.get("author", {})
        name = author_info.get("name", "")
        date = author_info.get("date", "")[:10]
        msg = commit.get("message", "").split("\n")[0]
        lines.append(f"- `{sha_short}` {msg} — {name} ({date})")
    llm_text = "\n".join(lines)

    # Rich UI
    rows = []
    for c in commits:
        commit = c.get("commit", {})
        author_info = commit.get("author", {})
        rows.append([
            c["sha"][:7],
            commit.get("message", "").split("\n")[0][:80],
            author_info.get("name", ""),
            author_info.get("date", "")[:10],
        ])

    components: list[dict] = [
        {"type": "heading", "text": f"{len(commits)} commits in {owner}/{repo}", "level": 3},
        {"type": "table", "columns": ["SHA", "Message", "Author", "Date"],
         "rows": rows, "compact": True},
    ]
    plain = f"{len(commits)} commits in {owner}/{repo}"
    return _rich(llm_text, plain, components)


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
}}, returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
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
    raw_files = data.get("files", [])

    files = [
        f"{f['filename']} (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
        for f in raw_files
    ]

    # Fetch diff format
    r_diff = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/commits/{ref}",
        headers=_headers("application/vnd.github.v3.diff"),
    )
    diff = r_diff.text if r_diff.status_code == 200 else "(diff unavailable)"
    if len(diff) > 50_000:
        diff = diff[:50_000] + "\n... (diff truncated at 50K chars)"

    # LLM text
    lines = [
        f"# Commit {data['sha'][:7]}",
        f"Author: {author.get('name', '')} <{author.get('email', '')}>",
        f"Date: {author.get('date', '')}",
        f"+{stats.get('additions', 0)} -{stats.get('deletions', 0)} across {len(raw_files)} files",
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
    llm_text = "\n".join(lines)

    # Rich UI
    sha_short = data["sha"][:7]
    additions = stats.get("additions", 0)
    deletions = stats.get("deletions", 0)
    message = commit.get("message", "(no message)")

    components: list[dict] = [
        {"type": "heading", "text": f"Commit {sha_short}", "level": 2},
        {"type": "properties", "items": [
            {"label": "Author", "value": f"{author.get('name', '')} <{author.get('email', '')}>"},
            {"label": "Date", "value": author.get("date", "")[:10]},
            {"label": "Stats", "value": f"+{additions} −{deletions} across {len(raw_files)} files"},
        ], "layout": "vertical"},
        {"type": "links", "items": [
            {"url": data.get("html_url", f"https://github.com/{owner}/{repo}/commit/{ref}"),
             "title": f"View commit {sha_short} on GitHub", "icon": "github"},
        ]},
    ]
    if message:
        components.append({
            "type": "section", "label": "Message",
            "collapsible": True, "defaultOpen": True,
            "children": [{"type": "text", "content": message, "markdown": True}],
        })
    if raw_files:
        components.append({
            "type": "section", "label": f"Changed Files ({len(raw_files)})",
            "collapsible": True, "defaultOpen": False,
            "children": [{"type": "table", "compact": True,
                          "columns": ["File", "+", "−"],
                          "rows": [[f["filename"],
                                    str(f.get("additions", 0)),
                                    str(f.get("deletions", 0))]
                                   for f in raw_files[:50]]}],
        })
    if diff and diff != "(diff unavailable)":
        components.append({
            "type": "section", "label": "Diff",
            "collapsible": True, "defaultOpen": False,
            "children": [{"type": "code", "content": diff[:3000], "language": "diff"}],
        })

    plain = f"Commit {sha_short} — +{additions} −{deletions} across {len(raw_files)} files"
    return _rich(llm_text, plain, components)


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


@reg.register({"type": "function", "function": {
    "name": "github_get_issue",
    "description": "Get details of a single GitHub issue by number, including title, body, state, labels, assignees, and comments.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "issue_number": {"type": "integer", "description": "Issue number"},
        },
        "required": ["owner", "repo", "issue_number"],
    },
}}, returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
async def github_get_issue(owner: str, repo: str, issue_number: int) -> str:
    r = await _http.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}",
        headers=_headers(),
    )
    r.raise_for_status()
    issue = r.json()

    labels = ", ".join(l["name"] for l in issue.get("labels", []))
    assignees = ", ".join(f"@{a['login']}" for a in issue.get("assignees", []))

    # LLM text
    lines = [
        f"# Issue #{issue_number}: {issue.get('title', '')}",
        f"State: {issue.get('state', '')}",
        f"Author: @{issue.get('user', {}).get('login', '')}",
    ]
    if labels:
        lines.append(f"Labels: {labels}")
    if assignees:
        lines.append(f"Assignees: {assignees}")
    if issue.get("milestone"):
        lines.append(f"Milestone: {issue['milestone'].get('title', '')}")
    lines += [
        f"Created: {issue.get('created_at', '')[:10]} | Updated: {issue.get('updated_at', '')[:10]}",
        f"URL: {issue.get('html_url', '')}",
        "",
        "## Body",
        issue.get("body") or "(no description)",
    ]

    comments_data: list[dict] = []
    if issue.get("comments", 0) > 0:
        r_comments = await _http.get(
            f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
            headers=_headers(),
            params={"per_page": 30},
        )
        if r_comments.status_code == 200:
            comments_data = r_comments.json()
            lines += ["", f"## Comments ({len(comments_data)})"]
            for c in comments_data:
                c_author = c.get("user", {}).get("login", "")
                date = c.get("created_at", "")[:10]
                body = c.get("body", "")
                if len(body) > 2000:
                    body = body[:2000] + "... (truncated)"
                lines += [f"### @{c_author} ({date})", body, ""]
    llm_text = "\n".join(lines)

    # Rich UI
    state = issue.get("state", "")
    title = issue.get("title", "")
    author = issue.get("user", {}).get("login", "")

    props = [
        {"label": "Author", "value": f"@{author}"},
        {"label": "Created", "value": issue.get("created_at", "")[:10]},
        {"label": "Updated", "value": issue.get("updated_at", "")[:10]},
    ]
    if labels:
        props.append({"label": "Labels", "value": labels})
    if assignees:
        props.append({"label": "Assignees", "value": assignees})
    if issue.get("milestone"):
        props.append({"label": "Milestone", "value": issue["milestone"].get("title", "")})

    components: list[dict] = [
        {"type": "heading", "text": f"Issue #{issue_number}: {title}", "level": 2},
        {"type": "status", "text": state, "color": _state_color(state)},
        {"type": "properties", "items": props, "layout": "vertical"},
        {"type": "links", "items": [
            {"url": issue.get("html_url", _gh_link(owner, repo, issue_number)),
             "title": f"View issue #{issue_number} on GitHub", "icon": "github"},
        ]},
    ]

    body_text = issue.get("body") or ""
    if body_text:
        components.append({
            "type": "section", "label": "Description",
            "collapsible": True, "defaultOpen": True,
            "children": [{"type": "text", "content": body_text[:2000], "markdown": True}],
        })

    if comments_data:
        comment_children: list[dict] = []
        for c in comments_data[:10]:
            c_author = c.get("user", {}).get("login", "")
            date = c.get("created_at", "")[:10]
            body = c.get("body", "")[:500]
            comment_children.append(
                {"type": "text", "content": f"**@{c_author}** ({date}): {body}", "markdown": True}
            )
        components.append({
            "type": "section", "label": f"Comments ({len(comments_data)})",
            "collapsible": True, "defaultOpen": False,
            "children": comment_children,
        })

    plain = f"Issue #{issue_number}: {title} — {state}"
    return _rich(llm_text, plain, components)


@reg.register({"type": "function", "function": {
    "name": "github_create_issue",
    "description": "Create a new GitHub issue.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "title": {"type": "string", "description": "Issue title"},
            "body": {"type": "string", "description": "Issue body (Markdown)"},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "Labels to apply (must already exist in the repo)."},
            "assignees": {"type": "array", "items": {"type": "string"}, "description": "GitHub usernames to assign."},
        },
        "required": ["owner", "repo", "title"],
    },
}}, returns={
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "issue_number": {"type": "integer"},
        "issue_url": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def github_create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> str:
    payload: dict = {"title": title}
    if body:
        payload["body"] = body
    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees

    r = await _http.post(
        f"{_GITHUB_API}/repos/{owner}/{repo}/issues",
        headers=_headers(),
        json=payload,
    )
    r.raise_for_status()
    issue = r.json()
    return json.dumps({"ok": True, "issue_number": issue["number"], "issue_url": issue.get("html_url", "")}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# PR / Issue mutation tools (used by interactive widgets + direct calls)
# ---------------------------------------------------------------------------

@reg.register({"type": "function", "function": {
    "name": "github_update_pr",
    "description": "Update a pull request's state (open/closed) or title.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "pull_number": {"type": "integer", "description": "PR number"},
            "state": {"type": "string", "enum": ["open", "closed"], "description": "New state"},
            "title": {"type": "string", "description": "New title (optional)"},
        },
        "required": ["owner", "repo", "pull_number"],
    },
}}, safety_tier="exec_capable", returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
async def github_update_pr(
    owner: str, repo: str, pull_number: int,
    state: str | None = None, title: str | None = None,
) -> str:
    payload: dict = {}
    if state:
        payload["state"] = state
    if title:
        payload["title"] = title
    if not payload:
        return json.dumps({"error": "Provide at least state or title."}, ensure_ascii=False)

    r = await _http.patch(
        f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}",
        headers=_headers(), json=payload,
    )
    r.raise_for_status()
    pr = r.json()
    new_state = "merged" if pr.get("merged") else pr.get("state", "unknown")
    return await github_get_pr(owner, repo, pull_number)


@reg.register({"type": "function", "function": {
    "name": "github_merge_pr",
    "description": "Merge a pull request.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "pull_number": {"type": "integer", "description": "PR number"},
            "merge_method": {"type": "string", "enum": ["merge", "squash", "rebase"],
                             "description": "Merge strategy. Default: merge."},
        },
        "required": ["owner", "repo", "pull_number"],
    },
}}, safety_tier="exec_capable", returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
async def github_merge_pr(
    owner: str, repo: str, pull_number: int,
    merge_method: str = "merge",
) -> str:
    r = await _http.put(
        f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/merge",
        headers=_headers(), json={"merge_method": merge_method},
    )
    if r.status_code == 405:
        return json.dumps({"error": "PR cannot be merged (conflicts, checks failing, or not mergeable)."}, ensure_ascii=False)
    r.raise_for_status()
    return await github_get_pr(owner, repo, pull_number)


@reg.register({"type": "function", "function": {
    "name": "github_update_issue",
    "description": "Update an issue's state (open/closed) or title.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "issue_number": {"type": "integer", "description": "Issue number"},
            "state": {"type": "string", "enum": ["open", "closed"], "description": "New state"},
            "title": {"type": "string", "description": "New title (optional)"},
        },
        "required": ["owner", "repo", "issue_number"],
    },
}}, safety_tier="exec_capable", returns={
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "count": {"type": "integer"},
        "error": {"type": "string"},
    },
})
async def github_update_issue(
    owner: str, repo: str, issue_number: int,
    state: str | None = None, title: str | None = None,
) -> str:
    payload: dict = {}
    if state:
        payload["state"] = state
    if title:
        payload["title"] = title
    if not payload:
        return json.dumps({"error": "Provide at least state or title."}, ensure_ascii=False)

    r = await _http.patch(
        f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}",
        headers=_headers(), json=payload,
    )
    r.raise_for_status()
    return await github_get_issue(owner, repo, issue_number)


# ---------------------------------------------------------------------------
# gh CLI wrapper
# ---------------------------------------------------------------------------

_GH_ALLOWED = frozenset({
    "api", "browse", "cache", "codespace", "gist", "issue",
    "label", "milestone", "pr", "project", "release", "repo",
    "run", "search", "status", "workflow",
})
_GH_TIMEOUT = 60


def _parse_gh_subcommand(command: str) -> str | None:
    """Extract the first non-flag token (the subcommand) from a gh arg string."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    for part in parts:
        if not part.startswith("-"):
            return part
    return None


@reg.register({"type": "function", "function": {
    "name": "gh",
    "description": (
        "Run a GitHub CLI (gh) command. Pass the arguments you would type after `gh`. "
        "Examples: 'pr list --repo owner/repo', 'run list --repo owner/repo --limit 5', "
        "'release list --repo owner/repo', 'api /repos/owner/repo/actions/runs'. "
        "Allowed subcommands: " + ", ".join(sorted(_GH_ALLOWED)) + "."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "Arguments after 'gh'. "
                    "Example: 'pr list --repo octocat/hello-world --state open'"
                ),
            },
        },
        "required": ["command"],
    },
}}, safety_tier="exec_capable")
async def gh(command: str) -> str:
    if not shutil.which("gh"):
        return "Error: gh CLI is not installed. Install it from https://cli.github.com/"

    subcommand = _parse_gh_subcommand(command)
    if not subcommand:
        return "Error: could not parse a subcommand from the command."
    if subcommand not in _GH_ALLOWED:
        return (
            f"Error: subcommand '{subcommand}' is not allowed. "
            f"Allowed: {', '.join(sorted(_GH_ALLOWED))}"
        )

    try:
        args = shlex.split(command)
    except ValueError as e:
        return f"Error: invalid command syntax: {e}"

    env = {**os.environ}
    token = settings.GITHUB_TOKEN
    if token:
        env["GH_TOKEN"] = token

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GH_TIMEOUT)
    except asyncio.TimeoutError:
        return f"Error: command timed out after {_GH_TIMEOUT}s"
    except Exception as e:
        return f"Error running gh: {e}"

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        result = f"gh exited with code {proc.returncode}"
        if err:
            result += f"\nstderr: {err}"
        if out.strip():
            result += f"\nstdout: {out.strip()}"
        return result

    if len(out) > 100_000:
        out = out[:100_000] + "\n... (output truncated at 100K chars)"

    return out or "(no output)"
