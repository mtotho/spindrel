# Spindrel Design Context

This file exists so design-focused repo agents can load project context quickly. The canonical Spindrel design system lives in:

- `docs/guides/ui-design.md`
- `docs/guides/ui-components.md`

## Design Direction

Spindrel is product UI, not brand UI. Design should serve repeated operational work: scanning, triage, configuration, review, session navigation, and evidence inspection.

The north star is low chrome with clear focal points. Use spacing, typography, neutral surface steps, and a sparse emphasis token to create hierarchy. Avoid both extremes: do not make every section a card, and do not make every section so quiet that the page becomes visually flat.

## Core Rules

- Use Tailwind classes backed by `ui/global.css` and `ui/tailwind.config.cjs` tokens. Do not add component-local hex colors.
- Use `accent` for primary interaction, selected/current state, and focus. Use semantic colors only for real success, warning, danger, or info state.
- Use `emphasis` only as a non-semantic scan marker for primary anchors, such as a small icon well, short top rail, or dot.
- Keep app pages aligned with the shell rhythm. Do not center broad operational layouts into wide-screen dead zones unless the page is prose or deliberately narrow.
- Prefer rows, header rails, anchor sections, meters, pills, and inline status bands over repeated equal cards.
- Use shared controls from `docs/guides/ui-components.md` before creating local controls.

## Visual QA

For meaningful visual work, capture and inspect the matching screenshot bundle from `docs/guides/visual-feedback-loop.md`. Typecheck alone is not enough for layout, hierarchy, or responsive behavior.
