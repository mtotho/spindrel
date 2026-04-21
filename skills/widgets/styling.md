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
| Form controls | `sd-input`, `sd-select`, `sd-textarea`, `sd-input-group` |
| Styled controls | `sd-check` (checkbox), `sd-radio`, `sd-switch` |
| Rows & lists | `sd-list`, `sd-list--divided`, `sd-row`, `sd-row__title`, `sd-row__meta`, `sd-row__actions` |
| Section grouping | `sd-section`, `sd-section__header`, `sd-section__title`, `sd-inline` |
| Status chip | `sd-chip`, `sd-chip-accent/success/warning/danger/purple` |
| Tag (pill) | `sd-tag`, `sd-tag--accent/success/warning/danger/purple`, `sd-tag__remove` |
| Icons | `sd-icon`, `sd-icon--sm/lg/xl`, `sd-icon--muted/dim/accent/success/danger/warning` |
| Keyboard hint | `sd-kbd` |
| Menu / Tooltip / Modal | `sd-menu`, `sd-menu-item`, `sd-menu-item--danger`, `sd-menu-divider`, `sd-tooltip`, `sd-modal` (built by `spindrel.ui.menu/tooltip/confirm`) |
| Progress bar | `sd-progress` (+ `style="--p: 60"` for 60%) + color variants |
| Feedback | `sd-error`, `sd-empty`, `sd-empty__icon/title/subtitle/cta`, `sd-skeleton`, `sd-spinner`, `sd-divider` |
| State | `sd-is-selected`, `sd-is-disabled`, `sd-is-loading` (shows spinner overlay) |
| Motion | `sd-anim-fade-in`, `sd-anim-pop` (respects `prefers-reduced-motion`) |

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

## Component cookbook (sd-* v2)

Copy-paste starting points. Each snippet uses only preamble-injected CSS and
the icon sprite — no `<style>` block required.

### Styled checkbox (`sd-check`)

```html
<label class="sd-check">
  <input type="checkbox" />
  <span class="sd-check__box">
    <svg class="sd-check__mark" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>
  </span>
  <span class="sd-check__label">Mark done</span>
</label>
```

The native `<input>` stays in the label so form semantics work; the
styled box + animated check mark are siblings. Checked state flips on the
real input — read `.checked` / listen to `change` events as usual.

### Radio and switch

```html
<label class="sd-radio">
  <input type="radio" name="scope" value="channel" checked />
  <span class="sd-radio__dot"></span>
  <span>Channel</span>
</label>

<label class="sd-switch">
  <input type="checkbox" />
  <span class="sd-switch__track"><span class="sd-switch__thumb"></span></span>
  <span class="sd-switch__label">Enable notifications</span>
</label>
```

### Input group (leading icon + trailing action)

```html
<form class="sd-input-group">
  <span class="sd-input-group__icon">
    <svg class="sd-icon sd-icon--sm"><use href="#sd-icon-search"/></svg>
  </span>
  <input class="sd-input" placeholder="Search…" />
  <button type="submit" class="sd-btn sd-btn-primary sd-input-group__action">Go</button>
</form>
```

Hook `spindrel.ui.autogrow(textarea)` on a `<textarea class="sd-textarea">` to
make it grow to fit content (caps at 240px by default).

### List of rows with hover actions

```html
<div class="sd-list sd-list--divided">
  <div class="sd-row">
    <svg class="sd-icon"><use href="#sd-icon-file"/></svg>
    <span class="sd-row__title">Quarterly report</span>
    <span class="sd-row__meta">12m ago</span>
    <span class="sd-row__actions">
      <button class="sd-btn sd-btn-subtle" aria-label="Edit">
        <svg class="sd-icon sd-icon--sm"><use href="#sd-icon-pencil"/></svg>
      </button>
      <button class="sd-btn sd-btn-subtle" aria-label="Delete">
        <svg class="sd-icon sd-icon--sm"><use href="#sd-icon-trash"/></svg>
      </button>
    </span>
  </div>
  <!-- more .sd-row children … -->
</div>
```

Actions auto-hide until the row is hovered or focus-within. Add
`.sd-row--done` to apply line-through + muted text, or `.sd-is-selected` /
`aria-selected="true"` to highlight.

### Empty state

```html
<div class="sd-empty">
  <svg class="sd-icon sd-icon--xl sd-empty__icon"><use href="#sd-icon-inbox"/></svg>
  <div class="sd-empty__title">No messages</div>
  <div class="sd-empty__subtitle">New items will appear here as they arrive.</div>
  <div class="sd-empty__cta"><button class="sd-btn sd-btn-primary">Compose</button></div>
</div>
```

### Tag (removable)

```html
<span class="sd-tag sd-tag--accent">
  urgent
  <button class="sd-tag__remove" aria-label="Remove tag">×</button>
</span>
```

### Icons

Every widget iframe ships the Lucide subset as an inline SVG sprite at the
top of `<body>`. Reference by id:

```html
<svg class="sd-icon"><use href="#sd-icon-check"/></svg>
<svg class="sd-icon sd-icon--lg sd-icon--accent"><use href="#sd-icon-bell"/></svg>
```

Or render from JS:

```js
el.innerHTML = window.spindrel.ui.icon("trash", { size: "sm", tone: "danger" });
```

Available names are listed in `WIDGET_ICON_NAMES` in
`ui/src/components/chat/renderers/widgetIcons.ts` — common picks:
`check`, `x`, `plus`, `minus`, `trash`, `pencil`, `search`, `filter`,
`chevron-{up,down,left,right}`, `arrow-{up,down,left,right}`,
`more-{horizontal,vertical}`, `calendar`, `clock`, `bell`, `user`, `users`,
`mail`, `file`, `folder`, `link`, `external-link`, `settings`, `eye`,
`eye-off`, `refresh`, `play`, `pause`, `star`, `heart`, `tag`, `pin`,
`check-circle`, `alert-circle`, `info`, `alert-triangle`, `loader`,
`list`, `grid`, `home`, `inbox`, `send`, `download`, `upload`, `sun`,
`moon`, `copy`, `save`, `bookmark`, `flag`, `lock`, `unlock`, `zap`,
`chart-bar`.

Unknown names produce a warning via `spindrel.log.warn` and render empty.

### Motion

Apply `.sd-anim-fade-in` to newly inserted nodes and `.sd-anim-pop` to
popovers. Both respect `prefers-reduced-motion: reduce` — animation is
automatically disabled for users who opt out.

### Loading state

```html
<button class="sd-btn sd-btn-primary sd-is-loading">Save</button>
```

Hides the label and shows a centered spinner; blocks clicks.

## See also

- `widgets/sdk.md` — `window.spindrel.theme`, `onTheme`, `ui.chart`, `ui.icon`, `ui.autogrow`, `ui.menu`, `ui.tooltip`, `ui.confirm`
- `widgets/html.md` — sandbox, CSP, auth model
- `widgets/errors.md` — theme-related rendering bugs
