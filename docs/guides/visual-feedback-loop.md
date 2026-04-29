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
