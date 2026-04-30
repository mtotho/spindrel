# Visual Feedback Loop

Browser screenshots are part of the UI acceptance loop. For Spatial Canvas,
Starboard, Map Brief, mobile hub, and other visual surfaces, a typecheck plus
DOM assertions is not enough. The run should create documentation images,
exercise browser behavior, and leave a visible artifact an engineer can inspect.

## Canonical Spatial Canvas Run

Run from the repo root. The screenshot tool reads
`scripts/screenshots/.env`, which must point at the e2e instance or a local
development UI backed by the e2e API.

```bash
python -m scripts.screenshots stage --only spatial-checks
python -m scripts.screenshots capture --only spatial-checks
python -m scripts.screenshots check
```

The capture step writes documentation artifacts to `docs/images/`:

```text
spatial-check-map-brief-selection.png
spatial-check-jump-starboard-framing.png
spatial-check-channel-schedule-satellites.png
spatial-check-attention-badge.png
spatial-check-attention-review-deck.png
spatial-check-attention-run-log.png
spatial-check-hover-suppression.png
spatial-check-overview-hover-calm.png
spatial-check-cluster-focus-calm.png
spatial-check-cluster-doubleclick-focus.png
spatial-check-density-smoke.png
```

If these files change, inspect them before finishing. Passing screenshot
assertions proves the DOM-level contract, not that the UI feels good.

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
- which artifact files changed;
- what visual inspection confirmed;
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
project-workspace-blueprints.png
project-workspace-blueprint-editor.png
project-workspace-settings-blueprint.png
project-workspace-setup-ready.png
project-workspace-setup-run-history.png
project-workspace-instances.png
project-workspace-terminal.png
project-workspace-channels.png
project-workspace-channel-settings.png
project-workspace-memory-tool.png
```

The staging step creates a reusable screenshot Project, attaches one channel to
it, creates one attachable channel, writes a file through the channel workspace
API, seeds a Blueprint-created Project with secret bindings, runs repo plus
setup-command preparation for `https://github.com/mtotho/spindrel.git`, and
seeds a fresh Project instance, and seeds a memory-tool turn. Inspect all twelve images before closing out: the
bundle intentionally checks Project admin surfaces, Blueprint management,
Project setup commands and run history, Project runtime-env readiness, fresh
Project instances, Project settings, and the channel transcript.

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
ssh spindrel-bot 'cd /opt/thoth-server && \
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
  --api-url http://10.10.30.208:8000 \
  --ui-url http://10.10.30.208:8000 \
  --browser-url http://10.10.30.208:8000 \
  --output-dir docs/images
```

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
```

When Playwright runs in the shared Docker browser runtime, use the same
container-IP pattern documented in `scripts/screenshots/README.md`, replacing
`scripts.screenshots.harness_live` with
`scripts.screenshots.spindrel_plan_live`.
