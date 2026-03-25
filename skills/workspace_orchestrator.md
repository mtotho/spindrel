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

### Skills & Knowledge Management

Create and manage skills (reusable knowledge chunks) that bots can reference. Skills are auto-embedded for RAG retrieval.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/skills` | List all skills |
| POST | `/api/v1/admin/skills` | Create skill (`{id, name, content}`) |
| GET | `/api/v1/admin/skills/{id}` | Get skill by ID |
| PUT | `/api/v1/admin/skills/{id}` | Update skill (`{name?, content?}`) |
| DELETE | `/api/v1/admin/skills/{id}` | Delete skill |

**Create a skill from workspace content:**
```sh
# Write workspace knowledge as a reusable skill
agent-api POST /api/v1/admin/skills '{
  "id": "project-api-spec",
  "name": "Project API Specification",
  "content": "# API Spec\n\n## Endpoints\n\n..."
}'
```

**Assign skill to a bot** — add the skill ID to the bot's `skills` array:
```sh
agent-api PUT /api/v1/admin/bots/coder '{"skills": [{"id": "project-api-spec"}]}'
```

**Pattern: shared knowledge via skills** — create a skill from shared workspace content so all workspace bots can reference it. This is preferred over duplicating content in each bot's prompt.

### Custom Tools via File Drop

Tools are Python files with `@register` decorators. Agents can create tools by writing `.py` files to directories listed in `TOOL_DIRS`:

```sh
# Write a tool file to a workspace tool directory
cat > /workspace/common/tools/my_tool.py << 'EOF'
from app.tools.registry import register

@register({
    "name": "my_custom_tool",
    "description": "Does something useful",
    "parameters": {"type": "object", "properties": {"input": {"type": "string"}}}
})
async def my_custom_tool(input: str) -> str:
    return f"Processed: {input}"
