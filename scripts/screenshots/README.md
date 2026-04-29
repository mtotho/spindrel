# scripts/screenshots — automated scenario staging + capture

Runs locally, talks to the e2e instance at `10.10.30.208:18000`, lands PNGs in
`docs/images/`. Never touches production.

## Setup

```bash
cd scripts/screenshots
pip install -r requirements.txt
cp .env.example .env
# Fill in SPINDREL_LOGIN_EMAIL / SPINDREL_LOGIN_PASSWORD for an admin user on
# the e2e instance. SPINDREL_API_KEY defaults to the baked e2e key.
```

Browser capture uses the shared launcher in `scripts/screenshots/playwright_runtime.py`.
It tries `PLAYWRIGHT_WS_URL`, then the `browser_automation` runtime-service
endpoint, then `PLAYWRIGHT_CHROMIUM_EXECUTABLE` such as `/snap/bin/chromium`,
then Playwright-managed Chromium. If no backend is available, install the
managed fallback with `python -m playwright install chromium`.

## Spindrel live-server harness captures

Do not rely on memory alone to decide whether you are targeting the main
Spindrel server or an e2e instance. A channel hint such as "use main Spindrel"
is helpful, but verify the target before running parity checks or writing
screenshots. Be explicit about the context: the in-app Codex/Claude harness runs
inside the Spindrel app container, not in the host checkout.

The main deployed server currently uses:

- Host checkout/control path for SSH/operator commands: `/opt/thoth-server`
- API/UI from the server host: `http://127.0.0.1:8000`
- API/UI from the LAN: `http://10.10.30.208:8000`
- Running app container: `agent-server-agent-server-1`
- App-container code path: `/app`
- App-container workspace root: `/workspace-data`
- Browser stack container: `spindrel-local-browser-automation-playwright-1`
- Runtime DNS name from the app container: `playwright-local`

E2E instances use their own port, repo path, containers, and API key. Common
signals are port `18000`, an e2e repo/worktree path, and container names that
include the e2e instance id. Verify with `docker ps`, health, and the selected
host checkout before capture.

Run Docker diagnostics from the server host, not the workstation, when the
check needs container DNS or container names:

```bash
ssh spindrel-bot "cd /opt/thoth-server && \
  docker ps --format '{{.Names}}' | grep -E 'agent-server|browser-automation' && \
  docker exec agent-server-agent-server-1 getent hosts playwright-local"
```

For an in-app harness turn, do not tell Codex to use `/opt/thoth-server`. The
harness receives `ctx.workdir` from the channel Project Directory resolver:

- Channel `project_path=common/projects` resolves inside the app container to
  `/workspace-data/shared/<workspace_id>/common/projects`.
- The Spindrel repo lives under that cwd as `./spindrel`, matching local
  developer checkouts where the workspace root is `/home/mtoth/personal` and
  the repo is `./agent-server`.
- The harness sends that value to Codex as `cwd` in `thread/start` and
  `turn/start`.
- Verify the actual value from the harness status/details surface
  (`effective_cwd`) or by checking the channel Project Directory; `/opt` is
  only the host checkout used by SSH maintenance commands.

The live harness parity suite includes a project-build tier for this exact
path. It sets/verifies `project_path=common/projects`, asks Codex and Claude to
plan then build a small static app under `./e2e-testing/<runtime>-<run_id>`,
and captures the result through the shared Playwright runtime:

```bash
ssh spindrel-bot 'cd /opt/thoth-server && \
  HARNESS_PARITY_TIER=project ./scripts/run_harness_parity_live.sh \
    -k project_plan_build_and_screenshot'
```

Scratch app files are deleted through the workspace file API after the test.
Per-test diagnostic screenshots land under `/tmp/spindrel-harness-parity/`
unless `HARNESS_PARITY_ARTIFACT_DIR` is set. For `project` and deeper tiers,
`run_harness_parity_live.sh` also runs the live harness screenshot capturer
after pytest passes and writes the docs fixtures to `docs/images` by default.
Use `HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR` to change that destination, or
`HARNESS_PARITY_CAPTURE_SCREENSHOTS=false` to skip docs fixture capture.

