"""Unit tests for the dashboard ASCII renderer + free-slot finder.

Pure-function tests — no DB, no I/O. Fed with plain dicts matching the
shape ``dashboard_pins.serialize_pin`` produces.
"""
from __future__ import annotations

import uuid

import pytest

from app.services.dashboard_ascii import (
    default_size_for_zone,
    find_free_slot,
    render_layout,
    render_legend,
    resolve_preset_name,
)
from app.services.dashboard_grid import ascii_max_rows, header_cols, preset_cols


def _pin(
    zone: str = "grid",
    x: int = 0, y: int = 0, w: int = 1, h: int = 1,
    *,
    display_label: str | None = None,
    tool_name: str = "emit_html_widget",
    is_main_panel: bool = False,
    pid: str | None = None,
) -> dict:
    return {
        "id": pid or str(uuid.uuid4()),
        "zone": zone,
        "grid_layout": {"x": x, "y": y, "w": w, "h": h},
        "display_label": display_label,
        "tool_name": tool_name,
        "is_main_panel": is_main_panel,
    }


class TestResolvePreset:
    def test_default_when_grid_config_none(self):
        assert resolve_preset_name(None) == "standard"

    def test_default_when_grid_config_empty(self):
        assert resolve_preset_name({}) == "standard"

    def test_explicit_standard(self):
        assert resolve_preset_name({"preset": "standard"}) == "standard"

    def test_explicit_fine(self):
        assert resolve_preset_name({"preset": "fine"}) == "fine"

    def test_unknown_preset_falls_back(self):
        assert resolve_preset_name({"preset": "jumbo"}) == "standard"


class TestDefaultSizes:
    def test_grid_default_is_6x6(self):
        assert default_size_for_zone("grid") == (6, 6)

    def test_header_default_is_6x2(self):
        assert default_size_for_zone("header") == (6, 2)

    def test_rail_default_is_1x4(self):
        assert default_size_for_zone("rail") == (1, 4)

    def test_dock_default_is_1x4(self):
        assert default_size_for_zone("dock") == (1, 4)


class TestRenderLegend:
    def test_empty_dashboard_message(self):
        out = render_legend([], {})
        assert "empty" in " ".join(out).lower()

    def test_legend_lists_every_pin_with_coords(self):
        p1 = _pin(zone="rail", x=0, y=0, w=1, h=2, display_label="Notes")
        p2 = _pin(zone="grid", x=2, y=2, w=4, h=3, display_label="Kanban")
        labels = {p1["id"]: "A", p2["id"]: "B"}
        out = "\n".join(render_legend([p1, p2], labels))
        assert "A = Notes" in out
        assert "B = Kanban" in out
        assert "rail" in out
        assert "grid" in out
        assert "1×2" in out
        assert "4×3" in out

    def test_panel_pin_carries_tag(self):
        p = _pin(zone="grid", display_label="Dashboard", is_main_panel=True)
        labels = {p["id"]: "A"}
        out = "\n".join(render_legend([p], labels))
        assert "[panel]" in out


class TestRenderLayout:
    def test_empty_dashboard_still_renders_structure(self):
        out = render_layout({"grid_config": None}, [])
        assert "CHAT VIEW" in out
        assert "FULL DASHBOARD VIEW" in out
        assert "empty" in out.lower()

    def test_chat_view_only(self):
        out = render_layout({}, [], view="chat")
        assert "CHAT VIEW" in out
        assert "FULL DASHBOARD VIEW" not in out

    def test_full_view_only(self):
        out = render_layout({}, [], view="full")
        assert "FULL DASHBOARD VIEW" in out
        assert "CHAT VIEW" not in out

    def test_header_pin_appears_in_preview(self):
        p = _pin(zone="header", x=0, y=0, w=2, h=1, display_label="Chip A")
        out = render_layout({}, [p])
        assert "Chip A" in out

    def test_header_preview_supports_second_row(self):
        p = _pin(zone="header", x=0, y=1, w=2, h=1, display_label="Row Two")
        out = render_layout({}, [p])
        assert "Row Two" in out

    def test_grid_pin_renders_in_full_view_only(self):
        p = _pin(zone="grid", x=2, y=2, w=3, h=3, display_label="Board")
        out = render_layout({}, [p])
        # Present in both legend and full-view grid matrix.
        assert "Board" in out
        # Chat view's middle column is a placeholder, not a matrix.
        # The chat column label is rendered as "[ chat column ]".
        assert "chat column" in out

    def test_rail_and_dock_pins_render_in_chat_view(self):
        rail = _pin(zone="rail", x=0, y=0, w=1, h=3, display_label="Rail A")
        dock = _pin(zone="dock", x=0, y=0, w=1, h=2, display_label="Dock A")
        out = render_layout({}, [rail, dock])
        assert "Rail A" in out
        assert "Dock A" in out
        # Both CHAT VIEW and FULL DASHBOARD include rail/dock columns.
        assert out.count("│") > 0  # has vertical borders

    def test_panel_mode_surface_note(self):
        p = _pin(
            zone="grid", x=0, y=0, w=6, h=6,
            display_label="Big Panel", is_main_panel=True,
        )
        out = render_layout({}, [p])
        assert "Panel mode" in out
        assert "Big Panel" in out

    def test_fine_preset_renders_wider_header(self):
        out_std = render_layout({"grid_config": {"preset": "standard"}}, [])
        out_fine = render_layout({"grid_config": {"preset": "fine"}}, [])
        # Fine preset has 24 header cols vs 12 standard; full view header row
        # should be wider.
        std_header_line = next(
            line for line in out_std.splitlines() if line.startswith("│")
        )
        fine_header_line = next(
            line for line in out_fine.splitlines() if line.startswith("│")
        )
        assert len(fine_header_line) > len(std_header_line)


