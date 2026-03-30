# Frigate NVR Integration

Connects your agent server to [Frigate NVR](https://frigate.video/) for camera monitoring and push-based detection alerts via MQTT.

## Features

- **Polling tools**: List cameras, query events, download snapshots/clips
- **Push events**: MQTT listener receives Frigate detections in real-time and forwards them to the agent server
- **Filtering**: Camera allowlist, label allowlist, minimum confidence score, per-camera+label cooldown

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

# Required for MQTT — which bot handles Frigate events
FRIGATE_BOT_ID=your-frigate-bot-id
FRIGATE_CLIENT_ID=frigate:events

# Optional — event filtering
FRIGATE_MQTT_CAMERAS=             # comma-separated, empty = all
FRIGATE_MQTT_LABELS=person,car    # comma-separated, empty = all
FRIGATE_MQTT_MIN_SCORE=0.6        # minimum detection confidence (0-1)
FRIGATE_MQTT_COOLDOWN=300         # seconds between alerts per camera+label
```

### 3. Bot configuration

Create a bot YAML that has the Frigate tools available. The MQTT listener posts events to this bot. Example `bots/security.yaml`:

```yaml
id: security
name: Security Monitor
model: gemini/gemini-2.5-flash
system_prompt: |
  You are a security monitoring assistant. When you receive Frigate detection
  events, fetch the snapshot with frigate_event_snapshot, analyze the image,
  and report significant detections.
```

### 4. Running

If using `dev-server.sh`, the MQTT listener auto-starts when `FRIGATE_MQTT_BROKER` and `FRIGATE_BOT_ID` are set.

To run manually:

```bash
python integrations/frigate/mqtt_listener.py
```

## Architecture

```
Frigate NVR → MQTT broker → mqtt_listener.py (background process)
                                    ↓
                            POST /chat (agent server API)
                                    ↓
                            Bot processes event (has Frigate tools)
                                    ↓
                            Response dispatched to channel
```

The MQTT listener is just another client — like the Slack bot. It receives Frigate events, formats them as messages, and POSTs to the agent server.

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

MQTT events pass through these filters in order:

1. **Event type**: Only `type: "new"` (skip update/end)
2. **Camera allowlist**: `FRIGATE_MQTT_CAMERAS` (empty = all)
3. **Label allowlist**: `FRIGATE_MQTT_LABELS` (empty = all)
4. **Minimum score**: `FRIGATE_MQTT_MIN_SCORE` (default 0.6)
5. **Cooldown**: `FRIGATE_MQTT_COOLDOWN` per camera+label (default 300s)
