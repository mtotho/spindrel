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

Member bots default to `/workspace/bots/{bot_id}/` as their working directory. You default to `/workspace`.

## Roles, CWD, and Access

| Role | Default cwd | `search_workspace` scope | File access | Delegation |
|------|-------------|--------------------------|-------------|------------|
| **orchestrator** | `/workspace` | Entire workspace | All files via exec | Configured via `delegate_bots` |
| **member** | `/workspace/bots/{bot_id}` | Own `bots/{bot_id}/` only | All files via exec | Configured via `delegate_bots` |

**What roles actually control:**
- **Default working directory** — where exec commands start (`cd` target). Orchestrator gets `/workspace`, member gets `/workspace/bots/{bot_id}/`.
- **`search_workspace` index scope** — semantic file search only indexes files under the bot's workspace root. Orchestrator indexes everything; member indexes only its own directory.
- **`cwd_override`** — any bot can have a custom cwd regardless of role (set via `PUT /workspaces/{id}/bots/{bot_id}` with `cwd_override`).

**What roles do NOT control:**
- **Filesystem access** — there is no sandboxing within the container. A member bot can `cat /workspace/bots/other-bot/file.md` via exec commands. The cwd is just the default starting directory.
- **Delegation** — any bot can delegate to others if configured with `delegate_bots` in its bot config. This is independent of workspace role.
- **Context assembly** — both roles get the same skill injection, RAG, and context pipeline.

