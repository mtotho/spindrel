# GitHub Integration

Receives GitHub webhook events, injects them into agent sessions (one channel per repo), and posts agent responses as issue/PR comments.

## Setup

### 1. Environment Variables

Add to your `.env`:

```bash
GITHUB_TOKEN=ghp_...              # PAT with `repo` scope (or fine-grained with issues:write, pull_requests:read)
GITHUB_WEBHOOK_SECRET=your_secret # Shared secret for webhook signature verification
GITHUB_BOT_LOGIN=my-bot           # GitHub username of the PAT owner (prevents responding to own comments)
```

Generate the webhook secret with: `openssl rand -hex 20`

### 2. Expose Your Server to the Internet

GitHub needs to reach your server to deliver webhook events. If your server is already publicly accessible, skip to step 3.

#### Option A: Cloudflare Tunnel (recommended)

Free, stable URL, production-grade. Runs as a system service on your host.

**One-time setup:**

1. In the [Cloudflare dashboard](https://dash.cloudflare.com/) go to **Networking → Tunnels → Create a tunnel**
2. Choose **Cloudflared** as connector type, name it (e.g. `agent-server`)
3. The dashboard gives you an install command — run it on your host. This installs `cloudflared` as a system service that starts on boot.
4. Once the connector shows as healthy, add a **public hostname**:
   - Subdomain: e.g. `agent` on your domain → `agent.yourdomain.com`
   - Service type: HTTP
   - URL: `localhost:8000`
5. Set `BASE_URL` in your `.env` so the admin UI shows the full webhook URL:
   ```bash
   BASE_URL=https://agent.yourdomain.com
   ```

Your webhook URL is now `https://agent.yourdomain.com/integrations/github/webhook` — stable across restarts.

> **Note:** The tunnel exposes your full server, but all endpoints require `API_KEY` bearer auth except the webhook route (which uses HMAC signature verification). Your server is safe to expose.

#### Option B: ngrok (quick testing)

Easiest for trying things out, but the free tier gives you a random URL that changes on restart.

```bash
# Install: https://ngrok.com/download
ngrok http 8000
```

Copy the `https://xxxx.ngrok-free.app` URL. Your webhook URL is `https://xxxx.ngrok-free.app/integrations/github/webhook`.

> Note: You'll need to update the GitHub webhook URL each time ngrok restarts (unless you have a paid plan with a static domain).

### 3. Configure Webhook on GitHub

Go to **Settings → Webhooks → Add webhook** on your repo (or org for all repos):

| Field | Value |
|-------|-------|
| Payload URL | `https://your-tunnel-url/integrations/github/webhook` |
| Content type | `application/json` |
| Secret | Same value as `GITHUB_WEBHOOK_SECRET` |
| Events | "Send me everything" or select specific events below |

Click **Add webhook**. GitHub sends a ping event immediately — you should see a green checkmark if your tunnel and server are running.

### 4. Restart the Server

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
- **`gh`** — General GitHub CLI wrapper for any `gh` subcommand (pr, issue, run, release, search, api, etc.)

### System Dependencies

The `gh` tool requires the [GitHub CLI](https://cli.github.com/) (`gh`) binary. It is declared as a system dependency in `integration.yaml` and the server will attempt auto-install via apt. However, `gh` requires adding GitHub's apt repo first:

```bash
type -p curl >/dev/null || sudo apt install curl -y
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install gh -y
```

No separate `gh auth login` is needed — the tool uses the `GITHUB_TOKEN` setting automatically.

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
