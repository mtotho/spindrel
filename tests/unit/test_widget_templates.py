"""Tests for the widget template engine."""
import json
import pytest

from app.services.widget_templates import (
    _substitute,
    _resolve_path,
    _evaluate_expression,
    apply_widget_template,
    _widget_templates,
)


class TestResolvePath:
    def test_simple_key(self):
        assert _resolve_path("name", {"name": "Office"}) == "Office"

    def test_nested_dot_path(self):
        assert _resolve_path("data.targets", {"data": {"targets": [1, 2]}}) == [1, 2]

    def test_array_index(self):
        data = {"items": [{"id": "a"}, {"id": "b"}]}
        assert _resolve_path("items[0].id", data) == "a"
        assert _resolve_path("items[1].id", data) == "b"

    def test_missing_key(self):
        assert _resolve_path("missing", {"name": "x"}) is None

    def test_missing_nested(self):
        assert _resolve_path("a.b.c", {"a": {"x": 1}}) is None

    def test_array_out_of_bounds(self):
        assert _resolve_path("items[5]", {"items": [1]}) is None


class TestEvaluateExpression:
    def test_equality_true(self):
        assert _evaluate_expression("state == 'on'", {"state": "on"}) is True

    def test_equality_false(self):
        assert _evaluate_expression("state == 'on'", {"state": "off"}) is False

    def test_map_transform(self):
        data = {"items": [{"name": "A", "id": "1"}, {"name": "B", "id": "2"}]}
        result = _evaluate_expression(
            "items | map: {label: name, value: id}", data
        )
        assert result == [{"label": "A", "value": "1"}, {"label": "B", "value": "2"}]

    def test_pluck_transform(self):
        data = {"items": [{"name": "Office"}, {"name": "Kitchen"}]}
        result = _evaluate_expression("items | pluck: name", data)
        assert result == ["Office", "Kitchen"]

    def test_join_transform(self):
        data = {"items": [{"name": "Office"}, {"name": "Kitchen"}]}
        result = _evaluate_expression("items | pluck: name | join: , ", data)
        assert result == "Office, Kitchen"

    def test_pluck_join_chain(self):
        data = {"data": {"success": [
            {"name": "Office", "id": "office"},
            {"name": "Light Switch", "id": "light.x"},
        ]}}
        result = _evaluate_expression("data.success | pluck: name | join: , ", data)
        assert result == "Office, Light Switch"


class TestSubstitute:
    def test_string_replacement(self):
        template = {"text": "Hello {{name}}"}
        result = _substitute(template, {"name": "World"})
        assert result == {"text": "Hello World"}

    def test_full_expression_keeps_type(self):
        template = {"value": "{{state == 'on'}}"}
        result = _substitute(template, {"state": "on"})
        assert result == {"value": True}

    def test_nested_dict(self):
        template = {
            "components": [
                {"type": "status", "text": "{{status}}"},
                {"type": "properties", "items": "{{data.success | map: {label: name, value: id} }}"},
            ]
        }
        data = {
            "status": "done",
            "data": {"success": [{"name": "Office", "id": "office"}]},
        }
        result = _substitute(template, data)
        assert result["components"][0]["text"] == "done"
        assert result["components"][1]["items"] == [{"label": "Office", "value": "office"}]


class TestApplyWidgetTemplate:
    def setup_method(self):
        _widget_templates.clear()

    def test_no_template(self):
        assert apply_widget_template("unknown_tool", '{"data": {}}') is None

    def test_basic_template(self):
        _widget_templates["TestTool"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {
                "v": 1,
                "components": [
                    {"type": "status", "text": "{{response_type}}", "color": "success"},
                ],
            },
            "integration_id": "test",
        }

        raw = json.dumps({"response_type": "action_done", "data": {}})
        env = apply_widget_template("TestTool", raw)
        assert env is not None
        assert env.content_type == "application/vnd.spindrel.components+json"
        assert env.display == "inline"

        body = json.loads(env.body)
        assert body["v"] == 1
        assert body["components"][0]["text"] == "action_done"

    def test_server_prefixed_name(self):
        """MCP tools are often named 'server-ToolName' — template lookup strips the prefix."""
        _widget_templates["HassTurnOn"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": [{"type": "status", "text": "on", "color": "success"}]},
            "integration_id": "homeassistant",
        }
        raw = json.dumps({"response_type": "action_done", "data": {}})
        # Full prefixed name should still match
        env = apply_widget_template("homeassistant-HassTurnOn", raw)
        assert env is not None
        body = json.loads(env.body)
        assert body["components"][0]["text"] == "on"

    def test_non_json_result(self):
        _widget_templates["TestTool"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "integration_id": "test",
        }
        assert apply_widget_template("TestTool", "not json") is None

    def test_ha_turn_on_template(self):
        """Simulates the HassTurnOn tool result with our HA integration template."""
        _widget_templates["HassTurnOn"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {
                "v": 1,
                "components": [
                    {"type": "status", "text": "Turned on", "color": "success"},
                    {
                        "type": "properties",
                        "layout": "inline",
                        "items": "{{data.success | map: {label: name, value: id} }}",
                    },
                    {
                        "type": "toggle",
                        "label": "Power",
                        "value": True,
                        "action": {
                            "dispatch": "tool",
                            "tool": "HassTurnOff",
                            "args": {"area": "{{data.success[0].id}}"},
                            "optimistic": True,
                        },
                    },
                ],
            },
            "integration_id": "homeassistant",
        }

        raw = json.dumps({
            "speech": {},
            "response_type": "action_done",
            "data": {
                "targets": [],
                "success": [
                    {"name": "Office", "type": "area", "id": "office"},
                    {"name": "Office Light Switch", "type": "entity", "id": "light.shelly1minig3"},
                ],
                "failed": [],
            },
        })

        env = apply_widget_template("HassTurnOn", raw)
        assert env is not None
        body = json.loads(env.body)
        components = body["components"]

        # Status badge
        assert components[0]["type"] == "status"
        assert components[0]["text"] == "Turned on"

        # Properties mapped from success array
        assert components[1]["type"] == "properties"
        assert components[1]["items"][0] == {"label": "Office", "value": "office"}
        assert components[1]["items"][1] == {"label": "Office Light Switch", "value": "light.shelly1minig3"}

        # Toggle with resolved action args
        assert components[2]["type"] == "toggle"
        assert components[2]["value"] is True
        assert components[2]["action"]["args"]["area"] == "office"
