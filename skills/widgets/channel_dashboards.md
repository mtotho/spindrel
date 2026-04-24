---
name: Widget Dashboards
id: widget_dashboards
description: How to read, propose, and modify widget dashboard layouts with describe_dashboard, pin_widget, move_pins, unpin_widget, promote_panel, demote_panel — zones (rail/header/dock/grid), chat view vs full dashboard, ASCII mockups, first-free-slot placement, panel mode
triggers: widget dashboard, dashboard layout, pin widget, unpin widget, move widget, rearrange dashboard, dashboard rail, dashboard dock, dashboard zones, chat widgets, header chip, dashboard panel, panel mode, describe dashboard, show me the dashboard, where is this pinned, change layout
category: widgets
---

# Widget Dashboards — Layout Tools

Every channel has a dashboard. Bots act as first-class collaborators on it: read what's pinned, propose layout changes via ASCII mockups, then execute those changes when the user says yes.

Six tools cover the full surface:

| Tool | Purpose |
|---|---|
| `describe_dashboard` | Read raw pin JSON + rendered ASCII preview |
| `pin_widget` | Pin a library widget (builtin / integration / channel) at a zone + slot |
| `move_pins` | Batch-update one or more pins' zone + `{x, y, w, h}` |
| `unpin_widget` | Remove a pin |
| `promote_panel` | Flip a pin into panel mode (fills the dashboard's main area) |
| `demote_panel` | Clear a pin's panel-mode flag |
| `set_dashboard_chrome` | Toggle dashboard-wide `borderless` / `hover_scrollbars` |

## The dashboard model

**Zones.** A channel dashboard is split into four named zones — three of which are visible alongside the chat column, one of which is dashboard-only.

| Zone | Where it lives | Visible in chat view? |
|---|---|---|
| `rail` | Left-side OmniPanel sidebar (1 col) | ✅ |
| `header` | Horizontal chip strip across the top | ✅ |
| `dock` | Right-side WidgetDock (1 col) | ✅ |
| `grid` | The main dashboard body (full 2D) | ❌ (only on `/widgets/channel/<uuid>`) |

Every pin carries a `zone` on its row and a `grid_layout: {x, y, w, h}` expressed in the zone's local coord space. `visible_in_chat` in the `describe_dashboard` response is the convenience flag: `True` iff `zone in {rail, header, dock}`.

**Presets.** A dashboard's `grid_config.preset` sets the column count for the grid and header zones:

| Preset | Grid cols | Header cols |
|---|---|---|
| `standard` (default) | 12 | 12 |
| `fine` | 24 | 24 |

Rail/dock are 1-col canvases regardless of preset — pins in them always have `x=0, w=1` and stack on `y`/`h`.

**Panel mode.** At most one pin per dashboard can be the *panel pin* (`is_main_panel: true`). When promoted, the dashboard switches to panel mode: the grid matrix is hidden on `/widgets/channel/<uuid>` and the panel pin fills the main area. Rail / header / dock are unaffected. Demoting the only panel pin reverts the dashboard to grid mode automatically.

## Dashboard slugs

- `channel:<uuid>` — the implicit per-channel dashboard. Lazy-created the first time a pin lands on it. **This is your default target** — every tool defaults `dashboard_key` to this when you're running in a channel.
- `default` — the built-in global dashboard.
- `my-board` — named user-created dashboards (global, shared across channels).

Only touch non-channel dashboards when the user explicitly references them ("pin it to my personal dashboard", "put it on the global dashboard"). Don't guess.

## Canonical flow

Most layout requests follow the same four-step dance:

1. **See** — call `describe_dashboard` first. Always. Don't propose changes against a dashboard you haven't inspected; pins may already exist in that zone, the preset may surprise you, panel mode may be active.
2. **Propose** — reply with the ASCII preview you'd like to end at, prefixed with "here's what I'm thinking". Quote the legend so pin IDs are visible.
3. **Wait** — do not execute without explicit user confirmation when the change moves or removes user-placed pins. Pinning a brand-new widget the user just asked for is fine to execute immediately.
4. **Execute** — chain `pin_widget` / `move_pins` / `unpin_widget` calls. Render the post-execution ASCII preview to confirm the result.

## Chat view vs full dashboard view

`describe_dashboard` renders both views by default. Know the difference:

- **Chat view** shows the user what they see *while chatting*: header strip on top, rail on left, dock on right, chat column in the middle. Grid-zone pins are invisible here.
- **Full dashboard view** is what the user sees on `/widgets/channel/<uuid>` — the same chrome plus the grid matrix in the middle.

When the user says "put it where I'll see it", pick a chat-visible zone (rail / header / dock). When they say "keep it on the dashboard" or "put it on the big page", grid is fine.

**`layout_mode` nuance.** A channel's `channel.config.layout_mode` may hide some chat-visible zones (e.g. `"rail-chat"` hides the header + dock; `"dashboard-only"` hides the whole chat surface). Don't pin to a zone the current layout mode hides without asking — the user won't see your widget until they switch modes. `describe_dashboard`'s raw response doesn't currently read `layout_mode`, so ask the user when in doubt.

## `pin_widget` — library widgets

Pins a file-backed widget from one of three catalogs:

- `source_kind="builtin"` — widgets that ship under `app/tools/local/widgets/` (e.g. `mc_kanban`, `mc_tasks`, `mc_timeline`).
- `source_kind="integration"` — widgets bundled by a specific integration under `integrations/<id>/widgets/`. Must pass `source_integration_id`.
- `source_kind="channel"` — widgets authored in the current channel's workspace (any `.html` with `window.spindrel.*` references).

`widget` matches against slug → path → name, case-insensitive.

### Placement

Pass `zone` + optional `x`, `y`, `w`, `h`. Omitted coords auto-place at the first-free-slot in the zone. Sensible defaults per zone if you also omit size:

| Zone | Default size |
|---|---|
| `grid` | 6×6 |
| `rail`, `dock` | 1×4 |
| `header` | 2×1 |

### Auth scope

`auth_scope="user"` (default) — the widget iframe runs as each viewer, using their credentials. Best for dashboards that display per-user data (inbox, calendar, personal tasks).

`auth_scope="bot"` — the widget iframe always runs as you (the emitting bot). Use when the widget needs data only your bot has access to (a private API key, a bot-scoped file), and the dashboard is shared with viewers who shouldn't need their own access.

### Duplicate refusal

`pin_widget` refuses to pin the same widget twice on the same dashboard (matched by `source_kind` + `source_integration_id` + `source_path`). Use `move_pins` instead if the widget already exists and you want to reposition it.

## `move_pins` — batch moves

Pass a list of `{pin_id, zone?, x?, y?, w?, h?}` objects. Omitted fields preserve the pin's current value. Everything commits in a single transaction — any validation failure rolls back the whole batch.

Common shapes:

- **Change zone only** (preserve size): `{pin_id, zone: "rail"}`. The pin moves to the rail and keeps its width/height; x/y fall back to the pin's current values (which may or may not be sensible in the new zone — pass them if you're moving between very different zones).
- **Resize only**: `{pin_id, w, h}`.
- **Relocate within a zone**: `{pin_id, x, y}`.

