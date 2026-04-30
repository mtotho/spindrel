---
tags: [agent-server, track, mission-control, spatial-canvas, product-vision]
status: active
updated: 2026-04-30
---

# Track - Mission Control Vision

## North Star

Mission Control is the workspace operator for Spindrel. It replaces the vague
`orchestrator:home` product concept with a professional command surface that
can chat, inspect, draft, stage, and explain work across bots, channels,
widgets, tasks, and the spatial map.

The spatial canvas becomes a useful work map, not just spatial organization.
Channels are rooms/clusters on that map. Bots are actors. Widgets are live
instruments. Missions are durable work objects that connect the operator feed,
the map, and task-backed execution.

The guiding product shape is **Operator Map**: Mission Control is the command
room, and the spatial canvas is the living map. This is not another
orchestrator-led setup interview and not a generic workflow wizard. The operator
must inspect actual workspace state, name concrete missing pieces, stage
specific changes, and require approval before durable work or configuration
mutations happen.

## Locked Product Decisions

- **Mission Control is an operator agent.** It should have a normal-feeling
  feed, access to tools/skills/memory/context, and the ability to emit
  structured cards. It is not only a hidden AI helper behind a panel.
- **The existing orchestrator is migration substrate.** The current
  `orchestrator` bot and private `orchestrator:home` channel already carry
  broad admin tools and system-management prompts. Long term, that identity
  should become Mission Control rather than remain a parallel "Home" concept.
- **Actions are approval-first.** Mission Control may inspect, plan, draft,
  and stage. Starting missions and meaningful mutations require human approval
  by default.
- **The canvas is a professional work map.** Keep planets, landmarks,
  infinite scroll, dive-in, and world widgets, but every visible object should
  earn its space with actionable state or useful navigation.
- **Channels are rooms.** A channel is the close-up room for a canvas object or
  cluster: chat, dashboard, local missions, widgets, evidence, and context.
- **Missions remain task-backed in v1.** Approved missions create normal
  kickoff/tick tasks with scheduler, trace, model override, and harness support.
  Heartbeat injection is a later explicit feature, not the current execution
  truth.
- **Position is advisory.** Spatial readiness changes recommendation order,
  warnings, and visual state. It does not hard-block power users.
- **Game feeling is structural, not toy.** "Quest board" means motivating
  work framing, optional useful side quests, and a living world. No XP,
  inventory, levels, or blocking game loops in this track's v1 scope.
- **Setup help is inspection-first.** Mission Control should not ask broad
  intake questions when the workspace can answer them. Useful suggestions cite
  detected state, missing pieces, staged action, approval requirement, and the
  durable object that will exist afterward.
- **Quiet by default.** Setup opportunities belong in Mission Control, the
  optional native widget, or selected-object context. Channels and the map stay
  clean unless there is active local work, severe evidence, or an explicitly
  pinned widget.
- **Avoid user-facing "workflow" language.** Automations and Pipelines remain
  implementation primitives. Mission Control copy should speak in concrete
  operating goals: maintain this repo, watch this server, triage this room,
  keep this project moving.
- **Software factory is a future operating model.** Mission Control should
  eventually support issue pickup, reviewer/manager roles, and high-level
  next-action status across bots. Near-term alerts and map state should prepare
  this language, but not invent durable manager/reviewer systems before the
  existing primitives prove useful.

## End State

### Mission Control Operator

Mission Control has a canonical feed that behaves like chat plus structured
work cards:

- normal text turns for questions, explanations, and follow-up;
- operator brief cards for workspace summary and next focus;
- mission draft cards with rationale, bot, channel, run cadence, model, and
  accept/edit/dismiss actions;
- approval cards for meaningful mutations;
- mission run cards with progress, trace links, next actions, and failure
  evidence;
- compact system event rows for task completion, spatial movement, widget
  changes, and attention resolution.

Mission Control should be able to use the same core capabilities a strong
operator bot needs:

