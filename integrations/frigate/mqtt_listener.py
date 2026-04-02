"""Frigate MQTT event listener — pushes detection events to the agent server.

Standalone process (like the Slack bot). Connects to MQTT broker, subscribes
to Frigate event topics, applies global filters + cooldown, and POSTs raw
payloads to the Frigate webhook endpoint for channel fan-out.

Usage:
    pip install -r integrations/frigate/requirements.txt
    python integrations/frigate/mqtt_listener.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("frigate.mqtt")

import httpx

# aiomqtt is lazy-imported in run() so the module can be imported for
# testing without the optional dependency installed.

# ---------------------------------------------------------------------------
# Configuration (env vars, same as config.py but standalone-safe)
# ---------------------------------------------------------------------------

MQTT_BROKER = os.environ.get("FRIGATE_MQTT_BROKER", "")
MQTT_PORT = int(os.environ.get("FRIGATE_MQTT_PORT", 1883))
MQTT_USERNAME = os.environ.get("FRIGATE_MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("FRIGATE_MQTT_PASSWORD", "")
MQTT_TOPIC_PREFIX = os.environ.get("FRIGATE_MQTT_TOPIC_PREFIX", "frigate")

AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("AGENT_API_KEY", "")

# Filters
CAMERA_FILTER: list[str] = [
    c.strip()
    for c in os.environ.get("FRIGATE_MQTT_CAMERAS", "").split(",")
    if c.strip()
]
LABEL_FILTER: list[str] = [
    lb.strip()
    for lb in os.environ.get("FRIGATE_MQTT_LABELS", "").split(",")
    if lb.strip()
]
MIN_SCORE = float(os.environ.get("FRIGATE_MQTT_MIN_SCORE", 0.6))
COOLDOWN_SECONDS = int(os.environ.get("FRIGATE_MQTT_COOLDOWN", 300))

# ---------------------------------------------------------------------------
# Cooldown tracker
# ---------------------------------------------------------------------------

_cooldowns: dict[str, float] = {}


def check_cooldown(camera: str, label: str, now: float | None = None) -> bool:
    """Return True if this camera+label is allowed (not in cooldown)."""
    if COOLDOWN_SECONDS <= 0:
        return True
    key = f"{camera}:{label}"
    now = now if now is not None else time.time()
    last = _cooldowns.get(key, 0.0)
    if now - last < COOLDOWN_SECONDS:
        return False
    _cooldowns[key] = now
    return True


def reset_cooldowns() -> None:
    """Clear all cooldown state (for testing)."""
    _cooldowns.clear()


# ---------------------------------------------------------------------------
# Event filtering
# ---------------------------------------------------------------------------


def should_process_event(event: dict) -> bool:
    """Apply all configured filters to a Frigate event payload.

    Returns True if the event should be forwarded to the agent server.
    """
    # Only "new" events
    event_type = event.get("type", "")
    if event_type != "new":
        return False

    before = event.get("before", {})
    after = event.get("after", {})
    # Use "after" state which has the latest data
    data = after if after else before

    camera = data.get("camera", "")
    label = data.get("label", "")
    score = data.get("top_score") or data.get("score") or 0.0
    if isinstance(score, str):
        score = float(score)

    # Camera filter
    if CAMERA_FILTER and camera not in CAMERA_FILTER:
        return False

    # Label filter
    if LABEL_FILTER and label not in LABEL_FILTER:
        return False

    # Min score
    if score < MIN_SCORE:
        return False

    # Cooldown
    if not check_cooldown(camera, label):
        return False

    return True


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def format_event_message(event: dict) -> str:
    """Format a Frigate event into a message for the agent server."""
    after = event.get("after", {})
    data = after if after else event.get("before", {})

    camera = data.get("camera", "unknown")
    label = data.get("label", "unknown")
    score = data.get("top_score") or data.get("score") or 0
    if isinstance(score, str):
        score = float(score)
    zones = data.get("current_zones", []) or data.get("zones", [])
    event_id = data.get("id", "unknown")
    has_snapshot = data.get("has_snapshot", False)
    has_clip = data.get("has_clip", False)

    start_time = data.get("start_time")
    if start_time:
        dt = datetime.fromtimestamp(float(start_time), tz=timezone.utc)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        time_str = "unknown"

    lines = [
        f"[Frigate event] New detection on {camera}",
        "",
        f"- Object: {label} (score: {score:.0%})",
    ]
    if zones:
        lines.append(f"- Zones: {', '.join(zones)}")
    lines.extend([
        f"- Event ID: {event_id}",
        f"- Snapshot available: {has_snapshot}",
        f"- Clip available: {has_clip}",
        f"- Time: {time_str}",
        "",
        "Use frigate_event_snapshot to fetch the image. Respond according to your instructions.",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent server HTTP client
# ---------------------------------------------------------------------------

http = httpx.AsyncClient(timeout=120.0)


async def post_webhook(event_payload: dict) -> None:
    """POST a raw Frigate event payload to the webhook endpoint for fan-out."""
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    try:
        r = await http.post(
            f"{AGENT_BASE_URL}/integrations/frigate/webhook",
            json=event_payload,
            headers=headers,
        )
        r.raise_for_status()
        logger.info("Posted event to webhook (status=%d)", r.status_code)
    except Exception:
        logger.exception("Failed to post event to webhook")


# ---------------------------------------------------------------------------
# MQTT main loop
# ---------------------------------------------------------------------------


async def run() -> None:
    try:
        import aiomqtt
    except ImportError:
        logger.error(
            "aiomqtt is not installed. Run: pip install -r integrations/frigate/requirements.txt"
        )
        sys.exit(1)

    if not MQTT_BROKER:
        logger.error("FRIGATE_MQTT_BROKER is not set — exiting")
        sys.exit(1)

    topic = f"{MQTT_TOPIC_PREFIX}/events"
    logger.info(
        "Connecting to MQTT broker %s:%d, topic=%s, webhook=%s/integrations/frigate/webhook",
        MQTT_BROKER, MQTT_PORT, topic, AGENT_BASE_URL,
    )
    if CAMERA_FILTER:
        logger.info("Camera filter: %s", CAMERA_FILTER)
    if LABEL_FILTER:
        logger.info("Label filter: %s", LABEL_FILTER)
    logger.info("Min score: %.0f%%, Cooldown: %ds", MIN_SCORE * 100, COOLDOWN_SECONDS)

    while True:
        try:
            async with aiomqtt.Client(
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
                username=MQTT_USERNAME or None,
                password=MQTT_PASSWORD or None,
            ) as client:
                await client.subscribe(topic)
                logger.info("Subscribed to %s", topic)

                async for msg in client.messages:
                    try:
                        payload = json.loads(msg.payload)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Non-JSON MQTT message on %s", msg.topic)
                        continue

                    if not should_process_event(payload):
                        continue

                    camera = (payload.get("after") or payload.get("before", {})).get("camera", "?")
                    label = (payload.get("after") or payload.get("before", {})).get("label", "?")
                    logger.info("Processing event: %s detected on %s", label, camera)
                    await post_webhook(payload)

        except aiomqtt.MqttError as e:
            logger.error("MQTT connection error: %s — reconnecting in 5s", e)
            await asyncio.sleep(5)
        except Exception:
            logger.exception("Unexpected error — reconnecting in 5s")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
