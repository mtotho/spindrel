# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quality Standards

**These rules are non-negotiable. Follow them on every change.**

### Tests First
- **ALWAYS write tests for every bug fix** — write the test FIRST, verify it FAILS without the fix, then fix the code and verify it passes
- **Never leave tests failing** — if a test fails, fix it before moving on
- **Explore adjacent coverage gaps** — when fixing a bug, look for related untested code paths and add tests for those too
- Tests run via `Dockerfile.test`: `docker build -f Dockerfile.test -t agent-server-test . && docker run --rm agent-server-test`
- Full suite: `pytest tests/ integrations/ -v`
- Uses SQLite in-memory (aiosqlite) — no postgres needed
- Do NOT use `docker compose run` for tests

### UX Quality
- **Think about the user experience, not just correctness** — every change should make the product feel better to use
- Double-check your work — no bugs, verify edge cases
- Don't propose hacky guardrails when the real fix is better design
- Prefer reusing existing infrastructure over building new pipelines

### UI Quality
- **ALWAYS run `cd ui && npx tsc --noEmit` after ANY UI changes** — build failures crash prod, there is NO CI safety net
- Production build: `npx expo export --platform web` (runs in Docker via `ui/Dockerfile`)
- Common gotcha: adjacent JSX elements need `<>...</>` fragment wrappers
- **ALWAYS split large files proactively** — don't let UI files hit 1000+ lines; extract into sibling files without being asked

### Documentation
- **ALWAYS update docs when adding or changing features** — if it's user-facing, it belongs in `docs/` and/or `README.md`
- `README.md` — feature list, architecture diagram, quick start, guide index
- `docs/index.md` — MkDocs landing page with feature cards and guide links
- `docs/guides/` — per-topic setup and usage guides
- `docs/integrations/` — integration development docs
- Keep README.md and docs/index.md in sync — same feature list, same integration names, same tagline

### Code Quality
- Research existing code before making changes — understand what's there before modifying
- Prefer better design over surface-level fixes
- Reuse existing infrastructure — don't build new pipelines when existing ones work

## Development Commands

```bash
# Start all services (postgres, searxng, playwright, agent-server)
docker compose up

# Run server locally (requires postgres running)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Dev server with Slack bot auto-started (if SLACK_* vars set)
python scripts/dev-server.py

# Run migrations manually
alembic upgrade head

# CLI client (separate terminal)
cd client && pip install -e . && agent

# Run tests
pytest

# Run UI typecheck (REQUIRED after any UI changes)
cd ui && npx tsc --noEmit
```

## Where to Find Things

| I want to...                        | Look here                                              |
|-------------------------------------|--------------------------------------------------------|
| Add a local tool                    | Create `.py` in `tools/` with `@register(schema)`     |
| Add an integration tool             | `integrations/{name}/tools/`                           |
| Add a skill                         | Create `.md` in `skills/` or `integrations/{name}/skills/` |
| Add a carapace                      | Create `.yaml` in `carapaces/` or `integrations/{name}/carapaces/` |
| Add a workflow                      | Create `.yaml` in `workflows/` or `integrations/{name}/workflows/` |
| Add an API endpoint                 | `app/routers/api_v1_admin/` (admin) or `app/routers/` (bot-facing) |
| Add a UI page                       | `ui/app/(app)/` (file-based routing via Expo Router)   |
| Add an API hook                     | `ui/src/api/hooks/`                                    |
| Add a DB migration                  | `alembic revision --autogenerate -m "description"`     |
| Change runtime config               | `app/config.py` (Pydantic Settings, reads `.env`)      |
| Change how context is assembled     | `app/agent/context_assembly.py`                        |
| Change how tools are dispatched     | `app/agent/tool_dispatch.py`                           |
| Change the agent loop               | `app/agent/loop.py`                                    |
| Change LLM call behavior            | `app/agent/llm.py`                                     |
| Add/change a bot config field       | `app/agent/bots.py` (BotConfig dataclass + YAML loader)|
| Add an integration                  | `integrations/{name}/` with `setup.py`, `router.py`, etc. |
| Debug a test                        | `pytest tests/unit/test_foo.py -v -s`                  |
| Debug a production issue            | Read the code paths — don't query the DB directly      |

