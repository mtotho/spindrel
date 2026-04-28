# scripts/screenshots — automated scenario staging + capture

Runs locally, talks to the e2e instance at `10.10.30.208:18000`, lands PNGs in
`docs/images/`. Never touches production.

## Setup

```bash
cd scripts/screenshots
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Fill in SPINDREL_LOGIN_EMAIL / SPINDREL_LOGIN_PASSWORD for an admin user on
# the e2e instance. SPINDREL_API_KEY defaults to the baked e2e key.
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
