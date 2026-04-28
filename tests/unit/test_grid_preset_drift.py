"""Cross-layer drift guard for dashboard grid presets.

``packages/dashboard-grid/presets.json`` is the source of truth. Backend and
frontend code may keep compatibility projections, but they must import or
derive from the manifest instead of reintroducing local preset literals.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.services import dashboard_grid
from app.services.dashboards import DEFAULT_PRESET, GRID_PRESETS as BACKEND_PRESETS


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_FILE = _REPO_ROOT / "packages" / "dashboard-grid" / "presets.json"
_TS_FILE = _REPO_ROOT / "ui" / "src" / "lib" / "dashboardGrid.ts"


def _load_manifest() -> dict:
    if not _MANIFEST_FILE.is_file():
        pytest.fail(f"shared preset manifest not found at {_MANIFEST_FILE}")
    return json.loads(_MANIFEST_FILE.read_text(encoding="utf-8"))


def _load_ts() -> str:
    if not _TS_FILE.is_file():
        pytest.skip(f"frontend source not available at {_TS_FILE}")
    return _TS_FILE.read_text(encoding="utf-8")


def _assignment_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_manifest_default_preset_exists() -> None:
    manifest = _load_manifest()
    assert manifest["defaultPresetId"] in manifest["presets"]
    assert DEFAULT_PRESET == manifest["defaultPresetId"]


def test_backend_projection_matches_manifest() -> None:
    manifest = _load_manifest()
    expected = {
        preset_id: {
            "cols_lg": preset["cols"]["lg"],
            "row_height": preset["rowHeight"],
        }
        for preset_id, preset in manifest["presets"].items()
    }
    assert BACKEND_PRESETS == expected


def test_manifest_presets_have_integer_scale_ratios() -> None:
    manifest = _load_manifest()
    presets = manifest["presets"]
    for from_id, from_preset in presets.items():
        for to_id, to_preset in presets.items():
            from_cols = from_preset["cols"]["lg"]
            to_cols = to_preset["cols"]["lg"]
            if from_cols == to_cols:
                assert dashboard_grid.scale_ratio(from_id, to_id) == 1
            elif to_cols > from_cols:
                assert to_cols % from_cols == 0
                assert dashboard_grid.scale_ratio(from_id, to_id) == to_cols // from_cols
            else:
                assert from_cols % to_cols == 0
                assert dashboard_grid.scale_ratio(from_id, to_id) == -(from_cols // to_cols)


def test_frontend_imports_shared_manifest_instead_of_local_literal() -> None:
    src = _load_ts()
    assert "../../../packages/dashboard-grid/presets.json" in src
    assert "export const GRID_PRESETS: Record<GridPresetId, GridPreset> = {" not in src
    assert 'export const DEFAULT_PRESET_ID: GridPresetId = "standard"' not in src


def test_backend_callers_do_not_define_local_preset_tables() -> None:
    owners = {
        _REPO_ROOT / "app" / "services" / "dashboards.py": {"GRID_PRESETS"},
        _REPO_ROOT / "app" / "services" / "dashboard_ascii.py": {"_PRESETS", "_DEFAULT_PRESET"},
        _REPO_ROOT / "app" / "services" / "dashboard_pins.py": {
            "_HEADER_PRESET_COLS",
            "_DASHBOARD_PRESET_DEFAULT",
        },
    }
    for path, forbidden in owners.items():
        assigned = _assignment_names(path)
        assert assigned.isdisjoint(forbidden), (
            f"{path.relative_to(_REPO_ROOT)} reintroduced local preset state: "
            f"{sorted(assigned & forbidden)}"
        )