## `unpin_widget` — removal

Pass a `pin_id`. Unpinning preserves the widget's SQLite data (if any) by default; pass `delete_bundle_data=true` to also wipe the data file.

**Before unpinning a user-placed widget (`source_bot_id=null`), confirm with the user.** Those are pins they added from the library or another bot emitted — removing them without asking is rude. Unpinning your own pins is fine.

## `promote_panel` / `demote_panel`

Panel mode is all-or-nothing per dashboard:

- `promote_panel(pin_id)` atomically demotes any existing panel pin and promotes the new one. Dashboard switches to `layout_mode: "panel"`.
- `demote_panel(pin_id)` clears the flag. If the dashboard has no other panel pin, it reverts to `grid` mode.

Use panel mode sparingly — it suppresses the grid matrix entirely. Good for a single-purpose dashboard (one big Kanban, one live camera feed); bad for dashboards with multiple first-class widgets.

## `set_dashboard_chrome` — dashboard-wide visual prefs

Two dashboard-wide toggles live on `grid_config`:

| Field | What it does |
|---|---|
| `borderless` | Drops the per-tile border. Good for kiosk / media-wall layouts where tile chrome competes with content. |
| `hover_scrollbars` | Hides scrollbars until the user hovers. Cleaner look on dense dashboards. |

Both default `false`. Omit a field in the call to leave it unchanged:

```python
set_dashboard_chrome(borderless=true)              # flip just borders
set_dashboard_chrome(hover_scrollbars=true)        # flip just scrollbars
set_dashboard_chrome(borderless=true, hover_scrollbars=true)  # both
```

These are **render preferences, not layout**. They don't move pins and don't affect zone/coord math. If the user says "make the dashboard look cleaner" or "no borders please", reach for this. Preset switches (standard ↔ fine) are a separate, heavier operation that rescales every pin — not wired as a bot tool today; ask the user to switch presets in the dashboard editor if they want that.

## Relation to `emit_html_widget`

`emit_html_widget` **does not pin**. It's purely a chat-message renderer: the widget shows up inside the tool result bubble, and the user can click the Pin button if they want it on the dashboard. When the user says "make me a widget and put it on my dashboard", do both:

1. `emit_html_widget(...)` to show the snapshot in chat.
2. If the widget lives at a known path, `pin_widget(widget=..., source_kind="channel", zone=...)` to place it.

For one-off inline widgets (no file on disk), there's currently no way for a bot to pin without the user clicking. Tell them they'll need to hit the Pin button.

## Anti-patterns

- Don't pin the same widget multiple times on one dashboard hoping for different positioning — `pin_widget` refuses duplicates.
- Don't mix `zone` and raw coordinates incorrectly: rail/dock pins should always have `x=0, w=1`. If you pass `x=5, w=3` to a rail zone, the renderer will clip.
- Don't remove user-placed pins without confirmation.
- Don't propose a layout without `describe_dashboard`-ing first. You'll produce ASCII that doesn't reflect reality.
- Don't guess at dashboard slugs. When unsure, ask the user which dashboard they mean or default to the current channel.

## See also

- [HTML Widgets](widgets/index.md) — authoring the widgets you'll pin (decision tree + sub-skills: `widgets/html`, `widgets/sdk`, `widgets/dashboards`, `widgets/tool-dispatch`, `widgets/manifest`, `widgets/db`, `widgets/handlers`, `widgets/suites`, `widgets/styling`, `widgets/errors`)
- [Knowledge Bases](knowledge_bases.md) — how auto-indexed widget frontmatter surfaces in search
