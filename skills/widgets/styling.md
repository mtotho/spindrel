---
name: Widget styling — entry point
description: Routing skill for widget styling — the `sd-*` vocabulary every iframe auto-inherits. Full reference (variables, utility/component classes, button contract, `window.spindrel.theme`, dark mode, cookbook) lives at `get_doc("reference/widgets/styling")`.
triggers: sd-card, sd-btn, sd-chip, sd-stack, sd-grid, widget CSS, widget styling, design tokens, widget dark mode, widget theme, spindrel.theme, sd-* vocabulary, CSS variables widget, --sd-accent, --sd-surface
category: core
---

# Widget styling — entry point

Every widget iframe auto-inherits the app's design language: tokens (`var(--sd-*)`) and component classes (`sd-card`, `sd-btn`, `sd-chip`, `sd-stack`, `sd-tile`, `sd-row`, `sd-input`, …). **Use these instead of inline hex or bespoke CSS.** Widgets that lean on the vocabulary look like part of the app, stay correct in dark mode, and survive theme changes.

**The full styling reference moved out of skills.** It's now a doc:

```
get_doc("reference/widgets/styling")
```

The reference covers: CSS variable palette, the full utility/component class table, the button contract, `window.spindrel.theme` for SVG/canvas widgets, dark mode propagation, the do/don't anti-pattern list, panel guidance, and the copy-paste component cookbook (checkbox, radio/switch, input group, list rows, empty state, tags, icons, motion, loading state).

## Non-negotiable rules

These bite widget authors most. The full *why* is in the doc; the *what* lives here so it stays resident:

- **No inline hex.** Use `var(--sd-*)` tokens or `sd-*` classes.
- **Low chrome.** Spacing and tonal steps separate regions — not borders, not shadows.
- **Never `border + bg-color + shadow` on one element.** Pick at most one.
- **Filled accent buttons (`sd-btn-primary`) are reserved for one final-commit moment per screen.** Routine row actions ("Refresh", "Connect", "Retry") use `sd-btn` (default ghost) or `sd-btn-accent` (ghost tinted primary). Filled-blue CTAs on every row are the Bootstrap anti-pattern.
- **Don't double-chrome.** The host already owns the outer tile shell. Start flat with `sd-stack` / `sd-section`; add `sd-card` only where grouping clearly improves the widget.
- **`docs/guides/ui-design.md` wins** when the vocabulary disagrees with it; open an issue so the vocabulary catches up.

## Quick mapping

| You want… | Reach for |
|---|---|
| Vertical / horizontal layout | `sd-stack`, `sd-stack-sm`, `sd-hstack`, `sd-hstack-between` |
| Auto-fit grid | `sd-grid`, `sd-grid-2`, `sd-tiles` |
| Base panel | `sd-card` (with `sd-card-header` / `-body` / `-actions`) |
| Inset sub-panel | `sd-tile`, `sd-subcard`, or `sd-card--flat` |
| Buttons | `sd-btn` (ghost) → `sd-btn-accent` (primary affordance) → `sd-btn-primary` (final-commit only) |
| Chips / tags / status | `sd-chip-*`, `sd-tag--*` |
| List rows with hover actions | `sd-list--divided` + `sd-row` + `sd-row__actions` |
| Form controls | `sd-input`, `sd-select`, `sd-textarea`, `sd-check`, `sd-radio`, `sd-switch` |
| Programmatic colors (SVG/canvas) | `window.spindrel.theme.accent` etc., not hex |

## See also

- `get_doc("reference/widgets/styling")` — full reference + component cookbook
- skill `widgets/sdk` (and `get_doc("reference/widgets/sdk")`) — `window.spindrel.theme`, `onTheme`, `ui.chart`, `ui.icon`
- skill `widgets/html` — bundle layout, sandbox, CSP, auth
- skill `widgets/errors` — theme-related rendering bugs
- `docs/guides/ui-design.md` — canonical visual spec the app is polished against
