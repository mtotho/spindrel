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

- **Local dev mode** means a repo-dev agent in this source checkout. It may run
  Python, pytest, screenshot scripts, and the local helper directly. For source
  iteration, use the helper to start Docker-backed dependencies and run the
  API/UI yourself from this checkout on unused ports.
- **Spindrel dev mode** means Codex/Claude running inside a Project-bound
  channel or Project coding run. It uses native shell/edit tools for
  Project-root code work only.
- Harness agents must use task-granted Spindrel tools for e2e, screenshots,
  server/machine actions, Docker/compose, and receipts.
- Project Dependency Stacks are the normal Docker path for Project coding runs:
  agents edit source/compose files in the Project root, then use
  `get_project_dependency_stack` and `manage_project_dependency_stack` to prepare,
  reload, restart, inspect logs, run service commands, check health, and read
  dependency connection env. Agents still start app/dev servers themselves.
- Project coding runs may include assigned dev targets such as
  `SPINDREL_DEV_API_PORT` / `SPINDREL_DEV_API_URL`. Use those for source-run
  servers and report their status in `publish_project_run_receipt`.
- Normal Spindrel bots use runtime skills such as `e2e_testing` and tools such
  as `run_e2e_tests`.

Fresh Project Instances are disposable Project roots. Dependency Stack instances
are run-scoped Docker stacks attached to those roots when the Project declares a
stack spec. Do not use raw Docker from a harness shell.

## Commands

Prepare a local e2e env:

```bash
python scripts/agent_e2e_dev.py write-env
python scripts/agent_e2e_dev.py prepare-deps
python scripts/agent_e2e_dev.py start-api --build-ui
python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py commands
```

If `doctor` reports `subscription bootstrap: connected`, do not ask the user to
repeat browser/device-code OAuth. Normal `prepare-deps` preserves the local e2e
DB and only starts shared dependencies. Start the Spindrel app/API/UI from this
checkout on your own unused ports while iterating. The explicit DB reset
command is `python scripts/agent_e2e_dev.py wipe-db --yes`.
If the default Docker compose project has stale/dead containers that Docker
cannot remove, use `E2E_COMPOSE_PROJECT=<unique-name>` with alternate
`E2E_POSTGRES_PORT` / `E2E_SEARXNG_PORT` values instead of deleting provider
state.

Use `python scripts/agent_e2e_dev.py prepare` only when you intentionally need
the full local Docker e2e stack with an app container. Normal harness parity
setup now uses Docker for dependencies only and runs the API natively from this
checkout.

The containerized app fallback can still mount native harness auth:

```bash
python scripts/agent_e2e_dev.py write-auth-override
export E2E_COMPOSE_OVERRIDES="$PWD/scratch/agent-e2e/compose.auth.override.yml"
```

Prepare local Codex/Claude harness parity channels:

```bash
python scripts/agent_e2e_dev.py prepare-harness-parity
./scripts/run_harness_parity_local.sh --tier core
./scripts/run_harness_parity_local.sh --tier skills -k "native_image_input_manifest"
./scripts/run_harness_parity_local_batch.sh --preset smoke
./scripts/run_harness_parity_local_batch.sh --preset fast --jobs 3
```

Use `--runtime codex` or `--runtime claude-code` on `prepare-harness-parity`
for one-runtime setup. The command preserves the local e2e database, starts
Postgres/SearXNG in Docker, starts or reuses a native `uvicorn` API process
from this checkout on an unused port, reuses host `~/.codex` / `~/.claude`
runtime auth, creates stable local harness bots/channels, and writes
`scratch/agent-e2e/native-api.env` plus
`scratch/agent-e2e/harness-parity.env`.
The channels are Project-bound through `project_id` to the real `Harness Parity
Project` at `common/projects/harness-parity`; do not treat the old path field
as the source of truth. Native mode builds `ui/dist` so the API can serve the
UI same-origin for Playwright screenshots.
For Claude Code, it also runs a tiny live auth smoke because `claude auth
status` can report logged-in even when the first SDK turn will 401. If it
fails, refresh the mounted auth with:

```bash
claude auth login
```

Use `prepare-harness-parity --docker-app` only for the containerized app
fallback.

Use `run_harness_parity_local_batch.sh` for fast iteration: `smoke` is the
cheap confidence pass, `fast` covers core/plan/skills/replay, and `deep` is for
broader pre-deploy scrutiny. Logs are written under
`scratch/agent-e2e/harness-parity-runs/`.

Prepare screenshots:

```bash
python scripts/agent_e2e_dev.py write-screenshot-env --setup-user
python -m scripts.screenshots stage --only project-workspace
python -m scripts.screenshots capture --only project-workspace
python -m scripts.screenshots check
```

## Screenshot Evidence Contract

Every e2e proof that touches UI, Project runs, harness sessions, browser output,
or user-reviewable workflow state needs screenshot evidence. Treat screenshots
as both:

- **Feedback for you**: inspect the images before closing the task. Confirm the
  expected route, server, Project/channel/session, data, and visual state are
  actually rendered. If the image shows a spinner, stale route, wrong channel,
  empty fixture, clipped content, overlap, or confusing layout, the e2e proof is
  not done even if pytest passed.
- **Proof for the user**: durable evidence images belong in source-controlled
  `docs/images/` and must be referenced from the relevant guide or track doc.
  Temporary scratch images are fine during iteration, but they are not enough
  for final proof.

Required closeout flow for UI/e2e evidence:

1. Run the relevant e2e or live scenario against the intended server.
2. Capture the product UI surfaces that prove the workflow happened, not only a
   terminal log or generated output. For Project work this usually means the
   Project page/Runs page/channel/session transcript plus any generated app or
   browser result.
3. Open or inspect every new/changed screenshot. Use the images to decide
   whether rendering, layout, data binding, and workflow state are correct.
4. Copy durable proof images to `docs/images/` with stable names.
5. Reference those images from the relevant doc, usually
   `docs/guides/agent-e2e-development.md` or
   `docs/guides/visual-feedback-loop.md`.
6. Run `python -m scripts.screenshots check` and leave it passing.
7. In the final answer, list the e2e command, screenshot files, what visual
   inspection confirmed, and any remaining gaps.

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

Live Project Factory PR smoke (opt-in, opens a real draft PR):

```bash
python scripts/agent_e2e_dev.py prepare-project-factory-smoke \
  --runtime codex \
  --github-repo mtotho/vault \
  --base-branch master \
  --seed-github-token-from-gh

PROJECT_FACTORY_LIVE_PR=1 \
E2E_MODE=external \
E2E_HOST=localhost \
E2E_PORT=18000 \
E2E_KEEP_RUNNING=1 \
pytest tests/e2e/scenarios/test_project_factory_live_pr_smoke.py -v -s
```

Use `E2E_MODE=external` here. The helper already built and prepared the local
`:18000` stack; letting pytest start compose again can fail on stale or missing
provider env. The test writes
`scratch/agent-e2e/project-factory-live-pr-smoke.json` for screenshot capture
and review notes.

## Lessons Learned

- Run `doctor` first. If subscription bootstrap is already connected, do not
  restart browser/device-code OAuth.
- Rebuild current source before judging e2e behavior. If Docker context fails
  on generated dependency folders, exclude those folders instead of wiping the
  local e2e database.
- Normal local `prepare` preserves provider/OAuth state. Only
  `wipe-db --yes` should erase the durable local e2e Postgres volume.
- Prefer `prepare-deps` for normal source-tree development. It starts shared
  Docker dependencies and prints connection env; each agent owns its own
  source-run server process and port.
- `.env.agent-e2e` must keep the generated `ENCRYPTION_KEY` and `JWT_SECRET`
  alongside the durable local Postgres volume. If encrypted provider/OAuth rows
  were written under a lost key, the local app cannot boot until that local DB
  is wiped or the original key is restored.
- Never delete/regenerate `.env.agent-e2e` secrets as a convenience. If
  `doctor` reports subscription/provider state is connected, protect that file
  and use normal `prepare` / `prepare-harness-parity`; only `wipe-db --yes`
  should intentionally reset provider/OAuth state.
- Screenshot staging should use deterministic fixtures for documentation
  transcripts. Do not depend on a live model turn to render a docs artifact.
- Harness parity can now run locally against `localhost:18000` through
  `run_harness_parity_local.sh`; use `--screenshots feedback` for throwaway
  visual review and `--screenshots docs` only when intentionally refreshing
  checked-in `docs/images/harness-*` fixtures.
- `prepare-harness-parity` installs Codex/Claude integration deps, restarts the
  native local API so the harness modules reload, then creates stable
  parity bots/channels with baseline bridge tools and writes
  `scratch/agent-e2e/harness-parity.env`.
- Local parity can be parallelized with focused selectors, not full tier
  sweeps. Prefer `run_harness_parity_local_batch.sh --preset smoke|fast --jobs
  2` during development; raise jobs only for targeted, independent slices.
- Durable screenshot fixtures can outlive a regenerated encryption key. Staging
  should repair screenshot secret values through the API instead of clearing
  the stack.
- Local live PR smoke needs three independent credentials: Spindrel provider
  auth for normal model calls, host Codex auth mounted into the local e2e
  container, and a Project-bound GitHub token secret for clone/push/`gh pr`.
  The helper checks all three without printing secret values.
- GitHub handoff receipts may return `changed_files` as strings and may omit
  `handoff_type` when the agent only supplies a URL. Assert the durable URL and
  changed path; treat type as optional unless the product contract changes.
- Project Dependency Stacks separate spec from instance. The Project/Blueprint
  owns the compose source; coding runs get task-scoped dependency instances so
  parallel runs do not restart the same database/services. App/dev servers are
  native per-agent processes outside the dependency stack.
- Native local parity sets `CONFIG_STATE_FILE=` by default so source-mode API
  startup does not replay exported config into a fresh e2e DB. Opt into config
  restore explicitly only when that is the thing under test.
- Native local parity uses the repo-seeded `default` bot for e2e health checks;
  the compose-only `e2e` bot is not available unless a containerized app run
  mounts `tests/e2e/bot.e2e.yaml`.
- If the default compose project gets stuck in Docker removal state, verify
  with a unique `E2E_COMPOSE_PROJECT` and alternate Postgres/SearXNG ports.
  Do not delete the durable default DB/auth state to unblock a proof run.
- Native Project parity dogfood requires both product UI evidence and the
  generated app screenshot. Capture and link the Project detail, Project
  channels binding, Codex session transcript, and generated app artifacts
  instead of stopping at the static app image.

## Completion Standard

Report:

- which target was used and how it was verified;
- which e2e tests ran;
- which screenshot bundle ran;
- which screenshot/artifact files were added or changed under `docs/images`;
- which docs now reference those screenshots;
- what visual inspection confirmed from the screenshots;
- any missing task grants or auth.
