"""Unit tests for `classify_pin` — pure function, no DB."""
from __future__ import annotations

from app.services.channel_chat_zones import classify_pin
from app.services.grid_presets import GRID_PRESETS


STD = GRID_PRESETS["standard"]  # cols_lg=12, rail_zone_cols=3, dock_right_cols=3
FINE = GRID_PRESETS["fine"]  # cols_lg=24, rail_zone_cols=6, dock_right_cols=6


def _pin(x: int, y: int, w: int, h: int) -> dict:
    return {"grid_layout": {"x": x, "y": y, "w": w, "h": h}}


class TestClassifyPin:
    def test_rail_left_edge_in_rail_band(self):
        assert classify_pin(_pin(0, 0, 3, 6), STD) == "rail"
        assert classify_pin(_pin(2, 4, 3, 6), STD) == "rail"

    def test_dock_left_edge_in_dock_band(self):
        # standard: dock band starts at 12 - 3 = 9
        assert classify_pin(_pin(9, 0, 3, 6), STD) == "dock_right"
        assert classify_pin(_pin(11, 2, 1, 2), STD) == "dock_right"

    def test_header_chip_top_row_middle(self):
        # x in [3, 9), y=0, h=1 → header chip
        assert classify_pin(_pin(3, 0, 1, 1), STD) == "header_chip"
        assert classify_pin(_pin(5, 0, 3, 1), STD) == "header_chip"
        assert classify_pin(_pin(8, 0, 1, 1), STD) == "header_chip"

    def test_header_chip_requires_h_equals_1(self):
        # top-row but taller → grid, not header
        assert classify_pin(_pin(5, 0, 3, 2), STD) == "grid"

    def test_header_chip_requires_y_equals_0(self):
        # y > 0 in the middle band → grid
        assert classify_pin(_pin(5, 1, 3, 1), STD) == "grid"

    def test_grid_middle_area(self):
        assert classify_pin(_pin(5, 2, 3, 4), STD) == "grid"

    def test_rail_precedence_over_header(self):
        # Tile with x=2, y=0, h=1 — rail takes precedence even though it'd
        # otherwise shape-match header_chip.
        assert classify_pin(_pin(2, 0, 1, 1), STD) == "rail"

    def test_dock_precedence_over_header(self):
        # x=9 in dock band AND h=1, y=0 — dock wins.
        assert classify_pin(_pin(9, 0, 1, 1), STD) == "dock_right"

    def test_missing_grid_layout_is_grid(self):
        assert classify_pin({}, STD) == "grid"
        assert classify_pin({"grid_layout": None}, STD) == "grid"
        assert classify_pin({"grid_layout": "not-a-dict"}, STD) == "grid"

    def test_non_int_coords_are_grid(self):
        assert classify_pin({"grid_layout": {"x": "a", "y": 0, "w": 1, "h": 1}}, STD) == "grid"

    def test_fine_preset_boundaries(self):
        # fine: rail < 6, dock >= 24-6 = 18
        assert classify_pin(_pin(5, 0, 6, 12), FINE) == "rail"
        assert classify_pin(_pin(6, 0, 6, 12), FINE) == "grid"
        assert classify_pin(_pin(17, 0, 6, 12), FINE) == "grid"
        assert classify_pin(_pin(18, 0, 6, 12), FINE) == "dock_right"
        # header band in middle (x in [6, 18))
        assert classify_pin(_pin(10, 0, 4, 1), FINE) == "header_chip"
