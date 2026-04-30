---
name: spindrel-e2e-development
description: Use when developing Spindrel features that need local fresh e2e stacks, provider/auth setup, Codex/Claude harness auth mounts, browser screenshots, or Project coding-run evidence. This is for repository development agents and harness coding agents, not a Spindrel runtime skill.
---

# Spindrel E2E Development

This is a repo-dev skill. It is not imported into Spindrel runtime skills.

## Start Here

1. Read `CLAUDE.md`.
2. Read `docs/guides/agent-e2e-development.md`.
3. If UI screenshots are involved, read `docs/guides/visual-feedback-loop.md`.
4. If harness task agents are involved, read `docs/guides/agent-harnesses.md`
   and `docs/guides/projects.md`.

## Boundary

- Local repo-dev agents may run pytest and screenshot scripts directly.
- Harness agents use native Codex/Claude tools for Project-root code work.
- Harness agents must use task-granted Spindrel tools for e2e, screenshots,
  server/machine actions, Docker/compose, and receipts.
- Normal Spindrel bots use runtime skills such as `e2e_testing` and tools such
  as `run_e2e_tests`.

Fresh Project Instances are disposable Project roots, not per-task Docker
sidecars.

## Commands

Prepare a local e2e env:

```bash
python scripts/agent_e2e_dev.py write-env
python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py commands
```

Mount native harness auth into the local e2e container:

```bash
python scripts/agent_e2e_dev.py write-auth-override
export E2E_COMPOSE_OVERRIDES="$PWD/scratch/agent-e2e/compose.auth.override.yml"
```

Prepare screenshots:

```bash
python scripts/agent_e2e_dev.py write-screenshot-env --setup-user
python -m scripts.screenshots stage --only project-workspace
python -m scripts.screenshots capture --only project-workspace
python -m scripts.screenshots check
```

## Completion Standard

Report:

- which target was used and how it was verified;
- which e2e tests ran;
- which screenshot bundle ran;
- which artifact files changed;
- whether visual inspection happened;
- any missing task grants or auth.
