---
name: Project Run Review
description: >
  Review Project coding runs - read the right context tool, route by queue
  state, finalize accepted work, decide between accepted/rejected/blocked, and
  hand off follow-ups without colliding with other reviewers.
triggers: project review, coding run review, review project run, finalize project run, merge selected runs, what changed, latest review
category: project
---

# Project Run Review

Use this skill when the user asks to review, summarize, or finalize one or
more Project coding runs, or when `current_stage=needs_review` from
`get_project_factory_state`.

## Source of Truth

1. **In a review session task**: call `get_project_coding_run_review_context`.
   It returns the selected runs, readiness, evidence, handoff links, and
   finalization rules. Treat this as authoritative.
2. **Outside a review session** (ad hoc latest-run questions): call
   `get_project_coding_run_details`. Omit `task_id` to retrieve the latest
   meaningful run (newest reviewed or ready-for-review run, falling back to
   newest run when no reviewable run exists).
3. Use the returned `links.project_run_url` for the full review page.
   Summarize `receipt`, `review`, `evidence`, `activity`, blockers in plain
   language - do not dump raw JSON unless asked.

## Queue State Routing

Each run carries a queue state. Decide what to do based on it:

| Queue state | What to do |
|---|---|
| `ready_for_review` | Run `get_project_coding_run_review_context`, inspect, decide. The user's actionable next step. |
| `changes_requested` | Open the continuation path with concrete feedback. Do not re-finalize. |
| `missing_evidence` | Block. Ask the implementing agent to publish receipt evidence (tests, screenshots, dep health) before finalizing. |
| `follow_up_running` | Wait. A continuation is mid-flight; do not duplicate it. |
| `follow_up_created` | Review the follow-up, not the parent. The parent stays in its previous decision state. |
| `reviewing` | Another reviewer is active. Do not collide; either skip or coordinate explicitly. |
| `blocked` | Inspect the blocker. May need operator action - capture the blocker; do not pretend it is reviewable. |
| `reviewed` | Terminal. No action. |

## Review Session Procedure

1. Call `get_project_coding_run_review_context` before deciding.
2. Inspect each selected run's receipt, PR/handoff, tests, screenshots, and
   blockers. Do not infer evidence that is not in the context or the PR.
3. Call `finalize_project_coding_run_review` once per selected run you
   reviewed.
4. Outcomes:
   - `accepted` - work is ready under the requested merge policy.
   - `rejected` - changes are needed; provides feedback for follow-up. Does
     not mark the run reviewed; follow-ups can continue.
   - `blocked` - missing evidence, failing checks, or unmergeable PR. Does
     not mark the run reviewed.
5. Use `merge=true` only when the operator explicitly asked this review
   session to merge accepted work.

## Recovery and Follow-Up

For failed, blocked, stale, or `changes_requested` runs, check
`review.recovery`. If `can_continue` is true, open the continuation path with
concrete feedback. If `latest_continuation_id` is present, review or summarize
that follow-up before creating another. Do not continue active or already
reviewed runs.

## Boundaries

- Review and triage work must be visible as a normal session/task. Do not hide
  it inside background heartbeats.
- Use `merge=true` only with explicit operator ask. Default is review without
  merge.
- Do not finalize a run as `accepted` if you have not actually inspected the
  PR/evidence.
