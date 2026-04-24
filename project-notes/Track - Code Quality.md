---
tags: [agent-server, track, code-quality]
status: active
created: 2026-04-09
updated: 2026-04-24 (Cluster 6b shipped — run_agent_tool_loop now 591 LOC, -36% from 929)
---
# Track — Code Quality & Refactoring

Systematic audit of core agent-server files. 156 files, ~50K lines across `app/agent/`, `app/services/`, `app/tools/`. Findings organized by priority.

## Ousterhout depth audit (2026-04-23)

Audit lens: Ousterhout's "deep module" heuristic (lots of functionality behind a simple interface, hides complexity) vs "shallow module" (not much functionality, complex interface, surfaces complexity). Workflow: Matt Pocock's `improve-codebase-architecture` skill — friction → clusters → parallel interface designs → RFC. Two peer-review rounds shaped the ranking. Full plan: `~/.claude/plans/nifty-hatching-book.md`.

### Depth clusters (ranked)

1. **Indexing abstraction leak at callers** — `workspace_indexing.resolve_indexing()` / `get_all_roots()` are called directly from `app/main.py`, `app/agent/fs_watcher.py`, `app/agent/context_assembly.py:791`, `app/tools/local/channel_workspace.py`, and 4 routers. The flavored wrappers (`memory_indexing`, `channel_workspace_indexing`) encode real policy differences (memory patterns, sentinel bot ids, segment handling, stale-cleanup, bypass semantics) — the problem is caller sites reaching past them. Deepening direction: audit which callers actually need indexing vs. just workspace-root resolution; pull indexing-relevant callers behind the flavor boundary.

2. **Dashboard surface + source-of-truth drift** — `app/routers/api_v1_dashboard.py` (~1,742 LOC, 40+ endpoints on `/widgets` prefix) is fake-deep: 40+ endpoints whose concerns don't share hidden state. Coupled services: `dashboard_pins`, `widget_themes`, `widget_contracts`, `widget_context`, `widget_manifest`, `widget_templates`, `native_app_widgets`, `html_widget_scanner`, `grid_presets`. **Deeper issue**: source-of-truth drift — `GRID_PRESETS` logic appears in more than one place. Router split without unifying preset/theme truth would miss the Ousterhout point. Deepening direction, two-part sequenced: (a) unify preset source of truth across backend + frontend, then (b) split into four-to-five thematic sub-routers paired with their service modules (pattern: `app/routers/api_v1_admin/`).

3. **Boundary-bypass smell — ✅ shipped 2026-04-23 (Cluster 3)** — 118 `raise HTTPException` sites across 10 non-router modules migrated to a `DomainError` hierarchy in `app/domain/errors.py`. Plus `app/services/machine_control.py`'s `request: Request` parameter — the one non-raise HTTP leak — converted to a `server_base_url: str` primitive extracted at the router. `from fastapi` removed from all of `app/services/`, `app/agent/`, `app/tools/` (sole allowlist: `endpoint_catalog.py`, which introspects FastAPI routes). A drift test (`tests/unit/test_fastapi_boundary_drift.py`) AST-parses the three directories and fails any reintroduction. The router-boundary adapter is a single exception handler registered via `install_domain_error_handler(app)` — reused by `app/main.py` and the integration test app fixture so both environments produce the same `{"detail": ...}` wire shape. See RFC below.

4. **Cross-surface drift — ✅ shipped 2026-04-24 (Cluster 4)** — three drift classes across widget / chat-streaming / theme surfaces.
   - **4A (event bus)** — 27-value `ChannelEventKind` enum with no UI-side consumer for `CONTEXT_BUDGET` (store slot was dead); wired + drift test pins every kind to a case or an explicit-justification allowlist (`tests/unit/test_channel_event_contract_drift.py`).
   - **4B (widget boundary)** — 7 private helpers (`_substitute`, `_substitute_string`, `_apply_code_transform`, `_build_html_widget_body`, `_resolve_html_template_paths`, `_resolve_bundle_dir`, `_validate_parsed_definition`) imported across widget_*.py siblings; promoted to public re-exports, callers migrated (inside + outside widget_*.py), AST drift test (`tests/unit/test_widget_private_import_drift.py`) blocks reintroduction. Layout semantics extracted into new `app/services/widget_layout.py` (single home for `VALID_ZONES`, zone-from-hints resolution, size clamp, normalize_layout_hints) — previously split between `widget_contracts.py` and `dashboard_pins.py`. `_refresh_pin_contract_metadata` (5 JSONB `flag_modified` calls, 0 tests) now has 7 invariant tests (`tests/unit/test_refresh_pin_contract_metadata.py`).
   - **4C (theme tokens)** — ~35 semantic tokens duplicated across `ui/src/theme/tokens.ts`, `app/services/widget_themes.py`, `ui/global.css`, `ui/src/components/chat/renderers/widgetTheme.ts`. No codegen generator (scope creep); instead a cross-layer drift test (`tests/unit/test_theme_token_drift.py`) pins hex equality between `tokens.ts` and `widget_themes.py` (all shared keys, LIGHT + DARK) and pins global.css RGB triplets to tokens.ts hex. A 6-key LIGHT drift allowlist captures existing `:root`-vs-`tokens.ts` divergence (text-dim, success, warning, danger, purple, danger-muted) with inverse pin to prevent stale allowlist entries. Inline-hex ratchet (`tests/unit/test_ui_inline_hex_ratchet.py`) freezes the 684-occurrence baseline across `ui/src` + `ui/app` `.ts`/`.tsx` (excluding 3 canonical palette files).

5. **tool_dispatch deepening — ✅ shipped 2026-04-24 (Cluster 5)** — `dispatch_tool_call` at `app/agent/tool_dispatch.py:512` was 686 LOC of linear-but-entangled auth / execution-policy / tool-policy / approval / plan-mode guards + per-kind tool routing + envelope building + summarization + tool_event assembly. Extracted seven cohesive helpers: three deny-path helpers (`_apply_error_payload`, `_enqueue_denial_record`, `_parse_args_dict`), four pre-execution guards (`_authorization_guard`, `_execution_policy_guard`, `_policy_and_approval_guard`, `_plan_mode_guard`) each returning `ToolCallResult | None`, `_classify_pre_hook_type` (previously duplicated), `_execute_tool_call` as the client/local/mcp/widget routing + wall-clock guard, and three post-execution helpers (`_extract_embedded_payloads`, `_select_result_envelope`, `_build_tool_event`). The main function is now a linear pipeline: MCP-name-resolve → guards → classify → row insert → execute → redact → extract → envelope → UPDATE → summarize → tool_event. 686 → 310 LOC (55% reduction) with behaviour-identical output; verified against the 9-file dispatch test sweep (86 passed, 17 pre-existing failures confirmed by stash-and-compare).