EOF
```

Tools are discovered at server startup. After writing a tool file, the server must be restarted for it to take effect.

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

## Workspace Skills

Workspace skills are `.md` files auto-discovered from the workspace filesystem and injected into bot context. Three modes determine when/how content is injected:

### Directory Conventions

```
/workspace/
├── common/
│   ├── prompts/
│   │   └── base.md              ← replaces global base prompt for all workspace bots
│   └── skills/
│       ├── pinned/*.md          ← injected into every request (full content)
│       ├── rag/*.md             ← retrieved by semantic similarity
│       ├── on-demand/*.md       ← available via get_workspace_skill tool call
│       └── *.md                 ← top-level defaults to pinned
└── bots/
    └── <bot-id>/
        ├── prompts/
        │   └── base.md          ← concatenated AFTER common base prompt (per-bot)
        └── skills/
            ├── pinned/*.md
            ├── rag/*.md
            ├── on-demand/*.md
            └── *.md             ← top-level defaults to pinned
```

### Skill Modes

| Mode | Subdirectory | Behavior |
|------|-------------|----------|
| **Pinned** | `pinned/` or top-level | Full content injected into every turn's system messages |
| **RAG** | `rag/` | Chunked, embedded, and retrieved by semantic similarity to user message |
| **On-demand** | `on-demand/` | Skill index shown; agent calls `get_workspace_skill(path)` to retrieve |

### Creating Skills

```sh
# Create a pinned skill available to all bots
cat > /workspace/common/skills/pinned/coding-standards.md << 'EOF'
# Coding Standards
- Use TypeScript strict mode
- Follow ESLint config
EOF

# Create a RAG skill (retrieved when relevant)
cat > /workspace/common/skills/rag/api-reference.md << 'EOF'
# API Reference
## GET /users
Returns list of users...
EOF

# Create a bot-specific on-demand skill
mkdir -p /workspace/bots/coder/skills/on-demand/
cat > /workspace/bots/coder/skills/on-demand/deployment-guide.md << 'EOF'
# Deployment Guide
Step-by-step deployment process...
EOF
```

### Reindexing Skills

After creating or modifying workspace skill files, reindex to update embeddings:

```sh
agent-api POST /api/v1/workspaces/$WSID/reindex-skills
# Returns: {"total": 5, "embedded": 2, "unchanged": 3, "errors": 0}
```

### Listing Discovered Skills

```sh
agent-api GET /api/v1/workspaces/$WSID/skills
# Returns: {"skills": [{"skill_id": "ws:...", "source_path": "common/skills/pinned/coding.md", "mode": "pinned", ...}]}
```

## Workspace Base Prompt Override

Replace the global base prompt with workspace-specific content:

- **`common/prompts/base.md`** — replaces the global base prompt for all workspace bots
- **`bots/<bot-id>/prompts/base.md`** — concatenated after common (per-bot additions)

If `common/prompts/base.md` doesn't exist, the global base prompt is used as fallback.

### Config Inheritance

- **Workspace level**: `workspace_skills_enabled` and `workspace_base_prompt_enabled` (default: true)
- **Channel level**: `workspace_skills_enabled` and `workspace_base_prompt_enabled` (null = inherit from workspace)

```sh
# Update workspace settings
agent-api PUT /api/v1/workspaces/$WSID '{"workspace_skills_enabled": true, "workspace_base_prompt_enabled": true}'

# Override at channel level
agent-api PUT /api/v1/admin/channels/$CHID/settings '{"workspace_skills_enabled": false}'
```

## Prompt Template Management

Create, list, and link prompt templates to channels for compaction and heartbeat prompts.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/prompt-templates?workspace_id={id}` | List workspace templates |
| POST | `/api/v1/prompt-templates` | Create template |
| PUT | `/api/v1/prompt-templates/{id}` | Update template |
| DELETE | `/api/v1/prompt-templates/{id}` | Delete template |

**Source types:**
- `manual` — inline content stored directly
- `workspace_file` — reads content from a workspace filesystem path (auto-syncs on reindex)

**Create a template from a workspace file:**
```sh
agent-api POST /api/v1/prompt-templates '{
  "name": "Research Compaction",
  "description": "Custom compaction prompt for research channels",
  "category": "compaction",
  "workspace_id": "'$WSID'",
  "source_type": "workspace_file",
  "source_path": "common/prompts/research-compaction.md"
}'
```

**Create a manual template:**
```sh
agent-api POST /api/v1/prompt-templates '{
  "name": "Heartbeat Check-in",
  "content": "Review recent activity and summarize progress.",
  "category": "heartbeat",
  "workspace_id": "'$WSID'"
}'
```

**List templates for a workspace:**
```sh
agent-api GET "/api/v1/prompt-templates?workspace_id=$WSID"
```

## Channel Prompt Configuration

Configure compaction and heartbeat prompts per channel. Use the workspace channels endpoint for a batch overview, or individual channel endpoints for full settings.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workspaces/{id}/channels` | List channels with prompt config (batch) |
| GET | `/api/v1/admin/channels/{id}/settings` | Full channel settings |
| PUT | `/api/v1/admin/channels/{id}/settings` | Update compaction prompt/template |
| GET | `/api/v1/admin/channels/{id}/heartbeat` | Heartbeat config |
| PUT | `/api/v1/admin/channels/{id}/heartbeat` | Update heartbeat prompt/template |

**Batch overview** — returns all workspace channels with inline compaction + heartbeat config + resolved template names:
```sh
agent-api GET /api/v1/workspaces/$WSID/channels
# Returns: [{id, name, bot_id, bot_name, heartbeat_enabled, heartbeat_prompt_template_name, compaction_prompt_template_name, ...}]
```

**Link a prompt template to a channel's compaction:**
```sh
agent-api PUT /api/v1/admin/channels/$CHID/settings '{
  "compaction_prompt_template_id": "'$TEMPLATE_ID'"
}'
```

**Set an inline compaction prompt (no template):**
```sh
agent-api PUT /api/v1/admin/channels/$CHID/settings '{
  "memory_knowledge_compaction_prompt": "Focus on preserving technical decisions and code references."
}'
```

**Update heartbeat prompt template:**
```sh
agent-api PUT /api/v1/admin/channels/$CHID/heartbeat '{
  "prompt_template_id": "'$TEMPLATE_ID'",
  "enabled": true,
  "interval_minutes": 30
}'
```

**Resolution chain:** channel template > channel inline prompt > bot default

## Bot Skills & Tools Management

Manage which skills and tools are available to bots and channels.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/bots/{id}` | Get bot config (includes skills, tools) |
| PUT | `/api/v1/admin/bots/{id}` | Update bot skills/tools |
| GET | `/api/v1/admin/tools` | List all available tools |
| GET | `/api/v1/admin/skills` | List all skills |
| POST | `/api/v1/admin/skills` | Create skill |
| PUT | `/api/v1/admin/skills/{id}` | Update skill |
| GET | `/api/v1/workspaces/{id}/skills` | List workspace-discovered skills |
| POST | `/api/v1/workspaces/{id}/reindex-skills` | Reindex workspace skills |
| GET | `/api/v1/admin/channels/{id}/effective-tools` | Resolved tools after overrides |

### Skill Modes
- **Pinned** — full content injected into every turn's system messages
- **RAG** — chunked, embedded, retrieved by semantic similarity
- **On-demand** — skill index shown; agent calls `get_skill(id)` to retrieve

### Tool Types
- **local_tools** — Python functions registered on the server
- **mcp_servers** — remote MCP protocol endpoints
- **client_tools** — actions handled client-side (e.g. shell_exec)
- **pinned_tools** — always included, bypass tool retrieval filtering

### Workspace skill auto-discovery
Skills are auto-discovered from workspace filesystem:
- `common/skills/` — available to all bots in workspace
- `bots/{bot-id}/skills/` — bot-specific skills
- Subdirectories: `pinned/`, `rag/`, `on-demand/` (top-level defaults to pinned)

**Add a skill to a bot:**
```sh
agent-api PUT /api/v1/admin/bots/coder '{"skills": [{"id": "project-api-spec"}]}'
```

**List all tools available to assign:**
```sh
agent-api GET /api/v1/admin/tools
```

**Channel-level tool/skill overrides** — override or disable specific tools/skills at the channel level:
```sh
# Override tools for a channel (replaces bot defaults)
agent-api PUT /api/v1/admin/channels/$CHID/settings '{
  "local_tools_override": ["web_search", "save_memory"],
  "skills_override": [{"id": "custom-skill"}]
}'

# Disable specific tools while keeping others
agent-api PUT /api/v1/admin/channels/$CHID/settings '{
  "local_tools_disabled": ["exec_sandbox"]
}'
```

**Check resolved tools for a channel** (after overrides applied):
```sh
agent-api GET /api/v1/admin/channels/$CHID/effective-tools
```

## Orchestrator Checklist

- [ ] Workspace container is running (`GET /workspaces/{id}/status`)
- [ ] All needed member bots are added (`GET /workspaces/{id}` — check `bots` array)
- [ ] Shared resources placed in `/workspace/common/` before delegating
- [ ] Workspace skills created in `common/skills/` or `bots/<id>/skills/` as needed
- [ ] Skills reindexed after modifications (`POST /workspaces/{id}/reindex-skills`)
- [ ] Base prompt customized if needed (`common/prompts/base.md`)
- [ ] Prompt templates created for reusable compaction/heartbeat prompts
- [ ] Channel compaction + heartbeat prompts configured (`GET /workspaces/{id}/channels` to review)
- [ ] Bot skills and tools assigned appropriately (`GET /admin/bots/{id}` to verify)
- [ ] Channel-level tool/skill overrides applied where needed
- [ ] Member bots given clear, self-contained prompts (they can't see your context)
- [ ] Polling deferred tasks to completion before reporting results
- [ ] Collecting outputs from `/workspace/bots/{bot_id}/` after members finish
