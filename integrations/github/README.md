# GitHub Webhook Integration

Receives GitHub webhook events and posts failure notifications to a Slack channel.

## Supported Events

- **`workflow_run`** — notifies when a CI workflow fails
- **`check_run`** — notifies when a check run fails

Success events are silently ignored.

## Setup

### 1. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_WEBHOOK_SECRET` | Yes | Secret used to verify webhook signatures (`X-Hub-Signature-256`) |
| `SLACK_CHANNEL_ID` | Yes | Slack channel ID to post notifications to (e.g. `C01ABCDEF`) |
| `SLACK_BOT_TOKEN` | Yes | Slack bot token (`xoxb-...`) with `chat:write` scope |
| `GITHUB_TOKEN` | No | GitHub API token for future use (phase 2 — enriched notifications) |

### 2. GitHub Webhook Configuration

1. Go to your repository (or org) **Settings → Webhooks → Add webhook**
2. **Payload URL**: `https://<your-server>/api/integrations/github/webhook`
3. **Content type**: `application/json`
4. **Secret**: the value of `GITHUB_WEBHOOK_SECRET`
5. **Events**: select **workflow runs** and **check runs**

### 3. Slack App

Ensure the Slack app associated with `SLACK_BOT_TOKEN` has:
- `chat:write` scope
- Has been invited to the target channel

## Testing Locally

```bash
# 1. Set required env vars
export GITHUB_WEBHOOK_SECRET="test-secret"
export SLACK_CHANNEL_ID="C01ABCDEF"
export SLACK_BOT_TOKEN="xoxb-test-token"

# 2. Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3. Send a test webhook (workflow_run failure)
curl -X POST http://localhost:8000/api/integrations/github/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: workflow_run" \
  -H "X-Hub-Signature-256: sha256=$(echo -n '{"workflow_run":{"conclusion":"failure","name":"CI","head_branch":"main","html_url":"https://github.com/org/repo/actions/runs/1","id":1},"repository":{"full_name":"org/repo"}}' | openssl dgst -sha256 -hmac 'test-secret' | awk '{print $2}')" \
  -d '{"workflow_run":{"conclusion":"failure","name":"CI","head_branch":"main","html_url":"https://github.com/org/repo/actions/runs/1","id":1},"repository":{"full_name":"org/repo"}}'
```

For real end-to-end testing, use [smee.io](https://smee.io) or `ngrok` to expose your local server to GitHub.
