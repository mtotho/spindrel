"""Drift guard: Python `GRID_PRESETS` must match the TS source of truth
in `ui/src/lib/dashboardGrid.ts`. If either side changes a preset field,
the other must follow — otherwise zone classification diverges between
server and client.

Parses the TS source via regex rather than executing JS. We only assert
on the fields classify_pin consumes: `cols.lg`, `railZoneCols`,
`dockRightCols`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.services.grid_presets import GRID_PRESETS


REPO_ROOT = Path(__file__).resolve().parents[2]
TS_SOURCE = REPO_ROOT / "ui" / "src" / "lib" / "dashboardGrid.ts"


def _extract_preset_field(preset_id: str, field: str) -> int:
    """Pull a numeric field out of a GRID_PRESETS entry in the TS file."""
    src = TS_SOURCE.read_text()
    # Find the preset block: `  standard: { ... },`
    block_re = re.compile(
        rf"{preset_id}\s*:\s*\{{(.+?)\n\s*\}}",
        re.DOTALL,
    )
    block_match = block_re.search(src)
    assert block_match, f"Could not locate '{preset_id}:' block in {TS_SOURCE}"
    block = block_match.group(1)

    if field == "cols.lg":
        m = re.search(r"cols\s*:\s*\{\s*lg\s*:\s*(\d+)", block)
    else:
        m = re.search(rf"{field}\s*:\s*(\d+)", block)
    assert m, f"Could not find '{field}' in '{preset_id}' block"
    return int(m.group(1))


@pytest.mark.skipif(not TS_SOURCE.exists(), reason="ui/ not present in this checkout")
class TestPresetParity:
    def test_standard_cols_lg(self):
        assert _extract_preset_field("standard", "cols.lg") == GRID_PRESETS["standard"].cols_lg

    def test_standard_rail_zone_cols(self):
        assert _extract_preset_field("standard", "railZoneCols") == GRID_PRESETS["standard"].rail_zone_cols

    def test_standard_dock_right_cols(self):
        assert _extract_preset_field("standard", "dockRightCols") == GRID_PRESETS["standard"].dock_right_cols

    def test_fine_cols_lg(self):
        assert _extract_preset_field("fine", "cols.lg") == GRID_PRESETS["fine"].cols_lg

    def test_fine_rail_zone_cols(self):
        assert _extract_preset_field("fine", "railZoneCols") == GRID_PRESETS["fine"].rail_zone_cols

    def test_fine_dock_right_cols(self):
        assert _extract_preset_field("fine", "dockRightCols") == GRID_PRESETS["fine"].dock_right_cols
