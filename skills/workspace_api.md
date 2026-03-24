---
name: workspace-api
description: "Load when the bot is running inside a Docker workspace container and needs to call back to the agent server API. Trigger when: executing scripts that interact with the server, using the agent-api helper, ingesting documents, injecting messages into channels/sessions, polling task status, managing todos, or searching conversation history from workspace code. Also load when writing scripts or automation that will run inside a workspace."
---

# Workspace API Reference

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
- `AGENT_SERVER_URL` — base URL of the agent server (e.g. `http://host.docker.internal:8000`)
- `AGENT_SERVER_API_KEY` — API key for Bearer auth

For Python scripts, use `httpx` or `requests` directly:

```python
import os, httpx

BASE = os.environ["AGENT_SERVER_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_SERVER_API_KEY']}"}

r = httpx.get(f"{BASE}/api/v1/channels", headers=HEADERS)
```

## API Endpoints

All paths are relative to `AGENT_SERVER_URL`. Auth is via `Authorization: Bearer {API_KEY}` header (agent-api does this automatically).

### Channels — `/api/v1/channels`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/channels` | Create/retrieve channel |
| GET | `/api/v1/channels` | List channels (filter: `?integration=`, `?bot_id=`) |
| GET | `/api/v1/channels/{id}` | Get channel info |
| PUT | `/api/v1/channels/{id}` | Update channel settings |
| POST | `/api/v1/channels/{id}/messages` | Inject message into active session |
| POST | `/api/v1/channels/{id}/reset` | Reset session (starts fresh, preserves plans) |
| GET | `/api/v1/channels/{id}/messages/search` | Search messages (`?q=`, `?role=`, `?limit=`) |

**Create channel:**
```sh
agent-api POST /api/v1/channels '{"client_id":"my-script","bot_id":"default"}'
```

**Inject message + trigger agent:**
```sh
agent-api POST /api/v1/channels/{id}/messages \
  '{"content":"Analyze this data","run_agent":true}'
```
Returns `{"task_id":"..."}` when `run_agent=true` — poll with GET `/api/v1/tasks/{task_id}`.

**Search conversation history:**
```sh
agent-api GET '/api/v1/channels/{id}/messages/search?q=deployment&limit=20'
```

### Sessions — `/api/v1/sessions`

Lower-level than channels. Use channels when possible.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/sessions` | Create/retrieve session (`bot_id`, `client_id`) |
| POST | `/api/v1/sessions/{id}/messages` | Inject message (`content`, `role`, `run_agent`, `notify`) |
| GET | `/api/v1/sessions/{id}/messages` | List messages (`?limit=50`) |

### Documents — `/api/v1/documents`

Ingest text for semantic search (uses pgvector embeddings).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/documents` | Ingest + embed document |
| GET | `/api/v1/documents/search` | Semantic search (`?q=`, `?integration_id=`, `?limit=`) |
| GET | `/api/v1/documents/{id}` | Get document by ID |
| DELETE | `/api/v1/documents/{id}` | Delete document |

**Ingest a document:**
```sh
agent-api POST /api/v1/documents '{
  "title": "Meeting Notes 2026-03-24",
  "content": "Discussed deployment timeline...",
  "integration_id": "my-script",
  "metadata": {"source": "meeting"}
}'
```

**Semantic search:**
```sh
agent-api GET '/api/v1/documents/search?q=deployment+timeline&limit=5'
```

### Tasks — `/api/v1/tasks`

Poll async task status (created by `run_agent=true` on message injection).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/tasks/{id}` | Get task status + result |

**Status values:** `pending`, `running`, `complete`, `failed`

```sh
# Poll until complete
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

### Workspaces — `/api/v1/workspaces`

Manage workspace containers (including self-management).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workspaces` | List all workspaces |
| POST | `/api/v1/workspaces` | Create workspace |
| GET | `/api/v1/workspaces/{id}` | Get workspace details |
| POST | `/api/v1/workspaces/{id}/start` | Start container |
| POST | `/api/v1/workspaces/{id}/stop` | Stop container |
| GET | `/api/v1/workspaces/{id}/status` | Check container status |
| GET | `/api/v1/workspaces/{id}/logs` | Get logs (`?tail=300`) |
| GET | `/api/v1/workspaces/{id}/files` | Browse files (`?path=/`) |

### Admin — `/api/v1/admin`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/bots` | List all bots |
| GET | `/api/v1/admin/bots/{id}` | Get bot config |
| GET | `/api/v1/admin/skills` | List all skills |
| GET | `/api/v1/admin/skills/{id}` | Get skill content |

## Common Patterns

### Run a script and report results to a channel

```sh
#!/bin/sh
CHANNEL_ID="$1"
RESULT=$(python analyze.py 2>&1)
agent-api POST /api/v1/channels/$CHANNEL_ID/messages \
  "{\"content\":\"Analysis complete:\n$RESULT\",\"role\":\"user\",\"source\":\"workspace-script\"}"
```

### Ingest files for RAG search

```sh
#!/bin/sh
for f in docs/*.md; do
  TITLE=$(basename "$f" .md)
  CONTENT=$(cat "$f" | jq -Rs .)
  agent-api POST /api/v1/documents \
    "{\"title\":\"$TITLE\",\"content\":$CONTENT,\"integration_id\":\"workspace-docs\"}"
done
```

### Trigger agent and wait for result

```python
import os, time, httpx

BASE = os.environ["AGENT_SERVER_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_SERVER_API_KEY']}"}

# Inject message and trigger agent
r = httpx.post(f"{BASE}/api/v1/channels/{channel_id}/messages",
    headers=HEADERS,
    json={"content": "Summarize today's logs", "run_agent": True})
task_id = r.json()["task_id"]

# Poll for completion
while True:
    r = httpx.get(f"{BASE}/api/v1/tasks/{task_id}", headers=HEADERS)
    status = r.json()["status"]
    if status in ("complete", "failed"):
        break
    time.sleep(5)

print(r.json().get("result"))
```

## Pre-Flight Checklist

- [ ] `AGENT_SERVER_URL` and `AGENT_SERVER_API_KEY` are set (check with `env | grep AGENT`)
- [ ] Using correct channel/session ID (create one if needed)
- [ ] JSON body is properly escaped (use `jq` for complex content)
- [ ] For async tasks: polling with appropriate interval (5s minimum)
- [ ] Document `integration_id` is consistent for later search filtering
