# Session Plan Mode

![Session plan card — `publish_plan` renders the plan inline with status pill, scope, runtime issues, and a per-step checklist](../images/chat-plan-card.png)

This is the canonical document for the web session planning system.

Live native-plan E2E captures for the current transcript UI are stored as
`../images/spindrel-plan-question-card-dark.png`,
`../images/spindrel-plan-card-default-dark.png`,
`../images/spindrel-plan-card-mobile-dark.png`,
`../images/spindrel-plan-card-terminal-dark.png`,
`../images/spindrel-plan-answered-questions-dark.png`,
`../images/spindrel-plan-answered-questions-terminal-dark.png`,
`../images/spindrel-plan-progress-executing-mobile-dark.png`,
`../images/spindrel-plan-progress-executing-terminal-dark.png`,
`../images/spindrel-plan-replan-pending-default-dark.png`,
`../images/spindrel-plan-replan-pending-terminal-dark.png`,
`../images/spindrel-plan-pending-outcome-default-dark.png`, and
`../images/spindrel-plan-pending-outcome-terminal-dark.png`.

If plan-mode behavior, prompting, tools, UI, or execution semantics change, update this file first and then update any shorter guides that point at it.

## Purpose

Session plan mode is a transcript-first planning workflow for web chat sessions.

It exists to solve a specific failure mode:

- normal chat tends to blur discovery, planning, approval, and execution together
- the model tends to dump large prose proposals when the user actually needs narrowing questions and a concrete artifact
- execution drifts unless it is tied to an accepted plan revision

Plan mode separates those concerns without creating a second session type.

## Core Model

Plan mode has three distinct concepts:

1. Session mode
2. Plan artifact
3. Plan presentation

They must stay separate.

### 1. Session mode

Session mode is the runtime source of truth.

Valid states today:

- `chat`
- `planning`
- `executing`
- `blocked`
- `done`

Mode is stored in session metadata and is what drives prompt injection, file-write restrictions, and execution behavior.

### 2. Plan artifact

The plan artifact is the canonical saved plan.

Current v1 storage:

- one active Markdown file per task
- immutable Markdown snapshots per revision under `.revisions/`
- no plans table
- no snapshot/version table
- revision number stored in the file and session metadata

Canonical path:

`channels/<channel-id>/.sessions/<session-id>/plans/<task-slug>.md`

### 3. Plan presentation

Visible planning UI lives in the transcript, not in page chrome.

That means:

- entering plan mode does not immediately create visible plan UI
- the first real plan appears only when the agent publishes one
- structured plan questions also appear as in-feed transcript widgets

The transcript renderer is the correct substrate because it matches the rest of the app’s tool/result model.

## State Machine

The current session-level state machine is:

`chat -> planning -> executing -> blocked|done`

There are also local loops inside those states:

- `planning -> planning`
  via more clarifying questions or plan revisions
- `executing -> planning`
  when a step reveals the plan is stale and needs revision
- `blocked -> planning`
  when the user or agent resumes planning instead of continuing execution

### Transition ownership

User-driven transitions:

- `chat -> planning`
  via the Plan control or `/plan`
- `planning -> executing`
  by approving the current revision
- `planning -> chat`
  by exiting plan mode
- `blocked|done -> planning`
  by resuming/re-entering planning

Agent-driven transitions:

- no mode flip should happen silently just because the model feels like it
- the agent can create or revise the plan artifact while the session is already in `planning`
- step completion/blocking updates happen during `executing`, but they should still respect the session’s accepted plan contract

Important invariant:

- mode changes are session/runtime decisions
- plan creation/revision is an agent/tool decision
- transcript rendering is a UI/result decision

Those three must not be collapsed into one action.

## Entry Semantics

Entering plan mode is intentionally inert from a UI perspective.

What entering plan mode does:

- flips the session into `planning`
- causes plan-mode context to be injected every turn
- tightens write policy so non-plan file edits are blocked

What entering plan mode does not do:

