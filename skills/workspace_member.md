---
name: Workspace Member
description: Operating inside your container environment — filesystem layout, permissions, write protection, cross-bot coordination
triggers: workspace, container, /workspace/bots, write protection, shared filesystem
category: workspace
---

# Workspace Member

## Core Principle

Every bot has a container environment: a shared Docker workspace with your own working directory under `/workspace/bots/{your_bot_id}/`. Your memory, prompts, and work output live there. Other bots' directories are usually readable but not writable. Shared resources (specs, datasets, base prompts) live under `/workspace/common/`. This skill is the reference for navigating that environment effectively.

You may sometimes be coordinating with an orchestrator that puts specs in `/workspace/common/` and reads your output from your directory — but most of the time you're just a bot doing work, and the container is the place where it happens.

---

## Your Environment

- **Container**: Shared Docker workspace — all bots share the same container, isolated by working directory
- **Your cwd**: `/workspace/bots/{your_bot_id}/` (your default working directory)
- **Shared files**: `/workspace/common/` (orchestrator places specs, datasets, configs here)
- **Other bots**: `/workspace/bots/{other_bot_id}/` (readable, usually not writable)
- **Container tools**: Python 3.12, Node.js 22, git, curl, jq, ripgrep, fd, tree, sqlite3
- **Python packages**: httpx, requests, pyyaml, toml, jinja2, beautifulsoup4, lxml, pandas, markdown, python-dotenv
- **Server interaction**: use the `call_api` / `list_api_endpoints` tools — they run in-process with your scoped key, no shell hop required.

### Filesystem Layout

```
/workspace/
├── common/                          # Shared resources (read-only for members typically)
│   ├── prompts/
│   │   └── base.md                  # Workspace base prompt (applies to all bots)
│   └── ...                          # Specs, datasets, shared configs
├── bots/
│   ├── {your_bot_id}/               # YOUR working directory
│   │   ├── memory/                  # Your memory files
│   │   │   ├── MEMORY.md            # Persistent cross-session memory
│   │   │   ├── daily/               # Daily activity logs
│   │   │   └── references/          # Long-lived reference documents
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

Your scoped API key determines what server endpoints you can call. To see what's available, use the in-process tools:

- `list_api_endpoints()` — list every endpoint your key permits, with method/path/description.
- `list_api_endpoints(scope="channels")` — narrow by scope prefix (e.g. `channels`, `tasks`, `documents`).
- `call_api(method, path, body)` — invoke any allowed endpoint. Body is a JSON string.

These tools share the same scoped key as the rest of your tooling, so you don't need to handle auth headers or shell-escape JSON. Run `list_api_endpoints` once at the start of a new task to learn what's reachable.

---

## Channels

A **channel** is a persistent conversation container. You are always operating within one. Each channel has:

- Its own **session** (conversation history) and **channel workspace** (persistent files in `channels/{channel_id}/workspace/`)
- Per-channel **settings** (model overrides, tool overrides, compaction config, heartbeats)
- Optional **indexed directories** — folders in the channel workspace indexed for RAG code search

Other channels exist for your bot and for other bots. You can interact with them via the API tools:

```python
call_api("GET", "/api/v1/channels")                              # List channels
call_api("GET", "/api/v1/channels/{id}/config")                  # Get channel settings
call_api("POST", "/api/v1/channels/{id}/messages",
         body='{"content":"message","run_agent":true}')          # Inject + trigger processing
```

Use `list_channels` and `search_channel_workspace` to discover and search across channel workspaces. If the user references another project or channel, these tools help you find relevant content without needing to know the channel ID upfront.

---

## Workspace Search

If workspace indexing is enabled, use `search_workspace` to find relevant content across indexed workspace files:

```
search_workspace(query="authentication flow", top_k=5)
```

Returns chunks with file paths, symbols, and line numbers. Use `exec_command` with `cat <filepath>` to read full files from results.

---

## Memory System

Your memory lives on disk at `/workspace/bots/{your_bot_id}/memory/`:

- **`MEMORY.md`** — Persistent cross-session memory. Updated during compaction. Contains key learnings, decisions, and context that should persist.
- **`daily/`** — Daily activity logs with timestamped entries.
- **`references/`** — Long-lived reference documents for stable knowledge.

Memory files are indexed and searched automatically each turn. You don't need to manually read them — the system injects relevant memory into your context.

For file editing safety patterns and the `file` tool reference, see the **workspace_files** skill (auto-enrolled in your starter pack).

---

## Common Mistakes

| Mistake | Why It's Wrong | Do This Instead |
|---|---|---|
| Writing to `/workspace/common/` | Usually write-protected for members | Write to your own dir; let orchestrator know the path |
| Writing to another bot's directory | May be protected; disrupts their workspace | Write to your own dir |
| Not checking `list_api_endpoints` first | You may lack scopes, causing silent 403s | Call `list_api_endpoints()` once before issuing requests in a new context |
| Working outside your bot directory | Other bots may overwrite your files | Default to `/workspace/bots/{your_bot_id}/` |
| Not reading `/workspace/common/` | Orchestrator placed context there for you | Always check shared resources before starting work |

---

## Member Checklist

Before starting work:

- [ ] `list_api_endpoints()` — confirm your scopes and available endpoints
- [ ] Check `/workspace/common/` for shared resources, specs, datasets
- [ ] Working in your directory: `/workspace/bots/{your_bot_id}/`

During work:

- [ ] Write output where the orchestrator expects it (your dir, or as instructed)
- [ ] Use `search_workspace` for finding relevant workspace content
- [ ] Reach the server via `call_api` rather than shelling out — your scoped key is already wired in
- [ ] For long-running work, prefer `schedule_task` and poll with `get_task_result` (5s+ intervals)

After completion:

- [ ] Results written to expected location
- [ ] Report completion if a channel injection was requested
- [ ] `integration_id` consistent across document ingestions for later filtering
