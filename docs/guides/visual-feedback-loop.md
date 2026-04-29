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

## Harness Parity Run

External harness parity screenshots use real live harness sessions rather than
synthetic screenshot staging. They are documented in
`agent-harnesses.md` and written to `docs/images/harness-*.png`.
Run the project-build tier first when refreshing terminal/native tool-output
fixtures, because those screenshots are captured from the latest live Codex and
Claude project-build sessions.

```bash
SPINDREL_API_KEY=... \
python -m scripts.screenshots.harness_live \
  --api-url http://10.10.30.208:8000 \
  --ui-url http://10.10.30.208:8000 \
  --browser-url http://10.10.30.208:8000 \
  --output-dir docs/images
```

Use a local dev UI in `--ui-url` when validating a UI patch before deploy, and
use the deployed UI after deploy. When Playwright runs in the shared Docker
browser runtime, `--browser-url` must be reachable from that browser container;
see `scripts/screenshots/README.md` for the main-host Docker command.
Question-card captures require a pending harness question and
`HARNESS_VISUAL_QUESTION_SESSION_ID`; the normal bridge, terminal write,
`/style` command-picker, and usage-log captures rediscover the latest E2E
sessions from the configured harness channels.

## Native Spindrel Plan Mode Run

Native plan-mode screenshots use real live Spindrel sessions rather than
synthetic screenshot staging. First run the live diagnostics to create fresh
detached sessions on the dedicated native-plan E2E channel:

```bash
./scripts/run_spindrel_plan_live.sh --tier replay
```

The runner writes the latest session ids to
`/tmp/spindrel-plan-parity/spindrel-plan-sessions.json`. Capture the matching
UI artifacts with:

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
spindrel-plan-answered-questions-dark.png
spindrel-plan-progress-executing-mobile-dark.png
```

When Playwright runs in the shared Docker browser runtime, use the same
container-IP pattern documented in `scripts/screenshots/README.md`, replacing
`scripts.screenshots.harness_live` with
`scripts.screenshots.spindrel_plan_live`.
