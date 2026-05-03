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

## Run Brief

Every loop-enabled run needs a Run Brief, either directly in the prompt or in
the source artifact the prompt names. If the prompt says "look at this track"
or "keep working on this document," first narrow it to:

- **Source document:** path plus section when possible.
- **Mission:** the one outcome this loop is allowed to pursue.
- **Stop when:** the concrete condition that makes the loop complete.
- **Stay inside:** files, subsystem, issue class, or phase boundaries.
- **Evidence:** tests, screenshots, PR, receipt, or audit output required.
- **Update:** artifact and section to update before handoff.
- **Review handoff:** what the human should inspect next.

If you cannot form that brief from the prompt, set `loop_decision` to
`needs_review` instead of starting broad discovery. A track is a source of
context, not an infinite work queue.

## `loop_decision` Receipt Field

Every iteration's receipt must include `loop_decision` plus a `loop_reason`
and `remaining_work` for any non-`done` decision.

| `loop_decision` | When to use | Side effect |
|---|---|---|
| `done` | The Run Brief stop condition is satisfied, even if the source document has unrelated open gaps. | Loop ends. |
| `continue` | Concrete remaining work remains inside the same Run Brief mission. | A continuation iteration is created automatically. |
| `needs_review` | The next useful work changes scope, needs a new Run Brief, or requires a human product decision. | Loop pauses; routed to review queue. |
| `blocked` | External input or unavailable access is required. | Loop pauses; blocker recorded. |

`loop_reason` is one or two sentences explaining why. `remaining_work` is the
concrete next slice (file, test, behavior). Vague entries like "more polish"
are not acceptable.

## Stop Conditions

Stop the loop (set `loop_decision="done"`) when any of the following hold:

- The original stop condition in the run prompt is satisfied.
- The Run Brief mission is complete.
- The next useful work would exceed the `Stay inside` boundary.
- New gaps were discovered that need their own Run Brief.
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
- Do not replenish scope from the track, audit, or docs after each iteration.
  Propose a new Run Brief when the current one is done.
