---
name: spindrel-e2e-development
description: Use when developing Spindrel features that need local fresh e2e stacks, provider/auth setup, Codex/Claude harness auth mounts, browser screenshots, or Project coding-run evidence. This is for repository development agents and harness coding agents, not a Spindrel runtime skill.
---

# Spindrel E2E Development

This is a repo-dev skill. It is not imported into Spindrel runtime skills.
If you are reading this from inside Spindrel while working on this repository
as a Project, treat it as Project-local guidance only. For ad hoc development,
use the Project root normally and ask the user to attach relevant files with
composer file mentions when needed. For formal Project coding/review runs, use
the runtime skill `project/runs/implement` (review work uses `project/runs/review`).

## Start Here

1. Read `CLAUDE.md`.
2. Read `docs/guides/agent-e2e-development.md`.
3. If UI screenshots are involved, read `docs/guides/visual-feedback-loop.md`.
4. If harness task agents are involved, read `docs/guides/agent-harnesses.md`
   and `docs/guides/projects.md`.

## Boundary

- **Local dev mode** means a repo-dev agent in this source checkout. It may run
  Python, pytest, screenshot scripts, and the local helper directly from the
  repo venv. Unit/backend tests run natively; do not wrap them in Docker,
  Dockerfile.test, or docker compose. For source iteration, use the helper to
  start Docker-backed dependencies only when services are needed, then run the
  API/UI yourself from this checkout on unused ports.
- **Spindrel dev mode** means Codex/Claude running inside a Project-bound
  channel or Project coding run. It uses native shell/edit tools for
  Project-root code work only, and it should treat this file as selected
  Project-local guidance rather than global runtime behavior.
- Harness agents must use task-granted Spindrel tools for screenshots,
  server/machine actions, and receipts. For Docker/compose work inside an
  isolated Project run, use ordinary Docker commands; Spindrel routes them to
  the session's private Docker daemon.
- In Spindrel dev mode, if Docker-backed dependencies, dev-target ports,
  screenshot access, secrets, or execution grants are missing, ask the user to
  configure the Project settings or launch a run with the needed access. Do not
  assume the local repo-dev helper commands are available.
- Isolated Project coding runs are the normal Docker path for scheduled/loop
  work: agents edit source/compose files in the Project root and use ordinary
  `docker` / `docker compose` commands against the session daemon. Agents still
  start app/dev servers themselves.
- Project coding runs may include assigned dev targets such as
  `SPINDREL_DEV_API_PORT` / `SPINDREL_DEV_API_URL`. Use those for source-run
  servers and report their status in `publish_project_run_receipt`.
- Project Factory agents run repo-local tests and feedback-loop scripts with
  native shell inside the Project work surface. Spindrel supplies dependency
  stacks, runtime env, dev targets, screenshots, and receipts; it does not
  replace the Project's own test commands with a Spindrel-specific test tool or
  a Docker-wrapped unit-test runner.
- When a harness agent is executing an ordinary Project coding run, do not run
  repo-dev bootstrap helpers such as `scripts/agent_e2e_dev.py prepare`,
  `start-api`, or `prepare-harness-parity`. Those commands are for the outer
  repo-dev operator setting up the host test server. Inside the Project run,
  use injected env, the session Docker daemon, and your own source-run dev
  process on the assigned port.

## Port Ownership

Each repo-dev agent owns its native Spindrel API/UI process and port. Do not use
a shared fixed API/UI port in instructions or tests. Start with
`python scripts/agent_e2e_dev.py write-env --port auto`, source
`.env.agent-e2e`, then keep using the `SPINDREL_E2E_URL` and `E2E_PORT` values
from that env for helper commands, pytest, Playwright, and screenshots. Never
restart another agent's native API/UI process.
Use `set -a && source .env.agent-e2e && set +a`, not a plain `source`, whenever
child Python/Node commands need those values.