**Gitignored user directories** (not checked in — users create their own):
`bots/`, `skills/`, `tools/*.py`

**Checked-in examples**: `carapaces/*.yaml`, `workflows/*.yaml`

## Project Architecture

Self-hosted LLM agent server built on FastAPI + PostgreSQL (pgvector). Supports multiple LLM provider types:
- **OpenAI-compatible** (`openai` SDK client): OpenAI, Gemini, Ollama, OpenRouter, LiteLLM, vLLM, any `/v1/chat/completions` endpoint
- **Anthropic-compatible** (native `anthropic` SDK client): Direct Anthropic API, Bedrock, etc.
- **LiteLLM bonus**: When using a LiteLLM proxy, Spindrel can pull model pricing data for cost tracking

Each bot can use a different provider via `model_provider_id`. The default provider is configured via `LITELLM_BASE_URL`/`LITELLM_API_KEY` in `.env` (named for historical reasons — works with any OpenAI-compatible endpoint).

### Request Flow
`run_stream()` (loop.py) → `assemble_context()` (context_assembly.py) → `run_agent_tool_loop()` (loop.py) → `_llm_call()` (llm.py) → `dispatch_tool_call()` (tool_dispatch.py) → LLM → ... → final response

The agent loop is iterative: LLM calls tools until it returns a text response (max `AGENT_MAX_ITERATIONS` iterations). Events are streamed as JSON lines (SSE). LLM calls have automatic retry with exponential backoff for transient errors and optional fallback model (`LLM_FALLBACK_MODEL`).

### Startup Sequence (app/main.py lifespan)
1. Run Alembic migrations
2. Load server settings + integration settings from DB
3. Load provider configs from DB
4. Seed + load bot configs from `bots/*.yaml` (seed-once pattern)
5. Load MCP server config from `mcp.yaml`
6. Discover and load tool files (`tools/` + `TOOL_DIRS` + `integrations/*/tools/`)
7. Import `app/tools/local/` to trigger `@register` decorators
8. Index all tool schemas for retrieval (RAG)
9. Fetch + index MCP tool schemas (warm cache)
10. Validate pinned tools
11. Sync file-sourced skills/knowledge/prompts from `skills/*.md`, `knowledge/*.md`, `prompts/*.md`
12. Seed + load carapaces from `carapaces/*.yaml` + `integrations/*/carapaces/*.yaml`
13. Seed + load workflows from `workflows/*.yaml` + `integrations/*/workflows/*.yaml`
14. Load harness configs from `harnesses.yaml`
15. Register integration routers (discover + mount at `/integrations/{id}`)
16. Start file watcher + index configured filesystem directories
17. Warm up STT provider (if enabled)
18. Start integration background processes (Slack bot, MQTT listener, etc.)
19. Start `task_worker` background loop (polls every 5s)
20. Start `heartbeat_worker` background loop (polls every 30s)

### Configuration Layers
- **`.env`** → `app/config.py` (Pydantic Settings) — all runtime config
- **`bots/*.yaml`** → `app/agent/bots.py` (BotConfig) — per-bot behavior (gitignored; users create their own)
- **`skills/*.md`** — Markdown knowledge files (gitignored; users create their own)
- **`workflows/*.yaml`** — Multi-step automations (gitignored; users create their own)
- **`carapaces/*.yaml`** — Composable expertise bundles (checked in; see Carapaces section)
- **`mcp.yaml`** — MCP server URLs and auth (supports `${ENV_VAR}` substitution)
- **`harnesses.yaml`** — External CLI tool configs (claude, cursor, etc.)
- **`INTEGRATION_DIRS`** — colon-separated paths to external integration directories

### Tool System
Three tool types, all passed to the LLM in OpenAI function format:
- **Local tools** (`app/tools/local/`, `tools/`): Python functions decorated with `@register(openai_schema)`. Auto-discovered at startup.
- **MCP tools** (`mcp.yaml`): Remote HTTP endpoints implementing the MCP protocol. Proxied via `app/tools/mcp.py`.
- **Client tools** (`app/tools/client_tools.py`): Actions the client app handles (shell_exec, TTS toggle, etc.), declared to the LLM but executed client-side via a pending request/poll mechanism.

