---
name: Project Development
description: >
  Runtime procedure for ad hoc Project-bound code, test, e2e, screenshot,
  setup, and feedback-loop work before or outside a formal Project coding run.
triggers: project development, project code changes, run project tests, project e2e, project screenshots, project dev server, project dependency setup
category: workspace
---

# Project Development

Use this skill when a Project-bound channel session is doing ordinary
development work in a Project root: editing code, running tests, starting a
dev server, checking screenshots, or preparing enough evidence to decide
whether a formal Project coding run is needed.

If the user asks to start, continue, review, merge, or finalize a Project
coding run, load `workspace/project_coding_runs` instead. If the user is still
shaping rough notes, bugs, ideas, or a multi-part track, load
`workspace/issue_intake` first.

## Procedure

1. Call `list_agent_capabilities()` before broad work. Check `project`,
   `tools`, `skills.recommended_now`, `doctor.findings`, and any assigned
   work state.
2. Confirm the current Project work surface. Use the Project root for file,
   search, shell, test, screenshot, and handoff work. If the session only has
   a plain working-directory hint and no Project binding, say that Project
   features may be unavailable and ask the user to bind or create a Project
   before relying on Project-specific tools.
3. Read Project-local instructions when they exist, such as repository agent
   guidance, local skill files, README/development docs, or test runbooks.
   Treat those files as instructions for the current Project only; do not copy
   them into runtime skills or assume they apply to other Projects.
4. Make focused edits with the available file/shell tools inside the Project
   root. Use the Project's own package manager, test scripts, app commands,
   and screenshot tools unless Project-local instructions say otherwise.
5. For app or browser checks, start your own native dev/server process on an
   assigned dev target port when one is present. If no dev target is assigned,
   choose an unused port. Do not restart another agent's process.
6. For Docker-backed databases, caches, search services, or similar
   dependencies, use the Project Dependency Stack tools when the Project
   declares a stack. Call `get_project_dependency_stack` first, then use
   `manage_project_dependency_stack` for prepare, reload, restart, logs,
   service commands, and health checks. Do not assume raw Docker access exists.
7. If dependency-stack access, execution grants, dev target ports, or required
   secrets are missing, report the exact blocker and ask the user to configure
   Project settings or launch a Project coding run with the needed access.
8. When verification matters, capture evidence. Name test commands and
   results, include screenshot paths or records, and mention the dev server URL
   you actually checked. Do not claim tests or screenshots without artifacts.

## Boundaries

- This runtime skill is generic. It must work for any Project and any
  repository.
- Project-local instruction files may be repository-specific, but they stay
  Project-local guidance. They are not runtime skill source material.
- Do not write secrets into logs, receipts, screenshots, or chat.
- Do not use fixed host ports from examples. Use assigned ports or discover an
  unused one.
- Do not use a Project Dependency Stack to run unit tests. Run tests with the
  Project's native shell/runtime unless the Project's own test contract says
  otherwise.
