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
