# Spindrel Project Runbook

This file is the repo-owned runbook for agents working on Spindrel through a
Spindrel Project. It is intentionally source-controlled so Project-bound
sessions and formal Project runs get the same local policy as CLI agents.

## Start Here

1. Read `AGENTS.md` or `CLAUDE.md` first. `CLAUDE.md` is a symlink to the
   same rules.
2. Read `docs/roadmap.md` and the relevant `docs/tracks/<slug>.md` before
   continuing multi-phase work.
3. Use the repo-local `.agents/skills` only as Project-local development
   guidance:
   - `.agents/skills/spindrel-ui-operator/SKILL.md` for UI changes.
   - `.agents/skills/spindrel-e2e-development/SKILL.md` for local e2e,
     screenshots, harness parity, or Project run evidence.
   - `.agents/skills/agentic-readiness/SKILL.md` when deciding whether a
     workflow belongs in skills, tools/APIs, docs, memory, or UI.

Runtime skills under `skills/` are product behavior for all Spindrel users and
all Projects. Do not copy Spindrel repo-specific helper commands, screenshot
bundle names, or local paths into runtime skills.

## Work Policy

- Base branch is `development` unless the task says otherwise.
- Inspect `git status --short` before editing. Never revert, stash, reset, or
  clean another session's changes.
- Prefer focused, task-scoped edits. If a guide, track, or test is the contract
  for the behavior, update it in the same pass.
- For Project coding runs, use fresh Project instances or task-scoped work
  surfaces when available. Publish a receipt with changed files, tests,
  screenshots, dev targets, and handoff links.
- Spindrel Issue Intake, Work Packs, Runs, and Receipts are coordination and
  evidence surfaces. Durable product tracking still belongs in GitHub, Linear,
  or the external tracker when linked.

## Local E2E Loop

For repo-dev agents running from this checkout, use one native Spindrel API/UI
port per agent. Docker is for shared dependencies only unless explicitly
running the Docker-app fallback.

```bash
python scripts/agent_e2e_dev.py write-env --port auto
set -a && source .env.agent-e2e && set +a
python scripts/agent_e2e_dev.py prepare-deps
python scripts/agent_e2e_dev.py start-api --build-ui
python scripts/agent_e2e_dev.py doctor
```

Use `SPINDREL_E2E_URL` from `.env.agent-e2e` for Playwright, API checks, and
screenshot capture. Do not rely on a fixed port like `8000` or `18000`.

If screenshots are required:

```bash
python scripts/agent_e2e_dev.py write-screenshot-env --api-url "$SPINDREL_E2E_URL" --ui-url "$SPINDREL_E2E_URL" --setup-user
python -m scripts.screenshots stage --only project-workspace
python -m scripts.screenshots capture --only project-workspace
python -m scripts.screenshots check
```

Inspect the resulting images in `docs/images/` before claiming a visual pass is
good. If the UI changed, screenshots are evidence, not decoration.

## Testing Defaults

- Backend logic: run focused `pytest` against the changed area.
- UI changes: run `cd ui && npx tsc --noEmit --pretty false`.
- API response model changes: run `bash scripts/generate-api-types.sh` and
  include generated UI API type updates.
- Visual/layout changes: typecheck plus the relevant screenshot bundle.
- Do not wrap normal unit tests in Docker.

If `start-api` reuses a stale process after backend code changed, restart only
the agent-owned process recorded under `scratch/agent-e2e-${E2E_PORT}/`. Do not
restart another agent's server.

## Project Runs Inside Spindrel

When running inside a Spindrel Project-bound session or formal Project coding
run:

- Use normal shell/edit/test workflows from the Project root.
- Use the assigned dev target port/env if one is injected.
- Use Project Dependency Stack tools for Postgres, Redis, or other Docker-backed
  services. Do not use raw Docker from a harness shell unless the run explicitly
  grants and documents that access.
- If dependency stacks, secrets, screenshots, or dev target ports are missing,
  ask the user to configure the Project/run rather than inventing a workaround.
- Keep receipts concrete: problem statement, changed files, tests, screenshots,
  running dev targets, blockers, and external PR/tracker links.

## Completion

End every implementation pass with:

- what changed;
- tests and screenshots run;
- whether any live Project run, PR, or receipt still needs review;
- any blocker that requires user or environment action.