- read workspace mission/task/channel/bot/spatial/widget state;
- inspect traces, task results, recent failures, and attention evidence;
- use selected admin tools and APIs through normal tool policy paths;
- load relevant skills on demand;
- remember durable workspace-level operating context;
- propose changes as structured drafts before mutating.

Every operator suggestion should clear the "materially better than the old
orchestrator" bar:

- **Detected:** what Mission Control found in live missions, tasks, channels,
  bots, widgets, traces, integrations, spatial state, or files.
- **Missing:** the exact absent setup or decision that prevents useful work.
- **Stages:** the concrete mission, automation, widget, setting, bot/channel
  edit, or run that would be created.
- **Approval:** what the human is approving and what remains unchanged if they
  dismiss it.
- **Afterward:** where the durable result appears: feed card, channel strip,
  widget, map marker, run transcript, task, or trace.

The feed is not the only surface. Mission Control can also appear as:

- dense Starboard panel on desktop;
- compact mobile hub section;
- channel-local mission strip or proposal card;
- canvas marker/overlay for a mission, draft, warning, or operator suggestion;
- native widget snapshot pinned to the world.

### Reality Check - 2026-04-28

The mission-oriented roadmap is not yet validated product direction. Do not
make the spatial canvas, Starboard, or channel room UX depend on a mission
system that does not exist yet or may be redesigned. Near-term implementation
should use existing primitives as source of truth: spatial nodes, channels,
bots, widgets/pins, heartbeats, scheduler tasks, sessions/traces/tool calls,
integration bindings, and Attention as a warning/evidence overlay.

The current durable substrate is `/api/v1/workspace/spatial/map-state`: a
read-only object-state model that tells the UI what each channel/bot/widget/
landmark is doing now, what is scheduled next, what happened recently, and what
warnings are attached. Mission Control can later consume this model, but it
must not own the basic map semantics until the product direction is proven.

### Attention Operator Triage - 2026-04-29

The first operator workflow should consume existing Attention primitives rather
than invent a mission/task-management model. The Hub now starts one
task-backed operator triage session over all active visible Attention items.
The operator classifies each item through `report_attention_triage_batch`:
noise/recovered/duplicate items become processed/acknowledged, and real risks
stay active as ready-for-review items with a suggested action and optional
route. Review feedback is written back to the item and operator memory so
future runs can learn routing preferences.

The Starboard surface must not expose the compatibility `orchestrator` identity
as the primary product name. Treat that bot/channel as migration substrate:
launch and review copy says Operator, the run setup discloses read-only mode and
model/provider choice before work starts, and the embedded transcript stays
contained inside Starboard instead of becoming the main navigation path.

This is a proving slice for Mission Control: chat-native session, structured
card output, approval/review loop, and live Attention cleanup, without making
the product depend on a durable mission system.

2026-04-29 refinement: Attention now treats Operator output as a visible review
pipeline, not hidden metadata inside the old raw alert inbox. Starboard bucket
copy leads with review/untriaged/cleared counts, sweep candidates exclude items
already in Operator Review, review details put the Operator finding before raw
evidence, and Map Brief distinguishes operator-reviewed findings from raw red
alerts. This keeps the current Attention primitives while making the sweep feel
like it transformed the queue.

Same-day run isolation follow-up: Operator sweeps now only claim untriaged or
failed Attention items. Existing `ready_for_review` and processed findings keep
their original task/session evidence, so a new sweep cannot overwrite the
transcript that produced an older review card. The Starboard run workspace now
treats the transcript as its own full panel surface with a compact chat variant,
then lists review/processed buckets below it instead of embedding a cramped
chat card inside the overview.

Bot-reported issue lane follow-up: scheduled tasks and channel heartbeats can
opt into `allow_issue_reporting`, which injects a scoped `report_issue` tool.
Those reports stay inside the existing Attention Item substrate with
`evidence.report_issue`, sort ahead of automatic system/tool failures, and can
absorb matching automatic signals as evidence. This preserves the current
Mission Control Review model: bots can raise a judgment, Operator can classify
the broader queue, and humans still make the visible decision.

