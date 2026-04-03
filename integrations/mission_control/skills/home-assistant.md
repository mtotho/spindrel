---
name: Home Assistant Smart Home Management
description: >-
  Comprehensive reference for managing a smart home via Home Assistant MCP tools —
  entity domains, service call patterns, automation creation, debugging, helper entities,
  dashboard management, energy monitoring, and household preference tracking.
---

# Home Assistant — Deep Reference

## Entity Domains Quick Reference

Home Assistant organizes devices by domain. Know the domain to pick the right service calls.

| Domain | Examples | Key Services |
|--------|----------|--------------|
| `light` | Bulbs, strips, groups | `turn_on` (brightness, color_temp, rgb_color), `turn_off`, `toggle` |
| `switch` | Smart plugs, relays | `turn_on`, `turn_off`, `toggle` |
| `climate` | Thermostats, AC, heaters | `set_temperature`, `set_hvac_mode`, `set_fan_mode`, `set_preset_mode` |
| `cover` | Blinds, shades, garage doors | `open_cover`, `close_cover`, `set_cover_position`, `stop_cover` |
| `fan` | Ceiling fans, air purifiers | `turn_on` (speed, percentage), `turn_off`, `set_percentage` |
| `media_player` | Speakers, TVs, Chromecasts | `turn_on`, `play_media`, `volume_set`, `media_pause`, `select_source` |
| `lock` | Smart locks | `lock`, `unlock` |
| `vacuum` | Robot vacuums | `start`, `stop`, `return_to_base`, `send_command` |
| `camera` | Security cameras | Use `ha_get_camera_image` for snapshots |
| `sensor` | Temperature, humidity, power | Read-only — query state for current value |
| `binary_sensor` | Motion, door/window, occupancy | Read-only — `on`/`off` state |
| `automation` | HA automations | `trigger`, `turn_on` (enable), `turn_off` (disable) |
| `script` | HA scripts | `turn_on` (run with variables) |
| `scene` | HA scenes | `turn_on` (activate scene) |
| `input_boolean` | Virtual toggles | `turn_on`, `turn_off`, `toggle` |
| `input_number` | Virtual sliders | `set_value` |
| `input_select` | Virtual dropdowns | `select_option` |
| `timer` | Countdown timers | `start`, `cancel`, `pause`, `finish` |
| `button` | One-shot triggers | `press` |
| `number` | Device numeric controls | `set_value` |
| `select` | Device option selectors | `select_option` |

## Service Call Patterns

### Lights

```
# Turn on at specific brightness (0-255) and color temperature (mireds)
ha_call_service("light", "turn_on", entity_id="light.living_room",
    data={"brightness": 128, "color_temp": 370})

# Turn on with RGB color
ha_call_service("light", "turn_on", entity_id="light.accent_strip",
    data={"rgb_color": [255, 147, 41]})  # warm amber

# Transition over 5 seconds
ha_call_service("light", "turn_on", entity_id="light.bedroom",
    data={"brightness": 50, "transition": 5})
```

**Brightness guide** (for preferences.md):
- `255` = 100% — full blast, cleaning/task work
- `200` = ~78% — bright, daytime comfortable
- `128` = 50% — moderate, evening general use
- `64` = 25% — dim, relaxed evening
- `25` = ~10% — nightlight level
- `1` = minimum — barely on

**Color temperature guide** (in mireds, lower = cooler):
- `153` = 6500K — daylight blue-white (energizing, task lighting)
- `250` = 4000K — neutral white (balanced, daytime)
- `370` = 2700K — warm white (relaxed, evening default)
- `454` = 2200K — candlelight warm (very cozy, wind-down)
- `500` = 2000K — ultra warm (nightlight)

### Climate

```
# Set target temperature
ha_call_service("climate", "set_temperature", entity_id="climate.thermostat",
    data={"temperature": 72})

# Set mode (heat, cool, auto, off)
ha_call_service("climate", "set_hvac_mode", entity_id="climate.thermostat",
    data={"hvac_mode": "auto"})

# Set range (dual setpoint)
ha_call_service("climate", "set_temperature", entity_id="climate.thermostat",
    data={"target_temp_low": 68, "target_temp_high": 74})
```

### Covers (Blinds/Shades)

```
# Position: 0 = closed, 100 = fully open
ha_call_service("cover", "set_cover_position", entity_id="cover.living_room_blinds",
    data={"position": 50})
```

