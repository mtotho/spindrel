---
name: Home Assistant Smart Home Management
description: >-
  Comprehensive reference for managing a smart home via Home Assistant MCP tools —
  covers both the official HA MCP integration (Hass* tools) and the community ha-mcp
  server (ha_* tools). Entity domains, service call patterns, automation creation,
  debugging, preference tracking, and routine management.
---

# Home Assistant — Deep Reference

## Two MCP Servers, Two Tool Sets

| | Official HA MCP Integration | Community ha-mcp |
|---|---|---|
| **Tool prefix** | `Hass*` (e.g., `HassTurnOn`) | `ha_*` (e.g., `ha_call_service`) |
| **Scope** | Device control only (intents) | Full HA API (92+ tools) |
| **Setup** | Built into HAOS, enable in integrations | Separate add-on or Docker container |
| **Entity exposure** | Only entities exposed to voice assistants | All entities |
| **Automation CRUD** | No | Yes (`ha_config_set_automation`, etc.) |
| **History/Logbook** | No | Yes (`ha_get_history`, `ha_get_logbook`) |
| **Dashboard editing** | No | Yes (`ha_config_set_dashboard`, etc.) |
| **System admin** | No | Yes (backups, updates, HACS, etc.) |
| **Custom scripts** | Exposed as named tools (e.g., `bedroom_set_scene_based_on_time`) | Via `ha_call_service("script", ...)` |

Use whichever tools are available. Sections marked **(ha-mcp only)** require the community server.

---

## Official HA MCP Tools Reference

These intent-based tools are available when using the built-in HA MCP integration.

### Core Control Tools

| Tool | What it does | Key parameters |
|------|-------------|----------------|
| `HassTurnOn` | Turn on any entity | `name` (friendly name or entity_id) |
| `HassTurnOff` | Turn off any entity | `name` |
| `HassLightSet` | Set light brightness and color | `name`, `brightness` (0-100%), `color`, `temperature` |
| `HassClimateSetTemperature` | Set thermostat temperature | `name`, `temperature` |
| `HassFanSetSpeed` | Set fan speed | `name`, `percentage` (0-100%) |
| `HassSetVolume` | Set media player volume | `name`, `volume_level` (0-100) |
| `HassSetVolumeRelative` | Adjust volume up/down | `name`, `volume_level_relative` |
| `HassMediaPause` | Pause media playback | `name` |
| `HassMediaUnpause` | Resume media playback | `name` |
| `HassMediaNext` | Next track | `name` |
| `HassMediaPrevious` | Previous track | `name` |
| `HassMediaPlayerMute` | Mute | `name` |
| `HassMediaPlayerUnmute` | Unmute | `name` |
| `HassMediaSearchAndPlay` | Search and play media | `name`, `query` |
| `HassCancelAllTimers` | Cancel all running timers | — |
| `GetDateTime` | Get current date/time | — |
| `GetLiveContext` | Get live entity states | — |

### Custom Script Tools

HA scripts that are exposed to voice assistants appear as named tools — e.g.,
`bedroom_set_scene_based_on_time`, `kitchen_set_scene_based_on_time`. These
run the full script sequence when called.

### Exposing More Entities

To add entities to the official HA MCP tools:
1. Go to **Settings > Voice Assistants** in Home Assistant
2. Click the **Expose** tab
3. Toggle on entities you want the AI to control
4. Only exposed entities are visible to `HassTurnOn`, `HassLightSet`, etc.

**Tip**: Expose liberally — the AI benefits from seeing more of the home. At minimum, expose all lights, switches, climate, media players, covers, and locks.

---

## Entity Domains Quick Reference

