"""Binding-source transforms for Frigate widget presets.

Each function receives the raw tool-result string and a runtime context dict
(``{"params": {...}}`` from the YAML binding_sources entry) and returns a
flat list of ``{value, label, description?, group?, meta?}`` option dicts
for the preset configure step's picker controls.
"""
from __future__ import annotations

import json
from typing import Any


def camera_options(raw_result: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn ``frigate_list_cameras`` output into picker options.

    ``params.enabled_only: bool`` (default false) hides disabled cameras from
    the picker — useful for snapshot bindings where a disabled camera won't
    produce a frame.
    """
    try:
        parsed = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return []

    cameras = parsed.get("cameras") if isinstance(parsed, dict) else None
    if not isinstance(cameras, list):
        return []

    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    enabled_only = bool(params.get("enabled_only"))

    out: list[dict[str, Any]] = []
    for cam in cameras:
        if not isinstance(cam, dict):
            continue
        name = cam.get("name")
        if not isinstance(name, str) or not name:
            continue
        enabled = bool(cam.get("enabled", True))
        if enabled_only and not enabled:
            continue
        w, h, fps = cam.get("width"), cam.get("height"), cam.get("fps")
        desc_bits: list[str] = []
        if isinstance(w, int) and isinstance(h, int):
            desc_bits.append(f"{w}×{h}")
        if isinstance(fps, (int, float)):
            desc_bits.append(f"{fps:g}fps")
        if not enabled:
            desc_bits.append("disabled")
        out.append({
            "value": name,
            "label": name,
            "description": " · ".join(desc_bits) or None,
            "group": "Cameras" if enabled else "Disabled",
            "meta": {"enabled": enabled},
        })

    out.sort(key=lambda item: ((item.get("group") or "").lower(), item["label"].lower()))
    return out


_DEFAULT_LABELS: tuple[str, ...] = (
    "person", "car", "truck", "motorcycle", "bicycle", "dog", "cat",
)


def label_options(raw_result: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a fixed list of object labels the events widget can filter on.

    Frigate's config exposes per-camera label sets but there's no cheap
    discovery call that enumerates them globally. The curated list matches
    ``_LABEL_COLOR`` in ``widget_transforms`` — extend both together.
    ``raw_result`` is ignored (no upstream tool); the function keeps the
    standard binding-source signature for uniformity.
    """
    del raw_result, context  # signature parity
    return [
        {"value": label, "label": label, "group": "Objects"}
        for label in _DEFAULT_LABELS
    ]
