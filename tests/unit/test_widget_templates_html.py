"""Tests for the HTML template mode in the widget template engine.

Covers the declarative path where a tool ships a bundled HTML file that
receives the tool's JSON result as `window.spindrel.toolResult`. See
`app/services/widget_templates.py::apply_widget_template` (html_template
branch) and `_build_html_widget_body`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.widget_templates import (
    _build_html_widget_body,
    _register_widgets,
    _resolve_html_template_paths,
    _widget_templates,
    apply_state_poll,
    apply_widget_template,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    _widget_templates.clear()
    yield
    _widget_templates.clear()


def _register_snapshot_widget(tmp_path: Path, html_body: str = "<div id='root'></div>"):
    """Register a declarative HTML widget backed by a file in tmp_path."""
    html_path = tmp_path / "widgets" / "snapshot.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_body)
    widgets = {
        "frigate_snapshot": {
            "content_type": "application/vnd.spindrel.html+interactive",
            "display": "inline",
            "display_label": "{{filename}}",
            "html_template": {"path": "widgets/snapshot.html"},
            "default_config": {"show_bbox": True},
            "state_poll": {
                "tool": "frigate_snapshot",
                "args": {"camera": "{{display_label}}", "bounding_box": "{{config.show_bbox}}"},
                "refresh_interval_seconds": 60,
            },
        },
    }
    return _register_widgets("test-integration", widgets, base_dir=tmp_path)


class TestHtmlTemplatePathResolution:
    def test_path_resolves_at_registration(self, tmp_path):
        body_html = "<h1>Live snap</h1>"
        count = _register_snapshot_widget(tmp_path, html_body=body_html)
        assert count == 1
        cached = _widget_templates["frigate_snapshot"]
        assert cached["html_template_body"] == body_html
        # Template component tree must stay unused for html-template mode.
        assert cached.get("template") is None

    def test_body_inline_accepted(self):
        widgets = {
            "my_tool": {
                "html_template": {"body": "<div>inline</div>"},
            },
        }
        count = _register_widgets("test", widgets)
        assert count == 1
        assert _widget_templates["my_tool"]["html_template_body"] == "<div>inline</div>"

    def test_missing_file_skipped(self, tmp_path):
        widgets = {
            "my_tool": {"html_template": {"path": "nope.html"}},
        }
        count = _register_widgets("test", widgets, base_dir=tmp_path)
        assert count == 0
        assert "my_tool" not in _widget_templates

    def test_path_escaping_base_dir_rejected(self, tmp_path):
        outer = tmp_path / "outside.html"
        outer.write_text("<x/>")
        nested = tmp_path / "integration"
        nested.mkdir()
        widgets = {"my_tool": {"html_template": {"path": "../outside.html"}}}
        count = _register_widgets("test", widgets, base_dir=nested)
        assert count == 0
        assert "my_tool" not in _widget_templates

    def test_template_and_html_template_both_set_rejected(self, tmp_path):
        html_path = tmp_path / "x.html"
        html_path.write_text("<x/>")
        widgets = {
            "my_tool": {
                "template": {"v": 1, "components": [{"type": "status", "text": "hi"}]},
                "html_template": {"path": "x.html"},
            },
        }
        count = _register_widgets("test", widgets, base_dir=tmp_path)
        assert count == 0
        assert "my_tool" not in _widget_templates

    def test_missing_both_skipped(self):
        widgets = {"bare_tool": {"content_type": "text/plain"}}
        count = _register_widgets("test", widgets)
        assert count == 0


class TestResolveHtmlTemplatePaths:
    def test_body_inline_no_op(self):
        widget_def = {"html_template": {"body": "<x/>"}}
        resolved, err = _resolve_html_template_paths(widget_def, None)
        assert err is None
        assert resolved is widget_def  # returned untouched

    def test_path_without_base_dir_errors(self):
        widget_def = {"html_template": {"path": "a.html"}}
        _, err = _resolve_html_template_paths(widget_def, None)
        assert err is not None
        assert "base_dir" in err

    def test_path_resolved_inline(self, tmp_path):
        (tmp_path / "w.html").write_text("<hello/>")
        widget_def = {"html_template": {"path": "w.html"}}
        resolved, err = _resolve_html_template_paths(widget_def, tmp_path)
        assert err is None
        assert resolved["html_template"]["body"] == "<hello/>"
        # path key stripped so downstream serializers emit a clean inline form.
        assert "path" not in resolved["html_template"]


class TestApplyWidgetTemplateHtmlMode:
    def test_envelope_has_html_content_type_and_preamble(self, tmp_path):
        _register_snapshot_widget(tmp_path, html_body="<div>Template</div>")
        raw = json.dumps({"attachment_id": "abc", "filename": "drive.jpg"})
        env = apply_widget_template("frigate_snapshot", raw)
        assert env is not None
        assert env.content_type == "application/vnd.spindrel.html+interactive"
        assert "<div>Template</div>" in env.body
        # Preamble comes BEFORE the template so toolResult is set before any
        # user script in the template body runs.
        assert env.body.index("window.spindrel.toolResult") < env.body.index("<div>Template</div>")
        assert env.refreshable is True
        assert env.refresh_interval_seconds == 60

    def test_preamble_carries_tool_result_json(self, tmp_path):
        _register_snapshot_widget(tmp_path)
        raw = json.dumps({"attachment_id": "abc", "filename": "x.jpg", "size_bytes": 123})
        env = apply_widget_template("frigate_snapshot", raw)
        # Extract the JSON object from the preamble literally.
        preamble = env.body.split("</script>")[0]
        json_text = preamble.split("window.spindrel.toolResult = ", 1)[1].rstrip(";")
        parsed = json.loads(json_text)
        # Tool result fields ride into the iframe verbatim; ``config`` is
        # added alongside (merged default_config + pin widget_config).
        for key, value in {"attachment_id": "abc", "filename": "x.jpg", "size_bytes": 123}.items():
            assert parsed[key] == value
        assert "config" in parsed

    def test_preamble_includes_merged_widget_config(self, tmp_path):
        _register_snapshot_widget(tmp_path)
        raw = json.dumps({"filename": "x.jpg"})
        env = apply_widget_template(
            "frigate_snapshot", raw, widget_config={"show_bbox": False},
        )
        # The merged config (default_config < widget_config) rides into the
        # iframe under `toolResult.config` so widget JS can gate rendering
        # on user-selected state (e.g. starred URLs, toggles, unit prefs).
        preamble = env.body.split("</script>")[0]
        json_text = preamble.split("window.spindrel.toolResult = ", 1)[1].rstrip(";")
        parsed = json.loads(json_text)
        assert parsed.get("config") == {"show_bbox": False}

    def test_preamble_uses_default_config_when_no_pin_overrides(self, tmp_path):
        _register_snapshot_widget(tmp_path)
        env = apply_widget_template("frigate_snapshot", json.dumps({"filename": "x"}))
        preamble = env.body.split("</script>")[0]
        json_text = preamble.split("window.spindrel.toolResult = ", 1)[1].rstrip(";")
        parsed = json.loads(json_text)
        assert parsed.get("config") == {"show_bbox": True}

    def test_display_label_substituted(self, tmp_path):
        _register_snapshot_widget(tmp_path)
        raw = json.dumps({"filename": "drive.jpg"})
        env = apply_widget_template("frigate_snapshot", raw)
        assert env.display_label == "drive.jpg"

    def test_html_envelope_large_body_not_truncated_by_widget_engine(self, tmp_path):
        # The template engine itself never applies the 4KB cap (that lives
        # in _build_envelope_from_optin / _build_default_envelope, which are
        # exempted for html+interactive). This test guards against accidentally
        # introducing a cap in the widget engine itself.
        big = "<div>" + ("x" * 8192) + "</div>"
        _register_snapshot_widget(tmp_path, html_body=big)
        env = apply_widget_template("frigate_snapshot", json.dumps({"filename": "x"}))
        assert env is not None
        assert env.body is not None
        assert len(env.body) > 8000


class TestBuildHtmlWidgetBody:
    def test_preamble_escapes_closing_script_tag(self):
        data = {"note": "before </script> after"}
        body = _build_html_widget_body("<div/>", data)
        # The literal `</script>` from user data must not terminate the
        # preamble script tag early. `</` gets escaped to `<\/`.
        # Exactly ONE `</script>` may appear — the preamble's own closing tag.
        assert body.count("</script>") == 1
        assert "<\\/script>" in body

    def test_empty_data_still_produces_valid_preamble(self):
        body = _build_html_widget_body("<p/>", {})
        assert "window.spindrel.toolResult = {};" in body
        assert body.endswith("<p/>")


class TestApplyStatePollHtmlMode:
    def test_poll_returns_html_envelope_with_fresh_preamble(self, tmp_path):
        _register_snapshot_widget(tmp_path, html_body="<div>Stable</div>")
        fresh = json.dumps({"attachment_id": "new-id", "filename": "new.jpg"})
        env = apply_state_poll(
            "frigate_snapshot",
            fresh,
            {"display_label": "driveway", "tool_name": "frigate_snapshot"},
        )
        assert env is not None
        assert env.content_type == "application/vnd.spindrel.html+interactive"
        assert '"attachment_id": "new-id"' in env.body
        assert "<div>Stable</div>" in env.body
        assert env.refreshable is True

    def test_poll_reemits_source_bot_id_and_channel(self, tmp_path):
        _register_snapshot_widget(tmp_path)
        fresh = json.dumps({"filename": "x.jpg"})
        env = apply_state_poll(
            "frigate_snapshot",
            fresh,
            {
                "display_label": "front",
                "tool_name": "frigate_snapshot",
                "source_bot_id": "bot-abc",
                "source_channel_id": "chan-xyz",
            },
        )
        assert env is not None
        # Without these, PinnedToolWidget's refresh path strips window.spindrel
        # auth on every poll and the iframe 401s.
        assert env.source_bot_id == "bot-abc"
        assert env.source_channel_id == "chan-xyz"

    def test_poll_does_not_require_state_poll_template(self, tmp_path):
        # Declarative HTML mode skips state_poll.template — freshness is the
        # whole new toolResult JSON, the HTML file re-renders on its own.
        _register_snapshot_widget(tmp_path)
        # Ensure state_poll in our fixture has no .template key.
        assert "template" not in _widget_templates["frigate_snapshot"]["state_poll"]
        env = apply_state_poll(
            "frigate_snapshot",
            json.dumps({"filename": "x"}),
            {"display_label": "x", "tool_name": "frigate_snapshot"},
        )
        assert env is not None