**When to use each role:**
- **orchestrator** — bots that coordinate others, manage the workspace, need `search_workspace` across all directories
- **member** — bots that do focused work in their own directory, with organized output under `bots/{bot_id}/`
- **member + `delegate_bots`** — a member that supervises other members (e.g., a synthesis bot that reads others' output and delegates tasks to them). Gets the organizational benefit of its own directory while still coordinating others.

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
- Any bot can read any path via exec — use `/workspace/common/` for intentionally shared data

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
| GET | `/api/v1/workspaces/{id}/bots/{bot_id}` | Get bot config (system_prompt, model, skills, etc.) |
| PUT | `/api/v1/workspaces/{id}/bots/{bot_id}` | Update bot config and/or workspace membership |
| DELETE | `/api/v1/workspaces/{id}/bots/{bot_id}` | Remove bot from workspace |

**Roles**: `orchestrator` (full access, cwd=/workspace) or `member` (scoped, cwd=/workspace/bots/{bot_id})

#### Reading a Bot's Config

```
GET /api/v1/workspaces/{id}/bots/{bot_id}
```

Returns:
```json
{
  "bot_id": "baking-bot",
  "name": "Baking Bot",
  "model": "gemini/gemini-2.5-flash",
  "system_prompt": "You are a baking assistant...",
  "role": "member",
  "cwd_override": null,
  "skills": [{"id": "baking-recipes", "mode": "on_demand"}],
  "local_tools": ["web_search"],
  "persona": true,
  "workspace": {"enabled": true, "indexing": {"patterns": ["**/*.md"]}},
  "indexing_enabled": true
}
```

#### Updating a Bot's Config

```
PUT /api/v1/workspaces/{id}/bots/{bot_id}
```

All fields are optional — only send what you want to change:

| Field | Type | Description |
|-------|------|-------------|
| `system_prompt` | string | Replace the bot's system prompt |
| `name` | string | Change display name |
| `model` | string | Change LLM model |
| `skills` | list | Set skill list (`[{"id": "skill-id", "mode": "on_demand"}]`) |
| `local_tools` | list | Set local tool list |
| `persona` | bool | Enable/disable persona |
| `persona_content` | string | Update persona content text |
| `role` | string | Change workspace role (`orchestrator` / `member`) |
| `cwd_override` | string | Override default working directory |

Example — update a bot's system prompt:
```json
PUT /api/v1/workspaces/{id}/bots/baking-bot
{
  "system_prompt": "You are a baking assistant specializing in sourdough. Always suggest starter maintenance tips."
}
```

Example — change model and add a skill:
```json
PUT /api/v1/workspaces/{id}/bots/baking-bot
{
  "model": "gemini/gemini-2.5-pro",
  "skills": [{"id": "baking-recipes", "mode": "on_demand"}, {"id": "nutrition-facts", "mode": "on_demand"}]
}
```

### File Browser

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workspaces/{id}/files` | Browse files (`?path=/`) |
| POST | `/api/v1/workspaces/{id}/reindex` | Reindex all bot workspace files |

### Workspace File Indexing

Workspace files are automatically indexed for semantic retrieval (RAG). When a user sends a message, relevant file chunks are retrieved by cosine similarity and injected into the bot's context.

#### How It Works

1. **Discovery** — files matching configured glob patterns are found under each bot's workspace root
2. **Chunking** — files are split into chunks using language-aware strategies (AST for Python, headers for Markdown, symbols for TS/JS, etc.)
3. **Embedding** — chunks are embedded using the configured embedding model and stored in `filesystem_chunks` table
4. **Retrieval** — on each request, user message is embedded and matched against indexed chunks by cosine similarity; top-K above threshold are injected into context

#### Supported Languages

| Extension | Chunking Strategy |
|-----------|------------------|
| `.py` | AST-based (functions, classes) |
| `.md` | Header-based (`##` splits) |
| `.yaml` / `.yml` | Key-based |
| `.json` | Key-based |
| `.ts` / `.tsx` | Symbol-based |
| `.js` / `.jsx` | Symbol-based |
| `.go` | Function-based |
| `.rs` | Function-based |
| Other | Sliding window (1500 chars, 200 overlap) |

#### Always Skipped

- **Extensions**: `.pyc`, `.pyo`, `.so`, `.dylib`, `.dll`, `.exe`, `.bin`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`, `.ico`, `.pdf`, `.zip`, `.tar`, `.gz`, `.bz2`, `.xz`, `.7z`, `.lock`, `.sum`, `.mod`
- **Directories**: `.git`, `__pycache__`, `node_modules`, `.venv`, `venv`, `.mypy_cache`, `.ruff_cache`, `dist`, `build`, `.next`
- **Files > 500KB** are skipped
- `.gitignore` patterns are respected

#### Configuration Hierarchy

Settings resolve with a three-tier cascade: **bot-explicit > workspace default > global env**

| Setting | Description | Global Default |
|---------|-------------|---------------|
| `patterns` | Glob patterns for file discovery | `["**/*.py", "**/*.md", "**/*.yaml"]` |
| `similarity_threshold` | Min cosine similarity for retrieval | `0.30` |
| `top_k` | Max chunks to inject per request | `8` |
| `watch` | Enable filesystem watcher for auto-reindex | `true` |
| `cooldown_seconds` | Min seconds between full re-indexes | `300` |
| `include_bots` | Also index these other bots' directories | `[]` |

If a bot has an explicit value, it wins. Otherwise workspace defaults apply. If neither is set, global env defaults are used.

**Cross-bot file visibility**: A member bot normally only indexes its own `bots/{bot_id}/` directory. Set `include_bots` to also index other bots' directories. This gives the bot semantic search over those files without changing its role.

```sh
# Give sag-bot visibility into baking-bot and olivia-bot's files
agent-api PUT /api/v1/workspaces/$WSID/bots/sag-bot/indexing '{
  "include_bots": ["baking-bot", "olivia-bot"]
}'
```

#### Viewing Current Config

```sh
agent-api GET /api/v1/workspaces/$WSID/indexing
```

Returns:
```json
{
  "global_defaults": {"patterns": ["**/*.py", "**/*.md", "**/*.yaml"], "similarity_threshold": 0.30, "top_k": 8, "watch": true, "cooldown_seconds": 300},
  "workspace_defaults": {"patterns": ["**/*.py", "**/*.ts"], "similarity_threshold": 0.25},
  "bots": [
    {
      "bot_id": "coder",
      "bot_name": "Coder",
      "role": "member",
      "indexing_enabled": true,
      "explicit_overrides": {"patterns": ["**/*.py"]},
      "resolved": {"patterns": ["**/*.py"], "similarity_threshold": 0.25, "top_k": 8, "watch": true, "cooldown_seconds": 300, "enabled": true}
    }
  ],
  "supported_languages": ["python (.py) — AST-based chunking", "..."],
  "skip_extensions": [".pyc", ".png", "..."],
  "skip_directories": [".git", "node_modules", "..."]
}
```

#### Setting Workspace-Level Defaults

Set default indexing config for all bots in the workspace (bots without explicit overrides inherit these):

```sh
agent-api PUT /api/v1/workspaces/$WSID '{
  "indexing_config": {
    "patterns": ["**/*.py", "**/*.ts", "**/*.md"],
    "similarity_threshold": 0.25,
    "top_k": 12
  }
}'
```

#### Per-Bot Overrides

Override indexing settings for a specific bot. Only provided fields are updated; send `null` to clear an override (inherit from workspace/global):

```sh
# Set custom patterns and top_k for coder bot
agent-api PUT /api/v1/workspaces/$WSID/bots/coder/indexing '{
  "patterns": ["**/*.py", "**/*.ts"],
  "top_k": 15
}'

