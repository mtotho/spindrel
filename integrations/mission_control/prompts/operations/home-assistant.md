---
name: "Smart Home (Home Assistant)"
description: "Workspace schema for managing a smart home via Home Assistant — device tracking, preference learning, routine definitions, automation management, and proactive monitoring."
category: workspace_schema
compatible_integrations:
  - mission_control
mc_min_version: "2.0"
tags:
  - home-assistant
  - smart-home
  - automation
  - iot
  - lighting
  - climate
  - mission-control
group: "Operations"
recommended_heartbeat:
  prompt: >-
    Run a smart home health check. Query HA for: (1) any unavailable entities (disconnected devices),
    (2) low battery sensors, (3) pending HA updates, (4) any automations that failed in the last 24h.
    Update status.md with findings. If anything needs attention, create a task card. If everything is
    healthy, just update the "last checked" timestamp in status.md.
  interval: "daily"
  quiet_start: "23:00"
  quiet_end: "07:00"
---

## Workspace File Organization — Smart Home (Home Assistant)

Organize channel workspace files to manage your smart home:

- **preferences.md** — Household preferences: per-room lighting, temperature, and comfort settings
  - Organized by room, then by category (lighting, climate, covers, media)
  - Each preference includes: value, context (time of day, activity), and when it was last updated
  - **This is the bot's long-term memory for your home** — updated proactively whenever you adjust something or express a preference
  - Format:
    ```markdown
    ## Living Room

    ### Lighting
    - **Evening (after sunset)**: 50% brightness, 2700K warm — updated 2026-03-15 (was 60%, user said "too bright")
    - **Movie mode**: 12% brightness, 2200K candlelight
    - **Morning**: 80% brightness, 4000K neutral

    ### Climate
    - **Daytime**: 72°F, mode: auto
    - **Night**: 68°F, mode: heat
    - **Away**: 65°F
    ```

- **routines.md** — Named routines with exact service calls to execute
  - Each routine has: name, trigger phrases, and numbered steps with HA service calls
  - Format:
    ```markdown
    ## Morning

    **Trigger phrases**: "good morning", "I'm up", "start the day"

    1. Living room lights → 80%, 4000K neutral
    2. Kitchen lights → 100%, 4000K
    3. Blinds → open all
    4. Thermostat → 72°F (daytime setpoint)

    ## Good Night

    **Trigger phrases**: "good night", "going to bed", "lights out"

    1. All lights → off (except nightlights)
    2. All doors → lock
    3. Thermostat → 68°F (night setpoint)
    4. Blinds → close all
    5. TV/speakers → off
    ```

- **devices.md** — Device inventory with entity IDs, areas, and notes
  - Organized by area/room, then by device type
  - Include entity_id, friendly name, device model, and any quirks or notes
  - Format:
    ```markdown
    ## Living Room

    | Entity ID | Name | Type | Model | Notes |
    |-----------|------|------|-------|-------|
    | light.living_room_ceiling | Ceiling Light | light | Hue White Ambiance | Supports color_temp only |
    | light.living_room_lamp | Floor Lamp | light | LIFX A19 | Full RGB + color_temp |
    | sensor.living_room_temperature | Temperature | sensor | Aqara WSDCGQ11LM | Updates every 5 min |
    | binary_sensor.living_room_motion | Motion | binary_sensor | Hue Motion | 30s cooldown |
    | media_player.living_room_tv | TV | media_player | LG webOS | Sources: HDMI 1, HDMI 2, Netflix, YouTube |
    ```

- **automations.md** — Active automation inventory and tuning notes
  - Track which automations exist, what they do, and any issues/tuning needed
  - Format:
    ```markdown
    ## Active Automations

    ### Porch light at sunset
    - **entity**: automation.porch_light_sunset
    - **trigger**: sun → sunset, offset -15min
    - **action**: light.porch → on, brightness 200
    - **condition**: vacation_mode off
    - **status**: working well
    - **notes**: Adjusted offset from -30min to -15min on 2026-03-10

    ### Motion-activated hallway
    - **entity**: automation.hallway_motion_light
    - **trigger**: binary_sensor.hallway_motion → on
    - **action**: light.hallway → on for 3min
    - **status**: needs tuning — triggers too easily from pets
    ```

- **status.md** — Home health overview (Mission Control compatible)

- **tasks.md** — Kanban board for home maintenance, upgrades, and troubleshooting (Mission Control compatible)

- **timeline.md** — Reverse-chronological activity log (Mission Control compatible)
  - Auto-captures: device issues detected, automations created/modified, preferences updated, maintenance completed
  - Entries: `- HH:MM — Event description` grouped under `## YYYY-MM-DD` date headers
  - Use `append_timeline_event` tool to log events

