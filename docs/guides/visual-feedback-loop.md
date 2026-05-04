# Visual Feedback Loop

Browser screenshots are part of the UI acceptance loop. For Spatial Canvas,
Starboard, Map Brief, mobile hub, and other visual surfaces, a typecheck plus
DOM assertions is not enough. The run should create documentation images,
exercise browser behavior, and leave a visible artifact an engineer can inspect.

For local fresh e2e setup, screenshot env generation, and the difference
between local agents, harness agents, and runtime bots, read
[Agent E2E Development](agent-e2e-development.md).

## Canonical Spatial Canvas Run

Run from the repo root. The screenshot tool reads
`scripts/screenshots/.env`, which must point at the e2e instance or a local
development UI backed by the e2e API.
For native local e2e, leave `SSH_ALIAS` / `SSH_CONTAINER` blank; server helper
fixtures run in the current checkout with the sourced `native-api.env` instead
of requiring a Docker app container.

```bash
python -m scripts.screenshots stage --only spatial-checks
python -m scripts.screenshots capture --only spatial-checks
python -m scripts.screenshots check
```

The capture step writes documentation artifacts to `docs/images/`. Review these
checked-in images before closing the UI pass:

- [spatial-check-map-brief-selection.png](../images/spatial-check-map-brief-selection.png)
- [spatial-check-canvas-view-controls.png](../images/spatial-check-canvas-view-controls.png)
- [spatial-check-jump-starboard-framing.png](../images/spatial-check-jump-starboard-framing.png)
- [spatial-check-channel-schedule-satellites.png](../images/spatial-check-channel-schedule-satellites.png)
- [spatial-check-attention-badge.png](../images/spatial-check-attention-badge.png)
- [spatial-check-attention-review-deck.png](../images/spatial-check-attention-review-deck.png)
- [spatial-check-issue-intake-work-packs.png](../images/spatial-check-issue-intake-work-packs.png)
- [spatial-check-attention-run-log.png](../images/spatial-check-attention-run-log.png)
- [spatial-check-hover-suppression.png](../images/spatial-check-hover-suppression.png)
- [spatial-check-overview-hover-calm.png](../images/spatial-check-overview-hover-calm.png)
- [spatial-check-cluster-focus-calm.png](../images/spatial-check-cluster-focus-calm.png)
- [spatial-check-cluster-doubleclick-focus.png](../images/spatial-check-cluster-doubleclick-focus.png)
- [spatial-check-density-smoke.png](../images/spatial-check-density-smoke.png)

If these files change, inspect them before finishing. Passing screenshot
assertions proves the DOM-level contract, not that the UI feels good.

Before accepting refreshed images, verify that the captured UI is actually
showing the staged scenario data. The stage step and browser login must land in
the same workspace/user context. If screenshots show unrelated live channels,
empty attention lanes after staged attention was created, or route state from a
prior run, treat the bundle as failed even if some DOM assertions pass.
If screenshots show stale labels or pre-change layout while the built assets
contain the new code, suspect browser/service-worker caching before changing
product code. The screenshot runner blocks service workers for fresh captures;
preserve that behavior when adding new capture paths.

## Evidence Artifact Rule

Screenshots serve two jobs:

- They are the agent feedback loop. Open or inspect them and use what you see to
  decide whether the UI works, renders the right state, and looks acceptable.
- They are proof for review. Durable proof images belong in source-controlled
  `docs/images/` and must be referenced from the relevant guide or feature doc.

Temporary `/tmp` or `scratch/` captures are useful while iterating, but they are
not final evidence. Before claiming a UI/e2e workflow is verified, copy or
capture the proof images into `docs/images/`, add markdown references to the
relevant docs, and run:

```bash
python -m scripts.screenshots check
```

For workflow e2e, capture the workflow surfaces, not just the final output. A
Project run proof should include the Project/Runs/Channels page or channel
session transcript plus generated app/browser output as applicable.

## When To Add Or Update A Scenario

Add a screenshot scenario when a visual behavior should not regress:

- Starboard or drawer framing.
- Object selection, jump, zoom, or cluster behavior.
- Hover suppression and popover ownership.
- Mobile hub layout or route handoff.
- Explicit design anti-pattern prevention, such as duplicate labels,
  side-stripe chrome, clipped content, or runaway padding.

