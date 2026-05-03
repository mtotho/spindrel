---
name: Project Run Environment
description: Inspect and manage the session execution environment for Project runs - worktree, private Docker daemon, TTL/pinning, doctor checks, and cleanup.
triggers: project run environment, session environment, isolated run, private docker, docker daemon, stop docker, restart docker, pin environment, cleanup environment
category: project
---

# Project Run Environment

Use this when a Project run or review needs to inspect, troubleshoot, preserve,
stop, restart, or clean up its execution environment.

A Project run is still a normal session. The execution environment is an
attachment to that session: usually a per-session git worktree plus a private
Docker daemon exposed through `DOCKER_HOST`.

## Tools

- `get_session_execution_environment(session_id?, doctor=true)` inspects the
  current or named session environment.
- `manage_session_execution_environment(action, session_id?)` manages it.
  Actions: `status`, `doctor`, `ensure_isolated`, `start`, `stop`, `restart`,
  `pin`, `unpin`, `cleanup`.

Use the current session by default. Pass `session_id` only when the user named a
different run/session or when operating from a triage/operator channel.

## Procedure

1. Inspect first with `get_session_execution_environment(doctor=true)`.
2. If Docker is stopped or missing and the worktree exists, use `start` or
   `restart`.
3. If the user wants to preserve the environment for later inspection, use
   `pin`. Pinning prevents TTL cleanup; it does not block explicit cleanup.
4. If the user wants to free resources, use `stop` when they may inspect files
   later, or `cleanup` when they want the worktree and Docker state removed.
5. Inspect again after any lifecycle action. Report cwd/worktree, branch,
   Docker status, endpoint, TTL/pin state, and any remaining findings.

## Boundaries

- Do not touch host/shared Docker directly for an isolated run. Ordinary
  `docker` and `docker compose` commands should use the session's `DOCKER_HOST`.
- `stop` preserves the worktree and Docker volume. `cleanup` is destructive.
- Dependency Stack tools are only for Projects that explicitly declare a
  Project-managed stack. Otherwise use the session Docker daemon.
- If a run needs missing Project setup, secrets, or dev-target access, report the
  blocker instead of bootstrapping the host Spindrel app from inside the run.
