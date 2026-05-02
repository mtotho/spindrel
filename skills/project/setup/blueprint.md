---
name: Project Blueprint
description: Recipe model end-to-end - declare a Blueprint, apply it to a Project, snapshot it, and how fresh Project instances clone from it.
triggers: blueprint, project blueprint, project recipe, apply blueprint, blueprint from current, fresh project instance, project snapshot
category: project
---

# Project Blueprint

Use this skill when the user asks how Project recipes work, when `init` flagged
the Project has no applied Blueprint, or when changing the Blueprint shape
(repos, branch, setup commands, env slots, dependency stack, dev targets).

Blueprints are durable Project recipes. Fresh Project instances are disposable
copies created from the Project's applied Blueprint snapshot. A Blueprint is
not per-run state - update it only when the setup recipe itself changes.

## Mental Model

- **Blueprint** - declarative recipe: repos with branches, runtime env keys,
  required secret slots, setup commands, dependency stack reference, dev target
  declarations.
- **Applied Blueprint snapshot** - the frozen copy bound to a Project. New
  fresh instances clone from this snapshot.
- **Fresh Project instance** - disposable working copy created when a formal
  run starts. Clones the declared branch at creation time so it picks up the
  latest remote state at that moment.
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
applied Blueprint summary, runtime env status, dependency stack status,
configured dev targets, attached channels. Read this before recommending edits.

### Add Docker-backed dependencies

Declare `dependency_stack` on the snapshot pointing at a Project-local compose
file. The compose file holds backing services only (Postgres, Redis, search
indexes, queues). Never put the app server in the stack - agents start
app/dev servers from source on assigned or unused ports.

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

- Repo, branch, setup commands, env slots, dependency stack, dev targets all
  changed - **update the Blueprint snapshot**.
- Code or product behavior changed - **open a coding run**, do not touch the
  Blueprint.

## Boundaries

- No secrets in Blueprint repo URLs. Use secret bindings.
- No app servers in the dependency stack.
- Do not reseat `apply_to_project=true` casually - it replaces the snapshot
  used for the next fresh instance.
