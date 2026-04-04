---
name: "Camera Monitoring"
category: workspace_schema
description: Security camera monitoring with Frigate NVR — detection event tracking, camera health, zone activity, and alert management.
compatible_integrations:
  - frigate
tags: security, cameras, nvr, frigate, detection, iot
recommended_heartbeat:
  prompt: "Check camera health with frigate_get_stats and frigate_list_cameras. Update status.md with any cameras offline or degraded. Review recent detections with frigate_get_events(limit=20) and log notable events to events.md. Check for detection anomalies (unusual activity spikes or dead cameras)."
  interval: "hourly"
  quiet_start: "02:00"
  quiet_end: "06:00"
---

## Workspace File Organization — Camera Monitoring

Organize channel workspace files to track your Frigate NVR system. Root `.md` files are injected into every context — keep them concise and current.

### Root Files (auto-injected)

- **status.md** — System health and camera overview (updated every heartbeat)
  - Per-camera status: online/offline, FPS, resolution, detection enabled
  - Detector performance (inference speed, CPU/memory)
  - Alert summary: recent notable detections
  - Any cameras or zones needing attention

- **events.md** — Rolling log of notable detection events
  - Recent detections worth tracking (person, vehicle, package)
  - Events the user flagged for follow-up
  - Detection patterns (recurring false positives, new activity)

- **notes.md** — Configuration notes, detection tuning, and preferences
  - Alert preferences per zone (e.g., "ignore cats on driveway")
  - Detection sensitivity notes
  - User notification preferences

### Optional Files (create as needed)

- **devices.md** — Camera inventory and zone configuration
  - Each camera: name, location, resolution, FPS, model
  - Defined zones per camera with purpose (driveway, porch, street, etc.)
  - Detection labels enabled per camera
  - Create when managing multiple cameras or doing inventory work

- **maintenance.md** — Maintenance schedule and history
  - Firmware update status per camera
  - Lens cleaning schedule, detection model updates
  - Create when tracking recurring maintenance tasks
  - Alert preferences per zone (e.g., "ignore cats on driveway")
  - Detection sensitivity notes
  - User notification preferences (what warrants an alert vs. silent log)

### Archive (`archive/`)

Old event logs and resolved maintenance items. Searchable via `search_channel_archive`.

---

## File Formats

### status.md — System Health

```markdown
## System Health
- **status**: Online — all cameras operational
- **updated**: 2026-03-28 14:00
- **detector**: Coral TPU — 8.2ms inference

## Cameras

| Camera | Status | FPS | Resolution | Detection | Notes |
|--------|--------|-----|------------|-----------|-------|
| front_door | online | 15 | 1920x1080 | person, car, package | |
| backyard | online | 10 | 1280x720 | person, dog, cat | |
| driveway | online | 15 | 1920x1080 | person, car, motorcycle | |
| garage | offline | — | — | — | Power issue since 03-27 |

## Recent Alerts
- 2026-03-28 13:45 — person detected on front_door (score: 0.91) — delivery driver
- 2026-03-28 09:15 — car detected on driveway (score: 0.85) — neighbor parking

## Current Issues
- garage camera offline since 2026-03-27 — needs power cycle
```

### events.md — Detection Event Log

Rolling log of notable events. Most recent at top. Trim entries older than 2 weeks.

```markdown
## 2026-03-28

### 13:45 — Person at front door (front_door)
- **score**: 0.91
- **zones**: porch, walkway
- **event_id**: 1774889100.abc123
- **action**: Delivery driver — package left on porch
- **snapshot**: fetched and reviewed

### 09:15 — Car on driveway (driveway)
- **score**: 0.85
- **zones**: driveway
- **event_id**: 1774872900.def456
- **action**: Neighbor vehicle — no concern

## 2026-03-27

### 22:30 — Person at front door (front_door)
- **score**: 0.72
- **zones**: porch
- **event_id**: 1774836600.ghi789
- **action**: False positive — shadow from tree branch
- **note**: Consider adjusting zone mask for porch area at night
```

**Event logging rules:**
- Log detections with score ≥ 0.7 (high confidence) or any the user explicitly wants tracked
- Include event_id so clips/snapshots can be retrieved later with `frigate_event_clip` or `frigate_event_snapshot`
- Note the action taken or assessment (delivery, false positive, unknown person, etc.)
- Flag recurring false positives for zone/mask tuning
- Archive entries older than 2 weeks to `archive/YYYY-MM/events.md`

### devices.md — Camera Inventory

```markdown
## Camera Inventory

### front_door
- **location**: Front entrance, mounted above door frame
- **model**: Reolink RLC-810A
- **resolution**: 1920x1080 @ 15 FPS
- **detection labels**: person, car, package, dog
- **zones**: porch (primary alert zone), walkway, street (suppress alerts)
- **notes**: Night vision good, slight glare from porch light after 8pm

### backyard
- **location**: Back of house, covers patio and fence line
- **model**: Reolink RLC-520A
- **resolution**: 1280x720 @ 10 FPS
- **detection labels**: person, dog, cat
- **zones**: patio, fence_line, garden
- **notes**: Detection range limited at night — consider IR supplement

### driveway
- **location**: Garage corner, covers full driveway
- **model**: Reolink RLC-810A
- **resolution**: 1920x1080 @ 15 FPS
- **detection labels**: person, car, motorcycle, bicycle
- **zones**: driveway, sidewalk (suppress)
- **notes**: Wide angle, good coverage
```

### Guidelines

- **Detection scores**: 0.7+ = high confidence, 0.5–0.7 = moderate (worth checking), below 0.5 = likely noise
- **Timestamps**: Frigate uses Unix epoch seconds for all time parameters — convert to human-readable in event logs
- **Clips**: Max 10 minutes, 50MB. Use `frigate_event_clip(event_id)` for detection clips, `frigate_recording_clip(camera, start, end)` for raw recording segments
- **Snapshots**: `frigate_snapshot(camera)` for live view, `frigate_event_snapshot(event_id)` for detection snapshots
- **System health**: `frigate_get_stats()` for CPU, memory, detector speed, per-camera FPS — a camera at 0 FPS is offline
- **False positive tuning**: Track recurring false positives in events.md notes → adjust zone masks or minimum score in Frigate config
- **Archive**: Rotate events.md entries older than ~2 weeks into `archive/YYYY-MM/events.md`