# Clear top_k override (inherit from workspace or global)
agent-api PUT /api/v1/workspaces/$WSID/bots/coder/indexing '{
  "top_k": null
}'

# Disable indexing entirely for a bot
agent-api PUT /api/v1/workspaces/$WSID/bots/coder/indexing '{
  "enabled": false
}'
```

#### Triggering Re-Index

Force re-index all files for all bots in the workspace (uses each bot's resolved patterns):

```sh
agent-api POST /api/v1/workspaces/$WSID/reindex
# Returns: {"results": {"coder": {"files_indexed": 42, ...}, "researcher": {"files_indexed": 15, ...}}}
```

#### Channel-Level RAG Toggle

Disable workspace file RAG for a specific channel without changing indexing config:

```sh
agent-api PUT /api/v1/admin/channels/$CHID/settings '{"workspace_rag": false}'
```

#### Indexing Checklist

1. Review current config: `GET /workspaces/{id}/indexing`
2. Set workspace-level patterns if needed: `PUT /workspaces/{id}` with `indexing_config`
3. Set per-bot overrides where needed: `PUT /workspaces/{id}/bots/{bot_id}/indexing`
4. Tune `similarity_threshold` (lower = more results, less precise) and `top_k` (higher = more context)
5. Trigger reindex: `POST /workspaces/{id}/reindex`
6. Verify retrieval via trace events (`fs_context` events show chunk count and similarity)

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

## Available Models

Discover available LLM models dynamically. Use this to pick the right model for heartbeats, scheduled tasks, or channel overrides.

```sh
agent-api GET /api/v1/admin/models
# Returns: [{provider_id, provider_name, provider_type, models: [{id, display, max_tokens}]}]
```

- `provider_id: null` = .env LiteLLM fallback (no provider override needed)
- `models[].id` is the value for `model_override`, `model`, and similar fields
- `provider_id` is the value for `model_provider_id` and `model_provider_id_override` fields

**Workflow:** list models → pick one → assign to heartbeat, task, or channel override.

```sh
# List all models, pick one
agent-api GET /api/v1/admin/models

# Use in a heartbeat
agent-api PUT /api/v1/admin/channels/$CHID/heartbeat '{"model": "gemini/gemini-2.5-flash", "model_provider_id": "provider-uuid"}'

# Use in a scheduled task
agent-api POST /api/v1/admin/tasks '{"prompt": "...", "bot_id": "coder", "model_override": "gemini/gemini-2.5-flash", "model_provider_id_override": "provider-uuid"}'
```

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

**Batch overview** — returns all workspace channels with inline compaction + heartbeat config + activity metrics:
```sh
agent-api GET /api/v1/workspaces/$WSID/channels
# Returns: [{id, name, bot_id, bot_name, heartbeat_enabled, heartbeat_prompt_template_name,
#   compaction_prompt_template_name, last_user_turn_at, user_turns_24h, user_turns_48h, user_turns_72h, ...}]
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

