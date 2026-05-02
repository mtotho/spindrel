---
name: Project Init
description: Inspect and initialize a Project so channels, Blueprint, dependency stack, skills, and run readiness match the repository's actual needs.
triggers: project init, initialize project, setup project, project setup audit, configure project, project readiness, blueprint from current
category: workspace
---

# Project Init

Use this when a user asks whether a Project is set up correctly, wants a new
Project made ready for agent work, or asks a Project-bound channel to inspect
the repo and configure the Project.

## Goal

Turn the current Project from "a folder a channel points at" into an agent-ready
work surface:

- Project has an applied Blueprint snapshot.
- Blueprint repo declarations match the repo roots, remotes, and intended
  branches.
- Blueprint does not store credential-bearing remote URLs.
- Project channels have the relevant runtime skills enrolled.
- Dependency Stack is declared only when the repo needs Docker-backed backing
  services such as Postgres, Redis, SearXNG, or queues.
- Dependency Stack points at a Project-local compose file that is reviewable in
  source.
- Runtime env, required secret slots, dev targets, and setup commands are
  declared when the repo actually needs them.

## Procedure

1. Confirm the current channel is Project-bound. If not, tell the user to attach
   the channel to a Project first.
2. Call `list_agent_capabilities()` and read the `project`, `tools`, and
   `skills.recommended_now` sections. If recommended, load
   `agent_readiness/operator`.
3. Inspect the Project root like a normal checkout. Look for `AGENTS.md`,
   README/setup docs, package files, compose files, test scripts, env examples,
   and child git repos. Do not assume a stack before reading the repo.
4. If there is no applied Blueprint, create one from the current Project.
   Prefer the Project API route equivalent to:
   `POST /api/v1/projects/{project_id}/blueprint-from-current` with
   `{"apply_to_project": true}`.
5. Sanitize Blueprint repo declarations. Remove embedded tokens or usernames
   from Git remotes and set the intended base branch. Use secret bindings for
   credentials instead of URLs containing credentials.
6. Enroll only the skills the Project channels need. For software-factory work
   this usually means `workspace/issue_intake`,
   `workspace/project_coding_runs`, `workspace/docker_stacks`, and
   `agent_readiness/operator`.
7. If the repo needs Docker-backed services, add or identify a Project-local
   compose file for backing services only. App/dev servers should still be
   started by the agent from source on assigned or unused ports.
8. Update the applied Blueprint snapshot with `dependency_stack`:

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

9. Check `/api/v1/projects/{project_id}/setup`,
   `/api/v1/projects/{project_id}/runtime-env`, and
   `/api/v1/projects/{project_id}/dependency-stack`. Report what is ready,
   what changed, and what still needs a user decision.
10. If UI behavior changed or the Project setup surface is part of the work,
    capture screenshot evidence and attach/link it in the normal Project run or
    documentation evidence path.

## Boundaries

- Do not paste secret values into Project metadata, Blueprint repos, channel
  prompts, receipts, or compose files.
- Do not copy repo-local `.agents` skills into runtime skills. Repo-local files
  can guide this Project only.
- Do not create a Docker stack for the app server. Dependency Stacks are for
  backing services; agents run app/dev servers from source.
- Do not use raw Docker from harness shells when Project Dependency Stack tools
  are available.