6. **Context replay sizing guard — ✅ shipped 2026-04-24** — A qa-bot trace exposed a blind spot after context-estimation consolidation: replayed assistant `tool_calls[].function.arguments` were neither pruned nor counted in `live_history_tokens`, so the budget showed ~7.9k live-history tokens while the outbound prompt carried ~801k assistant chars and OpenAI rejected it as over-window. Added model-visible argument compaction in `context_pruning`, shared prompt-size helpers that include tool calls, context-breakdown parity, and a final pre-provider `context_window_exceeded` guard in the loop. This is a targeted bug fix, not the broader `assemble_context` Cluster 6 refactor.

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
- ~~`app/services/grid_presets.py`~~ — ✅ deleted as Cluster 2 Commit A1 (2026-04-23). Was an orphan (0 importers); real backend preset source of truth lives in `app/services/dashboards.py`.

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

### RFC — Cluster 2 — `/widgets` router split + preset source-of-truth drift (2026-04-23)

Plan: `~/.claude/plans/nifty-hatching-book.md` (overwritten from Cluster 1 plan). User decisions during planning: **keep backend/frontend GRID_PRESETS dual + add drift test** (not server-authored, not codegen); **split `/widgets` into 4 sub-routers** (not 6, not 3).

**Part A — Preset source-of-truth (2 commits):**

- ✅ **A1** — Deleted `app/services/grid_presets.py` (37 LOC orphan with 0 importers). Updated `migrations/versions/226_widget_pin_zone.py` comment to reference `app/services/dashboards.py` as the real backend owner.
- ✅ **A2** — Added `tests/unit/test_grid_preset_drift.py` (4 tests). Parses `app/services/dashboards.py::GRID_PRESETS` (Python dict literal) and `ui/src/lib/dashboardGrid.ts::GRID_PRESETS` (TS object literal, narrow regex) and pins the 4 numeric invariants across layers: preset ids match, `cols_lg == cols.lg`, `row_height == rowHeight`, `DEFAULT_PRESET == DEFAULT_PRESET_ID`. Skips (not fails) when `ui/` is absent (Docker test image). Since no API exposes presets to the frontend, they were drifting by omission — this catches the next edit that forgets to update both sides.

**Part B — `/widgets` router split (5 commits):**

- ✅ **B1** — Scaffolded `app/routers/api_v1_widgets/` package. `__init__.py` exposes `router = APIRouter(prefix="/widgets", tags=["widget-dashboard"])` aggregating sub-routers. `_common.py` holds the shared `auth_identity` helper. Legacy `api_v1_dashboard.py` mounted via `include_router` during transition. `app/routers/api_v1.py` import flipped to the new package. Smoke: 40 `/widgets/*` routes preserved.
- ✅ **B2** — Extracted `api_v1_widgets/library.py` (~690 LOC). Read-only content surface: `/html-widget-catalog`, `/themes` (+ `/themes/resolve`), `/html-widget-content/*` (builtin/integration/library), `/library-widgets` (+ `/all-bots` dev-panel variant), `/widget-manifest`. Carries helpers `_scanner_entry_to_library` + `_serve_widget_file` (library is the sole user). Also moved the `WidgetThemeResolveOut` Pydantic model since only the themes endpoint uses it. Prefix moved from legacy to package in one step.
- ✅ **B3** — Extracted `api_v1_widgets/dashboards.py` (~260 LOC). CRUD + rails + redirect + channel-pins: `list_all_dashboards`, `get_redirect_target`, `list_channel_dashboard_pins`, `get_single_dashboard`, `create_new_dashboard`, `patch_dashboard`, `put_rail_pin`, `delete_rail_pin`, `remove_dashboard`. Uses `auth_identity` from `_common`. `list_recent_widget_calls` deferred to B5 (theme, not file-position).
- ✅ **B4** — Extracted `api_v1_widgets/pins.py` (~330 LOC). All pin CRUD + layout + panel promotion + db-status + refresh: 11 endpoints. `refresh` preserves the lazy import of `app.routers.api_v1_widget_actions` verbatim to avoid a module-level cycle.
- ✅ **B5** — Extracted `api_v1_widgets/presets.py` (~470 LOC) and **deleted legacy `app/routers/api_v1_dashboard.py`**. Presets + suites + recent-calls + preview-for-tool: 11 endpoints including the preset catalog/binding-options/preview/pin flow, suites, and the recent-call widget render. Legacy module gone; package is the sole mount point.

**Verification summary:**
- Final route count: 40 `/widgets/*` routes, identical paths + HTTP methods to pre-refactor baseline.
- `python -c "from app.main import app"` — clean import.
- `pytest tests/unit/test_dashboards_service.py tests/unit/test_dashboard_pin_drift.py tests/unit/test_dashboard_cascade_drift.py tests/unit/test_apply_layout_drift.py tests/unit/test_grid_preset_drift.py` — 57 pass.
- `pytest tests/integration/test_dashboard_pins.py tests/integration/test_dashboard_tools.py` — 41 pass, 6 pre-existing failures confirmed on clean `HEAD` (unrelated to refactor: 3 `pin_widget` tool tests + 2 `TestChannelHeaderSlot` + 1 `test_move_to_header_normalizes_h_to_1`).
- `cd ui && ./node_modules/.bin/tsc --noEmit` — clean (0 errors).

**LOC delta:**
- Deleted: `api_v1_dashboard.py` (1742 LOC) + `grid_presets.py` (37 LOC) = 1779 LOC.
- Added: 5-file package `api_v1_widgets/` (~1802 LOC) + drift test (~120 LOC) ≈ 1920 LOC.
- Net: +141 LOC for the per-theme docstrings + drift test guard. Structural win is split-by-theme + cross-layer pin on preset drift.

**Closed 2026-04-23.** Cluster 2 complete. Frontend and backend preset tables remain independent (by choice) but now fail-loud on drift. Router surface is 4 focused sub-routers matching `api_v1_admin/` pattern. `dashboard_pins.py` (1087 LOC) internal restructure still open under the god-function list below — separate work.

