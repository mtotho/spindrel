---
name: Project Blueprint
description: Recipe model end-to-end - declare a Blueprint, apply it to a Project, snapshot it, and how formal Project runs derive isolated session worktrees from it.
triggers: blueprint, project blueprint, project recipe, apply blueprint, blueprint from current, isolated project run, project snapshot
category: project
---

# Project Blueprint

Use this skill when the user asks how Project recipes work, when `init` flagged
the Project has no applied Blueprint, or when changing the Blueprint shape
(repos, branch, setup commands, env slots, optional managed dependency stack,
dev targets).

Blueprints are durable Project recipes. Formal Project runs derive their
session worktree and runtime setup from the Project's applied Blueprint
snapshot. A Blueprint is not per-run state - update it only when the setup
recipe itself changes.

## Mental Model

- **Blueprint** - declarative recipe: repos with branches, runtime env keys,
  required secret slots, setup commands, optional managed dependency stack
  reference, dev target declarations.
- **Applied Blueprint snapshot** - the frozen copy bound to a Project. New
  formal run environments derive from this snapshot.
- **Session execution environment** - per-session work surface created when a
  formal run starts. It usually creates a git worktree on the run branch and a
  private Docker daemon for that session.
- **Shared Project root** - the long-lived checkout used for ad hoc work and
  when no isolation is requested.

## Common Operations

### Create a Blueprint from the current Project state

`POST /api/v1/projects/{project_id}/blueprint-from-current` with
`{"apply_to_project": true}`. Use this when the Project root already reflects
the desired shape and you just want to capture it.

### Update the applied snapshot

Edit the snapshot directly through the Project's Blueprint editing surface, or
re-derive from current state and re-apply. Do this only when the recipe
changes - not when chasing a bug.

### Inspect what is in the snapshot

`GET /api/v1/projects/{project_id}/setup` returns the merged readiness view:
applied Blueprint summary, runtime env status, optional dependency stack status,
configured dev targets, attached channels. Read this before recommending edits.

### Add Docker-backed dependencies

Prefer a Project-local compose file that agents run with ordinary
`docker compose` inside each isolated session environment. Declare
`dependency_stack` on the snapshot only when the Project intentionally wants
Spindrel-managed backing services. Never put the app server in a stack - agents
start app/dev servers from source on assigned or unused ports.

```json
{
  "source_path": "infra/docker-compose.project.yml",
  "env": {
    "DATABASE_URL": "postgresql://user:pass@${postgres.host}:${postgres.5432}/db"
  },
  "commands": {
    "postgres-ready": "pg_isready -U user -d db"
  }
}
```

### Add dev target declarations

Dev targets are leases the run system assigns: `SPINDREL_DEV_<KEY>_PORT`
exported to the run for use by the Project app/dev server. They are different
from the host Spindrel API/UI port. Declare only the dev targets the repo
actually needs.

## When to Edit the Blueprint vs. Open a Coding Run

- Repo, branch, setup commands, env slots, optional dependency stack, or dev
  targets changed - **update the Blueprint snapshot**.
- Code or product behavior changed - **open a coding run**, do not touch the
  Blueprint.

## Boundaries

- No secrets in Blueprint repo URLs. Use secret bindings.
- No app servers in dependency stacks or backing-service compose files.
- Do not reseat `apply_to_project=true` casually - it replaces the snapshot
  used for future formal run environments.
