---
name: spindrel-ui-operator
description: "Use when editing Spindrel frontend source: React routes, shared components, channel surfaces, Mission Control, Spatial Canvas, CSS, layout behavior, and UI tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel UI Operator

This is a repo-dev skill for any agent editing this checkout: local CLI on the
operator's box, in-app Spindrel agent on the server, or a Project coding run.
It is not a Spindrel runtime skill and must not be imported into app skill
tables.

## Start Here

1. Read `CLAUDE.md`.
2. Read `PRODUCT.md`, `DESIGN.md`, `docs/guides/ui-design.md`, and
   `docs/guides/ui-components.md`.
3. For visual work, also use `.agents/skills/spindrel-visual-feedback-loop`.
4. Check `git status --short` before editing UI or docs image artifacts.

## UI Preflight

Before changing a visual surface, name these in your working notes:

- **Surface register:** product UI. Do not use marketing-page structure for app
  workflows.
- **Surface archetype:** command, app/content, or control surface. Use the
  matching rules in `docs/guides/ui-design.md`.
- **Primary focal point:** the one place the user should look first.
- **Emphasis level:** quiet section, header rail, anchor section, or status
  band. Most sections stay quiet; broad pages get at most one primary anchor
  and two secondary anchors above the fold.
- **Chrome budget:** pick one separator per region: spacing, tonal step, or one
  neutral border.
- **Proof path:** typecheck plus focused tests; add screenshots for visual
  layout, hierarchy, or responsive work.

## Triage primitives

| Need | Primitive |
|---|---|
| Shared dropdown / settings row / prompt editor | `docs/guides/ui-components.md` |
| Design tokens | `ui/global.css` + `ui/tailwind.config.cjs` |
| Surface archetype rules | `docs/guides/ui-design.md` (command vs app/content vs control) |
| Find a component's call sites | `rg -n "<ComponentName" ui/` |
| Typecheck after a change | `cd ui && npx tsc --noEmit --pretty false` |
| 1000-line UI file | split into siblings before editing further (per `AGENTS.md`) |

## Named patterns to grep for

- **Imperative chat scroll anchoring** (`scrollTop = scrollHeight`, `ResizeObserver` pin logic, image-load races) — never reintroduce. The chat uses `flex-direction: column-reverse` for native bottom-pinning. Per `AGENTS.md`, this is non-negotiable.
- **Component-local color literals** (`#hex`, `rgb()`, `text-blue-500`) — must be tokens. Add to `ui/global.css` + `ui/tailwind.config.cjs`, then consume via Tailwind classes.
- **Cards inside cards / repeated equal metric-card grids** — flag as a layout smell; one anchor section + compact rows usually scans faster.
- **Fixed-width content centered in wide-screen dead zones** — operational pages should align with the app shell rhythm, not marketing-page centering.

## Worked example: add an admin settings row

1. Use the canonical `SettingsRow` component (per `docs/guides/ui-components.md`) — do not build a one-off.
2. Tokens only — no inline colors.
3. State via the existing zustand/react-query patterns; don't add a new global store.
4. `cd ui && npx tsc --noEmit --pretty false`. If layout-sensitive, run the visual feedback loop and inspect screenshots.
5. Bump test for the changed component if behavior changed.

## Do

- Match existing app layout density, component patterns, and design tokens.
- Use shared components before adding local one-off controls.
- Keep operational surfaces scannable; avoid marketing-page structure for app
  workflows.
- Make state obvious through actual data, not explanatory in-app copy.
- Align broad operational pages with the app shell rhythm. Do not center them
  into wide-screen dead zones unless the surface is prose or intentionally
  narrow.
- Use the `emphasis` token only as a sparse non-semantic scan marker for
  primary anchors.
- Run `cd ui && npx tsc --noEmit --pretty false` after UI changes.
- For visual verification, reuse an already-running Vite/app server when one is
  available. If none is running and screenshots or browser checks are needed,
  start the required local dev server using the repo's normal workflow, choosing
  an open port if the default is occupied.

## Avoid

- Do not start duplicate Vite servers when an existing suitable server is
  already running; reuse it instead.
- Do not add UI cards inside UI cards.
- Do not create repeated equal metric-card grids when one anchor section plus
  compact rows would scan faster.
- Do not use side-stripe borders, gradient text, decorative glass, or filled
  blue buttons for routine row actions.
- Do not add component-local colors. Add tokens in `ui/global.css` and
  `ui/tailwind.config.cjs`, then consume them through Tailwind classes.
- Do not reintroduce imperative chat scroll anchoring.
- Do not create a runtime skill importer or app skill mutation from repo
  `.agents` content.

## Completion Standard

For logic-only UI edits, run the focused UI test plus typecheck. For visual
layout edits, capture and inspect the matching screenshot bundle before calling
the pass complete.