**Tool RAG** (`app/agent/tools.py`): On each request, user query is embedded and cosine-similarity matched against indexed tool schemas. Only top-K relevant tools above threshold are passed to the LLM. `pinned_tools` in bot YAML always bypass filtering. Bot opt-out: `tool_retrieval: false`.

**Adding a new local tool**: Create a `.py` file in `tools/` (or any `TOOL_DIRS` path). Use `@register({...openai schema...})` from `app/tools.registry`. The tool is auto-discovered on next server restart.

### Context Assembly Pipeline

`assemble_context()` in `context_assembly.py` is the central hub. It runs in this order:

1. **Current time injection** (timezone-aware)
2. **Context pruning** (trim stale tool results from old turns)
3. **Channel-level overrides** (tool/skill override/disabled lists, model overrides)
4. **Workspace DB skills merge** (if bot has `shared_workspace_id`)
5. **Carapace resolution** (merge skills + tools + system prompt fragments from carapaces)
6. **Memory scheme setup** ("workspace-files": inject MEMORY.md, daily logs, reference index)
7. **Channel workspace files** (if `channel_workspace_enabled`: inject active .md files + schema)
8. **@mention tag resolution** (`@skill:name`, `@tool:name`, `@bot:name`, `@knowledge:name`)
9. **Skills injection** (pinned: full content; rag: semantic match; on-demand: index + get_skill tool)
10. **API docs injection** (if `api_permissions` set)
11. **Delegate bot index** (list available bots for delegation)
12. **Conversation history** (sections index + `read_conversation_history` tool in file mode)
13. **Workspace filesystem RAG** (semantic retrieval from indexed workspace files)
14. **Tool retrieval** (tool RAG: cosine similarity matching)
15. **Channel prompt + system preamble** (per-channel customization, heartbeat metadata)
16. **User message** (text or native audio)

### Carapaces System

Composable bundles of skills, tools, and behavioral instructions that give bots instant expertise in specific domains.

- **Model**: `app/db/models.py` (Carapace table)
- **Core logic**: `app/agent/carapaces.py` (registry, resolution, YAML seeding)
- **API**: `app/routers/api_v1_admin/carapaces.py` (admin CRUD + export + resolve)
- **Bot-facing API**: `app/routers/api_v1_carapaces.py`
- **Tool**: `app/tools/local/carapaces.py` (`manage_carapace` — list/get/create/update)
- **UI**: `ui/app/(app)/admin/carapaces/` (list + detail editor)
- **Examples**: `carapaces/*.yaml` (orchestrator, qa, code-review, bug-fix)

**Key concepts:**
- **Composition via `includes`**: Carapaces can reference other carapaces; resolution is depth-first with cycle detection (max 5 levels)
- **Source types**: `manual` (API/UI), `file` (YAML, read-only), `integration`, `tool`
- **Channel overrides**: `carapaces_extra` (add) and `carapaces_disabled` (remove) on Channel
- **Bot config**: `carapaces: [qa, code-review]` in bot YAML

### Channel Workspace System

Per-channel file stores with schema-guided organization.

- **Storage**: `~/.agent-workspaces/{bot_id_or_shared}/channels/{channel_id}/`
- **Active files** (`.md` at root): Auto-injected into context every request
- **Archive files** (`archive/`): Searchable via tool, not auto-injected
- **Data files** (`data/`): Listed but not injected; referenced via search tool
- **Schema templates**: 7 pre-seeded templates (Software Dev, Research, Creative, General, PM Hub, QA, Structured Task Hub) stored as `PromptTemplate` rows
- **Schema resolution**: channel override (`workspace_schema_content`) > template (`workspace_schema_template_id`) > none
- **Indexing**: Background re-index on every message (content-hash makes it cheap); `filesystem_chunks` table
- **Tools**: `search_channel_workspace`, `search_channel_archive`, `list_workspace_channels`
- **UI**: `ChannelWorkspaceTab.tsx` (file browser), `WorkspaceSchemaEditor.tsx` (schema picker/editor)

### Heartbeat System

Periodic autonomous check-ins for channels. Fires scheduled prompts to gather status, trigger actions, or maintain monitoring.

