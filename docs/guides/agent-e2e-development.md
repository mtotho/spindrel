# Spindrel E2E Development

This guide is the operating contract for agents developing Spindrel features
that need real e2e tests, browser screenshots, provider auth, or Project
coding-run evidence.

## Execution Contexts

There are three different agent surfaces. In this project track, use these two
short names when discussing development execution:

- **Local dev mode**: a repo-dev agent in a source checkout, like Codex running
  from this repository on a developer machine.
- **Spindrel dev mode**: a Codex/Claude harness agent running inside a
  Project-bound channel or Project coding run.

| Context | Uses | E2E path |
|---|---|---|
| Local dev mode | Shell in this checkout, repo `.agents/skills` | Run Python/pytest/screenshot scripts directly; use the helper for Docker-backed dependencies, then start API/UI/dev servers from this checkout on unused ports. |
| Spindrel dev mode | Native Codex/Claude shell/edit tools in the Project work surface | Edit files and run repo-local commands natively; start app/dev servers yourself on assigned dev target ports when present; use Project Dependency Stack tools for Docker-backed databases/services; use Spindrel tools for e2e, screenshots, server/machine, and receipts. |
| Normal Spindrel bot | Runtime tools and runtime `skills/` | Load `e2e_testing`, then call `run_e2e_tests` or granted machine tools. |

Harness agents may have native shell access, but infrastructure control is not
ambient product authority. Do not rely on direct Docker/socket access from a
native harness shell. A Project coding/review task that needs e2e, screenshots,
server commands, or Docker/compose must receive a task-scoped grant and use the
Spindrel tool/API path so the action is auditable and reviewable.

Fresh Project Instances are disposable Project roots selected through the
WorkSurface policy. Project Dependency Stacks are the Docker-backed dependency
layer for those roots: a Project declares a stack spec, and coding runs prepare
a run-scoped dependency instance through Spindrel tools. Agents still start
their own app/dev servers from source. The harness shell should not use raw
Docker.

## Local Fresh E2E Setup

Use the helper to prepare a local, gitignored environment:

```bash
python scripts/agent_e2e_dev.py write-env \
  --llm-base-url "$E2E_LLM_BASE_URL" \
  --llm-api-key "$E2E_LLM_API_KEY" \
  --model "${E2E_DEFAULT_MODEL:-gemini-2.5-flash-lite}"

python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py commands
```

Then have the helper start the shared local dependencies:

```bash
python scripts/agent_e2e_dev.py prepare-deps
python scripts/agent_e2e_dev.py start-api --build-ui
python scripts/agent_e2e_dev.py doctor
```

The default local dependency stack is durable across normal Docker restarts:
Postgres uses a named Docker volume, Postgres is exposed on `localhost:15432`
unless overridden, and the API key defaults to `e2e-test-key-12345`. Run the
Spindrel API/UI yourself from this source checkout on unused ports while
iterating. Future agents should run `doctor` first; if it reports
`subscription bootstrap: connected`, do not restart the browser OAuth flow.
`write-env` also writes stable local `ENCRYPTION_KEY` and `JWT_SECRET` values.
Do not remove those while keeping the durable Postgres volume; encrypted
provider/OAuth rows cannot boot under a different key.
If Docker leaves the default compose project with stale/dead containers that it
cannot remove, use `E2E_COMPOSE_PROJECT=<unique-name>` with alternate
`E2E_POSTGRES_PORT` / `E2E_SEARXNG_PORT` values. Do not wipe provider/OAuth
state just to get unstuck.

Use `python scripts/agent_e2e_dev.py prepare` only when you intentionally need
the full Docker app-container e2e stack for a fixture that explicitly expects
the app container.

Only wipe local e2e state when that is the explicit goal:

```bash
python scripts/agent_e2e_dev.py wipe-db --yes
```

## Provider/Auth Paths

For OpenAI-compatible providers, put the provider URL/key in `.env.agent-e2e`
through `write-env`. The helper does not print secret values.

For ChatGPT/OpenAI subscription testing:

```bash
python scripts/agent_e2e_dev.py write-env --provider subscription

python scripts/agent_e2e_dev.py bootstrap-subscription \
  --api-url http://localhost:18000 \
  --provider-id chatgpt-subscription \
  --model gpt-5.4-mini
```

Subscription mode writes a local fallback placeholder so the compose stack can
boot before OAuth exists. `bootstrap-subscription` then creates or reuses an
`openai-subscription` provider, runs the device-code OAuth flow, and patches
e2e bots to use that provider/model. By default it also rebuilds and recreates
the local Spindrel e2e app container before touching the API, so it does not
silently talk to a stale container on `:18000`. If the subscription provider is
already connected, the command skips the browser/device-code flow and only
repairs the e2e bot provider bindings.

