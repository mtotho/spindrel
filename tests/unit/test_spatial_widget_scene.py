from app.services.workspace_spatial import _score_widget_scene


def test_spatial_widget_scene_score_reports_overlaps_duplicates_and_tiny_widgets():
    items = [
        {
            "node_id": "a",
            "kind": "widget",
            "label": "Notes",
            "world_bounds": {"x": 0.0, "y": 0.0, "w": 140.0, "h": 80.0},
            "visibility": {"clipped_fraction": 0.2},
        },
        {
            "node_id": "b",
            "kind": "widget",
            "label": "Notes",
            "world_bounds": {"x": 80.0, "y": 40.0, "w": 240.0, "h": 160.0},
            "visibility": {"clipped_fraction": 0.0},
        },
    ]

    score = _score_widget_scene(items, min_gap=96.0)

    assert score["widget_count"] == 2
    assert score["overlap_count"] == 1
    assert score["total_overlap_area"] == 2400.0
    assert score["duplicate_label_groups"] == [{"label": "notes", "count": 2}]
    assert score["clipped_count"] == 1
    assert score["tiny_count"] == 1
    assert "1 widget overlap pair(s)" in score["warnings"]