**Set a custom compression prompt (overrides hardcoded default for pre-turn context compression):**
```sh
agent-api PUT /api/v1/admin/channels/$CHID/settings '{
  "compression_prompt": "Your custom compression prompt here..."
}'
```

### Summarizer (Auto-Resume)

When a channel has been idle for a configurable period, the summarizer auto-injects a summary of prior conversation into context before the first response. The summary is generated from raw messages (not compaction summaries).

```sh
agent-api PUT /api/v1/admin/channels/$CHID/settings '{
  "summarizer_enabled": true,
  "summarizer_threshold_minutes": 45,
  "summarizer_message_count": 100,
  "summarizer_target_size": 1000,
  "summarizer_model": "gemini/gemini-2.5-flash",
  "summarizer_prompt": "Focus on technical decisions and action items"
}'
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `summarizer_enabled` | bool | false | Enable auto-summarize on resume |
| `summarizer_threshold_minutes` | int | 45 | Idle minutes before triggering |
| `summarizer_message_count` | int | 100 | Max messages to include in summary |
| `summarizer_target_size` | int | 1000 | Target summary size in characters |
| `summarizer_model` | string | inherit | LLM model for summarizer (falls back to compression model) |
| `summarizer_prompt` | string | null | Custom focus prompt for the summarizer |

**Update heartbeat config (including enable/disable and model):**
```sh
agent-api PUT /api/v1/admin/channels/$CHID/heartbeat '{
  "enabled": true,
  "prompt_template_id": "'$TEMPLATE_ID'",
  "interval_minutes": 30,
  "model": "gemini/gemini-2.5-flash",
  "model_provider_id": "'$PROVIDER_ID'"
}'
```

**Heartbeat fields reference:**

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | — | Toggle on/off (null = no change) |
| `interval_minutes` | 60 | Minutes between runs (min 1) |
| `model` | `""` | Model id; empty string = inherit bot default |
| `model_provider_id` | null | Provider id; null = .env LiteLLM fallback |
| `prompt` | `""` | Inline prompt text |
| `prompt_template_id` | null | Linked template (overrides inline prompt) |
| `dispatch_results` | true | Post result to channel integration |
| `trigger_response` | false | Fire follow-up agent turn after heartbeat completes |
| `quiet_start` | null | `"HH:MM"` — suppress heartbeats after this time |
| `quiet_end` | null | `"HH:MM"` — resume heartbeats after this time |
| `timezone` | null | IANA timezone for quiet hours (e.g. `"America/New_York"`) |

**Quick toggle** (flips enabled without touching other settings):
```sh
agent-api POST /api/v1/admin/channels/$CHID/heartbeat/toggle
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

## Scheduled Tasks & Recurring Jobs

Create one-off tasks or recurring schedules via the admin API. Tasks can link to prompt templates and override models.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/tasks` | List tasks + schedules (filters: `status`, `bot_id`, `channel_id`, `task_type`, `after`, `before`) |
| GET | `/api/v1/admin/tasks/{id}` | Full task detail |
| POST | `/api/v1/admin/tasks` | Create task or recurring schedule |
| PUT | `/api/v1/admin/tasks/{id}` | Update any field |
| DELETE | `/api/v1/admin/tasks/{id}` | Hard delete |

### Task vs Schedule

- **Schedule**: `status=active` + `recurrence` set → template that spawns concrete tasks on each fire
- **One-off task**: `status=pending` → runs once at `scheduled_at` (or immediately if null)
- `run_count` tracks how many times a schedule has fired
- `parent_task_id` links spawned concrete tasks back to their schedule

### Examples

**Create an immediate one-off task:**
```sh
agent-api POST /api/v1/admin/tasks '{
  "prompt": "Summarize today'\''s activity",
  "bot_id": "researcher",
  "channel_id": "'$CHID'"
}'
```

**Create a future scheduled task:**
```sh
agent-api POST /api/v1/admin/tasks '{
  "prompt": "Run nightly report",
  "bot_id": "researcher",
  "channel_id": "'$CHID'",
  "scheduled_at": "+2h"
}'
```

**Create a recurring schedule with prompt template:**
```sh
agent-api POST /api/v1/admin/tasks '{
  "prompt": "placeholder (template overrides this)",
  "bot_id": "researcher",
  "channel_id": "'$CHID'",
  "recurrence": "+1d",
  "prompt_template_id": "'$TEMPLATE_ID'",
  "task_type": "scheduled"
}'
```

**Create a task with model override:**
```sh
agent-api POST /api/v1/admin/tasks '{
  "prompt": "Deep analysis of codebase",
  "bot_id": "coder",
  "channel_id": "'$CHID'",
  "model_override": "openai/gpt-4o",
  "model_provider_id_override": "'$PROVIDER_ID'"
}'
```

**List/filter tasks:**
```sh
# All tasks for a channel
agent-api GET "/api/v1/admin/tasks?channel_id=$CHID"

