---
name: spindrel-visual-feedback-loop
description: Run Spindrel browser screenshot scenarios as a tight UI feedback loop and documentation artifact workflow. Use when verifying Spatial Canvas, Starboard, Map Brief, mobile hub, or other visual UI changes; when the user asks whether screenshots were checked; when adding or updating screenshot scenarios; when turning e2e captures into docs images; or when a UI pass needs visual evidence beyond typechecks and unit tests.
---

# Spindrel Visual Feedback Loop

Use this skill to make UI work visible before calling it done. Passing
typechecks or DOM assertions is not enough for canvas, Starboard, hub, or mobile
UX changes. Run the browser scenario, capture screenshots, inspect the images,
then record what changed and what still looks wrong.

## Start Here

1. Work from the repository root.
2. Read `CLAUDE.md`, `docs/guides/ui-design.md`, and the feature guide for the
   surface under review. For Spatial Canvas work, read
   `docs/guides/spatial-canvas.md`.
3. Check `git status --short --untracked-files=all` before running captures.
   Screenshot captures intentionally update docs images; unrelated dirty files
   must be left alone.
4. Read `docs/guides/visual-feedback-loop.md` for the current command sequence
   and scenario conventions.

## Spatial Canvas Loop

Use the e2e screenshot target configured by `scripts/screenshots/.env` as the
canonical artifact path.

```bash
python -m scripts.screenshots stage --only spatial-checks
python -m scripts.screenshots capture --only spatial-checks
python -m scripts.screenshots check
```

Expected documentation artifacts:

```text
docs/images/spatial-check-map-brief-selection.png
docs/images/spatial-check-jump-starboard-framing.png
docs/images/spatial-check-attention-badge.png
docs/images/spatial-check-hover-suppression.png
docs/images/spatial-check-overview-hover-calm.png
docs/images/spatial-check-cluster-focus-calm.png
docs/images/spatial-check-cluster-doubleclick-focus.png
docs/images/spatial-check-density-smoke.png
```

After capture, inspect the images. If visual inspection is not possible in the
current environment, say that explicitly and do not imply the visual pass was
completed.

## Channel Quick Automations Loop

Use this target when changing Channel Settings -> Automation -> Tasks quick
automation presets or the preset review drawer.

```bash
python -m scripts.screenshots stage --only channel-quick-automations
python -m scripts.screenshots capture --only channel-quick-automations
python -m scripts.screenshots check
```

Expected documentation artifacts:

```text
docs/images/channel-quick-automations.png
docs/images/channel-quick-automation-drawer.png
docs/images/channel-quick-automation-drawer-mobile.png
```

Inspect the preset surface and both drawer captures. The scenario opens the
drawer only; it must not create a scheduled task during capture.

## Channel Widget Usefulness Loop

Use this target when changing the channel dashboard widget review strip,
usefulness drawer, or Channel Settings -> Dashboard usefulness summary.

```bash
python -m scripts.screenshots stage --only channel-widget-usefulness
python -m scripts.screenshots capture --only channel-widget-usefulness
python -m scripts.screenshots check
```

Expected documentation artifacts:

```text
docs/images/channel-widget-usefulness-dashboard.png
docs/images/channel-widget-usefulness-drawer.png
docs/images/channel-widget-usefulness-settings.png
```

Inspect the strip, drawer, and settings summary. The staged dashboard should
show real duplicate/visibility pin state. Capture uses a narrow browser shim
for the read-only assessment endpoint when the shared e2e API lags the UI
branch; it must not create or mutate widgets during capture.

## Project Workspace Loop

Use this target when changing Project workspace pages, Project Blueprints,
channel Project bindings, or Project-rooted file/terminal behavior.

```bash
python -m scripts.screenshots stage --only project-workspace
python -m scripts.screenshots capture --only project-workspace
python -m scripts.screenshots check
```

Expected documentation artifacts:

```text
docs/images/project-workspace-list.png
docs/images/project-workspace-detail.png
docs/images/project-workspace-blueprints.png
docs/images/project-workspace-blueprint-editor.png
docs/images/project-workspace-settings-blueprint.png
docs/images/project-workspace-terminal.png
docs/images/project-workspace-channels.png
docs/images/project-workspace-channel-settings.png
docs/images/project-workspace-memory-tool.png
```

Inspect all nine images before closing out. The bundle checks Project admin
surfaces, Blueprint management, applied Blueprint settings, channel settings,
Project-rooted file/terminal behavior, and the memory-tool transcript envelope.

## Widget Authoring Runtime Loop

Use this loop when changing the tool-widget package editor or validating draft
YAML/Python widgets. Run the Templates tab **Full Check** action, or ask a bot
to call `check_widget_authoring(..., include_runtime=true,
include_screenshot=true)`. The check renders the draft envelope in the real
widget host via Playwright and returns browser-smoke phases plus an optional PNG
artifact for visual inspection. It is runtime feedback for drafts, not a
checked-in docs image bundle.

## Adding A Scenario

Add or adjust screenshot specs in `scripts/screenshots/capture/specs.py` when a
UI invariant should become durable.

Good screenshot scenarios:

- Stage state through `scripts/screenshots/stage/scenarios/` or existing seeded
  e2e data, not by hand-editing live data.
- Assert user-visible behavior: selected object visible, Starboard framing,
  hover suppression, cluster zoom threshold, cue marker presence.
- Save output under `docs/images/` so the same run serves as regression check
  and documentation artifact.
- Avoid brittle implementation assertions unless they protect an explicit UX
  anti-pattern, such as side-stripe chrome or duplicate selected labels.

## Completion Standard

A UI pass using this skill is not complete until the final response or session
log states:

- which screenshot bundle ran;
- whether capture succeeded;
- which artifact files changed;
- what the screenshots visibly confirm;
- any visual issues that remain.

For UI code changes, also run:

```bash
cd ui && npx tsc --noEmit --pretty false
```

Run focused unit tests for any screenshot helper or UI logic touched. Use
`git diff --check` before finishing.
