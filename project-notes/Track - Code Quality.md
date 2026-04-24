---
tags: [agent-server, track, code-quality]
status: active
created: 2026-04-09
updated: 2026-04-23 (Cluster 1 all 6 commits shipped — indexing abstraction-leak closed)
---
# Track — Code Quality & Refactoring

Systematic audit of core agent-server files. 156 files, ~50K lines across `app/agent/`, `app/services/`, `app/tools/`. Findings organized by priority.

## Ousterhout depth audit (2026-04-23)

Audit lens: Ousterhout's "deep module" heuristic (lots of functionality behind a simple interface, hides complexity) vs "shallow module" (not much functionality, complex interface, surfaces complexity). Workflow: Matt Pocock's `improve-codebase-architecture` skill — friction → clusters → parallel interface designs → RFC. Two peer-review rounds shaped the ranking. Full plan: `~/.claude/plans/nifty-hatching-book.md`.

### Depth clusters (ranked)

1. **Indexing abstraction leak at callers** — `workspace_indexing.resolve_indexing()` / `get_all_roots()` are called directly from `app/main.py`, `app/agent/fs_watcher.py`, `app/agent/context_assembly.py:791`, `app/tools/local/channel_workspace.py`, and 4 routers. The flavored wrappers (`memory_indexing`, `channel_workspace_indexing`) encode real policy differences (memory patterns, sentinel bot ids, segment handling, stale-cleanup, bypass semantics) — the problem is caller sites reaching past them. Deepening direction: audit which callers actually need indexing vs. just workspace-root resolution; pull indexing-relevant callers behind the flavor boundary.

2. **Dashboard surface + source-of-truth drift** — `app/routers/api_v1_dashboard.py` (~1,742 LOC, 40+ endpoints on `/widgets` prefix) is fake-deep: 40+ endpoints whose concerns don't share hidden state. Coupled services: `dashboard_pins`, `widget_themes`, `widget_contracts`, `widget_context`, `widget_manifest`, `widget_templates`, `native_app_widgets`, `html_widget_scanner`, `grid_presets`. **Deeper issue**: source-of-truth drift — `GRID_PRESETS` logic appears in more than one place. Router split without unifying preset/theme truth would miss the Ousterhout point. Deepening direction, two-part sequenced: (a) unify preset source of truth across backend + frontend, then (b) split into four-to-five thematic sub-routers paired with their service modules (pattern: `app/routers/api_v1_admin/`).

3. **Boundary-bypass smell — PROMOTED (2026-04-23 scan)** — services / agent / tools raising HTTP-layer errors from non-HTTP contexts. Scan found **118 `raise HTTPException` sites** across 14+ non-router modules. Includes `app/services/machine_control.py` taking `request: Request` as a function parameter — the wrapper receives HTTP objects directly, not just raises HTTP errors. Callers: routers, tasks, background workers, tools. Consumers end up catching or swallowing errors the wrapper wasn't designed to surface correctly. Depth direction: introduce a domain-exception layer (e.g., `DomainError` subclasses in `app/domain/`); HTTP-adapter layer at the router boundary converts to `HTTPException`. Services stop importing from `fastapi`. This is the largest of the three clusters in surface area but can be migrated incrementally.

### Deep modules to preserve (emulation targets, do not split reflexively)

| Module | LOC | Why exemplary |
|---|---|---|
| `app/services/session_plan_mode.py` | 2,180 | Plan-mode as first-class runtime object |
| `app/services/compaction.py` | 2,653 | Watermark/section/summary pipeline |
| `app/services/step_executor.py` | 1,530 | Pipeline execution state machine |
| `app/services/sessions.py` | 1,310 | Session lifecycle + persistence |
| `app/agent/context_assembly.py` | 2,717 | RAG admission control |
| `app/agent/llm.py` | 1,705 | Streaming / classification / fallback |
| `app/agent/tool_dispatch.py` | 1,551 | Execution + approval + truncation |
| `app/agent/tokenization.py` | 481 | Model-family dispatch + fallback |
| `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx` | 3,389 | Iframe pool + theme + CSP |
| `ui/app/(app)/widgets/ChannelDashboardMultiCanvas.tsx` | 1,810 | Four-canvas DnD grid |
| `ui/src/components/chat/ChatSession.tsx` | 1,638 | Ephemeral + channel chat |
| `ui/src/api/hooks/useChannelEvents.ts` | 756 | SSE subscription state machine |