# Active schedules only
agent-api GET "/api/v1/admin/tasks?status=active&task_type=scheduled"

# Tasks from last 24 hours
agent-api GET "/api/v1/admin/tasks?after=2026-03-24T00:00:00Z"
```

**Check task status:**
```sh
agent-api GET /api/v1/admin/tasks/$TASK_ID
# Returns: {id, status, prompt, result, bot_id, channel_id, recurrence, run_count, ...}
```

**Update a schedule (change recurrence, swap template, update model):**
```sh
agent-api PUT /api/v1/admin/tasks/$TASK_ID '{
  "recurrence": "+12h",
  "prompt_template_id": "'$NEW_TEMPLATE_ID'",
  "model_override": "gemini/gemini-2.5-flash"
}'
```

**Pause a schedule:**
```sh
agent-api PUT /api/v1/admin/tasks/$TASK_ID '{"status": "complete"}'
```

**Delete a task/schedule:**
```sh
agent-api DELETE /api/v1/admin/tasks/$TASK_ID
```

### Key Concepts

- **`prompt_template_id`** — resolved at execution time; recurring schedules always get the latest template content
- **`scheduled_at` formats**: relative (`+30m`, `+2h`, `+1d`), ISO 8601 (`2026-03-25T14:00:00Z`), or null (immediate)
- **`recurrence` format**: same relative syntax (`+1h`, `+1d`, `+7d`)
- **`model_override` / `model_provider_id_override`**: null = inherit bot default; use `GET /api/v1/admin/models` to find valid values
- **`trigger_rag_loop`**: fires a follow-up agent turn after the task completes (useful for tasks that generate context the bot should react to)
- **`dispatch_type`**: auto-resolved from `channel_id` — no need to set manually

### Agent Tool vs Admin API

| Capability | `create_task` tool | `POST /admin/tasks` |
|---|---|---|
| `prompt_template_id` | No | Yes |
| `model_override` | No | Yes |
| `recurrence` | Yes | Yes |
| `trigger_rag_loop` | Yes | Yes |

Use the admin API when you need prompt templates or model overrides. Use the agent tool for simple task creation within a conversation.

## Agent Turns (Troubleshooting)

Query recent agent turns across all bots and channels. Each turn represents one user message → agent response cycle, with full tool call details, token usage, model info, errors, and timing. Use this for troubleshooting bot behavior, monitoring activity, and diagnosing failures.

```sh
# Last 20 turns (default)
agent-api GET /api/v1/admin/turns

# Last 10 turns for a specific channel
agent-api GET "/api/v1/admin/turns?channel_id=$CHID&count=10"

# Only turns with errors
agent-api GET "/api/v1/admin/turns?has_error=true&count=50"

# Turns from a specific bot in the last hour
agent-api GET "/api/v1/admin/turns?bot_id=coder&after=1h"

# Turns with tool calls from the last 30 minutes
agent-api GET "/api/v1/admin/turns?has_tool_calls=true&after=30m"