For native Codex/Claude harness auth in the containerized local app fallback:

```bash
python scripts/agent_e2e_dev.py write-auth-override
export E2E_COMPOSE_OVERRIDES="$PWD/scratch/agent-e2e/compose.auth.override.yml"
```

The override bind-mounts existing host `~/.codex` and/or `~/.claude` into the
local e2e app container. It is local-only and gitignored. The default native
local harness path does not need this override because it runs from the host
checkout and reuses host auth directly.

## Local Harness Parity

Use this path for Codex/Claude harness parity before waiting on a deployed
server:

```bash
python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py prepare-harness-parity
./scripts/run_harness_parity_local.sh --tier core
```

`prepare-harness-parity` preserves the durable local e2e database, ensures the
Docker-backed dependencies are running, starts or reuses a native `uvicorn` API
process from this checkout on an unused port, enables the Codex/Claude
integrations, installs their declared dependencies, verifies
`/admin/harnesses`, and creates stable local harness bots/channels attached to
the real Project `Harness Parity Project` at
`common/projects/harness-parity`. It writes native API settings to
`scratch/agent-e2e/native-api.env` and channel ids/runner settings to
`scratch/agent-e2e/harness-parity.env`. The helper restarts the native API
after dependency installation so newly installed harness packages are imported
before runtime readiness is checked. In native mode it also builds `ui/dist`
so the API can serve the UI same-origin without a separate Vite process.
The parity bots are seeded with the baseline Spindrel bridge tools required by
the live scenarios, including `get_tool_info`, channel history, memory, and
skill lookup tools.
Native local parity sets `CONFIG_STATE_FILE=` by default so source-mode startup
does not replay exported config into a fresh e2e DB. It also uses the
repo-seeded `default` bot for e2e harness health checks; the compose-only
`e2e` bot exists only when the app container mounts `tests/e2e/bot.e2e.yaml`.

Claude Code readiness includes a tiny live auth smoke. Native
`claude auth status` can still report logged-in when the first SDK turn returns
`401 authentication_failed`, so a failed smoke prints the exact host refresh
command:

```bash
claude auth login
```

Use `python scripts/agent_e2e_dev.py prepare-harness-parity --docker-app` only
when a containerized app fallback run is explicitly required.

Focused local runs reuse the deployed parity scenarios:

```bash
./scripts/run_harness_parity_local.sh --tier plan -k "plan_mode_round_trip"
./scripts/run_harness_parity_local.sh --tier skills -k "native_image_input_manifest"
./scripts/run_harness_parity_local.sh --tier replay -k "persisted_tool_replay_survives_refetch"
```

For faster iteration, run focused slices in bounded parallel batches:

```bash
./scripts/run_harness_parity_local_batch.sh --preset smoke
./scripts/run_harness_parity_local_batch.sh --preset fast --jobs 3
./scripts/run_harness_parity_local_batch.sh --preset deep --list
```

Batch logs are written under `scratch/agent-e2e/harness-parity-runs/`. Use
focused selectors for parallel runs; full tier sweeps still create enough
shared channel pressure that they should be run sequentially.

For visual feedback, use local screenshots first:

```bash
./scripts/run_harness_parity_local.sh --tier project --screenshots feedback \
  -k "project_plan_build_and_screenshot"
```

Use `--screenshots docs` only when intentionally refreshing checked-in harness
fixtures under `docs/images`; that mode runs `python -m scripts.screenshots
check` after capture. Local e2e disables Docker-stack-backed browser automation
by default, so shared browser-runtime tool tests may skip locally unless the
stack is explicitly enabled. Chat UI screenshots still run through the normal
Playwright screenshot pipeline.

## Screenshots

For UI work, use the visual feedback loop after the e2e API/UI target is
current:

```bash
python scripts/agent_e2e_dev.py write-screenshot-env \
  --api-url http://localhost:18000 \
  --ui-url http://localhost:5173 \
  --setup-user

python -m scripts.screenshots stage --only project-workspace
python -m scripts.screenshots capture --only project-workspace
python -m scripts.screenshots check
```

Inspect changed images before calling the work done. Screenshot assertions prove
that the scripted route rendered; visual review proves the UI is acceptable.

For workflow e2e, screenshots are part of the acceptance contract. Capture the
screens a reviewer would use to trust the run: the Project or channel surface
that launched work, the session transcript or Runs/Receipts rows that show what
the agent did, and any generated app/browser output. Use temporary screenshots
while debugging, but final proof artifacts must live under `docs/images/`, be
referenced from this guide or the relevant feature guide, and pass:

```bash
python -m scripts.screenshots check
```

