---
title: Plan - Project Factory Cohesion Pass
summary: Five-phase plan to make the Project Factory cohesive enough for daily personal use - rename Work Pack to Run Pack, move skills to skills/project/, add stage-aware factory-state primitive, decompose runs skill, add Symphony-equivalent observability.
status: active
tags: [spindrel, plan, projects, project-factory, cohesion]
created: 2026-05-02
updated: 2026-05-02
---

# Plan - Project Factory Cohesion Pass

## TL;DR

The Project Factory backend, UI, and operational surface have grown faster than the runtime-skill surface that agents read. Right now an agent in a Project-bound channel can't tell what stage of the lifecycle it's in, the project skills live under the wrong namespace (`workspace/`), the canonical "Run Pack" unit is still called "Work Pack", and there is no Symphony-equivalent observability for run phase, stalls, or concurrency. This plan closes that gap in five phases. Phase 0 (rename + namespace move) and Phase 1 (`get_project_factory_state`) are load-bearing; the rest depend on them.

## Context

- The Projects track (`docs/tracks/projects.md`) has shipped Phases 4O through 4AX - intake, run packs, batch launch, review ledger, schedule cockpit, recovery, review inbox, Symphony scavenging pass.
- The runtime skills under `skills/workspace/project_*` are several phases behind the backend. They route by user phrase, not by Project state. They duplicate concerns. The `project_coding_runs.md` skill alone mixes implementation, review, scheduling, and loop-decision contracts in one ~170-line file.
- The user's stated dogfood test: open a Project-bound channel against a brand-new Project, say "I want to build X", reach a Blueprint + PRD + three proposed Run Packs in under six messages, all visible in the cockpit. Same channel later: pile up intake without nag; trigger triage on demand.
- Tracker-agnostic intake is a deliberate feature, not a Symphony gap. Slack mirroring already exists - any channel can be Slack-bound and behaves the same. No source-adapter work is needed for the cohesion pass.
- The user often runs from `cwd = /common/projects` (workspace root containing multiple project repos). Skills must use `WorkSurface.root_path`, never `pwd`.

## Goals

- An agent in any Project-bound channel can answer "what stage am I in and what should we do next?" without the user naming a skill.
- Every project skill body is under 100 lines and has a single audience.
- Run phase, stall state, and concurrency cap are first-class on every Project coding run.
- The unit of launchable work is named `RunPack` (DB, API, tools, UI, docs).
- Project skills live under `skills/project/`, not `skills/workspace/`.

## Non-Goals

- Source adapters (GitHub, Linear, Slack ingestion). Slack mirroring already exists.
- Auto retry-with-backoff for transient run failures.
- Spatial canvas changes (Factory Status pane).
- Workflow visual builder.
- Multi-tenancy.

## Phase order (revised after Codex review)

The factory-state primitive is the leverage win and ships first. Renames are risky and gated behind real dogfood data; they happen after agents are useful.

1. **Phase 4AZ** - Stage-aware factory-state primitive (load-bearing for Phase 4BA).
2. **Phase 4BA** - Skill decomposition with stage routing (consumes 4AZ).
3. **Phase 4BB** - Symphony-equivalent observability (parallelizable with 4BA).
4. **Phase 4AY-a** - Skill namespace + product copy: `skills/project/` + UI/copy says "Run Pack". Old skill IDs aliased for transitional period.
5. **Phase 4AY-b** - Internal `IssueWorkPack` -> `RunPack` rename: DB tables, FK columns, Python classes, tool IDs. Migration with alias support so existing dogfood data survives.
6. **Phase 4BC** - Canonical orchestration policy view.

## Phase 4AZ - Stage-aware primitive

The single load-bearing piece that unblocks Phase 4BA. Built using current `IssueWorkPack` naming; renamed in Phase 4AY-b.

### New API

`GET /api/v1/projects/{project_id}/factory-state`

Returns:

```json
{
  "current_stage": "unconfigured | ready_no_work | planning | shaping_packs | runs_in_flight | needs_review | reviewed_idle",
  "blueprint": {"applied": true, "snapshot_id": "..."},
  "runtime_env": {"ready": true, "missing_secrets": []},
  "dependency_stack": {"declared": false, "ready": null},
  "dev_targets": [{"key": "...", "url": "...", "status": "..."}],
  "intake": {"pending_count": 12, "triaged_count": 0},
  "run_packs": {"proposed": 3, "needs_info": 1, "not_code_work": 0, "launched": 0, "dismissed": 0},
  "runs": {"by_queue_state": {"ready_for_review": 0, "changes_requested": 0, "missing_evidence": 0, "follow_up_running": 0, "follow_up_created": 0, "reviewing": 0, "blocked": 0, "reviewed": 0}},
  "review_tasks_active": 0,
  "recent_receipts": [{"task_id": "...", "summary": "...", "at": "..."}],
  "concurrency": {"in_flight": 0, "cap": null},
  "suggested_next_action": {
    "stage": "unconfigured",
    "headline": "This Project has no recipe yet. Apply a Blueprint to get started.",
    "skill_id_to_load": "project/setup/blueprint",
    "why": "current_stage=unconfigured and blueprint.applied=false"
  }
}
```

### New tool

`get_project_factory_state(project_id?)` - defaults to active channel's Project. Wraps the API.

### Backing module

`app/services/project_factory_state.py` - composes existing services (`projects.py`, `project_coding_runs.py`, `project_run_receipts.py`, `project_runtime.py`, `project_dependency_stacks.py`). Does not reach into private internals.

### Stage classification rules

Explicit precedence (highest first wins; first match wins):