The default local dependency Compose project is `spindrel-local-e2e-runtime-deps`.
It is the shared Postgres/SearXNG stack for native repo-dev agents and it
reuses the durable `spindrel-local-e2e_postgres-data` volume. The separate
`spindrel-local-e2e` project is only for explicit Docker app-container fallback.
If dependency setup gets wedged, fix or diagnose `prepare-deps`, Docker status,
and the helper's stale-container repair path. Do not switch agents to private
Compose projects, and do not wipe the durable DB/auth state unless the user
explicitly asked for a reset.

Keep these ports distinct:

- **Agent-owned Spindrel API/UI port**: `E2E_PORT` serves that agent's native
  Spindrel product under test.
- **Dependency ports**: `E2E_POSTGRES_PORT` and `E2E_SEARXNG_PORT` expose the
  local e2e backing services.
- **Project app ports**: `SPINDREL_DEV_*_PORT` values are assigned to Project
  coding runs for the app/server being developed. A Project agent must use its
  assigned dev target port and must not restart the host Spindrel API/UI port.

Fresh Project coding runs use a normal session plus an optional isolated
session environment: a per-session git worktree and a private Docker daemon
exposed through `DOCKER_HOST`. Dependency Stack instances are only for Projects
that explicitly declare a stack spec. Do not use dependency stacks to run unit
tests.

## Commands

Prepare a local e2e env:

```bash
python scripts/agent_e2e_dev.py write-env --port auto
set -a && source .env.agent-e2e && set +a
python scripts/agent_e2e_dev.py prepare-deps
python scripts/agent_e2e_dev.py start-api --build-ui
python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py commands
set -a && source "scratch/agent-e2e-${E2E_PORT}/native-api.env" && set +a
```

If `doctor` reports `subscription bootstrap: connected`, do not ask the user to
repeat browser/device-code OAuth. Normal `prepare-deps` preserves the local e2e
DB and only starts shared dependencies. Start the Spindrel app/API/UI from this
checkout on your own unused ports while iterating. The explicit DB reset
command is `python scripts/agent_e2e_dev.py wipe-db --yes`.
For ChatGPT subscription e2e, use the cheapest capable model by default:
`gpt-5.4-mini`. Do not override bootstrap commands, temp bots, or live e2e
defaults to a larger model just because a user trace, screenshot, or production
bot used one. Larger models need an explicit model-specific regression reason.
If the dependency Compose project has stale/dead containers that Docker cannot
remove, treat that as a helper/stack bug to repair. Capture the failing command
and Docker state, then fix the default dependency-stack behavior instead of
switching to a private Compose project.
The helper intentionally fails fast when Docker reports Dead dependency
containers because Docker can hang while trying to recreate them.

Use `python scripts/agent_e2e_dev.py prepare` only when you intentionally need
the full local Docker e2e stack with an app container. Normal harness parity
setup now uses Docker for dependencies only and runs the API natively from this
checkout.

Explicit containerized infrastructure mode can still mount native harness auth:

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
./scripts/run_harness_parity_local_batch.sh --preset sdk --screenshots docs
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

Use `prepare-harness-parity --docker-app` only for explicit containerized
infrastructure work.

Use `run_harness_parity_local_batch.sh` for fast iteration: `smoke` is the
cheap confidence pass, `sdk` targets documented SDK parity gaps with durable
screenshots, `fast` covers core/plan/skills/replay, and `deep` is for broader
pre-deploy scrutiny. Logs are written under
`scratch/agent-e2e/harness-parity-runs/`.

Prepare screenshots:

```bash
python scripts/agent_e2e_dev.py write-screenshot-env \
  --api-url "$SPINDREL_E2E_URL" \
  --ui-url "$SPINDREL_E2E_URL" \
  --setup-user
python -m scripts.screenshots stage --only project-workspace
python -m scripts.screenshots capture --only project-workspace
python -m scripts.screenshots check
```

