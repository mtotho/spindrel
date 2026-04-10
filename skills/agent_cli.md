---
name: Agent CLI
description: The agent CLI and agent-api wrapper for interacting with the Spindrel server from inside a workspace container or any shell environment
triggers: agent CLI, agent discover, agent api, agent-api, agent docs, agent chat, agent channels, agent tasks, server API call
category: core
---

# Agent CLI

The `agent` CLI at `/usr/local/bin/agent` is the primary way to interact with the Spindrel server API from a shell environment (workspace containers, scripts, dev terminals).

## Discovery — Always Run This First

Your scoped API key determines what endpoints you can call. Before making API requests, learn what your key allows:

```sh
agent discover              # Quick list — endpoints + your scopes
agent docs                  # Full markdown API reference filtered to your key
```

This is the **authoritative** source for what you can do. Don't memorize endpoints — let `agent docs` tell you what's available.

### api_reference Virtual Skill

If API docs injection is enabled on your bot config, you have an `api_reference` entry in your skill index. Call `get_skill("api_reference")` to get full API documentation filtered to your scopes — same data as `agent docs`, surfaced via the skill system.

## Common Commands

```sh
agent discover                          # Show available endpoints for your key
agent docs                              # Full markdown API reference
agent chat "message"                    # Send a chat message
agent channels                          # List channels
agent channels get <id>                 # Channel details
agent channels create --bot-id X        # Create channel
agent channels messages <id>            # List messages
agent channels messages <id> --inject "msg"  # Inject message
agent channels reset <id>              # Reset session
agent tasks                             # List tasks
agent tasks get <id>                    # Task details
agent tasks wait <id>                   # Block until complete/failed
agent api METHOD /path [json_body]      # Raw API call
```

## agent-api Helper (legacy)

The `agent-api` shell script wraps `curl` with auth headers. Prefer `agent` CLI for new work — `agent-api` is kept for compatibility with older scripts.

```sh
agent-api GET /api/v1/channels
agent-api POST /api/v1/documents '{"title":"notes","content":"hello"}'
```

## Python Pattern

When you need more control than the CLI offers (response inspection, error handling, looping):

```python
import os, httpx

BASE = os.environ["AGENT_SERVER_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_SERVER_API_KEY']}"}

r = httpx.get(f"{BASE}/api/v1/channels", headers=HEADERS)
```

`AGENT_SERVER_URL` and `AGENT_SERVER_API_KEY` are auto-injected into the workspace container environment, scoped to your bot's permissions.

## Common Operations

### Inject a message into a channel

```sh
# Inject without triggering processing
agent api POST /api/v1/channels/{channel_id}/messages \
  '{"content":"Analysis complete: 42 issues found","role":"user","source":"workspace"}'

# Inject + trigger agent processing
agent api POST /api/v1/channels/{channel_id}/messages \
  '{"content":"Review these results","run_agent":true}'
# Returns {"task_id":"..."} — wait for completion:
agent tasks wait <task_id>
```

### Trigger another bot and wait

```python
import os, httpx

BASE = os.environ["AGENT_SERVER_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_SERVER_API_KEY']}"}

r = httpx.post(f"{BASE}/api/v1/channels/{channel_id}/messages",
    headers=HEADERS, json={"content": "Summarize logs", "run_agent": True})
task_id = r.json()["task_id"]

# Or from CLI: agent tasks wait <task_id>
```

### Ingest documents for RAG

```sh
agent api POST /api/v1/documents \
  '{"title":"Research Notes","content":"...","integration_id":"my-bot","metadata":{"source":"analysis"}}'

# Search later
agent api GET '/api/v1/documents/search?q=deployment+timeline&limit=5'
```

### Batch-ingest files

```sh
for f in docs/*.md; do
  TITLE=$(basename "$f" .md)
  CONTENT=$(cat "$f" | jq -Rs .)
  agent api POST /api/v1/documents \
    "{\"title\":\"$TITLE\",\"content\":$CONTENT,\"integration_id\":\"workspace-docs\"}"
done
```

### Manage todos

```sh
agent api GET '/api/v1/todos?status=pending'
agent api POST /api/v1/todos '{"content":"Review auth module","priority":"high"}'
agent api PATCH /api/v1/todos/{id} '{"status":"completed"}'
```

### Download attachments

```sh
agent api GET '/api/v1/attachments?channel_id={id}&limit=10'
agent api GET /api/v1/attachments/{id}/file > output.bin
```

## Common Mistakes

| Mistake | Why It's Wrong | Do This Instead |
|---|---|---|
| Skipping `agent discover` | You may lack scopes, causing silent 403s | Run it before making API calls in a new context |
| Hardcoding API paths from memory | Your scopes may not cover them | Use `agent docs` for your actual available endpoints |
| Tight polling loops (< 5s) | Wastes resources, may hit rate limits | Use `agent tasks wait` or poll at 5s+ intervals |
| Forgetting `jq -Rs` for file content | Raw newlines break JSON bodies | Always escape: `cat file \| jq -Rs .` |
