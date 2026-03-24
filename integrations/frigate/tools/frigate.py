"""Frigate NVR camera tools. Requires FRIGATE_URL in .env."""

import base64
import json
import logging
from typing import Optional

import httpx

from app.config import settings
from app.tools.registry import register

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return settings.FRIGATE_URL.rstrip("/")


def _headers() -> dict[str, str]:
    h: dict[str, str] = {}
    if settings.FRIGATE_API_KEY:
        h["Authorization"] = f"Bearer {settings.FRIGATE_API_KEY}"
    return h


async def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    """GET helper. Returns parsed JSON or raises."""
    url = f"{_base_url()}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(), params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()


def _error(msg: str) -> str:
    return json.dumps({"error": msg})


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "frigate_list_cameras",
        "description": (
            "List all cameras configured in Frigate NVR. Returns camera names, "
            "detect resolution, and enabled status. Use this to discover available "
            "cameras before querying events or snapshots."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def frigate_list_cameras() -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")
    try:
        config = await _get("/api/config")
        cameras = config.get("cameras", {})
        result = []
        for name, cam in cameras.items():
            detect = cam.get("detect", {})
            result.append({
                "name": name,
                "enabled": detect.get("enabled", True),
                "width": detect.get("width"),
                "height": detect.get("height"),
                "fps": detect.get("fps"),
                "snapshot_url": f"{_base_url()}/api/{name}/latest.jpg",
            })
        return json.dumps({"cameras": result})
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_list_cameras failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "frigate_get_events",
        "description": (
            "Get recent detection events from Frigate NVR cameras. Returns events "
            "with detected object labels (person, car, dog, etc.), timestamps, zones, "
            "and thumbnail/snapshot URLs. Use to answer questions like 'has anyone been "
            "outside?' or 'what activity has there been on the driveway?'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "camera": {
                    "type": "string",
                    "description": "Filter by camera name. Omit for all cameras.",
                },
                "label": {
                    "type": "string",
                    "description": "Filter by object label (e.g. 'person', 'car', 'dog', 'cat').",
                },
                "zone": {
                    "type": "string",
                    "description": "Filter by zone name (as configured in Frigate).",
                },
                "after": {
                    "type": "number",
                    "description": "Only events after this Unix timestamp.",
                },
                "before": {
                    "type": "number",
                    "description": "Only events before this Unix timestamp.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max events to return (default 20).",
                },
                "favorites": {
                    "type": "boolean",
                    "description": "Only return favorited/starred events.",
                },
            },
        },
    },
})
async def frigate_get_events(
    camera: Optional[str] = None,
    label: Optional[str] = None,
    zone: Optional[str] = None,
    after: Optional[float] = None,
    before: Optional[float] = None,
    limit: int = 20,
    favorites: Optional[bool] = None,
) -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")
    try:
        params: dict = {"limit": limit}
        if camera:
            params["camera"] = camera
        if label:
            params["label"] = label
        if zone:
            params["zone"] = zone
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        if favorites is not None:
            params["favorites"] = 1 if favorites else 0

        events = await _get("/api/events", params=params)
        results = []
        for ev in events:
            eid = ev.get("id", "")
            results.append({
                "id": eid,
                "camera": ev.get("camera"),
                "label": ev.get("label"),
                "sub_label": ev.get("sub_label"),
                "top_score": round(ev.get("top_score", 0), 3),
                "start_time": ev.get("start_time"),
                "end_time": ev.get("end_time"),
                "zones": ev.get("zones", []),
                "has_snapshot": ev.get("has_snapshot", False),
                "has_clip": ev.get("has_clip", False),
                "thumbnail_url": f"{_base_url()}/api/events/{eid}/thumbnail.jpg",
                "snapshot_url": f"{_base_url()}/api/events/{eid}/snapshot.jpg" if ev.get("has_snapshot") else None,
                "clip_url": f"{_base_url()}/api/events/{eid}/clip.mp4" if ev.get("has_clip") else None,
            })
        return json.dumps({"events": results, "count": len(results)})
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_get_events failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "frigate_get_snapshot_url",
        "description": (
            "Get the URL for the latest snapshot from a Frigate camera. "
            "Returns a direct URL the user can open to view the current camera frame. "
            "Optionally include bounding boxes for detected objects."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "camera": {
                    "type": "string",
                    "description": "Camera name (use frigate_list_cameras to discover names).",
                },
                "bounding_box": {
                    "type": "boolean",
                    "description": "Include bounding boxes for detected objects (default true).",
                },
                "quality": {
                    "type": "integer",
                    "description": "JPEG quality 1-100 (default 70).",
                },
            },
            "required": ["camera"],
        },
    },
})
async def frigate_get_snapshot_url(
    camera: str,
    bounding_box: bool = True,
    quality: int = 70,
) -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")

    params = []
    if bounding_box:
        params.append("bbox=1")
    if quality != 70:
        params.append(f"quality={quality}")

    url = f"{_base_url()}/api/{camera}/latest.jpg"
    if params:
        url += "?" + "&".join(params)

    return json.dumps({
        "camera": camera,
        "snapshot_url": url,
        "note": "Open this URL to view the latest camera frame.",
    })


