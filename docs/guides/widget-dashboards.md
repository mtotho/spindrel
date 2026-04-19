# Widget Dashboards

Dashboards are Spindrel's answer to "I want my agent's output *on a wall*, not buried in chat." Pin any tool result — a Home Assistant light toggle, a weather card, a task-status chip, a bot-authored HTML chart — to a dashboard and it keeps working: polling for fresh state, honoring clicks, updating when the underlying data moves.

There are two shapes of dashboard, and both are used by the same pins, grid, and editing tools:

- **Named user dashboards** at `/widgets/<slug>` — your personal pinboards (`default`, plus any you create: `home`, `monitoring`, etc.). Cross-channel; mix tools from any bot on any channel.
- **Channel dashboards** at `/widgets/channel/:channelId` — one per channel, lazy-created. The left column also surfaces in the channel's **OmniPanel** (sidebar), so pinning there lets a widget live next to the conversation that produced it.

You reach the `/widgets` page from the left sidebar rail ("Widgets" tab). Channel dashboards are reachable from the channel header's `LayoutDashboard` icon and the command palette ("Channel dashboard" under THIS CHANNEL).

## Two kinds of widgets, one dashboard

Any widget fits anywhere. The dashboard doesn't care what drew the pixels, only that the pin has an envelope.

| Kind | Authored by | How it renders | Example |
|---|---|---|---|
| **Component widget** | A tool's YAML template (e.g. integration-declared `tool_widgets:` or a `*.widgets.yaml` file next to a local tool) | Structured JSON → the built-in `ComponentRenderer` — buttons, toggles, sliders, properties, tiles, status chips | HassLightSet power toggle + brightness slider; weather card with a "Show forecast" button; `schedule_task` status card |
| **HTML widget** | A bot, via `emit_html_widget` | Sandboxed iframe with bot-written HTML + JS + CSS. Runs fetches against `/api/v1/...` via `window.spindrel.api()` | A recent-messages panel; a custom Chart.js bar chart; a per-project mini-control-surface |

Mix freely. A typical channel dashboard might have a Home Assistant tile, a bot-authored metrics chart, and a pinned `schedule_task` status — all on the same grid.

For the authoring deep-dive on each kind, see [Widget Templates](../widget-templates.md) (component widgets) and [HTML Widgets](html-widgets.md).

## Named user dashboards

The `/widgets` page shows a tab strip of your user dashboards (channel dashboards are filtered out so the tabs don't flood). Each tab is a full grid.

**Creating + managing:**

- **Create** (`+` button next to the tabs) → a sheet asks for slug, name, optional icon. The slug becomes the URL (`/widgets/<slug>`).
- **Rename / set icon / switch grid preset** (`⚙️` button on the active tab) → `EditDashboardDrawer`.
- **Delete** — any dashboard except `default`. `default` is your home board and always exists.

**Adding widgets:**

- **From chat** — every widget card has a pin icon (`📌`). Click and it lands on the **channel** dashboard (the conversation-local board). From there you can move it into a named dashboard using "Add from channel" (below).
- **From `/widgets`** — the "Add widget" button opens the `AddFromChannelSheet`: browse pins on any channel's dashboard, search by name, add to the currently-viewed dashboard. Adding here doesn't remove it from the source — pins are copied by envelope.
- **From a bot** — ask the bot to pin its output. Bots can author HTML widgets via `emit_html_widget`; the user still confirms the pin.

## Channel dashboards

Every channel gets an implicit widget dashboard under slug `channel:<uuid>`, created on first read or first pin — no setup required. The dashboard is cascade-deleted when the channel is.

**Two views onto the same pins:**

- **Full dashboard** at `/widgets/channel/:channelId` — the whole grid, identical editing UI to user dashboards.
- **OmniPanel rail** on the channel itself — a subset of the full grid, always visible alongside the conversation.

**The rail rule:** a pin is in the rail when `grid_layout.x < railZoneCols` (6 on the standard preset, 12 on fine). No opt-in flag — rail membership is a pure function of where you placed the widget on the grid. Drop a widget in the leftmost band and it shows up in the OmniPanel; drag it right and it leaves the rail without being unpinned. Edit mode on the full channel dashboard draws a `SidebarRailOverlay` band over those columns so the zone is visible while you work.

**OmniPanel structure:**

- **Widgets section** — the rail subset of the channel dashboard, each rendered as a `PinnedToolWidget` with its own drag handle, refresh, unpin.
- **Files section** — channel-scoped file tree (orthogonal to widgets).
- **Mobile** — the OmniPanel becomes a bottom sheet (tall ≈88vh + dismissed). Tabs remember your last choice; default is Widgets.

## Layout, editing, and grid presets

Under the hood the grid is `react-grid-layout` — drag to move, corner-handle to resize. Layout changes are optimistic and commit in one bulk `POST /pins/layout` call.

**Per-pin editing** (edit mode → pencil icon on a tile):

- **Display label** — what the card header says. Defaults to the envelope's `display_label` or the tool name.
- **Widget config** — free-form JSON. For widgets whose YAML template substitutes `{{ config.* }}`, this is where "Show Fahrenheit", "Hide forecast", "Compact mode", etc. live.

**Grid presets:**

| Preset | Columns | Row height | Rail zone | Best for |
|---|---|---|---|---|
| **Standard** (default) | 12 | 30 px | `x < 6` | Most dashboards; friendlier grid |
| **Fine** | 24 | 15 px | `x < 12` | Information-dense boards; half-tile increments |

Switch from `EditDashboardDrawer`. Rescaling is atomic and integer-safe (std↔fine = ×2), so the visual arrangement survives the switch.

## Authorization and ownership

- **Dashboards are shared, not per-user** (current iteration). Any authenticated user with `channels:write` can create, rename, delete, and pin. Multi-tenancy isolation is a roadmap item.
- **Widgets run as the bot that authored them**, not as you. For component widgets this is a non-issue (tools already run server-side under the bot's identity). For HTML widgets it's load-bearing security — see [HTML Widgets → Security model](html-widgets.md#the-security-model--widgets-run-as-the-bot-not-as-you). The `@botname` chip on an HTML widget's iframe tells you who it's acting as.

## Troubleshooting

| Symptom | Usual cause |
|---|---|
| Widget pinned from chat doesn't show in the OmniPanel | Its `grid_layout.x` is outside the rail zone. Open the full channel dashboard, drag it left of column 6 (standard) / 12 (fine). |
| "No widgets pinned" on the channel dashboard even though you see pins in the OmniPanel | You're probably on a user dashboard, not the channel one. The channel dashboard URL is `/widgets/channel/:channelId`; the page shows a breadcrumb instead of the tab strip when you're on it. |
| Widget says "Widget auth failed" | It's an HTML widget and the emitting bot has no API key. Admin UI → Bots → this bot → API Permissions. |
| Clicking a component widget toggle 403s | The bot doesn't have the scope the tool requires. Broaden the bot's scopes, not yours. |
| Mobile bottom sheet feels stuck | The sheet has two snap points only (tall + dismissed). Swipe down to dismiss; tap the handle to reopen. The middle "half" state is intentionally gone. |

## See also

- [HTML Widgets](html-widgets.md) — bot-authored iframe widgets and their bot-scoped auth model.
- [Widget Templates](../widget-templates.md) — authoring component widgets from YAML.
- [Developer API](api.md) — the endpoints widgets call when they need live data.
