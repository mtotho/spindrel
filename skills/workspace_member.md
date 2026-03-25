---
name: workspace-member
description: "Load when the bot is a member of a shared workspace and needs to execute commands, call the server API, write scripts, ingest documents, manage todos, or interact with the agent server from inside the workspace container. Trigger when: using exec_command or delegate_to_exec, writing scripts that use agent-api, ingesting documents for RAG, injecting messages into channels, polling task status, searching conversation history, or reasoning about what tools and APIs are available inside the container. Do NOT load for orchestrator-level workspace management."
---

# Workspace Member

You are a member bot in a shared workspace. You work inside a Docker container with access to your own directory and the server API.

## Your Environment

- **cwd**: `/workspace/bots/{your_bot_id}/` (your default working directory)
- **Shared files**: `/workspace/common/` (orchestrator places resources here)
- **Other bots**: `/workspace/bots/{other_bot_id}/` (readable via exec — e.g., `cat /workspace/bots/other-bot/output.md`)
- **Container tools**: Python 3.12, Node.js 22, git, curl, jq, ripgrep, fd, tree, sqlite3
- **Python packages**: httpx, requests, pyyaml, toml, jinja2, beautifulsoup4, lxml, pandas, markdown, python-dotenv

## agent-api Helper

Every workspace container has `/usr/local/bin/agent-api` on PATH. It wraps `curl` with auth headers.

```sh
agent-api METHOD /path [json_body]
```

**Examples:**
```sh
# GET request
agent-api GET /api/v1/channels

# POST with JSON body
agent-api POST /api/v1/documents '{"title":"notes","content":"hello world"}'

# Pipe through jq
agent-api GET /api/v1/todos | jq '.[] | .content'
```

**Environment variables** (injected automatically):
- `AGENT_SERVER_URL` — base URL of the agent server
- `AGENT_SERVER_API_KEY` — API key for Bearer auth

For Python scripts:
```python
import os, httpx

BASE = os.environ["AGENT_SERVER_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_SERVER_API_KEY']}"}

r = httpx.get(f"{BASE}/api/v1/channels", headers=HEADERS)
```

## Server API Reference

All paths relative to `AGENT_SERVER_URL`. Auth is automatic via agent-api.

### Channels — `/api/v1/channels`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/channels` | Create/retrieve channel (`client_id`, `bot_id`) |
| GET | `/api/v1/channels` | List channels (`?integration=`, `?bot_id=`) |
| GET | `/api/v1/channels/{id}` | Get channel info |
| PUT | `/api/v1/channels/{id}` | Update channel settings |
| POST | `/api/v1/channels/{id}/messages` | Inject message into active session |
| POST | `/api/v1/channels/{id}/reset` | Reset session (preserves plans + channel config) |
| GET | `/api/v1/channels/{id}/messages/search` | Search messages (`?q=`, `?role=`, `?limit=`) |

**Inject a message:**
```sh
agent-api POST /api/v1/channels/{id}/messages \
  '{"content":"Analysis complete: 42 issues found","role":"user","source":"workspace"}'
```

**Inject + trigger agent processing:**
```sh
agent-api POST /api/v1/channels/{id}/messages \
  '{"content":"Review these results","run_agent":true}'
# Returns {"task_id":"..."} — poll with GET /api/v1/tasks/{task_id}
```

### Sessions — `/api/v1/sessions`

Lower-level than channels. Prefer channels.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/sessions` | Create/retrieve session (`bot_id`, `client_id`) |
| POST | `/api/v1/sessions/{id}/messages` | Inject message (`content`, `role`, `run_agent`, `notify`) |
| GET | `/api/v1/sessions/{id}/messages` | List messages (`?limit=50`) |

### Documents — `/api/v1/documents`

Ingest text for semantic search (pgvector embeddings).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/documents` | Ingest + embed (`title`, `content`, `integration_id`, `metadata`) |
| GET | `/api/v1/documents/search` | Semantic search (`?q=`, `?integration_id=`, `?limit=`) |
| GET | `/api/v1/documents/{id}` | Get by ID |
| DELETE | `/api/v1/documents/{id}` | Delete |