The screenshot pipeline reads `SPINDREL_URL` / `SPINDREL_UI_URL` through
`scripts/screenshots/.env`. Always run `write-screenshot-env` with the current
agent-owned `SPINDREL_E2E_URL` after starting or restarting your native API/UI;
otherwise screenshots may silently target an older local server.

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

Do not defer screenshots because patched code is not deployed to a shared live
server. In local dev mode, start the patched Spindrel API/UI from this checkout
on the agent-owned port from `.env.agent-e2e`, capture screenshots against that
server, inspect them, and then stage durable proof images when the workflow
requires user-visible evidence. A shared deployed server is optional for
post-deploy verification; it is not a prerequisite for visual feedback on local
source changes.

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

Generic Project Factory live-loop proof uses the same rule. After
`PROJECT_FACTORY_GENERIC_LOOP=1` passes, capture the agent-owned local
Spindrel Project Runs/Receipts surface and the generated app/dev server output.
The current durable proof images are:

```text
docs/images/project-factory-generic-live-loop-runs.png
docs/images/project-factory-generic-live-loop-receipt.png
docs/images/project-factory-generic-live-loop-app.png
```

If a Project Dependency Stack prepare/start hangs, diagnose locks and stack
lifecycle ordering before changing local ports or compose projects. The known
bad pattern is holding the caller's ORM transaction open after linking
`runtime.docker_stack_id` / `DockerStack.source`, then calling a stack service
that uses another DB session. Commit the link/source metadata first so the
stack lifecycle service cannot block on the caller's uncommitted row.

Project Factory contract check:

```bash
set -a && source .env.agent-e2e && set +a
python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py prepare-deps
python scripts/agent_e2e_dev.py start-api --build-ui
set -a && source "scratch/agent-e2e-${E2E_PORT}/native-api.env" && set +a
E2E_KEEP_RUNNING=1 pytest tests/e2e/scenarios/test_project_factory_flow.py -v
```

Run this before a live agent/PR smoke when the work changes issue intake,
work-pack triage, Project coding-run launch, receipts, review sessions, or
review finalization. It proves the durable spine: rough issue notes -> work
packs -> Project coding run -> PR-like receipt -> review context -> accepted
finalization -> reviewed provenance.

Generic Project Factory feedback loop:

1. Prepare the Project work surface and branch.
2. Expect configured Project coding runs to preflight their task-scoped
   Dependency Stack before the first turn. If preflight failed, inspect/fix the
   Project compose file and use `manage_project_dependency_stack(action="reload")`.
3. Use Project Dependency Stack tools for Docker-backed databases/services.
4. Use injected runtime/dependency env in native shell commands.
5. Start the app/dev server yourself on the assigned dev target port when
   present.
6. Run the Project's own tests/scripts, such as `pytest`, `npm test`,
   Playwright, Cypress, or a repo smoke script.
7. Capture screenshots against the server you started.
8. Publish a Project run receipt with commands, results, dev target status,
   dependency stack evidence, screenshots, and handoff/PR state.

Before the agent starts Project-local work, inspect the coding run's
`readiness` manifest from the Project Runs API or run-detail payload. It is the
canonical secret-safe contract for runtime blockers, current dependency-stack
status, assigned dev-target URLs/env names, handoff branch details,
machine-target grant summary, and receipt-evidence requirements. Do not
reconstruct those facts from scattered Project settings when the run payload
already has them.

Do not use `prepare-harness-parity` or `start-api` from inside the harness task
to set up a normal Project run. A live generic Project Factory attempt proved
that doing so can restart an outer repo-dev agent's native API/UI process with
the wrong database port and interrupt the run. The correct fix is to use the already-injected
Project env and start only the Project's own dev process.
Project task runtimes export `SPINDREL_PROJECT_RUN_GUARD=1`, and the local
helper refuses those bootstrap commands unless
`SPINDREL_ALLOW_REPO_DEV_BOOTSTRAP=1` is set for an explicit infrastructure
task.

