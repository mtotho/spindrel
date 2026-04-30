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
python scripts/agent_e2e_dev.py prepare
python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py commands
```

If `doctor` reports `subscription bootstrap: connected`, do not ask the user to
repeat browser/device-code OAuth. Normal `prepare` preserves the local e2e DB
and recreates only the Spindrel app container. The explicit DB reset command is
`python scripts/agent_e2e_dev.py wipe-db --yes`.

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

Project Factory contract check:

```bash
python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py prepare
set -a && source .env.agent-e2e && set +a
E2E_KEEP_RUNNING=1 pytest tests/e2e/scenarios/test_project_factory_flow.py -v
```

Run this before a live agent/PR smoke when the work changes issue intake,
work-pack triage, Project coding-run launch, receipts, review sessions, or
review finalization. It proves the durable spine: rough issue notes -> work
packs -> Project coding run -> PR-like receipt -> review context -> accepted
finalization -> reviewed provenance.

## Lessons Learned

- Run `doctor` first. If subscription bootstrap is already connected, do not
  restart browser/device-code OAuth.
- Rebuild current source before judging e2e behavior. If Docker context fails
  on generated dependency folders, exclude those folders instead of wiping the
  local e2e database.
- Normal local `prepare` preserves provider/OAuth state. Only
  `wipe-db --yes` should erase the durable local e2e Postgres volume.
- Screenshot staging should use deterministic fixtures for documentation
  transcripts. Do not depend on a live model turn to render a docs artifact.
- Durable screenshot fixtures can outlive a regenerated encryption key. Staging
  should repair screenshot secret values through the API instead of clearing
  the stack.

## Completion Standard

Report:

- which target was used and how it was verified;
- which e2e tests ran;
- which screenshot bundle ran;
- which artifact files changed;
- whether visual inspection happened;
- any missing task grants or auth.
