---
name: spindrel-ui-operator
description: "Use when editing Spindrel frontend source: React routes, shared components, channel surfaces, Mission Control, Spatial Canvas, CSS, layout behavior, and UI tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel UI Operator

This is a repo-dev skill for agents editing Spindrel source. It is not a Spindrel runtime skill and must not be imported into app skill tables.

## Start Here

1. Read `CLAUDE.md`.
2. Read `docs/guides/ui-design.md` and `docs/guides/ui-components.md`.
3. For visual work, also use `.agents/skills/spindrel-visual-feedback-loop`.
4. Check `git status --short` before editing UI or docs image artifacts.

## Do

- Match existing app layout density, component patterns, and design tokens.
- Use shared components before adding local one-off controls.
- Keep operational surfaces scannable; avoid marketing-page structure for app
  workflows.
- Make state obvious through actual data, not explanatory in-app copy.
- Run `cd ui && npx tsc --noEmit --pretty false` after UI changes.

## Avoid

- Do not start a new Vite server or claim a new port unless explicitly asked.
- Do not add UI cards inside UI cards.
- Do not reintroduce imperative chat scroll anchoring.
- Do not create a runtime skill importer or app skill mutation from repo
  `.agents` content.

## Completion Standard

For logic-only UI edits, run the focused UI test plus typecheck. For visual
layout edits, capture and inspect the matching screenshot bundle before calling
the pass complete.
