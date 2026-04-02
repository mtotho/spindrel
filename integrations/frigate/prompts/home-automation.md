---
category: workspace_schema
description: Home automation hub — device inventory, automation rules, camera events, and maintenance logs.
compatible_integrations: frigate
tags: home, automation, cameras, iot
---
## Workspace File Organization — Home Automation

Organize channel workspace files as follows:

- **devices.md** — Device inventory: names, locations, types, connection status, notes
- **automations.md** — Active automation rules: triggers, conditions, actions, and schedules
- **events.md** — Notable events log: camera detections, sensor alerts, unusual patterns
- **maintenance.md** — Maintenance tasks: firmware updates, battery replacements, calibration, troubleshooting
- **notes.md** — Configuration notes, network layout, integration credentials reference

### Guidelines
- Keep devices.md as a living inventory — update when devices are added, moved, or removed
- Log camera events (Frigate detections) in events.md with timestamps and zones
- Track automation rules in automations.md with clear trigger → action descriptions
- Use maintenance.md for recurring tasks (filter changes, battery swaps, firmware checks)
- Archive resolved events and completed maintenance to the archive/ folder