- create a plan file immediately
- inject a fake assistant message
- mount a page-level panel
- auto-publish a placeholder plan

This is important. The user is opting into a planning contract, not asking the app to immediately fabricate a draft.

## Session Endpoints and UI Hooks

Current web/session plumbing includes:

- `GET /sessions/{session_id}/plan-state`
- `GET /sessions/{session_id}/plan/revisions`
- `GET /sessions/{session_id}/plan/revisions/{revision}`
- `GET /sessions/{session_id}/plan/diff`
- `POST /sessions/{session_id}/plan/start`
- `POST /sessions/{session_id}/plan/review-adherence`
- session plan approval and step-status routes in `app/routers/sessions.py`
- session SSE at `GET /api/v1/sessions/{session_id}/events`
  carries `session_plan_updated` frames so the web UI does not have to poll while the user is looking at an active plan

Frontend session state is currently driven through:

- `ui/app/(app)/channels/[channelId]/useSessionPlanMode.ts`

Composer/session entry points live in:

- `ui/src/components/chat/MessageInput.tsx`

Composer control copy must distinguish action from status:

- inactive chat with no plan shows `Start plan`
- inactive chat with an existing plan shows `Resume plan`
- active plan modes show status labels (`Planning`, `Executing`, `Blocked`, `Done`) with semantic tone
- inactive action states do not show a dropdown affordance when the only action is start/resume

This matters because the visible UX is split correctly:

- session state comes from session endpoints/query state
- the first real plan/question UI comes from transcript tool results
- the composer control is only a mode entry/control surface

## Expected User Experience

The intended flow is:

1. User toggles `Plan` or runs `/plan`
2. Session enters `planning`
3. Agent asks focused clarifying questions
4. If structured input is useful, agent calls `ask_plan_questions`
5. User answers
6. Agent calls `publish_plan`
7. A plan card appears in the transcript
8. User approves that revision
9. Session enters `executing`
10. Execution proceeds step-by-step

If the model jumps straight to a giant prose proposal before narrowing scope, that is a plan-mode failure.

Published plans are expected to be implementation-ready, not just plausible.
Before approval, the artifact must make the plan decision-complete: intended
outcome, scope boundaries, key changes, interface impact, assumptions/defaults,
execution steps, acceptance criteria, and verification plan are all visible in
the structured plan card.

## Runtime Injection

Plan mode is not primarily a skill.

It is enforced through runtime system-message injection in:

- `app/services/sessions.py`
- `app/services/session_plan_mode.py`

`_load_messages()` appends each line returned by `build_plan_mode_system_context(session)` as:

`[PLAN MODE]\n...`

That means the context is injected every turn while the session is in a plan-related mode.

This injection is the main reason plan mode should be treated as a runtime contract, not a mere prompt-writing convention.

## Injected Planning Contract

The current planning contract is derived from `build_plan_mode_system_context()` and should remain aligned with the implementation.

### When mode is `planning` and no plan exists yet

The injected rules are currently:

- stay in planning mode
- do not execute implementation changes
- do not edit non-plan files
- do not answer with long freeform proposals before the scope is clear
- ask at most 1-3 focused clarifying questions
- prefer `ask_plan_questions` when multiple structured answers would help
- keep formatting terse; avoid giant markdown sections/lists unless explicitly asked
- do not publish a plan until key scope questions are answered or the user explicitly says to proceed with assumptions
- when proceeding with assumptions, record those defaults in the plan instead of leaving intent implicit
- a publishable plan must include key changes, interface/API/type impact, assumptions/defaults, concrete steps, acceptance criteria, and a test plan
- when ready, use `publish_plan` instead of writing a giant markdown response in chat
- keep conversational replies short and scoped to the next decision

This is the most important planning state. It is where the model either behaves like a planner or falls back into “write essay in chat” mode.

### When mode is `planning` and a plan already exists

The injected rules additionally emphasize:

- keep planning chat concise
- refine the canonical plan artifact via tools
- do not restate the whole plan in normal assistant prose
- use `publish_plan` for revisions
- use `ask_plan_questions` if more input is needed
- respect the canonical plan file path and current revision
- keep the visible structured draft in the artifact/tool result, not duplicated as a second giant assistant prose block

### When mode is `executing`, `blocked`, or `done`

The injected rules shift to execution:

- follow the accepted revision
- work one step at a time
- keep the plan file current as status changes
- prefer the current in-progress step, or the next pending step
- carry completed-step context forward without redoing the whole plan in prose

## Tooling Contract

Plan mode depends on four explicit local tools.

### `ask_plan_questions`

Purpose:

- gather focused planning input in a structured way
- avoid giant back-and-forth prose
- surface a transcript-native form-like card

Expected use:

- before the first plan draft
- when key scope, constraints, priorities, or acceptance criteria are unclear

Current shape:

- up to 3 questions
- `text`, `textarea`, or `select`
- rendered as native-app widget `core/plan_questions`

Current backend/runtime details:

- registered as a local tool
- returns `application/vnd.spindrel.native-app+json`
- renders native widget ref `core/plan_questions`
- returns an `_envelope` plus an `llm` reminder telling the model to wait for answers before publishing the plan

Current UI behavior:

- the widget submits the collected answers as a real user message on the session
- the same answers are captured as structured entries in the visible `planning_state` capsule
- the answers land in transcript history instead of living only in browser/composer state
- submission still remains explicit user action; the widget does not silently answer itself

This tool should be preferred whenever multiple choice/structured answers will reduce ambiguity.

### `publish_plan`

Purpose:

- create the first plan artifact
- revise the canonical artifact later
- emit the transcript-visible plan envelope

Expected use:

- only once the agent has enough information to propose a concrete draft
- not as a placeholder
- not as a substitute for clarifying questions
- must include professional-plan fields: key changes, interface impact, assumptions/defaults, concrete steps, acceptance criteria, and test plan

This is the only correct way for the model to create the first visible plan.

Current backend/runtime details:

- registered as a local tool
- only allowed while the current session is already in `planning`
- writes or rewrites the canonical Markdown artifact
- increments the revision
- returns `application/vnd.spindrel.plan+json`
- includes the structured plan payload plus an `_envelope`
- includes validation feedback so blocking issues are visible before approval
- warns when confirmed `planning_state` decisions are not visibly reflected in the draft

Current rendering path:

- rendered in-feed through `RichToolResult`
- should be treated as the transcript-native plan surface
- approval and progress actions belong on this surface, not elsewhere

### `request_plan_replan`

Purpose:

- stop execution when the accepted plan is materially stale
- return the session to `planning`
- preserve the previous accepted revision as historical execution context
- record a replan reason, affected step ids, and optional evidence in the runtime capsule

Expected use:

- only after a plan has been approved
- during `executing` or `blocked`
- when continuing would mean working around the accepted plan instead of following it

Current backend/runtime details:

- registered as a local mutating tool
- also exposed as `POST /sessions/{session_id}/plan/replan`
- returns `application/vnd.spindrel.plan+json` so agent-triggered replans render on the transcript-native plan surface
- creates a new draft revision with an open replan question
- keeps `accepted_revision` pointed at the old approved revision until a new revision is approved
- emits `session_plan_updated` with reason `replan`

### `record_plan_progress`

Purpose:

- record the required execution outcome before an executing/blocked turn is considered complete
- clear a pending missing-outcome warning from the previous execution turn
- optionally advance the current plan step to `done` or `blocked`
- preserve compact progress, verification, blocker, or no-progress notes across compaction

Expected use:

- before ending every `executing` turn
- when a prior execution turn has been marked as missing an explicit outcome
- after verification-only work, using `verification`
- after useful partial progress, using `progress`
- when no durable progress happened, using `no_progress` with evidence or a status note

Current backend/runtime details:

- registered as a local mutating tool
- only allowed while the session is `executing` or `blocked` with an accepted current revision
- remains allowed even when a pending turn outcome blocks other mutating tools
- returns `application/vnd.spindrel.plan+json` so the transcript-native plan card refreshes
- records the outcome in `plan_adherence.outcomes`
- stores the newest outcome in both `plan_adherence.latest_outcome` and `plan_runtime.latest_outcome`
- emits `session_plan_updated` with reason `plan_progress`

Supported outcomes:

- `progress`
- `verification`
- `step_done`
- `blocked`
- `no_progress`

### Semantic review

Purpose:

- review whether the latest recorded execution outcome is actually supported by the turn evidence
- keep semantic review separate from deterministic protocol adherence
- persist a compact verdict that survives compaction and shows up in the normal plan card

Expected use:

- on demand from the transcript-native/session plan card
- after an execution turn has already recorded `record_plan_progress`
- as a warning/review loop, not a hard execution gate

Current backend/runtime details:

- driven by `POST /sessions/{session_id}/plan/review-adherence`
- reviews the latest recorded outcome by default, or an explicit `correlation_id`
- rejects legacy outcomes that do not carry a usable `correlation_id`
- reconstructs evidence from the accepted plan step, assistant message, `tool_calls`, and compact trace events for that correlation id
- uses hybrid judgment:
  - deterministic contradiction checks first
  - then rubric-based semantic judging over the structured evidence bundle
  - deterministic contradictions override the judge
- persists review history in `plan_adherence.semantic_reviews`
- exposes `latest_semantic_review` through both `plan_adherence` and `plan_runtime`
- exposes a separate `plan_runtime.semantic_status`

Current verdicts:

- `supported`
- `weak_support`
- `unsupported`
- `needs_replan`

Important invariant:

- `adherence_status` answers the protocol question:
  did the turn follow the explicit planning/execution contract
- `semantic_status` answers the semantic question:
  does the evidence actually support the claimed outcome

Those must not be collapsed into one field.

## Transcript Rendering Contract

All visible planning surfaces should render inside the chat feed.

Current transcript-native planning artifacts:

- plan result envelope from `publish_plan`, `request_plan_replan`, and `record_plan_progress`
- native-app `core/plan_questions` card from `ask_plan_questions`
- the same plan card now also surfaces semantic review state and an explicit `Review Last Outcome` action

What should not happen:

- top-of-page plan panels
- plan UI that pushes the transcript down
- separate planner chrome that bypasses the existing tool/result system

The app already has a tool/result rendering model. Plan mode should use it, not compete with it.

Current MIME/rendering split:

- `application/vnd.spindrel.plan+json`
  for the actual plan artifact/result
- `application/vnd.spindrel.native-app+json`
  with `widget_ref = core/plan_questions`
  for structured question intake

## Markdown Artifact Contract

The Markdown file is the canonical saved artifact, but it is strict Markdown, not arbitrary prose.

Required header lines:

- `Status: ...`
- `Revision: ...`
- `Session: ...`
- `Task: ...`

Required sections:

- `Summary`
- `Scope`
- `Key Changes`
- `Interfaces`
- `Assumptions`
- `Assumptions And Defaults`
- `Open Questions`
- `Execution Checklist`
- `Test Plan`
- `Artifacts`
- `Acceptance Criteria`
- `Risks`
- `Outcome`

Older artifacts without the newer professional-plan sections remain readable.
New approvable drafts must populate the professional sections through
`publish_plan` or the session-plan API.

Checklist lines use stable step ids and explicit statuses.

The file is designed to be:

- readable by a human
- writable by the runtime deterministically
- stable enough to update progress without fuzzy matching

## File-Write Policy

Planning mode is not just a prompt. It also gates mutation.

Current write policy:

- in normal chat or execution, file writes follow the usual rules
- in `planning`, writes outside the active plan path are blocked
- if planning has started but no plan file exists yet, non-plan writes are still blocked

