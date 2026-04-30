---
name: Native Session Planning
description: >
  Runtime procedure for Spindrel's native session plan mode: structured
  questions, publish_plan, approval-gated execution, record_plan_progress,
  replan recovery, and adherence review. Use when a session is in Planning,
  Executing, Blocked, or Done plan mode, or before using ask_plan_questions,
  publish_plan, record_plan_progress, or request_plan_replan.
triggers: native planning, plan mode, publish plan, record plan progress, request replan, plan adherence, plan questions
category: core
---

# Native Session Planning

Use this when the current session is in native plan mode or you are about to
use planning tools.

## First Action

Look at the current plan runtime state before choosing a tool:

- mode: planning, executing, blocked, done, or chat
- current accepted revision and current step
- latest tool feedback, latest outcome, semantic review, and pending blockers
- submitted plan-question answers and assumptions/defaults

If the runtime capsule is missing, use the visible transcript plan card and the
latest tool results as the source of truth.

## Planning Loop

1. If scope is unclear, call `ask_plan_questions`.
2. If enough is known, call `publish_plan`; do not write the plan as normal chat
   prose.
3. A publishable plan must include key changes, interfaces, assumptions/defaults,
   concrete steps, acceptance criteria, and test plan.
4. If `publish_plan` returns validation feedback, revise the exact failing
   field and retry once. Do not ask the user to repair mechanical labels.
5. Wait for approval before mutating non-plan files or external state.

## Execution Loop

1. Execute only the accepted revision and current step.
2. After a meaningful turn, call `record_plan_progress` with progress, blocked,
   verification, no_progress, or step_done.
3. If `step_done` uses a workspace path as evidence, or if you claim
   verification/readback, first perform the matching read/check tool call for
   that evidence path.
4. If the accepted plan is stale, call `request_plan_replan` as the only plan
   outcome for the turn; do not call `record_plan_progress` first and do not
   continue with unstated assumptions.
5. If semantic review marks an outcome unsupported, correct the outcome or
   repeat the step before mutating again.

## Boundaries

- Do not use repo-local `.agents` skill text as runtime guidance.
- Do not bypass plan approval to satisfy a user request faster.
- Do not turn every warning into a new tool rule. If the model needs ordering or
  examples, update this skill first.
- Do not hide validation errors; make them the next actionable plan focus.
