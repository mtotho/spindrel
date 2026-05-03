---
name: Project Init
description: Inspect a Project and bring it to agent-ready state - applied Blueprint, runtime env, session environment readiness, channel skill enrollment, and the repo-resident `.spindrel/WORKFLOW.md` contract.
triggers: project init, initialize project, setup project, project setup audit, configure project, project readiness, blueprint from current
category: project
---

# Project Init

Use this when `current_stage` from `get_project_factory_state` is `unconfigured`,
when the user asks whether a Project is set up correctly, or when a fresh
Project needs its recipe.

If the Project is configured and the user is asking what to do next, route via
`project/index` instead.

## Goal

Turn a Project from "a folder a channel points at" into an agent-ready work
surface:

- Project has an applied Blueprint snapshot (durable recipe).
- Blueprint repo declarations match the actual repo roots, remotes, and intended
  branches; no credentials embedded in remote URLs.
- Project channels have the relevant runtime skills enrolled.
- Project has the single repo-owned contract at `.spindrel/WORKFLOW.md`
  carrying policy / artifacts / intake / runs / hooks / dependencies sections.
- Session execution environments are ready for formal runs. Dependency Stack is
  declared only when the Project intentionally wants Spindrel-managed backing
  services rather than the run's private Docker daemon.
- Runtime env keys, required secret slots, dev targets, and setup commands are
  declared only when repo evidence supports them.

## Procedure

1. Confirm the channel is Project-bound. If not, ask the user to attach it.
2. Call `list_agent_capabilities` and read the `project`, `tools`, and
   `skills.recommended_now` sections. Load `agent_readiness/operator` if
   recommended.
3. **Prime the repo before recommending anything.** Run this short scan in
   order:
   a. Read `AGENTS.md` / `CLAUDE.md` if present - this is the entry-point
      doc the repo author wrote for agents. Treat it as authoritative.
   b. Read `README.md` and any obvious setup doc (`SETUP.md`,
      `CONTRIBUTING.md`).
   c. List the repo root and identify the stack from package files
      (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`,
      etc.) and any `docker-compose*.yml` / `Dockerfile*`.
   d. Read recent git history (`git log --oneline -20` or the harness
      equivalent) - the most recent direction is almost always relevant
      context for setup decisions.
   e. Look for child git repos under the Project root; a Project root may
      hold sibling repos, not just one.
   Do not assume a stack before reading. Do not skip this step even when the
   user has already described the Project in chat.
4. Check `repo_workflow.present` from `get_project_factory_state`. When the
   file is missing, offer to write a starter via
   `write_project_workflow_starter` (asks first; never silently overwrites).
   When the file is present, treat its sections as authoritative.
5. If there is no applied Blueprint, create one from the current Project:
   `POST /api/v1/projects/{project_id}/blueprint-from-current` with
   `{"apply_to_project": true}`. For end-to-end recipe details, load
   `project/setup/blueprint`.
6. Sanitize Blueprint repo declarations: strip embedded tokens or usernames
   from remotes, set the intended base branch, use secret bindings for
   credentials.
7. Enroll only the skills the channels need. For typical software-factory work:
   `project`, `project/intake`, `project/runs/implement`,
   `project/runs/environment`, and `agent_readiness/operator` when relevant.
8. If the repo needs Docker-backed services, prefer a Project-local compose
   file that agents can run with ordinary `docker compose` inside each isolated
   session environment. App/dev servers stay native to source on assigned or
   unused ports.
9. Only when the user explicitly wants Spindrel-managed backing services,
   update the applied Blueprint snapshot with `dependency_stack`:

```json
{
  "source_path": "path/from/project/root/docker-compose.project.yml",
  "env": {
    "DATABASE_URL": "postgresql://user:pass@${postgres.host}:${postgres.5432}/db"
  },
  "commands": {
    "postgres-ready": "pg_isready -U user -d db"
  }
}
```

10. Check `/api/v1/projects/{project_id}/setup`,
    `/api/v1/projects/{project_id}/runtime-env`, and
    `/api/v1/projects/{project_id}/dependency-stack`. Report what is ready,
    what changed, and what still needs a user decision.
11. Configure the issue-intake convention exactly once per Project. **Skip
    this step entirely when `repo_workflow.sections.intake` is non-null** -
    WORKFLOW.md is the source of truth and `intake_config` is not consulted.
    Otherwise read `intake_config.kind` from `get_project_factory_state`:
    - `unset` -> ask the user where issues should live and persist the answer
      with `update_project_intake_config`. Choices:
      - **A file in this repo** -> ask for a relative path. If the user has no
        preference, suggest `docs/inbox.md`.
      - **A folder in this repo** -> ask for a relative path. Suggest
        `docs/inbox/` if no preference.
      - **GitHub / Linear / Notion / other tracker** -> ask for the canonical
        URL or identifier; record the platform under
        `metadata.tracker` (e.g. `{"tracker": "github"}`).
      - **Skip / decide later** -> leave `intake_kind = unset`. The generic
        `project/intake` skill will warn next time it is invoked.
    - Already set -> do not re-prompt. If the user explicitly says
      "reconfigure intake," walk through the same choices and overwrite via
      `update_project_intake_config`.
    Strict invariant: this step records the convention only - it never writes
    the inbox file or creates the tracker on the user's behalf. The first real
    write happens via `project/intake`.

## Boundaries

- Do not paste secret values into Project metadata, Blueprint repos, channel
  prompts, receipts, or compose files.
- Do not copy repo-local `.agents` skills into runtime skills.
- Do not put the app server in a dependency stack. Agents run app/dev servers
  from source.
- In isolated Project runs, ordinary Docker commands should target the session
  private daemon. Do not touch host/shared Docker.
