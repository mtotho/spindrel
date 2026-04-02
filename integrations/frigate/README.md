# Frigate NVR Integration

Connects your agent server to [Frigate NVR](https://frigate.video/) for camera monitoring and push-based detection alerts via MQTT.

## Features

- **Polling tools**: List cameras, query events, download snapshots/clips
- **Push events**: MQTT listener receives Frigate detections in real-time and forwards them to the agent server
- **Multi-channel fan-out**: Route events to multiple channels with per-channel filters
- **Per-binding filters**: Each channel binding can filter by camera, label, and minimum score
- **Global filters**: MQTT listener applies global camera/label/score/cooldown filters before forwarding

## Setup

### 1. Install dependencies

```bash
pip install -r integrations/frigate/requirements.txt
```

### 2. Environment variables

Add to your `.env`:

```env
# Required — Frigate NVR connection
FRIGATE_URL=http://frigate:5000

# Optional — API auth (if Frigate is behind a proxy with auth)
FRIGATE_API_KEY=

# Optional — MQTT push events (enables real-time alerts)
FRIGATE_MQTT_BROKER=mqtt-broker-hostname
FRIGATE_MQTT_PORT=1883
FRIGATE_MQTT_USERNAME=
FRIGATE_MQTT_PASSWORD=
FRIGATE_MQTT_TOPIC_PREFIX=frigate

# Optional — global event filtering (applied by MQTT listener before webhook)
FRIGATE_MQTT_CAMERAS=             # comma-separated, empty = all
FRIGATE_MQTT_LABELS=person,car    # comma-separated, empty = all
FRIGATE_MQTT_MIN_SCORE=0.6        # minimum detection confidence (0-1)
FRIGATE_MQTT_COOLDOWN=300         # seconds between alerts per camera+label
```

### 3. Create a channel and bind it

1. Create a channel in the admin UI
2. Set the bot on the channel (e.g. your security monitoring bot)
3. Bind the channel to `frigate:events` via the integrations tab
4. Optionally set per-binding filters in the binding's dispatch config

### 4. Running

If using `dev-server.sh`, the MQTT listener auto-starts when `FRIGATE_MQTT_BROKER` is set.

To run manually:

```bash
python integrations/frigate/mqtt_listener.py
```

## Architecture

```
Frigate NVR → MQTT broker → mqtt_listener.py (background process)
                                    ↓ (global filters + cooldown)
                            POST /integrations/frigate/webhook
                                    ↓
                            Router resolves bound channels
                                    ↓ (per-binding filters)
                            Inject message into each matching channel
                                    ↓
                            Bot processes event (has Frigate tools)
```

The MQTT listener connects to the Frigate MQTT broker, applies global filters and cooldown, then POSTs raw event payloads to the webhook endpoint. The router resolves all channels bound to `frigate:events`, applies per-binding filters, and injects messages into matching channels.

## Multi-Channel Routing

You can route different camera/label combinations to different channels:

**Channel "Front Door Alerts"** — bound to `frigate:events` with filter:
```json
{"cameras": "front_door", "labels": "person", "min_score": 0.7}
```

**Channel "All Vehicle Activity"** — bound to `frigate:events` with filter:
```json
{"cameras": "driveway,garage", "labels": "car"}
```

**Channel "Everything"** — bound to `frigate:events` with no filter (receives all events).

Each channel has its own bot, conversation history, and dispatch settings.

## Available Tools

| Tool | Description |
|------|-------------|
| `frigate_list_cameras` | List all configured cameras |
| `frigate_get_events` | Query detection events with filters |
| `frigate_get_snapshot_url` | Get URL for latest camera snapshot |
| `frigate_get_stats` | System statistics (FPS, CPU, detectors) |
| `frigate_snapshot` | Download latest snapshot as attachment |
| `frigate_event_snapshot` | Download event snapshot as attachment |
| `frigate_event_clip` | Download event video clip as attachment |
| `frigate_recording_clip` | Download recording clip for time range |

## Event Filtering Pipeline

Events pass through two filter stages:

### Stage 1: MQTT Listener (global filters)
Applied before the event reaches the server. Configured via env vars.

1. **Event type**: Only `type: "new"` (skip update/end)
2. **Camera allowlist**: `FRIGATE_MQTT_CAMERAS` (empty = all)
3. **Label allowlist**: `FRIGATE_MQTT_LABELS` (empty = all)
4. **Minimum score**: `FRIGATE_MQTT_MIN_SCORE` (default 0.6)
5. **Cooldown**: `FRIGATE_MQTT_COOLDOWN` per camera+label (default 300s)

### Stage 2: Webhook Router (per-binding filters)
Applied per-channel based on the binding's `dispatch_config`.

1. **Camera filter**: `cameras` field (comma-separated or list)
2. **Label filter**: `labels` field (comma-separated or list)
3. **Minimum score**: `min_score` field (0-1)

Empty/missing filter fields = accept all events.
