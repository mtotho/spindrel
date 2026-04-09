---
name: workspace-management
description: >
  Channels, workspace skills, memory write patterns, base template overrides, and
  operational checklists. Load when managing channels, writing workspace skills,
  updating memory files, configuring workspace prompts, or reviewing operational
  procedures and common mistakes.
---

# Workspace Management

## Channels

A **channel** is a persistent conversation container tying a user (or integration) to a bot. Each channel has:

- Its own **session** (history), **channel workspace** (persistent files), and **settings** (model, tools, heartbeat, compaction)
- Optional **indexed directories** — folders in the channel workspace indexed for RAG code search (e.g. a cloned repo)
- A **heartbeat** — periodic scheduled prompt that runs on a timer

A single bot can have many channels (different users, different projects). When coordinating work:

- **Create channels** for member bots to give them persistent conversation contexts
- **Inject messages** into a channel to trigger bot processing (`run_agent: true` returns a `task_id`)
- **Search across channels** with `list_channels` + `search_channel_workspace`
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

---

## Memory Write Patterns

Your files survive across sessions — careless writes destroy accumulated knowledge.

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

### Quick Reference

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

## Workspace Base Template (`base.md`)

Only relevant if **workspace base prompt override** is turned **on** in workspace (or channel) settings. Then `common/prompts/base.md` supplies the workspace-wide base **template layer** (and `bots/<bot-id>/prompts/base.md` may be concatenated after it). It does **not** replace the bot's main system prompt, `GLOBAL_BASE_PROMPT`, memory scheme text, or other system layers — only that one base template slot. When the toggle is **off**, the `prompts/` tree is still useful for tasks, heartbeats, and manual references.

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

**Startup script** (`/workspace/startup.sh`) — configurable per-workspace, runs automatically on container start. Use for installing packages, cloning repos, setting up tooling. Optional; failures are logged but don't prevent container startup.

**`persona.md`** (`bots/<bot-id>/persona.md`) — overrides DB persona text when the bot has `persona: true` and is a member of this shared workspace. No extra toggle needed.

---

## Secret Values

Secrets are encrypted env vars stored in the vault, injected into workspace containers, and automatically redacted from all bot output.

### When to Use Secrets

Use `manage_secret` for any value that would be a problem if it appeared in conversation logs: API keys, tokens, passwords, credentials. If a tool or integration needs a sensitive value, create it as a secret rather than passing it inline.

### CRUD

```
manage_secret(action="list")                                          # Names + descriptions only, never plaintext
manage_secret(action="create", name="GITHUB_TOKEN", value="ghp_...") # UPPER_SNAKE_CASE name required
manage_secret(action="create", name="SLACK_WEBHOOK", value="https://hooks.slack.com/...", description="Alerts channel webhook")
manage_secret(action="delete", name="OLD_API_KEY")                   # Delete by name
```

To replace a secret value, delete then re-create (avoids partial update confusion).

### Secrets vs Workspace Env Vars

| | Secrets (`manage_secret`) | Workspace env vars |
|---|---|---|
| Encrypted at rest | Yes (Fernet) | No |
| Redacted from output | Yes (automatic) | No |
| Injected into containers | Yes (as env vars) | Yes |
| Visible in logs | Never | Yes |

**Rule of thumb:** If it's sensitive, use a secret. If it's just config (a URL, a mode flag), use a regular env var.

---

## Orchestrator Checklist

Before starting a workflow:

- [ ] `agent discover` — confirm your scopes cover needed operations
- [ ] Workspace structure exists (`/workspace/common/`, bot dirs)
- [ ] Shared resources placed in `/workspace/common/` before delegating
- [ ] Each delegation prompt is self-contained (bot has no access to your conversation)
- [ ] `notify_parent=true` set for tasks you need to track
- [ ] Claude Code tasks have appropriate `working_directory` set
- [ ] Write-protected paths won't block your operations (check `write_access`)
- [ ] Workspace skills re-indexed after changes (`reindex-skills`)

During execution:

- [ ] Monitor task status via `agent tasks` or wait for callbacks
- [ ] Check member bot output files before synthesizing
- [ ] Use `search_bot_memory` to verify what bots have learned
- [ ] Handle failures gracefully — retry Claude Code with refined prompts, re-delegate as needed

After completion:

- [ ] Synthesize results into a coherent deliverable
- [ ] Report outcomes to the requesting channel/user
- [ ] Clean up temporary shared resources if no longer needed
