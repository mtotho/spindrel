---
name: workspace-member
description: "Load when the bot is a member of a shared workspace and needs to execute commands, call the server API, write scripts, manage files, use workspace skills, work with memory, or interact with the agent server from inside the workspace container. Trigger when: using exec_command or delegate_to_exec, writing scripts that use agent CLI or agent-api, ingesting documents for RAG, injecting messages into channels, polling task status, searching workspace files, reading shared resources, managing todos, or reasoning about what tools and APIs are available inside the container. Do NOT load for orchestrator-level workspace management (delegation, multi-bot coordination, workspace lifecycle)."
---

# Workspace Member

## Core Principle

You are a specialist working inside a shared workspace. Your orchestrator assigns you tasks, provides context in shared directories, and synthesizes your output. Focus on your domain work within your own directory — read shared resources, produce clear output, and report results where expected.

---

## Your Environment

- **Container**: Shared Docker workspace — all bots share the same container, isolated by working directory
- **Your cwd**: `/workspace/bots/{your_bot_id}/` (your default working directory)
- **Shared files**: `/workspace/common/` (orchestrator places specs, datasets, configs here)
- **Other bots**: `/workspace/bots/{other_bot_id}/` (readable, usually not writable)
- **Container tools**: Python 3.12, Node.js 22, git, curl, jq, ripgrep, fd, tree, sqlite3
- **Python packages**: httpx, requests, pyyaml, toml, jinja2, beautifulsoup4, lxml, pandas, markdown, python-dotenv
- **Env vars**: `AGENT_SERVER_URL`, `AGENT_SERVER_API_KEY` (auto-injected, scoped to your permissions)

### Filesystem Layout

```
/workspace/
├── common/                          # Shared resources (read-only for members typically)
│   ├── skills/                      # Workspace skills (auto-discovered)
│   │   ├── pinned/                  # Always in your context
│   │   ├── rag/                     # Retrieved by similarity
│   │   └── on-demand/               # Index in context; fetch with get_workspace_skill()
│   ├── prompts/
│   │   └── base.md                  # Workspace base prompt (applies to all bots)
│   └── ...                          # Specs, datasets, shared configs
├── bots/
│   ├── {your_bot_id}/               # YOUR working directory
│   │   ├── memory/                  # Your memory files
│   │   │   ├── MEMORY.md            # Persistent cross-session memory
│   │   │   ├── daily/               # Daily activity logs
│   │   │   └── references/          # Long-lived reference documents
│   │   ├── skills/                  # Your bot-specific skills
│   │   │   ├── pinned/
│   │   │   ├── rag/
│   │   │   └── on-demand/
│   │   ├── prompts/
│   │   │   └── base.md              # Your bot-specific prompt layer
│   │   └── ...                      # Your work output
│   └── {other_bot_id}/              # Other bots' directories (readable)
└── users/                           # User-contributed files
```

---

## Write Protection

The workspace may have protected paths (e.g., `/workspace/common/`). If you try to write to a protected path without exemption, the command will be rejected.

**Rules:**
- You can always write inside `/workspace/bots/{your_bot_id}/`
- `/workspace/common/` is typically read-only for members
- Other bots' directories may be protected
- Your `write_access` exemptions (if any) are configured by the orchestrator/admin

**If a write is blocked**: Don't force it. Write to your own directory and let the orchestrator know where to find the output.

---

## Discovering Your Permissions

Your scoped API key determines what endpoints you can call. **Always check on first run:**

```sh
agent discover              # Quick list — shows endpoints and your scopes
agent docs                  # Full API reference filtered to what your key allows
```

This is the authoritative source for what you can do. The reference below covers common operations, but `agent docs` reflects your actual permissions and includes request/response schemas.

### api_reference Virtual Skill

If API docs injection is enabled on your bot config, you have an `api_reference` entry in your skill index. Call `get_skill("api_reference")` to get full API documentation filtered to your scopes — no need to memorize endpoints.

---

## Agent CLI

The `agent` CLI at `/usr/local/bin/agent` is the primary way to interact with the server API.