| Domain | Examples | Key Services (ha-mcp) | Official Tool |
|--------|----------|----------------------|---------------|
| `light` | Bulbs, strips, groups | `turn_on` (brightness, color_temp, rgb_color) | `HassLightSet` |
| `switch` | Smart plugs, relays | `turn_on`, `turn_off`, `toggle` | `HassTurnOn/Off` |
| `climate` | Thermostats, AC | `set_temperature`, `set_hvac_mode` | `HassClimateSetTemperature` |
| `cover` | Blinds, shades, garage | `open_cover`, `close_cover`, `set_cover_position` | `HassTurnOn/Off` |
| `fan` | Ceiling fans, purifiers | `turn_on`, `set_percentage` | `HassFanSetSpeed` |
| `media_player` | Speakers, TVs | `play_media`, `volume_set`, `media_pause` | `HassMediaPause`, `HassSetVolume` |
| `lock` | Smart locks | `lock`, `unlock` | `HassTurnOn/Off` (lock/unlock) |
| `vacuum` | Robot vacuums | `start`, `stop`, `return_to_base` | `HassTurnOn/Off` |
| `camera` | Security cameras | `ha_get_camera_image` (ha-mcp only) | — |
| `sensor` | Temperature, humidity | Read-only — query state | `GetLiveContext` |
| `binary_sensor` | Motion, door/window | Read-only — `on`/`off` | `GetLiveContext` |
| `automation` | HA automations | `trigger`, `turn_on` (enable) | — |
| `script` | HA scripts | `turn_on` (run with variables) | Exposed as named tools |
| `scene` | HA scenes | `turn_on` (activate) | `HassTurnOn` |
| `input_boolean` | Virtual toggles | `turn_on`, `turn_off`, `toggle` | `HassTurnOn/Off` |
| `input_number` | Virtual sliders | `set_value` | — |
| `input_select` | Virtual dropdowns | `select_option` | — |
| `timer` | Countdown timers | `start`, `cancel` | `HassCancelAllTimers` |

## Brightness & Color Temperature Reference

### Brightness Guide

When talking to users, use percentages. When calling tools:
- **Official HA MCP** (`HassLightSet`): uses **0-100%** directly
- **ha-mcp** (`ha_call_service`): uses **0-255** scale

| User Says | Percentage | ha-mcp value (0-255) | Use Case |
|-----------|-----------|---------------------|----------|
| "Full brightness" | 100% | 255 | Cleaning, task work |
| "Bright" | ~78% | 200 | Daytime comfortable |
| "Medium" | 50% | 128 | Evening general use |
| "Dim" | 25% | 64 | Relaxed evening |
| "Nightlight" | ~10% | 25 | Nightlight |
| "Barely on" | ~1% | 1 | Minimum |

### Color Temperature Guide

Color temperature in mireds (lower = cooler/bluer, higher = warmer/amber):

| Mireds | Kelvin | Feel | Good For |
|--------|--------|------|----------|
| 153 | 6500K | Daylight blue-white | Energizing, task lighting |
| 250 | 4000K | Neutral white | Balanced daytime |
| 370 | 2700K | Warm white | Relaxed evening (most common default) |
| 454 | 2200K | Candlelight | Wind-down, cozy |
| 500 | 2000K | Ultra warm | Nightlight |

---

## Service Call Patterns (ha-mcp only)

These patterns use `ha_call_service`. Skip this section if you only have official HA MCP tools.

### Lights

```
# Brightness (0-255) + color temperature (mireds)
ha_call_service("light", "turn_on", entity_id="light.living_room",
    data={"brightness": 128, "color_temp": 370})

# RGB color
ha_call_service("light", "turn_on", entity_id="light.accent_strip",
    data={"rgb_color": [255, 147, 41]})

# Transition over 5 seconds
ha_call_service("light", "turn_on", entity_id="light.bedroom",
    data={"brightness": 50, "transition": 5})
```

### Climate

```
# Set target temperature
ha_call_service("climate", "set_temperature", entity_id="climate.thermostat",
    data={"temperature": 72})

# Set mode
ha_call_service("climate", "set_hvac_mode", entity_id="climate.thermostat",
    data={"hvac_mode": "auto"})
```

### Media

```
# Set volume (0.0 to 1.0)
ha_call_service("media_player", "volume_set", entity_id="media_player.tv",
    data={"volume_level": 0.4})
```

### Bulk Operations

```
ha_bulk_control(commands=[
    {"domain": "light", "service": "turn_on", "entity_id": "light.living_room",
     "data": {"brightness": 128, "color_temp": 370}},
    {"domain": "light", "service": "turn_off", "entity_id": "light.kitchen"},
])
```

## Finding Entities (ha-mcp only)

1. **Fuzzy search**: `ha_search_entities("living room light")` — best first try
2. **By area**: `ha_get_states(area="living_room")` — all entities in a room
3. **By domain**: `ha_get_states(domain="light")` — all lights
4. **Deep search**: `ha_deep_search("motion sensor kitchen")` — searches configs too
5. **System overview**: `ha_get_overview()` — areas, devices, entity counts

For the official HA MCP: use `GetLiveContext` to see currently exposed entity states.

---

## Automation Management (ha-mcp only)

### Creating Automations

