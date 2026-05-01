---
name: Project Coding Runs
description: >
  Runtime procedure for Project-scoped implementation runs, review sessions,
  handoff receipts, e2e evidence, and finalization of selected Project runs.
triggers: project coding run, project review, coding run review, project handoff, finalize project run, merge selected runs, e2e screenshots
category: workspace
---

# Project Coding Runs

Use this skill before starting, continuing, reviewing, merging, or finalizing
Project coding runs.

## Scheduled Runs

1. Use `schedule_project_coding_run` when the operator asks for recurring
   Project review, maintenance, or implementation work in the current
   Project-bound channel.
2. Write the schedule request as the full run prompt. Include expected
   outputs: tests, screenshots when relevant, PR/handoff, and a Project run
   receipt.
3. If no code change is needed for a scheduled review, publish a no-change
   Project run receipt rather than opening an empty PR.
4. Treat each schedule fire as a normal Project coding run: inspect state,
   prepare the branch, run verification, and hand off evidence.

## Implementation Runs

1. Confirm you are in the Project work surface. Use the Project root for file,
   command, test, screenshot, and handoff work.
2. Before editing, inspect current state and call
   `prepare_project_run_handoff(action="prepare_branch")`.
3. Make focused changes with your native harness file and shell tools inside
   the Project work surface. Start app/dev servers yourself on an assigned or
   unused port; do not restart another agent's process.
4. If the Project declares a Dependency Stack, call `get_project_dependency_stack`
   before Docker-backed work. Use `manage_project_dependency_stack` to prepare,
   reload, restart, rebuild, inspect logs, run service commands, and check
   health for Docker-backed databases and dependencies. Do not call raw
   `docker` or `docker compose`; edit the Project compose file and reload
   through the tool when stack shape changes.
5. Run the smallest useful tests first. For UI work, run typecheck and capture
   screenshots against the configured e2e target when available.
6. Near handoff, call `prepare_project_run_handoff(action="open_pr")` when
   GitHub credentials and `gh` are available. If not, record the exact blocker.
7. Finish with `publish_project_run_receipt` including branch, changed files,
   tests, screenshots, handoff URL, and any blockers.

## Review Sessions

1. Call `get_project_coding_run_review_context` before deciding. Treat its
   selected runs, readiness, evidence, handoff links, and finalization rules as
   the source of truth.
2. Inspect each selected run's receipt, PR/handoff, tests, screenshots, and
   blockers. Do not infer evidence that is not in the context or the PR.
3. Use `merge=true` only when the operator explicitly asked this review
   session to merge accepted work.
4. Call `finalize_project_coding_run_review` once per selected run you reviewed.
   Use `accepted` only for work that is ready under the requested merge policy.
5. Use `rejected` or `blocked` when evidence is missing, checks fail, the PR
   cannot be merged, or changes are needed. Those outcomes do not mark the run
   reviewed, so follow-up work can continue.

## Evidence Rules

- Test evidence should name the command and result.
- Screenshot evidence should include paths or structured screenshot records.
- Handoff evidence should include the branch and PR URL when available.
- If e2e or screenshot capture is unavailable, record the blocker instead of
  claiming visual verification.
- Dependency Stack evidence should include health, service command results,
  exported env keys, and any reload/restart blockers. App server URLs and
  screenshots belong to the native server process you started for the run.

## Boundaries

- Do not import repo-local `.agents` skills into runtime. Repo-dev skills guide
  agents editing Spindrel's source; this runtime skill guides Spindrel bots.
- Do not write secrets or paste secret values into receipts.
- Do not create replacement PRs for continuation runs unless the handoff tool
  reports reuse is impossible.
- Do not rely on ambient Docker access from a harness shell. Dependency Stack
  Docker control must go through Spindrel tools.
