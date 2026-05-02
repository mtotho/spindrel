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

If the user is doing ad hoc Project-bound code, test, e2e, screenshot, setup,
or feedback-loop work without a formal Project coding run, do not load a broad
runtime Project skill. Ask the user to attach the relevant Project-local files
or dependency context with composer mentions such as `@file:<path>` or
`@project:dependencies`, then use normal shell/file tools in the Project root.
Ad hoc sessions use the shared Project root by default, like a normal CLI
checkout. If the user wants parallel ad hoc work that should not touch the
shared root, ask them to start an isolated Project session; that binds the
session to a fresh Project instance and gives dependency-stack tools a
Project-instance-scoped stack.

Blueprints are durable Project recipes. Fresh Project instances are disposable
copies created from the Project's applied Blueprint snapshot. Do not treat a
Blueprint as per-run state; update it only when the setup recipe changes, such
as repos, branch, setup commands, env slots, dependency stack, or dev targets.
Fresh instances clone the declared branch when they are created, so they pick
up the latest remote state at that moment.

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
5. When recurring work needs adjustment, edit/resume the existing schedule
   rather than creating a duplicate. Concrete schedule fires remain normal
   Project coding runs and should be reviewed through the Project Runs cockpit.

## Implementation Runs

1. Confirm you are in the Project work surface. Use the Project root for file,
   command, test, screenshot, and handoff work.
   Formal Project coding runs already use a fresh Project instance, generated
   branch, run-scoped Dependency Stack, and assigned dev target ports.
2. If you need to verify isolation, call `list_agent_capabilities` and read
   `project.work_surface`. Formal coding and review runs should report
   `kind="project_instance"` and `isolation="isolated"` after startup. If a
   formal run reports a missing, blocked, deleted, or shared work surface,
   stop and report that readiness blocker instead of editing the shared root.
3. Before editing, inspect current state and call
   `prepare_project_run_handoff(action="prepare_branch")`.
4. Make focused changes with your native harness file and shell tools inside
   the Project work surface. Start app/dev servers yourself on the assigned dev
   target ports when present; otherwise choose an unused port. Do not restart
   another agent's process or the host Spindrel e2e/API server. Treat
   `SPINDREL_DEV_*_PORT` values as Project app leases; they are different from
   the host Spindrel API/UI port used by the product under test.
5. If the Project declares a Dependency Stack, call `get_project_dependency_stack`
   before Docker-backed work. Use `manage_project_dependency_stack` to prepare,
   reload, restart, rebuild, inspect logs, run service commands, and check
   health for Docker-backed databases and dependencies. Do not call raw
   `docker` or `docker compose`; edit the Project compose file and reload
   through the tool when stack shape changes.
6. Run the smallest useful repo-local tests first with the native Project
   shell/runtime env. Do not wrap unit tests in Docker, Dockerfile.test, or
   docker compose. For UI work, run typecheck, start the Project app/dev server
   on the assigned dev target port when present, and capture screenshots
   against that server.
7. Near handoff, call `prepare_project_run_handoff(action="open_pr")` when
   GitHub credentials and `gh` are available. If not, record the exact blocker.
8. Finish with `publish_project_run_receipt` including branch, changed files,
   tests, screenshots, dev target URLs/status, handoff URL, and any blockers.
   Make the receipt review-ready: use structured records where useful, such
   as `{path,status,summary}` for files, `{command,status,exit_code,summary}`
   for tests, `{path,url,label,viewport,notes}` for screenshots, and metadata
   for risks, follow-ups, dependency health, PR notes, and implementation
   details.

## Run Details

1. When the operator asks what changed, asks for the latest review, or wants a
   Project run summarized in chat, call `get_project_coding_run_details`.
2. Omit `task_id` to retrieve the latest meaningful run: the newest reviewed
   or ready-for-review run, falling back to the newest run when no reviewable
   run exists.
3. Use the returned `links.project_run_url` for the full review page. Summarize
   `receipt`, `review`, `evidence`, `activity`, and blockers in plain language
   instead of dumping raw JSON unless the operator asks for raw details.
4. For failed, blocked, stale, or changes-requested runs, check
   `review.recovery`. If `can_continue` is true, create follow-up work through
   the Project coding-run continuation path with concrete feedback. If
   `latest_continuation_id` is present, open or summarize that follow-up before
   creating another one. Do not continue active or already reviewed runs.

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

- Project coding runs and review sessions require an applied Blueprint snapshot.
  If launch is blocked because the Project has no recipe, ask the operator to
  create a Blueprint from the current Project or create a Project from an
  existing Blueprint.
- Do not import repo-local `.agents` skills into runtime. It is OK to read
  Project-local instruction files as guidance for the current Project, but do
  not copy them into runtime skill storage or assume they apply globally.
- Do not write secrets or paste secret values into receipts.
- Do not create replacement PRs for continuation runs unless the handoff tool
  reports reuse is impossible.
- Do not rely on ambient Docker access from a harness shell. Dependency Stack
  Docker control must go through Spindrel tools and is for backing services,
  not for running unit tests.
- Do not run repository bootstrap helpers meant for an outer development
  operator from an ordinary Project coding run. Those are host setup commands,
  not Project task steps.
- Do not use or restart fixed host ports from examples. Those are not Project
  app ports.