### Media

```
# Play/pause
ha_call_service("media_player", "media_play_pause", entity_id="media_player.living_room_speaker")

# Set volume (0.0 to 1.0)
ha_call_service("media_player", "volume_set", entity_id="media_player.living_room_speaker",
    data={"volume_level": 0.4})

# Select input/source
ha_call_service("media_player", "select_source", entity_id="media_player.tv",
    data={"source": "HDMI 1"})
```

### Bulk Operations

Use `ha_bulk_control` to execute multiple commands atomically — ideal for routines:

```
ha_bulk_control(commands=[
    {"domain": "light", "service": "turn_on", "entity_id": "light.living_room", "data": {"brightness": 128, "color_temp": 370}},
    {"domain": "light", "service": "turn_off", "entity_id": "light.kitchen"},
    {"domain": "cover", "service": "close_cover", "entity_id": "cover.living_room_blinds"},
    {"domain": "media_player", "service": "turn_on", "entity_id": "media_player.tv"}
])
```

## Finding Entities

When you don't know the exact entity_id:

1. **Fuzzy search**: `ha_search_entities("living room light")` — best first try
2. **By area**: `ha_get_states(area="living_room")` — all entities in a room
3. **By domain**: `ha_get_states(domain="light")` — all lights
4. **Deep search**: `ha_deep_search("motion sensor kitchen")` — searches configs too
5. **System overview**: `ha_get_overview()` — high-level view of areas, devices, entities

**Entity ID conventions**: `{domain}.{descriptive_name}` — e.g., `light.kitchen_ceiling`, `sensor.outdoor_temperature`, `binary_sensor.front_door_contact`

## Automation Management

### Creating Automations

```
ha_config_set_automation(
    alias="Turn on porch light at sunset",
    description="Automatically illuminates the porch at sunset",
    trigger=[{
        "trigger": "sun",
        "event": "sunset",
        "offset": "-00:15:00"  # 15 minutes before
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
| `state` | Entity changes state (e.g., motion detected, door opened) |
| `sun` | Sunrise/sunset with optional offset |
| `time` | Specific time of day |
| `time_pattern` | Recurring (every N minutes/hours) |
| `numeric_state` | Value crosses a threshold (e.g., temperature above 80) |
| `zone` | Person enters/leaves a zone |
| `device` | Device-specific triggers (button press, etc.) |
| `calendar` | Calendar event starts/ends |
| `template` | Custom Jinja2 condition becomes true |

### Debugging Automations

1. **Check traces**: `ha_get_automation_traces(automation_id)` — see execution history, what triggered, what ran, what failed
2. **Check logbook**: `ha_get_logbook(entity_id="automation.name")` — when it fired
3. **Check entity state**: Verify trigger entities are in expected states
4. **Common issues**:
   - Automation disabled — `ha_get_state("automation.name")` should be `on`
   - Wrong entity_id in trigger/action — use `ha_search_entities` to verify
   - Condition blocking — traces show which condition failed
   - Service call data wrong — check domain docs for required fields

## Helper Entities

Helpers are virtual entities for storing state, useful for preferences and modes.

| Helper Type | Good For | Creation |
|-------------|----------|----------|
| `input_boolean` | Mode toggles (guest mode, vacation mode, sleep mode) | `ha_config_set_helper(type="input_boolean", name="...", icon="...")` |
| `input_number` | Preferred values (default brightness, temp setpoint) | `ha_config_set_helper(type="input_number", name="...", min=0, max=100)` |
| `input_select` | Mode selectors (lighting scene, HVAC preset) | `ha_config_set_helper(type="input_select", name="...", options=[...])` |
| `input_datetime` | Schedules (wake time, bedtime) | `ha_config_set_helper(type="input_datetime", name="...", has_time=true)` |
| `timer` | Countdown triggers (turn off in 30 min) | `ha_config_set_helper(type="timer", name="...", duration="00:30:00")` |
| `counter` | Event counting (door opens today) | `ha_config_set_helper(type="counter", name="...", step=1)` |

**Pro tip**: Combine helpers with automations for user-configurable behavior. E.g., `input_number.default_evening_brightness` → automation reads it when turning on lights at sunset.

## Script Management

Scripts are reusable sequences — perfect for routines that get triggered in multiple ways.

```
ha_config_set_script(
    alias="movie_mode",
    sequence=[
        {"action": "light.turn_on", "target": {"entity_id": "light.living_room"}, "data": {"brightness": 30, "color_temp": 454}},
        {"action": "cover.close_cover", "target": {"entity_id": "cover.living_room_blinds"}},
        {"action": "media_player.turn_on", "target": {"entity_id": "media_player.tv"}},
        {"delay": "00:00:03"},
        {"action": "media_player.select_source", "target": {"entity_id": "media_player.tv"}, "data": {"source": "HDMI 1"}}
    ]
)
```

## Dashboard Tips

- `ha_config_get_dashboard()` — list all dashboards
- `ha_config_get_dashboard(dashboard_id)` — get full YAML config
- `ha_config_set_dashboard(dashboard_id, config)` — update dashboard
- `ha_dashboard_find_card(dashboard_id, query)` — find specific cards
- Prefer modifying existing dashboards over creating new ones
- Use `type: entities` for status views, `type: grid` for controls

## Energy & Monitoring

For energy-aware responses:
- Query power sensors: `ha_get_states(domain="sensor")` → filter for `_power`, `_energy` entities
- Historical usage: `ha_get_history(entity_id="sensor.total_energy", start=..., end=...)`
- Statistics: `ha_get_statistics(entity_id, period="day")` for daily/weekly/monthly aggregates
- When suggesting automations, consider energy impact (e.g., "this automation could save ~$X/month by turning off [devices] when not in use")

## Preference Tracking (preferences.md)

Maintain preferences.md as a living document. Structure it by room and category:

```markdown
## Living Room