Deeper tiers build on that path:

- `memory` seeds a bot memory reference file through the shared workspace API and verifies the harness only sees it after an explicit bridged `get_memory_file` call.
- `skills` creates a temporary skill, tags it with `@skill:<id>`, and verifies a bridged `get_skill` call persists a renderable result envelope.
- `replay` refetches a harness session after a bridge tool call and verifies the persisted transcript/tool-result metadata still renders from stored messages.

The runner prefers the running app container's `API_KEY` over the host `.env`,
waits for `/health` before pytest starts, and uses `E2E_BOT_ID=default` for the
generic E2E fixture readiness check; Codex and Claude harness turns still
target their configured channel/bot ids. When `PLAYWRIGHT_WS_URL` is not set,
it resolves the local browser automation container IP and uses
`PLAYWRIGHT_CONNECT_PROTOCOL=cdp`.

When capturing docs screenshots, run the script from the host checkout but
connect to the app through Docker networking. The browser itself runs inside the
Playwright container, so from that browser `127.0.0.1:8000` means the Playwright
container, not the Spindrel app container.

```bash
ssh spindrel-bot 'cd /opt/thoth-server && \
  browser_ip=$(docker inspect spindrel-local-browser-automation-playwright-1 \
    --format "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}") && \
  app_ip=$(docker inspect agent-server-agent-server-1 \
    --format "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}") && \
  curl -fsS "http://$browser_ip:3000/json/version" >/dev/null && \
  PLAYWRIGHT_WS_URL="ws://$browser_ip:3000" \
  PLAYWRIGHT_CONNECT_PROTOCOL=cdp \
  SPINDREL_URL="http://$app_ip:8000" \
  SPINDREL_UI_URL="http://$app_ip:8000" \
  SPINDREL_BROWSER_URL="http://$app_ip:8000" \
  DOCS_IMAGES_DIR=/opt/thoth-server/docs/images \
  .venv/bin/python -m scripts.screenshots.harness_live'
```

Use the matching API key for the instance being captured. `SPINDREL_URL` is the
URL used by the host-side Python process; `SPINDREL_BROWSER_URL` is the URL
opened inside the Playwright container and injected into browser auth state.
The command above is for the main deployed server shape; adapt the host
checkout, app container, browser container, and port after verification for e2e.

Native Spindrel plan-mode captures use the same network shape after
`./scripts/run_spindrel_plan_live.sh --tier publish` has written
`/tmp/spindrel-plan-parity/spindrel-plan-sessions.json`:

```bash
ssh spindrel-bot 'cd /opt/thoth-server && \
  browser_ip=$(docker inspect spindrel-local-browser-automation-playwright-1 \
    --format "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}") && \
  app_ip=$(docker inspect agent-server-agent-server-1 \
    --format "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}") && \
  curl -fsS "http://$browser_ip:3000/json/version" >/dev/null && \
  PLAYWRIGHT_WS_URL="ws://$browser_ip:3000" \
  PLAYWRIGHT_CONNECT_PROTOCOL=cdp \
  SPINDREL_URL="http://$app_ip:8000" \
  SPINDREL_UI_URL="http://$app_ip:8000" \
  SPINDREL_BROWSER_URL="http://$app_ip:8000" \
  DOCS_IMAGES_DIR=/opt/thoth-server/docs/images \
  .venv/bin/python -m scripts.screenshots.spindrel_plan_live'
```

## Usage

```bash
# dry-run the stage to see what will be written
python -m scripts.screenshots stage --only flagship --dry-run

# actually stage (idempotent: rerunnable)
python -m scripts.screenshots stage --only flagship

# capture the flagship 8
python -m scripts.screenshots capture --only flagship

# capture attachment composer checks
python -m scripts.screenshots all --only attachment-checks

# do both in one shot
python -m scripts.screenshots all --only flagship

# remove everything prefixed screenshot:* / screenshot-*
python -m scripts.screenshots teardown --only flagship
```

## Architecture

- `stage/client.py` — httpx-based `SpindrelClient`; one idempotent helper per
  admin endpoint used. All writes go through the real API.
