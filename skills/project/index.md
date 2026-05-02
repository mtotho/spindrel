---
name: Project
description: >
  Entry point for any Project-bound conversation. Routes to the right next-step
  skill based on Project Factory stage instead of guessing from the user's
  phrasing.
triggers: project, project factory, what next, project workflow, project run, project review, project intake, what should we do, where are we at
category: project
---

# Project

Use this skill in any Project-bound channel. It is the cluster entry point for
the whole Project Factory: setup, planning, intake, Run Packs, coding runs,
review, and follow-up. The first action is always state-driven, not
phrase-matched.

## First Action

1. Call `get_project_factory_state`. It returns the current stage, what is
   ready, what is pending, and the recommended next skill to load.
2. Tell the user the stage in plain language and what you are about to do.
3. Load the recommended skill below based on `current_stage`. Do not skip the
   recommendation just because the user mentioned a different topic.

## Stage Routing

| `current_stage` | Load next | Why |
|---|---|---|
| `unconfigured` | `project/setup/init` | No applied Blueprint or runtime not ready. |
| `ready_no_work` | ask the user what they want to build, then route | Configured, idle. |
| `planning` | `project/plan/prd` | A PRD/brief is in progress; resume it. |
| `shaping_packs` | `project/plan/run_packs` | Proposed Run Packs need triage or expansion. |
| `runs_in_flight` | `project/runs/implement` (implementer) or `project/runs/review` (reviewer) | Active coding runs or active review tasks. |
| `needs_review` | `project/runs/review` | One or more runs are `ready_for_review` with no active reviewer. |
| `reviewed_idle` | ask the user what is next | All runs reviewed. |
| `get_project_factory_state` itself errored | report the error verbatim, do not retry blindly | The state call is the cluster's first action; if it fails, surface the failure to the user before guessing a stage. |
| Channel is not Project-bound | stop and ask the user to attach the channel to a Project | This skill cluster only operates inside Project-bound channels; do not improvise. |
| `readiness.blockers` is non-empty | route to `project/setup/init` regardless of `current_stage` | Unresolved setup blockers (missing Blueprint, secret slot, unconfigured intake) gate everything downstream. |

If the user is dumping rough bugs or ideas in any stage, recognise it and load
`project/intake` for the capture path. Intake is conversational; it never
launches work.

If the user asks for a *thematic sweep* of the Project ("deep security
audit", "find all the slow endpoints", "sweep for accessibility issues"),
load `project/plan/audit_to_runs`. That skill chains research → findings
artifact → Run Packs → bounded launch loop → review cadence end-to-end.
It is the recipe behind the dream "one prompt becomes a body of work" flow.

If a run is in a non-terminal failure state (`failed` / `stalled`,
`changes_requested`, `missing_evidence`, `blocked`, or a loop iteration
returned `needs_review` / `blocked`), load `project/runs/recovery` to pick
between `continue`, `retry`, `hand_off`, and `abandon` instead of treating
it as a normal review.

Before launching another implementation run (single or batch) or starting a
bounded run loop, call `get_project_orchestration_policy`. It returns the
effective concurrency cap with live `in_flight` and `headroom`, the stall /
turn timeouts with their source (`blueprint` vs `default` vs `unset`), and
the raw `## policy` section from `.spindrel/WORKFLOW.md` when present. If
`concurrency.saturated` is true, do not launch - tell the user the cap and
ask whether to wait, raise the Blueprint cap, or cancel a pending run.

## Work Surface Discipline

Every project skill in this cluster shares the same starting boundary:

1. Confirm the channel is Project-bound. If not, stop and ask the user to
   attach it to a Project.
2. Read `project.work_surface.root_path` from `list_agent_capabilities`. Treat
   that as the Project root. Never assume `pwd` equals the Project root - the
   user may run from a workspace root such as `/common/projects` that holds
   several repo siblings.
3. Formal coding runs report `kind="project_instance"` and `isolation="isolated"`.
   If a formal run reports a missing/blocked/deleted/shared work surface, stop
   and report that readiness blocker; do not edit the shared root.

## Operating Rules

- Tell the user which sub-skill you are loading and why.
- Stay conversational while planning. Do not launch coding runs in the middle of
  a PRD or Run Pack discussion unless the user explicitly says "launch".
- Use repo-owned files for durable planning material (`.spindrel/prds/*.md`,
  `docs/tracks/*.md`). Use Spindrel Issue Intake and Run Packs for the
  coordination layer.
- When switching stages, summarize the current artifact and the proposed next
  step before moving on.

## Boundaries

- Do not copy repo-local `.agents/` files into runtime skill storage. Read them
  for Project context only.
- Do not turn Issue Intake or Run Packs into the canonical external tracker.
  GitHub, Linear, or a repo file remains the durable home if one exists.
- Do not write secrets into receipts, Run Pack prompts, or repo-owned planning
  files.
