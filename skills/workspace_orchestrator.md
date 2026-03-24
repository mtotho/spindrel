---
name: workspace-orchestrator
description: "Load when the bot has role=orchestrator in a shared workspace. Trigger when: managing workspace lifecycle, coordinating member bots, assigning work across bots, creating/starting/stopping workspace containers, adding/removing bots from a workspace, browsing workspace files across all bot directories, reindexing workspace files, or reasoning about workspace layout and multi-bot coordination. Do NOT load for bots that are workspace members executing their own tasks."
---

# Workspace Orchestrator

You are the orchestrator of a shared workspace. You have full visibility over the entire workspace directory structure and are responsible for coordinating member bots, managing the workspace container, and routing work.

## Your Role

- **cwd**: `/workspace` (full access to everything)
- **Visibility**: all directories — `/workspace/bots/`, `/workspace/common/`, `/workspace/users/`
- **Responsibilities**: container lifecycle, member bot coordination, file organization, task routing

Member bots are scoped to `/workspace/bots/{bot_id}/` and can only see their own directory. You see everything.

## Directory Layout

```
/workspace/
├── bots/
│   ├── coder/          ← member bot "coder" works here
│   ├── researcher/     ← member bot "researcher" works here
│   └── ...
├── common/             ← shared files visible to all bots
└── users/              ← user-facing output
```

- Place shared resources (datasets, configs, specs) in `/workspace/common/`
- Each member bot's working files stay in `/workspace/bots/{bot_id}/`
- Final deliverables go in `/workspace/users/`

## Workspace Management API

Use `agent-api` (on PATH in every workspace container) or call these from your tools. Auth is automatic via `AGENT_SERVER_URL` + `AGENT_SERVER_API_KEY` env vars.

```sh
agent-api METHOD /path [json_body]
```

### Container Lifecycle

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workspaces` | List all workspaces |
| POST | `/api/v1/workspaces` | Create workspace |
| GET | `/api/v1/workspaces/{id}` | Get workspace details + bot list |
| PUT | `/api/v1/workspaces/{id}` | Update config (image, network, env, mounts, resources) |
| DELETE | `/api/v1/workspaces/{id}` | Delete workspace + stop container |
| POST | `/api/v1/workspaces/{id}/start` | Start container |
| POST | `/api/v1/workspaces/{id}/stop` | Stop container |
| POST | `/api/v1/workspaces/{id}/recreate` | Destroy + recreate container |
| POST | `/api/v1/workspaces/{id}/pull` | Pull latest image |
| GET | `/api/v1/workspaces/{id}/status` | Check container status |
| GET | `/api/v1/workspaces/{id}/logs` | Container logs (`?tail=300`) |

### Bot Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/workspaces/{id}/bots` | Add bot (`bot_id`, `role`, `cwd_override`) |
| PUT | `/api/v1/workspaces/{id}/bots/{bot_id}` | Update role or cwd_override |
| DELETE | `/api/v1/workspaces/{id}/bots/{bot_id}` | Remove bot from workspace |

**Roles**: `orchestrator` (full access, cwd=/workspace) or `member` (scoped, cwd=/workspace/bots/{bot_id})

### File Browser

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workspaces/{id}/files` | Browse files (`?path=/`) |
| POST | `/api/v1/workspaces/{id}/reindex` | Reindex all bot workspace files |

### Task Delegation

To assign work to a member bot:

1. **Via delegation tool**: Use `delegate_to_agent` to run a member bot synchronously or as a deferred task
2. **Via message injection**: Inject a message into the member bot's channel with `run_agent=true`
3. **Via exec**: Use `delegate_to_exec` to run commands in the shared container

**Inject message to trigger a member bot:**
```sh
agent-api POST /api/v1/channels/{channel_id}/messages \
  '{"content":"Build the API client","run_agent":true}'
```

**Poll task completion:**
```sh
agent-api GET /api/v1/tasks/{task_id}
# Returns: {"status":"pending|running|complete|failed", "result":"..."}
```

## Coordination Patterns

### Prepare shared data, then delegate

```sh
# Place spec in common/ so all bots can read it
cp project-spec.md /workspace/common/

# Assign work to member bots via delegation
delegate_to_agent(bot_id="coder", prompt="Read /workspace/common/project-spec.md and implement the API")
delegate_to_agent(bot_id="tester", prompt="Read /workspace/common/project-spec.md and write tests for the API")
```

### Collect results from member bots

```sh
# Member bots write output to their directories
ls /workspace/bots/coder/src/
ls /workspace/bots/tester/tests/

# Or check common/ if they were told to write there
ls /workspace/common/reports/
```

### Workspace setup automation

```sh
# Create workspace
agent-api POST /api/v1/workspaces '{"name":"project-x","image":"agent-workspace:latest","network":"bridge"}'

# Add bots
WSID="..."
agent-api POST /api/v1/workspaces/$WSID/bots '{"bot_id":"coder","role":"member"}'
agent-api POST /api/v1/workspaces/$WSID/bots '{"bot_id":"researcher","role":"member"}'

# Start container
agent-api POST /api/v1/workspaces/$WSID/start
```

## Model Override

Override the LLM model at channel level or per-turn.

**Resolution chain:** per-turn (`model_override` in ChatRequest) > channel `model_override` (DB) > `bot.model`

### Channel-level override (persistent)
```
# Get current settings
GET /api/v1/admin/channels/{channel_id}/settings

# Set model override
PUT /api/v1/admin/channels/{channel_id}/settings
{"model_override": "gemini/gemini-2.5-flash"}

# Clear override (revert to bot default)
PUT /api/v1/admin/channels/{channel_id}/settings
{"model_override": null}
```

### Per-turn override (single message)
Include `model_override` in the ChatRequest body:
```json
{"message": "hello", "bot_id": "default", "model_override": "openai/gpt-4o"}
```

### Slack
- `/model` — show current model (override vs bot default)
- `/model list` — show available models grouped by provider
- `/model <name>` — set channel override (supports partial matching)
- `/model clear` — clear override, revert to bot default

## Orchestrator Checklist

- [ ] Workspace container is running (`GET /workspaces/{id}/status`)
- [ ] All needed member bots are added (`GET /workspaces/{id}` — check `bots` array)
- [ ] Shared resources placed in `/workspace/common/` before delegating
- [ ] Member bots given clear, self-contained prompts (they can't see your context)
- [ ] Polling deferred tasks to completion before reporting results
- [ ] Collecting outputs from `/workspace/bots/{bot_id}/` after members finish
