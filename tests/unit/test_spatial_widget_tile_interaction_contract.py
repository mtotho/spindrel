from __future__ import annotations

from pathlib import Path


WIDGET_TILE = Path(__file__).resolve().parents[2] / (
    "ui/src/components/spatial-canvas/WidgetTile.tsx"
)


def test_spatial_widget_body_does_not_use_click_to_interact_shield() -> None:
    source = WIDGET_TILE.read_text()

    assert 'aria-label="Select widget"' not in source
    assert "Click to interact" not in source


def test_spatial_widget_header_owns_selection_and_body_owns_interaction() -> None:
    source = WIDGET_TILE.read_text()

    assert 'data-spatial-widget-header="true"' in source
    assert "onSelect?.();" in source[source.index('data-spatial-widget-header="true"') :]
    assert 'data-spatial-widget-body="true"' in source
    assert "onActivate(nodeId);" in source[source.index('data-spatial-widget-body="true"') :]