```
ha_config_set_automation(
    alias="Turn on porch light at sunset",
    description="Automatically illuminates the porch at sunset",
    trigger=[{
        "trigger": "sun",
        "event": "sunset",
        "offset": "-00:15:00"
    }],
    action=[{
        "action": "light.turn_on",
        "target": {"entity_id": "light.porch"},
        "data": {"brightness": 200}
    }],
    condition=[{
        "condition": "state",
        "entity_id": "input_boolean.vacation_mode",
        "state": "off"
    }]
)
```

### Common Trigger Types

| Trigger | Use When |
|---------|----------|
| `state` | Entity changes state (motion detected, door opened) |
| `sun` | Sunrise/sunset with optional offset |
| `time` | Specific time of day |
| `time_pattern` | Recurring (every N minutes/hours) |
| `numeric_state` | Value crosses a threshold (temp above 80) |
| `zone` | Person enters/leaves a zone |
| `device` | Device-specific (button press, etc.) |
| `calendar` | Calendar event starts/ends |
| `template` | Custom Jinja2 condition becomes true |

## Helper Entities (ha-mcp only)

Virtual entities for storing state — useful for preferences and modes.

| Helper Type | Good For | Creation |
|-------------|----------|----------|
| `input_boolean` | Mode toggles (guest, vacation, sleep) | `ha_config_set_helper(type="input_boolean", ...)` |
| `input_number` | Preferred values (brightness, temp) | `ha_config_set_helper(type="input_number", ...)` |
| `input_select` | Mode selectors (scene, HVAC preset) | `ha_config_set_helper(type="input_select", ...)` |
| `input_datetime` | Schedules (wake time, bedtime) | `ha_config_set_helper(type="input_datetime", ...)` |
| `timer` | Countdown triggers | `ha_config_set_helper(type="timer", ...)` |
| `counter` | Event counting | `ha_config_set_helper(type="counter", ...)` |

**Pro tip**: Combine helpers with automations for user-configurable behavior. E.g.,
`input_number.default_evening_brightness` → automation reads it at sunset.

---

## Preference Tracking (preferences.md)

Maintain preferences.md in the channel workspace as a living document. Structure by room and category:

```markdown
## Living Room

### Lighting
- **Evening (after sunset)**: 50% brightness, 2700K warm — adjusted 2026-03-15 (was 60%, "too bright")
- **Movie mode**: 12% brightness, 2200K candlelight
- **Morning**: 80% brightness, 4000K neutral

### Climate
- **Daytime**: 72°F
- **Night**: 68°F
```

**When to update preferences.md**:
- User says "too bright/dim/hot/cold" → adjust + record
- User manually sets a specific value → note it with context
- User defines a routine → record all settings
- User corrects your choice → update with the correction and reason

## Routine Definitions (routines.md)

Track named routines with the exact tool calls for each step in the channel workspace:

```markdown
## Morning

**Trigger phrases**: "good morning", "I'm up", "start the day"

### Steps (Official HA MCP)
1. `HassLightSet` → Living room, brightness 80%
2. `HassLightSet` → Kitchen, brightness 100%
3. `HassTurnOn` → Cover: living room blinds
4. `HassClimateSetTemperature` → 72°F
```

**Tip**: If the user has custom script tools (like `bedroom_set_scene_based_on_time`),
record what they do and use them directly — they're often better than manual service
calls because they encapsulate HA-side logic.

## System Health Checks (ha-mcp only)

For heartbeats or status requests:
1. `ha_get_system_health()` — overall HA health
2. `ha_get_updates()` — pending updates
3. `ha_get_states(domain="binary_sensor")` → check for `unavailable` entities
4. `ha_get_states(domain="sensor")` → battery sensors below threshold
5. `ha_get_logbook(hours=24)` → unusual events or errors

For the official HA MCP: use `GetLiveContext` for a status snapshot.

## Common Pitfalls

- **Entity unavailable**: Device offline — power cycle, check WiFi, re-pair Zigbee/Z-Wave
- **Wrong brightness scale**: Official uses 0-100%, ha-mcp uses 0-255. Convert when talking to users (always speak in percentages).
- **Color temp units**: Mireds (153-500) — lower = cooler/bluer, higher = warmer. Not all bulbs support the full range.
- **Service call fails silently**: Verify entity supports the service — not all lights support color_temp or RGB
- **Automation not firing** (ha-mcp): Check enabled state, review traces for condition failures
- **Official MCP "entity not found"**: Entity isn't exposed to voice assistants — go to Settings > Voice Assistants > Expose
- **Custom scripts don't appear**: Script must be exposed to voice assistants to show as a tool