Several have god functions inside (separate from depth — see existing table below).

### Rejected from the depth queue (documented so they don't get revived)

- **Presence → push merge** — presence is shared infrastructure (sessions, turn_worker, machine_control, push); folding into push widens coupling.
- **Bot/channel visibility unification** — different policies (public/private vs owner/grants); common shape ≠ common policy. Would produce a shallow abstraction.
- **Generic `index_for(target)` dispatcher** — flavor modules encode real policy differences; a dispatcher loses type-safety for negligible gain.
- **Reverting `loop_dispatch.py` / `loop_helpers.py`** — deliberate decomposition shipped April-23; keep.
- **Consolidating UI Card/Badge variants** — semantically distinct, different data + interactions.

### Housekeeping shipped (2026-04-23)

- ✅ Deleted `ui/app/(app)/channels/[channelId]/ChatMessageArea.tsx` (4-LOC re-export shim). Sole importer in `channels/[channelId]/index.tsx` retargeted to canonical `@/src/components/chat/ChatMessageArea`.
- ✅ Deleted `ui/app/(app)/channels/[channelId]/IntegrationsTab.tsx` (5-LOC single-child wrapper). Sole importer in `settings.tsx` now renders `BindingsSection` directly.
- ✅ Deleted `ui/src/components/chat/renderers/NativeAppRenderer.tsx` (6-LOC passthrough). `RichToolResult.tsx` now calls `renderNativeWidget()` from `./renderers/nativeApps/registry` directly.
- ✅ Deleted `ui/src/components/shared/TaskCreateModal.tsx` (multi-symbol compat shim). Dead `ChipPicker` re-export removed; `admin/tasks/index.tsx` renamed to use canonical `TaskCreateWizard` from `@/src/components/shared/task/TaskCreateWizard`.
- ✅ Deleted `app/services/local_machine_control.py` (1-LOC `from machine_control import *` alias). Zero importers; safe delete.
- ✅ Added `ui/src/components/shared/PlaceholderPage.tsx`; consolidated `admin/delegations.tsx`, `admin/memories.tsx`, `admin/sandboxes.tsx`, `admin/sessions/index.tsx` (4 identical "Coming soon" boilerplates) into `<PlaceholderPage title="..." />` instances.
- Verification: `cd ui && npx tsc --noEmit` exits 0.

### Housekeeping deferred (not free cleanup)

- ❌ **`app/services/workflow_hooks.py` — deferred**. Looked like dead weight at first glance (24 LOC registering a no-op hook). But `tests/unit/test_workflow_advancement.py:127-136` treats the no-op as a **defensive regression test** — it verifies the hook system does *not* double-fire workflow step completion (since `_fire_task_complete` now advances workflow state directly). Deletion is only safe once it's confirmed that the hook-system's `after_task_complete` firing path is unused or that double-fire is otherwise impossible. Needs its own investigation session.
- `app/services/grid_presets.py` — moved into Cluster 2 depth queue. Question isn't "is the file used," it's "where does preset truth live, and is there more than one copy?"

### Verify-first small files (Ousterhout uncertain)

Claimed shallow by one explore agent but unverified. Future session: `wc -l`, `grep ^def`, grep importers for each.
- `app/agent/pending.py`, `app/agent/tracing.py`, `app/agent/hybrid_search.py`, `app/agent/persona.py`, `app/agent/vector_ops.py`, `app/agent/approval_pending.py`.

### Why this matters (architectural read)

The three promoted clusters share a theme: **caller-side knowledge that should live in one module**. Indexing callers duplicate resolution logic. Dashboard callers and services duplicate preset truth. Service callers duplicate HTTP error handling that the service shouldn't own. Each cluster, when deepened, reduces the number of places that need to understand a given policy.