Prefer e2e-seeded state through `scripts/screenshots/stage/scenarios/`. Avoid
manual live data setup when the behavior can be staged.

## Scenario Rules

- Store specs in `scripts/screenshots/capture/specs.py`.
- Use stable `data-testid` or `data-*` hooks for actions and assertions.
- Assert user-visible behavior, not private component structure.
- Save outputs under `docs/images/` so the run doubles as documentation.
- Keep selectors specific enough to fail loudly when the UI contract changes.
- Do not hide visual review behind screenshots alone. Open or inspect the
  generated images and record visible findings.

## Required Closeout

For any UI pass using screenshots, the session log or final answer must state:

- the screenshot bundle run;
- whether staging and capture succeeded;
- which `docs/images` files changed;
- which docs reference those screenshots;
- what visual inspection confirmed from the images;
- remaining visual issues, if any.

For UI code changes, also run:

```bash
cd ui && npx tsc --noEmit --pretty false
```

For screenshot spec changes, also run:

```bash
PYTHONPYCACHEPREFIX=/tmp/codex-pycache python -m py_compile scripts/screenshots/capture/specs.py
PYTHONPATH=. pytest scripts/screenshots/tests/test_pure_units.py -q
```

## Project Workspace Run

Use this bundle when changing Project workspace pages, channel Project
bindings, or Project-rooted file/terminal behavior:

```bash
python -m scripts.screenshots stage --only project-workspace
python -m scripts.screenshots capture --only project-workspace
python -m scripts.screenshots check
```

Expected artifacts:

```text
project-workspace-list.png
project-workspace-detail.png
project-workspace-files.png
project-workspace-blueprints.png
project-workspace-blueprint-editor.png
project-workspace-settings-blueprint.png
project-workspace-setup-ready.png
project-workspace-setup-run-history.png
project-workspace-instances.png
project-workspace-runs.png
project-workspace-review-inbox.png
project-workspace-run-detail.png
project-workspace-review-ledger.png
project-workspace-scheduled-reviews.png
project-workspace-execution-access.png
project-workspace-review-launched.png
project-workspace-review-execution-access.png
project-workspace-review-finalized.png
project-workspace-terminal.png
project-workspace-channels.png
project-workspace-channel-settings.png
project-workspace-channel-header.png
project-workspace-memory-tool.png
project-factory-live-pr-smoke.png
project-factory-live-pr-smoke-receipts.png
```

The staging step creates a reusable screenshot Project, attaches one channel to
it, creates one attachable channel, writes a file through the channel workspace
API, seeds a Blueprint-created Project with secret bindings, runs repo plus
setup-command preparation for `https://github.com/mtotho/spindrel.git`, seeds
a fresh Project instance, starts or shims one Project coding run with linked
branch/PR progress receipts, review receipt, scheduled review controls,
selected-run review controls, and a memory-tool turn. Inspect all deterministic
Project Workspace images before closing out: the
bundle intentionally checks Project admin surfaces, Blueprint management,
Project setup commands and run history, Project Basics readiness,
Project runtime-env readiness, fresh
Project instances, Project coding-run cockpit/receipts/review launcher,
Needs Human Review queue, review-session ledger, scheduled Project reviews,
task-scoped execution access for coding and review launches, launched
review-session confirmation, finalized review/merge provenance, Project
settings, and the channel transcript.

The two `project-factory-live-pr-smoke*` images are live evidence rather than
deterministic staging fixtures. Capture them after the opt-in live PR smoke in
[Agent E2E Development](agent-e2e-development.md), using the scratch JSON
artifact from that test to open the real local Project Runs page against
the leased `SPINDREL_E2E_URL` / `E2E_PORT`. Do not assume a fixed local port.

## Channel Quick Automations Run

Use this bundle when changing Channel Settings -> Automation -> Tasks quick
automation presets, preset review drawers, or channel-scoped task shortcuts:

```bash
python -m scripts.screenshots stage --only channel-quick-automations
python -m scripts.screenshots capture --only channel-quick-automations
python -m scripts.screenshots check
```

