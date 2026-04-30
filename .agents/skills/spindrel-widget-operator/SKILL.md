---
name: spindrel-widget-operator
description: "Use when editing Spindrel widgets and dashboards: widget contracts, package loading, pins, iframe SDK, native widgets, authoring checks, dashboard surfaces, and widget tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Widget Operator

This is a repo-dev skill for agents editing Spindrel source. It is not a Spindrel runtime skill and must not be imported into app skill tables.

## Start Here

1. Read `CLAUDE.md`.
2. Read `docs/guides/widget-system.md`.
3. For dashboard surfaces, read `docs/guides/widget-dashboards.md`.
4. For HTML widgets or authoring work, read `docs/guides/html-widgets.md` and
   `docs/guides/dev-panel.md`.

## Do

- Preserve widget envelope contracts, origin rules, and host policy.
- Keep generated or user-authored widget content separate from trusted app UI.
- Add focused tests for manifest loading, pin behavior, SDK handlers, or
  authoring checks when those paths change.
- Use runtime screenshot or authoring checks when the issue is renderability,
  not just data shape.
- Keep widget usefulness and agency receipts meaningful to agents and humans.

## Avoid

- Do not special-case a widget by bypassing the package/manifest contract.
- Do not weaken iframe, auth, or action authorization boundaries.
- Do not import repo-dev `.agents` skills into widget packages or app skills.
- Do not mutate dashboard state during screenshot capture unless the scenario
  explicitly stages that mutation.

## Completion Standard

Run the focused widget unit slice for the contract touched. Run UI typecheck for
dashboard UI edits and the visual feedback loop for layout-sensitive changes.
