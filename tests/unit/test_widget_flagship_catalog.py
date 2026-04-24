"""Smoke tests for the Phase 2 flagship HTML widget catalog.

Covers flagship/result widgets shipped on 2026-04-19 and later:

- ``generate_image``  → app/tools/local/widgets/generate_image/template.yaml
- ``get_weather``     → integrations/openweather/integration.yaml
- ``web_search``      → integrations/web_search/integration.yaml (core semantic renderer)
- ``frigate_list_cameras`` → integrations/frigate/integration.yaml

Each widget must register with the correct content type and a representative
``sample_payload`` so the dev-panel preview renders on first open.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.services.widget_templates import (
    _register_widgets,
    _widget_templates,
    apply_widget_template,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_registry():
    _widget_templates.clear()
    yield
    _widget_templates.clear()


def _load_integration_manifest(integration_id: str) -> tuple[dict, Path]:
    path = REPO_ROOT / "integrations" / integration_id / "integration.yaml"
    return yaml.safe_load(path.read_text()), path.parent


def _load_core_widgets(tool_name: str) -> tuple[dict, Path]:
    """Load a core widget template under the new per-tool layout.

    Returns ``({tool_name: widget_def}, base_dir)`` so the existing tests
    that iterate ``raw["<tool>"]["sample_payload"]`` keep working without
    reshaping.  ``base_dir`` is the widget folder itself — that's what
    ``html_template.path`` resolves against.
    """
    widget_dir = REPO_ROOT / "app" / "tools" / "local" / "widgets" / tool_name
    widget_def = yaml.safe_load((widget_dir / "template.yaml").read_text())
    return {tool_name: widget_def}, widget_dir


class TestGenerateImageWidget:
    def test_registers_from_yaml(self):
        raw, base = _load_core_widgets("generate_image")
        count = _register_widgets("core:generate_image", raw, base_dir=base)
        assert count == 1
        tmpl = _widget_templates["generate_image"]
        assert tmpl["content_type"] == "application/vnd.spindrel.html+interactive"
        assert tmpl["html_template_body"]
        # Widget references window.spindrel.toolArgs? No — prompt lives on the
        # tool result now. Confirm the widget reads the prompt off toolResult.
        assert "toolResult" in tmpl["html_template_body"]

    def test_sample_payload_renders(self):
        raw, base = _load_core_widgets("generate_image")
        _register_widgets("core:generate_image", raw, base_dir=base)
        sample = raw["generate_image"]["sample_payload"]
        env = apply_widget_template("generate_image", json.dumps(sample))
        assert env is not None
        assert env.content_type == "application/vnd.spindrel.html+interactive"
        # Prompt must ride into the iframe so regen buttons can mutate it.
        assert '"prompt"' in env.body


class TestGetWeatherWidget:
    def test_registers_as_html(self):
        raw, base = _load_integration_manifest("openweather")
        tool_widgets = raw["tool_widgets"]
        count = _register_widgets("integration:openweather", tool_widgets, base_dir=base)
        assert count == 1
        tmpl = _widget_templates["get_weather"]
        assert tmpl["content_type"] == "application/vnd.spindrel.html+interactive"
        assert tmpl["html_template_body"]
        assert tmpl["state_poll"]["refresh_interval_seconds"] == 3600

    def test_sample_payload_has_hourly_for_svg_chart(self):
        raw, _ = _load_integration_manifest("openweather")
        sample = raw["tool_widgets"]["get_weather"]["sample_payload"]
        assert isinstance(sample.get("hourly_forecast"), list)
        assert len(sample["hourly_forecast"]) >= 6  # enough points to draw a curve

    def test_default_config_includes_units(self):
        raw, _ = _load_integration_manifest("openweather")
        cfg = raw["tool_widgets"]["get_weather"].get("default_config") or {}
        assert cfg.get("units") in {"imperial", "metric"}

    def test_config_schema_documents_user_controls(self):
        raw, _ = _load_integration_manifest("openweather")
        schema = raw["tool_widgets"]["get_weather"]["config_schema"]
        assert schema["properties"]["units"]["enum"] == ["imperial", "metric"]
        assert schema["properties"]["show_feels_like"]["type"] == "boolean"


class TestWebSearchWidget:
    def test_registers_as_core_search_results(self):
        raw, base = _load_integration_manifest("web_search")
        tool_widgets = raw["tool_widgets"]
        count = _register_widgets("integration:web_search", tool_widgets, base_dir=base)
        assert count == 1
        tmpl = _widget_templates["web_search"]
        assert tmpl["content_type"] == "application/vnd.spindrel.components+json"
        assert tmpl["view_key"] == "core.search_results"
        assert tmpl.get("html_template_body") is None

    def test_sample_payload_has_results(self):
        raw, _ = _load_integration_manifest("web_search")
        sample = raw["tool_widgets"]["web_search"]["sample_payload"]
        assert sample["count"] == len(sample["results"])
        # Non-zero count so the preview shows cards on first open.
        assert sample["count"] > 0


class TestFrigateListCamerasWidget:
    def test_registers_as_components_with_drilldown(self):
        raw, base = _load_integration_manifest("frigate")
        tool_widgets = raw["tool_widgets"]
        count = _register_widgets("integration:frigate", tool_widgets, base_dir=base)
        # Three widgets: snapshot, events_timeline, list_cameras.
        assert count == 3
        tmpl = _widget_templates["frigate_list_cameras"]
        # Ported to tiles v2 in Phase 5 — no per-tile live thumbnails, click
        # drills into the per-camera snapshot widget. Slow state_poll catches
        # camera add/remove events only.
        assert tmpl["content_type"] == "application/vnd.spindrel.components+json"
        assert tmpl["state_poll"]["refresh_interval_seconds"] == 300
        assert tmpl["transform"].endswith(":render_cameras_widget")
        assert tmpl["state_poll"]["transform"].endswith(":cameras_view")


class TestFrigateSnapshotWidgetCarriesCamera:
    """Regression: state_poll args.camera = ``{{display_label}}``, so the
    envelope's display_label must resolve to the actual camera name — not
    the widget's static label — or every auto-refresh hits Frigate with a
    bogus camera id and 404s. Fixed 2026-04-19 by adding ``camera`` to the
    tool's result and templating ``display_label: "{{camera}}"``.
    """

    def test_display_label_resolves_to_camera_from_result(self):
        raw, base = _load_integration_manifest("frigate")
        _register_widgets("integration:frigate", raw["tool_widgets"], base_dir=base)
        result = json.dumps({
            "attachment_id": "00000000-0000-0000-0000-000000000000",
            "filename": "driveway_snapshot.jpg",
            "size_bytes": 12345,
            "camera": "driveway",
        })
        env = apply_widget_template("frigate_snapshot", result)
        assert env is not None
        assert env.display_label == "driveway"

    def test_sample_payload_has_camera(self):
        raw, _ = _load_integration_manifest("frigate")
        sample = raw["tool_widgets"]["frigate_snapshot"]["sample_payload"]
        assert sample.get("camera"), "sample_payload needs camera for dev preview"

    def test_config_schema_documents_bbox_toggle(self):
        raw, _ = _load_integration_manifest("frigate")
        schema = raw["tool_widgets"]["frigate_snapshot"]["config_schema"]
        assert schema["properties"]["show_bbox"]["type"] == "boolean"

    def test_state_poll_args_substitute_camera_from_display_label(self):
        from app.services.widget_templates import substitute_vars

        raw, base = _load_integration_manifest("frigate")
        _register_widgets("integration:frigate", raw["tool_widgets"], base_dir=base)
        poll = _widget_templates["frigate_snapshot"]["state_poll"]
        # Simulate _do_state_poll's widget_meta for a pinned widget. The pin's
        # display_label is the camera name (captured at pin creation from the
        # envelope's {{camera}}-substituted display_label).
        widget_meta = {
            "display_label": "driveway",
            "widget_config": {"show_bbox": True},
        }
        args = substitute_vars(poll["args"], widget_meta)
        assert args["camera"] == "driveway"
        assert args["bounding_box"] is True


class TestExcalidrawWidget:
    def test_registers_both_tools_with_shared_template(self):
        raw, base = _load_integration_manifest("excalidraw")
        tool_widgets = raw["tool_widgets"]
        count = _register_widgets("integration:excalidraw", tool_widgets, base_dir=base)
        assert count == 2
        create = _widget_templates["create_excalidraw"]
        mermaid = _widget_templates["mermaid_to_excalidraw"]
        assert create["content_type"] == "application/vnd.spindrel.html+interactive"
        assert mermaid["content_type"] == "application/vnd.spindrel.html+interactive"
        # Same rendered shape (attachment_id + filename) so they share the
        # widget body byte-for-byte.
        assert create["html_template_body"] == mermaid["html_template_body"]

    def test_sample_payload_has_attachment_id(self):
        raw, _ = _load_integration_manifest("excalidraw")
        sample = raw["tool_widgets"]["create_excalidraw"]["sample_payload"]
        assert sample["attachment_id"]
        assert sample["filename"]
        assert sample["mime_type"].startswith("image/")


class TestConfigRidesIntoHtmlToolResult:
    """Slice 0: merged config must land in the canonical HTML runtime
    widgetConfig channel, with toolResult.config preserved for compatibility."""

    def test_generate_image_gets_empty_default_config(self):
        raw, base = _load_core_widgets("generate_image")
        _register_widgets("core:generate_image", raw, base_dir=base)
        env = apply_widget_template(
            "generate_image",
            json.dumps({"prompt": "x", "images": []}),
        )
        assert "window.spindrel.widgetConfig = {};" in env.body
        assert "window.spindrel.toolResult = " in env.body

    def test_web_search_structured_data_feeds_core_renderer(self):
        raw, base = _load_integration_manifest("web_search")
        _register_widgets("integration:web_search", raw["tool_widgets"], base_dir=base)
        env = apply_widget_template(
            "web_search",
            json.dumps({
                "query": "x",
                "results": [{"title": "A", "url": "https://example.com", "content": "Snippet"}],
                "count": 1,
            }),
        )
        body = json.loads(env.body)
        assert env.content_type == "application/vnd.spindrel.components+json"
        assert env.view_key == "core.search_results"
        assert env.data["query"] == "x"
        assert env.data["results"][0]["url"] == "https://example.com"
        assert body["components"][2]["items"][0]["title"] == "A"
