"""Shared dashboard grid preset manifest helpers.

The JSON manifest is the source of truth consumed by both backend and
frontend. This module deliberately exposes the older backend projection
(``GRID_PRESETS`` / ``DEFAULT_PRESET``) so existing callers keep a small
interface while preset details stay local to this seam.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.domain.errors import InternalError, ValidationError


_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "dashboard-grid"
    / "presets.json"
)


def _require_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"dashboard grid manifest field {field} must be a positive int")
    return value


def _load_manifest() -> dict[str, Any]:
    with _MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)
    if not isinstance(manifest, dict):
        raise RuntimeError("dashboard grid manifest must be an object")
    return manifest


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    default_id = manifest.get("defaultPresetId")
    presets = manifest.get("presets")
    if not isinstance(default_id, str):
        raise RuntimeError("dashboard grid manifest defaultPresetId must be a string")
    if not isinstance(presets, dict) or not presets:
        raise RuntimeError("dashboard grid manifest presets must be a non-empty object")
    if default_id not in presets:
        raise RuntimeError("dashboard grid manifest defaultPresetId must reference a preset")

    for preset_id, preset in presets.items():
        if not isinstance(preset_id, str) or not isinstance(preset, dict):
            raise RuntimeError("dashboard grid manifest presets must be keyed objects")
        if preset.get("id") != preset_id:
            raise RuntimeError(f"dashboard grid preset {preset_id!r} id must match its key")
        cols = preset.get("cols")
        if not isinstance(cols, dict):
            raise RuntimeError(f"dashboard grid preset {preset_id!r} cols must be an object")
        _require_positive_int(cols.get("lg"), f"{preset_id}.cols.lg")
        _require_positive_int(preset.get("rowHeight"), f"{preset_id}.rowHeight")
        _require_positive_int(preset.get("headerCols"), f"{preset_id}.headerCols")
        _require_positive_int(preset.get("asciiMaxRows"), f"{preset_id}.asciiMaxRows")

        default_tile = preset.get("defaultTile")
        min_tile = preset.get("minTile")
        for tile_name, tile in (("defaultTile", default_tile), ("minTile", min_tile)):
            if not isinstance(tile, dict):
                raise RuntimeError(
                    f"dashboard grid preset {preset_id!r} {tile_name} must be an object"
                )
            _require_positive_int(tile.get("w"), f"{preset_id}.{tile_name}.w")
            _require_positive_int(tile.get("h"), f"{preset_id}.{tile_name}.h")

    for from_id, from_preset in presets.items():
        from_cols = from_preset["cols"]["lg"]
        for to_id, to_preset in presets.items():
            to_cols = to_preset["cols"]["lg"]
            if from_cols == to_cols:
                continue
            if to_cols % from_cols != 0 and from_cols % to_cols != 0:
                raise RuntimeError(
                    "dashboard grid preset columns must have integer scale ratios: "
                    f"{from_id}={from_cols}, {to_id}={to_cols}"
                )
    return manifest


_MANIFEST = _validate_manifest(_load_manifest())
DEFAULT_PRESET: str = _MANIFEST["defaultPresetId"]
GRID_PRESETS: dict[str, dict[str, int]] = {
    preset_id: {
        "cols_lg": preset["cols"]["lg"],
        "row_height": preset["rowHeight"],
    }
    for preset_id, preset in _MANIFEST["presets"].items()
}


def manifest_path() -> Path:
    return _MANIFEST_PATH


def manifest() -> dict[str, Any]:
    return copy.deepcopy(_MANIFEST)


def valid_preset(preset: str | None) -> str:
    if preset is None:
        return DEFAULT_PRESET
    if preset not in GRID_PRESETS:
        raise ValidationError(
            f"grid_config.preset must be one of {sorted(GRID_PRESETS)}",
        )
    return preset


def resolve_preset_name(grid_config: dict[str, Any] | None) -> str:
    if not isinstance(grid_config, dict):
        return DEFAULT_PRESET
    preset = grid_config.get("preset")
    if isinstance(preset, str) and preset in GRID_PRESETS:
        return preset
    return DEFAULT_PRESET


def scale_ratio(from_preset: str, to_preset: str) -> int:
    """Return an integer multiplier for preset coordinate rescaling.

    Positive ratios multiply coordinates; negative ratios divide by the
    absolute value. This preserves the existing ``dashboards`` rescale
    contract while making invalid future manifest changes fail at one seam.
    """
    a = GRID_PRESETS[from_preset]["cols_lg"]
    b = GRID_PRESETS[to_preset]["cols_lg"]
    if a == b:
        return 1
    if b % a == 0:
        return b // a
    if a % b == 0:
        return -(a // b)
    raise InternalError(
        f"Non-integer scale between presets {from_preset} and {to_preset}",
    )


def preset_cols(preset_name: str, *, breakpoint: str = "lg") -> int:
    preset = _MANIFEST["presets"].get(preset_name) or _MANIFEST["presets"][DEFAULT_PRESET]
    cols = preset["cols"].get(breakpoint)
    return _require_positive_int(cols, f"{preset_name}.cols.{breakpoint}")


def header_cols(preset_name: str) -> int:
    preset = _MANIFEST["presets"].get(preset_name) or _MANIFEST["presets"][DEFAULT_PRESET]
    return preset["headerCols"]


def ascii_max_rows(preset_name: str) -> int:
    preset = _MANIFEST["presets"].get(preset_name) or _MANIFEST["presets"][DEFAULT_PRESET]
    return preset["asciiMaxRows"]


def default_tile(preset_name: str) -> dict[str, int]:
    preset = _MANIFEST["presets"].get(preset_name) or _MANIFEST["presets"][DEFAULT_PRESET]
    return dict(preset["defaultTile"])


def default_grid_layout(position: int, *, preset_name: str = DEFAULT_PRESET) -> dict[str, int]:
    tile = default_tile(preset_name)
    return {
        "x": (position % 2) * tile["w"],
        "y": (position // 2) * tile["h"],
        "w": tile["w"],
        "h": tile["h"],
    }