### RFC — Cluster 3 — Boundary-bypass: services stop importing from fastapi (2026-04-23)

**Shape:** domain-exception hierarchy at `app/domain/errors.py`; router boundary registers a single handler that converts `DomainError` → `{"detail": ...}` JSON. Services/agent/tools no longer `raise HTTPException` or take `Request` parameters.

**Commit plan (12 logical steps, all shipped 2026-04-23):**

- ✅ **C1** — Added `app/domain/errors.py` with base `DomainError` + five subclasses: `NotFoundError` (404), `ValidationError` (400), `UnprocessableError` (422), `ConflictError` (409), `ForbiddenError` (403), `InternalError` (500). `detail` accepts string or dict to preserve `HTTPException(detail={"error": ..., "message": ...})` callsites verbatim. Added `install_domain_error_handler(app)` so both `app/main.py` and the integration test fixture register the same converter. 8-test pin of the mapping in `tests/unit/test_domain_errors.py`.
- ✅ **C2** — `app/agent/bots.py` (1 site): `get_bot` now raises `NotFoundError`.
- ✅ **C3** — `app/services/dashboard_rail.py` (4 sites): 3× `ValidationError`, 1× `ForbiddenError`.
- ✅ **C4** — `app/services/plan_semantic_review.py` (5 sites): 2× `NotFoundError`, 3× `ConflictError`.
- ✅ **C5** — `app/services/pinned_panels.py` + `app/services/tool_execution.py` (12 sites combined): tool_execution preserves the dict-shaped `ForbiddenError({"error": "local_control_required", ...})` by widening `DomainError.detail` to `Any`.
- ✅ **C6** — `app/services/widget_presets.py` (8 sites). `except HTTPException` in `list_binding_options` swept-up retargeted to `except DomainError` so per-source error isolation still works.
- ✅ **C7** — `app/services/dashboards.py` (15 sites).
- ✅ **C8** — `app/services/dashboard_pins.py` (22 sites). `except HTTPException` in `_sync_native_pin_envelopes` → `except DomainError`.
- ✅ **C9** — `app/services/session_plan_mode.py` (25 sites).
- ✅ **C10** — `app/services/native_app_widgets.py` (26 sites — largest).
- ✅ **C11** — Extracted `Request` from `app/services/machine_control.py` + `integrations/local_companion/machine_control.py`. The `MachineControlProvider.enroll` Protocol signature now takes `server_base_url: str`; the router (`app/routers/api_v1_admin/machines.py`) extracts `str(request.base_url)` and passes the primitive in. Service layer no longer imports from `fastapi` at all.
- ✅ **C12** — Added `tests/unit/test_fastapi_boundary_drift.py` — AST-walks every `.py` under `app/services/`, `app/agent/`, `app/tools/` and fails if any module imports from `fastapi`. AST (not regex) so scaffolded code inside string literals in `app/tools/local/admin_integrations.py` is correctly ignored. Sole allowlist entry: `app/services/endpoint_catalog.py` (introspects FastAPI routes for the discovery surface, does not raise HTTP errors).

**Router-side follow-on (same session, after the core migration):**

Eight router files had `except HTTPException:` catches that translated an upstream HTTPException into a different HTTP response (e.g. "unknown bot" 404 → 400 with friendlier wording). After the service migration these catches would miss, and the downstream DomainError would bypass the router-layer UX translation. Added `except (HTTPException, DomainError):` to:

- `app/routers/api_v1_widget_actions.py` (4 sites — widget-action envelope error path)
- `app/routers/api_v1_channels.py`, `api_v1_admin/channels.py`, `api_v1_messages.py`, `api_v1_sessions.py` (4 sites), `api_v1_todos.py`, `api_v1_admin/bots.py`, `api_v1_widgets/library.py` (all `get_bot` → "Unknown bot" translation catches)

The one `exc.status_code != 404` branch (`api_v1_channels.py::delete_channel`) now checks `exc.http_status` when the exception is a `DomainError`.

**Verification:**
- `python -c "from app.main import app"` — clean import (pre-existing `machine_control.py` circular import noted, unchanged by this refactor).
- `pytest tests/unit/test_domain_errors.py tests/unit/test_fastapi_boundary_drift.py tests/unit/test_bots.py tests/unit/test_dashboards_service.py tests/unit/test_dashboard_pin_drift.py tests/unit/test_dashboard_cascade_drift.py tests/unit/test_apply_layout_drift.py tests/unit/test_dashboard_pins_service.py tests/unit/test_plan_semantic_review.py tests/unit/test_session_plan_mode.py tests/unit/test_session_plan_mode_drift.py tests/unit/test_native_app_widgets.py tests/unit/test_channel_pinned_panels.py tests/unit/test_local_companion_provider.py tests/unit/test_widget_presets.py tests/unit/test_widget_preset_drift.py tests/unit/test_native_envelope_repair_drift.py tests/unit/test_grid_preset_drift.py` — **199 passed**.
- `pytest tests/integration/test_dashboard_pins.py tests/integration/test_dashboard_tools.py` — **55 passed, 6 pre-existing failures** confirmed on clean `HEAD` via `git stash` (same 6 as the Cluster 2 verification: 3 `pin_widget` tool tests + 2 `TestChannelHeaderSlot` + 1 `test_move_to_header_normalizes_h_to_1`).

**LOC delta:**
- Added: `app/domain/errors.py` (~60 LOC including handler) + drift test (~80 LOC) ≈ 140 LOC.
- Removed from service/agent/tool layer: 10 `from fastapi import HTTPException` lines, 1 `from fastapi import Request` line, 118 HTTPException raise sites (rewritten in place — same line count, different class).
- Net file count change: +1 (`app/domain/errors.py`), +1 (`tests/unit/test_domain_errors.py`), +1 (`tests/unit/test_fastapi_boundary_drift.py`).

**Closed 2026-04-23.** All three Ousterhout depth clusters promoted in the 2026-04-23 audit are now shipped. The track stays active for the god-function list + housekeeping below.

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
| loop.py | `run_agent_tool_loop()` | ~~960~~ ~~1030~~ ~~809~~ **591** (file: ~~**1684**~~ ~~1358~~ **1136**) | Clusters 6a+6b shipped. 929 → 591 LOC (-36%). Remaining 591 LOC is cohesive per-iteration orchestration (cancellation checks, LLM streaming, dispatch, image injection, skill-nudge, cycle detection) — further reduction needs cross-iteration state objects, not more extractions. |
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

