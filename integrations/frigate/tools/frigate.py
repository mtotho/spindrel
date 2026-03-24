"""Frigate NVR camera tools. Requires FRIGATE_URL in .env."""

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
            "Get detection events from Frigate NVR cameras. Returns compact event summaries. "
            "Use frigate_event_snapshot/frigate_event_clip to download media for specific events. "
            "Pagination: use 'before' with the start_time of the last event to get the next page."
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
                    "description": "Only events before this Unix timestamp. Use for pagination: pass start_time of the last event from previous page.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max events to return (default 20).",
                },
                "has_clip": {
                    "type": "boolean",
                    "description": "Only return events that have a video clip available.",
                },
                "has_snapshot": {
                    "type": "boolean",
                    "description": "Only return events that have a snapshot image available.",
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
    has_clip: Optional[bool] = None,
    has_snapshot: Optional[bool] = None,
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
        if has_clip is not None:
            params["has_clip"] = 1 if has_clip else 0
        if has_snapshot is not None:
            params["has_snapshot"] = 1 if has_snapshot else 0
        if favorites is not None:
            params["favorites"] = 1 if favorites else 0

        events = await _get("/api/events", params=params)
        results = []
        for ev in events:
            data = ev.get("data") or {}
            entry: dict = {
                "id": ev.get("id", ""),
                "camera": ev.get("camera"),
                "label": ev.get("label"),
                "score": round(data.get("score") or data.get("top_score") or ev.get("top_score") or 0, 3),
                "start_time": ev.get("start_time"),
                "end_time": ev.get("end_time"),
                "zones": ev.get("zones", []),
                "has_snapshot": ev.get("has_snapshot", False),
                "has_clip": ev.get("has_clip", False),
            }
            # Only include optional fields when present
            if ev.get("sub_label"):
                entry["sub_label"] = ev["sub_label"]
            if data.get("description"):
                entry["description"] = data["description"]
            if data.get("type"):
                entry["type"] = data["type"]
            if data.get("recognized_license_plate"):
                entry["license_plate"] = data["recognized_license_plate"]
            if data.get("attributes"):
                entry["attributes"] = data["attributes"]
            results.append(entry)
        has_more = len(results) == limit
        resp: dict = {"events": results, "count": len(results)}
        if has_more and results:
            resp["next_before"] = results[-1].get("start_time")
        return json.dumps(resp)
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
# Media download helpers
# ---------------------------------------------------------------------------


async def _get_bytes(path: str, params: dict | None = None, timeout: float = 30.0) -> bytes:
    """Binary GET from Frigate. Returns raw bytes."""
    url = f"{_base_url()}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(), params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.content


async def _download_media(
    path: str,
    *,
    params: dict | None = None,
    filename: str,
    mime_type: str,
    max_bytes: int | None = None,
    timeout: float = 30.0,
) -> str:
    """Download binary from Frigate → persist as attachment → return attachment_id."""
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

    att = await create_attachment(
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

    return json.dumps({
        "attachment_id": str(att.id),
        "filename": filename,
        "size_bytes": len(data),
    })


# ---------------------------------------------------------------------------
# Media download tools (return attachment_id — use post_attachment to display)
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "frigate_snapshot",
        "description": (
            "Download the latest snapshot from a Frigate camera and save it as an attachment. "
            "Returns an attachment_id. Use post_attachment to display it in chat."
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
async def frigate_snapshot(
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
        return await _download_media(
            f"/api/{camera}/latest.jpg",
            params=params,
            filename=f"{camera}_snapshot.jpg",
            mime_type="image/jpeg",
        )
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_snapshot failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "frigate_event_snapshot",
        "description": (
            "Download the snapshot image from a Frigate detection event and save it as an attachment. "
            "Returns an attachment_id. Use post_attachment to display it in chat."
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
async def frigate_event_snapshot(event_id: str) -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")
    try:
        return await _download_media(
            f"/api/events/{event_id}/snapshot.jpg",
            filename=f"event_{event_id}_snapshot.jpg",
            mime_type="image/jpeg",
        )
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_event_snapshot failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "frigate_event_clip",
        "description": (
            "Download the video clip from a Frigate detection event and save it as an attachment. "
            "Returns an attachment_id. Use post_attachment to display it in chat. "
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
async def frigate_event_clip(event_id: str) -> str:
    if not settings.FRIGATE_URL:
        return _error("FRIGATE_URL is not configured")
    try:
        return await _download_media(
            f"/api/events/{event_id}/clip.mp4",
            filename=f"event_{event_id}_clip.mp4",
            mime_type="video/mp4",
            max_bytes=settings.FRIGATE_MAX_CLIP_BYTES,
            timeout=120.0,
        )
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_event_clip failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "frigate_recording_clip",
        "description": (
            "Download a recording clip from a Frigate camera for a specific time range "
            "and save it as an attachment. Returns an attachment_id. Use post_attachment "
            "to display it in chat. Max duration: 10 minutes. Max file size: 50 MB. "
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
async def frigate_recording_clip(
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
        return await _download_media(
            f"/api/{camera}/start/{start_ts}/end/{end_ts}/clip.mp4",
            filename=f"{camera}_{start_ts}_{end_ts}.mp4",
            mime_type="video/mp4",
            max_bytes=settings.FRIGATE_MAX_CLIP_BYTES,
            timeout=120.0,
        )
    except httpx.HTTPStatusError as e:
        return _error(f"Frigate API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.exception("frigate_recording_clip failed")
        return _error(str(e))