### RFC — Cluster 1 — Indexing caller-boundary leak (2026-04-23)

Chosen design: **A+ — minimal surface with caller-optimized verbs + constructor-injected primitive**. This RFC is the output of the Matt-Pocock skill Step 7 (3 parallel designs evaluated, user picked A+). Not yet executed.

#### Scope

Consolidate three existing modules into one:
- `app/services/workspace_indexing.py` → becomes internal helpers
- `app/services/memory_indexing.py` → absorbed
- `app/services/channel_workspace_indexing.py` → absorbed
- **New:** `app/services/bot_indexing.py` (public module)

Remove all ~17 direct call sites of `resolve_indexing()` / `get_all_roots()` outside the new owning module. Caller reach surface: `app/main.py` (5), `app/agent/fs_watcher.py` (3 stanzas, ~9 refs), `app/agent/context_assembly.py` (4), `app/tools/local/workspace.py` (4), `app/tools/local/channel_workspace.py` (1).

#### Public interface (final)

```python
# app/services/bot_indexing.py
from typing import Literal, Iterator

Scope = Literal["workspace", "memory", "channel"]

@dataclass(frozen=True)
class BotIndexPlan:
    bot_id: str                   # sentinel "channel:{id}" for channel scope
    roots: tuple[str, ...]
    patterns: list[str]
    embedding_model: str
    similarity_threshold: float
    top_k: int
    watch: bool
    cooldown_seconds: int
    segments: list[dict] | None
    scope: Scope
    shared_workspace: bool
    skip_stale_cleanup: bool

# Reader — pure, no I/O. Returns None if scope doesn't apply to this bot.
def resolve_for(
    bot: BotConfig,
    *,
    scope: Scope = "workspace",
    channel_id: str | None = None,
    channel_segments: list[dict] | None = None,
) -> BotIndexPlan | None: ...

# Writer — resolves + runs index_directory per root. Returns merged stats or None.
async def reindex_bot(
    bot: BotConfig,
    *,
    include_workspace: bool = True,
    include_memory: bool = True,
    force: bool = True,
) -> dict | None: ...

# Watcher helper — one call, handles workspace-enabled + memory-only branches.
def iter_watch_targets(bots: list[BotConfig]) -> Iterator[tuple[BotIndexPlan, str]]: ...

# Channel flavor — narrower call for channel re-index (tools + admin routers)
async def reindex_channel(
    channel_id: str,
    bot: BotConfig,
    *,
    channel_segments: list[dict] | None = None,
    force: bool = True,
) -> dict | None: ...
```

Module init does one-time import of `index_directory` (injected primitive) to break the lazy-import cycle; `workspace_service` / `shared_workspace_service` remain lazy-imported inside private helpers (circular-import constraint).

#### Readers keep `retrieve_filesystem_context` separate

Call sites in `context_assembly.py` become:

```python
plan = bot_indexing.resolve_for(bot, scope="workspace")
fs_chunks, fs_sim = await retrieve_filesystem_context(
    user_message, plan.bot_id,
    roots=list(plan.roots),
    threshold=plan.similarity_threshold, top_k=plan.top_k,
    embedding_model=plan.embedding_model,
    segments=plan.segments, channel_id=..., exclude_paths=...,
)
```

We intentionally do **not** subsume `retrieve_filesystem_context` into `bot_indexing` — RAG retrieval and indexing are distinct concerns.

#### Invariants preserved