- **notes.md** — HA configuration notes and reference
  - Integration status (which integrations are active, any issues)
  - Network layout (MQTT broker address, HA URL, Zigbee/Z-Wave coordinator)
  - Custom entity naming conventions
  - Dashboards inventory
  - HACS installed components

Create files as needed — not all files are required from the start. `preferences.md` and `routines.md` are the most important to populate early, as they enable the bot to act on your habits. Archive old automation tuning notes and resolved device issues to the archive/ folder.

### status.md — Home Status Format

```markdown
- **phase**: Active Monitoring
- **health**: green
- **updated**: 2026-04-01
- **owner**: Homeowner

## System Health
- **HA version**: 2026.4.0
- **Last checked**: 2026-04-01 08:00
- **Unavailable entities**: 0
- **Low battery devices**: 0
- **Pending updates**: 1 (HACS: custom-cards-frontend)

## Active Alerts
None — all systems operational

## Device Summary

| Area | Devices | Entities | Issues |
|------|---------|----------|--------|
| Living Room | 8 | 24 | — |
| Kitchen | 5 | 12 | — |
| Bedroom | 6 | 15 | — |
| Outdoor | 4 | 10 | 1 unavailable (sensor.mailbox_battery) |

## Automation Health
- **Total**: 12 active, 2 disabled
- **Failed (24h)**: 0
- **Last created**: "Porch light sunset" (2026-03-28)

## Energy (if monitored)
- **Today**: 18.4 kWh
- **This month**: 412 kWh
- **Top consumers**: HVAC (45%), Kitchen (20%), Entertainment (15%)
```

Health values: `green` (all devices connected, no failed automations, batteries OK), `yellow` (unavailable entities, low batteries, or failed automations), `red` (critical device offline, security sensor failure, or HVAC malfunction).

### tasks.md — Kanban Format

Use a markdown kanban board with these columns:

```markdown
## Backlog

### Set up motion-activated garage lights
- **id**: mc-a1b2c3
- **priority**: medium
- **tags**: automation, garage, lighting

### Research smart blinds for bedroom
- **id**: mc-d4e5f6
- **priority**: low
- **tags**: upgrade, bedroom, covers

## In Progress

### Fix hallway motion sensor sensitivity
- **id**: mc-g7h8i9
- **priority**: high
- **tags**: troubleshooting, automation, motion
- **started**: 2026-03-28

## Done

### Replace outdoor sensor battery
- **id**: mc-j0k1l2
- **priority**: medium
- **tags**: maintenance, battery
- **completed**: 2026-03-25
```

Each card follows the Mission Control card format:
- **id** (required): Unique `mc-XXXXXX` identifier (auto-generated by `create_task_card`)
- **priority**: `low`, `medium`, `high`, or `critical`
- **tags**: Comma-separated labels (e.g., automation, troubleshooting, upgrade, maintenance, battery, lighting, climate)
- **started** / **completed**: ISO date timestamps (auto-set by `move_task_card`)

Use `create_task_card` and `move_task_card` tools for all task management — tasks.md is a read-only rendering from the database and must not be edited directly.

### timeline.md — Activity Log

Reverse-chronological event stream capturing smart home activity:

```markdown
## 2026-04-01

- 08:00 — Heartbeat: all systems healthy, 0 unavailable entities, 0 low batteries
- 07:30 — Preference updated: bedroom morning brightness 70% → 60% (user: "a bit softer")

## 2026-03-28

- 20:15 — Routine "Movie Night" executed — 4 service calls successful
- 19:00 — Automation created: porch_light_sunset (trigger: sunset -15min)
- 14:00 — Card mc-g7h8i9 moved to **In Progress** — "Fix hallway motion sensor"
- 10:30 — Device added to inventory: sensor.garage_door_contact (Aqara)
```

Events are auto-logged by `move_task_card` and status changes. Use `append_timeline_event` to manually log notable events (device additions, automation changes, preference updates, routine executions, heartbeat results).

### Heartbeat Recommendations

| Frequency | Focus | Prompt Guidance |
|-----------|-------|----------------|
| **Daily** (recommended) | Device health, failed automations, battery levels | Check for unavailable entities, automation failures in last 24h, low batteries. Update status.md. |
| **Weekly** | Deeper audit, energy trends, automation review | Everything from daily + energy usage trends, automation trace analysis, HA update check, HACS updates. |
| **On demand** | User triggers | "Check the house" / "Home status" — full snapshot of current state |

### plans.md — Structured Execution Plans (Read-Only Rendering)

Plans are stored in the MC database. `plans.md` is auto-generated after every state change — never edit it directly. Use `draft_plan` to create plans, and `update_plan_step`/`update_plan_status` for mutations. After approval, the plan executor automatically sequences step execution. Pull the planning skill for the full protocol.
