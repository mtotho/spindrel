---
name: Agent Readiness Operator
description: >
  Short runtime procedure for Spindrel bots handling capability manifests,
  Doctor findings, staged readiness repairs, and approval-gated repair
  requests. Designed for smaller models that need explicit tool ordering.
triggers: agent readiness operator, readiness repair, preflight agent repair, request agent repair, pending repair request, missing api scopes, empty tool working set, widget skills not enrolled
category: core
---

# Agent Readiness Operator

Use this when you are doing broad API, config, integration, widget, Project,
harness, or readiness work, or when you are blocked by missing tools, scopes,
skills, setup, or stale settings.

## Procedure

1. Call `list_agent_capabilities()` before broad work. Read `doctor.findings`,
   `skills.recommended_now`, `tools`, `project`, `harness`, `widgets`, and
   `integrations` before deciding what to do.
2. If you only need the blocked-state diagnosis, call `run_agent_doctor()`.
3. If `skills.recommended_now[*].first_action` is present, follow it before
   procedural work. Usually this means `get_skill("...")`.
4. For broad Project-bound code, test, e2e, screenshot, or setup work outside
   a formal Project coding run, load `workspace/project_development` before
   editing or starting processes.
5. For each proposed readiness action, call
   `preflight_agent_repair(action_id)` before applying or requesting anything.
6. If preflight is `stale`, `noop`, or `blocked`, report the status and stop
   that repair path. Do not mutate stale or blocked actions.
7. If preflight is `ready` but you lack apply authority, call
   `request_agent_repair(action_id, rationale)` so a human can review it in
   Agent Readiness or Mission Control Review.
8. After an approved or agent-important mutation through the normal API/tool
   path, publish or rely on the existing execution receipt path so later agents
   can see the result.

## Boundaries

- Do not create a bot-authored skill with `manage_bot_skill` just because a
  readiness recommendation exists.
- Do not import repo-local `.agents` skills into runtime skills. Repo-dev
  `.agents` skills can be read as Project-local instructions when a Project
  exposes them, but they are not product runtime skills and must not be copied
  into runtime skill storage.
- Do not write secrets, install dependencies, start processes, or change
  integration runtime state from this skill. Route those to the existing
  settings, integration, Project, or approval surfaces.
- Do not bypass `preflight_agent_repair` or mutate a repair request that is
  stale, blocked, or already a no-op.
