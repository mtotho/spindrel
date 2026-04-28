---
tags: [agent-server, track, mission-control, spatial-canvas, product-vision]
status: active
updated: 2026-04-28
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

## Key Invariants

- Mission Control is the canonical operator surface. Do not create a second
  "home/orchestrator" product lane.
- The old orchestrator bot/channel may remain as compatibility substrate, but
  user-facing navigation should converge on Mission Control.
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