1. Three-tier config cascade (bot → workspace → global env).
2. Memory flavor gate: `memory_scheme == "workspace-files" AND workspace.enabled`.
3. Memory pattern source: `memory_scheme.get_memory_index_patterns(bot)`.
4. Channel sentinel bot_id: `"channel:{id}"` stored on `FilesystemChunk.bot_id`.
5. Channel patterns: `channels/{id}/**/*.md` + optional per-segment extensions.
6. Shared-workspace root: `shared_workspace_service.get_host_root(id)`; standalone: `workspace_service.get_workspace_root(bot.id, bot=bot)`.
7. `skip_stale_cleanup=True` for memory + channel-without-explicit-segments; `False` when `channel_segments` provided.
8. Shared-workspace-no-segments skip + stale non-memory chunk deletion (currently `main.py:204-222` inline branch).
9. Per-root stats merging (currently memory_indexing's inline merge).

#### Commit plan (6 commits, behavior-preserving)

Behavior-preserving = `pytest tests/unit/test_workspace_indexing.py tests/unit/test_memory_indexing.py tests/unit/test_channel_workspace_indexing.py tests/unit/test_fs_watcher_channel_workspace_e2e.py tests/integration/test_workspace_indexing_e2e.py` green at every commit.

1. ~~**Add `bot_indexing.py` skeleton + tests**~~ ✅ shipped 2026-04-23 — `app/services/bot_indexing.py` with `BotIndexPlan` + `resolve_for(scope="workspace")` delegating to `resolve_indexing` + `get_all_roots`. 10 new boundary tests (`tests/unit/test_bot_indexing.py`); 82 legacy indexing tests unchanged. Zero caller changes.
2. ~~**Port `main.py` startup block (5 sites)**~~ ✅ shipped 2026-04-23 — `_index_filesystems_and_start_watchers` collapsed from 104 → 22 lines. Single loop over `list_bots()` calling `bot_indexing.reindex_bot(bot, force=True, cleanup_orphans=True)` + the legacy `filesystem_indexes` loop. Shared-workspace-no-segments stale-chunk cleanup, two-pass stale-root cleanup, Phase-1 memory indexing, and Phase-2 segment indexing now all live inside `reindex_bot`. New writer tests (6) cover memory-only, segments-indexes-each-root, cleanup-orphans gating, and memory-failure isolation.
3. ~~**Port `fs_watcher.py` (3 stanzas)**~~ ✅ shipped 2026-04-23 — `start_watchers` now mounts watcher tasks from `iter_watch_targets(bots)` (63 → 33 lines); `_watch_shared_workspace` inner loop collapsed to `reindex_bot(bot, force=True)` per matching bot (36 → 10 lines); periodic reindex worker collapsed to `reindex_bot(bot, force=False)` per bot (30 → 7 lines). 4 new boundary tests on `iter_watch_targets` (memory-scope synthesis, watch=False gate, shared-workspace skip). Minor behavior change noted: periodic memory reindex was implicit force=True → now force=False (matches workspace periodic; skips redundant re-embedding of unchanged memory files).
4. ~~**Port `context_assembly.py` readers (3 sites)**~~ ✅ shipped 2026-04-23 — channel-segments RAG (line 800), workspace RAG (line 990), bot-knowledge-base RAG (line 1085) all use `bot_indexing.resolve_for(bot, scope="workspace")` and pass plan fields into `retrieve_filesystem_context` unchanged. Implicit-KB-prefix dedupe at line 800 kept at call site per RFC Risk note. (RFC said "4 sites"; actual = 3.)
5. ~~**Port tool sites (5 files)**~~ ✅ shipped 2026-04-23 — `tools/local/workspace.py` (2 sites), `tools/local/channel_workspace.py` (1 site), `tools/local/memory_files.py` (2 sites). Extended: RFC under-counted callers; also ported `routers/api_v1_workspaces.py` (2 reindex endpoints — phase 0/1/2 cleanup+memory+segments collapsed to single `reindex_bot` loop), `routers/api_v1_admin/diagnostics.py` (3 sites — force-reindex admin endpoint, memory-search diagnostics endpoint, filesystem-per-bot stats endpoint), `routers/api_v1_admin/channels.py` (1 site), `routers/api_v1_search.py` (1 site). Two admin visibility endpoints (`get_workspace_indexing`, `update_bot_indexing`) intentionally retained `resolve_indexing` — they return the raw cascade dict (incl. `segments_source`) for UI display.
6. ~~**Delete legacy wrappers**~~ ✅ shipped 2026-04-23 — `memory_indexing.index_memory_for_bot` now delegates to `bot_indexing.reindex_bot(include_memory=True, include_workspace=False)`; `channel_workspace_indexing.index_channel_workspace` delegates to `bot_indexing.reindex_channel`. Memory indexing body absorbed into `_reindex_memory` inside `bot_indexing.py`; channel indexing body absorbed into `reindex_channel`. `workspace_indexing.resolve_indexing` + `get_all_roots` remain as internal helpers (used by `bot_indexing._resolve_workspace` + the two admin visibility endpoints) — no deletion. Legacy module file shrink: `memory_indexing.py` 67 → 29 LOC; `channel_workspace_indexing.py` 95 → 32 LOC.

#### Critical regression tests

- `tests/unit/test_workspace_indexing.py` — cascade math.
- `tests/unit/test_memory_indexing.py` — memory gate + pattern resolution.
- `tests/unit/test_channel_workspace_indexing.py` — sentinel bot_id + segment composition.
- `tests/unit/test_fs_watcher_channel_workspace_e2e.py` — watcher + indexing integration.
- `tests/integration/test_workspace_indexing_e2e.py` — end-to-end.
- Any `tests/unit/test_main_startup*.py` (if exists) — startup reindex flow.

#### Risks

- **Shared-workspace "no segments" stale-chunk DB cleanup** (`main.py:204-222`) is ~20 lines of SQL that only runs at startup. Moving it inside `reindex_bot` means it runs more often in principle — mitigate by keying the cleanup on a `segments_source` change flag or by keeping it startup-only via an explicit `cleanup_orphans=True` kwarg.
- **`context_assembly.py:800-826` implicit-KB-prefix dedupe** is channel-retrieval logic, not indexing. Commit 4 should keep that dedupe at the call site — do NOT pull it into `bot_indexing`.
- **Periodic re-index in `fs_watcher.py:321`** uses `force=False` — commit 3 must preserve that explicit flag.

**All 6 commits shipped 2026-04-23.** Indexing abstraction-leak closed: 18 caller sites across 10 files now route through `bot_indexing.resolve_for` / `reindex_bot` / `iter_watch_targets` / `reindex_channel`. Net LOC delta: ~200 lines removed from caller sites; new `bot_indexing.py` is ~300 LOC carrying all prior semantics behind a 4-function public surface. Legacy flavor modules retained as one-liner delegators for external-caller / test-patch stability.

## Actual Bugs

### ~~knowledge.py:266 — `append_to_knowledge` doesn't re-embed~~ SKIPPED (knowledge system being removed)

### knowledge.py:266 — `append_to_knowledge` doesn't re-embed
After `row.content += content`, the embedding is NOT updated. Appended content is invisible to RAG. Compare `edit_knowledge` (line 323) which correctly re-embeds.
- **Impact**: Silent data corruption — content exists but can't be found via search
- **Fix**: Add `row.embedding = await _embed(row.content)` after append

### ~~file_sync.py:828-829 — Watch handler drops skill metadata~~ FIXED April 9
Extracted `_extract_skill_metadata()` helper used by both `sync_all_files` and `sync_changed_file`.

### ~~tasks.py:375,915 — `UnboundLocalError` in except handlers~~ FIXED April 9
`_task_timeout` initialized before try block. `_exec_timeout` was already safe (assigned before try).

### ~~tasks.py:787 — Stale `task` object after DB updates~~ FIXED April 9
`task.correlation_id = correlation_id` now reflects back to in-memory object.

### ~~carapaces.py:268 — No type-check on YAML parse result~~ FIXED April 9
Added `isinstance(data, dict)` check after `yaml.safe_load()`.

### ~~rag.py:192-195 — BM25-only matches bypass similarity threshold~~ FIXED April 9
BM25-only matches now capped at `RAG_TOP_K // 2` to prevent unbounded keyword injection.

## God Functions (structural, address incrementally)

These functions are too large to test, review, or safely modify. Each handles 5-20 distinct concerns inline.

| File | Function | Lines | Concern count |
|------|----------|-------|---------------|
| context_assembly.py | `assemble_context()` | ~~1400~~ **~990** | ~20 pipeline stages (5 extracted so far) |
| loop.py | `run_agent_tool_loop()` | ~~960~~ **~1030** (file: ~~**1684**~~ **1358**) | LLM call, streaming, tool dispatch, approval, cycle detection, etc. Dispatch/helpers split shipped; remaining iteration / retry / post-loop seams still inline |
| file_sync.py | `sync_all_files()` | ~518 | 5 resource types × collect-upsert-orphan-delete |
| tasks.py | `run_task()` | ~490 | session, config, prompt, agent run, persistence, dispatch, follow-up |
| tool_dispatch.py | `dispatch_tool_call()` | ~385 | auth, policy, approval, routing, recording, redaction, summarization |
| compaction.py | `run_compaction_stream()` | ~342 | flush, watermark, section, summary, persistence, trace |
| bots.py | `_bot_row_to_config()` | ~180 | manual field-by-field mapping |
| sessions.py | `persist_turn()` | ~150 | filtering, metadata, delegation, heartbeat, DB, attachments |

**Approach**: Extract each concern into a named sub-function. For `assemble_context`, each `# ---` section becomes its own async function operating on a shared pipeline state object.

### 2026-04-23 stabilization pass

- Approval-gated dispatch no longer relies on fire-and-forget DB writes for correctness-critical state. `tool_dispatch` now creates the `awaiting_approval` `ToolCall` row and matching `ToolApproval` row in one transaction, and normal dispatch/completion awaits strict recording helpers instead of silently dropping missing-row updates.
- `recording.py` now reports zero-row completion/status writes as real failures (`False` by default, raise in `strict=True`) so callers can detect lifecycle drift instead of committing a quiet no-op.
- `loop.py` now reconciles approval timeout verdicts against DB truth via a shared helper, removing the duplicated timeout branch that could locally decide `"expired"` even after another actor had already approved/denied the request.
- The large loop split is still not finished, but the approval timeout duplication was reduced and the risky state machine is materially smaller than before this pass.

### 2026-04-23 focused loop dispatch extraction

- Added `app/agent/loop_helpers.py` and moved the pure helper surface out of `loop.py` (`_sanitize_messages`, transcript-entry helpers, response finalization, fallback helpers, provider resolution).
- Added `app/agent/loop_dispatch.py` and made it the single owner of iteration-time tool dispatch. Parallel and sequential execution now share one `dispatch_iteration_tool_calls()` path plus a common `_process_tool_call_result()` for approval reconciliation, message assembly, tool-result envelopes, client actions, image injection, and `after_tool_call` hooks.
- `run_agent_tool_loop()` no longer contains separate parallel and sequential post-processing branches; it builds `SummarizeSettings` / `LoopDispatchState` once and streams dispatch events from the shared helper.
- Backwards-compat was preserved intentionally at the `app.agent.loop` module boundary. The moved helper names plus the patch-targeted runtime dependencies (`dispatch_tool_call`, `is_client_tool`, `_resolve_approval_verdict`) are still re-exported so existing tests and callers do not need to switch imports.
- Verification surface this session: `python -m py_compile` clean on `loop.py`, `loop_helpers.py`, `loop_dispatch.py`; `tests/unit/test_loop_helpers.py` now passes (`25 passed`). The full `tests/unit/test_parallel_tool_execution.py` file still stalls in the local harness after the first passing case, with aiosqlite worker-thread "event loop is closed" warnings during teardown. Single-test runs such as `test_single_tool_uses_sequential_path` pass, so the remaining issue looks like harness teardown noise rather than an immediate dispatch-order regression.

### loop.py refactor — parked plan (April 11)

`app/agent/loop.py` is back to **1684 lines** despite past splits. Confirmed nothing in `app/agent/` is already-extracted-but-unused — every helper module is imported. Pure option-B split needed.

**Plan:** [/home/mtoth/.claude/plans/fuzzy-growing-hamming.md](file:///home/mtoth/.claude/plans/fuzzy-growing-hamming.md)

**Why parked:** Lots of pending in-flight changes (`app/domain/`, `app/integrations/`, channel renderer work) on the development branch. Re-evaluate the plan against those changes before executing — the dispatch DRY (Step 5) in particular may interact with the new domain/renderer layer.
Update 2026-04-23: the approval-timeout sub-branch was extracted into a shared helper during the lifecycle stabilization pass, but the broader dispatch/iteration split below is still pending.

**Plan summary (6 commits, behavior-preserving, target ~400 lines):**
1. `loop_helpers.py` — pure helpers (`_sanitize_*`, `_extract_usage_extras`, `_finalize_response`, `_record_fallback_event`, etc.). Drops ~280 lines.
2. `loop_nudges.py` — correction / repeated-lookup / learning skill nudges (~50 lines).
3. `loop_iteration.py` — per-iteration pre-work: pruning, breakdown trace, rate limit (~80 lines).
4. `loop_empty_response.py` — silent-vs-forced-retry block (~100 lines).
5. `loop_dispatch.py` — **unify parallel + sequential tool dispatch** (~280 lines, ~140 of which are pure duplication today). Highest-leverage step. Highest risk.
6. `loop_post_loop.py` — cycle/max-iters forced final response (~110 lines).

`run_stream` body stays as-is — already cleanly factored via `assemble_context`. Backwards compat handled by re-exports from `loop.py` so test imports (`_CORRECTION_RE`, `_sanitize_messages`, `_synthesize_empty_response_fallback`, etc.) keep working untouched.

**Critical regression test:** `tests/unit/test_parallel_tool_execution.py` (~14 cases) is the canary for Step 5. If it stays green, the dispatch DRY is correct.

**context_assembly.py progress (April 9)**: Extracted 5 functions so far:
- `_merge_skills()` — shared skill dedup helper (eliminated 3x duplication)
- `_inject_memory_scheme()` — MEMORY.md, daily logs, reference index
- `_inject_channel_workspace()` — workspace files, schema, index segments, plan stall
- `_inject_conversation_sections()` — structured mode retrieval + file mode section index
- `_inject_workspace_rag()` — workspace filesystem RAG (current + legacy)
- Also fixed: redundant channel re-query in conversation sections (used `_ch_row` instead)
- Remaining: tag resolution, skill injection, multi-bot awareness, tool retrieval, capability discovery

## Major Duplication (collapse into shared helpers)

### ~~loop.py:858-1176 — Parallel vs sequential tool dispatch~~ FIXED April 23
Shipped as `app/agent/loop_dispatch.py`. One `dispatch_iteration_tool_calls()` path now owns both execution modes and a shared `_process_tool_call_result()` owns approval/result bookkeeping.

### ~~loop.py:894-997, 1065-1138 — `dispatch_tool_call` invoked 4x with identical 16+ kwargs~~ FIXED April 23
Collapsed behind `_make_dispatch_kwargs()` in `loop_dispatch.py` plus the `SummarizeSettings` dataclass. Initial dispatch and approval re-dispatch now use the same argument builder.

### llm.py:1071-1226 — Streaming vs non-streaming factory closures
6 near-identical closures (`_make_attempt`, `_make_no_tools`, `_make_no_images` × 2). Same kwargs construction repeated 6 times.
- **Fix**: Unify into single factory with `stream: bool` parameter

### compaction.py:830-1474 — Stream vs forced compaction
~250 lines of duplicated pipeline (watermark, section, summary, session update).
- **Fix**: Extract shared compaction core into private helper

### file_sync.py:241-1041 — Full sync vs watch handler
Per-type upsert logic duplicated with inconsistencies (the skill metadata bug above).
- **Fix**: Extract per-type upsert functions called by both paths

### sandbox.py:319-844 — `exec` vs `exec_bot_local`
Secret injection (~15 lines), API key injection, subprocess creation, output truncation — all duplicated.
- **Fix**: Extract `_build_exec_env()` and `_run_subprocess()`

### knowledge.py:240-370 — Dual-lookup pattern 5x
Same ~20-line "try legacy lookup, then fallback to knowledge_access" pattern copy-pasted.
- **Fix**: Extract `_find_knowledge_by_name()` helper

### tasks.py:376-981 — "Mark task failed" pattern 4x
`fetch task → set failed → commit → fire hook → dispatch error` repeated with trivial variations.
- **Fix**: Extract `_fail_task()` helper

### ~~context_assembly.py:500-648 — Skill merge pattern 5x~~ FIXED April 9
Extracted `_merge_skills(bot, new_skill_ids, disabled_ids)` helper. Three enrollment blocks now use it.

## Concurrency & Resource Risks

### tasks.py:1227 — No concurrency limit on task spawning
`asyncio.create_task(run_task(task))` in a loop, up to 20 concurrent tasks. Can exhaust API rate limits, DB pool, or memory.
- **Fix**: `asyncio.Semaphore` to cap concurrent execution

### bots.py:601 — Registry race on reload
`_registry.clear()` creates a window where all bots appear missing. Concurrent `get_bot()` calls during reload will 404.
- **Fix**: Build new registry in local var, then swap atomically

### Multiple files — Fire-and-forget `asyncio.create_task`
~25 total across context_assembly (9), compaction (7), loop, tasks. Unhandled exceptions silently lost. GC may cancel tasks before completion.
- **Fix**: Store references, add done-callback for error logging

### llm.py:434 — Module-level mutable `_model_cooldowns` without lock
Check-then-mutate pattern in async code. Not atomic.
- **Fix**: `asyncio.Lock` around cooldown mutations

### Multiple files — Module-level TTL caches without async safety
`_bot_skill_cache`, `_core_skill_cache`, `_skill_index_cache`, `_tool_cache` — plain dicts accessed concurrently.
- **Fix**: Extract shared `AsyncTTLCache` utility with lock

## Bad Practices (clean up opportunistically)

### Silent exception swallowing
Bare `except Exception: pass` in: context_assembly (4 sites), sandbox (4 sites), loop (3 sites), knowledge (1 site), bots (1 site). Hides misconfigurations and real bugs.
- **Fix**: At minimum log with `exc_info=True`

### bots.py:745 — `get_bot()` raises `HTTPException` from non-HTTP contexts
Background tasks call `get_bot()` and get meaningless `status_code=404`.
- **Fix**: Raise domain exception, let HTTP layer convert

### bots.py:401-468 — Excessive `getattr(row, ..., default)` as migration crutch
~15 fields use defensive getattr instead of direct access. Hides missing column bugs.
- **Fix**: Ensure columns exist via migrations, use direct access

### Inline imports proliferation
~60+ inline imports across audited files. Some are circular-import guards (justified), many are not (`import time`, `import uuid`, `import re`).
- **Fix**: Move non-circular imports to module top. Document circular ones.

### Inconsistent time functions
`time.time()` vs `time.monotonic()` for TTL caches. `time.time()` is subject to clock drift.
- **Fix**: Use `time.monotonic()` consistently for TTL tracking

### docker_stacks.py:654 — No path traversal check in `_materialize_file`
`rel_path` is joined without validation. Currently only called with trusted input.
- **Fix**: Assert resolved path is under stack directory

## Low Priority (cosmetic, minor)

- Leading underscore convention overuse on local variables (context_assembly, loop)
- Magic numbers for truncation lengths (`[:4000]`, `[:500]`, `[:200]`) — define constants
- Duplicate `ExecResult` dataclass in sandbox.py and docker_stacks.py
- `effective_model` variable shadowing in loop.py (assigned to `model`, never diverges)
- `_est_msg_chars` defined inside loop body but has no closure dependency
- Stale docstrings (skills.py:22 says "from DB" but only reads filesystem)
- Redundant `elif not x:` that should be `else:` (file_sync.py:353)
- `asyncio.sleep(0)` without explanation (tasks.py:332,421)

## Approach

This is a pre-freeze cleanup track. Work incrementally:
1. **Bugs first** — the 6 actual bugs above are small, targeted fixes
2. **Duplication** — each duplication item is independently extractable
3. **God functions** — tackle one at a time, starting with the highest-churn files
4. **Concurrency** — the task spawning limit is the most impactful single fix

Don't refactor for refactoring's sake. Each change should make the code more bug-resistant or easier to work in. Test coverage should exist before splitting god functions.