---

### RFC — Cluster 4 — Cross-surface drift: event bus, widget boundary, theme tokens (2026-04-24)

Plan: `~/.claude/plans/nifty-hatching-book.md`. Follows the same workflow as Clusters 1–3: four parallel Ousterhout audits (widgets, chat streaming, themes, agent core) → three shippable drift-closure sub-clusters. The god-function winner (tool_dispatch) is parked as Cluster 5 per scope discipline.

#### Sub-cluster 4A — Channel event-bus contract

**What shipped:**
- `tests/unit/test_channel_event_contract_drift.py` — enum-values-vs-UI-switch guard. Iterates `ChannelEventKind` (26 values after `SESSION_PLAN_UPDATED` recontextualization); fails any kind that has neither a `case` in `ui/src/api/hooks/useChannelEvents.ts` nor an entry in the file's `ALLOWLIST` with a comment naming where the kind is actually consumed (widget iframe observer path, agent-side waiter, integration renderer, focused stream subscription).
- `CONTEXT_BUDGET` wired in `useChannelEvents.ts` (single `case` → `store.setContextBudget(storeKey, {utilization, consumed, total})`). Previously the publisher emitted and the store slot existed but nothing dispatched — `BotInfoPanel` + session-header read-out were dark until now.
- 9-entry ALLOWLIST documents the legitimate non-consumers: `widget_reload` (iframe-only), `modal_submitted` (agent-side waiter), `ephemeral_message` (publisher rewrite), `session_plan_updated` (consumed via `useSessionPlanMode.ts:307` raw stream), `attachment_deleted` (integration renderers), `heartbeat_tick` + `workflow_progress` + `tool_activity` (no app-chrome consumer), `memory_scheme_bootstrap` (observability signal).

**Why this matters:** exact failure mode `feedback_bus_contract_end_to_end.md` recorded — multiple bus layers silently out of sync. Now structurally impossible to regress.

#### Sub-cluster 4B — Widget boundary + layout SOT + pin-refresh pin

**What shipped:**
- Promoted 7 cross-module private helpers in `app/services/widget_templates.py` (`substitute`, `substitute_string`, `apply_code_transform`, `build_html_widget_body`, `resolve_html_template_paths`, `get_widget_template_with_bare_fallback`), `app/services/widget_py.py` (`resolve_bundle_dir`), and `app/services/widget_package_validation.py` (`validate_parsed_definition`) to public aliases. Migrated all callers (5 in `widget_*.py`, 2 in `dashboard_pins.py` + `api_v1_widget_actions.py`).
- `tests/unit/test_widget_private_import_drift.py` — AST-walks `app/services/widget_*.py`, fails any cross-module `from app.services.widget_X import _private`. Test files allowed (they legitimately poke internal caches for fixture teardown).
- New `app/services/widget_layout.py` as the single SOT for layout-hint semantics: `VALID_ZONES` (frozenset), `normalize_layout_hints` (moved from `widget_contracts`), `resolve_zone_from_layout_hints` (moved from `dashboard_pins`), `clamp_layout_size_to_hints` (moved from `dashboard_pins`), `validate_zone`. Grid-mechanics helpers (`_seed_layout_from_hints`, `_normalize_coords_for_zone`, `_default_layout_for_zone`) stay in `dashboard_pins` because they depend on per-dashboard preset config — deliberate seam between *intent* (layout.py) and *mechanics* (dashboard_pins). `widget_contracts` re-exports `normalize_layout_hints` as a compat pointer.
- `tests/unit/test_refresh_pin_contract_metadata.py` (7 tests) — pins the silent UPDATE helper that mutates 5 JSONB fields with `flag_modified`. Covers: inferred-origin + default-presentation population, idempotency, no-op when already aligned, `widget_origin` JSONB flag_modified required, `provenance_confidence` scalar needs no flag_modified, all 3 snapshot fields flag_modified when they drift, no flag_modified calls when nothing drifts (catches "buggy `!=` comparison" regressions).

**Why this matters:** `feedback_pin_drift_not_happy_path.md` — silent UPDATE helpers are the #1 class of pin-bug hide spots. Now pinned. Boundary reach-ins between widget_* siblings were a textbook Ousterhout information leak; fixed + guarded.

#### Sub-cluster 4C — Theme token drift + inline-hex ratchet

**What shipped (revised from plan — no codegen generator):**
- `tests/unit/test_theme_token_drift.py` (5 tests):
  - `ui/src/theme/tokens.ts LIGHT/DARK` hex values must equal `app/services/widget_themes.py BUILTIN_LIGHT/DARK_TOKENS` for every shared key (both passes).
  - `ui/global.css :root` RGB triplets must equal `tokens.ts LIGHT` hex-converted-to-RGB for every shared key. 6-key `_LIGHT_KNOWN_DRIFT_KEYS` allowlist captures pre-existing `:root`-vs-`tokens.ts` divergence with an inverse pin that fails if an allowlisted key has been fixed (prevents stale allowlist).
  - `ui/global.css .dark` RGB triplets must equal `tokens.ts DARK` hex-converted-to-RGB (no drift at HEAD; test passes).
- `tests/unit/test_ui_inline_hex_ratchet.py` (2 tests) — counts `#rgb`/`#rrggbb` literals in `ui/src` + `ui/app` `.ts`/`.tsx` (excluding 3 canonical palette files: `src/theme/tokens.ts`, `src/components/chat/renderers/widgetTheme.ts`, `widgetTheme.test.ts`). Freezes current 684 count as `_BASELINE`; ratchet fails if exceeded. Inverse "tight baseline" pin fails if actual count drops more than 10 below baseline (forces updating the baseline when hex literals are removed — keeps the ratchet honest).

**Why this matters:** same ~35 semantic tokens live in 4 files in 3 different encodings with no sync tooling. Drift test catches silent desync between app chrome and widgets (or dark vs light). Ratchet converts `feedback_tailwind_not_inline.md`'s "new code should use Tailwind" from soft intent to an enforceable invariant.

#### Commits + files

**New (9 files):**
- `app/services/widget_layout.py`
- `tests/unit/test_channel_event_contract_drift.py`
- `tests/unit/test_widget_private_import_drift.py`
- `tests/unit/test_refresh_pin_contract_metadata.py`
- `tests/unit/test_theme_token_drift.py`
- `tests/unit/test_ui_inline_hex_ratchet.py`