### Starboard / Command Deck Pivot - 2026-04-29

The Attention experiment exposed a deeper IA problem: Starboard cannot be the
object inspector, raw alert inbox, Operator sweep launcher, reviewed-findings
queue, transcript viewer, bot assignment form, and run history at the same
time. That model makes every state look like every other state, especially in a
narrow drawer.

Lock the product split:

- **Canvas** is the living world. It should show where things are, what is hot,
  what is running, and what changed, then route the user toward the right place.
- **Starboard** is the contextual inspector. It explains the selected object,
  local risk, local next action, and where to go next. It should not host the
  full Attention/Operator workbench.
- **Attention Command Deck** is the serious review surface. It owns raw
  Attention, Operator findings, cleared items, active sweeps, evidence, and run
  logs in a larger layout.

Operator sweep is a queue transformation, not a chat-first interaction:
untriaged signals become reviewed findings, cleared/noise is visibly separated,
and the transcript becomes a run log/evidence record. Product UI says
**Operator**; the `orchestrator` bot/channel remain compatibility substrate
only.

Near-term implementation should make `/hub/attention` the canonical Attention
Command Deck, keep `/hub/mission-control` for the broader Mission Control
surface, and change Starboard's Attention station into a compact launcher and
object-local summary. Do not introduce a mission system for this pivot.

2026-04-29 implementation note: the global Attention drawer mount was removed.
Channel Attention badges now route into `/hub/attention?channel=...&mode=inbox`,
and the deck owns mode state through URL params. The deck now leads with a
"What to do now" lane strip, treats reviewed/cleared/raw/running as distinct
modes, makes cleared items read-only, keeps normal bot assignment collapsed, and
shows Operator run receipts before exposing transcript evidence. Transcript is
deliberate evidence, not the default run workspace.

Same-day route consolidation: the current user-facing funnel is **Mission
Control Review**, backed by `/hub/attention`. Shared command-center links,
Starboard Attention summaries, map warning affordances, and the legacy
`/hub/mission-control` entry should all route there until the durable mission
substrate exists. Starboard remains the contextual inspector/launcher, not the
review workbench. The older Mission Control draft surface stays experimental
and must not be treated as the canonical place for Attention triage.

Same-day interaction-contract pass: the deck now has one explicit
`What to do now` lane instead of four equal forks, Operator sweep success pins
the user to the run log with `run=<task_id>` in the URL, and Starboard/Map Brief
copy uses shallow review verbs (`Open Review`, `Review signal`, `Review
finding`) instead of implying the drawer is the workbench. Screenshot specs now
cover the review deck and run-log states so this split can be visually checked.

Eye-flow/progressive-discovery pass: the product split is now **Canvas points,
Starboard inspects, Mission Control Review decides**. Starboard no longer owns a
station switcher or command-center navigation; it is the selected-object
inspector only. Canvas owns Add and View controls, with attention markers as
visual state unless an obvious badge/button target exists. `/hub/attention`
remains the durable review workbench, with unreviewed/finding/cleared/run-log
language and the old "raw signal" framing treated as legacy. Screenshot specs
now cover object-inspector Starboard and the canvas View popover.

Same-day deck clarity follow-up: Mission Control Review now treats bot-reported
issues as first-class findings, removes the misleading "Reviewing now" passive
state, switches medium-width layouts to queue + detail instead of stacked
sections, and uses sweep-history/receipt language for Operator runs.

2026-04-30 sweep-status follow-up: Mission Control Review now shows a loading
skeleton while the Attention payload is still empty, clears stale item selection
when switching lanes, and keeps a newly-started Operator sweep on a starting
receipt instead of flashing an older run. Operator transcripts are now presented
as an always-visible terminal-style feed inside the run receipt rather than a
collapsed details box. The tool-schema failure that pushed Operator runs off
`gpt-5.4` was traced to `call_api.body` declaring arrays without `items`; that
schema now includes an empty `items` declaration for strict providers.

