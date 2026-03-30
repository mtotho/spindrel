---
name: GitHub
description: GitHub tools and webhook events — PRs, issues, commits, code review, file browsing
---
# SKILL: GitHub

## Overview
GitHub integration with webhook-driven events and API tools. Incoming webhook events (PR opened, issue opened, comments, reviews) arrive as messages. Tools let you fetch PRs, browse commits, read files, compare branches, search issues, and post comments.

## Tools

### Pull Requests & Issues
- `github_get_pr` — full PR details with diff, changed files, and stats. Parameters: `owner`, `repo`, `pull_number`
- `github_list_prs` — list PRs for a repository. Parameters: `owner`, `repo`, `state` (open/closed/all)
- `github_search_issues` — search issues and PRs using GitHub search syntax. Parameters: `query`, `repo` (optional, `owner/repo` format)
- `github_post_comment` — post a comment on an issue or PR. Parameters: `owner`, `repo`, `issue_number`, `body` (markdown)

### Commits & History
- `github_list_commits` — list commits on a branch/path with filters. Parameters: `owner`, `repo`, `sha` (branch/tag), `path`, `author`, `since`, `until`, `per_page`
- `github_get_commit` — full commit details with message, stats, changed files, and diff. Parameters: `owner`, `repo`, `ref` (SHA/branch/tag)

### Code Browsing
- `github_get_file` — read a file's contents at a specific ref. Parameters: `owner`, `repo`, `path`, `ref` (branch/tag/SHA, optional)
- `github_compare` — compare two refs showing commits and combined diff. Parameters: `owner`, `repo`, `base`, `head`
- `github_list_branches` — list all branches with protection status. Parameters: `owner`, `repo`

## Incoming Webhook Events

Events arrive as messages describing what happened. The system auto-responds to events that need a reply (the agent runs and its response is posted as a GitHub comment). Events that are informational only (push, release, PR closed) are stored but don't trigger the agent.

### Events that trigger the agent (you respond as a comment)
- **PR opened** — full PR details with title, author, branches, file change stats, body
- **Issue opened** — issue title, author, labels, body
- **Comments** — on issues or PRs, includes the comment body and context
- **Review with changes requested** — review body with the reviewer's feedback
- **Inline review comments** — file path, line number, and comment body

### Informational events (stored, no agent response)
- PR synchronized (new commits pushed), PR closed/merged
- Push events (commits to branches)
- Releases published
- Discussions and discussion comments

## Key Workflows

### Review a PR
1. Read the incoming PR event message — it includes title, stats, and body
2. `github_get_pr(owner="...", repo="...", pull_number=N)` — fetch the full diff
3. Review the code changes — check for bugs, style issues, missing tests
4. Your response is automatically posted as a comment on the PR

### Review recent commits on a branch
1. `github_list_commits(owner="...", repo="...", sha="main", per_page=10)` — recent commits
2. `github_get_commit(owner="...", repo="...", ref="abc1234")` — drill into a specific commit's diff
3. If you need to see the current state of a file: `github_get_file(owner="...", repo="...", path="src/main.py")`

### Compare branches / review what changed
1. `github_compare(owner="...", repo="...", base="main", head="feature-branch")` — see all commits and diff between branches
2. For specific file context: `github_get_file(owner="...", repo="...", path="...", ref="feature-branch")`

### Investigate a file's history
1. `github_list_commits(owner="...", repo="...", path="src/auth.py")` — all commits touching this file
2. `github_get_commit(ref="...")` — see what each commit changed

### Respond to an issue
1. Read the incoming issue event — it includes title, labels, body
2. If you need context: `github_search_issues(query="similar terms", repo="owner/repo")` — find related issues
3. If you need to read the code: `github_get_file(...)` to inspect the relevant source
4. Your response is automatically posted as a comment on the issue

### Respond to a comment
1. Read the incoming comment event — it includes the commenter and their message
2. If it's on a PR and you need the diff: `github_get_pr(...)` to get full context
3. Your response is posted as a reply comment

### Search for context
- `github_search_issues(query="is:open label:bug", repo="owner/repo")` — open bugs
- `github_search_issues(query="is:pr is:merged auth")` — merged PRs about auth (cross-repo)
- `github_search_issues(query="author:username is:open")` — open items by a specific user
- `github_list_commits(owner="...", repo="...", author="username", since="2026-03-01T00:00:00Z")` — recent commits by someone

## Common Patterns
- **Channel format**: `github:owner/repo` — all events for a repo share one channel/session
- **owner/repo extraction**: webhook events include owner and repo in the message context; use them with tools
- **Comment body**: supports full GitHub Markdown — code blocks, task lists, mentions, etc.
- **Long diffs**: `github_get_pr`, `github_get_commit`, and `github_compare` truncate diffs over 50K characters. Focus on the changed files list to identify key files if the diff is truncated.
- **File contents**: `github_get_file` truncates at 100K characters. For large files, use commit diffs instead.
- **Refs**: most tools accept branch names, tags, or commit SHAs interchangeably for the `ref`/`sha` parameter
- **Self-loop prevention**: the bot won't respond to comments posted by its own GitHub user (`GITHUB_BOT_LOGIN`)