Expected artifacts:

```text
channel-quick-automations.png
channel-quick-automation-drawer.png
channel-quick-automation-drawer-mobile.png
```

The staging step creates one reusable channel with a screenshot bot. The
capture opens the quick-automation preset drawer without creating a task, so it
is safe to rerun. Inspect all three images before closing out: the bundle
checks the in-settings preset surface plus desktop and mobile drawer framing.

## Channel Widget Usefulness Run

Use this bundle when changing the channel dashboard widget proposal affordance,
usefulness drawer, recent bot widget activity receipts, Channel Settings ->
Dashboard usefulness summary, Bot widget agency control, or Agent readiness
widget-authoring status:

```bash
python -m scripts.screenshots stage --only channel-widget-usefulness
python -m scripts.screenshots capture --only channel-widget-usefulness
python -m scripts.screenshots check
```

Expected artifacts:

```text
channel-widget-usefulness-dashboard.png
channel-widget-usefulness-drawer.png
channel-widget-usefulness-settings.png
channel-widget-authoring-readiness.png
```

The staging step creates one channel with duplicate native widgets and a dock
widget hidden by the channel's chat layout mode. Capture uses a narrow browser
shim for the assessment, receipt, and agent-capability endpoints so artifacts
stay deterministic when the shared e2e API lags the UI branch; the dashboard
pins themselves are real. Inspect all four images before closeout: the bundle
checks the dashboard toolbar affordance, the widget proposal drawer, recent bot
widget activity receipts including authoring evidence, the compact settings
summary, and the Agent readiness widget-authoring row with the HTML full-check
badge.

## Voice Input Run

Use this bundle when changing the web composer microphone flow or the
browser-recorded audio payload sent to chat:

```bash
python -m scripts.screenshots stage --only voice-input
python -m scripts.screenshots capture --only voice-input
python -m scripts.screenshots check
```

Expected artifacts:

```text
chat-voice-recording.png
chat-voice-payload.png
```

The staging step creates a reusable `screenshot:voice-input` channel. Capture
uses browser media shims and a fake chat submit so the recording overlay and
encoded `audio_data` payload are deterministic.

## Dashboard Pin Config Editor Run

Use this bundle when changing the dashboard pin editor, widget config schema
controls, or the advanced JSON escape hatch:

```bash
python -m scripts.screenshots stage --only dashboard-pin-config-editor
python -m scripts.screenshots capture --only dashboard-pin-config-editor
python -m scripts.screenshots check
```

Expected artifacts:

```text
dashboard-pin-config-editor.png
dashboard-pin-config-editor-mobile.png
```

The staging step creates one real channel dashboard pin. Capture uses a narrow
browser shim to attach a deterministic `config_schema` to that pin so the UI
shows schema-backed settings with Advanced JSON collapsed. Inspect both desktop
and mobile drawer captures before closeout.

## Widget Authoring Runtime Check

Use the Templates tab **Full Check** action, or the bot-facing
`check_widget_authoring(..., include_runtime=true, include_screenshot=true)`
tool, when changing tool-widget authoring UX or debugging draft YAML/Python
widgets. For standalone HTML/library/path widgets, use
`check_html_widget_authoring(..., include_runtime=true, include_screenshot=true)`
with the same source args you plan to emit or pin. These are runtime smokes, not
docs screenshot bundles: the server renders the draft envelope, opens
`/widgets/dev/runtime-preview` in Playwright, checks browser errors and visible
bounds, and can return a PNG data URL artifact for inspection.

Run the normal UI typecheck after related UI changes:

```bash
cd ui && npx tsc --noEmit --pretty false
```

Local UI patches do not need to be deployed before screenshot review. Start the
patched app from the current checkout on the agent-owned local e2e port, point
the screenshot runner or Playwright script at that URL, and inspect the images.
Use a shared deployed server only for explicit post-deploy verification.

## Harness Parity Run

External harness parity screenshots use real live harness sessions rather than
synthetic screenshot staging. They are documented in
`agent-harnesses.md`. Verification captures are written under `/tmp` by
default; set `HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR=docs/images` only when
refreshing checked-in `docs/images/harness-*.png` fixtures.
Run the project-build tier first when refreshing terminal/native tool-output
fixtures. The runner creates the live Codex and Claude project-build sessions,
then automatically captures screenshots after pytest passes.

