---
name: workspace-api-reference
description: >
  Server API endpoints, agent CLI usage, permissions and scopes reference. Load when
  making API calls from the workspace container, checking permissions, using the agent
  CLI, or performing file/task/workspace operations via the API.
---

# Server API Reference

All paths relative to `AGENT_SERVER_URL`. Use `agent api` or `agent-api` for authenticated requests.

## Discovering Your Permissions

Your API key determines what server endpoints you can call. Always check on first run:

```sh
agent discover              # Quick list of available endpoints
agent docs                  # Full API reference filtered to your scopes
```

### Common Scopes for Orchestrators

The `workspace_bot` preset provides: `chat`, `bots:read`, `channels:read/write`, `sessions:read`, `tasks:read/write`, `documents:read/write`, `todos:read/write`, `workspaces.files:read/write`, `attachments:read`.

Orchestrators often need additional scopes:
- `workspaces:read` — list workspaces, check container status, view logs
- `workspaces:write` — start/stop/recreate containers, manage bot membership (implies `workspaces:read` and `workspaces.files:*`)
- `bots:write` — modify bot configs (system prompts, skills, tools)

If `agent discover` shows you lack a needed scope, inform the user — you cannot escalate your own permissions.

### API Docs Injection (api_reference skill)

If API docs injection is enabled on your bot config, you automatically get an `api_reference` entry in your skill index. Modes:
- **on_demand**: Short hint injected; call `get_skill("api_reference")` when needed
- **rag**: Full docs injected when your message mentions API-related keywords
- **pinned**: Full docs always in context (~1K tokens)

---

## Workspace Management

```sh
# Get workspace details (includes bots list in response)
agent api GET /api/v1/workspaces/{ws_id}

# Container status
agent api GET /api/v1/workspaces/{ws_id}/status

# Container logs (last 300 lines)
agent api GET /api/v1/workspaces/{ws_id}/logs?tail=300

# List channels belonging to workspace bots
agent api GET /api/v1/workspaces/{ws_id}/channels
```

## Bot Membership (add/update/remove bots in workspace)

```sh
# Get specific bot's workspace config
agent api GET /api/v1/workspaces/{ws_id}/bots/{bot_id}

# Add bot to workspace
agent api POST /api/v1/workspaces/{ws_id}/bots \
  '{"bot_id":"my-bot","workspace_dir":"/workspace/my-bot"}'

# Update bot workspace config (dir, indexing overrides)
agent api PUT /api/v1/workspaces/{ws_id}/bots/{bot_id} \
  '{"workspace_dir":"/workspace/my-bot","indexing":{"enabled":true}}'

# Remove bot from workspace
agent api DELETE /api/v1/workspaces/{ws_id}/bots/{bot_id}
```

## Skills & Indexing

```sh
# List discovered workspace skill files
agent api GET /api/v1/workspaces/{ws_id}/skills

# Trigger full reindex (file content + embeddings)
agent api POST /api/v1/workspaces/{ws_id}/reindex

# Re-discover and re-embed workspace skills only
agent api POST /api/v1/workspaces/{ws_id}/reindex-skills

# Get full indexing config (global, workspace-level, per-bot)
agent api GET /api/v1/workspaces/{ws_id}/indexing

# Update per-bot indexing overrides
agent api PUT /api/v1/workspaces/{ws_id}/bots/{bot_id}/indexing \
  '{"enabled":true,"extensions":[".py",".md",".ts"]}'
```

## File Operations (via API — alternative to exec_command)

```sh
# Browse files
agent api GET /api/v1/workspaces/{ws_id}/files?path=/workspace/common

# Read file
agent api GET /api/v1/workspaces/{ws_id}/files/content?path=/workspace/common/spec.md

# Write file
agent api PUT /api/v1/workspaces/{ws_id}/files/content?path=/workspace/common/spec.md \
  '{"content":"# Project Spec\n..."}'
```

## Channel Management

```sh
# List channels for workspace bots
agent api GET /api/v1/workspaces/{ws_id}/channels

# Inject message into a bot's channel (triggers processing)
agent api POST /api/v1/channels/{channel_id}/messages \
  '{"content":"New instructions","run_agent":true}'
# Returns {"task_id":"..."} — poll with: agent tasks wait <task_id>
```

## Task Monitoring

```sh
agent tasks                       # List all tasks
agent tasks get <task_id>         # Get status + result
agent tasks wait <task_id>        # Block until complete/failed (polls every 5s)
```
