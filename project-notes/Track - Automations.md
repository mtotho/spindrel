---
tags: [agent-server, track, automations]
status: active
created: 2026-04-15
updated: 2026-04-29 (channel quick automations visual feedback)
---
# Track — Automations (Task Pipelines)

Task pipelines are the automation primitive — multi-step sequences (shell → tool → LLM) stored inline on the Task model. Decision documented in [[Architecture Decisions#Task Pipelines as Automation Primitive]].

## 2026-04-29 — Channel Quick Automations V1

- Added internal run presets as read-only canned task payloads, not a new persisted primitive. The first preset is `widget_improvement_healthcheck`.
- Channel Settings -> Tasks now shows a compact Quick automations launcher. The preset opens a review drawer with editable title, start, recurrence, prompt, and channel-posting behavior, then creates an ordinary scheduled task through the existing task API.
- The preset defaults to a quiet weekly widget health/usefulness review with recent channel history, the `widgets` skill pack, and the read/inspection widget tools. It does not alter heartbeat behavior or grant global approval bypasses.
- Advanced customization stays in `/admin/automations`: the drawer can create the task and jump to the full automation editor.
- Visual feedback is now durable through `python -m scripts.screenshots capture --only channel-quick-automations`, producing the launcher plus desktop/mobile review drawer docs images.

## 2026-04-29 — Heartbeat and maintenance consolidation pass

- Added a shared task-run policy module so heartbeat, scheduled prompt/pipeline, delegation, and maintenance runs resolve context profile, origin, and skill-injection behavior from one place instead of scattered `task_type` checks.
- Added a maintenance automation read model for memory hygiene and skill review jobs. Existing "Dreaming" admin endpoints keep their response shape, but upcoming activity and usage forecasting now read maintenance jobs through the shared service instead of re-deriving bot config and latest task state.
- Upcoming activity now has a generic `maintenance` shape while preserving legacy `memory_hygiene` and `skill_review` filters for existing UI/API callers.
- This is intentionally a read-model/plumbing step, not a scheduler rewrite. The next UX pass should expose maintenance jobs through the same Automations surfaces only after the shared run/session-target semantics for heartbeats and scheduled automations are settled.

## 2026-04-26 — Canvas xyflow rebuild + workspace orbit

This pass folded three things together: replaced the hand-rolled drag/edges with **xyflow (React Flow v12)**; pulled task definitions onto the **main spatial canvas** as an outer-ring orbit around the Now Well that zoom-dives into the editor; tightened dark-mode contrast on the mode picker.

### 2026-04-26 follow-up — mobile editor fit + date picker portal

- `DateTimePicker` now renders its calendar panel through a body-level portal with viewport-aware fixed positioning, matching the shared dropdown pattern. This lets the Trigger tab's start-date picker escape the task card's scroll/overflow boundary.
- The automation canvas editor now has a narrow-viewport default camera, a wrapping action bar, mobile-hidden minimap toggle, scroll-safe mode picker, and viewport-clamped task node width/height so iPhone-sized viewports do not crop the task card or top actions.

### Library survey (recorded for future picks)

- **`@xyflow/react` (React Flow v12)** — adopted. MIT, ~50 KB gz. Pan/zoom, controlled positions, edges with handles, snap-to-grid, multi-select + marquee, CSS-var theming via `--xy-*`. Bridge file at `ui/app/(app)/admin/tasks/canvas/CanvasTheme.css` maps `--xy-*` onto Spindrel `--color-*` tokens.
- **`motion` (Motion One)** — installed (~5 KB gz) for future tile expand/collapse animations. Not yet exercised in this pass.
- **Excalidraw** — sketch-feel editor; lower fit for structured node graphs. Skipped.
- **Rete.js / LiteGraph** — graph engines that don't compose cleanly with React. Skipped.
- **Claude Code skill packs / Tailwind plugins** — none required for this pass; revisit if a specific pain point surfaces.

### Editor surface

- `ui/app/(app)/admin/tasks/canvas/CanvasEditor.tsx` is now a thin `<ReactFlow>` wrapper. Custom node types: `task` (TaskNode) + `step` (StepNode). Edges classified as `anchor` / `sequential` / `conditional` / `secondary` (`edges.ts`, `CanvasEdges.tsx`).
- Edge classification mirrors the rev-2 spec: sequential primary edge from `steps[idx-1]→steps[idx]`; secondary dotted edge from non-immediate `when.step` referent; simple/complex condition shapes get readable badges or a "conditional" pill with raw-JSON tooltip respectively. Conditions never reshape on save — round-trip pin still applies.
- StepNode wraps the existing `StepCard` (already extracted under `step-editor/`) inline when expanded; collapsed shows icon + type + label + summary.
- TaskNode mounts ContentFields / ExecutionFields / TriggerFields inside section tabs. ContentFields gained a `hideStepEditor` prop so pipeline-mode shows a "steps live as tiles" hint instead of inlining the linear editor.
- Snap-to-grid on at 16 px. Min/max zoom 0.4–1.5. Background dots at 24 px. Minimap toggle. Pan via middle/right mouse + scroll-wheel pan (left button reserved for box selection).
- Click empty canvas (double-click) → adds a step at click point. Floating "+ Add Step" button does the same at viewport center.

### Dirty gate (Esc + Close, both protected)

- `ui/app/(app)/admin/tasks/canvas/useDirtyGate.ts` snapshots the form payload on initial load and compares it against the current state; `isDirty` is the deep diff. Save updates the baseline via `markClean()`.
- Esc and Close button both call `dirty.guard()` which short-circuits to `true` when clean, or shows `window.confirm("Discard unsaved changes?")` when dirty.
- "Unsaved" pill in the action bar surfaces dirty state visibly so the user is never surprised.

### Workspace spatial-canvas integration

- `spatialGeometry.ts` — added `DEFINITIONS_R = WELL_R_MAX * 1.42` (static outer-ring radius outside the 1w time-band ring).
- `spatialDefinitionsOrbit.ts` — angle math sibling of `spatialActivity.ts`. Hash-based deterministic angular slot per `task.id` + an even-spread mode (count + index) for tidy distribution when N is small.
- `TaskDefinitionTile.tsx` — three semantic-zoom tiers (far dot, mid glyph, close full card with step-count + trigger chip), mirrors `UpcomingTile`. Lens (fisheye) projection respected.
- `SpatialCanvas.tsx` — adds `useQuery({ queryKey: ["spatial-task-definitions"] })` against `/api/v1/admin/tasks?definitions_only=true` (filters `source === "system"`), renders one TaskDefinitionTile per non-system definition, and provides `diveToTaskDefinition(taskId)` mirroring `diveToChannel`: camera flies, scale ramps to ~`MAX_SCALE * 0.95`, then `navigate("/admin/automations?canvas=1&edit=<id>")`.

### Surface map (the standalone canvas index is retired)

- `/canvas` — workspace canvas, **the index** for definitions (orbit visible at all zoom tiers).
- `/admin/automations?canvas=1&new=1[&mode=prompt|pipeline]` — fullscreen new-task editor (mode picker → xyflow editor).
- `/admin/automations?canvas=1&edit=<id>` — fullscreen edit-mode editor.
- `/admin/automations?canvas=1` (no params) — auto-redirects to `/canvas`.
- `/admin/automations` (no `?canvas=1`) — table list view stays for power-users.

`AutomationsCanvasPage` is now a thin host for the editor (sidebar + dot-grid index removed). The list-view page header replaces the old "Canvas" button with "Open in spatial canvas" → `/canvas`.

### Files

- New: `CanvasEditor.tsx` (rewritten on xyflow), `TaskNode.tsx`, `StepNode.tsx`, `CanvasEdges.tsx`, `edges.ts`, `useDirtyGate.ts`, `CanvasTheme.css`, `TaskDefinitionTile.tsx`, `spatialDefinitionsOrbit.ts`.
- Modified: `ModePickerCard.tsx` (dark-mode contrast — explicit text-text on header, text-text-muted on body, opaque inner card backgrounds), `AutomationsCanvasPage.tsx` (slimmed to editor host with redirect for empty `?canvas=1`), `TaskFormFields.tsx` (`hideStepEditor` prop on ContentFields), `SpatialCanvas.tsx` (orbit + dive), `spatialGeometry.ts` (`DEFINITIONS_R`).
- Deleted: `TaskTile.tsx`, `StepTile.tsx`, `useDraggableTile.ts`, `DefinitionsSidebar.tsx`.
- Dependencies added: `@xyflow/react`, `motion`.

### Parked

- Pin a task definition as a draggable workspace-canvas widget tile (separate Phase-3 idea; orbit is the primary surface).
- Pipeline-definition orbit using *recency-of-last-run* as radius (Phase-3 future per the original Phase 3 sketch).
- Drag-from-palette in the editor (click-to-add + Add-Step button stay primary).
- Foreach sub-canvas drill-down (sub-steps editable in JSON view).
- Combinator-tree builder (round-trip + JSON edit only).
- Mobile < 768 px (canvas remains desktop-only).
- Motion One animations on tile expand/collapse + editor pop-in (lib installed; not exercised yet).

## 2026-04-25 — Automations Canvas page (redirected from in-modal tab)

The previous attempt put a Canvas tab inside the existing edit modal — that was the wrong primitive. The user clarified: **the entire add-task experience** should be on a canvas, not a tab inside the modal. New shape:

- `/admin/automations` (no flag) — existing list mode, unchanged. Page header gains a "Canvas" toggle button (next to "+ New Task").
- `/admin/automations?canvas=1` — `<AutomationsCanvasPage>` mounts. Left rail = `<DefinitionsSidebar>` listing user task definitions; main area = dot-grid empty plane evoking the spatial-canvas vibe. Top-right of the plane has a "List" button (back to list mode) and a "+ New Task" button.
- `/admin/automations?canvas=1&new=1` — overlays a centered `<ModePickerCard>` on the plane (Prompt / Pipeline). On selection adds `&mode=<picked>`.
- `/admin/automations?canvas=1&new=1&mode=<prompt|pipeline>` — overlays `<EditorCard>` with the chosen mode pre-seeded (pipeline mode pre-seeds `steps=[]`).
- `/admin/automations?canvas=1&edit=<taskId>` — overlays `<EditorCard>` for the existing task. Save stays open so the user can keep iterating; X dismisses to the empty plane.

`<EditorCard>` reuses `useTaskFormState` + `<ContentFields>` + `<ExecutionFields>` + `<TriggerFields>` + `<WizardStepIndicator>` — same form components as the modal wizard, so behavior parity is automatic. v1 keeps the modal wizard at `?new=1` (today's flow) intact; canvas mode is opt-in.

### What was reverted

- `TaskFormFields.tsx` three-tab Visual / JSON / Canvas strip → reverted to two-tab Visual / JSON (the in-modal Canvas tab is gone).
- `ui/src/components/shared/task/PipelineCanvas/` (10 files: `index.tsx`, `Canvas.tsx`, `StepNode.tsx`, `EdgeLayer.tsx`, `NodesLibrary.tsx`, `ConfigPanel.tsx`, `layout.ts` + test, `edges.ts` + test) — deleted. The dedicated step-graph view inside a definition's card on the canvas plane is a future move (when we move beyond sidebar to floating-tile-per-definition).
- Phase 0 step-editor extraction stays — independent refactor.
- Phase 1 backend `Task.layout` JSONB column stays — its meaning narrows for now (no per-step positions yet on the canvas page; future home: definition's position on the global plane). Tests stay valid.

### New files

- `ui/app/(app)/admin/tasks/canvas/AutomationsCanvasPage.tsx` — orchestrator, branches on `?new=1` / `?edit=<id>` / `?mode=<picked>`.
- `ui/app/(app)/admin/tasks/canvas/DefinitionsSidebar.tsx` — left rail (filters out `source=system`).
- `ui/app/(app)/admin/tasks/canvas/ModePickerCard.tsx` — Prompt / Pipeline picker.
- `ui/app/(app)/admin/tasks/canvas/EditorCard.tsx` — the form-as-card; tabs are `Content` / `Execution` / `Trigger` via `<WizardStepIndicator>`.

### Routing branch

`ui/app/(app)/admin/tasks/index.tsx` wraps the existing list body in a sub-component (`TasksListScreen`) and the parent `TasksScreen` short-circuits to `<AutomationsCanvasPage>` when `searchParams.get("canvas") === "1"` — keeps rules-of-hooks compliance (no early-return inside the heavy hook tree).

### Parked for next session(s)

- **Definitions on the plane** — render each definition as a draggable card on the plane. Persistence: `Task.layout.canvas_position = {x, y}` (already in the column shape, just not yet wired). Sidebar can stay as a drawer or get hidden once tiles take over.
- **Pan / zoom on the canvas plane** — reuse `spatialGeometry.ts` (`Camera`, `clampCamera`, `MIN_SCALE`, `MAX_SCALE`). Skipped in v1 since one centered card doesn't need panning.
- **`/admin/automations/new` as a real route** — today the modal flow is `?new=1`. Promoting it to a route lets `?canvas=1` apply uniformly to both new + edit URLs.
- **Per-card step-graph view** — the deleted `<PipelineCanvas>` directory was a workflowbuilder.io-style step graph; it can be revived later as an embedded view inside a definition card on the plane.
- **"Canvas mode" affordance from inside the existing modal** — single button that flips the route. Polish; user explicitly called it optional.

## 2026-04-25 — Pipeline Canvas tab (workflowbuilder.io-style three-pane editor) — REVERTED

Added a third **Canvas** tab to the pipeline editor at `/admin/automations/:taskId`, modeled on workflowbuilder.io. Three panes: Nodes Library (click-to-add palette) | pannable/zoomable Canvas | Config Panel (selected step or edge fields). Same `Task.steps[]` array shape as Visual + JSON tabs; positions persist on a new top-level `Task.layout` JSONB column. The runtime never reads `layout` — it's pure UI state.

### Phase 0 — Step-editor extraction (precondition for Canvas)

`ui/src/components/shared/TaskStepEditor.tsx` was 997 LOC, at the 1000-LOC split threshold. Adding Canvas without splitting would have crossed it and forced duplicate field-editor logic between Visual + Canvas surfaces. Extracted 10 siblings into `ui/src/components/shared/task/step-editor/`:

- `MiniDropdown.tsx`, `toolSchemaHelpers.ts`, `StepConditionEditor.tsx`, `StepResultBadge.tsx`, `ToolArgsEditor.tsx`, `StepTypeSelector.tsx` (incl. `ON_FAILURE_OPTIONS`), `UserPromptFields.tsx`, `ForeachFields.tsx` (incl. `ForeachSubStepCard`), `StepCard.tsx`, `AddStepButton.tsx`.

`TaskStepEditor.tsx` shrank to 147 LOC, re-importing each sibling. Both Visual tab and Canvas Config Panel consume the same components — one source of truth.

### Phase 1 — Backend (`Task.layout`)

- **Migration 251_task_layout.py** (`down_revision = "250_heartbeat_execution_policy"`): adds `Task.layout` JSONB column, default `'{}'::jsonb`, nullable false.
- `app/db/models.py` — `layout: Mapped[dict] = mapped_column(JSONB, ...)` between `step_states` and `source`.
- `app/routers/api_v1_admin/tasks.py` — `layout` field in `TaskDetailOut`, `TaskCreateIn`, `TaskUpdateIn`. `_task_dict` surfaces it. `admin_create_task` threads it. `admin_update_task` handles it via `flag_modified` AND adds a system-pipeline guard that rejects (422) PATCH requests touching anything other than `layout` when `task.source == "system"` — matches the "system pipelines are read-only configuration except for layout" semantics.
- `app/services/task_ops.py::spawn_child_run` copies `parent.layout` to child runs as a deep copy. Child-run views render with the same node positions; later parent edits don't bleed into completed runs.
- `app/services/task_seeding.py::_SYSTEM_PIPELINE_FIELDS` — **does NOT include `layout`**. YAML never declares layout; per-installation layout is owned by the frontend. Locked by a unit test (`test_seeding_allowlist_excludes_layout`).
- `app/services/step_executor.py` — **untouched**. Layout invariant pinned by a runtime test that runs a pipeline with a sentinel layout and asserts it's unchanged after completion.

### Phase 2 — Frontend (`PipelineCanvas`)

`ui/src/components/shared/task/PipelineCanvas/`:
- `index.tsx` — three-pane shell, owns selection state.
- `Canvas.tsx` — pan/zoom plane + manual pointer-to-world drag pattern copied from `SpatialCanvas.tsx:675-729` (the Bot-tile path that fixed zoom-offset drift; explicitly avoiding the dnd-kit `delta/scale` pattern at line 657 which doesn't survive zoom).
- `StepNode.tsx` — single draggable node card.
- `EdgeLayer.tsx` — SVG edge rendering with stroke-dash + arrow markers. `<line>` hit targets are 14px wide for click ergonomics.
- `NodesLibrary.tsx` — left palette, click-to-add at viewport center (drag-to-add parked).
- `ConfigPanel.tsx` — right pane; reuses Phase-0 components for step-type-specific fields. Edge mode shows simple condition editor or read-only complex-condition summary with "Edit as JSON" link.
- `edges.ts` — `classifyWhen` (unconditional / simple / complex), `describeWhen` (label text), `buildEdges` (sequential primary edges + faint secondary edges from `when.step` references to non-immediate predecessors), `staleWhenStepRefs` (forward/missing reference detection after reorder).
- `layout.ts` — `ensurePositions` (auto-place top-down stack for unpositioned steps + prune stale entries; returns same reference when no change for cheap memoization), `setNodePosition` (immutable update).

Reused `spatialGeometry.ts` (`Camera`, `clampCamera`, `MIN_SCALE`, `MAX_SCALE`) — no fisheye lens warp on the pipeline canvas, just linear pan/zoom.

`useTasks.ts` gained `TaskLayout` type; `TaskDetail`, `TaskCreatePayload`, `TaskUpdatePayload` accept `layout`. `useTaskFormState.ts` adds `layout` state + threads it through `handleSave` for both create and update.

`TaskFormFields.tsx` Visual/JSON toggle becomes a three-tab strip: Visual / JSON / Canvas. Canvas tab hidden on `< 768px` viewports — Visual + JSON remain the mobile authoring surfaces.

### Edge model (matches runtime)

The runtime executes `steps[]` in array order. Primary edges always reflect that — never derived from `when.step`. When `when.step` references a non-immediate predecessor, a faint secondary dotted edge from that step to the current step makes the data dependency visible without misrepresenting execution flow.

Edge classification:
- `unconditional` — `when` absent/empty: solid line, no badge.
- `simple` — only `{step, status?, output_contains?, output_not_contains?}`: dashed line + readable label ("if status = done").
- `complex` — `all` / `any` / `not` / `param` / unrecognized keys: dashed line + neutral "conditional" badge; Config Panel shows JSON dump + "Edit as JSON" link routing to the JSON tab. **Conditions are never re-shaped on save.** Pinned by a parametrized backend round-trip test covering 5 complex `when` shapes.

Reordering does NOT rewrite `when.step` references — preserves user intent. Forward / missing references after reorder surface as a warning chip on the affected node.

### Tests (~25 new across backend + frontend)

Backend: `tests/integration/test_admin_tasks_layout.py` (round-trip, system-pipeline guard); `tests/integration/test_when_round_trip.py` (parametrized over complex condition shapes); `tests/unit/test_system_pipelines.py` gained `test_spawn_child_run_copies_layout`, `test_layout_untouched_by_reseed`, `test_seeding_allowlist_excludes_layout`; `tests/unit/test_step_executor.py::TestRunTaskPipeline::test_layout_is_invariant_through_pipeline_run`.

Frontend (existing `node:assert` convention, no new test runner): `ui/.../PipelineCanvas/edges.test.ts` (classifyWhen, describeWhen, buildEdges sequential primary + secondary, staleWhenStepRefs forward/missing/valid); `ui/.../PipelineCanvas/layout.test.ts` (ensurePositions auto-place + preserve + prune + no-op reference equality, setNodePosition immutability).

Verification: `pytest tests/integration/test_admin_tasks_layout.py tests/integration/test_when_round_trip.py tests/unit/test_system_pipelines.py tests/unit/test_step_executor.py tests/integration/test_admin_task_list.py tests/integration/test_channel_pipelines_api.py -q` → 167 passed (in Docker). `cd ui && npx tsc --noEmit` clean.

Plan: `~/.claude/plans/can-we-plan-something-snoopy-yeti.md` — Phases 0, 1, 2 shipped this session. Phase 3 (workspace spatial canvas integration via new `core/pipeline_summary` native widget pinned through existing `widget_dashboard_pins` + `workspace_spatial_nodes`) is parked as the next session's work — keeps the "no new node type on `workspace_spatial_nodes`" boundary.

### Out of scope / parked

- Drag-to-add from Nodes Library (click-to-add ships first; pointer-up + pointer-to-world drop target is a follow-up).
- Drill-down `foreach` sub-canvas (sub-steps live in Config Panel).
- Combinator tree builder for `all`/`any`/`not` — round-trip works; UI exposure deferred until a real pipeline outgrows the simple-condition surface.
- React-rendering frontend tests for tab-switch preservation, no-PATCH-on-drag, etc. — repo has no React test runner; pure-function behavior is covered above; UI behavior verified via typecheck + manual smoke.
- Manual e2e smoke on the live instance — not run this session.

## 2026-04-25 — Vocabulary cleanup (Task overload triage)

The bare word "Task" was overloaded across six execution models (Scheduled prompt, Pipeline definition, Sub-session, Delegation, Standing order, Heartbeat run, Background worker). The bot tool surface conflated single-prompt scheduled work with multi-step Pipeline definitions in one tool — `schedule_task(prompt=..., steps=...)` — which the LLM struggled to disambiguate. Three-part cleanup landed in one pass:

- **`docs/guides/ubiquitous-language.md`** — added a new "Automations and scheduled work" section with seven precise terms (Automation umbrella, Scheduled prompt, Pipeline, Run, Delegation, Sub-agent, Heartbeat run, Standing order, Background worker) and a new flagged ambiguity entry "Task is overloaded — use a precise term." Heartbeat run moved out of the Sessions table into Automations.
- **Bot tool surface** — `schedule_task` removed; replaced with two tools: `schedule_prompt` (single-prompt, no `steps` arg, in `app/tools/local/tasks.py`) and `define_pipeline` (multi-step, requires `steps`, in `app/tools/local/pipelines.py`). Both share a private `_create_task_row` helper. `list_tasks` / `cancel_task` / `update_task` / `get_task_result` / `run_task` descriptions tightened to use the new vocabulary. Widget templates renamed (`widgets/schedule_task/` → `widgets/schedule_prompt/`; new `widgets/define_pipeline/`).
- **Admin UI** — `/admin/tasks` route renamed to `/admin/automations`. Old route returns a permanent redirect via `<Navigate>` and the new `RedirectToAutomation` helper; existing detail pages still work. Page label "Tasks" → "Automations" everywhere it surfaces (palette, sidebar rail, settings index, spatial canvas NowWell tooltip, all "View task" button copy in TaskRunEnvelope / TriggerCard / TaskEditor).

`spawn_subagents` was considered for renaming but explicitly **deferred** — the readonly boundary is enforced in `app/agent/subagents.py:48` regardless of verb. Revisit only if a future session shows the LLM still confusing it with `delegate_to_agent`.

Skills updated: `skills/pipelines/{index,creation}.md`, `skills/orchestrator/{index,workspace_delegation}.md`, `skills/workspace/member.md`, `skills/widgets/handlers.md`. Docs updated: `docs/index.md`, `docs/guides/{pipelines,widget-dashboards,tool-policies,workflows}.md`, `docs/reference/widget-inventory.md`. Tests updated: 8 unit + integration files (mostly `from app.tools.local.tasks import schedule_prompt as schedule_task` aliases to keep the existing test bodies). One pre-existing broken assertion in `test_task_title.py` (asserted `"queued" in result` against a JSON string) tightened to parse JSON. Two other pre-existing `TestListTasksTitle` failures are unrelated (MagicMock JSON-serializability) and predate this work.

Verification: `pytest tests/unit/test_task_tools.py tests/unit/test_task_title.py tests/unit/test_phase0_smoke.py tests/unit/test_security_hardening.py::TestTaskCreationRateLimit tests/integration/test_widget_catalog_api.py tests/unit/test_widget_packages_seeder.py tests/unit/test_canonical_docs_drift.py` → 78 passed, 2 pre-existing fails unrelated to vocabulary work. UI `npx tsc --noEmit` clean.

Plan: `~/.claude/plans/cna-we-please-do-expressive-koala.md`.

## 2026-04-20 — Audit pipelines demoted; configurator skill replaces ambient surface

Five featured audit pipelines (`full_scan`, `analyze_skill_quality`, `analyze_memory_quality`, `analyze_tool_usage`, `analyze_costs`) flipped to `featured: false` in their YAML. Only `orchestrator.analyze_discovery` remains featured (evidence-backed, produces apply-worthy proposals). Demoted YAMLs stay on disk — users who want a structured batch-audit run them from the Library drawer. No subscriptions were touched.

The driving problem: Full System Scan accumulated 18 stuck awaiting-review findings because "audit every knob in one pass" can't produce ≥2 real correlation_ids per proposal, so the foreach step either refused to emit or emitted weak proposals that the user couldn't confidently approve. Analyze Discovery works because its scope is narrow (one bot, one RAG knob, quantitative trace evidence).

Replacement for the ambient "fix my config" UX is the **configurator skill + `propose_config_change` tool** (new in `skills/configurator/` folder layout + `app/tools/local/propose_config_change.py`). The tool uses the existing tool-policy approval gate (`safety_tier="mutating"`, `TOOL_POLICY_DEFAULT_ACTION=require_approval` default) rather than a bespoke review widget. Structured `InlineApprovalReview`-style widget is a follow-up.

Plan: `~/.claude/plans/scalable-prancing-music.md`. Side effect: skill loader now supports folder layout (`skills/<name>/index.md` + `skills/<name>/<sub>.md`), unblocking Widget Library Phase 3.

## Current State (2026-04-15)
- Backend: `app/services/step_executor.py` — pipeline runner, shared condition/prompt/context functions
- Migration 199: `steps` + `step_states` JSONB columns on tasks
- UI: `Prompt | Steps` toggle in task create/edit, step cards with condition editor + tool selector
- Workflows: deprecated, hidden from admin nav, backend preserved

## Gaps (priority order)

### 1. Run History (High)
**Problem**: Pipeline executions overwrite `step_states` on the task row. Cron-triggered pipelines lose all history — you can only see the latest run.

**Design needed**: Separate `TaskRun` table (or equivalent) that captures per-execution step_states, timestamps, trigger source, and aggregated result. Similar to how `WorkflowRun` worked, but scoped to tasks.

**UX questions**:
- Where does run history surface? Task detail page? Channel sidebar?
- How much history to retain? (Cap by count or age?)
- Should run history be visible in the task list view?

### 2. Approval Gates — SHIPPED 2026-04-17 (backend + pipelines + admin editor; channel Findings still pending)
Ships as the `user_prompt` step type. Pipeline pauses with `step_states[i].status = "awaiting_user_input"`, a rendered widget envelope, and a response schema (`binary` or `multi_item` in v1). Resolved via `POST /api/v1/admin/tasks/{id}/steps/{index}/resolve` — validated, fills `result`, flips to `done`, calls `_advance_pipeline(start_index=i+1)`.

Used by the orchestrator system pipelines (below) to gate apply-patches behind multi-item review. Admin editor support for authoring `user_prompt` + `foreach` steps landed 2026-04-17 (see Done list). **What remains**: the in-channel Findings panel + widget rendering for actually resolving `awaiting_user_input` steps — part of Phase 4B of the orchestrator restructure (see [[#Phase 4B — Orchestrator channel UI]] below).

### 3. Channel Presence (Medium)
**Problem**: If a pipeline task is bound to a channel, there's no in-channel indication that it's running, completed, or failed. The user has to go to admin → tasks to see status.

**Design needed**: Reuse concepts from `ActiveWorkflowStrip.tsx` — a strip/banner in the channel UI showing active pipeline runs with step progress. Could also surface in the channel's existing Tasks tab.

### 4. Reusable Templates (Low)
**Problem**: Every pipeline is defined inline on a specific task. No way to say "run this standard pipeline with different params."

**Design needed**: Could be as simple as a "Clone task" button (already exists for tasks) or as complex as a template library with param injection. The existing YAML workflow definitions (`workflows/*.yaml`) could seed a template gallery.

**Not urgent**: Most automations are one-offs. Templates are a power-user feature.

## Done
- [x] Backend step_executor with exec/tool/agent steps (2026-04-15)
- [x] Pipeline routing in task runner (2026-04-15)
- [x] Agent step callbacks (child task → pipeline resumption) (2026-04-15)
- [x] UI step editor with tool selector + condition builder (2026-04-15)
- [x] Shared functions extracted from workflow_executor (2026-04-15)
- [x] Architecture decision documented (2026-04-15)
- [x] Workflow UI hidden from admin nav (2026-04-15)
- [x] Unit tests for step_executor pure functions + pipeline execution (2026-04-15)
- [x] Bot tool enrichment for full definition management (2026-04-16)
  - `list_tasks` detail mode: steps, step_states, execution_config, trigger_config, task_type
  - `get_task_result`: step_states, step_count, parent_task_id
  - `update_task`: steps, execution_config, trigger_config params
  - `schedule_task`: trigger_config param for event-triggered tasks
  - `list_tasks`: parent_task_id param for run history
  - New `run_task` tool: manual trigger of task definitions
  - Shared `spawn_child_run()` in `app/services/task_ops.py`
  - Admin API refactored to use shared helper
  - Pipeline Creation skill updated with management docs
- [x] **Per-step `skills:` on agent steps** (2026-04-17) — `step_executor._spawn_agent_step` now forwards `step_def["skills"]` into child `execution_config["skills"]`, wired into existing `set_ephemeral_skills` runtime path. Matches the `tools` / `carapaces` surface; ephemeral per-step, no pipeline-level `defaults:` block (kept intentional — steps stay self-contained). Regression test at `tests/unit/test_step_executor.py::TestSpawnAgentStep::test_forwards_skills_tools_carapaces_to_execution_config`. Runtime still supports `exclude_tools` / `allowed_secrets` / `fallback_models` that step_executor doesn't forward — parked, not urgent.
- [x] **Pipeline docs + authoring skills updated for new step types** (2026-04-17) — new `docs/guides/pipelines.md` primer covering all five step types (exec / tool / agent / user_prompt / foreach), params, templates, conditions. Linked from `docs/index.md`. `skills/pipeline_authoring.md` extended with user_prompt + foreach + params sections and `use_when` frontmatter; `skills/pipeline_creation.md` extended with user_prompt-vs-agent-question and foreach-vs-agent-loop decision notes, plus review→approve→apply pattern.
- [x] **Admin task editor UI for `user_prompt` + `foreach`** (2026-04-17, Phase 4A)
  - `StepType` / `StepDef` / `StepState` widened in `ui/src/api/hooks/useTasks.ts` (adds `awaiting_user_input`, `ResponseSchema`, `TaskSource`, `source` on TaskDetail/TaskItem).
  - New shared `ui/src/components/shared/task/JsonObjectEditor.tsx` — compact highlight-textarea JSON editor for `widget_template` / `widget_args` / nested objects. Supports optional schema skeleton insert + copy.
  - `TaskStepEditor.tsx` gains:
    - Two new `STEP_TYPES` entries (`user_prompt` = teal MessageCircleQuestion, `foreach` = fuchsia Repeat).
    - `UserPromptFields` (title input + response_schema picker [binary | multi_item + items_ref] + two `JsonObjectEditor`s for widget_template / widget_args with "Insert skeleton" scaffold).
    - `ForeachFields` + `ForeachSubStepCard` — `over` expression input, `on_failure` dropdown via existing `MiniDropdown`, nested `do` sub-step list. v1 restricts sub-step type to `tool` only (shows "v1 supports only `tool` sub-steps" hint); reuses existing `ToolSelector` + `ToolArgsEditor`.
    - Unknown-step-type fallback card — renders when `step.type` isn't in the known list. Shows a raw JSON dump in a read-only `<pre>` and a banner directing to the JSON view. Critical for safety: seeded system tasks now contain unknown-to-some-UI-versions types.
    - `StepResultBadge` extended with `awaiting_user_input` → pulsing accent `PauseCircle`.
  - `StepsJsonEditor.tsx` — `ALLOWED_STEP_TYPES` widened, validation recurses into `foreach.do`.
  - `StepsSchemaModal.tsx` — schema reference text extended with both new step types + an "Approval Gate + Batch Apply" YAML example.
  - **Admin task list filtering**: `ui/app/(app)/admin/tasks/index.tsx` hides `source=system` rows by default (localStorage-persisted `showSystem` toggle chip — "N system hidden" or "System on"). `TaskDefinitionsView` renders a `<SystemBadge />` pill inline with titles when the toggle is on.
  - **Admin task detail read-only**: `isSystemSeeded` flag hides Save/Delete/Enable buttons and keeps Run-Now live. Banner: "System pipeline — seeded from `app/data/system_pipelines/{id}.yaml`. Edits are overwritten on server restart." OverviewTab wrapped in a `<fieldset disabled>` when read-only so inputs still show but can't be edited. `STEP_STATUS_ICON` + color map extend to `awaiting_user_input` → pulsing accent.
  - Typecheck: `npx tsc --noEmit` clean (enforced by hook).
  - Untested in browser: no dev-server smoke was run this session — see next-session UX verification steps below.
- [x] **System pipelines + `user_prompt` + `foreach` primitives** (2026-04-17)
  - Migration 202 adds `Task.source` column (`user` default, `system` for seeded).
  - `app/services/task_seeding.py` — `ensure_system_pipelines()` on lifespan, refreshes `source=system` rows from `app/data/system_pipelines/*.yaml`, refuses to clobber user-owned id collisions.
  - `POST /tasks/{id}/run` accepts `params: dict` body → merged into child's `execution_config["params"]`; `{{params.*}}` substitution in step templates.
  - `user_prompt` step type: pauses pipeline with `awaiting_user_input` status + widget envelope + response schema (binary | multi_item). Resolved via `POST /tasks/{id}/steps/{index}/resolve`.
  - `foreach` step type: sequential iteration over a list from `{{steps.*}}` / `{{params.*}}`, runs `do` sub-steps (tool only in v1) per item with `{{item.*}}`, `{{item_index}}`, `{{item_count}}` bound. `on_failure: abort|continue`.
  - Three seeded orchestrator pipelines in `app/data/system_pipelines/`: `orchestrator.full_scan.yaml`, `orchestrator.deep_dive_bot.yaml`, `orchestrator.analyze_discovery.yaml`. Each composes `tool` → `agent` → `user_prompt` → `foreach → call_api` — zero bespoke apply-tools. Existing validated PATCH endpoints do the work.
  - Orchestrator bot YAML extended with `api_permissions` for scan scopes (`bots/skills/tools/tasks/traces` ×read/write).
  - Tests: 14 unit `test_system_pipelines.py`, 16 unit `test_user_prompt_step.py`, 19 unit `test_foreach_step.py`, 7 integration `test_resolve_endpoint.py`, 5 integration `test_orchestrator_pipelines.py`. All green, full existing suite passes.

## Phase 4B — Orchestrator channel UI (SHIPPED 2026-04-17, session 13)

Plan: `~/.claude/plans/clever-snuggling-marble.md`. Vercel/Linear deploy-panel aesthetic. All four pieces landed in a single session; typecheck clean throughout.

**What landed** (files in `ui/app/(app)/channels/[channelId]/` unless noted):

- **4B.1 Header chrome** — yellow banner deleted from `index.tsx:428-445`. `ChannelHeader.tsx` gains `isSystemChannel` prop that switches Hash→Cog icon, renders a compact `SYSTEM` pill (`bg-accent/10 text-accent border-accent/30`) next to the channel title, and shows a `"System configuration channel"` subtitle. New `toggleFindingsPanel` + `findingsCount` props render a `PanelRight` toggle with accent badge.
- **4B.2 Launchpad** — new `OrchestratorEmptyState.tsx`. Hero-tile grid (`grid-cols-1 md:grid-cols-2`) over `source=system` tasks with `execution_config.featured === true`. Hover-reveal "Last run Xm ago" chip (polls `useTaskChildren` every 5s — also drives Running state). Library drawer for non-featured system pipelines (collapsed by default). Inline `TaskRunModal` for pipelines with `execution_config.params_schema` — `bot_id` fields wire to `BotPicker`, generic strings get text inputs. Injects via new `emptyStateComponent?: React.ReactNode` prop on `ChatMessageArea.tsx` (channel-agnostic — any channel can override the empty state).
- **4B.3 Findings panel** — new `FindingsPanel.tsx` exports `FindingsPanel` (desktop right rail, 320px), `FindingsSheet` (mobile bottom sheet, 85vh), and a shared `useFindings(channelId)` hook that collapses to a single `react-query` fetch. Filter walks `step_states` for `status === "awaiting_user_input"` client-side; backend `?step_status=` filter parked as a trivial follow-up. Each finding card renders the stored `widget_envelope` through the existing `ComponentRenderer` — Approve/Reject buttons in the envelope already dispatch via `useWidgetAction` to `/api/v1/admin/tasks/{id}/steps/{i}/resolve` (no new hook, no new allowlist).
- **4B.4 Sidebar SYSTEM section** — `ChannelList.tsx:330` wraps `OrchestratorItem` in a `SYSTEM` section header using the existing `sidebar-section-label` class. `OrchestratorItem` visual tightened to match regular channel items (same padding scale, same font-weight map, no redundant Shield accessory).

**Hook changes**:
- `useRunTaskNow()` extended to accept `string | RunTaskArgs` where `RunTaskArgs = {taskId, params?}`. Payload-only when params is non-empty — existing callers (`admin/tasks/index.tsx`, `admin/tasks/[taskId]/index.tsx`) kept their string-arg signature; the admin list read of `runNowMut.variables` got a runtime type-narrow.

**Easy-win generalizations** (fell out of the primitives cleanly, no extra work):
- `emptyStateComponent` prop on `ChatMessageArea` is channel-agnostic — any channel can inject a custom empty state (DMs, private channels, etc.) without further plumbing.
- `useFindings(channelId)` is keyed on `channelId`, not hardcoded to `orchestrator:home`. Any channel with a task pipeline bound to it could surface its awaiting-input steps in the same right-rail treatment; the mount condition in `channels/[channelId]/index.tsx` is the only gate.

**Not done / explicitly parked for follow-up**:
- Backend `?source=user|system` and `?step_status=<status>` query params on `GET /api/v1/admin/tasks` — deferred; client-side filters work for v1 traffic volumes.
- Recent-runs strip (Zone B in the original plan) — skipped for now; the Last-run chip on each hero tile covers the same information without adding a second row that's empty on a fresh install.
- Mobile Findings: implemented as bottom sheet (`FindingsSheet`). Could use a real drag-to-dismiss gesture — v1 uses backdrop tap + X button.
- Per-item `when:` gating inside `foreach` (Loose Ends #50), `run_history` table (Gap #1), free-form text `user_prompt`, Findings history view — all parked per original scope.

**Verification still owed**: browser smoke on the e2e instance per the plan's verification checklist (load orchestrator channel, click Full Scan tile, verify review widget appears inline + in Findings panel, verify approve→foreach→PATCH works end-to-end).

## Phase 4B — Original plan reference (archived)

Approved plan: `~/.claude/plans/shimmering-giggling-fog.md` Phase 4 (§Phase 4 — Orchestrator channel UI). That plan's backend phases 1–3 shipped (session 10); phase 4A (admin editor UI) shipped 2026-04-17 (above). Phase 4B is the channel-facing surface — the actual "resolve awaiting_user_input" path for humans + the launcher for starting scans.

**North star**: the orchestrator channel becomes a structured command center, not a chat. Launch pipelines via tiles → watch steps stream into the anchor message → approve/reject in a right-rail Findings panel → foreach applies the approved subset through `call_api`.

**Scope (4 discrete pieces):**

### 4B.1 — Replace the yellow admin banner with distinct chrome
- `ui/app/(app)/channels/[channelId]/index.tsx:428` currently renders an inline yellow `Shield` banner ("System admin channel — this bot has unrestricted tool access..."). Replace with accent-ring header chrome + subtitle "System configuration channel". Detection stays on `client_id === "orchestrator:home"` — no `channel_kind` column.
- New code: use Tailwind classes (no inline styles — see `feedback_tailwind_not_inline.md` in auto-memory).

### 4B.2 — Empty-state launchpad (OrchestratorEmptyState.tsx)
- New component: `ui/app/(app)/channels/[channelId]/OrchestratorEmptyState.tsx`.
- Mounts when `channel.client_id === "orchestrator:home"` AND `invertedData.length === 0 && !isLoading` — inject via prop into `ChatMessageArea.tsx:226` (current hardcoded "Send a message to start the conversation" span).
- Three zones per approved plan:
  1. **Recent runs strip** — `GET /api/v1/admin/tasks?parent_task_id=<pipeline_id>&limit=3` grouped by pipeline, small horizontal cards. Click → scroll to / open run's anchor message.
  2. **Hero tiles** — canonical pipelines from `source=system` Tasks with `execution_config.featured === true`. Three live today: `orchestrator.full_scan`, `orchestrator.deep_dive_bot`, `orchestrator.analyze_discovery`. Each tile: icon + title (from `Task.title`) + description (from `execution_config.description`) + "Run" affordance. Click → if pipeline declares params → param-picker modal (reuse `ConfirmDialog` or new lightweight modal) → `POST /api/v1/admin/tasks/{id}/run` with `{params}` body.
  3. **Library drawer** (optional for v1) — collapsed by default, expands to show all other `source=system` pipelines. Skip entirely if we only have 3 featured pipelines — revisit when the library grows.
- Tile click affordance: `HomeGrid.tsx:314` (hero banner) or `HomeGridTile.tsx` compact pattern — match UI audit findings. Hover: surface elevation + accent ring.
- Running-state affordance on a tile: poll `useTaskChildren(taskId)` and show "Running..." + spinner when any child is `status === "running"`. Prevents double-triggering.

### 4B.3 — Findings panel (FindingsPanel.tsx)
- New component: `ui/app/(app)/channels/[channelId]/FindingsPanel.tsx` — right-rail panel. Reuse `HudSidePanel` structure (`ui/app/(app)/channels/[channelId]/hud/HudSidePanel.tsx`) — 320px width, border-left, surface-raised background.
- Content: lists pipelines where any step has `status === "awaiting_user_input"`, scoped to `channel_id=orchestrator:home`. Backend filter doesn't exist yet → **client-side filter** against `GET /admin/tasks?limit=200` (or add a lightweight `step_status` param to the tasks router as a trivial follow-up).
- Each finding: title (pipeline name), subtitle (bot + when triggered), stored `widget_envelope` rendered inline via existing `ComponentRenderer` (`ui/src/components/chat/renderers/ComponentRenderer.tsx`). Buttons use `dispatch: "api"` (already supported via `useWidgetAction.ts`) to POST `/api/v1/admin/tasks/{id}/steps/{i}/resolve`.
- Mount conditionally at `ui/app/(app)/channels/[channelId]/index.tsx:591` next to `HudSidePanel` / `PinnedPanelsRail`, toggled from a header button with a badge count ("3 pending reviews").
- Empty state: "No pending reviews" with a subtle Cog icon.
- `broadcastEnvelope` store (shipped with widget pin work) keeps inline widget and findings-panel rendering in sync when the same prompt is viewed in both places.

### 4B.4 — Sidebar "System" section
- `ui/src/components/layout/sidebar/ChannelList.tsx:168` — extract `OrchestratorItem` into a new section labeled `SYSTEM` (uppercase, same `sidebar-section-label` styling as `CHANNELS`). Keeps orchestrator visually distinct from regular conversations. `SidebarFooter.tsx:114` rail fast-access icon stays.
- When additional system channels land (future), they belong in this section.

### 4B Gotchas / notes for the implementor

- **Widget-action allowlist**: `/api/v1/admin/tasks/.../steps/{i}/resolve` already matches the `_dispatch_api` `startswith("/api/v1/admin/tasks")` allowlist — no backend change needed.
- **`ComponentRenderer` shape**: `{v: 1, components: ComponentNode[]}`. The `user_prompt` step stores rendered `widget_envelope` in `step_states[i].widget_envelope` — pass that straight to `ComponentRenderer`.
- **Button dispatch**: actions already supported — see `useWidgetAction.ts:76` for the `dispatch === "api"` case. The `user_prompt` widget templates need Approve/Reject buttons with `action: {dispatch: "api", endpoint: "/api/v1/admin/tasks/{id}/steps/{i}/resolve", method: "POST", args: {response: ...}}`.
- **Source filter** on `GET /admin/tasks`: adding a `?source=user|system` query param is a trivial backend follow-up that would let the Findings panel do a targeted fetch instead of full-list-then-client-filter. Not required for v1 but nice hygiene.
- **Do NOT introduce `channel_kind`**: all detection is `client_id === "orchestrator:home"`. This is the canonical decision (session 10 gotchas, plan §Architecture).
- **Tailwind-only**: the existing `channels/[channelId]/index.tsx` is inline-style-heavy and is known-legacy (Web-Native Phase 3 is unwinding it). New code must be Tailwind. See `feedback_tailwind_not_inline.md`.
- **ESM admin channel check**: the banner at line 428 is the only orchestrator-specific UI today; everywhere else uses `client_id`. Touching this file means rebasing against Phase 3's column-reverse refactor — read `ChatMessageArea.tsx` before changing it (chat scroll is finicky; see `feedback_broader_vision_over_band_aid.md`).

### 4B Verification plan

1. Open orchestrator channel empty → hero tiles render with icons + descriptions; yellow banner is gone.
2. Click **Full Scan** tile → anchor message streams steps 1–3 (fetch_bots, fetch_endpoints, analyze).
3. Step 4 (`review`, user_prompt, multi_item) renders widget inline AND in Findings panel with pending badge count.
4. Approve one proposal, reject one, leave one unresolved → `foreach` iterates only the approved item, `call_api` fires the PATCH, DB reflects the change. Unresolved item's iteration is skipped (already covered by step_executor tests).
5. Findings panel drains resolved items; badge count decrements.
6. Start **Deep Dive Bot** → param-picker prompts for `bot_id` before launching; only that bot is patched.
7. Sidebar shows `SYSTEM` section above `CHANNELS`; Orchestrator listed there.
8. Confirm no yellow banner anywhere on orchestrator channel.

### 4B Explicitly parked (do not expand scope)

- Ambient scanning, slash commands, autoresearch eval loop, free-form text in `user_prompt`, Findings history view, `pin_widget` tool, user-authored orchestrator pipelines, route-level `/orchestrator` separation, parallel `foreach`, bespoke apply-patch tools — all parked in the original plan (`~/.claude/plans/shimmering-giggling-fog.md` §Explicitly parked).

## Status summary

| Phase | State | File / Plan |
|---|---|---|
| 1. System pipeline primitive | SHIPPED 2026-04-17 | `app/services/task_seeding.py`, migration 202 |
| 2a. `user_prompt` step + resolve endpoint | SHIPPED 2026-04-17 | `app/services/step_executor.py`, `tasks.py:/resolve` |
| 2b. `foreach` step | SHIPPED 2026-04-17 | `app/services/step_executor.py` |
| 3. Orchestrator pipelines | SHIPPED 2026-04-17 | `app/data/system_pipelines/*.yaml` |
| 4A. Admin task editor UI | SHIPPED 2026-04-17 | `TaskStepEditor.tsx`, `JsonObjectEditor.tsx`, task list + detail |
| 4B. Orchestrator channel UI | SHIPPED 2026-04-17 | `OrchestratorEmptyState.tsx`, `FindingsPanel.tsx`, `ChannelHeader.tsx`, `ChannelList.tsx` |
| 4C. Launch-context + UI fixes | SHIPPED 2026-04-17 | `execution_config.requires_channel`, `get_trace` list mode, approval_review renderer, auto-skip empty reviews |
| 5. Channel-scoped pipeline UX | SHIPPED 2026-04-17 | See §Phase 5 below |

## Phase 5 — Channel-scoped pipeline UX (SHIPPED 2026-04-17, session 15)

Plan: `~/.claude/plans/imperative-jumping-donut.md`. All proposed pieces landed in one session; UI typecheck clean; 212 focused backend tests green.

**What landed**:
- **5.1 Subscription table** — migration `204_channel_pipeline_subscriptions.py`, `ChannelPipelineSubscription` model in `app/db/models.py`. Columns: `channel_id/task_id (FK, cascade)`, `enabled`, `featured_override (bool|null)`, `schedule (cron)`, `schedule_config (jsonb)`, `last_fired_at`, `next_fire_at`, `UNIQUE(channel_id, task_id)`. Seed on migration auto-subscribes every existing `source=system` task to the orchestrator channel.
- **5.2 Admin routes** — new `app/routers/api_v1_admin/channel_pipelines.py`: `GET/POST /channels/{id}/pipelines`, `PATCH/DELETE /channels/{id}/pipelines/{sub_id}`, mirror `GET /tasks/{id}/subscriptions`. Server-side cron validation via `app/services/cron_utils.py` (croniter).
- **5.3 Cron scheduler** — `spawn_due_subscriptions()` in `app/agent/tasks.py` wired into `task_worker` loop right after `spawn_due_schedules()`. On fire: atomically advance `next_fire_at`, persist `last_fired_at`, then call `spawn_child_run(task_id, channel_id=sub.channel_id, params=schedule_config.params)`.
- **5.4 Admin tasks enrichment** — `?source=user|system` filter + `subscription_count` field on list + detail responses (one subquery batched).
- **5.5 Step failure signaling** — `_detect_error_payload()` flags tool results with non-null `error` JSON key; `_evaluate_fail_if()` + `_apply_fail_if_to_state()` support `fail_if: {result_empty_keys: [...]}` and implicit self-reference for `output_contains`. Applied in each step-type block in `_advance_pipeline` and in `on_pipeline_step_completed` (agent callback).
- **5.7 Delete WorkflowsTab** — removed from channel settings; `WorkflowsTab.tsx` deleted. Admin `/workflows` page left alone (separate cleanup).
- **5.8 PipelinesTab** — new `ui/app/(app)/channels/[channelId]/PipelinesTab.tsx` with subscribed/available sections. Each row: featured star (tri-cycle via override), enable toggle, schedule button (opens CronScheduleModal), link to pipeline definition, unsubscribe.
- **5.9 CronScheduleModal + CronInput** — `ui/src/components/shared/CronInput.tsx` + `CronScheduleModal.tsx`. Client-side 5-field shape validation, preset chips (Hourly, Every 6h, Daily 2am, Weekdays 9am, Weekly Mon). Server re-validates with croniter.
- **5.10 Launchpad rewire** — `OrchestratorEmptyState.tsx` now fetches `GET /admin/channels/{id}/pipelines?enabled=true` instead of the global definitions list. Subscription's `featured` (override-or-default) drives tile vs library split. Synthesized `TaskItem` shape preserves downstream compatibility.
- **5.11 Pipeline mode mount condition** — `channels/[channelId]/index.tsx` no longer gates launchpad on `client_id === "orchestrator:home"`. New derived flag: `launchpadVisible = pipeline_mode === "on" || (pipeline_mode === "auto" && hasSubscriptions)`.
- **5.12 Automation section** — new "Automation" section in `GeneralTab.tsx` with tri-state select (Auto / On / Off) backed by `channel.config.pipeline_mode`. Server shallow-merges into `channel.config` JSONB via `PATCH /channels/{id}/settings`.
- **5.13 Admin tasks Used By column** — `TaskDefinitionsView.tsx` shows subscription count pill between Trigger and Last Run.
- **5.14 Admin task detail Subscribed Channels panel** — new `SubscribedChannelsSection` in `admin/tasks/[taskId]/index.tsx` for pipeline-type tasks. Per-row enable toggle, schedule edit (CronScheduleModal), unsubscribe, link back to channel settings.

**Tests**:
- `tests/unit/test_step_executor.py` — 14 new assertions covering `_detect_error_payload`, `_evaluate_fail_if`, `_apply_fail_if_to_state` (including preserving the raw result when flipping to failed).
- `tests/unit/test_subscription_scheduler.py` — cron validation + `_fire_subscription` advance/skip/invalid-cron paths.
- `tests/integration/test_channel_pipelines_api.py` — subscribe/list/patch/delete/enabled-only/schedule-compute/clear-schedule/invalid-cron/featured-resolution/task-mirror/subscription_count/source-filter.
- Regression: full existing relevant suite (212 tests) green in Docker.

**One pre-existing flaky test (NOT a Phase 5 regression)**: `test_resolve_endpoint.py::test_happy_path_fills_result_and_advances` compares `step["result"]` to a dict literal, but the endpoint explicitly `json.dumps(...)` the response (intentional per inline comment). Fails on master without Phase 5 changes.

**Deferred** (carried to follow-up):
- Bot tool descriptions (`list_tasks`, `run_task`) still talk about "task" vs "pipeline" — small docs/prompt sweep.
- `Task.recurrence` → subscription migration path for legacy channel-scheduled prompt tasks.
- `/admin/workflows` route removal.
- Drop `Task.workflow_id / workflow_run_id / workflow_session_mode` columns (dormant backend).
- Parallel `foreach`, free-form `user_prompt` text, bulk multi-channel subscribe.

## Phase 5 — Original handoff (archived)

Session 14 shipped the orchestrator channel UI, fixed rendering crashes in Findings (`approval_review` needed a real renderer — ComponentRenderer has a different vocabulary), and introduced `execution_config.requires_channel` / `requires_bot` so pipelines can be launched into any channel (channel UUID supplied at launch time, cascades to the child run via `spawn_child_run`). The three system pipelines are now launched from the orchestrator channel and dispatch their anchor messages / approval widgets inline in chat.

What's exposed afterwards: the launchpad globally lists every `source=system` pipeline. There's no per-channel enablement, no per-channel schedule, and no way for an agent step to signal a "soft failure" when its own output tells the user it couldn't complete the task. Three discrete pieces for next session.

### 5.1 — Per-channel pipeline enablement / visibility

**Problem**: `OrchestratorLaunchpad` fetches all `source=system` tasks and shows every one. When pipelines multiply (or user-authored pipelines join `source=user`), any channel with the launchpad mounted will see them all. A team channel shouldn't see a "Deep Dive Bot" tile meant only for the orchestrator channel.

**Proposed shape**:
- New junction table `channel_pipeline_subscriptions` — columns: `id (uuid)`, `channel_id (uuid, FK)`, `task_id (uuid, FK)` (the pipeline definition), `enabled (bool, default true)`, `featured_override (bool | null)` (null = fall back to pipeline's `execution_config.featured`), `schedule (text | null)`, `schedule_config (jsonb | null)`, `created_at`, `updated_at`. Unique `(channel_id, task_id)`.
- Migration: DDL + seed every existing system pipeline as subscribed to the orchestrator channel (so no regression in what currently shows up there).
- Admin API:
  - `GET /api/v1/admin/channels/{id}/pipelines` → list subscriptions + pipeline detail join
  - `POST /api/v1/admin/channels/{id}/pipelines` body `{task_id, enabled?, featured_override?}` → subscribe
  - `PATCH /api/v1/admin/channels/{id}/pipelines/{subscription_id}` → update enabled/featured/schedule
  - `DELETE /api/v1/admin/channels/{id}/pipelines/{subscription_id}` → unsubscribe
- Launchpad data switch: replace `GET /api/v1/admin/tasks?definitions_only=true` with `GET /api/v1/admin/channels/{channelId}/pipelines`. Featured now computed from the join (`featured_override ?? pipeline.execution_config.featured`).
- Channel settings UI: add a "Pipelines" tab at `ui/app/(app)/channels/[channelId]/settings.tsx` (sibling to Context, Heartbeat, Tasks, Integrations tabs). List available system + user-authored pipelines with checkboxes to enable, chips to mark featured, inline `+ Schedule` button.
- Feature flag: for the orchestrator channel specifically, treat any unsubscribed pipeline as "visible in library drawer, greyed out" so the admin UI pathway is discoverable. Optional.

**Open questions / judgment calls**:
- Do user-authored pipelines (`source=user`) auto-subscribe to their `channel_id` at create time? Probably yes — a task you create on a channel should show up in that channel's launchpad by default.
- What happens when a pipeline definition is deleted? Cascade via FK.
- Is there a global "always visible" pipeline mode? Maybe via a `scope: "global"` column on the pipeline itself (bypasses the subscription table). Skip for v1.

### 5.2 — Per-channel scheduling of shared pipelines

**Problem**: Today, a Task definition carries its own `recurrence` and `scheduled_at`. That worked when each automation was a one-off `scheduled` task. With shared system pipelines that should be runnable from many channels, the schedule can't live on the definition — two channels scheduling `Full Scan` daily at different times need two schedules, one definition.

**Proposed shape**: Piggy-back on 5.1's subscription table. `schedule` + `schedule_config` columns drive a per-subscription scheduler. On boot, walk subscriptions where `schedule IS NOT NULL AND enabled = true`, and register them with the existing scheduler infrastructure (`app/agent/tasks.py` fetch loop or the cron-jobs service — pick whichever is already in use for `Task.recurrence`). Each fire calls `spawn_child_run(pipeline.id, channel_id=subscription.channel_id, params=subscription.schedule_config.get("params"))`.

**Cron vs recurrence**: currently `Task.recurrence` uses a simple `+1d` / `+6h` DSL. The subscription schedule can reuse that DSL for parity. Or step up to cron expressions — the cron-jobs service already handles that. Probably cleanest: `schedule` is a cron expression, the scheduler dispatches subscription entries alongside regular cron jobs.

**Migration path for existing schedules**: scan Task rows with `recurrence IS NOT NULL AND source = 'system'` (there shouldn't be any — system pipelines don't self-schedule today), or with `recurrence IS NOT NULL AND parent_task_id IS NULL AND channel_id IS NOT NULL` (user-created channel-scheduled tasks). Leave those untouched; they keep working on the old path. Subscriptions are additive.

**UI**: channel settings Pipelines tab gets a `+ Schedule` affordance per subscription. Modal with cron picker + params form (reuses `params_schema` rendering from the launchpad `TaskRunModal`). List shows `daily @ 02:00 UTC · last run 3h ago · next run in 9h`.

### 5.3 — Agent/tool step failure signaling

**Problem**: In session 14 the orchestrator pipeline had a tool step (`fetch_traces`) error with `{"error": "TypeError: ..."}`. The step still showed a **green checkmark** in the run-detail UI because the tool call returned (even though its result payload was an error). The downstream agent step dutifully wrote "No `fetch_traces` data available — ... Unable to analyze..." and emitted `{proposals: []}`. Both steps green; pipeline silently degrades. User can't tell from a glance that the pipeline actually failed.

**Proposed fixes** (start with tool, extend to agent):

1. **Tool step: detect error-shaped results**. In `app/services/step_executor.py:_run_tool_step`, after a tool returns, try `json.loads(result)` and if the parsed payload is a dict with an `error` key, set step status to `"failed"` instead of `"done"` (keep the raw result for display). The UI's `StepStatusIcon` will render the red failure badge automatically. Regression test: tool that returns `{"error": "x"}` → step_state status is `"failed"`. Tool that returns `{"error": null, "data": ...}` → still `"done"`.
2. **Agent step: declare output expectations**. Add an optional `expect_output` field on agent step definitions — shape `{required_keys: ["proposals"], non_empty_keys: ["proposals"]}`. After LLM completes and JSON-parses, validate; if missing or violated, set step status to `"failed"` with a detail message. For the orchestrator case: `expect_output: {required_keys: ["proposals"], non_empty_keys: ["proposals"]}` would have correctly flagged the degraded run as failed.
3. **Agent step: `fail_if` predicate** (alternative to 2). A simple when-style expression evaluated against the parsed output. Mirrors the existing `when:` gate syntax for step prerequisites. `fail_if: "{{result.proposals | length == 0}}"` catches the empty-list case without requiring a schema. Likely simpler to implement than full JSON schema validation.
4. **UI: "completed with warning" visual state** (optional). If step output content indicates trouble but we don't want to hard-fail, surface a yellow triangle icon instead of the green check. Needs a new `step_state.status` value or an adjacent `warnings` field — lean toward reusing the existing `failed` status since that's already wired through the UI.
5. **Hook interplay with `requires_channel` / empty-items auto-skip**: the auto-skip I added to `_run_user_prompt_step` (2026-04-17) was a bandaid for the symptom. With 5.3 in place, the upstream agent step marks itself `failed` when it produces empty proposals, the `user_prompt` step never fires (foreach `when:` gates skip it), and there's no phantom review to skip. Consider whether to keep the auto-skip or remove it once 5.3 lands — probably keep as belt-and-suspenders.

**Observed in session 14, backs up this design**:
- `fetch_traces` returned `{"error": "TypeError: ..."}` — should have been `failed`.
- `analyze` agent step returned a JSON blob starting with a paragraph explaining it couldn't do the task, followed by `{"proposals": []}` — a `non_empty_keys: ["proposals"]` assertion would have caught this.

### 5.4 — Immediate carryover from session 14

- **The Trash button on Findings cards (`FindingsPanel.tsx:FindingCard`)** deletes the whole pipeline run via `DELETE /api/v1/admin/tasks/{id}`. Works but is destructive. Consider a "Skip this review" that marks the step `done` with an empty response as an alternative — keeps the run visible in admin history, just removes it from the Findings queue.
- **Empty-items auto-skip landed (`step_executor.py:_run_user_prompt_step`)**. On future runs the 21 stuck "awaiting review" cases can't recur.
- **The 19 orphan stuck runs** still exist and have `channel_id = NULL` (created before the session-14 channel-binding fix). User-facing cleanup via the Trash button on each Findings card. Bulk cleanup: `DELETE FROM tasks WHERE parent_task_id IN (SELECT id FROM tasks WHERE source='system') AND channel_id IS NULL;` — user will decide when to run.
- **`get_trace` now supports list-mode** (`event_type + limit + bot_id` params → JSON array of TraceEvent). Any future pipeline that needs "recent events of type X" can use it without touching the tool.
- **Bot override (`requires_bot`) is plumbed but unused**. All three system pipelines still pin `bot_id: orchestrator` in YAML because they require orchestrator's API scopes to patch bots/skills. A future user-authored pipeline that's bot-agnostic can declare `requires_bot: true` and the launchpad will need a bot picker — not wired in the UI yet.
- **Admin task detail view**: when a pipeline definition is opened, there's no launch-time param picker for `requires_channel` pipelines. The "Run Now" button in admin will 400. Acceptable (admin users can use the channel launchpad), but worth a banner or disabled-state with a message: "This pipeline must be launched from a channel."

## Phase 5.5 — Inline review + evidence citations (SHIPPED 2026-04-17, session 15)

Plan: `~/.claude/plans/glittery-juggling-boole.md`. Four orthogonal workstreams (A–D). Companion to `~/.claude/plans/imperative-jumping-donut.md` (Phase 5 subscriptions); no semantic conflicts.

**A. Pipeline reshape (YAMLs)**

- `orchestrator.analyze_discovery.yaml` now requires `bot_id` param — `params_schema` entry wired to `TaskRunModal` → `BotPicker`. Adds a `fetch_bot` step so the analyze prompt can quote the bot's current triggers/descriptions in its diff_preview. Limit bumped 50 → 100 traces.
- `orchestrator.full_scan.yaml` analyze prompt now explicitly says "do NOT analyze discovery behavior — that's Analyze Discovery's job". Narrowed description: "Audit every bot's configuration (system_prompt, memory_scheme, pinned_tools)".
- All three pipelines' analyze prompts rewritten to require evidence-backed proposals: `scope.target_kind`, `scope.target_id`, `scope.bots_affected`, `evidence: [{correlation_id, bot_id, signal}]`. Prompt instructs "if you cannot cite 2 real correlation_ids (or concrete signals for config-drift cases), do NOT emit the proposal". No backend schema enforcement — relies on prompt discipline + graceful renderer fallback.

**B. Inline `user_prompt` review**

- `app/services/task_run_anchor.py:_step_summary` now attaches `widget_envelope` + `response_schema` + step `title` onto each step dict when `status == "awaiting_user_input"`. Zero new DB load — data already lives on `step_states[i]`. Envelope is dropped once status flips to `done` so stale envelopes can't leak.
- `ui/src/components/chat/TaskRunEnvelope.tsx` extended: status union widened to include `awaiting_user_input` (pulsing amber `PauseCircle`). When any step is awaiting, the header pill flips to a pulsing accent "Your review needed" that beats the outer `running`. The awaiting step renders `InlineApprovalReview` inline in chat — same component the Findings panel uses.
- `ui/src/components/chat/InlineApprovalReview.tsx` (**NEW**) — shared renderer consumed by both the chat anchor and the side-rail Findings panel. Reads items from `response_schema.items` with fallback to `widget_envelope.template.proposals` / `widget_envelope.args.proposals`. Graceful fallback for proposals that lack `scope` / `evidence`.
- `ui/src/api/hooks/useResolveStep.ts` (**NEW**) — shared mutation. Invalidates `findings`, `admin-tasks-timeline`, `orchestrator-runs`, `channel-messages` query keys.
- `ui/app/(app)/channels/[channelId]/ReviewNeededChip.tsx` (**NEW**) — sticky chip at the top of the chat scroll region. Uses IntersectionObserver scoped to the chat scroll root + MutationObserver for newly-streamed anchors. Chip appears when any `[data-awaiting-review="true"]` anchor exists but none is visible; click scrolls to the newest awaiting anchor; dismiss hides until a new finding arrives (key = sorted `task_id:step_index` list).

**C. Evidence in Findings**

- Scope chip (`skill` teal / `tool` purple / `bot` amber) is now the primary identifier for each proposal — the PATCH path drops to secondary dim mono.
- Evidence chips: first 8 chars of each traced `correlation_id` render as `<Link to="/admin/traces/<id>">` — trace-detail page is already wired. Untraced signals (config-drift proposals) render as truncated chips with the signal quoted in the `title` attribute.
- `FindingsPanel.tsx` card header: dropped raw `task.id` fallback in favor of title → stepDef.title → template.title → task.title. Shows `N proposals · Xm ago`.
- Findings card: destructive `confirm()` Trash button replaced with a `MoreHorizontal` overflow menu. Primary cleanup is **Skip review** (`POST /resolve` with empty response — drains the queue, keeps run in admin history). **Delete run** tucked behind an in-card confirm panel (no more native `confirm()`).

**D. Chrome reduction**

- `OrchestratorLaunchpad` default-collapsed when idle (findings === 0) — explicit user preference via tri-state localStorage key still wins. Expanded state auto-seeds from findings count on channel change.
- Strip header: killed "N featured · 1 more" subtext.
- Strip wrapper: dropped `border-b` + `bg-surface-raised/50`. Background tint only when expanded.
- Tiles: horizontal row layout instead of vertical card — icon + title + status + Run button, tile height ~52px (was ~110px). Description moves to `title` attribute for hover tooltip. "Last run Xm ago" now a `group-hover` opacity-reveal chip.
- Tile grid simplified to `grid-cols-1 md:grid-cols-2` (was 1/2/3 responsive).
- Recent Runs section now gated on `findingsCount === 0` — hidden while reviews are pending so the CTA is unambiguous.
- `TaskRunEnvelope` reshaped to single left-rail accent (`border-l-2`) echoing Linear's activity-feed pattern instead of full box border. Step-type badges desaturated to neutral monochrome; only the *active* step (running or awaiting) gets the accent pill. `user_prompt` → `REVIEW`, `foreach` → `APPLY` labels in chat (admin UI still uses technical names). Footer dropped "No dispatch / Context: None" boilerplate for pipeline runs.

**Tests**

- `tests/unit/test_task_run_anchor.py` (**NEW**, 4 tests): envelope+schema+title surfaced on awaiting_user_input; not surfaced for other statuses; graceful degradation when envelope missing; envelope not leaked after resolve flips status to done.
- Full `tests/unit/test_step_executor.py` + `tests/integration/test_orchestrator_pipelines.py` + `tests/integration/test_resolve_endpoint.py` re-ran: 121 passed, 1 pre-existing failure (`test_happy_path_fills_result_and_advances` — expects `step.result` as dict, gets JSON-serialized string; confirmed on HEAD, not caused by this session). Noted in Loose Ends as follow-up.

**Files touched (5 new, 7 modified, 3 YAMLs)**

New:
- `app/data/system_pipelines/orchestrator.analyze_discovery.yaml` (substantial rewrite; shape is new)
- `ui/src/components/chat/InlineApprovalReview.tsx`
- `ui/src/api/hooks/useResolveStep.ts`
- `ui/app/(app)/channels/[channelId]/ReviewNeededChip.tsx`
- `tests/unit/test_task_run_anchor.py`

Modified:
- `app/services/task_run_anchor.py` (+22 lines, `_step_summary` now surfaces `awaiting_user_input` payload)
- `app/data/system_pipelines/orchestrator.full_scan.yaml` (narrow description + evidence contract)
- `app/data/system_pipelines/orchestrator.deep_dive_bot.yaml` (evidence contract)
- `ui/src/components/chat/TaskRunEnvelope.tsx` (inline review + chrome reduction)
- `ui/app/(app)/channels/[channelId]/FindingsPanel.tsx` (drops local renderer + Skip action + overflow menu)
- `ui/app/(app)/channels/[channelId]/OrchestratorEmptyState.tsx` (default-collapse + flatter tiles + hide recent-runs when reviews pending)
- `ui/app/(app)/channels/[channelId]/index.tsx` (wires ReviewNeededChip into both mobile + desktop chat regions)

**Not done / explicitly parked**

- Per-item `when:` inside `foreach` (Loose Ends) — unchanged.
- Agent-step failure signaling (`expect_output` / `fail_if`) — owned by `imperative-jumping-donut.md` §5.5.
- `test_happy_path_fills_result_and_advances` failure (pre-existing, not caused by this session) — should be added to Loose Ends: resolve endpoint stores `step_state.result` as JSON string but the test expects a dict; either the endpoint should store parsed JSON or the test should `json.loads` before asserting.
- Free-form text `user_prompt` response type.
- Backend `?step_status=` filter (client-side still).

**Verification still owed**: browser smoke on the e2e instance — launch Analyze Discovery (BotPicker modal appears), watch the anchor show pulsing amber on the review step, click Approve/Reject inline in chat, verify foreach fires only for approved items. Plan has a 6-step smoke checklist.

## Addendum — SSH Machine Steps For Scheduled Tasks

- Added task-level SSH machine grants for user-authored task definitions. The admin task form can select one enrolled SSH target and choose whether agent/LLM machine tools may use the grant.
- Added deterministic pipeline step types `machine_inspect` and `machine_exec`. They render normal pipeline templates, validate the task grant, probe the SSH target, then run a fresh non-interactive SSH command. `machine_inspect` keeps the existing inspect-command allowlist.
- Agent steps spawned from a granted pipeline inherit access through parent-task grant resolution; task-origin agent runs materialize a short session lease before the agent loop starts.
- Follow-up: add richer launch-time warnings for pipelines that contain machine steps but no `machine_target_grant`.