Visual feedback status: the canonical `spatial-checks` screenshot bundle is
healthy again on the dedicated e2e target `:18000`. On 2026-04-30,
`stage --only spatial-checks` succeeded, `capture --only spatial-checks`
refreshed all `12/12` docs artifacts, and `scripts.screenshots check` found all
`91` docs image references. The refreshed Map Brief, Mission Control Review
deck, run-log, and dense canvas captures were visually inspected before
accepting the artifacts. Continue using the e2e target for docs images; do not
capture from the live LAN server without explicit approval.

### Spatial Canvas Work Map

The canvas should answer, at a glance:

- What exists in this workspace?
- Which channels/rooms are active?
- Which bots are assigned to what?
- What work is pending, running, stuck, or recently completed?
- Which objects are related, close, stale, or noisy?
- Where should I go next?

Object roles:

- **Channels** are planets/rooms. They retain the current world identity but
  gain mission, attention, activity, and assigned-bot state.
- **Bots** are actors. Their position communicates locality, current focus,
  nearest rooms/widgets, and readiness for channel-scoped work.
- **Widgets** are instruments. They remain directly interactive at close zoom
  and summarize live state at lower zoom.
- **Missions** are work objects. They render near assigned bots or target
  channels, with due/run state, traceability, and accept/run controls.
- **Landmarks** are system domains. Daily Health, Memory Observatory, Now Well,
  Mission Control, and future landmarks should explain the system through
  stable places, not disconnected pages.

### Channel Rooms

A channel is the room you enter from a map cluster. It should show:

- primary chat/session flow;
- local dashboard widgets;
- local Mission Control affordances: ask about this room, create mission for
  this room, show active local missions, show recent mission/task runs;
- evidence and outputs from work that touched this room;
- beam-back continuity to the originating canvas cluster.

Channel rooms remain useful standalone pages. They should not be reduced to
logs for Mission Control.

## Appearance And Interaction Direction

### World Tiles

Channel tiles keep the current planet direction, with utility layered in:

- **Far zoom:** clean glyph/planet, critical state only. No text clutter.
- **Mid zoom:** room title, assigned bot, active mission count, attention/risk
  chip, recent activity warmth.
- **Close zoom:** local actions: open room, ask Mission Control, create
  mission, inspect activity, pin/add widgets, manage local policy.

Visual state should be encoded with restrained, professional cues:

- attention rim for active signals;
- mission ring or small tethered marker for active work;
- activity warmth/halo for recent use;
- spatial readiness badge for assigned bot proximity;
- running tick/pulse only when a task is actually active;
- no decorative badges that do not change behavior.

### Bots

Bot objects should communicate assignment and capability:

- avatar/emoji identity remains primary;
- current or next mission appears as compact label/state;
- spatial readiness uses proximity/advisory language;
- nearby objects and target room are discoverable from selected-object actions;
- moving/tugging remains explicit and audit-visible.

### Widgets

World widgets remain replaceable and removable:

- compact widgets show the single most useful current state;
- close widgets are directly interactive;
- widgets that control external systems must keep clear state/action
  separation;
- Mission Control native widget becomes a serious operations snapshot:
  active missions, draft count, next run, spatial warnings, and open action.

Widget chrome stays low. Do not create nested cards or decorative dashboard
frames inside canvas widgets.

### Mission Control Board

The board version of Mission Control should be dense and professional:

- top command strip: ask input, subtle per-request model/provider selector,
  refresh, settings link;
- operator brief is compact, not a hero block;
- suggested missions are reviewable cards with edit/accept/dismiss;
- bot lanes show active mission, next run, recent update, warnings, and
  capacity;
- manual mission creation is available but tucked behind a compact action;
- empty states explain what to do next without looking like onboarding copy.

## Roadmap

