---
name: Workspace API Reference
description: >
  Server API endpoints, permissions, and scopes reference for workspace orchestration.
  Load when calling admin or workspace endpoints from the in-process API tools.
---

# Workspace API Reference

The server exposes two in-process tools for scoped API access:

- `list_api_endpoints(scope=...)`
- `call_api(method, path, body)`

Start with `list_api_endpoints()` in a fresh context if you are unsure what your key
permits.

## Scope expectations

The `workspace_bot` preset typically includes:

- `chat`
- `bots:read`
- `channels:read/write`
- `sessions:read`
- `tasks:read/write`
- `documents:read/write`
- `todos:read/write`
- `workspaces.files:read/write`
- `attachments:read`

Common additions:

- `workspaces:read`
- `workspaces:write`
- `bots:write`

If an endpoint does not appear in `list_api_endpoints()`, assume you do not have access.

## Workspace operations

```python
call_api("GET", "/api/v1/workspaces/{ws_id}")
call_api("GET", "/api/v1/workspaces/{ws_id}/status")
call_api("GET", "/api/v1/workspaces/{ws_id}/logs?tail=300")
call_api("GET", "/api/v1/workspaces/{ws_id}/channels")
```

## Bot membership and config

Bots are permanent members of the default workspace in the current single-workspace model.
Read and update membership/config state; do not expect add/remove membership endpoints to work.

```python
call_api("GET", "/api/v1/workspaces/{ws_id}/bots/{bot_id}")
call_api("PUT", "/api/v1/workspaces/{ws_id}/bots/{bot_id}",
         body='{"role":"member","write_access":["/workspace/common/specs"]}')
```

## Indexing

```python
call_api("POST", "/api/v1/workspaces/{ws_id}/reindex")
call_api("GET", "/api/v1/workspaces/{ws_id}/indexing")
call_api("PUT", "/api/v1/workspaces/{ws_id}/bots/{bot_id}/indexing",
         body='{"enabled":true,"extensions":[".py",".md",".ts"]}')
```

## File operations

```python
call_api("GET", "/api/v1/workspaces/{ws_id}/files?path=/workspace/common")
call_api("GET", "/api/v1/workspaces/{ws_id}/files/content?path=/workspace/common/spec.md")
call_api("PUT", "/api/v1/workspaces/{ws_id}/files/content?path=/workspace/common/spec.md",
         body='{"content":"# Project Spec\\n..."}')
```

## Channels and tasks

```python
call_api("GET", "/api/v1/workspaces/{ws_id}/channels")
call_api("POST", "/api/v1/channels/{channel_id}/messages",
         body='{"content":"New instructions","run_agent":true}')
```

Prefer dedicated task tools when possible:

- `list_tasks()`
- `get_task_result(task_id)`
- `cancel_task(task_id)`