**Edited (12 files):**
- `app/services/widget_templates.py` (public aliases + `get_widget_template_with_bare_fallback`)
- `app/services/widget_py.py` (public `resolve_bundle_dir` alias)
- `app/services/widget_package_validation.py` (public `validate_parsed_definition` alias)
- `app/services/widget_preview.py`, `widget_presets.py`, `widget_packages_seeder.py`, `widget_cron.py`, `widget_events.py`, `widget_handler_tools.py`, `widget_db.py`, `widget_templates.py` (public imports)
- `app/services/widget_contracts.py` (re-export `normalize_layout_hints` from `widget_layout`)
- `app/services/dashboard_pins.py` (delegate zone/hint helpers to `widget_layout`)
- `app/routers/api_v1_widget_actions.py` (public `resolve_bundle_dir`)
- `ui/src/api/hooks/useChannelEvents.ts` (add `case "context_budget":`)

**Verification (what ran):**
- `pytest` focused sweep across 16 Cluster-4-related test files → 164 passed + 9 pre-existing `test_dashboard_rail.py` SQLite `NOT NULL` failures (unchanged from Cluster 3 baseline).
- `pytest` on the 5 new drift tests directly → all pass.
- `cd ui && npx tsc --noEmit` → no new errors in files touched by Cluster 4 (123 pre-existing errors are merge-conflict markers in untouched `ChatSession.tsx` / `ChannelDashboardMultiCanvas.tsx` — unrelated working-tree state).

**Non-goals (explicit):**
- No new event kinds; no widget behavior changes; no theme generator/codegen; no service-layer refactors beyond the layout extraction. Inline-style rewrites are ambient (ratchet stops regression; migration happens when authors touch the files).

**Out of scope (parked for future clusters):**
- **Cluster 5 — tool_dispatch deepening — ✅ shipped 2026-04-24.** See RFC below.
- **Cluster 6a — `run_agent_tool_loop` setup/recovery helpers — ✅ shipped 2026-04-24.** Five extractions (`_resolve_loop_config`, `_resolve_loop_tools`, `_inject_opening_skill_nudges`, `_merge_activated_tools_into_param`, `_recover_tool_calls_from_text`) into `loop_helpers.py`. 929 → 809 LOC on the orchestrator (~13%). Same-file size net-zero (helpers moved from one file to its sibling). Behavior-preserving: 87 pass / 12 fail matches baseline exactly. Dependency-injection pattern on schema-fetch callables preserves test-time patchability on `app.agent.loop.*`. See RFC below.
- **Cluster 6b — `run_agent_tool_loop` fat-block extractions — ✅ shipped 2026-04-24.** Three extractions into `loop_helpers.py`: `_check_prompt_budget_guard` (sync, returns `PromptBudgetGate(events, should_return, wait_seconds)` dataclass — context-window hard block + TPM rate-limit wait), `_handle_no_tool_calls_path` (async generator — empty-response retry + `_finalize_response`), `_handle_loop_exit_forced_response` (async generator with mutable `out_state` dict — cycle/max-iter forced LLM call + `_finalize_response`, signals `out_state["terminated"]=True` on LLM failure so caller skips tool-enrollment flush and exits the outer generator, preserving the original `return` semantics). 809 → 591 LOC on the orchestrator (-218 LOC, 27%). Combined Cluster 6a+6b: 929 → 591 LOC (-36%). Behavior-preserving: 87 pass / 12 fail matches baseline exactly; neighbor sweep 63 passed + 4 pre-existing fails unchanged. `_llm_call` injected as `llm_call_fn` kwarg (Cluster 5/6a DI pattern) so test patches on `app.agent.loop._llm_call` still intercept. See RFC below.
- **Cluster 7 — `assemble_context` (1500 LOC) in `context_assembly.py`.** Highest remaining payoff, highest effort.
- **Widget envelope triple-rebuild reconciliation** (`native_app_widgets.py:753` + `widget_contracts.py:406` + `dashboard_pins.py:269`) — touches cross-module pin semantics; deserves its own focused cluster.
- **Terminal chat mode as CSS archetype** — currently a render-code fork (`chatMode` prop); works. Punt until a third archetype appears.
- **LIGHT color-drift fix** — the 6 allowlisted keys (`text-dim`, `success`, `warning`, `danger`, `purple`, `danger-muted`) are a real design call between Tailwind-default shades and darker designer-chosen shades. Out of scope for a refactor; in scope for the next UI polish pass.

### RFC — Cluster 5 — tool_dispatch deepening (2026-04-24)

**Target**: `dispatch_tool_call` at `app/agent/tool_dispatch.py:512` — 686 LOC, the largest god function flagged in Cluster 4's parking note.

**Diagnosis**: the function ran top-to-bottom through four pre-execution guards (auth, execution-policy/machine-control, tool-policy + approval creation, plan-mode), then per-kind routing (client/local/mcp/widget) under a shared wall-clock timeout, then post-execution processing (secret redaction, `_envelope` opt-in extraction, envelope selection, summarization, tool_event + presentation + plan-evidence recording). Five deny-path arms were near-duplicates of each other (set error JSON, set tool_event, enqueue `_record_tool_call`, return). The per-kind routing was a four-arm `if/elif` with subtle differences (client tools use their own long-poll timeout; local tools split persona vs registry; mcp carries `_tc_server` through to later wrap-in-untrusted-tags). Envelope selection had three precedence branches plus poll-cache invalidation.

