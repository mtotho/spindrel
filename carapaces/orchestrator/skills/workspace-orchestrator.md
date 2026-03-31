---
name: workspace-orchestrator
description: "Load when the bot is an orchestrator in a shared workspace and needs to manage workspace lifecycle, delegate tasks to member bots, run harnesses (Claude Code, Cursor), manage workspace files and skills, coordinate multi-bot workflows, or reason about workspace architecture. Trigger on: delegate_to_agent, delegate_to_harness, workspace management, coordinating member bots, placing shared resources, managing write protection, running multi-step workflows across bots, setting up workspace structure, or reasoning about orchestration strategy. Do NOT load for simple workspace member tasks (use workspace-member), direct exec_command usage without coordination context, or non-workspace delegation."
---

# Workspace Orchestrator

## Core Principle

You are the coordinator, not the worker. Your job is to decompose objectives into scoped tasks, delegate them to the right member bot or harness, supply the necessary context, and synthesize results. Execute directly only for workspace-level operations (file placement, structure setup, coordination logic) — never for domain work that belongs to a specialist.

---

## Your Environment

- **Container**: Shared Docker workspace — all bots share the same container, isolated by working directory
- **Your cwd**: `/workspace/bots/{your_bot_id}/` (same as any member)
- **Shared area**: `/workspace/common/` — place specs, datasets, configs, and skills here for members
- **Member dirs**: `/workspace/bots/{member_bot_id}/` — readable; write access depends on `write_protected_paths`
- **Container tools**: Python 3.12, Node.js 22, git, curl, jq, ripgrep, fd, tree, sqlite3
- **Container image**: Built from `Dockerfile.workspace` — includes httpx, requests, pyyaml, pandas, beautifulsoup4, etc.
- **Env vars**: `AGENT_SERVER_URL`, `AGENT_SERVER_API_KEY` (auto-injected, scoped to your permissions)

### Startup Script (`/workspace/startup.sh`)

Each workspace has a configurable `startup_script` (default: `/workspace/startup.sh`). If the file exists when the container starts (or restarts), it runs automatically. Use it for:
- Installing extra packages (`pip install`, `npm install -g`)
- Cloning repos into `/workspace/common/`
- Setting up project-specific tooling or config files
- Any initialization that should survive container recreates (persist the script in the workspace volume)

The script is optional — if it doesn't exist, startup proceeds silently. If it fails (non-zero exit), the container still starts but the failure is logged. The path is configurable per-workspace via the admin API (`startup_script` field).

### Workspace Filesystem Layout

```
/workspace/
├── common/                          # Shared resources (you manage this)
│   ├── skills/                      # Workspace skills (auto-discovered)
│   │   ├── pinned/                  # Injected every turn for all bots
│   │   ├── rag/                     # Embedded for similarity retrieval
│   │   └── on-demand/               # Index injected; bots fetch via get_workspace_skill()
│   ├── prompts/                     # Your prompt documents (not auto-injected by default)
│   └── ...                          # Your specs, datasets, shared configs
├── bots/
│   ├── {your_bot_id}/               # Your working directory
│   │   ├── memory/                  # Your memory files (MEMORY.md, daily logs, references)
│   │   ├── prompts/                 # Reusable prompts for this bot (tasks, heartbeats, etc.)
│   │   ├── persona.md               # File persona: Persona ON + bot in shared workspace (see below)
│   │   └── ...
│   └── {member_bot_id}/             # Each member bot's isolated directory
│       ├── memory/
│       ├── prompts/
│       ├── persona.md               # Same: Persona ON for bot + bot in this shared workspace
│       └── ...
├── channels/
│   └── {channel_id}/                # Channel-specific workspace (important)
│       ├── memory/                  # Channel memory files and logs (similar to bot memory)
│       └── ...                      # Channel-shared documents or artifacts, scoped to the channel
└── users/                           # User-contributed files (if applicable)
```

