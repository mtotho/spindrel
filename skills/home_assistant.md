---
name: Home Assistant
description: Home Assistant automation, configuration, and integration management
---
# SKILL: Home Assistant — Toth Home

## Integration Method
- HA is accessible via the agent's tool call (MCP or REST) — do NOT generate shell commands for HA control
- Entity names are used as-is from the context; match them exactly when calling services

## Areas & Entities

### Living Room
**Lights:**
- `Living Room Lights` (group)
- `Living Room Boob Light`
- `Living Room Floor Lamp`
- `Living Room Table Lamp`
- `WLED-Living Room Door Pipes` (addressable LED strip)
**Scenes:**
- `Living Room TV Watching`

**Other:**
- `Android TV 10.10.20.244` (media_player, TV)
- `Living Room - TV Smart Outlet` (switch — controls TV power)
- `Nest Thermostat` (climate)

**Sensors:**
- Temp: `Living Room Temperature Temperature` → 63.6°F
- Humidity: `Living Room Temperature Humidity` → 49.7%
- Motion: `Living Room Camera Motion`, `Living Room Motion Sensor Occupancy`, `Living Room Motion Door Occupancy`

---

### Kitchen
**Lights:**
- `Kitchen Lights` (group)
- `Kitchen Ceiling Lights`
- `Kitchen Coffee LED`
- `Kitchen Under Cabinet LED`
- `Cabinet LED Strip`
- `WLED-Kitchen Fairy Pipes` (addressable LED strip)

**Scenes:**
- `Kitchen Serious Use`

**Sensors:**
- Temp: `Kitchen Temperature Temperature` → 68.1°F
- Humidity: `Kitchen Temperature Humidity` → 76.6% (notably high)
- Motion: `Kitchen Camera Motion`, `Kitchen Motion Sensor Occupancy`
- `Fridge Door Sensor Door`
- `Freezer Door Sensor Door`

---

### Bedroom
**Lights:**
- `Bedroom Lights` (group)
- `Bedroom Boob Light`
- `Bedroom Lamp`
- `Bedroom Closet LED`
- `Bedroom Nightstand Lamp (Olivia)` — Olivia's side, treat with care
- `Master Bathroom Lights` (assigned to Bedroom area)
- `WLED-Bedroom Corner`
- `WLED-Bedroom Drawers`

**Scenes:**
- `Bedroom - LED Vibes`

**Other:**
- `Bedroom Fan Switch` (fan domain)

**Sensors:**
- Temp: `Bedroom Temperature Temperature` → 65.7°F
- Humidity: `Bedroom Temperature Humidity` → 54%
- Motion: `Bedroom Camera Motion`, `Bedroom Motion Sensor Occupancy`

---

### Master Bathroom
**Lights:**
- `Master Bathroom Boob`
- `Master Bathroom Mirror 1`
- `Master Bathroom Mirror 2`
- `Master Bathroom Mirror Lights` (group, no area assigned)
- `WLED-Bathroom Corner`

---

### Office
**Lights:**
- `Office Light Switch`
- `Office Desk LED Strip` (currently ON, dim — brightness 64)

**Sensors:**
- Temp: `Office Temperature Sensor Temperature` → 69.2°F
- Humidity: `Office Temperature Sensor Humidity` → 49.1%
- Server Room Temp: `Office Server Room Temperature Temperature` → 73.0°F
- Server Room Humidity: `Office Server Room Temperature Humidity` → 42%

---

### Stairwell
**Lights:**
- `Stairwell` (group)
- `Stairwell Bottom`
- `Stairwell Top`

**Scenes:**
- `Stairwell - Nighttime/Pre bed Illumination`

**Sensors:**
- `Stairwell Motion Sensor Occupancy`

---

### Outside
- `Front Door Lamp`
- `Outside Lights` (group)

---

## Climate
- **Nest Thermostat**
  - Mode: heat
  - Set point: 61°F
  - Current: ~64°F (above setpoint, not actively heating)
  - Humidity: 56%

---

## Global / Uncategorized
- `All Lights` — global light group
- `All Lights And Outside` — global + outside group
- `Optimal LED Brightness` (number) → 172.0 (circadian-derived target)
- `Optimal LED Temperature` (sensor) → 4537K (circadian color temp)
- `Zigbee2MQTT Bridge Permit join` (switch) — **do not toggle casually**, only for pairing new Zigbee devices

---

## Current State Snapshot (at skill load time)
| Entity | State |
|---|---|
| Kitchen Lights | ON (full brightness) |
| WLED-Kitchen Fairy Pipes | ON (full brightness) |
| Living Room Boob Light | ON (brightness 115) |
| Living Room Floor Lamp | ON (dim, 82) |
| Living Room Lights | ON (brightness 98) |
| WLED-Living Room Door Pipes | ON (half, 128) |
|