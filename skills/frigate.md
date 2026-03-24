---
name: Frigate NVR
description: Frigate NVR camera monitoring, event lookup, and media posting
---
# SKILL: Frigate NVR

## Overview
Frigate is a local NVR (network video recorder) with AI object detection. You can list cameras, query detection events, check system health, and **post snapshots and video clips directly into the chat**.

## Tools

### Query tools (return JSON metadata)
- `frigate_list_cameras` — discover available camera names, resolution, FPS
- `frigate_get_events` — search detection events by camera, label, zone, time range
- `frigate_get_snapshot_url` — get a URL to the latest camera frame (user opens it themselves)
- `frigate_get_stats` — system health: FPS, detector speed, CPU/memory

### Media posting tools (upload images/video inline)
- `frigate_post_camera_snapshot` — post the current camera frame into chat
- `frigate_post_event_snapshot` — post an event's best detection snapshot into chat
- `frigate_post_event_clip` — post an event's MP4 video clip into chat
- `frigate_post_recording_clip` — post a time-range recording clip from a camera

## Common Workflows

### "Show me the front door"
1. `frigate_post_camera_snapshot(camera="front_door")`

### "What happened on the driveway in the last hour?"
1. `frigate_get_events(camera="driveway", after=<unix_timestamp_1h_ago>)`
2. For interesting events: `frigate_post_event_snapshot(event_id="...")`
3. If user wants video: `frigate_post_event_clip(event_id="...")`

### "Show me the driveway from 2pm to 2:05pm"
1. Convert times to Unix timestamps
2. `frigate_post_recording_clip(camera="driveway", start_time=..., end_time=...)`

## Timestamp Handling
- All Frigate time parameters use **Unix epoch seconds** (e.g. `1711300800`)
- Convert human-readable times using the user's timezone
- Event results include `start_time` and `end_time` as Unix floats

## Limitations
- Recording clips: max **10 minutes** duration per request
- Video downloads: max **50 MB** file size
- Recording clips are stitched on-the-fly by Frigate — may take several seconds for longer clips
- Snapshot posting downloads the full image; for just a URL, use `frigate_get_snapshot_url`

## Object Labels
Common Frigate detection labels: `person`, `car`, `dog`, `cat`, `bird`, `motorcycle`, `bicycle`, `truck`, `bus`. The exact labels depend on the detection model configured in Frigate.