Do not route generic Project Factory work through a Spindrel-specific bot tool.
The Spindrel `tests/e2e/` suite is just another repo-local test suite when the
Project being edited is Spindrel itself.

Live Project Factory PR smoke (opt-in, opens a real draft PR):

Use any GitHub repo where the operator-bound token has push + PR scope; do not
depend on a specific operator's repo.

```bash
python scripts/agent_e2e_dev.py prepare-project-factory-smoke \
  --runtime codex \
  --github-repo OWNER/sandbox-repo \
  --base-branch master \
  --seed-github-token-from-gh

PROJECT_FACTORY_LIVE_PR=1 \
E2E_MODE=external \
E2E_HOST=$E2E_HOST \
E2E_PORT=$E2E_PORT \
E2E_KEEP_RUNNING=1 \
pytest tests/e2e/scenarios/test_project_factory_live_pr_smoke.py -v -s
```

Use `E2E_MODE=external` here. The helper already prepared the agent-owned
native API/UI; letting pytest start compose again can fail on stale or missing
provider env. The test writes
`scratch/agent-e2e/project-factory-live-pr-smoke.json` for screenshot capture
and review notes.

Generic live Project Factory loop (opt-in, no external repo):

```bash
set -a && source .env.agent-e2e && set +a
PROJECT_FACTORY_GENERIC_LOOP=1 \
PROJECT_FACTORY_RUNTIME=codex \
E2E_MODE=external \
E2E_HOST=$E2E_HOST \
E2E_PORT=$E2E_PORT \
E2E_API_KEY=e2e-test-key-12345 \
E2E_BOT_ID=default \
E2E_KEEP_RUNNING=1 \
pytest tests/e2e/scenarios/test_project_factory_generic_live_loop.py -v -s
```

Use this after dependency-stack preflight, dev-target env, runtime handoff, or
receipt-evidence changes. It launches a real harness agent against a generated
fixture Project and expects normal Project-local commands, a native source-run
server, screenshot/evidence output, and a Project run receipt. It writes
`scratch/agent-e2e/project-factory-generic-live-loop.json`; use that artifact
to capture Product UI proof from the Project Runs page, session transcript, and
served fixture app, then place durable images in `docs/images/` and reference
them from the relevant guide.

Full-live Project Factory dogfood (opt-in, real planning chat plus run/review):

```bash
set -a && source .env.agent-e2e && set +a
PROJECT_FACTORY_DOGFOOD_LIVE=1 \
PROJECT_FACTORY_DOGFOOD_RUNTIME=codex \
E2E_MODE=external \
E2E_HOST=$E2E_HOST \
E2E_PORT=$E2E_PORT \
E2E_API_KEY=e2e-test-key-12345 \
E2E_BOT_ID=default \
E2E_KEEP_RUNNING=1 \
pytest tests/e2e/scenarios/test_project_factory_dogfood_live.py -v -s
```

It writes `scratch/agent-e2e/project-factory-dogfood-live.json`. Use it when
you need to prove the actual user path from Project-bound planning chat to Work
Packs, launch, receipt evidence, and review provenance.
After it passes, capture and inspect live-result screenshots from the artifact
ids, then reference them from the docs:
`docs/images/project-factory-dogfood-live-work-packs.png`,
`docs/images/project-factory-dogfood-live-run-receipt.png`, and
`docs/images/project-factory-dogfood-live-runs.png`.

## Lessons Learned

See [`references/lessons-learned.md`](references/lessons-learned.md) for the
durable list. Append new lessons there.

## Completion Standard

Report:

- which target was used and how it was verified;
- which e2e tests ran;
- which screenshot bundle ran;
- which screenshot/artifact files were added or changed under `docs/images`;
- which docs now reference those screenshots;
- what visual inspection confirmed from the screenshots;
- any missing task grants or auth.