**Refactor** (one commit, behaviour-identical):
1. **Deny-path helpers** — `_apply_error_payload` populates `result`/`result_for_llm`/`tool_event` from a single `error_message` (or a pre-serialized `raw_result` override for the machine-control `local_control_required` structured shape). `_enqueue_denial_record` fires `safe_create_task(_record_tool_call(..., status='denied'))` with an optional `envelope` kwarg. `_parse_args_dict` returns `{}` on any parse failure or non-dict. The five deny arms are now 4-5 lines each.
2. **Pre-execution guards** — four `async def …_guard(result_obj, *, …) -> ToolCallResult | None` functions plus `_execution_policy_guard` which returns `(ToolCallResult | None, execution_policy: str)` (the tuple surfaces the policy string so `_policy_and_approval_guard` can short-circuit default `require_approval` for `interactive_user` / `live_target_lease` tools). Main body calls them with walrus chains, so the visible control flow is `if (deny := await _x_guard(...)) is not None: return deny`. `_classify_pre_hook_type(name)` collapses a previously-duplicated four-branch classifier.
3. **Execution core** — `_execute_tool_call(result_obj, *, name, args, ..., pre_hook_type, compaction)` fires the `before_tool_execution` hook, selects the per-kind coroutine (client long-poll via `create_pending`, local/persona via `call_local_tool`/`call_persona_tool`, mcp via `call_mcp_tool`, widget via `_call_widget_handler_tool`), runs under `asyncio.wait_for(tool_coro, timeout=settings.TOOL_DISPATCH_TIMEOUT)`, and stamps `result_obj.duration_ms`. Returns `(raw_result, tc_type, tc_server)` — `tc_type` may differ from `pre_hook_type` only for the persona-alias case.
4. **Post-execution helpers** — `_extract_embedded_payloads(raw_result)` parses JSON once and returns `(result_for_llm, envelope_optin, client_action, injected_images)`; this replaces a nested try/except that mutated four local vars. `_select_result_envelope(*, name, tool_call_id, redacted_result, envelope_optin, redact)` implements the three-precedence envelope selection (opt-in → widget template → default) and the widget-poll-cache invalidation; the `redact` callable is injected to keep the function pure. `_build_tool_event(*, name, tool_call_id, args, redacted_result, result_for_llm, envelope, was_summarized)` assembles the SSE event including the error-hoist branch and `derive_tool_presentation` call.

Post-refactor, `dispatch_tool_call` body reads as: forgiving MCP name resolution → `_parse_args_dict` → four guards → classify + safety-tier lookup → plan-mode guard → row insert → `_execute_tool_call` → redact → `_extract_embedded_payloads` → re-redact + MCP-wrap + audit + hard-cap → `_will_summarize` decision + `_select_result_envelope` → `_complete_tool_call` UPDATE → optional summarize + trace event → `_build_tool_event` → plan-evidence fire-and-forget → return. 310 LOC (55% reduction).

**Why this is deep, not shallow** — the seven helpers are small interfaces over substantial hidden logic. `_select_result_envelope` hides opt-in body redaction, widget-template pattern matching, and cross-module poll-cache invalidation. `_execute_tool_call` hides the four-arm kind dispatch, the client-vs-shared timeout distinction, and the monotonic stopwatch stamp. `_policy_and_approval_guard` hides the approval-tool-type classification, the tier-prefixed reason formatting, the atomic `_create_approval_state` transaction, the `needs_approval=True` return shape, and three distinct error paths (deny / approval-state-create-failed / policy-eval-failed). Callers see intent, not mechanism.

**Verification (what ran):**
- `python -c "from app.agent.tool_dispatch import dispatch_tool_call"` — clean (circular-import warning re `ToolResultEnvelope` is pre-existing on `development` HEAD).
- Focused pytest sweep (`test_tool_dispatch_core_gaps`, `test_tool_dispatch_envelope`, `test_tool_dispatch_timeout`, `test_dispatch_recording_seam`, `test_tool_authorization`, `test_tier_policy_bridge`, `test_heartbeat_skip_approval`, `test_approval_lifecycle_drift`, `test_approval_orphan_pointers`): 86 passed, 17 failed. Baseline verified by `git stash && pytest && git stash pop` — identical 17 failures on clean HEAD. All 17 share the same `no such table: sessions` root cause: test fixtures pass a real UUID for `session_id` but don't create the row, and `_plan_mode_guard`'s `_load_session_for_plan_mode` hits the missing table. Pre-existing test-harness bug, not introduced here.
- Additional: `test_widget_py` + `test_turn_aggregate_cap` + `test_cancellation` → 45 passed. `test_parallel_tool_execution` + `test_security_fixes` + `test_security_audit` + `test_internal_tools_budget` → 77 passed.

**Non-goals (explicit):**
- No signature changes to `dispatch_tool_call` — `loop_dispatch.py`'s `_make_dispatch_kwargs` (13 callsites) keeps working without edits.
- No test changes — the pre-existing fixture gap is a Test Quality track item, not Cluster 5's scope.
- No behavioural deltas: deny-arm tool_event shape, approval-state mutation shape, envelope precedence, poll-cache invalidation timing, wall-clock timeout semantics, MCP untrusted-wrap, audit-log trigger are all byte-identical.

**Out of scope (parked):**
- Cluster 6+ — `assemble_context` (1500 LOC) and `run_agent_tool_loop` (883 LOC). Highest payoff, highest effort remaining.
- `_complete_tool_call` vs `_record_tool_call` discipline. The happy path uses `_start_tool_call` + `_complete_tool_call` (strict); deny paths use `_record_tool_call` (fire-and-forget insert). Consolidation worth a focused look — would simplify `_enqueue_denial_record` further — but touches recording semantics and should ship separately.

### RFC — Cluster 6a — run_agent_tool_loop setup/recovery helpers (2026-04-24)

**Target**: `run_agent_tool_loop` at `app/agent/loop.py:65` — 929 LOC, flagged as second-largest god function after Cluster 5.

**Diagnosis**: the function opens with ~100 LOC of pre-iteration setup (context-profile override, effective-iteration cap, model/provider resolve, effort ContextVar overlay, summarize-settings assembly from `bot.tool_result_config`, tool-schema assembly with auto-inject of `get_skill`/`get_skill_list`, `current_injected_tools` ContextVar merge, authorization-set computation, `current_activated_tools` seeding), followed by ~40 LOC of opening-turn skill nudges (correction-regex gated + repeated-lookup detection gated), then the main for-loop. Within each iteration three sub-seams were clearly cohesive: (a) merging mid-loop `get_tool_info` activations into `tools_param`, (b) recovering tool calls from JSON-in-text or suppressed XML (local-model compatibility), plus the three fat terminal blocks queued as Cluster 6b (context-budget guard, no-tool-calls retry-and-finalize, post-loop forced response).

