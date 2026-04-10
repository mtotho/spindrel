---
name: Workspace API Reference
description: >
  Server API endpoints, permissions, and scopes reference for workspace orchestration.
  Load when calling server endpoints, checking your scopes, or performing
  workspace/file/task/channel operations via the API.
---

# Server API Reference

You reach the agent server through two in-process tools:

- **`list_api_endpoints(scope=...)`** — discover what your scoped API key permits.
- **`call_api(method, path, body)`** — invoke any allowed endpoint. Body is a JSON string.

These run inside the agent loop with your scoped key already wired in — no shell, no auth headers, no manual JSON escaping. Always start with `list_api_endpoints()` in a new context to see what's reachable, then call.

## Discovering Your Permissions

```python
list_api_endpoints()                        # Everything your key allows
list_api_endpoints(scope="channels")        # Narrow by scope prefix
list_api_endpoints(scope="workspaces")      # e.g. workspace management
```

### Common Scopes for Orchestrators

The `workspace_bot` preset provides: `chat`, `bots:read`, `channels:read/write`, `sessions:read`, `tasks:read/write`, `documents:read/write`, `todos:read/write`, `workspaces.files:read/write`, `attachments:read`.

Orchestrators often need additional scopes:
- `workspaces:read` — list workspaces, check container status, view logs
- `workspaces:write` — start/stop/recreate containers, manage bot membership (implies `workspaces:read` and `workspaces.files:*`)
- `bots:write` — modify bot configs (system prompts, skills, tools)

If `list_api_endpoints` doesn't show an endpoint you expected, you lack the scope — inform the user, you cannot escalate your own permissions.

---

## Workspace Management

```python
# Workspace details (includes bots list in response)
call_api("GET", "/api/v1/workspaces/{ws_id}")

# Container status
call_api("GET", "/api/v1/workspaces/{ws_id}/status")

# Container logs (last 300 lines)
call_api("GET", "/api/v1/workspaces/{ws_id}/logs?tail=300")

# Channels belonging to bots in the workspace
call_api("GET", "/api/v1/workspaces/{ws_id}/channels")
```

## Bot Membership (read/update only)

The server runs in single-workspace mode: every bot is a permanent member of the default workspace, auto-enrolled at server startup. The `POST` and `DELETE` membership endpoints return `410 Gone` — don't call them. Only the read and update endpoints are usable.

```python
# Get specific bot's workspace config
call_api("GET", "/api/v1/workspaces/{ws_id}/bots/{bot_id}")

# Update bot workspace config (role, cwd_override, write_access, system_prompt, ...)
call_api("PUT", "/api/v1/workspaces/{ws_id}/bots/{bot_id}",
         body='{"role":"member","write_access":["/workspace/common/specs"]}')
```

## Indexing

```python
# Trigger full reindex (file content + embeddings)
call_api("POST", "/api/v1/workspaces/{ws_id}/reindex")

# Get full indexing config (global, workspace-level, per-bot)
call_api("GET", "/api/v1/workspaces/{ws_id}/indexing")

# Update per-bot indexing overrides
call_api("PUT", "/api/v1/workspaces/{ws_id}/bots/{bot_id}/indexing",
         body='{"enabled":true,"extensions":[".py",".md",".ts"]}')
```

## File Operations (via API — alternative to exec_command)

```python
# Browse files
call_api("GET", "/api/v1/workspaces/{ws_id}/files?path=/workspace/common")

# Read file
call_api("GET", "/api/v1/workspaces/{ws_id}/files/content?path=/workspace/common/spec.md")

# Write file
call_api("PUT", "/api/v1/workspaces/{ws_id}/files/content?path=/workspace/common/spec.md",
         body='{"content":"# Project Spec\\n..."}')
```

## Channel Management

```python
# List channels for bots in the workspace
call_api("GET", "/api/v1/workspaces/{ws_id}/channels")

# Inject message into a bot's channel (triggers processing)
call_api("POST", "/api/v1/channels/{channel_id}/messages",
         body='{"content":"New instructions","run_agent":true}')
# Returns {"task_id":"..."} — track via list_tasks / get_task_result.
```

## Task Monitoring

Use the dedicated task tools rather than raw API calls when possible — they handle parsing and pagination:

- `list_tasks()` — list active and recent tasks
- `get_task_result(task_id)` — fetch status and output for a specific task
- `cancel_task(task_id)` — cancel a running task

For polling, call `get_task_result` at 5s+ intervals until status is `complete` or `failed`.
