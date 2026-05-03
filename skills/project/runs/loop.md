---
name: Project Run Loop
description: >
  Bounded continuation loop policy for Project coding runs - the loop_decision
  receipt contract, stop conditions, and what each decision means.
triggers: project loop, run loop, loop_decision, continue run, bounded loop, run continuation
category: project
---

# Project Run Loop

Use this skill when a Project coding run prompt declares a bounded loop is
enabled. A loop is **not** a separate orchestrator - it reuses the existing
Project coding-run continuation path: same branch/PR, same session execution
environment when available, one receipt per iteration.

## `loop_decision` Receipt Field

Every iteration's receipt must include `loop_decision` plus a `loop_reason`
and `remaining_work` for any non-`done` decision.

| `loop_decision` | When to use | Side effect |
|---|---|---|
| `done` | Stop condition is satisfied. | Loop ends. |
| `continue` | Concrete remaining work that should start the next automatic continuation. | A continuation iteration is created automatically. |
| `needs_review` | A human should decide before more work happens. | Loop pauses; routed to review queue. |
| `blocked` | External input or unavailable access is required. | Loop pauses; blocker recorded. |

`loop_reason` is one or two sentences explaining why. `remaining_work` is the
concrete next slice (file, test, behavior). Vague entries like "more polish"
are not acceptable.

## Stop Conditions

Stop the loop (set `loop_decision="done"`) when any of the following hold:

- The original stop condition in the run prompt is satisfied.
- The loop budget has been exhausted.
- A receipt is missing for the previous iteration.
- The latest decision was not `continue`.

## Inspecting Loop State

`get_project_coding_run_details` returns a `loop` object on loop-enabled runs.
Use it to:

- Confirm the loop is still active before deciding to continue.
- See the budget remaining.
- Read prior `loop_decision` history.

If the loop is disabled or the budget is exhausted, do not invent more
iterations - hand off to review or report blockers.

## Boundaries

- Do not start a loop without an explicit prompt instruction enabling it.
- Do not change the branch or replace the session execution environment
  mid-loop unless the user explicitly asks for a retry with a fresh run.
- Do not skip publishing a receipt - the loop scheduler reads it to decide
  whether to continue.
- Do not use the loop to do work the user did not approve.