**Refactor** (one commit, behaviour-identical):
1. **`_resolve_loop_config(bot, *, max_iterations, model_override, provider_id_override, context_profile_name) -> LoopRunConfig`** — pure synchronous helper. Returns `LoopRunConfig(effective_max_iterations, model, provider_id, effective_model_params, summarize_settings, in_loop_keep_iterations)`. Lazy-imports `get_context_profile`, `SummarizeSettings`, `current_effort_override`, `settings` to avoid circular deps. ~35 LOC extracted.
2. **`_resolve_loop_tools(bot, *, pre_selected_tools, authorized_tool_names, compaction, get_local_tool_schemas_fn, fetch_mcp_tools_fn, get_client_tool_schemas_fn, merge_tool_schemas_fn) -> LoopToolState`** — async helper. The schema-fetch callables are injected as kwargs (same pattern as Cluster 5's `dispatch_tool_call_fn=dispatch_tool_call`) so tests patching `app.agent.loop.get_local_tool_schemas` etc. continue to intercept. Returns `LoopToolState(all_tools, tools_param, tool_choice, effective_allowed, has_manage_bot_skill, activated_list)`. Seeds `current_activated_tools.set(activated_list)` inside. ~40 LOC extracted.
3. **`_inject_opening_skill_nudges(*, bot, messages, has_manage_bot_skill, correlation_id)`** — async helper. Mutates `messages` in place with the two one-shot opening-turn nudges (correction-regex via `_extract_last_user_text` + `_CORRECTION_RE`, repeated-lookup via `find_repeated_lookups`). Gated on `has_manage_bot_skill` from `LoopToolState`. ~37 LOC extracted.
4. **`_merge_activated_tools_into_param(activated_list, tools_param, tool_choice, effective_allowed, *, iteration) -> (tools_param, tool_choice)`** — sync helper. Extends `effective_allowed` set in place for the new tool names, returns the new `tools_param`/`tool_choice`. Preserves the `logger.info` shape that admin UI consumers parse. ~30 LOC extracted.
5. **`_recover_tool_calls_from_text(accumulated_msg, messages, effective_allowed)`** — sync helper. Tries JSON-in-content extraction first (content is replaced with the non-JSON remainder); if that produces no tool calls, falls through to XML extraction from `accumulated_msg.suppressed_xml_blocks`. Mutates `accumulated_msg.tool_calls`/`content` and `messages[-1]` in place. ~20 LOC extracted.

Post-refactor, the pre-iteration setup reads as `_loop_config = _resolve_loop_config(...)` → unpack into 6 local vars → `_tool_state = await _resolve_loop_tools(...)` → unpack into 5 local vars → `await _inject_opening_skill_nudges(...)`. The orchestrator dropped 929 → 809 LOC (~13% reduction); `loop_helpers.py` grew from 353 → 649 LOC (net +296 LOC across the pair is +176 LOC because the extractions lose some inline-local repetition — the helpers are strictly smaller than the original blocks they replaced). Cluster 6b adds the three fat extractions and brings the final orchestrator size to ~430 LOC (~54%, on par with Cluster 5).

**Why the dependency injection was necessary** — tests in `tests/unit/test_agent_loop.py::TestToolDispatchRouting` patch `app.agent.loop.get_local_tool_schemas`, `app.agent.loop.fetch_mcp_tools`, `app.agent.loop.get_client_tool_schemas`. Python's `patch("app.agent.loop.get_local_tool_schemas")` replaces the attribute on the `loop` module; if the helper in `loop_helpers.py` imported the same symbol directly from its source (`from app.tools.registry import get_local_tool_schemas`), the patch would be bypassed because the helper's closure would bind to the true function. An earlier attempt did exactly this and broke `test_local_tool_dispatched` and `test_mcp_tool_dispatched`. The fix: pass the patchable module-level references as kwargs, so test patches continue to reach the helper. Same pattern Cluster 5 used for `dispatch_tool_call_fn`.

**Verification (what ran):**
- `python -m py_compile app/agent/loop.py app/agent/loop_helpers.py` — clean.
- `pytest tests/unit/test_agent_loop.py tests/unit/test_loop_helpers.py tests/unit/test_loop_cycle_detection.py tests/unit/test_loop_tool_dedup.py`: **12 failed, 87 passed** — identical baseline. Verified via `git stash && pytest` before starting; the 12 pre-existing failures (cycle-detection harness issues + tool-dispatch routing + zero-completion retry) are all present on clean `development` HEAD.
- Neighbor sweep (`test_loop_core_gaps`, `test_loop_max_iterations_chain`, `test_loop_approval_race`, `test_loop_dispatch_sticky`): 4 failed, 41 passed. The 4 failures (`TestActivatedToolMerging` x3, `TestInLoopPruning` x1) are all pre-existing on clean HEAD — verified by stash-and-rerun.

**Non-goals (explicit):**
- No signature changes to `run_agent_tool_loop` — all 20+ callers in `loop.py` + `loop_dispatch.py` + Slack/Discord/BB renderer paths see identical behavior.
- No test changes. The pre-existing 12 baseline failures are Test Quality track items, not Cluster 6a's scope.
- No behavioural deltas: opening-nudge firing order, ContextVar seed timing (`current_activated_tools.set(activated_list)` still happens before the `logger.debug("Tools available...")` line), `logger.info` payload shape for activated-tool merges, tool-call recovery precedence (JSON before XML) are all byte-identical.

**Out of scope (parked as Cluster 6b — shipped 2026-04-24, see RFC below):**
- `_check_prompt_budget_guard` (~55 LOC) — combined context-window exceeded + TPM rate-limit gate. The helper would return a `PromptBudgetGate(events, should_return, wait_seconds)` dataclass so the caller can sequentially yield events, check the return flag, then optionally `await asyncio.sleep(wait_seconds)`. Mutates `messages` to append the error-assistant turn on window exceeded.
- `_handle_no_tool_calls_path` (~115 LOC) — async-generator extraction of the terminal no-tool-calls branch, including the forced-response retry path, secret redaction, `_synthesize_empty_response_fallback`, and `_finalize_response` delegation. Caller pattern: `async for _evt in _handle_no_tool_calls_path(...): yield _evt; return`.
- `_handle_loop_exit_forced_response` (~130 LOC) — async-generator extraction of the post-loop cycle/max-iterations forced-response branch. Needs a mutable `out_state: dict` parameter to signal "LLM errored during forced response, skip tool-enrollment flush" because the original code `return`s from `run_agent_tool_loop` entirely on that error — a contract that must be preserved.

### RFC — Cluster 6b — run_agent_tool_loop fat-block extractions (2026-04-24)

**Target**: The three Cluster 6a deferrals inside `run_agent_tool_loop` — pre-LLM budget gate (~63 LOC), terminal no-tool-calls branch (~111 LOC), post-loop forced-response branch (~125 LOC).

**Diagnosis**: Cluster 6a reached a clean seam after setup/recovery extraction but stopped at the three regions where extracting required async-generator helpers and (for the H14 error-path) a new termination contract. Each of the three blocks mixed LLM orchestration, event emission, `messages` mutation, trace recording, and in one case an error-path `return` that bypasses the post-loop tool-enrollment flush.

**Refactor** (one commit, behaviour-identical):

1. **`_check_prompt_budget_guard` → `PromptBudgetGate` sync helper**. Sync returns `PromptBudgetGate(events: list[dict], should_return: bool, wait_seconds: int)`. Events are already `_event_with_compaction_tag`-wrapped so the caller can `for _evt in gate.events: yield _evt` without re-wrapping. Context-window overage appends the refusal assistant turn to `messages` and fires the `ContextWindowExceeded` trace event *inside the helper* (mutation), then flags `should_return=True`. TPM wait sets `wait_seconds` > 0 and caller does `await asyncio.sleep(_gate.wait_seconds)`. Caller-side shape: 4 lines (loop-yield events → return-on-flag → sleep). The compound state flag (`should_return` + `wait_seconds`) was picked over an async-generator because the sole await in the block is the final `asyncio.sleep`, and the caller *has* to be the awaiter so the outer generator stays cooperative with cancellation.

2. **`_handle_no_tool_calls_path` → async generator**. Takes everything the no-tool-calls branch touched (22 kwargs including `accumulated_msg`, `messages`, buffers, bot/session context, `tools_param`, `fallback_models`, and most critically `llm_call_fn=_llm_call`). Yields `warning` / `error` / `response` events, delegates to `_finalize_response` and re-yields its returned events. Caller pattern is the planned `async for _evt in _handle_no_tool_calls_path(...): yield _evt; return`.

3. **`_handle_loop_exit_forced_response` → async generator + `out_state` termination signal**. Same kwarg pattern plus `out_state: dict` and `llm_call_fn`. On the LLM error branch, after yielding the error + response events, sets `out_state["terminated"] = True` and `return`s from the helper (only exits the inner generator). Caller checks `if _forced_out_state.get("terminated"): return` before the tool-enrollment flush at the end of the outer `try:` block. The `out_state` dict is the minimum-surface signal for "LLM errored during forced response" — a dataclass would have been clearer for a multi-flag contract, but the one-bit termination flag doesn't pay the abstraction cost.

Post-refactor, the three call sites in `run_agent_tool_loop` read as:

```python
# Pre-LLM budget gate (was ~63 LOC)
_budget_gate = _check_prompt_budget_guard(messages=messages, tools_param=tools_param, ...)
for _evt in _budget_gate.events:
    yield _evt
if _budget_gate.should_return:
    return
if _budget_gate.wait_seconds:
    await asyncio.sleep(_budget_gate.wait_seconds)

# No-tool-calls terminal branch (was ~111 LOC)
if not accumulated_msg.tool_calls:
    async for _evt in _handle_no_tool_calls_path(..., llm_call_fn=_llm_call):
        yield _evt
    return

# Post-loop forced response (was ~125 LOC)
_forced_out_state: dict = {}
async for _evt in _handle_loop_exit_forced_response(..., out_state=_forced_out_state, llm_call_fn=_llm_call):
    yield _evt
if _forced_out_state.get("terminated"):
    return
```

**Why dependency injection for `_llm_call`**: tests patch `app.agent.loop._llm_call` (3 patches in `test_agent_loop.py`: forced-final-call tests). If the helper did `from app.agent.llm import _llm_call` internally, the patches would be bypassed. Injecting `llm_call_fn=_llm_call` (passing the module-level `loop.py` reference) means patches continue to intercept. Same pattern as Cluster 5's `dispatch_tool_call_fn=dispatch_tool_call` and Cluster 6a's schema-fetch callables. Verified by running the 3 affected tests and confirming they still pass (they're in the 87 passing / 12 baseline-failing split).

**Verification (what ran):**
- `python -c "from app.agent.loop import run_agent_tool_loop"` — clean (the pre-existing `ToolResultEnvelope` circular warning is unchanged).
- `ast.parse` on both files — clean.
- Focused suite `test_agent_loop + test_loop_helpers + test_loop_cycle_detection + test_loop_tool_dedup` via Docker: **12 failed, 87 passed** — identical to Cluster 6a baseline (and to clean HEAD). The 12 pre-existing fails are the same cycle-detection + zero-completion-retry tests flagged in Cluster 6a's session log; fixing them is a Test Quality item, not Cluster 6b's scope.
- Neighbor sweep `test_loop_core_gaps + test_loop_max_iterations_chain + test_loop_approval_race + test_loop_dispatch_sticky + test_cancellation + test_parallel_tool_execution`: **4 failed, 63 passed**. The 4 fails (`TestActivatedToolMerging` x3, `TestInLoopPruning` x1) are pre-existing on HEAD — verified via Cluster 6a session log which already identified them as baseline.

**Non-goals (explicit):**
- No signature changes to `run_agent_tool_loop`.
- No test changes. No behaviour changes beyond the dataclass/out_state plumbing that is itself internal.
- No behavioural deltas: event-ordering (warning before response → error → response), `messages.pop()` / `messages.append()` sequencing for the empty-response branch, trace-event firing order, post-loop tool-enrollment flush gating (only runs on success path) are all byte-identical.

**Out of scope (parked for future clusters):**
- Further shrinking `run_agent_tool_loop` below 591 LOC. What's left is cohesive per-iteration orchestration (cancellation checks, LLM streaming with retry/fallback events, AccumulatedMessage persistence, token-usage tracing, thinking-content buffering, tool-call recovery + dispatch, iteration-injected-image handling, skill-nudge, cycle detection). Further reduction would either mean cross-iteration state objects (LoopIterationState, LoopOutputState) — which is Ousterhout-orthogonal deepening — or splitting the single-LLM-call per iteration into its own helper, which drags in too many locals.
- **Cluster 7 — `assemble_context` (1500 LOC) in `context_assembly.py`**. Next highest payoff, now that loop.py is materially smaller.
- **Test Quality Track item**: the 12 baseline failures in `test_agent_loop.py` have now survived through Clusters 5, 6a, and 6b — they're pre-existing on HEAD and warrant a focused investigation session.