This matters because otherwise “plan mode” is just a suggestion and the model can drift into implementation too early.

## Approval Contract

Approval must bind to a specific plan revision.

That means:

- the user approves a revision number
- execution runs against that accepted revision
- if the plan changes later, the accepted revision is no longer implicitly the latest file contents

Even though v1 uses a single rewritten Markdown file, revision numbers still matter because they define the execution contract.

The agent should treat approval as binding, not advisory.

That means:

- do not start implementation just because the plan looks complete
- do not assume the latest edited file contents are approved unless that revision was actually accepted
- do not keep executing after the plan is materially stale; return to planning instead

The web routes now enforce this more explicitly:

- approve routes can reject a stale client revision with `409 Revision mismatch`
- approve routes reject structurally incomplete plans with `422`
- step-status routes can reject a stale client revision with the same `409`
- transcript cards for older revisions should therefore be treated as historical views, not implicit control surfaces for the latest draft

### Plan validation

Approval is gated by a deterministic validator, not just prompt guidance.

Current blocking issues:

- missing or placeholder summary
- missing or placeholder scope
- missing key implementation changes
- missing interface/API/type impact
- missing assumptions/defaults
- unresolved open questions
- no acceptance criteria
- no test plan
- no execution steps
- invalid or duplicate step ids
- invalid step statuses
- placeholder step labels
- vague step labels such as generic “implement changes” / “test it” items

Current warnings:

- scope does not state a visible boundary or non-goal
- a single-step plan may be too compressed
- confirmed planning-state decisions are not visibly reflected in the draft
- planning-state open questions were not carried forward or resolved

Validation is returned on:

- `GET /sessions/{session_id}/plan-state`
- `GET /sessions/{session_id}/plan`
- `session_plan_updated` SSE payloads
- `publish_plan` tool results

The UI surfaces these issues on the transcript plan card and disables approval when blocking issues remain.

## Revision History And Sync

Revision history is now snapshot-backed, even though the canonical artifact is still one active Markdown file.

Current behavior:

- draft publication writes immutable revision snapshots under `.revisions/`
- `GET /sessions/{session_id}/plan` returns current revision metadata plus a lightweight revision-history list
- `GET /sessions/{session_id}/plan/diff` returns a unified diff between revision snapshots
- the web UI can render historical transcript cards and compare revisions without guessing from chat prose

Session sync is event-driven:

- plan mutations publish `session_plan_updated` on the session SSE bus
- `useSessionPlanMode` updates query state from that event stream
- polling is no longer the primary plan-state refresh mechanism

## Runtime Capsule

The Markdown plan is not the only load-bearing state. The runtime also persists a compact `plan_runtime` capsule in `Session.metadata_`.

Planning before the first published plan also has visible durable state: `planning_state`.

`planning_state` stores the back-and-forth that would otherwise depend only on live transcript history:

- confirmed decisions
- open questions
- assumptions
- constraints
- non-goals
- relevant evidence
- preference changes

It is not an invisible executable plan. It is durable planning notes, shown through plan state/card surfaces and injected into planning/execution context so compaction or short live-history windows do not erase the user's latest decisions.

Current `planning_state` fields:

- `schema_version`
- `decisions`
- `open_questions`
- `assumptions`
- `constraints`
- `non_goals`
- `evidence`
- `preference_changes`
- `last_updated_at`
- `last_update_reason`

Current `plan_runtime` fields:

- `schema_version`
- `mode`
- `plan_revision`
- `accepted_revision`
- `plan_status`
- `current_step_id`
- `next_step_id`
- `last_completed_step_id`
- `next_action`
- `unresolved_questions`
- `blockers`
- `replan`
- `pending_turn_outcome`
- `latest_outcome`
- `adherence_status`
- `latest_evidence`
- `compaction_watermark_message_id`
- `last_updated_at`
- `last_update_reason`

This capsule is deliberately separate from the Markdown artifact:

- Markdown remains the readable plan artifact
- the capsule is the compact state machine summary
- `planning_state` is the visible durable notes layer before and around the plan
- compaction summaries are not authoritative for plan state
- context assembly injects the runtime capsule alongside the active plan artifact for planning/executing profiles

## Adherence State

Execution also maintains a compact `plan_adherence` ledger in session metadata.

Current shape:

- `status`: `ok`, `warning`, `blocked`, `planning`, or `unknown`
- recent evidence records
- latest evidence record
- recent progress outcome records
- latest progress outcome record
- last transition
- last update timestamp

Evidence records capture the current accepted revision, current step id, tool name/kind, tool-call ids, status, error, arguments summary, and result summary.

Outcome records capture the required turn-level execution result: outcome type, summary, optional evidence/status note, accepted revision, step id, turn id, and correlation id.

This is the first deterministic supervisor loop:

- planning mode blocks mutating tools before approval
- executing mode blocks mutating tools if the accepted revision/current-step contract is invalid
- blocked/replan-pending execution blocks mutating tools until the plan returns to a valid state
- `request_plan_replan` is the allowed escape hatch while executing or blocked, unless a replan is already pending
- turn-end supervision marks an executing/blocked turn as pending when no outcome was recorded
- a pending turn outcome blocks further mutating tools except `record_plan_progress` and `request_plan_replan`
- successful tool execution records compact evidence back into `plan_adherence` and `plan_runtime`
- tool evidence emits `session_plan_updated` with reason `tool_evidence` so transcript plan cards can refresh the latest adherence state
- progress outcomes emit `session_plan_updated` with reason `plan_progress`

## Execution Contract

Execution is supervised and step-scoped.

It is not supposed to be one giant autonomous run.

Current intended loop:

1. Load accepted revision
2. Select current/next pending step
3. Inject step + compact plan context
4. Execute that step
5. Record tool evidence against the current step
6. Use `record_plan_progress` before ending the turn
7. Mark result
8. Update the plan file/runtime
9. Continue only if the step finished cleanly

Expected step outcomes:

- `done`
- `blocked`
- `needs_replan`
- `aborted`
- explicit `no_progress` with evidence/status note

Current persisted step statuses in the plan artifact are:

- `pending`
- `in_progress`
- `done`
- `blocked`

If a step reveals that the rest of the plan is stale, execution should stop and return the session to planning instead of blindly marching forward.

Current session router behavior also includes step-level updates and auto-advance logic through `update_plan_step_status(...)` and related routes in `app/routers/sessions.py`.

If the plan is stale, the correct transition is `request_plan_replan(...)`, not manual status hacking or continuing with unstated assumptions.

That means the practical v1 system is:

- artifact-backed
- session-state-driven
- step-progress-aware

even though it is not yet a detached autonomous worker.

## Expectations for Agent Behavior

When the agent is in plan mode, it is expected to:

- narrow scope before drafting
- ask short, high-signal questions
- prefer structured question cards for multi-part clarification
- avoid giant essays in chat
- publish a structured plan instead of narrating one
- keep revisions in the artifact, not duplicated across multiple long prose replies
- respect explicit approval before implementation

More concretely, in `planning` the agent should usually do one of four things:

1. Ask a short clarifying question in plain chat
2. Call `ask_plan_questions`
3. Call `publish_plan`
4. Briefly explain why it is waiting for input before it can publish the plan

It should usually not do a fifth thing:

5. write a long quasi-plan in normal chat and hope the user interprets it as the plan

The agent is not expected to:

- instantly fabricate a default plan on toggle
- restate the entire plan in chat every turn
- edit code while still planning
- continue executing after discovering the plan is stale

## Failure Modes

These are considered regressions:

- entering plan mode immediately creates a giant visible panel
- the model responds with a giant prose plan instead of clarifying
- the model does not know about `ask_plan_questions`
- the model does not know about `publish_plan`
- no plan-mode system context is injected before the first plan exists
- planning mode allows code edits before approval
- visible planning UI appears outside the transcript result system

