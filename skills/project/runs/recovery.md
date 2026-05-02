---
name: Project Run Recovery
description: >
  Decide whether a Project coding run that failed, stalled, was rejected, or
  ran out its loop budget should continue, retry, hand off, or be
  abandoned. Consolidates the recovery semantics scattered across loop /
  review / queue states.
triggers: project recovery, run recovery, retry run, stalled run, blocked run, follow-up run, continuation, abandon run, can_continue
category: project
---

# Project Run Recovery

Use this skill when a Project coding run is **not** in a clean terminal
state and you need to decide what to do next. Three signals tell you the
run needs a recovery decision rather than a normal review:

- `lifecycle.run_phase` reports `failed` or `stalled`.
- The run's `queue_state` is `changes_requested`, `missing_evidence`, or
  `blocked`.
- A loop iteration's `loop_decision` was `needs_review` or `blocked`.

If none of those apply, this is a normal review - load
`project/runs/review` instead.

## Recovery Modes

| Mode | When to pick it | What actually happens |
|---|---|---|
| `continue` | The run hit a recoverable transient (tool error, dependency restart, single failing test that just needs a fix). `recovery.can_continue` is `true` and `latest_continuation_id` is empty. | Open the continuation path with concrete feedback. Same branch, same Project instance, same Dependency Stack, same PR. Spindrel does not create a replacement PR. |
| `retry` | The run failed before producing any artifact (process died, sandbox preflight blocked, secret missing). The work was not partially done. | Re-launch from the same Run Pack source. Treat the prior attempt as a no-op for review purposes; the next attempt's receipt is the one of record. |
| `hand_off` | The run produced partial work that is correct as far as it went, but the remaining work needs a human decision (new requirement, ambiguous spec, scope split). | Publish a `needs_review` decision via `finalize_project_coding_run_review` with reviewer feedback. Do not silently continue. |
| `abandon` | The Run Pack itself is wrong (duplicate, superseded, no longer wanted). The run cannot succeed because the work should not happen. | Mark the source artifact stale and publish a `rejected` decision. Do not auto-launch a follow-up. |

## Decision Procedure

1. Read `get_project_coding_run_details` for the affected run. Check
   `recovery.can_continue`, `recovery.latest_continuation_id`,
   `lifecycle.run_phase`, and `queue_state`.
2. If `latest_continuation_id` is set, **review the continuation, not the
   parent**. The parent stays in its prior decision state. Skip the rest of
   this procedure.
3. If `recovery.can_continue` is `false`, the choice is `retry`,
   `hand_off`, or `abandon` - never `continue`. Pick based on whether work
   was done (`hand_off`), the run died before doing work (`retry`), or the
   work should not happen at all (`abandon`).
4. If `lifecycle.run_phase=stalled`, do not silently restart. Treat as
   `hand_off` and surface the stall reason from `work_surface.stall_state`
   to the reviewer. Re-engagement is an explicit decision.
5. If a loop iteration's `loop_decision` was `blocked`, copy the
   `loop_reason` into the recovery feedback so the human can resolve the
   blocker before the loop resumes.

## Boundaries

- Do not create a replacement PR for a `continue` decision. The handoff
  tool reuses the existing PR; only fall back when it explicitly reports
  reuse is impossible.
- Do not duplicate a continuation that is already mid-flight
  (`queue_state=follow_up_running`). Wait for it to settle.
- Do not promote a `retry` into a `continue` to "save context" - retry
  starts fresh by design and continue preserves session state.
- Do not abandon a run silently. Every abandon decision needs reviewer
  feedback explaining why so the Run Pack source can be flagged stale.