- **Worker**: `app/services/heartbeat.py` — polls every 30s for due heartbeats
- **Model**: `channel_heartbeats` (one-to-one with Channel) + `heartbeat_runs` (execution history)
- **Config**: Per-channel via admin API (not in bot YAML)
- **Quiet hours**: Global (`HEARTBEAT_QUIET_HOURS`) or per-heartbeat (`quiet_start`/`quiet_end`/`timezone`)
- **Repetition detection**: Detects 3+ similar outputs; skips LLM call if repetitive + idle
- **Dispatch modes**: `"always"` (classic) or `"optional"` (LLM gets `post_heartbeat_to_channel` tool)
- **Tools**: `get_last_heartbeat`, `post_heartbeat_to_channel` (injected only in optional mode)
- **API**: `GET/PUT /channels/{id}/heartbeat`, `POST /channels/{id}/heartbeat/toggle`, `POST /channels/{id}/heartbeat/fire`

### Task/Scheduling System

Manages scheduled recurring tasks and one-off deferred agent executions.

- **Worker**: `app/agent/tasks.py` — polls every 5s, max 20 tasks per poll
- **Model**: `tasks` table — status: pending/running/complete/failed/active/cancelled
- **Schedule templates**: status=`active` + `recurrence` set (e.g., `+1h`, `+1d`) → spawns concrete tasks
- **Task types**: agent, scheduled, delegation, harness, exec, callback, api, webhook
- **Dispatch**: `dispatch_type` + `dispatch_config` routed via dispatcher registry
- **execution_config** (JSONB): Model overrides, system preamble, injected skills/tools/carapaces
- **callback_config** (JSONB): Orchestration — trigger_rag_loop, notify_parent, harness params
- **Tool**: `schedule_task` (local tool for bots — supports cross-bot, relative time, recurrence)
- **Prompt resolution**: workspace file path (fresh at exec time) > template > inline prompt
- **Rate limit handling**: Exponential backoff (65s, 130s, 260s), max 3 retries
- **API**: Admin CRUD at `/api/v1/admin/tasks`, polling at `/api/v1/tasks/{id}`

### Workflow System

Reusable multi-step automations with conditions, approval gates, and cross-bot coordination. Defined in YAML, triggered via API, bot tool, or heartbeat.

- **Executor**: `app/services/workflow_executor.py` — state machine for advancing runs (condition eval, prompt render, param/secret validation, step advancement, approval gates)
- **Registry**: `app/services/workflows.py` — in-memory registry (carapace pattern); loads from DB, syncs YAML from `workflows/` and `integrations/*/workflows/`
- **Hooks**: `app/services/workflow_hooks.py` — listens for task completions to advance workflow runs
- **API**: `app/routers/api_v1_admin/workflows.py` — admin CRUD for workflows + runs (trigger, approve, skip, retry, cancel)
- **Tool**: `app/tools/local/workflows.py` (`manage_workflow` — list/get/trigger/create/get_run/list_runs)
- **UI**: `ui/app/(app)/admin/workflows/` — list page, detail editor (definition + runs tabs), step editor, run viewer with timeline
- **DB**: `workflows` + `workflow_runs` tables; `Task.correlation_id` links tasks to runs
- **Execution model**: Workflows create Tasks (task_type="workflow"), task worker executes them, `after_task_complete` hook advances the workflow
- **Triggers**: API call, bot tool (`manage_workflow` action=trigger), heartbeat (`workflow_id` on `channel_heartbeats`)
- **Session modes**: `shared` (steps share channel context) or `isolated` (each step gets fresh context)
- **Tests**: `tests/unit/test_workflows.py`, `tests/unit/test_workflow_tool.py`, `tests/unit/test_workflow_recovery.py`, `tests/integration/test_workflows.py`

### Integration System

Pluggable integration architecture for connecting to external services.

- **Discovery**: `integrations/__init__.py` — scans in-repo, packages, and `INTEGRATION_DIRS`
- **Three layers per integration**:
  - **Router** (`router.py`): FastAPI endpoints (webhooks, config)
  - **Dispatcher** (`dispatcher.py`): Result delivery (Slack messages, GitHub comments)
  - **Hooks** (`hooks.py`): Lifecycle (emoji reactions, display names) + metadata
