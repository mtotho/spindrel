---
name: Frigate NVR
description: Frigate NVR camera monitoring, event lookup, and media posting
---
# SKILL: Frigate NVR

## Overview
Frigate is a local NVR (network video recorder) with AI object detection. You can list cameras, query detection events, check system health, and **download snapshots and video clips then post them into chat**.

## Tools

### Query tools (return JSON metadata)
- `frigate_list_cameras` — discover available camera names, resolution, FPS
- `frigate_get_events` — search detection events by camera, label, zone, time range
- `frigate_get_snapshot_url` — get a URL to the latest camera frame (user opens it themselves)
- `frigate_get_stats` — system health: FPS, detector speed, CPU/memory

### Download tools (return attachment_id)
- `frigate_snapshot` — download the current camera frame as an attachment
- `frigate_event_snapshot` — download an event's best detection snapshot as an attachment
- `frigate_event_clip` — download an event's MP4 video clip as an attachment
- `frigate_recording_clip` — download a time-range recording clip from a camera as an attachment

### Posting & Analysis
- `post_attachment` — post any attachment (image, video, file) into chat by attachment_id
- `list_attachments` — list recent attachments with auto-generated descriptions (useful for reviewing multiple snapshots)
- `describe_attachment` — answer a specific question about an image (makes a vision call); without a prompt returns the auto-generated description

## Efficient Workflows

**Key insight:** Downloaded images are automatically described by a vision model in the background. You can download multiple snapshots at once, then use `list_attachments` to review all descriptions and only post the relevant ones. This saves tool calls vs describing one at a time.

### "Show me the front door"
1. `frigate_snapshot(camera="front_door")` → get attachment_id
2. `post_attachment(attachment_id="...")`

### "Check all the cameras for anything unusual"
1. Download snapshots from multiple cameras (can call `frigate_snapshot` multiple times in one turn)
2. `list_attachments(limit=10)` → review the auto-generated descriptions for each
3. Report findings; `post_attachment` only the interesting ones

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
