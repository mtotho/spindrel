# Spindrel E2E Development

This guide is the operating contract for agents developing Spindrel features
that need real e2e tests, browser screenshots, provider auth, or Project
coding-run evidence.

## Execution Contexts

There are three different agent surfaces:

| Context | Uses | E2E path |
|---|---|---|
| Local repo-dev agent | Shell in this checkout, repo `.agents/skills` | Run pytest and screenshot scripts directly. |
| Harness task agent | Native Codex/Claude shell/edit tools in the Project work surface | Edit files natively; use task-granted Spindrel tools for e2e, screenshots, machine/server, Docker/compose, and receipts. |
| Normal Spindrel bot | Runtime tools and runtime `skills/` | Load `e2e_testing`, then call `run_e2e_tests` or granted machine tools. |

Harness agents may have native shell access, but infrastructure control is not
ambient product authority. Do not rely on direct Docker/socket access from a
native harness shell. A Project coding/review task that needs e2e, screenshots,
server commands, or Docker/compose must receive a task-scoped grant and use the
Spindrel tool/API path so the action is auditable and reviewable.

Fresh Project Instances are currently disposable Project roots selected through
the WorkSurface policy. They are not per-task Docker sidecars. Per-task Docker
stacks are future Project Factory work.

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

Then have the helper build current source, recreate the local Spindrel e2e
stack, and wait for health:

```bash
python scripts/agent_e2e_dev.py prepare
python scripts/agent_e2e_dev.py doctor
```

The default local stack is durable across normal Docker restarts: Postgres uses
a named Docker volume, the server runs on `localhost:18000`, and the API key
defaults to `e2e-test-key-12345`. `prepare` recreates only the Spindrel app
container, so local provider/OAuth state survives normal rebuilds and restarts.
Future agents should run `doctor` first; if it reports
`subscription bootstrap: connected`, do not restart the browser OAuth flow.

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

For native Codex/Claude harness auth in a local e2e container:

```bash
python scripts/agent_e2e_dev.py write-auth-override
export E2E_COMPOSE_OVERRIDES="$PWD/scratch/agent-e2e/compose.auth.override.yml"
```

The override bind-mounts existing host `~/.codex` and/or `~/.claude` into the
local e2e app container. It is local-only and gitignored.

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
4. Use `run_e2e_tests(status)` before e2e checks to confirm the target.
5. Use task-granted Spindrel tools for e2e, screenshots, server/machine, and Docker/compose actions.
6. Publish receipts with tests, screenshots, branch/PR handoff, and any blocked infrastructure grants.

If a task does not have the needed grant, report the missing grant instead of
attempting ambient infrastructure access.