- **Shipped integrations**: slack, github, discord, gmail, frigate, mission_control, arr, claude_code, ingestion, bluebubbles, example
- **Channel binding**: `channel_integrations` table — client_id format `{type}:{identifier}`
- **Background processes**: Each integration can declare auto-start processes (`process.py`)
- **Settings**: `IntegrationSetting` table (DB cache > env var fallback)
- **Tools**: Auto-discovered from `integrations/*/tools/*.py`
- **Skills**: Auto-synced from `integrations/*/skills/*.md`
- **Carapaces**: Auto-seeded from `integrations/*/carapaces/*.yaml`
- **Workflows**: Auto-synced from `integrations/*/workflows/*.yaml`
- **Sidebar sections**: Declared via `sidebar_section` in `setup.py` SETUP dict
- **Dashboard modules**: Declared via `dashboard_modules` in `setup.py` SETUP dict
- **Activation + template compatibility**: `activation` block in SETUP declares carapace injection and `compatible_templates` tags; templates declare `compatible_integrations` frontmatter. See `docs/integrations/activation-and-templates.md`

#### setup.py SETUP Manifest Fields
```python
SETUP = {
    "env_vars": [...],                      # Environment variable declarations
    "webhook": {"path": str, "description": str} | None,
    "python_dependencies": [{"package": str, "import_name": str}] | None,
    "binding": {...} | None,                # Channel binding config (client_id format, etc.)
    "dashboard_modules": [                  # Custom MC dashboard sub-pages
        {"id": str, "label": str, "icon": str, "description": str},
    ],
    "sidebar_section": {                    # Adds a navigation section to the main sidebar
        "id": str,                          # Unique section ID (used for hide/show toggle)
        "title": str,                       # Section header (e.g. "MISSION CONTROL")
        "icon": str,                        # Lucide icon name for collapsed rail
        "items": [                          # Nav items within the section
            {"label": str, "href": str, "icon": str},
        ],
        "readiness_endpoint": str | None,   # Optional: API endpoint to check readiness
        "readiness_field": str | None,      # Optional: field name in readiness response
    },
}
```

### Delegation + Harness System

- **Delegation**: Bot-to-bot communication via `DelegationService`
  - Immediate (`run_immediate`): Synchronous child agent run
  - Deferred (`run_deferred`): Creates Task, executed by task_worker
  - Security: `delegate_bots` allowlist (bypassed by @-tags), max depth 3
- **Harnesses**: External CLI tools (claude, cursor) via `HarnessService`
  - Config: `harnesses.yaml`
  - Execution modes: host, bot sandbox, docker sandbox, shared workspace

### Memory/Knowledge Status
- **DB memory (`memories` table) is DEPRECATED** — not in use
- **DB knowledge (`bot_knowledge` table) is DEPRECATED** — not in use
- **Active memory system**: `memory_scheme: "workspace-files"` (MEMORY.md + daily logs + reference files)
- **Active history system**: `history_mode: "file"` (sections + transcript files + `read_conversation_history` tool)

### Key Files

**Agent core:**
- `app/agent/loop.py` — Core agent loop (iteration skeleton, stream orchestration)
- `app/agent/llm.py` — LLM call infrastructure (retry/backoff, fallback model, summarization)
- `app/agent/context_assembly.py` — Context injection pipeline (the big orchestrator)
- `app/agent/tool_dispatch.py` — Tool call routing + execution
- `app/agent/bots.py` — BotConfig dataclass and YAML loader
- `app/agent/tasks.py` — Task worker, scheduling, execution
- `app/agent/tools.py` — Tool embedding/retrieval (RAG)
- `app/agent/carapaces.py` — Carapace registry, resolution, YAML seeding
- `app/agent/channel_overrides.py` — Channel-level tool/skill/carapace override resolution
- `app/agent/tags.py` — @mention tag parsing and resolution
- `app/agent/dispatchers.py` — Dispatcher registry (none, webhook, internal, + integrations)
- `app/agent/hooks.py` — Integration lifecycle hooks