```sh
agent discover                          # Show available endpoints for your key
agent docs                              # Full markdown API reference
agent chat "message"                    # Send a chat message
agent channels                          # List channels
agent channels get <id>                 # Channel details
agent channels create --bot-id X        # Create channel
agent channels messages <id>            # List messages
agent channels messages <id> --inject "msg"  # Inject message
agent channels reset <id>              # Reset session
agent tasks                             # List tasks
agent tasks get <id>                    # Task details
agent tasks wait <id>                   # Block until complete/failed
agent api METHOD /path [json_body]      # Raw API call
```

### agent-api Helper (legacy)

The `agent-api` shell script wraps `curl` with auth headers. Prefer `agent` CLI for new work.

```sh
agent-api GET /api/v1/channels
agent-api POST /api/v1/documents '{"title":"notes","content":"hello"}'
```

### Python Scripts

```python
import os, httpx

BASE = os.environ["AGENT_SERVER_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_SERVER_API_KEY']}"}

r = httpx.get(f"{BASE}/api/v1/channels", headers=HEADERS)
```

---

## Channels

A **channel** is a persistent conversation container. You are always operating within one. Each channel has:

- Its own **session** (conversation history) and **channel workspace** (persistent files in `channels/{channel_id}/workspace/`)
- Per-channel **settings** (model overrides, tool overrides, compaction config, heartbeats)
- Optional **indexed directories** — folders in the channel workspace indexed for RAG code search

Other channels exist for your bot and for other bots. You can interact with them via the API:

```sh
agent channels                                    # List channels
agent api GET /api/v1/channels/{id}/config        # Get channel settings
agent api POST /api/v1/channels/{id}/messages \
  '{"content":"message","run_agent":true}'         # Inject message + trigger processing
```

Use `list_workspace_channels` and `search_channel_workspace` to discover and search across channel workspaces. If the user references another project or channel, these tools help you find relevant content without needing to know the channel ID upfront.

---

## Workspace Skills

Skills placed in workspace skill directories are automatically available to you.

### Pinned Skills
Always injected into your context. No action needed — you already have them.

### RAG Skills
Retrieved by similarity to your current conversation. Automatic — no action needed.

### On-Demand Skills
An index of available skills is injected. Fetch full content when needed:

```
get_workspace_skill(skill_path="common/skills/on-demand/api-patterns.md")
```

Valid paths must end in `.md`, contain `/skills/`, and be under `common/skills/` or `bots/{your_bot_id}/skills/`.

### Your Own Skills
You can create bot-specific skills in your directory:

```sh
mkdir -p /workspace/bots/{your_bot_id}/skills/on-demand
cat > /workspace/bots/{your_bot_id}/skills/on-demand/my-reference.md << 'EOF'
# My Reference
...domain knowledge...
EOF
```

---

## Workspace Search

If workspace indexing is enabled, use `search_workspace` to find relevant content across indexed workspace files:

```
search_workspace(query="authentication flow", top_k=5)
```

Returns chunks with file paths, symbols, and line numbers. Use `exec_command` with `cat <filepath>` to read full files from results.

To force a full re-index of your workspace files:

```
reindex_workspace()
```

---

## Memory System

Your memory lives on disk at `/workspace/bots/{your_bot_id}/memory/`:

- **`MEMORY.md`** — Persistent cross-session memory. Updated during compaction. Contains key learnings, decisions, and context that should persist.
- **`daily/`** — Daily activity logs with timestamped entries.
- **`references/`** — Long-lived reference documents for stable knowledge.

Memory files are indexed and searched automatically each turn. You don't need to manually read them — the system injects relevant memory into your context.

**Writing memory**: Memory is typically written during context compaction (automatic). If you need to persist something immediately, use the safe file editing patterns below.

---

## File Editing — Safe Patterns

You work inside a persistent filesystem shared with other bots. Files you write survive across sessions. Careless writes corrupt memory, clobber output, or leave partial files that break downstream consumers. Every write should be non-destructive by default.

