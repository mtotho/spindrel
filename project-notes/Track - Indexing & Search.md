---
tags: [agent-server, track, indexing, search]
status: active
updated: 2026-04-10
---
# Track — Indexing & Search

## Status
Phases 1-2 done. Phase 3 (audit + E2E test) pending.

## Why this exists
Multiple bots (QA, DEV) need the same `/workspace/repos/` indexed without duplicate config. The mechanism (`SharedWorkspace.indexing_config`) existed but UI didn't expose it. Tool descriptions didn't explain scope/method/when-to-use, so agents guessed. Admins couldn't see how config maps to agent behavior.

## Architecture (current)
**Three-tier indexing config**:
```
Global defaults (app.config) → Workspace defaults (SharedWorkspace.indexing_config JSONB) → Bot overrides (bot.workspace.indexing)
```
Resolution: `resolve_indexing()` in `app/services/workspace_indexing.py` cascades bot > workspace > global. As of Phase 2.3, segments cascade through workspace as well, with `segments_source` in the return dict.

**Content reaches the agent two ways**:
1. **Automatic injection** during context assembly (workspace files RAG, channel workspace files, channel index segments, memory files, capability discovery, tool RAG, conversation sections)
2. **On-demand tools**:
   - **Semantic** (embeddings): `search_workspace`, `search_memory`, `search_bot_memory`, `search_channel_workspace`, `search_channel_archive`, `search_history`, `get_memory_file`, `get_skill`
   - **Literal** (regex / fnmatch, no embeddings): `file(operation="grep", …)` and `file(operation="glob", …)` in `app/tools/local/file_ops.py`. Use when the bot knows the exact string or filename pattern — function names, error messages, config keys, `**/*.py`. Replaces the need to shell out to `exec_command "grep -r …"` (which defeats file_ops' shell-quoting guarantees).

**DB tables**:
- `filesystem_chunks` — workspace files, memory files, channel workspace files (`bot_id` or `"channel:{id}"` sentinel)
- `documents` — skill content chunks
- `tool_embeddings` — tool schemas
- `capability_embeddings` — carapace metadata
- ~~`BotKnowledge`~~ — DEPRECATED, scheduled for removal

## Done
- [x] **Phase 1.1** — `search_workspace` already uses hybrid via `retrieve_filesystem_context()` (`HYBRID_SEARCH_ENABLED=True` default). Discovered already-implemented during planning.
- [x] **Phase 1.2** — Workspace-level indexing defaults UI (`WorkspaceDefaultsEditor` component). Editable patterns / similarity_threshold / top_k / embedding_model / cooldown_seconds. Wired to `PATCH /api/v1/workspaces/{id}` with `indexing_config` body.
- [x] **Phase 1.3** — All 6 search tools' descriptions rewritten with disambiguation (what's searched, search method, when to use vs alternatives, scope).
- [x] **Phase 2.1** — Contextual help in indexing UI (collapsible "How agents use this" panel).
- [x] **Phase 2.2** — Search tools reference table in workspace help panel.
- [x] **Phase 2.3** — Workspace-level segment inheritance UX. `resolve_indexing()` cascades segments (bot > workspace > empty), with `segments_source` in return dict. UI shows "inherited" badges.

## Pending
- [ ] **Phase 3.1** — Audit all tool enrollment paths. Verify every search tool is correctly enrolled/hidden based on config. Verify `search_knowledge` is fully hidden when `memory_scheme='workspace-files'`. Verify `search_workspace` is pinned when indexing is enabled. Document enrollment conditions in this file.
- [ ] **Phase 3.2** — E2E test for shared workspace indexing. Two bots in shared workspace, workspace-level config, both retrieve same content. Bot-level override takes precedence over workspace default.

## Recommended config for shared-repos use case
```
/workspace/
  repos/
    vault/          ← Obsidian notes, roadmaps, tracks (index for RAG)
    spindrel/       ← Agent server codebase (tool access, NOT RAG)
    spindrel-website/ ← Marketing site (tool access, NOT RAG)
  bots/
    qa-bot/memory/  ← QA memory (auto-indexed, search_memory)
    dev-bot/memory/ ← DEV memory (auto-indexed, search_memory)
```

Workspace `indexing_config`: `{ "patterns": ["**/*.md", "**/*.yaml"] }` — index docs only.
Workspace segments: `[{ "path_prefix": "repos/vault/", "patterns": ["**/*.md"] }]`.
Code repos: NOT indexed. Agents use file tools (read, grep, glob via exec_command) for code navigation.

Rationale: RAG works well for prose (vault notes), poorly for code (loses dependency context, burns budget on fragments).

## Key files
- `app/services/workspace_indexing.py` — `resolve_indexing()` cascade
- `app/services/channel_workspace_indexing.py` — channel-scoped with sentinel `bot_id`
- `app/services/memory_indexing.py` — memory file indexing (memory/ prefix)
- `app/services/memory_search.py` — hybrid BM25+Vector RRF implementation
- `app/agent/fs_indexer.py` — `retrieve_filesystem_context()` (workspace RAG at query time)
- `app/agent/context_assembly.py` — orchestrates injection paths
- `app/agent/tools.py` — tool indexing + retrieval
- `app/agent/capability_rag.py` — capability discovery
- `app/tools/local/{workspace,memory_files,channel_workspace,search_history}.py`
- `app/routers/api_v1_workspaces.py` — workspace API (`indexing_config` CRUD)
- `ui/app/(app)/admin/workspaces/[workspaceId]/IndexingTab.tsx` + `IndexingOverview.tsx` + `WorkspaceDefaultsEditor.tsx`