Do not report a workflow as visually verified when the screenshot only shows
the final generated page. If the claim is that Spindrel created, ran, reviewed,
or recorded work, include Spindrel UI screenshots proving that path.

Screenshot staging should be deterministic for documentation artifacts. If a
capture needs a transcript, inject fixture messages or seed durable rows instead
of relying on a live model turn. Local screenshot data can survive app rebuilds
with an old encrypted secret value; staging should repair those fixture secrets
through the API instead of wiping the durable e2e database.

## Project Factory Contract Test

Use this scenario before a live agent/PR smoke when changing issue intake,
triage work packs, Project coding-run launch, Project run receipts, review
sessions, or review finalization:

```bash
python scripts/agent_e2e_dev.py doctor
python scripts/agent_e2e_dev.py prepare

set -a && source .env.agent-e2e && set +a
E2E_KEEP_RUNNING=1 pytest tests/e2e/scenarios/test_project_factory_flow.py -v
```

The test proves the durable Project Factory spine without asking a real model
or GitHub repo to do work: rough issue notes become work packs, a code work pack
launches a Project coding run, the run publishes a PR-like receipt with test and
screenshot evidence, a review session reads fresh context, accepted
finalization marks the selected run reviewed, and needs-info packs stay out of
the coding-run queue.

## Project Factory Live PR Smoke

Use this only after the deterministic Project Factory contract test is green.
It drives a real Codex harness agent through the local `localhost:18000` e2e
server, clones the configured GitHub repo, commits a marker file, opens a draft
PR, and publishes a Project run receipt. It is intentionally opt-in because it
pushes a branch and opens a real PR.

Prepare the local stack from current source, mount host Codex auth, install
`gh`, and seed the local e2e GitHub token from `gh auth token`:

```bash
python scripts/agent_e2e_dev.py prepare-project-factory-smoke \
  --runtime codex \
  --github-repo mtotho/vault \
  --base-branch master \
  --seed-github-token-from-gh
```

Then run pytest against the already-prepared local server. Use external mode so
pytest does not try to start a second compose stack or require fresh
`E2E_LLM_BASE_URL` values:

```bash
PROJECT_FACTORY_LIVE_PR=1 \
E2E_MODE=external \
E2E_HOST=localhost \
E2E_PORT=18000 \
E2E_KEEP_RUNNING=1 \
pytest tests/e2e/scenarios/test_project_factory_live_pr_smoke.py -v -s
```

The scenario writes `scratch/agent-e2e/project-factory-live-pr-smoke.json` with
the Project id, task id, Project run id, marker path, and PR URL. Use that
artifact to capture local UI evidence. The current docs artifacts are:

![Project Factory live PR smoke run](../images/project-factory-live-pr-smoke.png)

![Project Factory live PR smoke receipts](../images/project-factory-live-pr-smoke-receipts.png)

## Native Project Parity Evidence

The native local parity proof should include both product UI evidence and the
generated app screenshot. The current checked-in proof artifacts are:

![Project parity Project files](../images/project-parity-project-detail.png)

![Project parity channel binding](../images/project-parity-project-channels.png)

![Project parity Codex session transcript](../images/project-parity-codex-session.png)

![Project parity generated app](../images/project-parity-generated-app.png)

After UI-affecting Project Factory changes, refresh and inspect the Project
Workspace screenshot bundle:

```bash
python -m scripts.screenshots stage --only project-workspace
python -m scripts.screenshots capture --only project-workspace
python -m scripts.screenshots check
```

## Project Coding Runs

Project coding-run and review agents should:

1. Work only inside the resolved Project or Project Instance root.
2. Update from the configured base branch when safe.
3. Use native Codex/Claude editing and shell tools for repo-local code work.
4. Use `get_project_dependency_stack` and `manage_project_dependency_stack` for
   Project-declared Docker-backed databases, service dependencies, logs,
   restarts, rebuilds, service commands, health checks, and connection env. If
   stack shape changes, edit the Project compose file and call
   `manage_project_dependency_stack(action="reload")`.
5. Start app/dev servers yourself from source on assigned dev target ports
   (`SPINDREL_DEV_*_PORT` / `SPINDREL_DEV_*_URL`) when present. If no dev
   target is assigned, choose an unused port. Do not restart another agent's
   process.
6. Use `run_e2e_tests(status)` before e2e checks to confirm the target.
7. Use task-granted Spindrel tools for e2e, screenshots, server/machine, and Docker/compose actions.
8. Publish receipts with tests, screenshots, dev target URL/status evidence,
   dependency stack evidence, branch/PR handoff, and any blocked infrastructure grants.

If a task does not have the needed grant, report the missing grant instead of
attempting ambient infrastructure access.