```bash
# Test-server SSH alias is operator-private — see vault `Test Server Operations.md`.
ssh "$TEST_SERVER_SSH" 'cd /opt/thoth-server && \
  HARNESS_PARITY_TIER=project ./scripts/run_harness_parity_live.sh \
    -k project_plan_build_and_screenshot'
```

Set `HARNESS_PARITY_CAPTURE_SCREENSHOTS=false` only for an intentionally
diagnostic run. Use a local dev UI by running
`python -m scripts.screenshots.harness_live` directly when validating a UI patch
before deploy, and use the deployed UI after deploy. When Playwright runs in
the shared Docker browser runtime, the runner resolves the container-reachable
browser URL automatically; see `scripts/screenshots/README.md` for the manual
main-host Docker command.
Question-card captures require a pending harness question and
`HARNESS_VISUAL_QUESTION_SESSION_ID`; the normal bridge, terminal write,
`/style` command-picker, and usage-log captures rediscover the latest E2E
sessions from the configured harness channels. Native slash command captures
create fresh purpose-built sessions so picker/result screenshots do not inherit
noise from bridge parity transcripts.

## Native Spindrel Plan Mode Run

Native plan-mode screenshots use real live Spindrel sessions rather than
synthetic screenshot staging. First run the live diagnostics to create fresh
detached sessions on the dedicated native-plan E2E channel:

```bash
./scripts/run_spindrel_plan_live.sh --tier adherence
```

Use `--tier behavior` for the faster protocol/behavior pass and `--tier
quality` when validating professional-plan mechanics. Use `--tier stress` when
validating retry/revision pressure and plan-card readability. Use `--tier
adherence` when validating approved-plan execution, recorded evidence, and the
semantic adherence review. The runner writes the latest session ids to
`/tmp/spindrel-plan-parity/spindrel-plan-sessions.json`.
Capture the matching UI artifacts with:

```bash
SPINDREL_API_KEY=... \
python -m scripts.screenshots.spindrel_plan_live \
  --api-url "$SPINDREL_API_URL" \
  --ui-url "$SPINDREL_API_URL" \
  --browser-url "$SPINDREL_API_URL" \
  --output-dir docs/images
```

Set `SPINDREL_API_URL` to the test-server URL (operator-private; see vault
`Test Server Operations.md`).

Expected artifacts:

```text
spindrel-plan-question-card-dark.png
spindrel-plan-card-default-dark.png
spindrel-plan-card-mobile-dark.png
spindrel-plan-card-terminal-dark.png
spindrel-plan-answered-questions-dark.png
spindrel-plan-answered-questions-terminal-dark.png
spindrel-plan-progress-executing-mobile-dark.png
spindrel-plan-progress-executing-terminal-dark.png
spindrel-plan-replan-pending-default-dark.png
spindrel-plan-replan-pending-terminal-dark.png
spindrel-plan-pending-outcome-default-dark.png
spindrel-plan-pending-outcome-terminal-dark.png
spindrel-plan-quality-contract-default-dark.png
spindrel-plan-quality-contract-terminal-dark.png
spindrel-plan-stress-readability-default-dark.png
spindrel-plan-stress-readability-mobile-dark.png
spindrel-plan-stress-readability-terminal-dark.png
spindrel-plan-adherence-review-default-dark.png
spindrel-plan-adherence-review-terminal-dark.png
spindrel-plan-adherence-auto-default-dark.png
spindrel-plan-adherence-auto-terminal-dark.png
spindrel-plan-adherence-unsupported-default-dark.png
spindrel-plan-adherence-unsupported-terminal-dark.png
spindrel-plan-adherence-retry-default-dark.png
spindrel-plan-adherence-retry-terminal-dark.png
```

When Playwright runs in the shared Docker browser runtime, use the same
container-IP pattern documented in `scripts/screenshots/README.md`, replacing
`scripts.screenshots.harness_live` with
`scripts.screenshots.spindrel_plan_live`.
