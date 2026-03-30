# GitHub Integration

Receives GitHub webhook events, injects them into agent sessions (one channel per repo), and posts agent responses as issue/PR comments.

## Setup

### 1. Environment Variables

```bash
GITHUB_TOKEN=ghp_...              # PAT with `repo` scope (or fine-grained with issues:write, pull_requests:read)
GITHUB_WEBHOOK_SECRET=your_secret # Shared secret for webhook signature verification
GITHUB_BOT_LOGIN=my-bot           # GitHub username of the PAT owner (prevents responding to own comments)
```

### 2. Configure Webhook on GitHub

Go to **Settings → Webhooks → Add webhook** on your repo or org:

| Field | Value |
|-------|-------|
| Payload URL | `https://your-server/integrations/github/webhook` |
| Content type | `application/json` |
| Secret | Same value as `GITHUB_WEBHOOK_SECRET` |
| Events | "Send me everything" or select specific events below |

### 3. Restart the Server

The integration is auto-discovered on startup. You should see:
```
Registered integration meta: github (prefix=github:)
Registered local tool: github_get_pr
Registered local tool: github_search_issues
Registered local tool: github_post_comment
Registered local tool: github_list_prs
```

## How It Works

### Event Flow

```
GitHub webhook → POST /integrations/github/webhook
  → Verify HMAC-SHA256 signature
  → Parse event into human-readable message
  → Skip if sender == GITHUB_BOT_LOGIN
  → inject_message() into session for github:{owner}/{repo}
  → If run_agent=True, creates a Task → agent runs → dispatcher posts comment
```

### Channel Mapping

Each repo gets one channel: `github:owner/repo`. All events for that repo share context, so the agent can reference earlier PRs, issues, etc.

### Event Types

| Event | Action | Agent Runs? | Agent Replies? |
|-------|--------|-------------|----------------|
| `pull_request` opened | Logs PR details | Yes | Comment on PR |
| `pull_request` synchronize | Logs new commits | No | — |
| `pull_request` closed/merged | Logs status | No | — |
| `issues` opened | Logs issue details | Yes | Comment on issue |
| `issue_comment` created | Logs comment | Yes | Comment on issue/PR |
| `pull_request_review` (changes_requested) | Logs review | Yes | Comment on PR |
| `pull_request_review_comment` | Logs inline comment | Yes | Comment on PR |
| `push` | Logs commits | No | — |
| `release` published | Logs release | No | — |
| `discussion` created | Logs discussion | No | — |
| `discussion_comment` created | Logs comment | No | — |

### Agent Tools

The agent can proactively interact with GitHub via these tools:

- **`github_get_pr`** — Fetch PR details including diff and changed files
- **`github_search_issues`** — Search issues/PRs with GitHub search syntax
- **`github_post_comment`** — Post a comment on any issue or PR
- **`github_list_prs`** — List PRs for a repo (open/closed/all)

### Bot Configuration

By default, events use the `default` bot. To use a specific bot for a repo, configure the channel's bot in the admin UI after the first event creates the channel.

## Testing

```bash
# Signature validation + event parsing + dispatcher + tools
docker build -f Dockerfile.test -t agent-server-test .
docker run --rm agent-server-test pytest tests/unit/test_github_integration.py integrations/github/tests/ -v
```

## Verifying the Webhook

Use GitHub's webhook settings page → **Recent Deliveries** → **Redeliver** to test. The server should respond with `{"status": "processed", ...}` for handled events or `{"status": "pong"}` for ping.