### Lighting
- **Evening (after sunset)**: 50% brightness, 2700K warm — adjusted 2026-03-15 (was 60%, "too bright")
- **Movie mode**: 12% brightness, 2200K candlelight
- **Morning**: 80% brightness, 4000K neutral
- **Preferred bulb mode**: color_temp (not RGB)

### Climate
- **Daytime**: 72°F
- **Night**: 68°F
- **Preferred mode**: auto

### Covers
- **Morning**: open fully by 8:00 AM
- **Movie mode**: closed
- **Night**: closed by sunset + 30min

## Bedroom
### Lighting
- **Evening**: 25% brightness, 2200K — never above 40% after 9 PM
- **Wake-up**: gradual from 0→60% over 15 min starting at alarm time
...
```

**When to update preferences.md**:
- User says "too bright/dim/hot/cold" → adjust + record
- User manually sets a specific value → note it with context
- User defines a routine → record all settings
- User corrects your choice → update with the correction and reason
- Seasonal changes → note the date and season

## Routine Definitions (routines.md)

Track named routines with exact service calls:

```markdown
## Morning

**Trigger phrases**: "good morning", "I'm up", "start the day"

1. Living room lights → 80%, 4000K neutral
2. Kitchen lights → 100%, 4000K
3. Blinds → open all
4. Thermostat → daytime setpoint (72°F)
5. Coffee maker → turn on (if smart plug connected)

## Wind Down

**Trigger phrases**: "wind down", "relaxing time", "evening mode"

1. All lights → 40%, 2700K warm, 10s transition
2. Living room TV → turn on
3. Thermostat → evening setpoint (70°F)

## Good Night

**Trigger phrases**: "good night", "going to bed", "lights out"

1. All lights → off (except nightlights)
2. All doors → lock
3. Thermostat → night setpoint (68°F)
4. Blinds → close all
5. TV/speakers → off
6. Set alarm integration (if available)
```

## System Health Checks

For heartbeats or status requests:
1. `ha_get_system_health()` — overall HA health
2. `ha_get_updates()` — pending updates for HA core, OS, add-ons
3. `ha_get_states(domain="binary_sensor")` → check for `unavailable` entities (disconnected devices)
4. `ha_get_states(domain="sensor")` → look for battery sensors below threshold
5. `ha_get_logbook(hours=24)` → unusual events or errors

## Common Pitfalls

- **Entity unavailable**: Device offline or integration issue — check `ha_get_device` for the parent device status
- **Service call fails silently**: Verify entity supports the service — not all lights support color_temp or rgb
- **Automation not firing**: Check if it's enabled (`state: on`), review traces for condition failures
- **Wrong brightness scale**: HA uses 0-255 for brightness in service calls but 0-100% in UI — convert when talking to users
- **Color temp units**: Mireds (153-500 typical range) — lower number = cooler/bluer, higher = warmer
- **Template errors**: If using `ha_eval_template`, test with simple templates first