**Services:**
- `app/services/workflow_executor.py` — Workflow state machine (step advancement, conditions, approvals)
- `app/services/workflows.py` — Workflow registry (load, sync, lookup)
- `app/services/workflow_hooks.py` — Task-completion hooks for workflow advancement
- `app/services/heartbeat.py` — Heartbeat worker with quiet hours + repetition detection
- `app/services/delegation.py` — DelegationService
- `app/services/channels.py` — Channel service (get_or_create, binding, resolution)
- `app/services/compaction.py` — Context compaction with memory-phase
- `app/services/file_sync.py` — Skill/knowledge/prompt/carapace/workflow file sync
- `app/services/task_board.py` — Markdown kanban parser/serializer
- `app/services/reranking.py` — LLM-based RAG reranking

**Tools + infra:**
- `app/tools/registry.py` — Local tool registration
- `app/tools/loader.py` — importlib-based tool file discovery
- `app/tools/mcp.py` — MCP client (60s cache)
- `app/config.py` — All runtime settings (Pydantic Settings)
- `app/db/models.py` — All SQLAlchemy ORM models

### UI Architecture
- **Framework**: Expo 55 + React Native 0.83 + NativeWind (Tailwind) + TanStack Query + Zustand
- **Location**: `ui/` directory — the canonical UI (old Jinja2/HTMX admin is deprecated)
- **Routing**: Expo Router (file-based) — `ui/app/(app)/` for authenticated pages
- **API hooks**: `ui/src/api/hooks/` — 35+ TanStack Query hooks
- **State**: `ui/src/stores/` — auth, chat (SSE streaming), UI, theme, channelRead
- **Types**: `ui/src/types/api.ts` — 650+ lines of TypeScript types
- **Key pages**: channels (chat), admin/bots, admin/carapaces, admin/tasks, admin/workflows, admin/integrations, mission-control

### Docker Sandboxes

Long-lived containers with `docker exec`. Scope modes: `session` (default), `client`, `agent`, `shared`. Enable with `DOCKER_SANDBOX_ENABLED=true`.

- **Service**: `app/services/sandbox.py`
- **Tools**: `app/tools/local/sandbox.py`
- **Tables**: `sandbox_profiles`, `sandbox_bot_access`, `sandbox_instances`
- **Bot access**: `sandbox_bot_access` DB rows; bot YAML `docker_sandbox_profiles` restricts subset
- **Admin locking**: `locked_operations` JSONB on instances

### Database Notes
- `schema_` is the ORM attribute for the `schema` column in `tool_embeddings` (PostgreSQL reserved word)
- When using `sqlalchemy.dialects.postgresql.insert` (Core-level), use `**{"schema": value}` — Core doesn't translate ORM attribute names
- JSONB server_default: use `sa.text("'{}'::jsonb")` not bare string
- `EMBEDDING_DIMENSIONS` must match the vector dimensions in the DB
- Alembic migrations run automatically on startup; files in `migrations/versions/`

### Bot YAML Fields
```yaml
id: my_bot
name: "My Bot"
model: gemini/gemini-2.5-flash      # LiteLLM model alias
system_prompt: |
  ...
local_tools: [web_search, file]
mcp_servers: [homeassistant]
client_tools: [shell_exec]
skills:
  - id: channel-workspace
    mode: on_demand                  # pinned | rag | on_demand
pinned_tools: [exec_command]         # bypass tool retrieval
tool_retrieval: true                 # default true; false = always pass all tools
tool_similarity_threshold: 0.35      # override TOOL_RETRIEVAL_THRESHOLD
carapaces: [qa, code-review]         # composable expertise bundles
memory_scheme: workspace-files       # workspace-files (only active option)
history_mode: file                   # file (only active option)
workspace:
  enabled: true
  type: docker                       # docker | host
  indexing:
    enabled: true
delegate_bots: [helper_bot]
harness_access: [claude-code]
context_compaction: true
compaction_interval: 10
compaction_keep_turns: 4
persona: true
audio_input: transcribe              # or "native" (Gemini audio models)
docker_sandbox_profiles: [python-scratch]
```

### Deployment
- **Production runs in Docker** — do NOT connect to local postgres or assume localhost access
- Debug production issues by reading CODE, not by querying the DB directly
- To investigate prod issues: read the code paths, check Docker config, reason about what could go wrong
