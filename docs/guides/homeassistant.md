# Home Assistant

The `homeassistant` integration turns Home Assistant into a first-class target for Spindrel bots: entity control, area queries, live state polling, and rich inline widgets with toggles and sliders. It ships as an in-tree Spindrel integration, carrying tools, skills, and widget templates — but talks to HA over the **Model Context Protocol (MCP)**, not over the HA REST API.

This guide covers the MCP server options, how to connect, how the bot targets entities, and how the widget templates render HA state live in chat.

---

## Architecture

```
     Bot
      │  tool call (e.g. HassTurnOn)
      ▼
  MCP tool registry
      │  routes to MCP server endpoint
      ▼
 HA MCP server (official or community)
      │  HA REST / WebSocket
      ▼
    Home Assistant
```

Spindrel itself does **not** hold an HA access token. It holds an MCP server URL + API key (the MCP server's key), and the MCP server fans out to HA on your behalf. Every HA tool you see in Spindrel — `HassTurnOn`, `HassTurnOff`, `HassLightSet`, `GetLiveContext`, `ha_get_state`, `ha_search_entities` — is an MCP tool.

What the integration ships:

- **Widget templates** for every HA tool — status badges, toggles, brightness sliders, live state polls, domain-filtered live-state dashboards.
- **A skill pack** teaching bots the HA entity-targeting grammar and when to reach for each tool.
- **Activation metadata** so the integration can expose its HA toolset on a channel without per-bot tool wiring.
- **No settings**. The integration itself is zero-config; the MCP server is where you point at HA.

---

## Connecting Home Assistant via MCP

You have two MCP servers to choose from:

| Server | Source | Tools shape |
|---|---|---|
| **Official HA MCP** | Ships with Home Assistant (built-in) | Intent-based: `HassTurnOn`, `HassTurnOff`, `HassLightSet`, `GetLiveContext` |
| **Community `ha-mcp`** | Third-party, runs alongside HA | Lower-level: `ha_get_state`, `ha_search_entities`, per-domain calls |

You can run both at once. The widgets support tools from both — the integration's `integration.yaml` declares templates for every tool name you'll see.

### Configure in Spindrel

**Admin → MCP Servers → New Server**, enter the HA MCP URL and API key, **Test**, save. Discovered tools are available immediately — no restart.

First-boot YAML seed (`mcp.yaml`) also works if you're automating bootstrap:

```yaml
homeassistant:
  url: http://ha-mcp:4000/homeassistant/mcp
  api_key: ${HA_MCP_KEY}
```

One-time only — once servers exist in the DB, `mcp.yaml` is ignored. See the [MCP Servers guide](mcp-servers.md) for the full walkthrough.

### Assign tools to a bot

Either list them explicitly under `mcp_servers:` in the bot YAML:

```yaml
mcp_servers: [homeassistant]
```

…or activate the `homeassistant` integration on the channel so the bot picks up the HA toolkit there. Related skills still flow through the normal skill system.

---

## Entity targeting — `where`, `pluck`, `first`

Official HA MCP tools return a rich result shape:

```json
{
  "response_type": "action_done",
  "data": {
    "targets": [{"type": "area", "name": "Living Room"}],
    "success": [{"type": "entity", "id": "light.living_room_1", "name": "Living Room Light 1"}],
    "failed": []
  }
}
```

Widget templates pluck the entity name out with the `where` + `pluck` + `first` filter chain:

```yaml
display_label: "{{data.success | where: type=entity | pluck: name | first}}"
```

This is the canonical pattern — it targets **the entity that actually changed**, not the area you asked about. If a bot calls `HassTurnOn(name="Living Room")` (an area), HA resolves it into concrete entities (the bulbs), and the widget labels the card with the first entity that succeeded.

Use the same pattern in your own prompts and skills — "call HA with the human name; the widget will label itself."

---

## Widget templates

The integration ships widget packages for every HA tool. Highlights:

Home Assistant has two MCP tool families. Do not mix them inside one preset or one assumed control flow:

- Official HA MCP presets use `GetLiveContext` plus `HassTurnOn` / `HassTurnOff` / `HassLightSet`.
- Community `ha-mcp` widgets use `ha_get_state` / `ha_search_entities`.
- Current presets declare `tool_family: official`; registration fails if a preset straddles both families.

### `HassTurnOn` / `HassTurnOff` — power toggle

Renders:

- A status badge (`On` in success green, `Off` in muted).
- A toggle control whose action calls the opposite tool (`HassTurnOff` if currently on, `HassTurnOn` if off). `optimistic: true` flips the visual before the round-trip lands.
- A properties row showing the target name + type.

When pinned, the widget uses a shared `_ha_state_poll` anchor that calls `GetLiveContext` on a refresh cadence and filters to this entity via `widget_transforms.entity_state` — so the card reflects live HA state, not the stale result of the last call.

### `HassLightSet` — brightness slider

Same scaffold as the on/off cards, plus:

- A **Brightness** slider (0–100%, step 5) whose `value_key: brightness` dispatches `HassLightSet(name=..., brightness=...)` when released.
- Gated on `is_on` + the pin actually being a `HassLightSet` pin, not a generic `HassTurnOn` — the transform flips `show_brightness` based on the pin's tool name.

The result shape of `HassLightSet` itself doesn't echo the new brightness, so the widget template is state-neutral — the pinned `state_poll` does the work of fetching the real brightness from HA.

### `ha_get_state` — single-entity sensor read

Community `ha-mcp` path. Renders an adaptive single-entity card: sensor card, light card, toggle chip, or generic entity chip depending on domain and config. Pins use `state_poll.args.entity_id = {{widget_config.entity_id}}` with `refresh_interval_seconds: 30` so the card stays live without re-parsing the display label after creation.

### `ha_search_entities` — collapsible result grid

Returns many entities. The widget shows a status header (`N matches for "query"`) and a collapsible section with a responsive tile grid reshaping each result into `{label, value, caption}` via inline `map:` — no Python transform needed.

### `GetLiveContext` — whole-home dashboard

Full-home state dump. The raw result is a YAML blob; a Python transform (`live_context_summary`) rebuilds the component tree with total + per-domain counts, an "Active now" section, and two filter rows ("Filter by area" / "Filter by domain") that use `dispatch: widget_config` to re-key the pinned card.

This widget is the showcase for HA state awareness — pin it to your channel dashboard for an ambient map of what's on, what's armed, what's running.

---

## Live state polling

HA entities change state all the time. The integration's widgets stay live via `state_poll` blocks:

```yaml
state_poll:
  tool: GetLiveContext
  args: {}
  transform: integrations.homeassistant.widget_transforms:entity_state
  refresh_interval_seconds: 60
```

`GetLiveContext` is the official-lane shared poll target: it returns every entity's state in one call, the Python transform filters to the specific entity on official action/preset pins, and the resulting `is_on` / `is_off` / `brightness` drives the toggle + slider components. One cached poll can feed official-lane HA pins on the dashboard.

Community `ha_get_state` pins instead re-call `ha_get_state` with `{{widget_config.entity_id}}`. Preset-created official pins render through `GetLiveContext` with empty tool args and keep their selected entity in `widget_config`.

See [Widget Templates → State polling](widget-templates.md#state-polling) for the underlying mechanism.

---

## Tools + skill

The `homeassistant` integration packages:

- The full MCP toolkit (via MCP server enrollment).
- A **skill** teaching the bot:
  - How HA entity naming works (areas vs entities vs devices, friendly_name vs entity_id).
  - When to call `GetLiveContext` vs `ha_search_entities` vs `ha_get_state`.
  - The `where: type=entity | pluck: name | first` targeting pattern.
  - Canonical request patterns — "turn on the living room lights" → area-scoped `HassTurnOn`, not per-entity enumeration.

Activating the integration on a channel (Channel → Integrations tab → Activate) exposes the tools there without per-bot config churn. The skill remains a normal skill.

---

## Comparison with `guides/mcp-servers.md`

The [MCP Servers guide](mcp-servers.md) is the general walkthrough for any MCP server. This guide is specific to **the HA integration** — the widget packages, the skill pack, and the entity-targeting grammar. They're complementary:

- New to MCP entirely? Start with `mcp-servers.md`, which has a Home Assistant worked example.
- Already have MCP working and want to know what the HA integration adds on top? This is the right page.

---

## Reference

| What | Where |
|---|---|
| Integration YAML (widget templates) | `integrations/homeassistant/integration.yaml` |
| Python transforms | `integrations/homeassistant/widget_transforms.py` |
| Skill pack | `integrations/homeassistant/skills/` |
| Official HA MCP docs | HA project — `Settings → Voice Assistants → Expose` |
| Community `ha-mcp` | `github.com/...` (third-party, user-installed) |

## See also

- [MCP Servers](mcp-servers.md) — generic MCP setup, first-boot seed, admin UI walkthrough.
- [Widget Templates](widget-templates.md) — substitution syntax, `state_poll`, Python transforms, the `where`/`pluck`/`first`/`map` filter chain.
- [Widget Dashboards](widget-dashboards.md) — pin HA widgets to a live dashboard, OmniPanel rail.