### The Cardinal Rule

**Never overwrite a file you haven't read first.** If you need to modify a file, read it, apply the change, write the result. Never blindly `echo >` or `cat >` a file that may already have content.

### Appending (the safe default)

Most memory and log writes are appends. Always use `>>`, never `>`:

```sh
# CORRECT — appends to existing content
echo "## New Finding" >> memory/MEMORY.md

# WRONG — destroys everything already in the file
echo "## New Finding" > memory/MEMORY.md
```

For multi-line appends, use a heredoc with `>>`:

```sh
cat >> memory/MEMORY.md << 'EOF'

## Auth System Notes
- Uses JWT with 15-minute expiry
- Refresh tokens stored in httpOnly cookies
EOF
```

### Atomic Writes (for full-file replacements)

When you need to replace an entire file (not append), write to a temp file first, then move. This prevents partial writes if the command is interrupted:

```sh
# Write to temp, then atomic move
cat > output/report.md.tmp << 'EOF'
# Analysis Report
...full content...
EOF
mv output/report.md.tmp output/report.md
```

**Why**: A direct `cat > file` that gets interrupted leaves a truncated file. `mv` is atomic on the same filesystem — the file is either fully replaced or untouched.

### Editing Specific Sections

To modify a specific part of an existing file without rewriting the whole thing, use `sed` or a Python script:

```sh
# Replace a specific line
sed -i 's/status: pending/status: complete/' output/status.yaml

# Delete a section by marker
sed -i '/^## Old Section$/,/^## /{ /^## [^O]/!d; }' memory/MEMORY.md

# Insert after a marker line
sed -i '/^## References$/a - New reference: https://example.com' memory/MEMORY.md
```

For complex edits, a short Python script is safer than fragile sed:

```python
import pathlib
p = pathlib.Path("memory/MEMORY.md")
content = p.read_text()
content = content.replace("old value", "new value")
p.write_text(content)
```

### Memory File Best Practices

| Operation | Pattern | Why |
|---|---|---|
| Add a new finding | `cat >> memory/MEMORY.md << 'EOF'` | Preserves existing memory |
| Update a known fact | Read → modify → write back (Python or sed) | Don't lose surrounding content |
| Create a daily log | `cat >> memory/daily/$(date +%Y-%m-%d).md << 'EOF'` | Appends to today's log |
| Create a reference doc | `cat > memory/references/topic.md << 'EOF'` | Full replacement is fine for new files |
| Remove stale memory | Read file → remove section → write back | Never `> /dev/null` or truncate |

### Output Files

When producing work output:

```sh
# Create output directory if needed
mkdir -p output

# For reports/deliverables — atomic write
cat > output/results.md.tmp << 'EOF'
...
EOF
mv output/results.md.tmp output/results.md

# For incremental logs — append
echo "[$(date -Iseconds)] Step 3 complete: 42 items processed" >> output/progress.log
```

### Avoiding Common File Corruption

| Mistake | What Happens | Safe Alternative |
|---|---|---|
| `echo "new" > MEMORY.md` | All existing memory destroyed | `echo "new" >> MEMORY.md` |
| `cat > file` interrupted | File left truncated/empty | Write to `.tmp`, then `mv` |
| `sed -i` on wrong file | Irreversible in-place edit | `cp file file.bak && sed -i ...` for risky edits |
| Concurrent writes from script | Lines interleaved/corrupted | Use `flock` or write to separate files |
| Heredoc without quoting (`<< EOF`) | Shell expands `$variables` in content | Use `<< 'EOF'` (single-quoted) to write literal content |
| `echo` with unescaped special chars | Mangled output, broken JSON | Use `printf '%s\n'` or `cat <<` for complex content |

---

## Common Operations

### Report Results to a Channel

```sh
# Inject a message (no agent processing)
agent api POST /api/v1/channels/{channel_id}/messages \
  '{"content":"Analysis complete: 42 issues found","role":"user","source":"workspace"}'

# Inject + trigger agent processing
agent api POST /api/v1/channels/{channel_id}/messages \
  '{"content":"Review these results","run_agent":true}'
# Returns {"task_id":"..."} — wait for completion:
agent tasks wait <task_id>
```

