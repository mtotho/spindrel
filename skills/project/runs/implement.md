---
name: Project Implementation Runs
description: >
  How to execute a Project coding run - branch prep, focused edits, repo-local
  verification, session environment lifecycle, dev targets, and a review-ready
  receipt.
triggers: project coding run, implement, run pack, launch run, finish run, project handoff, screenshots, publish receipt
category: project
---

# Project Implementation Runs

Use this skill inside an active or about-to-launch Project coding run. For
review work load `project/runs/review`. For scheduled/recurring work load
`project/runs/scheduled`. For bounded loop policy load `project/runs/loop`.

If the user is doing **ad hoc** Project-bound code/test/screenshot work
without a formal coding run, do not load this skill. Use normal shell/file
tools in the Project root and ask the user to attach Project-local files
through composer mentions (`@file:<path>`, `@project:dependencies`).

## Work Surface

1. Confirm you are in the Project work surface. Formal coding runs use a normal
   session plus a session execution environment: usually a generated branch,
   per-session git worktree, private Docker daemon, and assigned dev target
   ports.
2. To verify, call `list_agent_capabilities` and read
   `execution_environment` plus `project.work_surface`. Formal isolated runs
   report `execution_environment.mode="isolated"` and a ready cwd/worktree. If
   the environment is missing, stopped, failed, deleted, or points at the shared
   root, **stop** and report the readiness blocker - do not edit the shared
   root.

## Procedure

1. **Read the repo contract first.** Call `get_project_factory_state` and
   inspect `repo_workflow.sections.runs` and `repo_workflow.sections.hooks`.
   When `runs` is non-null, follow that section's branch / test / PR
   conventions verbatim - it overrides the generic guidance below. When
   `hooks` is non-null, treat it as the source of truth for `before_run` /
   `after_run` shell commands and run them at the matching phase. The
   repo-owned `.spindrel/WORKFLOW.md` always wins over this skill's
   defaults.
2. **Research before editing.** Use `grep`, `Read`, `glob`, and (when
   helpful) sub-agent dispatch to understand the relevant code before
   touching it. Read the actual files referenced by the run prompt; do not
   improvise from filenames alone. For non-trivial work, write a short
   `.spindrel/runs/<run_id>/plan.md` artifact recording: scope, files you
   expect to touch, test plan, open questions. The plan is yours -
   throwaway between sessions, not a permanent doc - but writing it forces
   the research pass and gives the reviewer a hook to compare against the
   final receipt.
3. Inspect current state and call
   `prepare_project_run_handoff(action="prepare_branch")` before editing.
4. Make focused changes with native harness file/shell tools inside the Project
   work surface. Treat `SPINDREL_DEV_*_PORT` values as Project app leases (not
   the host Spindrel API/UI port).
5. For Docker-backed dependencies in an isolated run, use ordinary `docker` and
   `docker compose` commands from the Project worktree. They should target the
   session's private daemon through `DOCKER_HOST`. If Docker is stopped or
   unhealthy, load `project/runs/environment` and inspect before retrying.
   Dependency Stack tools are only for Projects that explicitly declare a
   Project-managed stack.
6. Run the smallest useful repo-local tests first with the native Project
   shell/runtime env. Do not wrap unit tests in Docker, Dockerfile.test, or
   docker compose. For UI work, run typecheck, start the Project app/dev
   server on the assigned dev target port when present, and capture
   screenshots against that server. Do not restart another agent's process or
   the host Spindrel e2e/API server.
7. Near handoff, call `prepare_project_run_handoff(action="open_pr")` when
   GitHub credentials and `gh` are available. If not, record the exact
   blocker.
8. Finish with `publish_project_run_receipt`. Make the receipt review-ready
   with structured records:
   - files: `{path, status, summary}`
   - tests: `{command, status, exit_code, summary}`
   - screenshots: `{path, url, label, viewport, notes}`
   - metadata for risks, follow-ups, dependency health, PR notes,
     implementation details.

## Phase Awareness (when surfaced)

`get_project_coding_run_details` returns a `lifecycle.run_phase` field tracking
what the run is doing right now (Symphony-equivalent activity phase). Use it
to decide your next move:

- `preparing` - work surface coming up; do not edit yet.
- `branching` - ensure `prepare_project_run_handoff(action="prepare_branch")`
  has run.
- `editing` - normal implementation flow.
- `testing` - finish the test pass before opening the PR.
- `handoff` - PR is open; record blockers if it is not.
- `review_ready` - work is ready for `project/runs/review`.
- `reviewed` / `failed` - terminal; no implementation action.
- `stalled` - background sweep flagged no activity past `stall_timeout`. Re-
  engage explicitly or hand off; do not silently restart.

`lifecycle.phase` is the broad operator-headline state (`needs_review`,
`running`, etc.) used by the UI. Prefer `run_phase` for in-loop decisions.

## Loop-Enabled Runs

If the run prompt says a bounded Project run loop is enabled, include
`loop_decision` in the receipt - see `project/runs/loop` for the decision
contract and stop conditions.

## Evidence Rules

- Test evidence names the command and result.
- Screenshot evidence includes paths or structured screenshot records.
- Handoff evidence includes the branch and PR URL when available.
- If tests or screenshot capture are unavailable, **record the blocker**
  instead of claiming verification.
- Environment evidence includes cwd/worktree, branch, Docker status/endpoint,
  and any stop/restart blockers. If a Dependency Stack is explicitly
  configured, include its health, service command results, exported env keys,
  and any reload/restart blockers. App server URLs and screenshots belong to
  the native server process you started for the run.
- Dev target evidence includes each assigned key, URL, port, and whether the
  source-run server was started, checked, blocked, or stopped.

## Boundaries

- Project coding runs require an applied Blueprint snapshot. If launch is
  blocked, route to `project/setup/blueprint`.
- Do not import repo-local `.agents` skills into runtime. Read them as Project
  guidance only.
- Do not write secrets or paste secret values into receipts.
- Do not create replacement PRs for continuation runs unless the handoff tool
  reports reuse is impossible.
- Do not touch host/shared Docker from an isolated run. Use the session
  Docker daemon surfaced through `DOCKER_HOST`.
- Do not run repository bootstrap helpers meant for an outer development
  operator from an ordinary Project coding run.
- Do not use or restart fixed host ports from examples - they are not Project
  app ports.