- `stage/_exec.py` + `stage/server_helpers/` — narrow SSH + `docker exec`
  escape hatch for the two cases the HTTP API deliberately does not expose:
  1. `seed_pipeline_step_states` mutates `tasks.step_states` on an existing
     pipeline task so the PipelineRunLive modal renders a frozen 2/3-done state.
  2. `seed_usage_events` inserts `trace_events` rows with
     `event_type="token_usage"` so `/admin/bots` cost pills populate without
     spending real LLM tokens.
  Everything else stays on HTTP.
- `capture/browser.py` — Playwright context with two init-scripts:
  1. Seeds localStorage under the Zustand persist key `agent-auth` with a
     `POST /auth/login` bundle — the app mounts authed from frame 1.
  2. Installs a `window.__spindrel_ready` counter that listens for the
     `spindrel:ready` postMessage handshake from interactive HTML widgets,
     plus a `window.__spindrel_pin_count()` helper for native pin tiles.
- `capture/specs.py` — `FLAGSHIP_SPECS` registry. Each spec has an explicit
  wait strategy (`selector` / `function` / `network_idle` / `pin_count`).
  No implicit `sleep` — flake is visible, not silent.
- `capture/runner.py` — groups specs by viewport/color-scheme so one context
  serves all same-viewport shots, reports per-spec status.

## Flagship 8 punch list

| File | Route | Viewport | Wait |
|------|-------|----------|------|
| `home.png` | `/` | 1440×900 | `[data-testid="channel-row"]:nth-of-type(4)` |
| `chat-main.png` | `/channels/:id` | 1440×900 | `window.__spindrel_pin_count() >= 2` |
| `widget-dashboard.png` | `/widgets/channel/:channelId` | 1440×900 | `window.__spindrel_pin_count() >= 6` |
| `chat-pipeline-live.png` | `/channels/:id?run=:taskId` | 1440×900 | `[data-status="running"]` |
| `html-widget-hero.png` | `/widgets/channel/:channelId` | 1440×900 | `window.__spindrel_ready >= 1 \|\| ...` |
| `dev-panel-tools.png` | `/widgets/dev` | 1440×900 | `[data-testid="rendered-envelope"], [data-testid="raw-result"]` |
| `omnipanel-mobile.png` | `/channels/:id` | 375×812 | drawer open (pre_capture clicks hamburger) |
| `admin-bots-list.png` | `/admin/bots` | 1440×900 | `[data-testid="bot-row"]:nth-of-type(3)` |

## Attachment checks

The `attachment-checks` bundle stages an isolated `screenshot:attachments`
channel and writes these documentation artifacts:

| File | Route | Viewport | Wait |
|------|-------|----------|------|
| `chat-attachments-drop-overlay.png` | `/channels/:attachments` | 1440×900 | composer drop zone ready |
| `chat-attachments-routing-tray.png` | `/channels/:attachments` | 1440×900 | pending rows routed/uploaded |
| `chat-attachments-sent-receipts.png` | `/channels/:attachments` | 1440×900 | optimistic image + data receipts |
| `chat-attachments-terminal-sent-receipts.png` | `/channels/:attachments` | 1440×900 | terminal-mode optimistic receipts |

## Key invariants

- **Never hit `/opt/thoth-server/`** — `config.load()` refuses URLs that don't
  look like the e2e instance.
- **Staging is idempotent** — every record keyed on a `screenshot:*` /
  `screenshot-*` prefix; `stage` reruns dedupe automatically.
- **Every spec declares its wait signal** — `sleep(N)` is banned.
- **Two fields cross the docker-exec hatch** (`tasks.step_states`, seeded
  `trace_events`). If you're tempted to add a third, add an admin endpoint.
- **No auto-commit** — capture writes PNGs, reviewer commits.

## Not in scope (yet)

- Thinking-indicator live shots — dynamic; capture in a follow-up.
- Push-notification OS popup — not HTML; capture manually via `browser_live`.
- The remaining ~32 shots (admin secrets/usage/approvals/etc, integration
  gallery, marketing-site placeholders). Fan out `capture/specs.py` + a new
  stager per scenario; nothing structural has to change.
