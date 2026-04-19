"""Smoke tests for the Phase 2 flagship HTML widget catalog.

Covers the four widgets shipped on 2026-04-19:

- ``generate_image``  → app/tools/local/image.widgets.yaml
- ``get_weather``     → integrations/openweather/integration.yaml
- ``web_search``      → integrations/web_search/integration.yaml
- ``frigate_list_cameras`` → integrations/frigate/integration.yaml

Each widget must register with the correct ``html+interactive`` content_type,
a resolvable ``html_template.path``, and a representative ``sample_payload``
so the dev-panel preview renders on first open.
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


def _load_core_widgets(stem: str) -> tuple[dict, Path]:
    path = REPO_ROOT / "app" / "tools" / "local" / f"{stem}.widgets.yaml"
    return yaml.safe_load(path.read_text()), REPO_ROOT / "app" / "tools" / "local"


class TestGenerateImageWidget:
    def test_registers_from_yaml(self):
        raw, base = _load_core_widgets("image")
        count = _register_widgets("core:image", raw, base_dir=base)
        assert count == 1
        tmpl = _widget_templates["generate_image"]
        assert tmpl["content_type"] == "application/vnd.spindrel.html+interactive"
        assert tmpl["html_template_body"]
        # Widget references window.spindrel.toolArgs? No — prompt lives on the
        # tool result now. Confirm the widget reads the prompt off toolResult.
        assert "toolResult" in tmpl["html_template_body"]

    def test_sample_payload_renders(self):
        raw, base = _load_core_widgets("image")
        _register_widgets("core:image", raw, base_dir=base)
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


class TestWebSearchWidget:
    def test_registers_as_html(self):
        raw, base = _load_integration_manifest("web_search")
        tool_widgets = raw["tool_widgets"]
        count = _register_widgets("integration:web_search", tool_widgets, base_dir=base)
        assert count == 1
        tmpl = _widget_templates["web_search"]
        assert tmpl["content_type"] == "application/vnd.spindrel.html+interactive"

    def test_default_config_declares_starred_array(self):
        raw, _ = _load_integration_manifest("web_search")
        cfg = raw["tool_widgets"]["web_search"]["default_config"]
        assert cfg["starred"] == []

    def test_sample_payload_has_results(self):
        raw, _ = _load_integration_manifest("web_search")
        sample = raw["tool_widgets"]["web_search"]["sample_payload"]
        assert sample["count"] == len(sample["results"])
        # Non-zero count so the preview shows cards on first open.
        assert sample["count"] > 0


class TestFrigateListCamerasWidget:
    def test_registers_as_html(self):
        raw, base = _load_integration_manifest("frigate")
        tool_widgets = raw["tool_widgets"]
        count = _register_widgets("integration:frigate", tool_widgets, base_dir=base)
        # Now 3 widgets: snapshot, events_timeline, list_cameras.
        assert count == 3
        tmpl = _widget_templates["frigate_list_cameras"]
        assert tmpl["content_type"] == "application/vnd.spindrel.html+interactive"
        # Per-tile snapshot polling lives in JS; the list itself only needs
        # a slow state_poll (300s) to catch camera add/remove events.
        assert tmpl["state_poll"]["refresh_interval_seconds"] == 300


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
            "config": {"show_bbox": True},
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
    """Slice 0: merged config must land in toolResult.config for widgets."""

    def test_generate_image_gets_empty_default_config(self):
        raw, base = _load_core_widgets("image")
        _register_widgets("core:image", raw, base_dir=base)
        env = apply_widget_template(
            "generate_image",
            json.dumps({"prompt": "x", "images": []}),
        )
        preamble = env.body.split("</script>")[0]
        payload = preamble.split("window.spindrel.toolResult = ", 1)[1].rstrip(";")
        # Config is present (possibly empty {}) — widgets rely on its presence.
        data = json.loads(payload)
        assert "config" in data

    def test_web_search_starred_config_is_merged(self):
        raw, base = _load_integration_manifest("web_search")
        _register_widgets("integration:web_search", raw["tool_widgets"], base_dir=base)
        env = apply_widget_template(
            "web_search",
            json.dumps({"query": "x", "results": [], "count": 0}),
            widget_config={"starred": ["https://example.com"]},
        )
        preamble = env.body.split("</script>")[0]
        payload = preamble.split("window.spindrel.toolResult = ", 1)[1].rstrip(";")
        data = json.loads(payload)
        assert data["config"]["starred"] == ["https://example.com"]