## Current Implementation Map

Backend:

- `app/services/session_plan_mode.py`
- `app/services/turn_supervisors.py`
- `app/services/sessions.py`
- `app/routers/sessions.py`
- `app/tools/local/ask_plan_questions.py`
- `app/tools/local/publish_plan.py`
- `app/tools/local/request_plan_replan.py`
- `app/tools/local/record_plan_progress.py`

Frontend:

- `ui/src/components/chat/MessageInput.tsx`
- `ui/src/components/chat/renderers/NativeAppRenderer.tsx`
- `ui/src/components/chat/RichToolResult.tsx`
- transcript plan renderer components

Docs:

- this file is the golden document
- shorter references should link here instead of re-defining behavior

## Current Limits

What v1 does well:

- session-local planning contract
- transcript-first plan/question rendering
- Markdown-backed canonical artifact
- revision-aware approval
- snapshot-backed revision history + diff surfaces
- event-driven plan-state sync on the session bus
- one-step-at-a-time execution model
- visible planning-state capsule for decisions/questions before the full plan exists
- metadata-backed runtime capsule injected across context trimming/compaction boundaries
- metadata-backed adherence/evidence ledger for execution
- executing-mode tool guard for stale, blocked, or replan-pending state
- deterministic approval validation
- professional-plan quality gates for key changes, interfaces, assumptions/defaults, concrete steps, and test plan
- explicit replan transition back to planning
- turn-end supervisor for missing execution outcomes
- explicit progress outcome tool that can clear supervisor warnings and advance steps

What v1 does not yet do:

- background detached executor loop
- Slack/Discord parity for this exact workflow
- mature behavioral evaluation of whether the model is planning well beyond static validation
  - Current live coverage includes a behavior tier for ambiguous-scope questions, answer handoff, planning write refusal, missing execution outcomes, stale-plan replan requests, and stale revision rejection.

## Gaps

These are known gaps between the current v1 and the fuller planning system we likely want:

- no detached execution worker
  execution is still session-turn-driven rather than a fully autonomous background loop
- no hard semantic step verifier
  the deterministic supervisor records evidence and gates invalid protocol state, but does not yet prove that every tool action semantically satisfied the step
- no full transcript history model for plan revisions
  revisions exist numerically, but there is no first-class diff/history experience beyond the canonical file and emitted revision artifacts
- no explicit “agent may propose entering plan mode” tool yet
  entry is still user/control-driven in practice
- no mature behavioral eval suite for the whole planning loop
  the deterministic protocol is covered and the live behavior/quality tiers now catch the highest-risk regressions; we still need broader model-behavior evals for question quality and semantic step satisfaction under realistic transcripts

## Future Ideas

Potential next steps, roughly in order of usefulness:

- expand plan validation heuristics
  examples: max-step heuristics, required done-condition checks, oversized-plan warnings
- add behavioral evals for turn-outcome adherence
  the agent should reliably record progress, blocker, replan, verification, or no-progress reason before ending an execution turn under realistic context pressure
- add agent-side “propose plan mode” tooling
  the agent should be able to suggest entering plan mode without silently flipping the session itself
- add revision history/diff UX
  especially useful once plans become a normal part of medium-sized engineering sessions
- add a detached step executor
  once the step contract is reliable enough, the loop can move out of the foreground session turn path
- add broader tests/evals for planning quality
  not just unit tests for plumbing, but behavioral tests that catch regressions in question quality, assumption handling, and semantic step satisfaction

## Maintenance Rule

If any of these change, update this document in the same edit:

- injected planning context
- `ask_plan_questions` semantics
- `publish_plan` semantics
- `request_plan_replan` semantics
- `record_plan_progress` semantics
- runtime capsule or validation semantics
- transcript vs page-level rendering rules
- approval/execution contract
- Markdown artifact structure
- state transitions / ownership
- transcript-native tool/rendering contract

This file is supposed to be the stable reference that future sessions can compare implementation against.
