---
name: agentic-readiness
description: >
  Use this repo-dev skill when auditing, designing, or improving Spindrel for
  agent usability across both external development agents working in this
  repository and internal Spindrel runtime agents using app APIs, tools,
  integrations, widgets, docs, and runtime skills. Trigger for agent-first AX,
  agentic readiness, MCP-ready surfaces, llms.txt, capability manifests, tool
  schemas, context budget, integrations, runtime skill design, or deciding
  whether a feature should be a skill, tool/API, docs, or memory.
---

# Agentic Readiness

This is a repo-dev skill for agents editing Spindrel source. It is not a Spindrel runtime skill and must not be imported into app skill tables. Channel
bots do not see `.agents/skills` unless a future explicit runtime bridge
supplies that content through an app-owned contract.

Use it to keep two contexts separate while improving both:

1. External repo-dev AX: other agents reading this repository, installing it,
   changing it, or integrating with it.
2. Internal runtime AX: agents inside Spindrel channels using runtime skills,
   tools, APIs, integrations, widgets, projects, and readiness surfaces.
3. In-Spindrel repo-dev AX: a runtime agent inside Spindrel is working on this
   repository as the current Project. It must follow generic runtime skills
   first, then may read this repo's `.agents/skills` as Project-local guidance.

## First Actions

1. State the active context before proposing changes:
   `external repo-dev AX`, `internal runtime AX`, or `both`.
2. Audit the current code/docs/runtime surface before prescribing work.
3. Classify each feature idea as `skill`, `tool/API`, `memory`, or `docs`
   before selecting files to edit.
4. Apply the small-model test: can a non-frontier model succeed from a short,
   explicit procedure plus existing tools?
5. Keep recommendations specific: name the runtime skill, API/tool contract,
   doc, or repo-local `.agents` skill that should own the behavior.

## Placement Defaults

Default ambiguous procedural work to a skill candidate. Prefer a tool/API only
when the agent needs fresh runtime state, side effects, permission enforcement,
atomicity, or data too large/stale for text.

Example: live health triage is split. The fresh runtime/error snapshot belongs
in `GET /api/v1/system-health/preflight` and `get_system_health_preflight`.
The decision procedure for promoting or resolving findings belongs in the
runtime skill `diagnostics/health_triage` and the repo-dev skill
`spindrel-live-health-triage`.

Use the full rubric in
[`references/feature-placement-rubric.md`](references/feature-placement-rubric.md)
whenever the user asks what should become a skill, when a review warning should
be categorized, or when an implementation plan crosses skill/tool/API/docs
boundaries.

## Reference Map

- Read
  [`references/feature-placement-rubric.md`](references/feature-placement-rubric.md)
  for skill-vs-tool/API-vs-docs decisions and review-warning categorization.
- Read
  [`references/external-agent-readiness.md`](references/external-agent-readiness.md)
  for repo-facing agent discoverability, installation, public API, CLI, and
  `llms.txt` work.
- Read
  [`references/internal-agent-readiness.md`](references/internal-agent-readiness.md)
  for Spindrel runtime agents, runtime skills, capability manifests, Agent
  Readiness panels, integrations, widgets, Mission Control, and execution
  receipts.
- Read
  [`references/small-model-guidance.md`](references/small-model-guidance.md)
  when a workflow must be reliable for cheaper or smaller models.

## Spindrel Boundary Rules

- Repo-local `.agents/skills` are for development agents working on this Git
  repository. They may also be read as Project-local instructions by a
  Spindrel runtime agent whose current Project is this repository.
- Runtime skills live under `skills/` and are product behavior for Spindrel
  bots and users.
- Runtime agents use runtime tools such as `list_agent_capabilities`,
  `run_agent_doctor`, `get_skill`, and integration/widget/project tools. They
  do not read repo-local `.agents` content by default; when a Project exposes
  repo-local guidance, it remains guidance for that Project only.
- Runtime skills must stay generic for any user and any Project. They must not
  mention this repository's helper scripts, local env files, screenshot bundle
  names, or Spindrel-specific development paths.
- Do not solve runtime agent discoverability by copying repo-dev skill text into
  runtime skills. First audit existing runtime skills, then create or update
  the smallest runtime skill only when the workflow is truly product-facing.

## Audit Output Shape

When reporting findings or a next slice, group by owner:

- `Repo-dev skill/docs`: `.agents`, `CLAUDE.md`, public guides, `llms.txt`,
  tests that protect contributor/agent workflow.
- `Runtime skill`: product-facing `skills/` content the in-app bot should load
  with `get_skill`.
- `Runtime tool/API`: app-owned state, mutation, schema, permission,
  integration, widget, Project, or Mission Control contracts.
- `UX/review surface`: Agent Readiness, Mission Control Review, composer/menu,
  or settings affordances that help humans approve outcomes instead of editing
  config manually.

End with verification commands and any boundary that should be pinned by a
test.