**Ingest:**
```sh
agent-api POST /api/v1/documents '{
  "title":"Meeting Notes",
  "content":"Discussed deployment...",
  "integration_id":"my-script",
  "metadata":{"source":"meeting"}
}'
```

**Search:**
```sh
agent-api GET '/api/v1/documents/search?q=deployment+timeline&limit=5'
```

### Tasks — `/api/v1/tasks`

Poll async task status (from `run_agent=true`).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/tasks/{id}` | Get status + result |

Status: `pending` → `running` → `complete` | `failed`

```sh
TASK_ID="..."
while true; do
  STATUS=$(agent-api GET /api/v1/tasks/$TASK_ID | jq -r '.status')
  [ "$STATUS" = "complete" ] || [ "$STATUS" = "failed" ] && break
  sleep 5
done
agent-api GET /api/v1/tasks/$TASK_ID | jq '.result'
```

### Todos — `/api/v1/todos`

Persistent work items scoped to bot + channel.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/todos` | List (`?bot_id=`, `?channel_id=`, `?status=pending`) |
| POST | `/api/v1/todos` | Create (`bot_id`, `channel_id`, `content`, `priority`) |
| PATCH | `/api/v1/todos/{id}` | Update (`content`, `status`, `priority`) |
| DELETE | `/api/v1/todos/{id}` | Delete |

### Attachments — `/api/v1/attachments`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/attachments` | List (`?channel_id=`, `?type=image`, `?limit=`) |
| GET | `/api/v1/attachments/{id}` | Get metadata |
| GET | `/api/v1/attachments/{id}/file` | Download raw file bytes |

### Admin (read-only) — `/api/v1/admin`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/bots` | List all bots |
| GET | `/api/v1/admin/bots/{id}` | Get bot config |
| GET | `/api/v1/admin/skills` | List all skills |
| GET | `/api/v1/admin/skills/{id}` | Get skill content |

## Common Patterns

### Report results to a channel

```sh
CHANNEL_ID="$1"
RESULT=$(python analyze.py 2>&1)
agent-api POST /api/v1/channels/$CHANNEL_ID/messages \
  "{\"content\":\"Analysis complete:\n$RESULT\",\"role\":\"user\",\"source\":\"workspace\"}"
```

### Batch-ingest files for RAG

```sh
for f in docs/*.md; do
  TITLE=$(basename "$f" .md)
  CONTENT=$(cat "$f" | jq -Rs .)
  agent-api POST /api/v1/documents \
    "{\"title\":\"$TITLE\",\"content\":$CONTENT,\"integration_id\":\"workspace-docs\"}"
done
```

### Trigger another agent and wait

```python
import os, time, httpx

BASE = os.environ["AGENT_SERVER_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_SERVER_API_KEY']}"}

r = httpx.post(f"{BASE}/api/v1/channels/{channel_id}/messages",
    headers=HEADERS, json={"content": "Summarize logs", "run_agent": True})
task_id = r.json()["task_id"]

while True:
    r = httpx.get(f"{BASE}/api/v1/tasks/{task_id}", headers=HEADERS)
    if r.json()["status"] in ("complete", "failed"):
        break
    time.sleep(5)

print(r.json().get("result"))
```

### Read shared resources from orchestrator

```sh
# Orchestrator places specs/data in /workspace/common/
cat /workspace/common/project-spec.md
ls /workspace/common/datasets/
```

## Member Checklist

- [ ] `AGENT_SERVER_URL` and `AGENT_SERVER_API_KEY` are set (`env | grep AGENT`)
- [ ] Working in your directory (`/workspace/bots/{bot_id}/`), not someone else's
- [ ] Check `/workspace/common/` for shared resources before starting work
- [ ] JSON bodies properly escaped (use `jq` for complex content)
- [ ] Polling async tasks at 5s+ intervals
- [ ] `integration_id` consistent for later search filtering
- [ ] Writing output where the orchestrator expects it