@register({
    "type": "function",
    "function": {
        "name": "frigate_get_stats",
        "description": (
            "Get Frigate NVR system statistics. Returns per-camera detection FPS, "
            "process stats, CPU/memory usage, and detector inference speed. "
            "Use to check system health or camera status."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def frigate_get_stats() -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")
    try:
        stats = await _get("/api/stats")

        # Summarize per-camera stats
        camera_stats = {}
        for name, cam in stats.get("cameras", {}).items():
            camera_stats[name] = {
                "camera_fps": cam.get("camera_fps"),
                "detection_fps": cam.get("detection_fps"),
                "process_fps": cam.get("process_fps"),
                "pid": cam.get("pid"),
            }

        # Detector stats
        detectors = {}
        for name, det in stats.get("detectors", {}).items():
            detectors[name] = {
                "inference_speed": det.get("inference_speed"),
                "pid": det.get("pid"),
            }

        return json.dumps({
            "cameras": camera_stats,
            "detectors": detectors,
            "service": stats.get("service", {}),
        }, default=str)
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_get_stats failed")
        return _error(str(e))


# ---------------------------------------------------------------------------
# Media posting helpers
# ---------------------------------------------------------------------------


async def _get_bytes(path: str, params: dict | None = None, timeout: float = 30.0) -> bytes:
    """Binary GET from Frigate. Returns raw bytes."""
    url = f"{_base_url()}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(), params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.content


async def _post_media(
    path: str,
    *,
    params: dict | None = None,
    filename: str,
    mime_type: str,
    caption: str = "",
    max_bytes: int | None = None,
    timeout: float = 30.0,
) -> str:
    """Download binary from Frigate → persist as attachment → return client_action."""
    from app.agent.context import current_bot_id, current_channel_id, current_dispatch_type
    from app.services.attachments import create_attachment

    data = await _get_bytes(path, params=params, timeout=timeout)

    if max_bytes and len(data) > max_bytes:
        mb = max_bytes / 1_048_576
        return _error(f"File too large ({len(data)} bytes). Max allowed: {mb:.0f} MB.")

    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()
    source = current_dispatch_type.get() or "web"

    is_image = mime_type.startswith("image/")
    action_type = "upload_image" if is_image else "upload_file"

    try:
        await create_attachment(
            message_id=None,
            channel_id=channel_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(data),
            posted_by=bot_id or "frigate",
            source_integration=source,
            file_data=data,
            attachment_type="image" if is_image else "video",
            bot_id=bot_id,
        )
    except Exception:
        logger.warning("Failed to persist frigate attachment %s", filename, exc_info=True)

    b64 = base64.b64encode(data).decode("ascii")
    return json.dumps({
        "message": f"Posted {filename}" + (f": {caption}" if caption else ""),
        "client_action": {
            "type": action_type,
            "data": b64,
            "filename": filename,
            "caption": caption,
        },
    })


# ---------------------------------------------------------------------------
# Media posting tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "frigate_post_camera_snapshot",
        "description": (
            "Post the latest camera snapshot image directly into the chat. "
            "Downloads the current frame from a Frigate camera and uploads it inline. "
            "Use this instead of frigate_get_snapshot_url when you want the image visible in chat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "camera": {
                    "type": "string",
                    "description": "Camera name (use frigate_list_cameras to discover names).",
                },
                "bounding_box": {
                    "type": "boolean",
                    "description": "Include bounding boxes for detected objects (default true).",
                },
                "quality": {
                    "type": "integer",
                    "description": "JPEG quality 1-100 (default 70).",
                },
            },
            "required": ["camera"],
        },
    },
})
async def frigate_post_camera_snapshot(
    camera: str,
    bounding_box: bool = True,
    quality: int = 70,
) -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")
    try:
        params: dict = {}
        if bounding_box:
            params["bbox"] = 1
        if quality != 70:
            params["quality"] = quality
        return await _post_media(
            f"/api/{camera}/latest.jpg",
            params=params,
            filename=f"{camera}_snapshot.jpg",
            mime_type="image/jpeg",
            caption=f"Latest snapshot from {camera}",
        )
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_post_camera_snapshot failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "frigate_post_event_snapshot",
        "description": (
            "Post the snapshot image from a Frigate detection event into the chat. "
            "Downloads the event's best snapshot and uploads it inline. "
            "Use after frigate_get_events to show what was detected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Frigate event ID (from frigate_get_events results).",
                },
            },
            "required": ["event_id"],
        },
    },
})
async def frigate_post_event_snapshot(event_id: str) -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")
    try:
        return await _post_media(
            f"/api/events/{event_id}/snapshot.jpg",
            filename=f"event_{event_id}_snapshot.jpg",
            mime_type="image/jpeg",
            caption=f"Event {event_id} snapshot",
        )
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_post_event_snapshot failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "frigate_post_event_clip",
        "description": (
            "Post the video clip from a Frigate detection event into the chat. "
            "Downloads the event's MP4 clip and uploads it inline. "
            "Use after frigate_get_events to show the full event recording. "
            "Max file size: 50 MB."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Frigate event ID (from frigate_get_events results). Event must have has_clip=true.",
                },
            },
            "required": ["event_id"],
        },
    },
})
async def frigate_post_event_clip(event_id: str) -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")
    try:
        return await _post_media(
            f"/api/events/{event_id}/clip.mp4",
            filename=f"event_{event_id}_clip.mp4",
            mime_type="video/mp4",
            caption=f"Event {event_id} clip",
            max_bytes=settings.FRIGATE_MAX_CLIP_BYTES,
            timeout=120.0,
        )
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_post_event_clip failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "frigate_post_recording_clip",
        "description": (
            "Post a recording clip from a Frigate camera for a specific time range. "
            "Frigate stitches the recording on-the-fly, so this may take a moment. "
            "Max duration: 10 minutes. Max file size: 50 MB. "
            "Timestamps are Unix epoch seconds."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "camera": {
                    "type": "string",
                    "description": "Camera name.",
                },
                "start_time": {
                    "type": "number",
                    "description": "Start Unix timestamp (epoch seconds).",
                },
                "end_time": {
                    "type": "number",
                    "description": "End Unix timestamp (epoch seconds).",
                },
            },
            "required": ["camera", "start_time", "end_time"],
        },
    },
})
async def frigate_post_recording_clip(
    camera: str,
    start_time: float,
    end_time: float,
) -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")

    duration = end_time - start_time
    if duration <= 0:
        return _error("end_time must be after start_time")
    if duration > 600:
        return _error("Maximum clip duration is 10 minutes (600 seconds)")

    try:
        start_ts = str(int(start_time))
        end_ts = str(int(end_time))
        return await _post_media(
            f"/api/{camera}/start/{start_ts}/end/{end_ts}/clip.mp4",
            filename=f"{camera}_{start_ts}_{end_ts}.mp4",
            mime_type="video/mp4",
            caption=f"Recording from {camera}",
            max_bytes=settings.FRIGATE_MAX_CLIP_BYTES,
            timeout=120.0,
        )
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_post_recording_clip failed")
        return _error(str(e))
