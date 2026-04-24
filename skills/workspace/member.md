---
name: Workspace Member
description: Operating inside your container environment — filesystem layout, permissions, write protection, API access
triggers: workspace, container, /workspace/bots, write protection, shared filesystem, call_api, list_api_endpoints
category: workspace
---

# Workspace Member

## Core Principle

Every bot has a container environment: a shared Docker workspace with your own working directory under `/workspace/bots/{your_bot_id}/`. Your memory, prompts, and work output live there. Other bots' directories are usually readable but not writable. Shared resources (specs, datasets, base prompts) live under `/workspace/common/`.

---

## Filesystem Layout

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

## API Access

Your scoped API key determines what server endpoints you can call. To see what's available, use the in-process tools:

- `list_api_endpoints()` — list every endpoint your key permits, with method/path/description.
- `list_api_endpoints(scope="channels")` — narrow by scope prefix (e.g. `channels`, `tasks`, `documents`).
- `call_api(method, path, body)` — invoke any allowed endpoint. Body is a JSON string.

These tools share the same scoped key as the rest of your tooling, so you don't need to handle auth headers or shell-escape JSON. Run `list_api_endpoints` once at the start of a new task to learn what's reachable.

---

## Container Tools

Pre-installed in the workspace container:
- **Runtime**: Python 3.12, Node.js 22
- **CLI**: git, curl, jq, ripgrep, fd, tree, sqlite3
- **Python packages**: httpx, requests, pyyaml, toml, jinja2, beautifulsoup4, lxml, pandas, markdown, python-dotenv

For file operations, prefer the `file` tool over shell commands — see the **workspace/files** skill. For channel workspace management, see the **workspace/channel_workspaces** skill.

---

## Cross-Bot Coordination

- Other bots' directories under `/workspace/bots/` are readable, giving you visibility into their output
- `/workspace/common/` is the drop zone for shared resources — check it before starting work
- Use `call_api` rather than shelling out for server interactions — your scoped key is already wired in

---

## Common Mistakes

| Mistake | Why It's Wrong | Do This Instead |
|---|---|---|
| Writing to `/workspace/common/` | Usually write-protected for members | Write to your own dir; let orchestrator know the path |
| Writing to another bot's directory | May be protected; disrupts their workspace | Write to your own dir |
| Not checking `list_api_endpoints` first | You may lack scopes, causing silent 403s | Call `list_api_endpoints()` once before issuing requests in a new context |
| Shelling out for file ops | Quoting hazards with special characters | Use the `file` tool instead |
| Not reading `/workspace/common/` | Orchestrator placed context there for you | Always check shared resources before starting work |

---

## Member Checklist

Before starting work:

- [ ] `list_api_endpoints()` — confirm your scopes and available endpoints
- [ ] Check `/workspace/common/` for shared resources, specs, datasets
- [ ] Working in your directory: `/workspace/bots/{your_bot_id}/`

During work:

- [ ] Write output where the orchestrator expects it (your dir, or as instructed)
- [ ] Reach the server via `call_api` rather than shelling out
- [ ] For long-running work, prefer `schedule_task` and poll with `get_task_result` (5s+ intervals)