| Phase | Status | Description |
|---|---|---|
| P0 - Vision and IA lock | active | Create this track, link it from Roadmap/INDEX, and mark Spatial Canvas as substrate while this track owns orchestration/product direction. |
| P1 - Professional Quest Board | planned | Implement the accepted near-term plan: dense lanes, subtle model selector, System > Models discoverability, mobile hub section, channel/context entry points, and better widget snapshot. |
| P2 - Operator Feed | planned | Migrate `orchestrator:home` toward Mission Control identity. Add chat-plus-cards feed semantics and approval-gated tool/skill use. |
| P3 - Actionable Work Map | planned | Add mission/draft/run/attention overlays to world objects, selected-object action rail, and canvas-visible mission objects. |
| P4 - Channel Rooms | planned | Add channel-local Mission Control affordances, local mission strips, recent runs, and tighter canvas-to-channel continuity. |
| P5 - Mobile Command Hub | planned | Make mobile Home a compact Mission Control entry point with next work, urgent signals, active rooms, and quick ask. |
| P6 - Side Quests and Operating Rhythm | deferred | Add optional useful side quests, recurring operating reviews, and lightweight progress rituals only after the professional workflow is proven. |

## Phase Detail

### P1 - Professional Quest Board

Carry forward the accepted near-term implementation plan:

- redesign `CommandCenter` into a dense operator board;
- add inspection-first opportunity cards that show detected state, missing
  pieces, staged action, and approval outcome;
- keep embedded Starboard density high: no duplicate Mission Control header,
  compact status strip instead of large metric cards, and scan-friendly
  opportunity rows;
- promote Mission Control AI settings into System > Models and make provider
  selection persist correctly;
- add per-request model/provider selector to Mission Control ask/refresh;
- add Mission Control to mobile hub;
- add channel-scoped ask/create mission entry points;
- improve the native world widget snapshot;
- keep mission execution task-backed.

Acceptance:

- browser find for "Mission Control" succeeds on System > Models;
- user can answer "what is each bot doing next?" in under 10 seconds;
- empty or underconfigured workspaces show concrete operator opportunities, not
  generic onboarding copy;
- Mission Control AI provider rejection never becomes a raw 500;
- a channel-scoped draft can be accepted into a normal mission;
- active missions remain traceable through task links.

### P2 - Operator Feed

Unify the old orchestrator concept with Mission Control:

- rename/present the existing orchestrator landing concept as Mission Control;
- decide whether the underlying bot id remains `orchestrator` for compatibility
  while UI labels shift to Mission Control;
- expose a canonical operator feed route;
- teach the operator feed to emit structured mission/proposal/approval cards;
- keep normal chat turns available for follow-up;
- route mutations through existing tool policy and approval systems.

Acceptance:

- no user-facing "Home channel vs Mission Control" ambiguity;
- the operator can inspect and propose without immediately mutating;
- proposal cards can be accepted into normal system actions or missions;
- old orchestrator launchpad concepts are either migrated or clearly retired.

### P3 - Actionable Work Map

Make the canvas useful beyond organization:

- mission drafts and active missions render near their target bot/channel;
- channel objects surface local missions, attention, and recent work state;
- selected-object rail offers actions by kind: channel, bot, widget, mission,
  landmark;
- map overlays avoid text clutter at far zoom and expose detail only on
  selection/close zoom;
- spatial readiness is visible but advisory.

Acceptance:

- from canvas, a user can identify urgent rooms and active bot work without
  opening Mission Control;
- selecting a mission marker opens the relevant Mission Control context;
- selecting a channel exposes room actions without accidentally moving objects.

### P4 - Channel Rooms

Make channels the close-up room for a map cluster:

- channel header or local rail shows active missions for that channel;
- composer/toolbar exposes "Ask Mission Control about this room";
- local recent runs/evidence are visible without going to Admin Tasks;
- beam-back returns to the same canvas object/cluster;
- local widgets can be promoted to the world and keep shared state where
  appropriate.

Acceptance:

- user can start in a channel, ask for a useful next mission, approve it, and
  see it on the map;
- user can start on the map, dive into a room, act, and return without losing
  context;
- chat remains usable and not crowded by Mission Control chrome.

### P5 - Mobile Command Hub

Mobile should not attempt to replicate the full spatial canvas first:

