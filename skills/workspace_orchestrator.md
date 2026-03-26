---
name: workspace-orchestrator
description: "Load when the bot has role=orchestrator in a shared workspace. Trigger when: managing workspace lifecycle, coordinating member bots, assigning work across bots, creating/starting/stopping workspace containers, adding/removing bots from a workspace, browsing workspace files across all bot directories, reindexing workspace files, or reasoning about workspace layout and multi-bot coordination. Do NOT load for bots that are workspace members executing their own tasks."
---

# Workspace Orchestrator

You are the orchestrator of a shared workspace — responsible for container lifecycle, member bot coordination, file organization, and task routing.

- **cwd**: `/workspace` (full access to everything)
- **Member bots**: default to `/workspace/bots/{bot_id}/`
- All API calls via `agent-api METHOD /path [json_body]` (auth is automatic)
- **API reference**: `agent-api GET /openapi.json` — full OpenAPI spec (all endpoints, parameters, request/response schemas). Large payload. Fetch when you need exact field names/types or want to discover endpoints not listed below.
- **Interactive docs**: `agent-api GET /docs` — Swagger UI (HTML). Useful if rendering for a human, not for programmatic use.

## Directory Layout

```
/workspace/
├── bots/{bot_id}/         ← member bot working directories
│   ├── skills/            ← bot-specific skills (pinned/, rag/, on-demand/)
│   └── prompts/base.md    ← per-bot base prompt (appended after common)
├── common/
│   ├── skills/            ← shared skills (pinned/, rag/, on-demand/)
│   └── prompts/base.md    ← replaces global base prompt for all workspace bots
└── users/                 ← user-facing output
```

No sandboxing within the container — any bot can read any path. The role only controls default cwd and `search_workspace` index scope.

## Workspace Management API

### Container Lifecycle

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/workspaces` | Create workspace |
| GET | `/api/v1/workspaces/{id}` | Get workspace details + bot list |
| PUT | `/api/v1/workspaces/{id}` | Update config (image, network, env, mounts, indexing_config) |
| DELETE | `/api/v1/workspaces/{id}` | Delete workspace + stop container |
| POST | `/api/v1/workspaces/{id}/start` | Start container |
| POST | `/api/v1/workspaces/{id}/stop` | Stop container |
| POST | `/api/v1/workspaces/{id}/recreate` | Destroy + recreate container |
| GET | `/api/v1/workspaces/{id}/status` | Check container status |
| GET | `/api/v1/workspaces/{id}/logs?tail=300` | Container logs |

### Bot Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/workspaces/{id}/bots` | Add bot (`bot_id`, `role`, `cwd_override`) |
| GET | `/api/v1/workspaces/{id}/bots/{bot_id}` | Get bot config |
| PUT | `/api/v1/workspaces/{id}/bots/{bot_id}` | Update bot config (system_prompt, model, skills, etc.) |
| DELETE | `/api/v1/workspaces/{id}/bots/{bot_id}` | Remove bot from workspace |

Updatable bot fields: `system_prompt`, `name`, `model`, `skills`, `local_tools`, `persona`, `persona_content`, `role`, `cwd_override`.

### Files & Indexing

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workspaces/{id}/files?path=/` | Browse files |
| GET | `/api/v1/workspaces/{id}/indexing` | View indexing config (global, workspace, per-bot resolved) |
| PUT | `/api/v1/workspaces/{id}/bots/{bot_id}/indexing` | Per-bot indexing overrides (patterns, top_k, similarity_threshold, include_bots, enabled) |
| POST | `/api/v1/workspaces/{id}/reindex` | Reindex all bot workspace files |

**Cross-bot file visibility**: Set `include_bots` on a bot's indexing config to also index other bots' directories for semantic search.

### Channel Config (Composite Endpoint)

Read and update ALL channel settings + heartbeat config in a single call:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/channels/{id}/config` | All channel settings + heartbeat (flat) |
| PATCH | `/api/v1/channels/{id}/config` | Update any subset of fields |
| GET | `/api/v1/channels?include_heartbeat=true` | List channels with heartbeat status |
| GET | `/api/v1/workspaces/{id}/channels` | Batch overview with activity metrics |

Only send fields you want to change — `exclude_unset` semantics. Heartbeat fields are prefixed with `heartbeat_`.

**Channel settings fields:**
- Behavior: `require_mention`, `passive_memory`, `allow_bot_messages`, `workspace_rag`, `max_iterations`
- Model: `model_override`, `model_provider_id_override`
- Compaction: `context_compaction`, `compaction_interval`, `compaction_keep_turns`, `compaction_prompt_template_id`, `memory_knowledge_compaction_prompt`
- Compression: `context_compression`, `compression_model`, `compression_threshold`, `compression_keep_turns`, `compression_prompt`
- Summarizer: `summarizer_enabled`, `summarizer_threshold_minutes`, `summarizer_message_count`, `summarizer_target_size`, `summarizer_prompt`, `summarizer_model`
- Elevation: `elevation_enabled`, `elevation_threshold`, `elevated_model`
- Tool overrides: `local_tools_override`, `local_tools_disabled`, `mcp_servers_override`, `mcp_servers_disabled`, `client_tools_override`, `client_tools_disabled`, `pinned_tools_override`, `skills_override`, `skills_disabled`, `workspace_skills_enabled`, `workspace_base_prompt_enabled`

