"""Tests for the widget template engine."""
import json
import pytest

from app.services.widget_templates import (
    _substitute,
    _substitute_string,
    _resolve_path,
    _evaluate_expression,
    apply_widget_template,
    apply_state_poll,
    substitute_vars,
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


class TestSubstituteStringMixed:
    """Regression: mixed-content strings with multiple {{...}} pairs must substitute
    each independently. Earlier fullmatch-based fast path backtracked the non-greedy
    `.+?` across the whole string, swallowing "}} · {{" into the expression and
    returning None (the OpenWeather widget's `"{{current.temperature}} · {{current.conditions}}"`
    rendered with `text: null`)."""

    def test_two_expressions_joined_by_static(self):
        data = {"current": {"temperature": "72°F", "conditions": "clear sky"}}
        got = _substitute_string(
            "{{current.temperature}} · {{current.conditions}}", data,
        )
        assert got == "72°F · clear sky"

    def test_three_expressions(self):
        data = {"a": 1, "b": 2, "c": 3}
        assert _substitute_string("{{a}}/{{b}}/{{c}}", data) == "1/2/3"

    def test_single_expression_preserves_type(self):
        # Fast path must still fire for truly-single expressions so bools/lists
        # don't get stringified.
        assert _substitute_string("{{flag}}", {"flag": True}) is True
        assert _substitute_string("{{items}}", {"items": [1, 2]}) == [1, 2]

    def test_expression_with_map_transform_braces(self):
        # The map transform payload contains braces; the single-expression fast
        # path must still treat the whole string as one expression.
        data = {"items": [{"n": "a", "i": 1}]}
        got = _substitute_string("{{items | map: {label: n, value: i} }}", data)
        assert got == [{"label": "a", "value": 1}]

    def test_missing_var_in_mixed_string_becomes_empty(self):
        assert _substitute_string("prefix-{{missing}}-suffix", {}) == "prefix--suffix"

    def test_static_string_unchanged(self):
        assert _substitute_string("no vars here", {"x": 1}) == "no vars here"


class TestSubstituteVarsPublic:
    """`substitute_vars` is the public entry used by state_poll args templating."""

    def test_deep_copies_input(self):
        original = {"location": "{{display_label}}"}
        result = substitute_vars(original, {"display_label": "Paris, FR"})
        assert result == {"location": "Paris, FR"}
        # Original must not be mutated — _do_state_poll reuses the poll_cfg dict.
        assert original == {"location": "{{display_label}}"}

    def test_nested_structures(self):
        template = {
            "args": {
                "location": "{{display_label}}",
                "opts": ["{{tool_name}}", "static"],
            }
        }
        meta = {"display_label": "London", "tool_name": "get_weather"}
        got = substitute_vars(template, meta)
        assert got == {
            "args": {"location": "London", "opts": ["get_weather", "static"]}
        }

    def test_missing_vars_substitute_to_empty_string_in_mixed(self):
        got = substitute_vars({"q": "id:{{x}}"}, {})
        assert got == {"q": "id:"}


class TestApplyWidgetTemplateRefreshInterval:
    """The `refresh_interval_seconds` hint on state_poll flows into the envelope
    so the UI can set an auto-refresh timer on pinned widgets."""

    def setup_method(self):
        _widget_templates.clear()

    def _register(self, state_poll):
        _widget_templates["TestTool"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": [{"type": "status", "text": "ok"}]},
            "state_poll": state_poll,
            "source": "test",
        }

    def test_interval_propagated_to_envelope(self):
        self._register({"tool": "TestTool", "args": {}, "refresh_interval_seconds": 3600})
        env = apply_widget_template("TestTool", json.dumps({}))
        assert env is not None
        assert env.refreshable is True
        assert env.refresh_interval_seconds == 3600

    def test_missing_interval_is_none(self):
        self._register({"tool": "TestTool", "args": {}})
        env = apply_widget_template("TestTool", json.dumps({}))
        assert env.refresh_interval_seconds is None

    def test_no_state_poll_means_not_refreshable(self):
        _widget_templates["TestTool"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "source": "test",
        }
        env = apply_widget_template("TestTool", json.dumps({}))
        assert env.refreshable is False
        assert env.refresh_interval_seconds is None

    def test_envelope_compact_dict_includes_interval(self):
        self._register({"tool": "TestTool", "args": {}, "refresh_interval_seconds": 1800})
        env = apply_widget_template("TestTool", json.dumps({}))
        d = env.compact_dict()
        assert d["refresh_interval_seconds"] == 1800
        assert d["refreshable"] is True

    def test_envelope_compact_dict_omits_interval_when_unset(self):
        self._register({"tool": "TestTool", "args": {}})
        env = apply_widget_template("TestTool", json.dumps({}))
        d = env.compact_dict()
        assert "refresh_interval_seconds" not in d


class TestApplyStatePoll:
    """`apply_state_poll` renders the state_poll.template against polled raw
    results and also propagates refresh_interval_seconds + display_label."""

    def setup_method(self):
        _widget_templates.clear()

    def test_renders_template_and_carries_display_label(self):
        _widget_templates["get_weather"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "state_poll": {
                "tool": "get_weather",
                "args": {"location": "{{display_label}}"},
                "refresh_interval_seconds": 3600,
                "template": {
                    "v": 1,
                    "components": [
                        {"type": "heading", "text": "{{location}}", "level": 3},
                    ],
                },
            },
            "source": "test",
        }

        raw = json.dumps({"location": "Lambertville, NJ, US"})
        env = apply_state_poll(
            "get_weather", raw,
            {"display_label": "Lambertville, NJ, US", "tool_name": "get_weather"},
        )
        assert env is not None
        body = json.loads(env.body)
        assert body["components"][0]["text"] == "Lambertville, NJ, US"
        assert env.display_label == "Lambertville, NJ, US"
        assert env.refresh_interval_seconds == 3600
        assert env.refreshable is True

    def test_returns_none_when_no_state_poll(self):
        _widget_templates["TestTool"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "source": "test",
        }
        assert apply_state_poll("TestTool", "{}", {"display_label": "x"}) is None

    def test_returns_none_when_state_poll_has_no_template(self):
        _widget_templates["TestTool"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "state_poll": {"tool": "TestTool", "args": {}},  # no template
            "source": "test",
        }
        assert apply_state_poll("TestTool", "{}", {"display_label": "x"}) is None