# Search for turns mentioning a keyword
agent-api GET "/api/v1/admin/turns?search=deploy&count=10"
```

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `count` | int | 20 | Max turns to return (1–200) |
| `channel_id` | UUID | — | Filter by channel |
| `bot_id` | string | — | Filter by bot ID |
| `after` | string | — | Only turns after this time (ISO 8601 or relative: `30m`, `2h`, `1d`) |
| `before` | string | — | Only turns before this time (ISO 8601) |
| `has_error` | bool | — | Filter to turns with/without errors |
| `has_tool_calls` | bool | — | Filter to turns with/without tool calls |
| `search` | string | — | Search in user message text |

**Response:**
```json
{
  "turns": [
    {
      "correlation_id": "uuid",
      "created_at": "2026-03-25T14:30:00+00:00",
      "bot_id": "coder",
      "model": "gemini/gemini-2.5-flash",
      "channel_id": "uuid",
      "channel_name": "dev-chat",
      "session_id": "uuid",
      "user_message": "Build the API client",
      "response_preview": "I'll start by creating...",
      "total_tokens": 4500,
      "prompt_tokens": 3800,
      "completion_tokens": 700,
      "iterations": 3,
      "duration_ms": 12500,
      "llm_duration_ms": 8200,
      "has_error": false,
      "tool_call_count": 2,
      "tool_calls": [
        {
          "tool_name": "exec_sandbox",
          "tool_type": "local",
          "iteration": 1,
          "duration_ms": 3200,
          "error": null,
          "arguments_preview": "{\"command\": \"npm init...\"}",
          "result_preview": "Initialized project..."
        }
      ],
      "errors": []
    }
  ],
  "total": 1,
  "count": 20
}
```

**Troubleshooting workflows:**
- **Check for failures**: `?has_error=true&after=1h` — find all recent errors
- **Monitor a bot**: `?bot_id=coder&count=10` — see what a bot has been doing
- **Channel audit**: `?channel_id=$CHID&count=50` — review all activity in a channel
- **Slow turns**: Look at `duration_ms` and `llm_duration_ms` to find bottlenecks
- **Token burn**: Check `total_tokens` across turns to monitor cost
- **Deep dive**: Use `correlation_id` with `GET /api/v1/admin/traces/{correlation_id}` for the full trace timeline

## Server Logs

Query the agent-server's own Python logs (in-memory ring buffer of the last 10,000 entries). Use this to diagnose errors, check startup health, or monitor agent activity.

```sh
# Recent 200 entries (default)
agent-api GET /api/v1/admin/server-logs

# Only errors
agent-api GET "/api/v1/admin/server-logs?level=ERROR&tail=100"

# Errors and warnings from the last 30 minutes
agent-api GET "/api/v1/admin/server-logs?level=WARNING&since_minutes=30"

# Search for a specific term
agent-api GET "/api/v1/admin/server-logs?search=workspace&tail=50"

# Filter by logger module
agent-api GET "/api/v1/admin/server-logs?logger=app.agent&tail=100"
```

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `tail` | int | 200 | Max entries to return (1–5000) |
| `level` | string | — | Min severity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `logger` | string | — | Logger name prefix (e.g. `app.agent.loop`) |
| `search` | string | — | Case-insensitive substring match in message |
| `since_minutes` | float | — | Only entries from the last N minutes |

**Response:**
```json
{
  "entries": [
    {"timestamp": 1711367400.0, "level": "ERROR", "logger": "app.agent.loop", "message": "...", "formatted": "14:30:00 ERROR [app.agent.loop] ..."}
  ],
  "total": 3,
  "levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
}
```

**Tips:**
- Start with `level=ERROR` to check for problems without loading too much data
- Use `logger=app.agent` to focus on agent loop activity
- Use `since_minutes=5` to narrow to recent activity
- Combine filters: `?level=WARNING&search=workspace&since_minutes=60`

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
- [ ] Models listed before assigning (`GET /admin/models`)
- [ ] Recurring schedules use `prompt_template_id` (not inline prompt) so edits propagate
- [ ] Heartbeat `model`/`model_provider_id` set or left empty to inherit bot default
- [ ] Task status confirmed after creation (`GET /admin/tasks/{id}`)
- [ ] File indexing config reviewed (`GET /workspaces/{id}/indexing`)
- [ ] Indexing patterns set per workspace or per bot as needed
- [ ] Workspace reindexed after config changes (`POST /workspaces/{id}/reindex`)
