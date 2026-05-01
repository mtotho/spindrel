---
name: Project Coding Runs
description: >
  Runtime procedure for Project-scoped implementation runs, review sessions,
  handoff receipts, repo-local verification evidence, and finalization of selected Project runs.
triggers: project coding run, project review, coding run review, project handoff, finalize project run, merge selected runs, project screenshots
category: workspace
---

# Project Coding Runs

Use this skill before starting, continuing, reviewing, merging, or finalizing
Project coding runs.

If the user is still shaping a plan, issue list, or multi-part track, load
`workspace/issue_intake` first and use `create_issue_work_packs` to publish
proposed work packs for review. Do not skip straight to implementation unless
the user explicitly asked to launch a coding run.

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
   the Project work surface. Start app/dev servers yourself on the assigned dev
   target ports when present; otherwise choose an unused port. Do not restart
   another agent's process or the host Spindrel e2e/API server. Treat
   `SPINDREL_DEV_*_PORT` values as Project app leases; they are different from
   the host Spindrel API/UI port used by the product under test.
4. If the Project declares a Dependency Stack, call `get_project_dependency_stack`
   before Docker-backed work. Use `manage_project_dependency_stack` to prepare,
   reload, restart, rebuild, inspect logs, run service commands, and check
   health for Docker-backed databases and dependencies. Do not call raw
   `docker` or `docker compose`; edit the Project compose file and reload
   through the tool when stack shape changes.
5. Run the smallest useful repo-local tests first with the native Project
   shell/runtime env. Do not wrap unit tests in Docker, Dockerfile.test, or
   docker compose. For UI work, run typecheck, start the Project app/dev server
   on the assigned dev target port when present, and capture screenshots
   against that server.
6. Near handoff, call `prepare_project_run_handoff(action="open_pr")` when
   GitHub credentials and `gh` are available. If not, record the exact blocker.
7. Finish with `publish_project_run_receipt` including branch, changed files,
   tests, screenshots, dev target URLs/status, handoff URL, and any blockers.

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
- If tests or screenshot capture are unavailable, record the blocker instead of
  claiming verification.
- Dependency Stack evidence should include health, service command results,
  exported env keys, and any reload/restart blockers. App server URLs and
  screenshots belong to the native server process you started for the run.
- Dev target evidence should include each assigned key, URL, port, and whether
  the source-run server was started, checked, blocked, or stopped.

## Boundaries

- Do not import repo-local `.agents` skills into runtime. Repo-dev skills guide
  agents editing Spindrel's source; this runtime skill guides Spindrel bots.
- Do not write secrets or paste secret values into receipts.
- Do not create replacement PRs for continuation runs unless the handoff tool
  reports reuse is impossible.
- Do not rely on ambient Docker access from a harness shell. Dependency Stack
  Docker control must go through Spindrel tools and is for backing services,
  not for running unit tests.
- Do not run repo-dev bootstrap helpers such as `scripts/agent_e2e_dev.py
  prepare`, `start-api`, or `prepare-harness-parity` from an ordinary Project
  coding run. Those are outer-operator setup commands, not Project task steps.
- Do not use or restart `:18000` just because examples mention it. That is a
  common local host Spindrel API default, not a Project app port.