1. `unconfigured` - no applied Blueprint OR `runtime_env.ready=false`.
2. `needs_review` - one or more runs with queue state `ready_for_review` AND zero active review tasks. (Wins over `runs_in_flight` because the user's next action is review.)
3. `runs_in_flight` - any run with queue state in {`changes_requested`, `follow_up_running`, `reviewing`, `blocked`, `missing_evidence`}, OR an active review task exists, OR an implementation run is mid-execution (no terminal receipt).
4. `shaping_packs` - one or more Run Packs in `proposed` or `needs_info`, none of the higher-stage conditions apply.
5. `planning` - any of: a known PRD/brief artifact reference exists on the Project (e.g. `prd_path` in Project metadata), a recent `planning` execution receipt exists within last N days, or a heuristic file scan finds `.spindrel/prds/*.md` / `docs/tracks/*.md` recently modified by a Project channel session. File presence is one signal, not the definition.
6. `ready_no_work` - configured, zero intake, zero packs, zero runs.
7. `reviewed_idle` - all runs `reviewed`, no pending packs, no pending intake.

### UI mirror

Same payload backs the Project detail page Factory Status pane. Both agents and humans see the same world. Avoid building a parallel UI-only assembly.

### Exit criteria

- Unit test asserts each stage classification with seeded fixtures.
- New tool callable from a Project-bound channel; returns the structure above.
- Unbound channel returns explicit unbound error, not a default Project.

## Phase 4BA - Skill decomposition with stage routing

Depends on Phase 4AZ (factory-state). Skill namespace move can land in parallel via Phase 4AY-a; this phase can use either old or new namespace.

### Final layout

```
skills/project/
- index.md                  # cluster index; first action: get_project_factory_state
- setup/
  - init.md                 # was project_init.md; failsafe for unbound channel; cwd-vs-root warning
  - blueprint.md            # NEW - recipe model end-to-end (declare -> apply -> snapshot -> fresh instance)
- plan/
  - prd.md                  # was project_prd.md; adds "discover existing planning material" first step
  - run_packs.md            # was project_stories.md; adds triage_receipt schema and size norm
- intake.md                 # reshape around recognition, not capture-on-explicit-ask
- runs/
  - implement.md            # implementation slice from project_coding_runs.md
  - review.md               # review slice + the 8 queue states with what-to-do-next
  - scheduled.md            # scheduled-run slice
  - loop.md                 # bounded-loop policy + loop_decision contract
```

### `skills/project/index.md` first action (the cohesion fix)

1. Call `get_project_factory_state`.
2. Route on `current_stage`:
   - `unconfigured` -> load `project/setup/init.md` (or `blueprint.md` if init complete but no recipe).
   - `ready_no_work` -> ask user "what do you want to build?", then route to `plan/prd.md` or `plan/run_packs.md`.
   - `planning` -> load `plan/prd.md` and resume the existing PRD.
   - `shaping_packs` -> load `plan/run_packs.md`.
   - `runs_in_flight` -> load `runs/implement.md` if user is the implementer; `runs/review.md` if reviewing.
   - `needs_review` -> load `runs/review.md`.
   - `reviewed_idle` -> ask user what is next, route accordingly.
3. Always tell the user the stage and proposed next action in plain language.

### Every skill's first action additions

- Step 1: call `list_agent_capabilities`, read `project.work_surface.root_path`. Use that, not `pwd`.
- If channel is not Project-bound, stop and surface the unbound state.
- Explicit warning: cwd may be a multi-project workspace root (`/common/projects`); never assume cwd equals Project root.

### `skills/project/intake.md` - reshape around recognition

Today: structured as "user explicitly asks to save -> call tool". Wrong.

New shape:
1. **Recognition rules** - when user says things like "oh and X is broken", "we should also...", "annoying that Y", "future idea: Z", treat as intake-candidate.
2. **Confirm-and-capture pattern** - short ack ("noted as intake - bug or idea?") then `publish_issue_intake`. Do not interrupt the active conversation thread. Do not write into channel notes.
3. **Pile-up tolerance** - agent does not push triage. Items accumulate. Only when user says "what is piled up" or "let's triage" does agent shift to grouping mode (load `plan/run_packs.md`).
4. **Triage on demand** - call `list_issue_intake`, propose Run Pack groupings, never auto-publish.
5. **Lifecycle integration** - factory-state surfaces "you have N pending intake items" when user opens a fresh session, but does not nag.

### `skills/project/runs/review.md` must list 8 queue states

Each with one line on next action:
- `ready_for_review` -> run `get_project_coding_run_review_context`, decide
- `changes_requested` -> continuation path with feedback
- `missing_evidence` -> block, ask agent to publish receipt evidence, do not finalize
- `follow_up_running` -> wait, do not duplicate
- `follow_up_created` -> review the follow-up, not the parent
- `reviewing` -> another reviewer is active, do not collide
- `blocked` -> inspect blocker, may need operator
- `reviewed` -> terminal, no action

### `skills/project/plan/run_packs.md` must include

- `triage_receipt` schema with example (currently required by Phase 4AI but never specified in runtime skill).
- Size norm: 1 pack = 1 PR target, ~500 LOC diff sweet spot, split larger.
- Flag for packs that change the recipe (Blueprint impact).

### `skills/project/plan/prd.md` must add

- First step: sweep `docs/roadmap.md`, `docs/tracks/*.md`, `docs/architecture-decisions.md`, `AGENTS.md` for prior decisions and constraints before drafting.

### Exit criteria

- Every project skill is single-purpose and scannable. (No hard line cap; pressure not rule.)
- Cluster has one entry point (`index.md`).
- Small-model agent can route from cold start using only `get_project_factory_state` output.
- A user typing "what's next?" in any Project-bound channel gets a stage-grounded answer.

## Phase 4BB - Symphony-equivalent observability

Independent of Phase 4BA; can run in parallel.

### Run `phase` field

- Enum: `preparing | branching | editing | testing | handoff | review_ready | reviewed | failed | stalled`.
- Derived from existing receipt + activity stream + queue state.
- Persisted on the run row.
- Returned by `get_project_coding_run_details`.
- `runs/implement.md` consumes it ("if your latest phase is `testing`, finish the test pass before opening the PR").

### Stall + turn timeout policy on Blueprint snapshot

- New Blueprint fields: `stall_timeout_seconds` (default 1200), `turn_timeout_seconds` (default 3600).
- Background sweep transitions runs with no event activity past `stall_timeout` to `phase=stalled` AND queue state `blocked`. The two fields stay distinct: `phase=stalled` says "no recent activity, recoverable"; queue state `blocked` says "needs operator attention". UI shows both.
- Stall reason recorded on the receipt.
- Surface in Project Runs UI as a visible badge.

### Per-Project concurrency knob

- Blueprint field: `max_concurrent_runs` (default unlimited).
- Launch path checks; over-cap launches refuse with a clear reason or queue.

### Exit criteria

- Stalled run shows badge within `stall_timeout`.
- Concurrency cap blocks the 4th run when set to 3.
- `phase` visible on every run detail page.

## Phase 4AY-a - Skill namespace + product copy

Skill files relocated, product language updated to "Run Pack". Internal class/table names unchanged.

- Move `skills/workspace/project_*.md` + `skills/workspace/issue_intake.md` -> `skills/project/`.
- Update `STARTER_SKILL_IDS` in `app/config.py`.
- Update `SKILL_ROUTING_TABLE` in `app/services/agent_capabilities.py:110-188`.
- Update `skills/index.md:14-15` to add `project` cluster.
- Trim Project section out of `skills/workspace/index.md`.
- **Old skill IDs aliased** in `app/services/skills_registry.py` (or equivalent resolver) so any persisted enrollment under `workspace/project_*` still resolves. Aliases stay until 4AY-b ships.
- UI/docs/help text says "Run Pack" (not "Work Pack") wherever the product surface speaks to a user. Internal API field names unchanged in this phase.

## Phase 4AY-b - Internal RunPack rename

Done after dogfood proves the new UX is sticky. Cleanly migrated.

- Migration: `issue_work_packs` -> `issue_run_packs`; rename FK columns `*_work_pack_id` -> `*_run_pack_id`. Migration includes view aliases or a deprecation window so in-flight tasks survive.
- Python: `IssueWorkPack` -> `RunPack`; module names `*work_pack*` -> `*run_pack*`.
- Tool IDs: `create_issue_work_packs` -> `create_run_packs` with old ID alias for one release; `report_issue_work_packs` -> `report_run_packs` similarly.
- API field names: change `work_pack` -> `run_pack` in payloads with deprecation field.
- Tests: rename in fixtures and assertion strings.

## Phase 4BC - Single canonical orchestration policy view

Last; nice-to-have.

- New endpoint `GET /api/v1/projects/{id}/orchestration-policy` - merged view of Blueprint snapshot + Project Runbook + run preset defaults.
- New tool `get_project_orchestration_policy(project_id?)` - same payload, agent-readable.
- Optional repo mirror: if `.spindrel/project-orchestration.yml` exists, it overrides matching Blueprint fields. Reviewable in source without forcing it.

## Order and dependencies

| Phase | Depends on | Can parallelize with |
|---|---|---|
| 4AZ - factory-state | nothing | 4BB |
| 4BA - skill decomposition | 4AZ | 4BB, 4AY-a |
| 4BB - observability | nothing | 4AZ, 4BA |
| 4AY-a - skill namespace + copy | nothing (uses aliases) | any |
| 4AY-b - internal RunPack rename | dogfood validation of new UX | nothing (high blast radius) |
| 4BC - canonical policy | 4BB (uses stall/timeout/concurrency fields) | nothing |

## Dogfood acceptance test

You open a brand-new Project-bound channel against an empty repo. You say "I want to build X." Within 6 messages: one Blueprint applied, one PRD draft saved at `.spindrel/prds/x.md`, three Run Packs proposed and visible in the Project Runs cockpit, none launched without your explicit "go".

Same channel a day later: you say "the Y page is slow". Agent recognizes intake, captures, does not launch anything. Pile grows over the week. You say "triage". Agent calls `list_issue_intake`, proposes Run Pack groupings, you approve and launch.

If both flows work without you ever loading a skill by name, the cohesion pass succeeded.

## Open questions

- Does `.spindrel/project-orchestration.yml` mirror happen in Phase 4 or stay deferred?
- Should `phase=stalled` auto-transition to `blocked`, or stay distinct so operators see "stalled" as a recoverable state?
- Run Pack URL/route rename: `/hub/attention?mode=issues` is acceptable for now; revisit when intake routes are reorganized.
