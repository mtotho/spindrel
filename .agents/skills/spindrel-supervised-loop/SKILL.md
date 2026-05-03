---
name: spindrel-supervised-loop
description: "Use when the user asks to keep iterating until green, run a bounded supervised loop, fix everything that breaks a suite, repair until passing, or ship one fix per iteration within budget. Generic recipe inherited by concrete loops (harness parity, type sweeps, screenshot regressions, etc.) — children slot in their own suite-runner + spec source + verification gate. Repo-dev skill — not a Spindrel runtime skill."
---

# Project Supervised Loop Iteration

Use this when the user wants a long-running, bounded, mostly autonomous loop
that runs a verification suite, fixes one regression at a time, and stops when
the suite is green or the budget runs out. Concrete loops (`project/loops/harness_parity`,
future `project/loops/type_sweep`, etc.) are *configurations* of this recipe;
they slot in three things and inherit everything else.

Every loop starts from a Run Brief. The brief can come from the user prompt or
from the child skill, but the iteration agent must be able to name the source
document, mission, stop condition, stay-inside boundary, evidence, update
target, and review handoff before editing.

## The contract a child skill must declare

A child skill specializes this recipe by declaring:

- **`mode`**: one of `plan_heavy` or `review_heavy`. Plan-heavy loops verify
  on test green alone. Review-heavy loops also capture screenshot evidence
  and attach it to the receipt for human sample-review.
- **`suite_runner`**: the exact command (or script) that runs the suite and
  emits structured failures. For parity that is
  `python scripts/harness_parity_loop_iteration.py --tier <tier>`. For a type
  sweep it might be `cd ui && npx tsc --noEmit -p tsconfig.json`.
- **`spec_source`**: where the agent goes to confirm the *correct* behavior
  for a failing test. For parity that is `docs/guides/harness-parity.md`.
  For a refactor it might be a track file under `docs/tracks/`.
- **`owning_module_heuristic`**: how to map a failing test back to the file
  that probably needs to change (the script does this when it can; the skill
  reasons about it when it cannot).
- **`gap_artifact_path`**: the repo-resident path the loop writes per-iteration
  reports to (e.g. `.spindrel/audits/harness-parity/<ts>.md`).

## Mode matrix

| | Frontend | Backend |
|---|---|---|
| New features | `review_heavy` (screenshots + visual sample) | `plan_heavy` |
| Refactor / migration | `plan_heavy` | `plan_heavy` |

Three of four cells are plan-heavy. Only frontend new features need the
review-heavy gate, because there green tests can pass while the UX is wrong.

## Procedure

1. **Confirm the loop is allowed to run here.** Read the child skill's
   prerequisites. For loops that need a local e2e stack, defer to whatever
   repo-dev guidance the child skill names; never re-derive that lifecycle.
   If the child skill requires a pre-seeded env file or dev target and it is
   missing, publish a blocked receipt instead of bootstrapping host services.
2. **Confirm the Run Brief.** State the source document, mission, stop
   condition, stay-inside boundary, evidence, update target, and review
   handoff. If the child skill and prompt do not provide a bounded brief,
   publish `decision: "stop", reason: "needs_review"` instead of converting
   the loop into open-ended discovery.
3. **Read state.** Call `get_project_factory_state` and
   `get_project_orchestration_policy`. Confirm canonical repo resolves and
   `concurrency.headroom > 0`. If `concurrency.saturated`, stop with
   `decision: stop, reason: concurrency_saturated` so the user can clear
   in-flight work first.
4. **Run the suite** via `run_script`, using whatever command the child
   skill's `suite_runner` declares. Wait for the run to complete. Read the
   gap-report path the script printed on stdout.
5. **If the report shows zero failures**, publish loop receipt
   `{decision: "stop", reason: "tier_green", evidence: {report: <path>}}`.
   Done.
6. **If the report shows failures**, pick the first gap. Tier-ascending when
   the report carries tier metadata; otherwise the order the suite emitted.
7. **Open the spec row** in the child skill's `spec_source` and the gap's
   `owning_module`. Reason about the smallest change that makes the spec
   true. Do not blanket-rewrite the module; do not add a feature flag; do
   not edit the test to match the broken behavior.
8. **Apply the fix.** Run the single failing test in isolation against the
   leased dev-target port (parity loop) or the appropriate local runner
   (other loops) until it passes. Confirm no other test in the same file
   regressed.
9. **Verify per mode**:
    - **Plan-heavy**: spot-run the suite again on the affected slice; if it
      stays green, proceed to commit.
    - **Review-heavy**: additionally capture screenshots of the touched UI
      surface against the leased dev-target port (the child skill names the
      visual-feedback contract for this Project) and attach the artifact
      paths to the receipt's `evidence` field. Continue without human
      approval; the artifact lets a human sample-review the morning batch.
10. **Commit + push** with a tight message: `<scope>: fix <test_id>` (or the
   equivalent slug for non-test failures). One commit per iteration.
11. **Publish loop receipt** `{decision: "continue", fixed: <test_id>,
    remaining: <count>, mode: <mode>, evidence: {...}}`. The existing
    `check_project_coding_run_loop_continuation` policy fires the next
    iteration up to the bounded budget (default `max_iterations=5,
    max_time_minutes=60`).
12. **On stop conditions**, do NOT tear down the e2e stack the child skill
    brought up — leave it for the next iteration or for human inspection.
    The schedule's terminal step (or the user) tears it down per the child
    skill's lifecycle.

## Stop conditions (publish `decision: "stop"`)

- Suite returns zero failures (`reason: "tier_green"`).
- Concurrency cap saturated (`reason: "concurrency_saturated"`).
- Same gap fixed and immediately re-failed (`reason: "fix_did_not_stick"`).
- Two iterations in a row produced no commits (`reason: "no_progress"`).
- Mode is review-heavy and the screenshot evidence step failed
  (`reason: "evidence_capture_failed"`).
- Budget exhausted (handled by the continuation policy, not this skill).
- The Run Brief mission is complete, even if the source document contains
  more possible work.
- The next useful gap falls outside the Run Brief stay-inside boundary.

## Boundaries

- This skill does not pick the *suite*. The child skill does.
- This skill does not edit other skills, even when its own gaps suggest a
  skill is undertriggering. That is the retro skill's job.
- This skill does not auto-merge PRs. The morning review pass (or a separate
  review-loop schedule per Phase 4L) merges accepted work.
- This skill does not promote a screenshot to canonical docs. That is a
  human gate.