### Ingest Documents for RAG

```sh
agent api POST /api/v1/documents \
  '{"title":"Research Notes","content":"...","integration_id":"my-bot","metadata":{"source":"analysis"}}'

# Search later
agent api GET '/api/v1/documents/search?q=deployment+timeline&limit=5'
```

### Batch-Ingest Files

```sh
for f in docs/*.md; do
  TITLE=$(basename "$f" .md)
  CONTENT=$(cat "$f" | jq -Rs .)
  agent api POST /api/v1/documents \
    "{\"title\":\"$TITLE\",\"content\":$CONTENT,\"integration_id\":\"workspace-docs\"}"
done
```

### Manage Todos

```sh
# List your pending todos
agent api GET '/api/v1/todos?status=pending'

# Create a todo
agent api POST /api/v1/todos \
  '{"content":"Review auth module","priority":"high"}'

# Complete a todo
agent api PATCH /api/v1/todos/{id} '{"status":"completed"}'
```

### Read Shared Resources

```sh
# Check what the orchestrator provided
ls /workspace/common/
cat /workspace/common/project-spec.md
ls /workspace/common/datasets/
```

### Trigger Another Bot and Wait

```python
import os, httpx

BASE = os.environ["AGENT_SERVER_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_SERVER_API_KEY']}"}

r = httpx.post(f"{BASE}/api/v1/channels/{channel_id}/messages",
    headers=HEADERS, json={"content": "Summarize logs", "run_agent": True})
task_id = r.json()["task_id"]

# Or from CLI: agent tasks wait <task_id>
```

### Download Attachments

```sh
# List attachments from a channel
agent api GET '/api/v1/attachments?channel_id={id}&limit=10'

# Download a file
agent api GET /api/v1/attachments/{id}/file > output.bin
```

---

## Common Mistakes

| Mistake | Why It's Wrong | Do This Instead |
|---|---|---|
| Writing to `/workspace/common/` | Usually write-protected for members | Write to your own dir; let orchestrator know the path |
| Writing to another bot's directory | May be protected; disrupts their workspace | Write to your own dir |
| Not checking `agent discover` first | You may lack scopes, causing silent 403s | Run `agent discover` before making API calls |
| Hardcoding API paths from memory | Your scopes may not cover them | Use `agent docs` for your actual available endpoints |
| Tight polling loops (< 5s) | Wastes resources, may hit rate limits | Use `agent tasks wait` or poll at 5s+ intervals |
| Forgetting `jq -Rs` for file content | Raw newlines break JSON bodies | Always escape content: `cat file | jq -Rs .` |
| Working outside your bot directory | Other bots may overwrite your files | Default to `/workspace/bots/{your_bot_id}/` |
| Not reading `/workspace/common/` | Orchestrator placed context there for you | Always check shared resources before starting work |
| Ignoring workspace skills index | On-demand skills have useful reference material | Call `get_workspace_skill()` when you see relevant entries |

---

## Member Checklist

Before starting work:

- [ ] `agent discover` — confirm your scopes and available endpoints
- [ ] Check `/workspace/common/` for shared resources, specs, datasets
- [ ] Working in your directory: `/workspace/bots/{your_bot_id}/`
- [ ] Environment set: `env | grep AGENT` confirms `AGENT_SERVER_URL` and `AGENT_SERVER_API_KEY`

During work:

- [ ] Write output where the orchestrator expects it (your dir, or as instructed)
- [ ] Use `search_workspace` for finding relevant workspace content
- [ ] Use `get_workspace_skill()` for on-demand skill content
- [ ] JSON bodies properly escaped (use `jq` for complex content)
- [ ] Polling async tasks at 5s+ intervals, or use `agent tasks wait`

After completion:

- [ ] Results written to expected location
- [ ] Report completion if a channel injection was requested
- [ ] `integration_id` consistent across document ingestions for later filtering
