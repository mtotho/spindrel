---
name: Chip Widgets
description: Authoring widgets for the 180×32 channel-header chip band — size constraints, `window.spindrel.layout` branching, `layout_hints` manifest field, and the three reference chips shipped in-repo
triggers: chip widget, chip, channel header, header chip, 180x32, 180×32, compact widget, header band, chip zone, layout hints, preferred_zone, chip toggle, chip status, chip metric
category: core
---

# Chip widgets

A **chip** is the compact 180×32 widget surface that renders inline in the channel header, to the left of the pins popover. Chips exist alongside the rail, dock, and grid zones on the same channel dashboard — the zone is stored on each pin, so any widget *can* land as a chip, but only chip-sized widgets render well there. This doc covers how to author a widget that fits that band.

## Size constraints

- **Height: 32 px.** Non-negotiable. Anything taller gets clipped by the header band.
- **Width: flexible.** Rendered width is the pin's grid column span, with realistic values between ~120 px and ~280 px. Design for ellipsis, not wrapping.
- **No titles, no chrome.** Chips are chromeless — there is no header row, no edit button, no drag handle at rest. Author the body only; the host manages the outer chip shell.
- **Single line.** A label + value + optional small affordance (dot / delta / switch) is the grammar.

## Branching on zone — `window.spindrel.layout`

Every interactive HTML widget sees one of four strings on `window.spindrel.layout`:

- `"chip"` — rendered in the channel header band (height-locked 32 px)
- `"rail"` — left OmniPanel widgets column
- `"dock"` — right chat dock
- `"grid"` — dashboard grid tile, or inline chat render

The value is set by the host before your script runs. Branch on it to render a compact variant when you're in a chip and a fuller variant otherwise:

```html
<div id="my-root"></div>
<script>
  const sp = window.spindrel;
  const root = document.getElementById("my-root");
  root.dataset.layout = (sp && sp.layout) || "grid";
  // …
</script>

<style>
  #my-root[data-layout="chip"] { height: 32px; padding: 0 10px; }
  #my-root[data-layout="chip"] .detail { display: none; }
  #my-root:not([data-layout="chip"]) { padding: 10px 12px; }
</style>
```

Reflecting `spindrel.layout` into a `data-layout` attribute lets the stylesheet do the branching without extra JS. That is the pattern used by the three reference chips.

## `layout_hints` in `widget.yaml`

Bundles declare advisory placement hints so the dashboard editor can suggest the right zone and clamp resize:

```yaml
name: My Chip
version: 1.0.0
description: …
layout_hints:
  preferred_zone: chip         # chip | rail | dock | grid
  min_cells:
    w: 2
    h: 1
  max_cells:
    w: 4
    h: 1
```

Field notes:

- `preferred_zone` is advisory — the editor can suggest "this belongs in the chip row" but won't refuse a drop elsewhere.
- `min_cells` / `max_cells` clamp the resize handles. Chips always want `h: 1`.
- Omit `layout_hints` entirely for widgets that belong in the grid — that's the default mental model.

## Common pitfalls

- **Authoring a grid widget and hoping it renders as a chip** — the grid widget's padding + title row + card chrome will blow the 32 px band. Branch on `spindrel.layout === "chip"` and strip those explicitly.
- **Polling in the chip** — chips are always visible, so a tight poll loop hammers the server. Prefer `spindrel.stream` subscriptions or `@on_cron` handlers (see `widgets/handlers.md`).
- **Long labels** — chip widths vary with pin column span; always set `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` on the label.
- **State persistence without `dashboardPinId`** — chip pins are dashboard pins, so `spindrel.state.save` works. Inline chat renders (no pin) save to an ephemeral per-iframe store that doesn't survive reload; that's fine for chat ephemera.

## Dry-run first

For chip widgets especially — the size constraint is tight and CSS mistakes don't show up until render — use `preview_widget(library_ref=..., html=..., path=...)` before emitting. It returns structured `{ok, envelope, errors}` so you can catch CSP violations, missing manifest fields, and malformed `layout_hints` in the same turn you author the bundle. See `widgets/html.md#dry-run-first` for the call shape.

## See also

- `widgets/html.md` — overall HTML-widget authoring (bundle layout, path grammar, CSP)
- `widgets/sdk.md` — the `window.spindrel` surface (`state`, `stream`, `callTool`)
- `widgets/manifest.md` — full `widget.yaml` schema
- `widgets/errors.md` — symptom-keyed fix table
