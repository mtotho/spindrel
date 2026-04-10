---
name: Workspace Member
description: Operating inside a shared workspace container — environment, permissions, write protection, cross-bot coordination
triggers: workspace member, shared workspace, container, workspace bot, /workspace/bots, write protection
category: workspace
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

Your scoped API key determines what endpoints you can call. **Always check on first run:**

```sh
agent discover              # Quick list — shows endpoints and your scopes
agent docs                  # Full API reference filtered to what your key allows
```

For the full agent CLI reference (commands, examples, common operations), see the **agent_cli** skill — it's auto-enrolled when you join a shared workspace.

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
| Not checking `agent discover` first | You may lack scopes, causing silent 403s | Run `agent discover` before making API calls |
| Working outside your bot directory | Other bots may overwrite your files | Default to `/workspace/bots/{your_bot_id}/` |
| Not reading `/workspace/common/` | Orchestrator placed context there for you | Always check shared resources before starting work |

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
- [ ] JSON bodies properly escaped (use `jq` for complex content)
- [ ] Polling async tasks at 5s+ intervals, or use `agent tasks wait`

After completion:

- [ ] Results written to expected location
- [ ] Report completion if a channel injection was requested
- [ ] `integration_id` consistent across document ingestions for later filtering