- Home becomes a compact Mission Control summary;
- show next work, urgent signals, active rooms, and recent updates;
- quick ask opens the Mission Control operator;
- channel rooms remain the main mobile deep-work surface;
- pinned widgets keep focused full-page mobile affordances.

Acceptance:

- mobile users can triage workspace state in one screen;
- full Mission Control route is usable on mobile;
- no desktop-only Starboard dependency for critical operations.

### Agent-First Capability Surface - 2026-04-29

The first implementation slice for "agents do not make humans configure what
the system can already inspect" is a shared capability manifest:

- `/api/v1/agent-capabilities` returns the bot/channel/session surface in one
  machine-readable payload: API grants/endpoints, tool profiles, enrolled and
  pinned tools, enrolled skills, Project/runtime readiness, harness state,
  widget authoring tools, and doctor findings.
- `list_agent_capabilities` exposes the same manifest to bots inside normal
  turns; `run_agent_doctor` is the compact readiness-only view.
- The endpoint catalog now includes OpenAPI-derived params/body/response hints
  when available, and `call_api` accepts structured JSON bodies so agents do
  not have to hand-escape request payloads.
- The UI consumes the same manifest in bot overview, channel tool overrides,
  and the chat composer. The composer now has an Agent readiness view and the
  tools menu promotes manifest-recommended core tools.
- Agent readiness findings can now include human-approved repair actions.
  Missing API grants stage an exact `workspace_bot` permissions patch, empty
  working sets stage deduped core tool additions, and Project/harness runtime
  gaps navigate to the owning settings surface. No separate mutation endpoint
  was added; the UI reuses the existing bot update path and refreshes the
  manifest after apply.
- Integration Doctor v1 extends the same manifest with read-only integration
  readiness. It composes the existing integration catalog, channel activation
  options, and channel bindings to show enabled/setup/dependency/process gaps,
  placeholder activation bindings, and missing channel activation config. Its
  proposed actions are route-only; enabling integrations, installing deps,
  starting processes, and writing secrets stay explicit admin work.
- Repo-dev AX is a separate surface: `.agents/manifest.json` indexes
  repository-local skills for development agents working on Spindrel source.
  These skills cover backend, UI, integrations, widgets, harnesses, docs,
  agentic readiness, and the existing visual feedback loop.
- The repo-dev skills are not Spindrel runtime skills. Channel bots do not see
  `.agents/skills` unless a future, explicit runtime bridge supplies that
  content through a real app-owned contract.
- External agentic discovery now has its own low-level entrypoint:
  repo-root `llms.txt` plus unauthenticated `GET /llms.txt` on running
  Spindrel servers. This is for outside/dev agents and external integrators;
  in-app runtime agents still use the capability manifest and runtime
  tools/skills.
- Runtime agents now have a compact context-pressure surface:
  `runtime_context` on the capability manifest plus `get_agent_context_snapshot`.
  It normalizes the latest channel/session budget into tokens used/remaining,
  percent full, source, profile, and `continue` / `summarize` / `handoff` /
  `unknown`; Doctor only raises context findings when summarize or handoff is
  actually needed.
- Runtime agents now have a compact assigned-work surface:
  `work_state` on the capability manifest plus `get_agent_work_snapshot`.
  It lists active Mission assignments and assigned Attention Items for the
  current bot with recent updates and `idle` / `advance_mission` /
  `review_attention`, while existing mission/attention tools remain the only
  write path.
- Runtime agents now have a compact liveness/status surface:
  `agent_status` on the capability manifest, `GET /api/v1/agent-status`, and
  `get_agent_status_snapshot`. It derives `idle`, `scheduled`, `working`,
  `blocked`, `error`, or `unknown` from existing Tasks, HeartbeatRuns,
  ChannelHeartbeat config, sessions, and structured tool-call errors, and
  Doctor can flag stale runs, latest failures, repetitive heartbeats, or
  missing channel heartbeat setup.
