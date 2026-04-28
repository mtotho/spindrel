---
tags: [agent-server, track, code-quality]
status: active
created: 2026-04-09
updated: 2026-04-28 (Loop recovery/no-tool seam shipped; track stays ambient per `feedback_living_tracks_never_close`)
---
# Track — Code Quality & Refactoring

Systematic audit of core agent-server files. 156 files, ~50K lines across `app/agent/`, `app/services/`, `app/tools/`. Findings organized by priority.

## Audit close-out roadmap (planned 2026-04-24)

After Cluster 10 shipped, planned the remaining slate as one sequenced close-out: Cluster 9 (`run_task` 657 LOC) + 3 secondary duplications (llm closures, sandbox exec, knowledge dual-lookup) + 2 god-functions (`_bot_row_to_config` 283 LOC, `persist_turn` 333 LOC) + 1 test fixture single-liner. Order: easy wins first → hardest last. Per `feedback_opus_plans_sonnet_executes`, each cluster is a separate Sonnet execution session; do not batch in the same session as planning.

Per `feedback_living_tracks_never_close`: when this slate ships, do NOT flip `status: complete`. Compress prose in place; Track stays evergreen for ambient maintenance.

| # | Name | Target | Result | Status |
|---|---|---|---|---|
| **Pre-11** | Test fixture fix | `tests/unit/test_file_sync.py:240-249` | +1 line `as embed`; 8 sync_all tests unblocked (10/18 → 18/18) | ✅ SHIPPED |
| **11** | knowledge dedup (verify-first) | track claim stale | `knowledge.py` deleted in commit `e0b448c7` (2026-04-16); duplication moot | ✅ MOOT |
| **12** | `llm.py` factory closure unify | `app/agent/llm.py:1391-1565` | 6 closures → 1 builder `_build_attempt_factories(stream: bool)`; file 1781 → 1768 LOC; 326/7 baseline match | ✅ SHIPPED |
| **13** | `sandbox.py` exec / exec_bot_local | `app/services/sandbox.py:319, 754` | 3 helpers (`_build_docker_exec_args`, `_run_docker_exec`, `_touch_instance_last_used`); exec 95 → ~20 LOC, exec_bot_local 90 → ~20 LOC; file 907 → 898 LOC; 25/25 baseline match | ✅ SHIPPED |
| **14** | `_bot_row_to_config` decomposition | `app/agent/bots.py:295` | 5 nested-config builders + 2 repetitive-field mappers; function 189 → 64 LOC (-66%); file 821 → 841 LOC; 103/1 baseline match | ✅ SHIPPED |
| **15** | `persist_turn` decomposition | `app/services/sessions.py:562` | 6 stage helpers (filter/metadata/insert/outbox-channel/outbox-thread/attachment-link/bus-publish); function 331 → 82 LOC (-75%); file 1341 → 1398 LOC; 16+442/5/2 baseline match | ✅ SHIPPED |
| **15.1** | `persist_turn` typed seam follow-up (Ousterhout deepening audit candidate #5) | `app/services/sessions.py` + new `app/services/session_writes.py` | `_build_message_metadata` + `_insert_message_records` collapsed into one public function `stage_turn_messages(db, ctx, messages) -> TurnWriteResult` (frozen `TurnContext` collapses 9 kwargs → 1; `TurnWriteResult` replaces 3-tuple). Silent `JSONDecodeError`/`TypeError` swallow at delegation parse → logged WARNING with session/correlation/tool_call_id/preview, malformed entry skipped, well-formed siblings preserved. Non-object JSON also handled. sessions.py 1398 → 1278 LOC; new module 268 LOC. 91/22 baseline match + 3 new regression tests in `tests/unit/test_sessions_core_gaps.py::TestStageTurnMessagesMalformedDelegations` (94/22 final). Bug class shipped to [[Fix Log]] 2026-04-25. | ✅ SHIPPED |
| **9** | `run_task` Wave A-C | `app/agent/tasks.py:774` | Wave A+B kept the specialized-runner/error helpers. Wave C added a typed task-run seam: `_PreparedTaskRun`, `_prepare_task_run`, `_run_harness_task_if_needed`, and `_run_normal_agent_task`. `run_task` now owns dispatch/lock/start-event/error orchestration while preparation, harness invocation, and normal agent persistence/dispatch/follow-up policy are local to the helper modules. Function 657 → 178 LOC overall after Wave C; local verification: task unit slice 23/18, integration task file skipped under local profile. | ✅ SHIPPED |

## Maintenance pass (2026-04-28)

- **Context preview consolidation shipped.** `admin_channel_context_preview` no longer rebuilds prompt composition in the router. It now validates channel existence, calls runtime `assemble_for_preview`, and delegates response shaping to `app.services.context_preview.build_context_preview_response`. The adapter may split the already-assembled base system prompt for display labels, but does not reconstruct prompt policy.
- **Context breakdown runtime seam shipped.** `compute_context_breakdown` now gets static/runtime-injected categories from `assemble_for_preview` via the shared preview-block adapter instead of manually reconstructing global/workspace/bot prompts, memory files, skills, tools, widgets, section indexes, and workspace RAG estimates. The breakdown module still owns DB diagnostics: gross conversation size, pruning savings, compaction state, reranking state, effective settings, and last-turn API usage reconciliation. `assemble_for_preview` accepts optional `session_id`/`db` so scratch-session breakdowns can use the same runtime path without leaving the request DB context.
- **`run_task` Wave C shipped.** The deferred agent-run-path extraction proved viable as an internal typed seam instead of a broad new public interface. `run_task` remains the task worker coordinator, but the hidden implementation now has locality around task-run preparation, harness-backed execution, and normal-agent persistence/dispatch/follow-up behavior.
- **Pending request rendezvous seam shipped.** `app.agent.pending` and `app.agent.approval_pending` now share one `PendingRegistry` implementation while preserving their existing wrapper Interfaces and `_pending` monkeypatch points. Client-tool timeout handling now discards timed-out request futures so the registry cannot leak stale entries; approval cancel/resolve behavior is unchanged.
- **Readonly tool returns-schema baseline restored.** Added schemas for `describe_canvas_neighborhood`, `inspect_nearby_spatial_object`, `view_spatial_canvas`, and `widget_version_history`; `tests/unit/test_tool_returns_schema_coverage.py` is green again.
- **Context assembly state seam shipped.** `assemble_context` now carries budget/admission accounting through `AssemblyLedger` and cross-stage outputs through `AssemblyStageState` instead of closure pairs plus ad hoc `out_state` dicts. Memory/channel/workspace/bot-KB/tool-retrieval helpers now expose typed in-file Interfaces. The pass also caught and fixed a real extraction leak: `_inject_channel_workspace` now receives `model_override` / `provider_id_override` explicitly instead of reading vanished outer-scope names.
- **Loop run state seam shipped.** `run_agent_tool_loop`, `loop_dispatch`, and response-finalization helpers now share `LoopRunContext` for stable run identifiers/flags and `LoopRunState` for mutable turn state. The change collapses the wide helper signatures for no-tool finalization, post-loop forced responses, and per-iteration dispatch while preserving public loop entrypoints and the `LoopDispatchState` compatibility alias.
- **Loop LLM iteration stage seam shipped.** Provider streaming, retry/fallback trace persistence, before/after LLM hooks, fallback telemetry, message append, token-usage accounting, and thinking-content accumulation now live behind `stream_loop_llm_iteration` / `LoopLlmIterationDone` in `app.agent.loop_llm`. `run_agent_tool_loop` keeps the orchestration path and passes dependencies explicitly so existing loop patch surfaces remain intact.
- **Loop tool-iteration stage seam shipped.** Post-LLM tool-call iteration handling now lives behind `stream_loop_tool_iteration` / `LoopToolIterationDone` in `app.agent.loop_tool_iteration`. The seam owns audio transcript emission on tool-call responses, intermediate assistant text/redaction/transcript updates, per-iteration tool dispatch, cancellation propagation, injected image follow-up context, pressure-triggered in-loop pruning events, skill nudges, and cycle-break decisions. `run_agent_tool_loop` now treats it as a bounded stage and keeps only orchestration/control-flow wiring.
- **Loop exit/finalization seam shipped.** Post-loop forced-response dispatch, success-path tool-enrollment telemetry, and error-path `after_response`/trace cleanup now live behind `stream_loop_exit_finalization` and `schedule_loop_error_cleanup` in `app.agent.loop_exit`. The existing forced-response helper remains injected to preserve behavior, while the coordinator now treats loop exit as one bounded stage and no longer owns success telemetry or error cleanup details.
- **Loop pre-LLM iteration seam shipped.** Cancellation before provider calls, mid-loop tool activation merging, heartbeat soft-budget pressure pruning, normal pressure-triggered in-loop pruning, first-iteration context-breakdown trace, and prompt-budget/rate-limit gating now live behind `stream_loop_pre_llm_iteration` / `LoopPreLlmIterationDone` in `app.agent.loop_pre_llm`. The coordinator now receives updated `tools_param` / `tool_choice` plus explicit return/continue control flags before entering the LLM stage.
- **Loop setup seam shipped.** Loop config resolution, tool schema resolution, run-control policy normalization, hard-cap handling, heartbeat `tool_surface_summary` emission/trace, `LoopRunContext` / `LoopRunState` creation, provider resolution, and opening skill nudges now live behind `stream_loop_setup` / `LoopSetupDone` in `app.agent.loop_setup`. `run_agent_tool_loop` is now a staged coordinator: setup -> pre-LLM -> LLM -> recovery/no-tool/tool-iteration -> exit.
- **Loop recovery/no-tool seam shipped.** Text-encoded tool-call recovery and the terminal no-tool branch now live behind `stream_loop_recovery` / `LoopRecoveryDone` in `app.agent.loop_recovery`. The coordinator now treats the LLM result as either recovered tool calls for the tool-iteration stage or a terminal no-tool response path.
- **Next section candidate.** Persona remains deferred as low-leverage/removable. The live-loop god function is now materially reduced and staged; next architecture review should use a fresh verify-first scan for the next high-risk module rather than continuing to split small loop utilities.

**Drift caught during planning** (track entries proved stale):
- `_bot_row_to_config` claimed ~180 LOC, actually 283.
- `persist_turn` claimed ~150 LOC, actually 333.
- `tasks.py` "mark task failed" claimed 4× duplication, actually 8× (lines 656, 680, 767, 816, 1371, 1400, 1416, 1491).
- `knowledge.py:240-370` dual-lookup — module not found at planning time; needs verify-first pass before scoping Cluster 11.

**Cross-cluster discipline** (same as Clusters 5-8, 10):
- One commit per cluster, behavior-preserving; baseline-FIRST exact-match.
- In-file helpers (preserves test-patch surfaces).
- Helpers raise; callers wrap.
- Vault same-edit (Track row + RFC + session log + Loose Ends entries).
- `mirror-agent-server-docs-bulk.sh` after vault edits.
- Per `feedback_targeted_test_runs`: scoped pytest, never `pytest tests/ integrations/` in Docker.
- Per `feedback_git_workflow`: agent-server uses manual commit; commit only when user directs.

**Detail per cluster** lives at `~/.claude/plans/woolly-tumbling-robin.md` (ephemeral scaffolding — refer to it when starting an execution session, but the durable status table is here).

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
| context_assembly.py | `assemble_context()` | ~~1400~~ ~~990~~ ~~1490~~ ~~1341~~ ~~1211~~ ~~898~~ ~~740~~ ~~654~~ ~~498~~ ~~441~~ **357** (file: ~~2730~~ ~~2857~~ ~~2963~~ ~~3013~~ ~~3047~~ ~~3083~~ ~~3122~~ ~~3167~~ **3220**) | **✅ CLUSTER 7 COMPLETE.** 16 in-file helpers extracted across 7a-7e-d covering all 33 pipeline stages. Cumulative 1490 → 357 LOC (**-76%**). Final sub-cluster 7e-d shipped Stages 30-33 finalization traces helper (105 LOC → 20 LOC caller). `assemble_context` is now a readable top-to-bottom driver: each `# --- stage ---` divider marks a helper call, and stages that aren't yet helpers (channel workspace, conversation sections, RAG, bot KB, plan artifact, memory scheme) already had their own inline helpers pre-Cluster 7. |
| loop.py | `run_agent_tool_loop()` | ~~960~~ ~~1030~~ ~~809~~ **591** (file: ~~**1684**~~ ~~1358~~ **1136**) | Clusters 6a+6b shipped. 929 → 591 LOC (-36%). Remaining 591 LOC is cohesive per-iteration orchestration (cancellation checks, LLM streaming, dispatch, image injection, skill-nudge, cycle detection) — further reduction needs cross-iteration state objects, not more extractions. |
| file_sync.py | `sync_all_files()` + `sync_changed_file()` | ~~333~~ **159** + ~~180~~ **60** (file: ~~851~~ **908**) | **✅ CLUSTER 10 SHIPPED.** 8 in-file stage helpers (`_log_action`, `_upsert_skill_row`, `_build_prompt_template_fields`, `_upsert_prompt_template_row`, `_upsert_workflow_row`, `_delete_orphan_skills`, `_delete_orphan_prompt_templates`, `_delete_orphan_workflows`, `_delete_rows_by_source_path`) collapse the sync_all/watch duplication. sync_all_files 333 → 159 (-52%); sync_changed_file 180 → 60 (-67%). `log_path: Path \| None` toggles watch vs sync_all logging + sync_all-only branches (manual-skip on workflows, source-drift fix on unchanged). |
| tasks.py | `run_task()` | ~~~490~~ ~~657~~ **596** (file: ~~1712~~ **1729**) | **✅ CLUSTER 9 (Wave A+B) SHIPPED.** Three helpers extracted: `_mark_task_failed_in_db` (DB-only mark-failed write — collapses 5 of 8 inline copies; rate-limit retry branch and `recover_stuck_tasks` keep their inline writes because they touch other state in the same session), `_publish_turn_ended_safe` (try/except wrapper around `_publish_turn_ended` — collapses 4 inline copies), `_dispatch_to_specialized_runner` (returns True if task was routed to exec/pipeline/workflow_trigger/claude_code; pulls ~50 LOC of branching out of `run_task`'s prologue). Function 657 → 596 LOC (-9%). Heavier deep-extraction of the agent-run path deferred — surface is too test-coupled to attempt without dedicated test refactor. Behavior-preserving: 103 task tests passed (exact baseline match). |
| tool_dispatch.py | `dispatch_tool_call()` | ~385 | auth, policy, approval, routing, recording, redaction, summarization |
| compaction.py | `run_compaction_stream()` | ~~342~~ ~~363~~ **177** + `run_compaction_forced()` ~~254~~ **106** (file: ~~2653~~ **2637**) | **✅ CLUSTER 8 SHIPPED.** 5 in-file stage helpers (`_run_memory_flush_phase`, `_compute_compaction_watermark`, `_persist_section_and_summary`, `_persist_session_compaction_state`, `_record_compaction_completion`) collapse the stream/forced duplication. Stream 361 → 177 (-51%); forced 248 → 106 (-57%). Both wrappers now linear drivers. |
| bots.py | `_bot_row_to_config()` | ~~~180~~ ~~283~~ **64** (file: ~~821~~ **841**) | **✅ CLUSTER 14 SHIPPED.** 5 nested-config builders (`_build_filesystem_indexes`, `_build_host_exec_config`, `_build_filesystem_access`, `_build_bot_sandbox_config`, `_build_workspace_config`) + 2 repetitive-field mappers (`_HYGIENE_FIELDS`, `_SKILL_REVIEW_FIELDS` consumed via `_map_optional_attrs`) collapse the inline construction. Function 189 → 64 LOC (-66%). Behavior-preserving: 103 passed / 1 pre-existing fail (exact baseline match). |
| sessions.py | `persist_turn()` | ~~~150~~ ~~331~~ **82** (file: ~~1341~~ **1398**) | **✅ CLUSTER 15 SHIPPED.** 6 in-file stage helpers (`_filter_messages_to_persist`, `_build_message_metadata`, `_insert_message_records`, `_enqueue_outbox_for_channel`, `_enqueue_outbox_for_thread`, `_link_orphan_attachments`, `_publish_persisted_messages_to_bus`) collapse the persistence pipeline. Function 331 → 82 LOC (-75%). Behavior-preserving: 16 focused passed + 442/5/2 broader sweep (exact baseline match). |

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

### ~~llm.py:1071-1226 — Streaming vs non-streaming factory closures~~ FIXED 2026-04-24 (Cluster 12)
Unified into a single module-level `_build_attempt_factories(*, messages, tools_param, tool_choice, stream: bool)` that returns `(_make_attempt, _make_no_tools, _make_no_images)`. `stream=True` adds `stream=True` + `stream_options` + per-attempt info log; `stream=False` runs post-call `EmptyChoicesError` validation and `record_usage`. Both `_llm_call_stream` and `_llm_call` now call the builder once and pass the closures into `_run_with_fallback_chain`. Behavior-preserving: 326 passed / 7 pre-existing fails (exact baseline match). File 1781 → 1768 LOC; ~150 LOC of duplication collapsed into a 70-LOC builder.

### ~~compaction.py:830-1474 — Stream vs forced compaction~~ FIXED 2026-04-24 (Cluster 8)
Extracted 5 in-file stage helpers (`_run_memory_flush_phase`, `_compute_compaction_watermark`, `_persist_section_and_summary`, `_persist_session_compaction_state`, `_record_compaction_completion`) that both wrappers now drive sequentially. ~250 LOC of duplicated pipeline collapsed; commit boundaries preserved (stream commits internally, forced lets caller commit). Behavior-preserving: focused 7-file suite 157 passed / 2 pre-existing fails (exact baseline match).

### ~~file_sync.py:241-1041 — Full sync vs watch handler~~ FIXED 2026-04-24 (Cluster 10)
Extracted 8 in-file stage helpers (3 upsert + 3 orphan-delete + 1 path-delete + 1 log-formatter). `log_path: Path | None` kwarg threads watch vs sync_all variants of log lines and behavior (sync_all-only manual-workflow skip, source-drift fix on unchanged). ~250 LOC of duplicated per-resource-type upsert logic collapsed; both wrappers now linear drivers. Behavior-preserving: focused 3-file suite 34 passed / 8 pre-existing fixture errors (exact baseline match).

### ~~sandbox.py:319-844 — `exec` vs `exec_bot_local`~~ FIXED 2026-04-24 (Cluster 13)
Extracted three module-level helpers: `_build_docker_exec_args(*, bot_id, user=None)` builds the leading `docker exec` argv with server URL + per-bot API key + scoped secret injection (best-effort try/except preserved); `_run_docker_exec(exec_args, *, timeout_secs, max_bytes, start_ts)` runs the subprocess with timeout-shaped `ExecResult` and output truncation; `_touch_instance_last_used(instance_id)` bumps `last_used_at` in its own commit. `exec` (95 LOC) and `exec_bot_local` (90 LOC) collapsed to ~20 LOC each. Behavior-preserving: 25 sandbox tests passed (exact baseline match). File 907 → 898 LOC.

### ~~knowledge.py:240-370 — Dual-lookup pattern 5x~~ MOOT 2026-04-24 (Cluster 11 verify-first)
Module removed by commit `e0b448c7` (2026-04-16, "deprecated knowledge system removal"). No `knowledge.py` exists anywhere in `app/` or `integrations/`; only residual reference is `app/services/memory_scheme.py` mentioning the removed surface in passing. Duplication self-resolved with the legacy system retirement; no extraction needed.

### ~~tasks.py:376-981 — "Mark task failed" pattern 4x (actually 8×)~~ FIXED 2026-04-24 (Cluster 9)
Original audit undercounted: 8 inline copies of fetch → set status → commit, not 4. Extracted `_mark_task_failed_in_db(task_id, *, error, completed_at=None)`; replaced 5 of 8 copies (run_exec_task TimeoutError + Exception, _run_workflow_trigger_task Exception, run_task TimeoutError + Exception, plus the claude_code-import-error fallback inside `_dispatch_to_specialized_runner`). Two skipped: rate-limit max-retries branch (in-place mutation of an already-open session that touches retry_count/scheduled_at), and `recover_stuck_tasks` (status=='running' guard + workflow-task hook-skip branching). `_publish_turn_ended_safe` separately collapses 4 try/except publish blocks.
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
- **Cluster 7 — `assemble_context` (1490 LOC) in `context_assembly.py` — ✅ COMPLETE 2026-04-24.** Eight sub-clusters shipped same day covering all 33 pipeline stages:
  - 7a ✅ (5 setup-stage helpers, 1490 → 1341 LOC)
  - 7b ✅ (4 discovery-stage helpers, 1341 → 1211 LOC)
  - 7c ✅ (Stage 9 skills helper, 1211 → 898 LOC)
  - 7d ✅ (Stage 18 tool-retrieval helper, 898 → 740 LOC — cumulative -50%)
  - 7e-a ✅ (Stages 19+20+21 tool-exposure finalization helper, 740 → 654 LOC)
  - 7e-b ✅ (Stages 22+23+24 + context_profile_note late cache-safe injections helper, 654 → 498 LOC — under 500)
  - 7e-c ✅ (Stages 25-29 message assembly helper, 498 → 441 LOC)
  - 7e-d ✅ (Stages 30-33 finalization traces helper, 441 → 357 LOC — **cumulative -76%**)
  
  Same-day baseline exact-match across 8 cluster runs (11 failed, 71 passed, 1 skipped in focused suite). Zero regressions. `assemble_context` is now a readable top-to-bottom driver where each `# --- stage ---` divider marks a helper call.
- **Widget envelope triple-rebuild reconciliation** (`native_app_widgets.py:753` + `widget_contracts.py:406` + `dashboard_pins.py:269`) — Hybrid C+B design plan accepted 2026-04-27 (`~/.claude/plans/we-need-an-in-sparkling-sparrow.md`). Phased rollout:
  | Phase | Scope | Status |
  |---|---|---|
  | 1 | Additive: new `app/services/pin_contract/` package (5 OriginResolvers, resolver-backed public functions, initial `compute_pin_source_stamp` helper); migration 264 adds `widget_dashboard_pins.source_stamp TEXT NULL`; write paths populate stamps; `list_pins` unchanged | ✅ shipped 2026-04-27 (session log `Sessions/agent-server/2026-04-27-P-pin-contract-deepening-phase-1.md`) |
  | 2 | Backfill script `scripts/backfill_pin_source_stamps.py`: stamp NULL rows + `--verify` parity dry-run between new resolver chain and legacy `build_pin_contract_metadata` (Phase 3 readiness gate) | ✅ shipped 2026-04-27 (session log `Sessions/agent-server/2026-04-27-Q-pin-contract-deepening-phase-2.md`) |
  | 2.5 | Parity fixture suite `tests/unit/test_pin_contract_parity.py` — 9 parametrized origin shapes + render-vs-legacy test. Surfaced 4 real bugs in the new resolver chain (PresetRegistry didn't catch `NotFoundError`; `_resolve_library_widget_dir` crashed on missing bot; `HtmlRuntimeEmitResolver` always returned `runtime_emit` instead of `direct_tool_call`; `_fold_with_snapshot` missing presentation defaults). All fixed; 10/10 parity tests + 76 adjacent suite tests green | ✅ shipped 2026-04-27 (session log `Sessions/agent-server/2026-04-27-R-pin-contract-deepening-phase-2-5-parity-gate.md`) |
  | 3 | `list_pins` flip — `serialize_pin` calls `render_pin_metadata` for fully-stamped rows (column-only, zero IO); `compute_pin_metadata` fallback for un-stamped stragglers. `list_pins` per-row blanket reconcile narrowed to un-stamped rows. `create_pin` / `update_pin_envelope` / `update_pin_scope` / `get_pin` flipped from legacy `build_pin_contract_metadata` + side-call `compute_pin_source_stamp` to single `compute_pin_metadata` + `apply_to_pin` (or `reconcile_pin_metadata`). Hot-path regression test (`tests/unit/test_pin_contract_hot_path.py`) raises if any registry / manifest / template is touched on a stamped read. Legacy helpers retained as parity oracle until Phase 4. | ✅ shipped 2026-04-27 (session log `Sessions/agent-server/2026-04-27-S-pin-contract-deepening-phase-3-flip.md`) |
  | 4 | Collapse legacy `build_pin_contract_metadata` / `infer_pin_origin` / `build_public_fields_from_origin` and delete the parity oracle; remove `compute_pin_source_stamp`; convert `scripts/backfill_pin_source_stamps.py` into a `pin_contract` drift scanner/repair helper; start a bounded background drift worker from lifespan | ✅ shipped 2026-04-28 (session log `Sessions/agent-server/2026-04-28-A-chat-ui-ux-polish.md`) |
  
  **Outcome**: `app.services.pin_contract` is now the owning Module and `widget_contracts.py` keeps only lower-level contract builders/manifest lookup helpers. The old pin-specific Interface (`build_pin_contract_metadata`, `infer_pin_origin`, `build_public_fields_from_origin`, `build_public_fields_for_pin`) and stamp-only helper (`compute_pin_source_stamp`) are gone. `tests/unit/test_pin_contract_parity.py` now asserts final contract shapes directly instead of comparing two Implementations. Stamp model: unified `sha256(widget.yaml || NUL || html body)` for every HTML widget scope; native uses `instance.state["updated_at"]`; preset uses integration `content_hash`.
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
- **Cluster 7 — `assemble_context` (1490 LOC) in `context_assembly.py`**. Cluster 7a shipped 2026-04-24 — see RFC below.
- **Test Quality Track item**: the 12 baseline failures in `test_agent_loop.py` have now survived through Clusters 5, 6a, and 6b — they're pre-existing on HEAD and warrant a focused investigation session.

### RFC — Cluster 7a — assemble_context setup-stage extractions (2026-04-24)

**Target**: `assemble_context` at `app/agent/context_assembly.py:1136` — 1490 LOC, the largest remaining god function after Cluster 6b brought `run_agent_tool_loop` to 591 LOC. The function has 32 active `# --- stage ---` dividers; six helpers (`_inject_plan_artifact`, `_inject_memory_scheme`, `_inject_channel_workspace`, `_inject_conversation_sections`, `_inject_workspace_rag`, `_inject_bot_knowledge_base`) were already extracted above it. Cluster 7a is the first narrow-scope follow-up, targeting the setup stages (1-4 + 10) that run before RAG injection.

**Diagnosis**: the "discovery + setup" phase at the top of `assemble_context` mixes five cohesive concerns with clean boundaries: channel-row load + skill-enrollment peek (Stage 1), turn-boundary context pruning (Stage 2), base+history token accounting + channel-layered effective-tool resolution + channel-override mirror to `result` (Stage 3), Phase-3 skill-enrollment loading with `_merge_skills` side-effect on `bot` (Stage 4), and scoped-API-key tool injection (Stage 10). Together these were ~200 LOC of inline code whose only shared state with downstream stages is a handful of locals (`_ch_row`, `_enrolled_ids`, `_source_map`) plus the replaced `bot`. Extraction is low-risk because each stage has well-defined inputs/outputs and no mid-stage awaits that require cross-stage buffering.

**Refactor** (one commit, behaviour-identical):

1. **`_load_channel_overrides(*, channel_id) -> Channel | None`** — async. Loads the `Channel` row with `selectinload(Channel.integrations)` + `ChannelSkillEnrollment.skill_id` in a single `async_session()`, stamps `_channel_skill_enrollment_ids` onto the row, returns the row (or `None` on missing channel / load failure). Lazy imports `sqlalchemy.select`, `sqlalchemy.orm.selectinload`, `app.db.engine.async_session`, `app.db.models.Channel + ChannelSkillEnrollment`.

2. **`_run_context_pruning(*, messages, bot, ch_row, inject_chars, correlation_id, session_id, client_id) -> AsyncGenerator[dict, None]`** — async generator. Resolves pruning enabled / min-length from the global→bot→channel cascade, returns early when disabled, otherwise calls `prune_tool_results` (lazy import), yields the `context_pruning` event, fires the trace task. Mutates `messages` and `inject_chars["context_pruning_saved"]` in place.

3. **`_apply_effective_tools_and_budget(*, messages, bot, ch_row, budget, result) -> BotConfig`** — sync (no awaits). Walks `messages` to split base-context vs conversation-history tokens, consumes them against the budget, resolves the channel-layered effective tool set via `resolve_effective_tools` + `apply_auto_injections`, returns the replaced `bot`. Copies channel-side model/iteration/fallback overrides onto `result` (in place). Kept the if/else split (channel present vs absent) intact — the no-channel path still calls `apply_auto_injections` on a fresh `EffectiveTools(list(bot.*))`.

4. **`_load_skill_enrollments(*, bot, out_state) -> AsyncGenerator[dict, None]`** — async generator + `out_state: dict` termination/result pattern. Sets `out_state["bot"]` (replaced BotConfig), `out_state["enrolled_ids"]`, `out_state["source_map"]` as defaults at entry; returns early if `bot.id` is falsy. Otherwise calls the module-level `_get_bot_authored_skill_ids` (so tests patching `app.agent.context_assembly._get_bot_authored_skill_ids` continue to intercept), lazy-imports `enroll_many` / `get_enrolled_skill_ids` / `get_enrolled_source_map` from `app.services.skill_enrollment`, yields `bot_authored_skills_enrolled` and `enrolled_skills` events, calls module-level `_merge_skills` to roll the enrolled skill ids into `bot`, and writes the final state to `out_state`. Out-dict pattern is the same as Cluster 6b's `_handle_loop_exit_forced_response` — used because an async generator can't both yield events and return a value.

5. **`_inject_api_access_tools(*, messages, bot) -> tuple[BotConfig, dict | None]`** — sync. No-op branch (`bot.api_permissions` falsy) returns `(bot, None)`. Otherwise appends `list_api_endpoints` and `call_api` to `bot.local_tools` + `bot.pinned_tools` (with `dict.fromkeys` de-dupe on pinned), appends the scoped-API system message, returns the replaced bot and the `api_access_tools` event dict.

Post-refactor, the five call sites in `assemble_context` read as:

```python
# Stage 1
_ch_row = await _load_channel_overrides(channel_id=channel_id)

# Stage 2
async for _evt in _run_context_pruning(messages=messages, bot=bot, ch_row=_ch_row, ...):
    yield _evt

# Stage 3
bot = _apply_effective_tools_and_budget(messages=messages, bot=bot, ch_row=_ch_row, budget=budget, result=result)

# Stage 4
_skill_state: dict = {}
async for _evt in _load_skill_enrollments(bot=bot, out_state=_skill_state):
    yield _evt
bot = _skill_state.get("bot", bot)
_enrolled_ids: list[str] = _skill_state.get("enrolled_ids", [])
_source_map: dict[str, str] = _skill_state.get("source_map", {})

# Stage 10
bot, _api_event = _inject_api_access_tools(messages=messages, bot=bot)
if _api_event:
    yield _api_event
```

LOC delta: `assemble_context` 1490 → 1341 (-149 LOC, ~10%). `context_assembly.py` file 2730 → 2857 (+127 LOC net — helpers added ~276 LOC, inline regions removed ~149 LOC). The per-helper size increase over raw inline is dominated by docstrings + keyword-only signature plumbing, which is intentional (follows the precedent of the 6 existing `_inject_*` helpers).

**Why helpers stay in-file** — tests in `tests/unit/test_assembly_budget.py` (lines 53, 221, 307, 345) and `tests/integration/test_context_assembly.py` (lines 523, 731, 1245, 1250) patch `app.agent.context_assembly._get_bot_authored_skill_ids`, `_all_tool_schemas_by_name`, `fetch_skill_chunks_by_id`, `retrieve_tools`. `patch("app.agent.context_assembly.X")` replaces the attribute on the module. Keeping helpers inside `context_assembly.py` (same precedent as the 6 existing `_inject_*` helpers) means those patches continue to work without any test edits. Moving helpers to a sibling file — as Cluster 6a/6b did for `loop_helpers.py` — would have required rewriting every patch path in both test files.

**Why no `_AssemblyCtx` dataclass** — explicitly rejected for 7a. Consolidating the two budget closures (`_budget_consume`, `_budget_can_afford`) plus `_inject_chars` / `_inject_decisions` / `bot` / `session_id` into a shared context dataclass would touch all 6 existing `_inject_*` helpers plus their tests. That's a larger-blast-radius refactor worth doing *after* all 32 stages are extracted, not during the extraction. Kwarg ceremony stays.

**Verification (what ran):**
- `python -c "import ast; ast.parse(open('app/agent/context_assembly.py').read())"` — clean.
- Focused baseline suite (9 files: `test_context_assembly`, `test_assembly_budget`, `test_memory_injection`, `test_bot_kb_auto_retrieve`, `test_channel_kb_auto_retrieve`, `test_context_assembly_widgets`, `test_channel_workspace_prompt`, `test_context_assembly_core_gaps`, `test_context_profile_note`) via Docker:
  - Pre-extraction baseline: **11 failed, 71 passed, 1 skipped** (failures are 8 in `test_memory_injection.py` + 3 in `test_channel_kb_auto_retrieve.py`, all pre-existing on clean HEAD).
  - Post-extraction: **11 failed, 71 passed, 1 skipped** — exact baseline match. Same files, same failures.
- Neighbor sweep `pytest tests/unit -k "context_assembly or assembly_budget or memory_injection or kb_auto or context_profile or channel_workspace"`: **11 failed, 131 passed**. Same 11 pre-existing failures, zero new regressions.

**Non-goals (explicit):**
- No signature changes to `assemble_context` — all callers (`loop.py`, `assemble_for_preview`, any external) see identical behavior.
- No test changes. No behaviour changes beyond the `out_state`/tuple plumbing that is itself internal.
- No byte-level divergence in event shape, pruning cascade, budget consumption, channel-override mirror to `result`, `_merge_skills` semantics, API-access injection order, or yield ordering.
- No fix for the 11 pre-existing baseline failures — unrelated to extraction, flagged for Test Quality.
- No `_AssemblyCtx` dataclass refactor (see rationale above).

**Out of scope (parked for future sub-clusters):**
- **Cluster 7b** — ✅ shipped 2026-04-24 (see RFC below).
- **Cluster 7c** — Stage 9 (skills working set + discovery + ranking, 346 LOC). Self-contained but large; has three internal closures (`_fmt_skill_line`, `_skill_category`, `_render_grouped_skill_lines`) that need to travel with the extraction. Dedicated session.
- **Cluster 7d** — Stage 18 (tool retrieval + policy gate, 182 LOC). Reads `_ch_row` + complex filtering logic; too much surface for a mixed cluster.
- **Cluster 7e** — Stages 22-34 (temporal framing, pinned widgets, refusal guard, channel prompt, preamble, user message, budget finalize, tracer emits). Homogeneous tail — all mutate `messages` + `result` + yield trace events. Batched after the fat blocks land.
- **`_AssemblyCtx` dataclass consolidation** — deferred until all stages are extracted.
- **4 `except Exception: pass` sites** in this file — separate quality sweep.

### RFC — Cluster 7b — assemble_context discovery-stage extractions (2026-04-24)

**Target**: four discovery-phase stages in `assemble_context` (`app/agent/context_assembly.py`) that share the `_tagged_*` / `_member_*` locals read by Stages 9 (skills), 12 (delegate index), and 18 (tool retrieval): Stage 7 (@mention tag resolution, ~65 LOC), Stage 8 (execution_config ephemeral skills, ~18 LOC), Stage 11 (multi-bot channel awareness, ~70 LOC), Stage 12 (delegate bot index, ~25 LOC). Post-7a starting point: `assemble_context` at 1341 LOC.

**Diagnosis**: the four stages collaborate through four shared locals (`_tagged_skill_names`, `_tagged_tool_names`, `_tagged_bot_names`, `_member_bot_ids`) that are consumed again at Stage 9 (`_tagged_skill_names | _untagged_ephemeral`), Stage 12 (`_tagged_bot_names + _member_bot_ids`), and Stage 18 (`_tagged_tool_names` in `_effective_pinned`). Extracting them as a batch is cleaner than one-at-a-time because the out_state dicts chain naturally and the dependency graph stays obvious to a top-to-bottom reader of the caller.

**Refactor**: four new module-level helpers in a `# ===== Cluster 7b discovery-stage extractions =====` header block positioned after the 7a block (just before `_inject_plan_artifact`):

1. `_resolve_tagged_mentions(*, messages, bot, user_message, client_id, session_id, correlation_id, result, out_state) -> AsyncGenerator[dict, None]` — async generator; calls `resolve_tags`, partitions by `tag_type`, mutates `result.tagged_tool_names` / `result.tagged_bot_names`, calls `set_ephemeral_delegates` / `set_ephemeral_skills` context-var setters, appends the "Tagged skill context" system message via `_build_tagged_skill_hint_lines`, yields `tagged_context` event + fires `_record_trace_event` task. Writes `tagged`, `tagged_skill_names`, `tagged_tool_names`, `tagged_bot_names` to out_state.
2. `_apply_ephemeral_skills(*, messages, bot, tagged_skill_names, out_state) -> None` — plain async (no yields). Reads `current_ephemeral_skills` ctxvar, filters against tagged set and `bot.skills`, calls module-level `fetch_skill_chunks_by_id` (patch-friendly), appends "Webhook skill context" system message. Writes `untagged_ephemeral` to out_state for Stage 9.
3. `_inject_multi_bot_awareness(*, messages, bot, channel_id, ch_row, system_preamble, out_state) -> AsyncGenerator[dict, None]` — DB load of `ChannelBotMember` via lazy sqlalchemy + db-models imports, builds participant lines with primary/member labels + self marker + config suffix, appends awareness system message with branching on `system_preamble` truthiness, yields `multi_bot_awareness`. Writes `member_bot_ids` / `member_configs` to out_state.
4. `_inject_delegate_index(*, messages, bot, tagged_bot_names, member_bot_ids) -> dict | None` — sync. Dedupes `bot.delegate_bots + tagged_bot_names + member_bot_ids`, lazy-imports `get_bot`, builds "Available delegates for delegate_to_agent" lines, appends system message. Returns `delegate_index` event or None for caller to yield.

Post-refactor caller shape:
```python
# --- @mention tag resolution ---
_tag_state: dict = {}
async for _evt in _resolve_tagged_mentions(
    messages=messages, bot=bot, user_message=user_message,
    client_id=client_id, session_id=session_id,
    correlation_id=correlation_id, result=result, out_state=_tag_state,
):
    yield _evt
_tagged = _tag_state.get("tagged", [])
_tagged_skill_names: list[str] = _tag_state.get("tagged_skill_names", [])
_tagged_tool_names: list[str] = _tag_state.get("tagged_tool_names", [])
_tagged_bot_names: list[str] = _tag_state.get("tagged_bot_names", [])

# --- execution_config ephemeral skills ---
_eph_state: dict = {}
await _apply_ephemeral_skills(
    messages=messages, bot=bot,
    tagged_skill_names=_tagged_skill_names, out_state=_eph_state,
)
_untagged_ephemeral: list[str] = _eph_state.get("untagged_ephemeral", [])

# (Stage 9 skills stays inline, pending Cluster 7c)
# (Stage 10 api access tools already extracted in 7a)

# --- multi-bot channel awareness ---
_mb_state: dict = {}
async for _evt in _inject_multi_bot_awareness(
    messages=messages, bot=bot, channel_id=channel_id,
    ch_row=_ch_row, system_preamble=system_preamble, out_state=_mb_state,
):
    yield _evt
_member_bot_ids: list[str] = _mb_state.get("member_bot_ids", [])
_member_configs: dict[str, dict] = _mb_state.get("member_configs", {})

# --- delegate bot index ---
_delegate_event = _inject_delegate_index(
    messages=messages, bot=bot,
    tagged_bot_names=_tagged_bot_names, member_bot_ids=_member_bot_ids,
)
if _delegate_event:
    yield _delegate_event
```

LOC delta: `assemble_context` **1341 → 1211** (-130, ~10%). File **2857 → 2963** (+106 net — helpers added ~236 LOC, inline regions removed ~178 LOC). Combined 7a+7b: assemble_context 1490 → 1211 LOC (-19%).

**Why in-file**: same rationale as 7a. Tests patch `app.agent.context_assembly.fetch_skill_chunks_by_id`, `_all_tool_schemas_by_name`, etc. at module level; moving the helpers would require rewriting every test's patch path.

**Why `out_state: dict` again**: async generators can't `return value` — `return` only exits the generator. Any helper that yields events _and_ needs to pass back state uses the out_state pattern. Four helpers' worth of chained out_states in the caller stays readable because the dict names are topic-scoped (`_tag_state`, `_eph_state`, `_mb_state`).

**Why sync `_inject_delegate_index`**: no awaits inside the underlying Stage 12 body (all sync dict/list work + sync `get_bot` lookup). Making it an async generator would add ceremony with no benefit.

**Verification**:
- Focused 9-file suite (same as 7a baseline): pre-extraction **11 failed, 71 passed, 1 skipped**; post-extraction **11 failed, 71 passed, 1 skipped** — exact match.
- Neighbor sweep `pytest tests/unit -k "context_assembly or assembly_budget or memory_injection or kb_auto or context_profile or channel_workspace"`: **11 failed, 131 passed, 7306 deselected**. Same 11 pre-existing fails, zero new regressions.

**Gotchas**:
- Dropped one no-op local (`_seen_delegate_ids: set[str]`) that was set but never read — confirmed unused via grep; behaviorally equivalent removal.
- `current_ephemeral_skills` is imported twice inline in the original (once in Stage 7 inside `if _tagged_skill_names:`, once at the top of Stage 8). Both got inlined into the respective helpers — no observable change.
- `_record_trace_event` task is preserved with `asyncio.create_task` fire-and-forget pattern exactly.

**Non-goals (explicit):**
- No signature changes to `assemble_context`.
- No test changes.
- No behaviour changes in event ordering, ctxvar side effects, or message append order.

**Out of scope (parked for future sub-clusters):**
- **Cluster 7c** — ✅ shipped 2026-04-24 (see RFC below).
- **Cluster 7d** — Stage 18 (tool retrieval + policy gate, 182 LOC).
- **Cluster 7e** — Stages 22-34 tail.

### RFC — Cluster 7c — assemble_context Stage 9 skills extraction (2026-04-24)

**Target**: Stage 9 (Phase-3 skill working set + semantic discovery + ranking + auto-inject) in `assemble_context` — the largest single stage at 346 LOC, with three internal closures (`_fmt_skill_line`, `_skill_category`, `_render_grouped_skill_lines`). Post-7b starting point: `assemble_context` at 1211 LOC.

**Diagnosis**: Stage 9 composes three independently-gated sub-layers — working-set metadata load + ranking, auto-inject into conversation history, and semantic discovery over unenrolled catalog skills — plus a `skill_index` trace yield at the end. The three internal closures are pure functions + reference-only use of `_resident_skill_ids`, so they travel cleanly into the helper as nested functions. Eight locals flow to the downstream active-skills snapshot trace (`_enrolled_rows`, `_suggestion_rows`, `_enrolled_ids`, `_ranked_relevant`, `_auto_injected`, `_auto_injected_similarities`, `_history_fetched_skills`, `_history_skill_records`), surfaced via out_state. One local — `_tool_discovery_info: {"tool_retrieval_enabled": False}` — was just a default init consumed by Stage 18, hoisted to the caller rather than passed through.

**Refactor**: one new module-level helper in a `# ===== Cluster 7c skills-stage extraction =====` block positioned after the 7b block (just before `_inject_plan_artifact`):

`_inject_skill_working_set(*, messages, bot, user_message, correlation_id, session_id, client_id, skip_skill_inject, tagged_skill_names, untagged_ephemeral, source_map, budget_can_afford, budget_consume, result, out_state) -> AsyncGenerator[dict, None]`

The helper walks the full Stage 9 flow: reverse-walks `messages` to identify `get_skill()` history residents + builds `_history_skill_records`, loads `Skill` rows for `bot.skills`, runs `rank_enrolled_skills` against last-3-turn query context, renders the working-set lines via `_render_grouped_skill_lines` (category-grouped when >=5 rows + >=2 categories, otherwise flat), appends the working-set system message with relevance-aware headers, runs the auto-inject loop gated by `skip_skill_inject`, `SKILL_ENROLLED_AUTO_INJECT_MAX`, `SKILL_ENROLLED_AUTO_INJECT_THRESHOLD`, `_INJECT_ELIGIBLE_SOURCES`, and `budget_can_afford`, yields per-skill `auto_inject` events, runs the discovery layer against unenrolled catalog rows, appends the discovery system message, and finally yields the `skill_index` trace with the full `_skill_trace_data` payload + fires `_record_trace_event`.

Post-refactor caller shape:
```python
# --- skills (Phase 3 working set + semantic discovery layer + ranking) ---
_tool_discovery_info: dict[str, Any] = {"tool_retrieval_enabled": False}
_ws_state: dict = {}
async for _evt in _inject_skill_working_set(
    messages=messages, bot=bot, user_message=user_message,
    correlation_id=correlation_id, session_id=session_id, client_id=client_id,
    skip_skill_inject=skip_skill_inject,
    tagged_skill_names=_tagged_skill_names,
    untagged_ephemeral=_untagged_ephemeral,
    source_map=_source_map,
    budget_can_afford=_budget_can_afford,
    budget_consume=_budget_consume,
    result=result,
    out_state=_ws_state,
):
    yield _evt
_enrolled_rows = _ws_state.get("enrolled_rows", [])
_suggestion_rows = _ws_state.get("suggestion_rows", [])
_enrolled_ids: list[str] = _ws_state.get("enrolled_ids", [])
_ranked_relevant: list[str] = _ws_state.get("ranked_relevant", [])
_auto_injected: list[str] = _ws_state.get("auto_injected", [])
_auto_injected_similarities: dict[str, float] = _ws_state.get("auto_injected_similarities", {})
_history_fetched_skills: set[str] = _ws_state.get("history_fetched_skills", set())
_history_skill_records: dict[str, dict[str, Any]] = _ws_state.get("history_skill_records", {})
```

LOC delta: `assemble_context` **1211 → 898** (-313, ~26%). File **2963 → 3013** (+50 net — helper added ~350 LOC, inline region removed ~346 LOC, ~35 LOC caller added, ~12 LOC default-value hoists). Combined 7a+7b+7c: assemble_context 1490 → 898 LOC (-40%).

**Why inner closures over module-level**: `_fmt_skill_line`, `_skill_category`, `_render_grouped_skill_lines` are only called from this helper and `_render_grouped_skill_lines` composes the other two. Module-level hoisting would add three more exported names to an already-long module for zero cross-helper reuse. Inner closures match the original structure.

**Why hoist `_tool_discovery_info`**: it was a default init (Stage 18 unconditionally overwrites it on the tool-retrieval path, and the final active-skills-snapshot trace reads it). Keeping the default in the caller avoids threading an unused key through `_ws_state` just to pass through.

**Verification**:
- Focused 9-file suite: pre-extraction (post-7b) **11 failed, 71 passed, 1 skipped**; post-extraction **11 failed, 71 passed, 1 skipped** — exact match.
- Neighbor sweep: **11 failed, 131 passed, 7306 deselected**. Same 11 pre-existing fails, zero new regressions.

**Gotchas**:
- Helper uses a bare `return` to exit the async generator when `bot.id` is falsy — valid Python for async generators (equivalent to `raise StopAsyncIteration`); preserves the original `if bot.id:` gate.
- `_fetch_skill_chunks`, `_rank_enrolled_skills`, `_retrieve_skill_index` are lazy-imported inside the helper from `app.agent.rag` (three-way import via aliases, matches original). `_increment_auto_inject_count` is also lazy-imported inside the per-skill auto-inject loop.
- `_ranking: list[dict] = []` initialized early in helper so both the "no ranking" path and the trace-data path can read it uniformly.

**Non-goals (explicit):**
- No module-level hoisting of the three formatting closures.
- No test changes.
- No change to auto-inject ordering, budget cutoff semantics, or trace event shape.

**Out of scope (remaining sub-clusters):**
- **Cluster 7d** — ✅ shipped 2026-04-24 (see RFC below).
- **Cluster 7e** — Stages 22-34 tail (temporal, widgets, refusal guard, prompt, preamble, user message, budget finalize, tracers).

### RFC — Cluster 7d — assemble_context Stage 18 tool-retrieval extraction (2026-04-24)

**Target**: Stage 18 (tool RAG + policy gate + pinned/retrieved merge + compact unretrieved-tool index + discovery trace) in `assemble_context` — 182 LOC, the second-largest remaining stage after 7c. Post-7c starting point: `assemble_context` at 898 LOC.

**Diagnosis**: Stage 18 composes four internal phases — enrolled-tool load + `by_name` pool construction (with auto-inject of `get_tool_info` / `search_tools` / `list_tool_signatures` / `run_script` / `get_skill` / `get_skill_list` when gates apply), semantic retrieval via `retrieve_tools`, channel-disabled + `TOOL_POLICY_ENABLED` deny-filter, effective-pinned ordering + `_merge_tool_schemas`, and unretrieved-tool index injection gated by `context_profile.allow_tool_index` + budget. All four phases compose through `by_name` and the discovered/retrieved sets; none depend on state outside the stage except the three outputs `pre_selected_tools` / `_authorized_names` / `_tool_discovery_info`. Gate `bot.tool_retrieval` stays in the caller so the helper is only invoked on the active path.

**Refactor**: one new module-level helper in a `# ===== Cluster 7d tool-retrieval extraction =====` block positioned after the 7c block:

`_run_tool_retrieval(*, messages, bot, user_message, ch_row, tagged_tool_names, correlation_id, session_id, client_id, context_profile, inject_decisions, budget_can_afford, budget_consume, out_state) -> AsyncGenerator[dict, None]`

Writes `pre_selected_tools`, `authorized_names`, `tool_discovery_info` to out_state. The `bot.tool_retrieval` branch stays in the caller; entering the helper implies retrieval is on.

Post-refactor caller shape:
```python
# --- tool retrieval (tool RAG) ---
pre_selected_tools: list[dict[str, Any]] | None = None
_authorized_names: set[str] | None = None
if bot.tool_retrieval:
    _tr_state: dict = {}
    async for _evt in _run_tool_retrieval(
        messages=messages, bot=bot, user_message=user_message,
        ch_row=_ch_row, tagged_tool_names=_tagged_tool_names,
        correlation_id=correlation_id, session_id=session_id, client_id=client_id,
        context_profile=context_profile, inject_decisions=_inject_decisions,
        budget_can_afford=_budget_can_afford, budget_consume=_budget_consume,
        out_state=_tr_state,
    ):
        yield _evt
    pre_selected_tools = _tr_state.get("pre_selected_tools")
    _authorized_names = _tr_state.get("authorized_names")
    _tool_discovery_info = _tr_state.get("tool_discovery_info", _tool_discovery_info)
```

LOC delta: `assemble_context` **898 → 740** (-158, ~18%). File **3013 → 3047** (+34 net — helper added ~182 LOC, inline region removed ~182 LOC, ~24 LOC caller added + gate preserved). Combined 7a+7b+7c+7d: assemble_context **1490 → 740 LOC (-50%)**.

**Why caller keeps the gate**: `bot.tool_retrieval` is a cheap bool check. Pushing it inside would mean the helper is always called and always constructs `_tr_state` / default out_state values, which adds call overhead on the non-retrieval path without simplifying the caller — all three output locals still need their pre-gate declarations (`pre_selected_tools: list[...] | None = None`, `_authorized_names: ... | None = None`) because downstream code reads them regardless. Keeping the gate saves the function call and preserves the original structure.

**Why `_tool_discovery_info` read uses `_tr_state.get(..., _tool_discovery_info)` fallback**: the helper only writes `tool_discovery_info` when `by_name` is non-empty. When `by_name` is empty the caller should keep the default init (`{"tool_retrieval_enabled": False}`) hoisted from the 7c caller block. Passing the existing value as the `.get` default is the idiomatic "keep it unless the helper provided one" pattern.

**Verification**:
- Focused 9-file suite: pre-extraction (post-7c) **11 failed, 71 passed, 1 skipped**; post-extraction **11 failed, 71 passed, 1 skipped** — exact match.
- Neighbor sweep (excluding 6 pre-existing collection errors in `test_slack_renderer.py` / `test_discord_renderer.py` / `test_bluebubbles_renderer.py` / `test_core_renderers.py` / `test_slack_ephemeral.py` / `test_slack_tool_output_display.py` — all caused by uncommitted work in `integrations/tool_output.py` from another session, unrelated to this extraction): **11 failed, 131 passed, 7191 deselected**. Zero new regressions.

**Gotchas**:
- Stage 18's side-effect on `_authorized_names` (adding discovered tool names post-policy-filter at the "Add discovered tool names to authorized set" block) must happen AFTER the policy gate — extraction preserves that order exactly.
- `TOOL_POLICY_ENABLED` policy call uses `_authorized_names` to distinguish "declared" tools (already in `by_name`) from "discovered" tools — only discovered tools go through `evaluate_tool_policy`. This preserves the original semantic: declared tools bypass the deny gate.
- Capability-gate drop of non-exposable tools (line 2281+82 of the outer function, still in caller) remains downstream of the helper — it mutates `_authorized_names` and filters `pre_selected_tools` after the helper returns.

**Non-goals (explicit):**
- No policy-gate semantics changes.
- No test changes.
- No merge ordering change in `_merge_tool_schemas`.

**Out of scope (remaining sub-cluster):**
- **Cluster 7e** — Stages 22-34 tail (temporal framing, pinned widgets, refusal guard, channel prompt, preamble, user message, budget finalize, tracer emits). Homogeneous tail — all mutate `messages` + `result` + yield trace events.

---

### RFC — Cluster 7e-a — assemble_context tool-exposure finalization extraction (2026-04-24)

**Scope:** Extracted Stages 19 (merge dynamically injected tools), 20 (widget-handler tools), and 21 (capability-gated tool exposure) as a single in-file helper. All three stages read/mutate the same two locals (`pre_selected_tools`, `_authorized_names`), so they factor into one helper cleanly.

**Result:**
- `assemble_context` 740 → 654 LOC (-86, ~12%).
- File 3047 → 3083 (+36 net).
- **Cumulative 7a+7b+7c+7d+7e-a: 1490 → 654 LOC (-56%).**
- Focused 9-file suite: **11 failed, 71 passed, 1 skipped** (exact baseline match).
- Neighbor sweep (`context_assembly or assembly_budget or memory_injection or kb_auto or context_profile or channel_workspace`): **11 failed, 131 passed, 7202 deselected** — zero new regressions. Pre-existing renderer-test collection errors ignored (same 6 files as 7d; not caused by this extraction).

**Helper added:**

`_finalize_exposed_tools(*, bot, channel_id, ch_row, pre_selected_tools, authorized_names, out_state) -> None`

Plain async (no yields). Writes final `pre_selected_tools` and `authorized_names` to out_state. Lives under `# ===== Cluster 7e-a tool-exposure finalization =====` header, positioned after `_run_tool_retrieval` (7d) and before `_inject_plan_artifact`.

**Caller block (13 LOC replaces ~100 LOC inline):**

```python
# --- tool-exposure finalization (dynamic injection + widget-handler tools + capability gate) ---
_ft_state: dict = {}
await _finalize_exposed_tools(
    bot=bot,
    channel_id=channel_id,
    ch_row=_ch_row,
    pre_selected_tools=pre_selected_tools,
    authorized_names=_authorized_names,
    out_state=_ft_state,
)
pre_selected_tools = _ft_state.get("pre_selected_tools", pre_selected_tools)
_authorized_names = _ft_state.get("authorized_names", _authorized_names)

result.pre_selected_tools = pre_selected_tools
result.authorized_tool_names = _authorized_names
result.effective_local_tools = list(bot.local_tools)
```

**Design choices worth remembering:**

- **Plain async, not async generator**. Stages 19/20/21 have no yields. Avoided the generator-return-via-out_state pattern where a simple async function suffices.
- **Three stages as one helper**. The alternative — three tiny helpers — would have required passing `pre_selected_tools`/`authorized_names` in and out of each and chaining them explicitly in the caller. Since all three stages share the same two mutable locals and form one conceptual phase ("finalize the exposed tool set"), merging was clearer.
- **`out_state.get(key, default)` fallback**. Helper writes to out_state unconditionally at the end, so defaults aren't strictly needed, but `.get(..., pre_selected_tools)` preserves the pattern used by 7c/7d and keeps the caller defensive.
- **`result.*` assignments stay in caller**. The three `result.pre_selected_tools = ...` / `result.authorized_tool_names = ...` / `result.effective_local_tools = ...` lines remain in the caller — they're the visible "commit" of the finalization phase and read as the natural closing of the section.

**Non-goals (explicit):**
- No policy-gate changes, no widget-handler contract changes, no capability-gate semantics changes.

**Out of scope (remaining sub-clusters):**
- **7e-b** — Stages 22 (temporal/conversation-gap framing), 23 (pinned widget state), 24 (tool refusal guard). ~169 LOC.
- **7e-c** — Stages 25-29 (channel prompt, system preamble, current-turn marker, system_prompt reinforcement, user message). ~76 LOC.
- **7e-d** — Stages 30-33 (budget finalize, injection summary trace, active-skills snapshot, discovery summary trace). ~115 LOC.

---

### RFC — Cluster 7e-b — assemble_context late cache-safe injections extraction (2026-04-24)

**Scope:** Extracted Stages 22 (datetime + conversation-gap framing), 23 (pinned widget state), 24 (tool refusal guard), and the trailing context-profile note as a single in-file helper. All four share the "cache-safety band" — inject AFTER tool surface is finalized, BEFORE channel prompt / preamble / user message — and all mutate the same three trackers (`messages`, `inject_chars`, `inject_decisions`).

**Result:**
- `assemble_context` 654 → 498 LOC (-156, ~24%).
- File 3083 → 3122 (+39 net).
- **Cumulative 7a+7b+7c+7d+7e-a+7e-b: 1490 → 498 LOC (-67%, UNDER 500).**
- Focused 9-file suite: **11 failed, 71 passed, 1 skipped** (exact baseline match).
- Neighbor sweep: **11 failed, 131 passed, 7202 deselected** — zero new regressions.

**Helper added:**

`_inject_late_cache_safe_context(*, messages, bot, channel_id, ch_row, session_id, authorized_names, context_profile, inject_chars, inject_decisions, budget_can_afford, budget_consume) -> None`

Plain async (no yields, no out_state). Mutates `messages`/`inject_chars`/`inject_decisions` in place via references. Under `# ===== Cluster 7e-b late cache-safe injections =====` header, positioned after `_finalize_exposed_tools` (7e-a) and before `_inject_plan_artifact`.

**Caller block (14 LOC replaces 170 LOC inline):**

```python
# --- late cache-safe injections (temporal + pinned widgets + refusal guard + profile note) ---
await _inject_late_cache_safe_context(
    messages=messages,
    bot=bot,
    channel_id=channel_id,
    ch_row=_ch_row,
    session_id=session_id,
    authorized_names=_authorized_names,
    context_profile=context_profile,
    inject_chars=_inject_chars,
    inject_decisions=_inject_decisions,
    budget_can_afford=_budget_can_afford,
    budget_consume=_budget_consume,
)
```

**Design choices worth remembering:**

- **Include `context_profile_note` in the same helper**. The note summarizes decisions from Stages 22-24 into a system-message and follows the same budget/decision pattern. Extracting it separately would force the caller to read `_inject_decisions` after the helper just to pass it back in — pointless roundtrip.
- **No out_state needed**. All mutations (`messages.append`, `inject_chars[key] = ...`, `_mark_injection_decision(inject_decisions, ...)`) go through mutable references. Plain async with no return value keeps the caller a single `await helper(...)` line.
- **`logger` stays module-level**. Four `logger.debug`/`logger.info` calls in the helper resolve to the module-level `logger` — matches precedent from all prior 7* helpers.
- **`_mark_injection_decision` stays module-level**. Called 12 times inside the helper; promoting it to a kwarg would be churn for zero payoff — it's a stable module-level utility.
- **Nested imports preserved**. Each stage's `from X import Y` stays inline (temporal_context, widget_context, tool_refusal_guard) — matches existing pattern of deferring expensive imports to the branch that uses them.

**Non-goals (explicit):**
- No changes to temporal framing semantics (ScanMessage, TemporalBlockInputs, build_current_time_block).
- No changes to pinned-widget snapshot structure.
- No changes to tool-refusal-guard scanning logic.
- No changes to context_profile_note rendering.

**Out of scope (remaining sub-clusters):**
- **7e-c** — Stages 25-29 (channel prompt, system preamble, current-turn marker, system_prompt reinforcement, user message). ~76 LOC.
- **7e-d** — Stages 30-33 (budget finalize, injection summary trace, active-skills snapshot, discovery summary trace). ~115 LOC.

---

### RFC — Cluster 7e-c — assemble_context message assembly extraction (2026-04-24)

**Scope:** Extracted Stages 25-29 (channel prompt, system preamble, current-turn marker, bot system_prompt reinforcement, user message text/audio) as a single in-file helper. These five stages are the final message-append phase — all mutate `messages` + `inject_chars`, and the last writes `result.user_msg_index`.

**Result:**
- `assemble_context` 498 → 441 LOC (-57, ~11%).
- File 3122 → 3167 (+45 net).
- **Cumulative 7a+7b+7c+7d+7e-a+7e-b+7e-c: 1490 → 441 LOC (-70%).**
- Focused 9-file suite: **11 failed, 71 passed, 1 skipped** (exact baseline match).
- Neighbor sweep: **11 failed, 131 passed, 7202 deselected** — zero new regressions.

**Helper added:**

`_append_prompt_and_user_message(*, messages, bot, channel_id, ch_row, user_message, attachments, audio_data, audio_format, native_audio, system_preamble, task_mode, inject_chars, budget_consume, result) -> None`

Plain async. 13-kwarg signature is noisier than prior helpers because this phase ingests almost every user-turn input (text, attachments, audio, preamble, task_mode) — but that's the natural shape, not accidental coupling.

**Non-goals (explicit):**
- No changes to `resolve_workspace_file_prompt`, `sanitize_unicode`, `_build_audio_user_message`, `_build_user_message_content`.
- No changes to the turn-marker wording or the REINFORCE_SYSTEM_PROMPT gate.
- `user_msg_index` continues to be set exactly once (either audio branch or text branch).

**Out of scope (remaining sub-cluster):**
- **7e-d** — Stages 30-33 (budget finalize, injection summary trace, active-skills snapshot, discovery summary trace). ~115 LOC. Tracer tail.

---

### RFC — Cluster 7e-d — assemble_context finalization traces extraction (2026-04-24) — CLUSTER 7 COMPLETE

**Scope:** Extracted Stages 30-33 (store budget utilization, injection summary trace, active-skills snapshot, discovery summary trace) as the final in-file helper. This closes Cluster 7.

**Result:**
- `assemble_context` 441 → 357 LOC (-84, ~19%).
- File 3167 → 3220 (+53 net).
- **Cumulative 7a+7b+7c+7d+7e-a+7e-b+7e-c+7e-d: 1490 → 357 LOC (-76%).**
- Focused 9-file suite: **11 failed, 71 passed, 1 skipped** (exact baseline match).
- Neighbor sweep: **11 failed, 131 passed, 7202 deselected** — zero new regressions.

**Helper added:**

`_emit_finalization_traces(*, bot, correlation_id, session_id, client_id, context_profile, budget, inject_chars, inject_decisions, enrolled_rows, enrolled_ids, ranked_relevant, auto_injected, auto_injected_similarities, suggestion_rows, history_fetched_skills, history_skill_records, tool_discovery_info, result) -> None`

Plain async. 18-kwarg signature — wide because the discovery_summary trace aggregates skill data from 7c (`enrolled_rows`, `enrolled_ids`, `ranked_relevant`, `auto_injected`, `auto_injected_similarities`, `suggestion_rows`, `history_fetched_skills`, `history_skill_records`) and tool data from 7d (`tool_discovery_info`). That's not coupling — that's the natural shape of a "summary emit" helper that reads everything discovery produced.

**Design choices worth remembering:**

- **Two `asyncio.create_task(_record_trace_event(...))` fire-and-forget emits**. Preserved exactly — no await, no error handling added. The original behavior was "emit and move on"; helper extraction didn't change it.
- **Active-skills snapshot stays in the same helper**. Logical grouping: the summary traces and the skills-in-context ctxvar update all happen at "end of assembly." Splitting would mean the caller has to hold `enrolled_rows` + `history_skill_records` twice — once for the snapshot helper and once for the discovery summary helper.
- **`current_skills_in_context.set(list(...))` stays inside**. Ctxvar mutation is atomic with the `result.skills_in_context.append()` that populates it.

**Cluster 7 retrospective:**

Same-day execution across 8 sub-clusters (7a, 7b, 7c, 7d, 7e-a, 7e-b, 7e-c, 7e-d) — all behavior-preserving with exact baseline match every time. 16 new helpers added to the module, no signature changes to `assemble_context` or `AssemblyResult`. The caller is now a linear driver where each stage-divider comment marks a helper call; readers can scan top-to-bottom to see the 33-stage pipeline without getting lost in stage internals.

**Non-goals (explicit):**
- No `_AssemblyCtx` dataclass refactor — per 7a plan, left as potential follow-up.
- No consolidation of out_state dicts across helpers — each helper's state scope is deliberately topic-scoped (`_ch_state`, `_skill_state`, `_ws_state`, `_tr_state`, `_ft_state`).
- No re-ordering of stages — every helper was extracted in-place.
- No test changes — baseline identity preserved across all 8 sub-clusters.

---

### RFC — Cluster 8 — compaction stream/forced duplication collapse (2026-04-24)

**Target:** `app/services/compaction.py` — both the god function `run_compaction_stream()` (361 LOC) and its near-twin `run_compaction_forced()` (248 LOC), which had run the same 6-stage pipeline (memory flush, watermark, section generation, summary synthesis, session persistence, trace emission) with ~250 LOC of byte-equivalent code. Stream owns its own session and yields SSE events; forced uses a caller-owned `db` and returns a `(title, summary)` tuple.

**Result:**
- `run_compaction_stream`: **361 → 177 LOC (-51%)**.
- `run_compaction_forced`: **248 → 106 LOC (-57%)**.
- File: 2653 → 2637 LOC (-16 net; helpers replaced more code than they added).
- Combined god-function delta: 609 → 283 LOC across the two wrappers (-326 LOC, -54%).
- Focused 7-file suite (`test_compaction*` × 6 + `test_compaction.py` integration): **157 passed, 2 failed, 0 skipped** — exact baseline match. The 2 failures (`test_settings_override`, `test_stream_path_captures_prev_watermark`) are pre-existing and were confirmed identical pre-/post-refactor.
- Neighbor sweep on remaining `-k compaction` unit tests: 49 passed + 2 pre-existing fails in `test_lc_compaction_improvements.py` (verified pre-existing via `git stash` and re-running on clean HEAD — both fail with `no such table: sessions` due to test-fixture gap, unchanged by Cluster 8).

**Five helpers added (in-file, above the wrappers):**

1. `_run_memory_flush_phase(*, channel, bot, session_id, messages, correlation_id) -> tuple[bool, str | None]` — pre-compaction memory flush + member-bot fan-out + heartbeat fallback. Errors log-and-swallow; returns `(memory_flush_ran, flush_result)`.
2. `_compute_compaction_watermark(*, db, session_id, keep_turns, prev_watermark_id) -> WatermarkPlan | None` — single source for the `oldest_kept` + `last_msg_id` query. Returns `None` for both empty-user-msgs and all-in-keep-window cases (forced wrapper distinguishes via a follow-up count query to preserve its two ValueError messages).
3. `_persist_section_and_summary(*, db, session_id, channel, bot, messages, watermark, correlation_id, client_id, model, existing_summary, autoflush_only) -> SectionPersistOutcome` — generates section, embeds, computes period bounds, writes transcript file, inserts `ConversationSection`, prunes old sections, builds the executive summary (with auto-regen). The `autoflush_only` kwarg is the commit-boundary switch: stream calls with `False` (helper commits + uses internal session for `prune_sections`); forced calls with `True` (helper flushes only, caller commits, `prune_sections` reuses the caller's `db`).
4. `_persist_session_compaction_state(*, db, session_id, title, summary, watermark_id) -> None` — single `update(Session)`. Does not commit.
5. `_record_compaction_completion(*, …)` — fire-and-forget `compaction_done` trace + `_record_compaction_log` task creation. The `forced=True` branch prepends `{"forced": True}` to the trace data dict to match the legacy shape.

Two new dataclasses (`WatermarkPlan`, `SectionPersistOutcome`) carry helper outputs as frozen records.

**Wrappers post-refactor:**

`run_compaction_stream` reads as: pre-flight session/channel load → enabled check → eligibility count → reload session for client_id/summary/prev_watermark → compute watermark + summary window → guard → emit `compaction_start` → trace start → memory flush → branch on history_mode (section helper or `_generate_summary`) → persist session state → record completion → yield `compaction_done` (or `compaction_failed`). The pre-start window guard is intentional so auto budget-triggered no-ops do not create visible chat cards.

`run_compaction_forced` (106 LOC) reads as: load session/channel → trace start → load all messages → memory flush → compute watermark (with two-case ValueError disambiguation) → branch on history_mode → persist session state → record completion → return tuple.

**Key design choices worth remembering:**

- **`autoflush_only` kwarg over two helpers.** The section-persist phase has identical logic except for transaction ownership. Two near-identical helpers would re-introduce the duplication; one helper with an explicit boundary switch keeps the seam visible.
- **Watermark `None` disambiguation lives in the forced wrapper.** Stream simply returns silently on either case; forced has to raise ValueErrors with specific substrings (`"No user messages found in session"` / `"All messages within keep window, nothing to compact"`) because `_is_noop_compaction_error` (line 275) substring-matches against `_COMPACTION_NOOP_ERRORS`. The disambiguation is a single follow-up `select(func.count())` query — cheap, and keeps the helper signature honest.
- **Session boundaries preserved.** Stream still opens its own multiple internal sessions across pre-flight, watermark/window, section persist, and session update steps. The section persist helper opens a session-internal commit when `autoflush_only=False`; the session-state persist is then in its own session. This collapses the previous five stream sessions into three (pre-flight + section-persist + state-persist). No commit timing change observable to tests.
- **Trace event shape preserved.** `_record_compaction_completion` builds the data dict with `{"forced": True}` first when forced=True so dict-key iteration order matches the legacy shape (relevant for any consumer that compared serialized JSON).

**Why this is deep, not shallow:** the five helpers hide substantial logic — `_persist_section_and_summary` alone is 132 LOC including LLM call, embedding, period computation, transcript file write, DB insert, retention pruning, executive-summary append-or-create, and auto-regeneration. Callers see "persist a section and produce a summary"; they don't see the dual transaction-ownership branch, the lazy `embed_text` import, the period-bound logic with optional prev-watermark fence, or the regen threshold constants.

**Non-goals (explicit):**
- No signature changes to `run_compaction_stream` or `run_compaction_forced` — `_drain_compaction`, `_run_manual_compaction_operation`, and the SSE/router callers are unaffected.
- No behavioural deltas: event shape, SSE yield order, ValueError message strings, trace data shape, compaction_log column values, retention pruning timing, transcript file path resolution, executive-summary regen thresholds — all byte-equivalent.
- No fix to the 2 pre-existing test failures (`test_settings_override`, `test_stream_path_captures_prev_watermark`). Test Quality track item.
- No `_generate_section` internal restructure (separate from duplication scope).
- No section-prompt consolidation.

**Out of scope (next clusters):**
- **Cluster 9 — `tasks.run_task()` (now 656 LOC, drifted from track's 490 estimate)** — 7 distinct concerns (session resolve, config extraction, prompt resolution, agent run, persistence, dispatch, follow-up creation) plus 4× "mark task failed" duplication. No section markers, heavier dependency-injection surface than compaction (get_bot, async_session, session_locks, openai.RateLimitError, etc.). Largest remaining absolute target.
- **Cluster 10 — `file_sync.sync_all_files()` (333 LOC) + `sync_changed_file()` (181 LOC)** — three resource types (Skills/Prompt Templates/Workflows), already has clean `# --- Stage ---` markers. Tightest duplication of the remaining set.

---

### RFC — Cluster 10 — file_sync sync_all/watch duplication collapse (2026-04-24)

**Goal**: collapse `sync_all_files` (full disk → DB scan) and `sync_changed_file` (single watch event) into thin drivers that share per-resource-type upsert / orphan-delete helpers. Both wrappers ran the same three resource pipelines (Skill, PromptTemplate, Workflow) with byte-equivalent SQL and ~250 LOC of duplication.

**Shipped**: 8 in-file stage helpers under `# ===== Cluster 10 file_sync stage helpers =====` block above `sync_all_files`:

1. `_log_action(action, kind, ident, log_path) -> str` — formats either watch-mode (`"file_sync(watch): added skill 'X'"`) or sync_all-mode (`"file_sync: added skill 'X' from /path"`) log messages depending on whether `log_path` is None.
2. `_upsert_skill_row(*, skill_id, raw, source_path, source_type, log_path) -> str` — returns `"added"`, `"updated"`, or `"unchanged"`. Raises on DB error so callers handle their own try/except (sync_all → counts["errors"]; watch → outer `watch_files()` try/except).
3. `_build_prompt_template_fields(raw, name) -> dict` — pure parser for PromptTemplate column values shared by both upsert paths. Includes the `mc_min_version` → tag expansion.
4. `_upsert_prompt_template_row(*, name, raw, source_path, source_type, log_path) -> str` — same status return, same raise-on-error. Watch-mode update preserves today's behavior of NOT touching `source_path`/`source_type` on hash mismatch (sync_all does).
5. `_upsert_workflow_row(*, workflow_id, raw, source_path, source_type, log_path) -> tuple[str, str]` — returns `(status, resolved_workflow_id)` because the YAML may contain an explicit `id:` field that differs from the path-derived id, and both wrappers need the resolved id (sync_all to populate `seen_workflow_ids`). Watch-mode skips `session_mode` setting and the `existing.source_type == "manual"` skip branch — preserved exactly.
6. `_delete_orphan_skills(*, seen_ids, any_files_on_disk, cwd) -> tuple[int, list[str]]` — encapsulates the "skip orphan deletion if zero files on disk" mount-protection branch with its warning log + error message. Returns `(deleted, error_messages)` for caller to fold into `counts`.
7. `_delete_orphan_prompt_templates(*, seen_paths) -> int` — straight orphan delete by source_path.
8. `_delete_orphan_workflows(*, seen_ids) -> int` — straight orphan delete by id.
9. `_delete_rows_by_source_path(*, path_str) -> tuple[bool, bool]` — used only by watch's deleted-file branch. Returns `(any_deleted, workflow_deleted)` so the caller can emit the "removed DB rows" log and decide whether to reload workflows.

**LOC delta**:
- `sync_all_files`: 333 → 159 LOC (-174, **-52%**)
- `sync_changed_file`: 180 → 60 LOC (-120, **-67%**)
- Combined wrappers: 513 → 219 LOC (-294, **-57%**)
- File: 851 → 908 LOC (+57 net; helpers add ~355 LOC, duplicated wrapper code -294 LOC)

**Tests — exact baseline match**:
- Focused 3-file suite (`test_file_sync.py`, `test_file_sync_core_gaps.py`, `test_file_sync_skills.py`): 34 passed, 8 errors (pre/post identical).
- The 8 errors are a pre-existing fixture bug at `tests/unit/test_file_sync.py:249` — `yield {"tmp_path": tmp_path, "embed": embed}` references `embed` but the matching `with patch(...)` is missing the `as embed` clause. Test Quality follow-up; **fixing it would unblock 8 tests covering `sync_all_files`'s skill + prompt template paths** that are currently dark.
- Neighbor sweep (`-k file_sync`): 35 passed, 8 errors (same pre-existing fixture bug).
- Workflow + skill_enroll sweep (`-k "workflow or skill_enroll"`): 216 passed, 18 skipped — clean.

**Design choices worth remembering**:
- **`log_path: Path | None` is the watch-vs-sync_all switch**. Threading a single Path-or-None kwarg into each upsert helper does double duty: (a) chooses log-message format, (b) gates sync_all-only behavior (workflow `manual` skip, source-drift fix on unchanged). Two helpers per kind would have re-introduced ~70% of the duplication; one helper with an `is_watch = log_path is None` flag keeps the seam visible in a single line per call site.
- **Helpers raise on DB error; callers wrap**. Watch mode lets exceptions bubble to `watch_files()` which does its own `logger.exception`, while sync_all mode wraps each per-file call to record into `counts["errors"]`. Embedding try/except inside the helper would have collapsed the two error-handling shapes into one and silently swallowed watch-mode errors — a regression.
- **Workflow upsert returns `(status, wid)`**. The YAML-level `id:` override means the resolved workflow id may differ from the path-derived input. Sync_all needs the resolved id to populate `seen_workflow_ids` so orphan deletion doesn't nuke the just-upserted row. Tuple return keeps that contract honest.
- **Watch-mode workflow doesn't set `session_mode`**. Today's watch handler omits `session_mode=data.get("session_mode", "isolated")` from both add and update paths — preserved exactly via `if not is_watch: kwargs["session_mode"] = ...`. This is a probable bug (watch-mode YAML edits to `session_mode` are silently dropped), but Cluster 10's contract is behavior preservation. **Filed under Loose Ends as a follow-up.**
- **Watch-mode prompt-template update doesn't update `source_path`/`source_type`**. Same preservation pattern: `if not is_watch: existing.source_path = source_path; existing.source_type = source_type`. Same probable bug, same Loose Ends entry.

**Gotchas**:
- **`_delete_rows_by_source_path` returns two bools, not one**. Watch needs to know whether ANY rows deleted (for the log message) AND whether a workflow row deleted (to gate the registry reload). Single bool would have either over-reloaded or under-logged.
- **`_upsert_prompt_template_row` lookup is by `source_path`**, not by `name`. PromptTemplate has no unique key on name, so the helper has to find the matching row via the same `(source_path, source_type IN [file, integration])` predicate both wrappers use. Lookup-by-name would have created or updated the wrong row when two integrations ship a template with the same stem.
- **`session_mode` is sync_all-only via `**({"session_mode": ...} if not is_watch else {})`**. Spread-into-kwargs because passing `session_mode=None` to the WorkflowRow constructor would have *set* the column to None, not skipped it. Conditional spread skips the kwarg entirely.

**Track update**:
- Frontmatter bumped to "Cluster 10 shipped — file_sync.py sync_all/watch duplication collapsed into 8 stage helpers; sync_all_files 333 → 159 LOC -52%, sync_changed_file 180 → 60 LOC -67%".
- God-functions table row for `file_sync.py sync_all_files()` updated with strikethrough chain + ✅ CLUSTER 10 SHIPPED prefix; combined sync_all + sync_changed_file LOC tracked.
- Major Duplication entry `file_sync.py:241-1041 — Full sync vs watch handler` struck through and noted FIXED.
- Full RFC — Cluster 10 — appended after Cluster 8 RFC.

**Follow-ups**:
- **Test fixture fix** at `tests/unit/test_file_sync.py:249` — add `as embed` to the first `patch(...)` call. Single-line change, unblocks 8 tests covering sync_all's skill + prompt template paths.
- **Watch-mode workflow `session_mode` drop** — preserved as-is for Cluster 10. Probable bug; should be a Loose Ends entry.
- **Watch-mode prompt-template update doesn't update `source_path`/`source_type`** — same probable bug class.
- **Cluster 9 — `tasks.run_task()` (656 LOC)** — last remaining structural cluster from the original audit. Largest absolute target.

**Why this is deep, not shallow**: the eight helpers hide substantial logic — each upsert carries the get-or-fetch-by-predicate, content-hash short-circuit, frontmatter parsing, mc_min_version tag expansion, source-type/source-path drift fix, and per-kind add/update SQL with the right column subset. Callers see "upsert this skill from raw" or "delete orphans by seen_ids"; they don't see the watch-vs-sync_all log format toggle, the manual-skip branch, the optional session_mode kwarg conditional, or the lookup-by-source_path predicate.

**Non-goals (explicit)**:
- No signature changes to `sync_all_files` or `sync_changed_file` — `app/main.py` startup, `watch_files()`, the admin trigger router, and the test patch surface are all unaffected.
- No behavioral deltas: log message strings, log levels, error messages in `counts["errors"]`, source_path/source_type drift behavior, manual-workflow skip, watch-mode `session_mode` omission, watch-mode prompt-template field omission — all byte-equivalent.
- No fix to the 8 pre-existing test fixture errors. Test Quality track follow-up.
- No fix to the watch-mode `session_mode` drop or watch-mode prompt-template `source_path`/`source_type` drop. Loose Ends follow-ups.