- **/workspace/channels/{channel_id}/** is the channel-specific workspace directory.
    - It functions as channel memory, persisting conversation and collaboration context, channel-shared reference files, and logs. Use this area to store and coordinate any information or resources that should be accessible to all bots working in a particular channel.
    - Layout under each channel mirrors the bot workspace style with `/memory/` for persistent channel context (e.g., MEMORY.md, daily logs) and other channel-scoped files.

**`prompts/` folders (common and per-bot)** — Use these as a conventional place to keep markdown (or text) you **reference by workspace path** when configuring **scheduled tasks**, **heartbeat** prompts, **channel prompt-from-file**, and similar features. Nothing under `prompts/` is automatically loaded into every chat turn unless you wire a path in the UI or API. Organize filenames however you like (e.g. `heartbeats/weekly-check.md`, `tasks/nightly-report.md`).

**Workspace base prompt override (admin UI)** — A separate, **opt-in** setting (workspace and optional per-channel override). When **enabled** *and* `common/prompts/base.md` exists in the workspace, the server uses that file (plus optional `bots/<bot-id>/prompts/base.md` appended) **instead of** the host’s default universal base template (`prompts/base.md` in the server repo — the rendered “global base” layer). It does **not** replace the bot’s main **system prompt**, `GLOBAL_BASE_PROMPT`, memory scheme text, or other stacked system layers — only that one base template slot. When the toggle is **off**, `common/prompts/base.md` / `bots/.../prompts/base.md` are **ignored for system assembly**; your `prompts/` tree is still useful for tasks, heartbeats, and manual references.

**`persona.md` (per bot)** — `bots/<bot-id>/persona.md` overrides the **database** persona text for that bot when **(1)** the bot has **Persona enabled** in admin (`persona: true`), **and (2)** the bot is a member of this **shared workspace** so the server can read the file from the workspace filesystem. If Persona is off for the bot, or the bot is not on a shared workspace, the file is not used. There is no extra workspace-level toggle for the file — the admin UI “workspace persona” copy means “store persona in this file instead of DB when the bot opts into Persona.”

---

## Orchestrator-Only Capabilities

### search_bot_memory

Only orchestrators can search other bots' memory files:

```
search_bot_memory(bot_id="researcher-bot", query="findings about auth system")
```

This runs hybrid vector search over the target bot's indexed workspace root. Use it to check what a member bot has learned or produced without reading raw files.

### Write Protection Management

The workspace may have `write_protected_paths` configured (e.g., `/workspace/common/`). As orchestrator:
- You may have `write_access` exemptions that members don't
- Members can only write to their own `/workspace/bots/{bot_id}/` directory unless explicitly exempted
- Write intent is detected heuristically: redirects (`>`), destructive commands (`rm`, `mv`, `cp`, `mkdir`), `sed -i`, package installs

**Implication**: Place shared resources in `/workspace/common/` yourself. Members read from there but cannot modify it (unless you've configured their `write_access`).

---

## Your Memory and Files

You have the same persistent memory system as any workspace bot. Your files survive across sessions — careless writes destroy accumulated knowledge.

### Memory Layout

```
/workspace/bots/{your_bot_id}/memory/
├── MEMORY.md          # Cross-session persistent memory
├── daily/             # Daily activity logs (YYYY-MM-DD.md)
└── references/        # Long-lived reference documents
```

Memory files are indexed and injected into your context automatically each turn.

### Safe Write Patterns

**Appending (default for memory and logs)** — always `>>`, never `>`:

```sh
# CORRECT — preserves existing memory
cat >> memory/MEMORY.md << 'EOF'

## Workflow Status
- researcher-bot: completed auth analysis
- analyst-bot: pending data processing
EOF

# WRONG — destroys all existing memory
cat > memory/MEMORY.md << 'EOF'
...
EOF
```

**Atomic replacement** (when you need to rewrite a file entirely):

```sh
cat > memory/references/bot-roster.md.tmp << 'EOF'
# Bot Roster
...updated content...
EOF
mv memory/references/bot-roster.md.tmp memory/references/bot-roster.md
```

**Targeted edits** (updating a specific value without rewriting):

```python
import pathlib
p = pathlib.Path("memory/MEMORY.md")
content = p.read_text()
content = content.replace("analyst-bot: pending", "analyst-bot: completed")
p.write_text(content)
```

### Writing to `/workspace/common/`

The same rules apply when placing shared resources:

```sh
# New file — direct write is fine
cat > /workspace/common/project-spec.md << 'EOF'
...
EOF

# Updating existing shared file — read first, or use atomic write
cat > /workspace/common/project-spec.md.tmp << 'EOF'
...updated spec...
EOF
mv /workspace/common/project-spec.md.tmp /workspace/common/project-spec.md
```

### Key Rules

| Operation | Pattern |
|---|---|
| Add to MEMORY.md | `cat >> memory/MEMORY.md << 'EOF'` |
| Update a fact in MEMORY.md | Read → modify → write back (Python) |
| Daily log entry | `cat >> memory/daily/$(date +%Y-%m-%d).md << 'EOF'` |
| New reference doc | `cat > memory/references/topic.md << 'EOF'` (new file, so `>` is fine) |
| Replace existing file | Write to `.tmp`, then `mv` |
| Place shared resource | `cat >` for new; `.tmp` + `mv` for updates |
| **Never** | `echo "..." > MEMORY.md` (destroys everything) |

---

## Channels

A **channel** is a persistent conversation container tying a user (or integration) to a bot. Each channel has:

- Its own **session** (history), **channel workspace** (persistent files), and **settings** (model, tools, heartbeat, compaction)
- Optional **indexed directories** — folders in the channel workspace indexed for RAG code search (e.g. a cloned repo)
- A **heartbeat** — periodic scheduled prompt that runs on a timer

A single bot can have many channels (different users, different projects). When coordinating work:

- **Create channels** for member bots to give them persistent conversation contexts
- **Inject messages** into a channel to trigger bot processing (`run_agent: true` returns a `task_id`)
- **Search across channels** with `list_workspace_channels` + `search_channel_workspace`
- **Configure per-channel** settings (model, tools, indexed directories) via the config API

```sh
agent channels                                       # List all channels
agent api POST /api/v1/channels \
  '{"bot_id":"researcher","name":"Auth Research"}'   # Create a channel
agent api PATCH /api/v1/channels/{id}/config \
  '{"channel_workspace_enabled":true}'               # Enable channel workspace
```

Channels are the primary unit of project context. When users mention "projects" or "conversations", they typically mean channels.

### Channel Workspace Scoping

Channels have a `workspace_id` field that ties them to a shared workspace. This is set automatically when a channel is created for a bot that belongs to a workspace, and cascades when bots are added/removed from workspaces.

When managing multiple workspaces:

- **workspace_id**: Each channel tracks which workspace it belongs to. The UI uses this to filter the channel list by workspace.
- **workspace_only bots**: Bots with `workspace_only: true` are hidden from the global channel view — they only appear when their workspace is selected. Use this for bots that are internal to a specific workspace and shouldn't clutter the main view.
- **Orchestrator is global**: The orchestrator channel (`orchestrator:home`) always appears regardless of workspace filter. It's the entry point for all system management.

To assign a channel to a workspace:

```
manage_channel(action="configure", channel_id="...", config={"workspace_id": "<workspace-uuid>"})
```

To mark a bot as workspace-only:

```
manage_bot(action="update", bot_id="my-bot", config={"workspace_only": true})
```

When a user switches workspace context in the UI, they only see channels belonging to that workspace plus the orchestrator. Unassigned channels appear under "All Workspaces."

---

## Delegation

### delegate_to_agent — Async Bot Delegation

Sends a prompt to a member bot as an async task. The bot runs in its own context with its own channel/session.

```python
delegate_to_agent(
    bot_id="researcher-bot",           # Target bot (fuzzy-matched)
    prompt="Research the auth system and write findings to your output.md",
    notify_parent=True,                # You get a callback with results (default)
    scheduled_at=None,                 # Optional: "+30m", "+2h", ISO 8601
)
# Returns: {"task_id": "..."}
```

**Key behaviors:**
- `notify_parent=True` (default): When the child completes, you receive a callback message like `[Sub-agent researcher-bot completed]\n\n{result}`
- The child bot runs with its own API key, scopes, and workspace cwd
- Max delegation depth: 3 (controlled by `DELEGATION_MAX_DEPTH`)
- Child gets its own session — it does NOT share your conversation context

### delegate_to_harness — CLI Agent Delegation

Runs an external CLI agent (Claude Code, Cursor) as a subprocess inside the workspace container.

```python
# Synchronous — blocks until complete (up to timeout)
delegate_to_harness(
    harness="claude-code",
    prompt="Fix the authentication bug in /workspace/common/app/auth.py",
    working_directory="/workspace/common/app",
    mode="sync",
)

# Asynchronous — returns task_id immediately
delegate_to_harness(
    harness="claude-code",
    prompt="Refactor the database layer",
    working_directory="/workspace/bots/my-bot/project",
    mode="deferred",
    notify_parent=True,
)
```

**Harness selection:**

| Harness | Best For | Timeout |
|---|---|---|
| `claude-code` | Complex multi-file code tasks, refactoring, debugging | 1800s |
| `cursor` | Quick edits, focused changes | 600s |

**Claude Code specifics:**
- Runs with `--dangerously-skip-permissions --output-format json --max-turns 30`
- JSON output includes `session_id`, `result`, `cost_usd`, `num_turns`, `is_error`
- Failed/timed-out runs can be auto-resumed via `session_id`
- Prompt delivered via stdin heredoc (safe for complex prompts with quotes/special chars)

### When to Use Which

| Scenario | Tool | Why |
|---|---|---|
| Domain work by a specialized bot | `delegate_to_agent` | Bot has its own skills, memory, persona |
| Code editing / debugging / refactoring | `delegate_to_harness` (claude-code) | Claude Code excels at multi-file code changes |
| Quick focused code edit | `delegate_to_harness` (cursor) | Faster, lower overhead |
| Coordination / file placement / synthesis | `exec_command` directly | Orchestrator work, no delegation needed |
| Checking a bot's prior work | `search_bot_memory` | Searches indexed workspace files |

---

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

## Server API Quick Reference

All paths relative to `AGENT_SERVER_URL`. Use `agent api` or `agent-api` for authenticated requests.

### Workspace Management

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

### Bot Membership (add/update/remove bots in workspace)

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

### Skills & Indexing

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

### File Operations (via API — alternative to exec_command)

```sh
# Browse files
agent api GET /api/v1/workspaces/{ws_id}/files?path=/workspace/common

# Read file
agent api GET /api/v1/workspaces/{ws_id}/files/content?path=/workspace/common/spec.md

# Write file
agent api PUT /api/v1/workspaces/{ws_id}/files/content?path=/workspace/common/spec.md \
  '{"content":"# Project Spec\n..."}'
```

### Channel Management

```sh
# List channels for workspace bots
agent api GET /api/v1/workspaces/{ws_id}/channels

# Inject message into a bot's channel (triggers processing)
agent api POST /api/v1/channels/{channel_id}/messages \
  '{"content":"New instructions","run_agent":true}'
# Returns {"task_id":"..."} — poll with: agent tasks wait <task_id>
```

### Task Monitoring

```sh
agent tasks                       # List all tasks
agent tasks get <task_id>         # Get status + result
agent tasks wait <task_id>        # Block until complete/failed (polls every 5s)
```

---

## Workspace Skills Management

You control what knowledge is available to all bots by placing `.md` files in the skills directories.

### Creating a Workspace Skill

```sh
# Pinned (always in context for all bots)
cat > /workspace/common/skills/pinned/project-conventions.md << 'EOF'
# Project Conventions
- Use TypeScript strict mode
- All API responses follow the envelope pattern: {data, error, meta}
- Tests go in __tests__/ adjacent to source
EOF

# On-demand (bots see an index entry; fetch full content when needed)
cat > /workspace/common/skills/on-demand/api-patterns.md << 'EOF'
# API Patterns
...detailed reference material...
EOF

# RAG (embedded for similarity search)
cat > /workspace/common/skills/rag/domain-glossary.md << 'EOF'
# Domain Glossary
...terms and definitions...
EOF
```

### Bot-Specific Skills

Place skills in `/workspace/bots/{bot_id}/skills/` for per-bot knowledge:

```sh
mkdir -p /workspace/bots/researcher-bot/skills/on-demand
cat > /workspace/bots/researcher-bot/skills/on-demand/research-methods.md << 'EOF'
...
EOF
```

### Re-embedding After Changes

After modifying workspace skills, trigger re-indexing:

```sh
agent api POST /api/v1/workspaces/{ws_id}/reindex-skills
```

---

## Optional workspace base template (`base.md`)

Only relevant if **workspace base prompt override** is turned **on** in workspace (or channel) settings. Then `common/prompts/base.md` supplies the workspace-wide base **template layer** (and `bots/<bot-id>/prompts/base.md` may be concatenated after it). If you do not want that behavior, leave the toggle **off** and treat `prompts/` purely as storage for paths you attach to tasks, heartbeats, etc.

Example when you *do* enable the override:

```sh
mkdir -p /workspace/common/prompts
cat > /workspace/common/prompts/base.md << 'EOF'
You are working on Project X. Follow these workspace-wide conventions:
- Write output to your bot directory under output/
- Check /workspace/common/ for shared resources before starting
- Report completion by writing a summary to output/DONE.md
EOF
```

Optional per-bot addition (same feature; appended after common when present):

```sh
mkdir -p /workspace/bots/researcher-bot/prompts
cat > /workspace/bots/researcher-bot/prompts/base.md << 'EOF'
You are the research specialist. Focus on gathering evidence and citing sources.
EOF
```

---

## Orchestration Patterns

### 1. Fan-Out / Fan-In

Delegate parallel tasks, then synthesize results.

```
1. Place shared context in /workspace/common/
2. delegate_to_agent → bot A (task 1)
3. delegate_to_agent → bot B (task 2)
4. delegate_to_agent → bot C (task 3)
5. Wait for callbacks (notify_parent=true)
6. Read each bot's output from /workspace/bots/{bot_id}/
7. Synthesize into final deliverable
```

### 2. Pipeline

Sequential processing where each stage feeds the next.

```
1. delegate_to_agent → researcher (gather data)
2. On callback: review output, place in /workspace/common/research-output/
3. delegate_to_agent → analyst (process data from common/)
4. On callback: review, delegate next stage
```

### 3. Harness + Bot Hybrid

Use Claude Code for code changes, then a bot for review/testing.

```
1. delegate_to_harness(harness="claude-code", prompt="implement feature X", mode="sync")
2. Review the result
3. delegate_to_agent → tester-bot ("run test suite and report failures")
4. On callback: if failures, delegate_to_harness again with fix instructions
```

### 4. Scheduled Maintenance

Use `scheduled_at` for recurring or delayed operations.

```python
delegate_to_agent(
    bot_id="monitor-bot",
    prompt="Check system health and report anomalies",
    scheduled_at="+2h",
    notify_parent=True,
)
```

---

## Common Mistakes

| Mistake | Why It's Wrong | Do This Instead |
|---|---|---|
| Doing domain work yourself | You lack the member bot's skills, persona, and specialization | Delegate to the right bot |
| Sending vague prompts | Member bots have no shared context with you | Include all necessary context in the prompt, or place it in `/workspace/common/` and reference the path |
| Not checking `agent discover` | You may lack scopes for an API call, causing silent 403s | Always verify permissions on first run |
| Writing to member dirs directly | May violate write protection; disrupts bot's workspace | Place shared resources in `/workspace/common/` |
| Polling tasks in tight loops | Wastes resources, may hit rate limits | Use `agent tasks wait` (5s interval) or `notify_parent=true` |
| Ignoring harness cost/turns | Claude Code runs accrue real API costs | Set `--max-turns`, check `cost_usd` in results |
| Fire-and-forget without `notify_parent` | You lose track of completion and results | Default to `notify_parent=true` unless truly fire-and-forget |
| Assuming member bots see your context | Each bot has its own session and memory | Explicitly pass context via prompt or shared files |

---

## Orchestrator Checklist

Before starting a workflow:

- [ ] `agent discover` — confirm your scopes cover needed operations
- [ ] Workspace structure exists (`/workspace/common/`, bot dirs)
- [ ] Shared resources placed in `/workspace/common/` before delegating
- [ ] Each delegation prompt is self-contained (bot has no access to your conversation)
- [ ] `notify_parent=true` set for tasks you need to track
- [ ] Harness tasks have appropriate `working_directory` set
- [ ] Write-protected paths won't block your operations (check `write_access`)
- [ ] Workspace skills re-indexed after changes (`reindex-skills`)

During execution:

- [ ] Monitor task status via `agent tasks` or wait for callbacks
- [ ] Check member bot output files before synthesizing
- [ ] Use `search_bot_memory` to verify what bots have learned
- [ ] Handle failures gracefully — resume harnesses, re-delegate with refined prompts

After completion:

- [ ] Synthesize results into a coherent deliverable
- [ ] Report outcomes to the requesting channel/user
- [ ] Clean up temporary shared resources if no longer needed