**Heartbeat fields (prefixed `heartbeat_`):**
- `heartbeat_enabled`, `heartbeat_interval_minutes` (min 1, default 60), `heartbeat_model`, `heartbeat_model_provider_id`, `heartbeat_prompt`, `heartbeat_prompt_template_id`, `heartbeat_dispatch_results`, `heartbeat_trigger_response`, `heartbeat_quiet_start` ("HH:MM"), `heartbeat_quiet_end` ("HH:MM"), `heartbeat_timezone`
- Read-only: `heartbeat_last_run_at`, `heartbeat_next_run_at`

**Examples:**
```sh
# Read all config
agent-api GET /api/v1/channels/$CHID/config

# Enable heartbeat with model
agent-api PATCH /api/v1/channels/$CHID/config '{"heartbeat_enabled": true, "heartbeat_interval_minutes": 30, "heartbeat_model": "gemini/gemini-2.5-flash"}'

# Set compaction + summarizer
agent-api PATCH /api/v1/channels/$CHID/config '{"context_compaction": true, "compaction_interval": 8, "summarizer_enabled": true, "summarizer_threshold_minutes": 45}'

# Override tools for a channel
agent-api PATCH /api/v1/channels/$CHID/config '{"local_tools_override": ["web_search", "save_memory"]}'

# Set model override
agent-api PATCH /api/v1/channels/$CHID/config '{"model_override": "gemini/gemini-2.5-flash"}'

# Clear override (revert to bot default)
agent-api PATCH /api/v1/channels/$CHID/config '{"model_override": null}'

# Scan channels for heartbeat status
agent-api GET "/api/v1/channels?include_heartbeat=true"
```

**Additional heartbeat actions (admin API):**
```sh
agent-api POST /api/v1/admin/channels/$CHID/heartbeat/toggle   # Quick toggle
agent-api POST /api/v1/admin/channels/$CHID/heartbeat/fire     # Fire immediately
```

**Effective tools** (resolved after channel overrides):
```sh
agent-api GET /api/v1/admin/channels/$CHID/effective-tools
```

### Skills & Knowledge

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/skills` | List all skills |
| POST | `/api/v1/admin/skills` | Create skill (`{id, name, content}`) |
| PUT | `/api/v1/admin/skills/{id}` | Update skill |
| GET | `/api/v1/workspaces/{id}/skills` | List workspace-discovered skills |
| POST | `/api/v1/workspaces/{id}/reindex-skills` | Reindex workspace skills |

Skill modes: **pinned** (always injected), **rag** (semantic retrieval), **on-demand** (agent calls `get_skill`). Place files in `pinned/`, `rag/`, or `on-demand/` subdirs; top-level defaults to pinned.

### Prompt Templates

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/prompt-templates?workspace_id={id}` | List workspace templates |
| POST | `/api/v1/prompt-templates` | Create template (source_type: `manual` or `workspace_file`) |
| PUT | `/api/v1/prompt-templates/{id}` | Update template |

Link templates to channels via `compaction_prompt_template_id` or `heartbeat_prompt_template_id` in the config endpoint. Templates are resolved at execution time — recurring schedules always get latest content.

### Available Models

```sh
agent-api GET /api/v1/admin/models
# Returns: [{provider_id, provider_name, models: [{id, display, max_tokens}]}]
```

Use `models[].id` for model fields. `provider_id: null` = .env LiteLLM fallback.

### Scheduled Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/tasks` | List tasks (filters: `status`, `bot_id`, `channel_id`, `task_type`, `after`, `before`) |
| POST | `/api/v1/admin/tasks` | Create task or recurring schedule |
| PUT | `/api/v1/admin/tasks/{id}` | Update any field |
| DELETE | `/api/v1/admin/tasks/{id}` | Delete |

- **Schedule**: `status=active` + `recurrence` set (e.g. `+1d`) → spawns tasks on each fire
- **One-off**: `status=pending`, runs at `scheduled_at` (relative like `+2h`, ISO 8601, or null for immediate)
- Use `prompt_template_id` for recurring schedules so edits propagate
- `model_override` / `model_provider_id_override` supported

### Agent Turns (Troubleshooting)

```sh
agent-api GET "/api/v1/admin/turns?channel_id=$CHID&count=10"
agent-api GET "/api/v1/admin/turns?has_error=true&after=1h"
agent-api GET "/api/v1/admin/turns?bot_id=coder&count=10"
```

Params: `count` (1-200), `channel_id`, `bot_id`, `after`/`before` (ISO or relative), `has_error`, `has_tool_calls`, `search`.

### Server Logs

```sh
agent-api GET "/api/v1/admin/server-logs?level=ERROR&tail=100"
agent-api GET "/api/v1/admin/server-logs?search=workspace&since_minutes=30"
```

Params: `tail` (1-5000), `level` (DEBUG/INFO/WARNING/ERROR), `logger`, `search`, `since_minutes`.

## Task Delegation

1. **`delegate_to_agent`** — run a member bot synchronously or deferred
2. **Message injection**: `POST /api/v1/channels/{id}/messages` with `run_agent=true`
3. **`delegate_to_exec`** — run commands in the shared container

Poll deferred tasks: `GET /api/v1/admin/tasks/{task_id}`

## Orchestrator Checklist

- Workspace container running (`GET /workspaces/{id}/status`)
- All member bots added (`GET /workspaces/{id}`)
- Shared resources in `/workspace/common/` before delegating
- Skills created and reindexed (`POST /workspaces/{id}/reindex-skills`)
- Channel config set (compaction, heartbeat, summarizer, model) via `PATCH /channels/{id}/config`
- Bot skills/tools assigned, channel overrides applied where needed
- Models listed before assigning (`GET /admin/models`)
- Recurring schedules use `prompt_template_id`
- File indexing reviewed and reindexed after changes
- Member bots given clear, self-contained prompts
- Deferred tasks polled to completion before reporting