class TestFindFreeSlot:
    def test_empty_grid_returns_origin(self):
        y, x = find_free_slot([], zone="grid", w=6, h=6)
        assert (y, x) == (0, 0)

    def test_grid_finds_next_row_when_top_occupied(self):
        pins = [_pin(zone="grid", x=0, y=0, w=6, h=6)]
        y, x = find_free_slot(pins, zone="grid", w=6, h=6)
        # The next free slot for 6x6 in a 12-col grid is (0, 6) — right of
        # the existing pin on the same row.
        assert (y, x) == (0, 6)

    def test_grid_wraps_to_next_row_when_row_is_full(self):
        pins = [
            _pin(zone="grid", x=0, y=0, w=6, h=6),
            _pin(zone="grid", x=6, y=0, w=6, h=6),
        ]
        y, x = find_free_slot(pins, zone="grid", w=6, h=6)
        assert (y, x) == (6, 0)

    def test_rail_stacks_vertically(self):
        pins = [_pin(zone="rail", x=0, y=0, w=1, h=3)]
        y, x = find_free_slot(pins, zone="rail", w=1, h=2)
        assert (y, x) == (3, 0)

    def test_rail_clamps_oversized_width(self):
        # rail is 1 col; a w=4 request should clamp and still find (0, 0).
        y, x = find_free_slot([], zone="rail", w=4, h=1)
        assert x == 0
        # Clamped to 1 col, so finds (0, 0).
        assert y == 0

    def test_header_finds_next_x_when_front_occupied(self):
        pins = [_pin(zone="header", x=0, y=0, w=3, h=1)]
        y, x = find_free_slot(pins, zone="header", w=2, h=1)
        assert (y, x) == (0, 3)

    def test_header_uses_second_row_before_wrapping_outside_cap(self):
        pins = [_pin(zone="header", x=0, y=0, w=12, h=1)]
        y, x = find_free_slot(pins, zone="header", w=4, h=1)
        assert (y, x) == (1, 0)

    def test_fine_preset_uses_24_cols(self):
        # A 6×6 grid pin at (0, 12) should be allowed under fine preset but
        # forbidden under standard (12 cols).
        pins = [_pin(zone="grid", x=0, y=0, w=12, h=6)]
        y_fine, x_fine = find_free_slot(
            pins, zone="grid", w=6, h=6, preset_name="fine",
        )
        # Fine has 24 cols — should find (0, 12) on the same row.
        assert (y_fine, x_fine) == (0, 12)

    def test_ascii_helpers_use_manifest_values(self):
        assert preset_cols("fine") == 24
        assert header_cols("fine") == 24
        assert ascii_max_rows("fine") == 24

    def test_respects_existing_occupancy_diagonal(self):
        # Top-left 6×6 occupied. Next free 4×4 should be at (0, 6).
        pins = [_pin(zone="grid", x=0, y=0, w=6, h=6)]
        y, x = find_free_slot(pins, zone="grid", w=4, h=4)
        assert (y, x) == (0, 6)


class TestLabelAlphabet:
    def test_up_to_52_unique_labels(self):
        # 60 pins → first 52 labelled A-Z,a-z; the rest fall back.
        pins = [_pin(zone="grid", x=(i % 12), y=(i // 12), w=1, h=1)
                for i in range(60)]
        out = render_layout({}, pins)
        # First pin's label is 'A'.
        assert "A = " in out
        # 52nd pin's label is 'z'.
        assert "z = " in out

    def test_pins_beyond_52_use_fallback(self):
        pins = [_pin(zone="grid", x=(i % 12), y=(i // 12), w=1, h=1)
                for i in range(55)]
        out = render_layout({}, pins)
        assert "??" in out  # 53rd pin onward


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