- Runtime tool failures now have a shared agent-facing error contract. The
  manifest publishes `tool_error_contract`, dispatch/API-tool failures preserve
  the legacy `error` string while adding `error_code`, `error_kind`,
  `retryable`, `retry_after_seconds`, and `fallback`, and tool-call audit rows
  persist those fields so later reviews can filter benign validation/setup
  warnings away from retryable outages and platform bugs.
- Mission Control Review now uses that contract directly for tool-call
  Attention signals: one-off benign contract failures stay out of the queue,
  repeated benign failures become low-priority findings, retryable outages stay
  visible with backoff/fallback context, and internal/platform failures remain
  high-priority.
- Runtime agents now have a normalized activity replay surface:
  `activity_log` on the capability manifest, `GET /api/v1/agent-activity`, and
  `get_agent_activity_log`. It reads existing evidence from tool calls,
  Attention Items, Mission updates, Project run receipts, and widget agency
  receipts, then returns one ordered stream with normalized actor, target,
  status, summary, trace/correlation, and structured error fields.
- Agent-important outcomes now have a generic receipt contract:
  `execution-receipt.v1`, `GET/POST /api/v1/execution-receipts`,
  `publish_execution_receipt`, and `execution_receipt` activity replay items.
  Agent Readiness writes these receipts after approved bot config repairs
  succeed, recording actor, target, action type, before/after summary,
  approval reference, result, rollback hint, and trace IDs. The receipt does
  not perform the mutation; Bot/Channel/Project/Widget/Integration APIs remain
  the actual write paths.
- Agent Readiness repair receipts are now verification receipts, not only
  mutation logs. After a repair applies, the UI refetches the capability
  manifest, records whether the original finding disappeared, stores before/
  after Doctor status and remaining finding codes, and surfaces the latest
  readiness receipt in the panel and manifest.
- Agent Readiness repair actions now have a read-only preflight contract:
  `POST /api/v1/agent-capabilities/actions/preflight` and the
  `preflight_agent_repair` tool return `agent-action-preflight.v1` with
  `ready` / `blocked` / `stale` / `noop`, missing actor scopes, current
  finding codes, and field-level bot diffs. The UI runs preflight before
  applying staged bot patches and stores the preflight result in the readiness
  execution receipt.
- Runtime agents can now request, rather than apply, ready Agent Readiness
  repairs. `POST /api/v1/agent-capabilities/actions/request` and
  `request_agent_repair` create/update an idempotent `needs_review`
  execution receipt with the review preflight and the requester's missing
  apply scopes; the manifest exposes these under
  `doctor.pending_repair_requests`, and the Agent Readiness panel lets humans
  apply a still-current request through the existing preflight + bot-update
  path.
- Mission Control Review now consumes the same pending readiness repair
  receipts as an Autofix queue in the attention brief. `GET
  /api/v1/workspace/attention/brief` returns `summary.autofix` and
  `autofix_queue`, prioritizes the first queued repair after explicit owner
  decisions, and applies still-current requests through the shared preflight +
  Bot update + manifest verification + execution receipt path. Stale requests
  route back to Bot readiness instead of mutating config.
- Agent Readiness now has skill-opportunity signals for runtime agents and
  humans. The manifest publishes `skills.recommended_now` for existing skills
  the bot should load before procedural work, plus `skills.creation_candidates`
  for missing runtime skill coverage. This is recommendation-only: no import
  from repo-dev `.agents`, no auto-enroll, and no full-body auto-inject.
- The repo-dev `agentic-readiness` skill is now progressive-disclosed. Its
  always-loaded `SKILL.md` stays focused on context classification and
  skill/tool/API/docs placement, while detailed external AX, internal runtime
  AX, feature-placement, and small-model guidance live in first-level
  references. Tests pin that it remains repo-dev only and not a runtime skill.
- This remains approval-first capability repair, not a spatial destination.
  Spatial/Mission Control surfaces may consume the actions later as "Fix bot
  access" or "Open setup", but Agent Readiness should not become a competing
  map mode.
