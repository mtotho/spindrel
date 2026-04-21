---
name: Widget styling — sd-* vocabulary, theme, dark mode
description: The `sd-*` CSS design vocabulary every widget iframe auto-inherits. Covers the CSS variable palette, utility + component classes (cards, buttons, chips, grids, forms), `window.spindrel.theme` for SVG/canvas widgets, dark-mode propagation, and the do/don't anti-pattern list (no inline hex, no hand-rolled card components).
triggers: sd-card, sd-btn, sd-chip, sd-stack, sd-grid, widget CSS, widget styling, design tokens, widget dark mode, widget theme, spindrel.theme, sd-* vocabulary, CSS variables widget, --sd-accent, --sd-surface
category: core
---

# Widget styling — use the `sd-*` vocabulary

Every widget iframe auto-inherits the app's design language: colors, spacing, typography, and component classes. **Use these instead of inline hex colors or bespoke CSS.** Widgets that lean on the vocabulary look like part of the app, stay correct in both light and dark mode, and survive future theme changes.

## CSS variables

Every token from the host theme is available as a CSS variable:

```
--sd-surface              --sd-text           --sd-accent          --sd-success
--sd-surface-raised       --sd-text-muted     --sd-accent-hover    --sd-warning
--sd-surface-overlay      --sd-text-dim       --sd-accent-muted    --sd-danger
--sd-surface-border                           --sd-accent-subtle   --sd-purple
                                              --sd-accent-border
```

Plus subtle/border variants for status colors (`--sd-success-subtle`, `--sd-danger-border`, etc.), overlay tints (`--sd-overlay-light`, `--sd-overlay-border`), spacing (`--sd-gap-xs/sm/md/lg`, `--sd-pad-sm/md/lg`), radii (`--sd-radius-sm/md/lg`), and typography (`--sd-font-sans`, `--sd-font-mono`, `--sd-font-size`).

```css
.my-chart-bar { fill: var(--sd-accent); }
.my-error    { color: var(--sd-danger); }
```

## Utility / component classes

Prefer these over hand-rolled CSS:

| Purpose | Class |
|---|---|
| Vertical layout | `sd-stack`, `sd-stack-sm`, `sd-stack-lg` |
| Horizontal layout | `sd-hstack`, `sd-hstack-sm`, `sd-hstack-between` |
| Responsive auto-fit grid | `sd-grid`, `sd-grid-2`, `sd-tiles` (smaller tiles) |
| Card surface | `sd-card`, `sd-card-header`, `sd-card-body`, `sd-card-actions` |
| Framed media region | `sd-frame`, `sd-frame-overlay` (centered status text) |
| Bordered tile | `sd-tile` |
| Text | `sd-title`, `sd-subtitle`, `sd-meta`, `sd-muted`, `sd-dim`, `sd-mono` |
| Button | `sd-btn`, `sd-btn-primary`, `sd-btn-subtle`, `sd-btn-danger` |
| Form controls | `sd-input`, `sd-select`, `sd-textarea` |
| Status chip | `sd-chip`, `sd-chip-accent/success/warning/danger/purple` |
| Progress bar | `sd-progress` (+ `style="--p: 60"` for 60%) + color variants |
| Feedback | `sd-error`, `sd-empty`, `sd-skeleton`, `sd-spinner`, `sd-divider` |

Toggle buttons work via `aria-pressed="true"` — the base `.sd-btn` handles the pressed styling:

```html
<div class="sd-card">
  <header class="sd-card-header">
    <h3 class="sd-title">Driveway</h3>
    <span class="sd-meta">Updated 30s ago</span>
  </header>
  <div class="sd-frame"><img src="…" /></div>
  <div class="sd-card-actions">
    <button class="sd-btn" aria-pressed="true">Bounding boxes</button>
    <button class="sd-btn sd-btn-primary">Refresh</button>
  </div>
</div>
```

## `window.spindrel.theme` (for SVG / canvas widgets)

When you're drawing programmatically — SVG chart fills, canvas strokes — use `window.spindrel.theme` instead of hard-coded hex:

```js
const accent = window.spindrel.theme.accent;
const isDark = window.spindrel.theme.isDark;
svg.innerHTML = `<rect fill="${accent}" .../>`;
```

Available keys: `isDark`, `surface`, `surfaceRaised`, `surfaceOverlay`, `surfaceBorder`, `text`, `textMuted`, `textDim`, `accent`, `accentHover`, `accentMuted`, `success`, `warning`, `danger`, `purple`.

## Dark mode

The iframe receives `<html class="dark">` when the app is in dark mode. CSS variables adjust automatically — you usually don't need to branch. For JS that needs to decide (e.g., chart background), check `window.spindrel.theme.isDark`.

Subscribe to mode switches live:

```js
window.spindrel.onTheme((theme) => {
  redraw(theme.accent, theme.isDark);
});
```

See `widgets/sdk.md#reacting-to-live-updates` for the full event surface.

## Do / Don't

| Don't | Do | Why |
|---|---|---|
| `style="color: #1f2937; background: #f9fafb"` | `style="color: var(--sd-text); background: var(--sd-surface-raised)"` or `class="sd-card"` | Hex colors drift from the app theme and break dark mode silently. |
| `style="font-family: sans-serif"` | Inherit body default (`var(--sd-font-sans)`) | The theme already sets a system font matching the app. |
| Custom card component from scratch | `class="sd-card"` + `sd-card-header` + `sd-card-body` | Consistency across widgets. |
| `<button style="padding: 3px 8px; border: 1px solid #e5e7eb; ...">` | `<button class="sd-btn">` | Fewer lines, on-brand, dark-mode correct. |
| `border-bottom: 1px solid #e5e7eb` between bars | Spacing + `sd-card` separation | Gratuitous borders look like low-polish admin chrome. |
| Hard-coded success green (`#16a34a`) | `class="sd-chip-success"` or `var(--sd-success)` | Same color in one place; updates ripple. |

## Layout & sizing

- The iframe auto-resizes to content height (up to 800px). Taller content scrolls inside the iframe.
- Cards fill available width on the dashboard grid. Let the user resize from the dashboard; don't set fixed widths.
- The theme stylesheet handles reset (box-sizing, margin/padding), scrollbar styling, table borders, code blocks, links. You rarely need a `<style>` block — reach for `sd-*` classes and `var(--sd-*)` first.

## `ui.chart` theming

`window.spindrel.ui.chart(el, data, opts)` defaults to `spindrel.theme.accent` for the line/fill color and uses the iframe's current theme for background. Pass an explicit `color:` if you want a specific token (e.g. `var(--sd-danger)` for error charts); the renderer reads from live CSS so token updates cascade.

See `widgets/sdk.md#uichart---sparkline--line--bar--area` for the chart API.

## See also

- `widgets/sdk.md` — `window.spindrel.theme`, `onTheme`, `ui.chart`
- `widgets/html.md` — sandbox, CSP, auth model
- `widgets/errors.md` — theme-related rendering bugs
