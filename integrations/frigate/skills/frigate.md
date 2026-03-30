---
name: Frigate NVR
description: Frigate camera tools — monitoring, snapshots, clips, detection events
---
# SKILL: Frigate NVR

## Overview
Camera monitoring and detection event handling for Frigate NVR. Tools query the Frigate API for camera status, detection events, and media downloads. MQTT push events deliver real-time detections as incoming messages.

## Tools

### Query Tools
- `frigate_list_cameras` — all cameras with resolution, FPS, enabled status, snapshot URLs
- `frigate_get_events` — detection events with filters (camera, label, zone, time range). Paginate with `before` param.
- `frigate_get_snapshot_url` — direct URL for a camera's latest frame (for linking, not downloading)
- `frigate_get_stats` — system health: per-camera FPS, detector inference speed, CPU/memory

### Media Download Tools (return attachment_id — use post_attachment to display)
- `frigate_snapshot` — download latest camera snapshot as image attachment
- `frigate_event_snapshot` — download snapshot from a specific detection event
- `frigate_event_clip` — download video clip from a detection event (max 50MB)
- `frigate_recording_clip` — download recording for a time range (max 10 min, max 50MB)

### Posting & Analysis
- `post_attachment` — post any attachment (image, video, file) into chat by attachment_id
- `list_attachments` — list recent attachments with auto-generated descriptions (useful for reviewing multiple snapshots)
- `describe_attachment` — answer a specific question about an image (makes a vision call) if you are unable to do so yourself; without a prompt returns 

## Handling MQTT Push Events

Incoming messages from the MQTT listener look like:

```
[Frigate event] New detection on front_door

- Object: person (score: 87%)
- Zones: driveway
- Event ID: 1234567890.abcdef
- Snapshot available: True
- Clip available: False
- Time: 2026-03-29 14:30:00 UTC
```

When you receive a `[Frigate event]` message:
1. Call `frigate_event_snapshot(event_id="...")` to fetch the image
2. Analyze the snapshot — describe what you see
3. Respond based on your system prompt instructions (notify, log, escalate, etc.)
4. If the event has `Clip available: True` and more context is needed, fetch with `frigate_event_clip`

## Key Workflows

### Check what's happening on cameras
1. `frigate_list_cameras` — see which cameras are active
2. `frigate_snapshot(camera="front_door")` — grab current frame
3. Describe what you see in the image

### Review recent detections
1. `frigate_get_events(limit=10)` — latest events across all cameras
2. Filter by camera/label: `frigate_get_events(camera="backyard", label="person")`
3. For interesting events: `frigate_event_snapshot(event_id="...")` to see what was detected

### Investigate a specific time period
1. `frigate_get_events(camera="garage", after=1711700000, before=1711703600)` — events in time window
2. `frigate_recording_clip(camera="garage", start_time=1711700000, end_time=1711700300)` — raw recording

### Check system health
1. `frigate_get_stats` — look for cameras with 0 FPS (offline) or high inference times


## Efficient Workflows

**Key insight:** Downloaded images are automatically described by a vision model in the background. You can download multiple snapshots at once, then use `list_attachments` to review all descriptions and only post the relevant ones. This saves tool calls vs describing one at a time.

### "What happened on the driveway in the last hour?"
1. `frigate_get_events(camera="driveway", after=<unix_timestamp_1h_ago>)`
2. For interesting events: `frigate_event_snapshot(event_id="...")` → get attachment_id
3. `post_attachment(attachment_id="...")` to show each snapshot
4. If user wants video: `frigate_event_clip(event_id="...")` → `post_attachment(...)`

### "Is there a package on the front porch?"
1. `frigate_snapshot(camera="front_porch")` → get attachment_id
2. `describe_attachment(attachment_id="...", prompt="Is there a package or delivery on the porch?")` — specific question needs a fresh vision call

### "Show me the driveway from 2pm to 2:05pm"
1. Convert times to Unix timestamps
2. `frigate_recording_clip(camera="driveway", start_time=..., end_time=...)` → get attachment_id
3. `post_attachment(attachment_id="...")`

## Common Patterns
- **Event IDs**: Get from `frigate_get_events` results, pass to `frigate_event_snapshot` / `frigate_event_clip`
- **Pagination**: `frigate_get_events` returns `next_before` — pass it as `before` to get the next page
- **Scores**: 0-1 float. Above 0.7 is high confidence. Below 0.5 is likely a false positive.
- **Zones**: Named areas configured in Frigate (e.g. driveway, porch, street). Empty means object wasn't in a defined zone.
- **Timestamps**: All Unix epoch seconds. Use `after`/`before` params for time filtering.

## Timestamp Handling
- All Frigate time parameters use **Unix epoch seconds** (e.g. `1711300800`)
- Convert human-readable times using the user's timezone
- Event results include `start_time` and `end_time` as Unix floats

## Limitations
- Recording clips: max **10 minutes** duration per request
- Video downloads: max **50 MB** file size
- Recording clips are stitched on-the-fly by Frigate — may take several seconds for longer clips
- Snapshot downloading fetches the full image; for just a URL, use `frigate_get_snapshot_url`

## Object Labels
Common Frigate detection labels: `person`, `car`, `dog`, `cat`, `bird`, `motorcycle`, `bicycle`, `truck`, `bus`. The exact labels depend on the detection model configured in Frigate.