- Added the first brief-first review slice. `GET /workspace/attention/brief`
  derives blockers, fix packs, owner decisions, quiet digest counts, and one
  next action from existing Attention Items. The Mission Control Review deck now
  consumes that brief above the queue, exposes copyable code-fix prompts, and
  makes "kept" Operator findings visibly acknowledged without pretending that
  the raw Attention queue is the product workflow.
- Added a direct `Clear all` escape hatch to Mission Control Review for the
  current active review/unreviewed set. It uses the existing bulk acknowledge
  endpoint, clears the selection on success, and keeps new occurrences eligible
  to resurface later.

## Key Invariants

- Mission Control is the canonical operator surface. Do not create a second
  "home/orchestrator" product lane.
- The old orchestrator bot/channel may remain as compatibility substrate, but
  user-facing navigation should converge on Mission Control.
- Near-term operator triage uses existing Attention items and `attention_triage`
  tasks as the durable substrate. Processed/noisy items can leave active
  Attention, but their outcomes must remain recoverable through operator run
  history.
- Bot-reported issues are Attention Items, not a new alert system. New
  scheduled tasks and heartbeats default to `report_issue` enabled, existing
  saved runs keep their saved setting, and the UI should present this as
  "Report blockers to Mission Control" rather than an advanced tool-policy
  switch. Prioritize those reports above automatic detector noise, and fold
  same-target same-signature detector events into the report evidence.
- Mission tasks remain the execution truth until a later track explicitly adds
  heartbeat consumption.
- Mission Control suggestions require human approval before creating durable
  work or mutating configuration.
- AI-assisted setup suggestions must cite detected state, missing pieces,
  staged action, approval impact, and the durable result after approval.
- Attention is a weak/noisy signal unless supported by task, trace, mission,
  channel, or spatial evidence.
- Spatial position affects recommendations and warnings, not authorization.
- The map must stay useful at every zoom level. Far zoom is state summary;
  close zoom is interaction.
- Channels are rooms, not only logs. Canvas and Mission Control should drive
  users into channels when local context matters.
- Widgets should remain real tools, not decorative panels. A widget earns its
  canvas footprint by showing state or enabling action.
- Professional utility wins over game flavor. Side quests must be useful work.
- The canvas should feel alive through useful state, actor movement, local
  context, and optional side objectives, not through XP, levels, or decorative
  mechanics.
- Mission Control Review must funnel the eye into one current decision. The
  Review CTA selects and focuses the first finding; run receipts use a separate
  run-log layout instead of sharing the review/right-rail workspace.
- Operator route labels are internal taxonomy. User-facing copy should say
  "Code fix", "Owner follow-up", or another concrete next action rather than
  "developer channel" or "route to development".
- Mission Control Review should open with a brief, not a mailbox. The queue is
  evidence and drilldown; the primary surface should summarize fix packs,
  owner decisions, blockers, quiet/noise, and the single next action.
- Map alert affordances must never be inert. Aggregates summarize state;
  clickable per-object attention badges open Mission Control Review for the
  specific item; object cue markers select the target object; non-clickable
  warning decoration should be removed or rendered as clearly decorative.

## References

- `Track - Spatial Canvas.md` - world substrate, spatial nodes, landmarks,
  widget tiles, bot movement, and map interaction rules.
- `Track - UI Vision.md` and `agent-server/docs/guides/ui-design.md` - low
  chrome, professional control-surface rules.
- `Track - Harness SDK.md` - external agent runtime behavior and scheduled
  harness task execution.
- `Track - Widgets.md` - widget contract, native widgets, context export, and
  world widget rendering.
- Current code seams:
  - `app/services/channels.py::ensure_orchestrator_channel`
  - `app/data/system_bots/orchestrator.yaml`
  - `app/services/workspace_missions.py`
  - `app/services/workspace_mission_control.py`
  - `app/services/workspace_mission_ai.py`
  - `ui/src/components/command-center/CommandCenter.tsx`
  - `ui/src/components/spatial-canvas/SpatialCanvas.tsx`
  - `ui/src/components/spatial-canvas/SpatialMissionLayer.tsx`
