"""Unit tests for app.tools.registry."""
import json

import pytest

from app.tools import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """Save and restore registry state around each test."""
    backup = registry._tools.copy()
    yield
    registry._tools.clear()
    registry._tools.update(backup)


def _register_dummy(name: str = "dummy_tool", func=None):
    """Register a simple dummy tool."""
    if func is None:
        async def func(**kwargs):
            return json.dumps({"ok": True, **kwargs})
    schema = {"type": "function", "function": {"name": name, "parameters": {}}}
    registry.register(schema)(func)
    return func


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------

class TestRegister:
    def test_stores_in_tools(self):
        _register_dummy("my_tool")
        assert "my_tool" in registry._tools
        assert registry._tools["my_tool"]["schema"]["function"]["name"] == "my_tool"

    def test_picks_up_source_dir(self):
        old = registry._current_load_source_dir
        registry._current_load_source_dir = "/custom/dir"
        try:
            _register_dummy("sourced_tool")
            assert registry._tools["sourced_tool"]["source_dir"] == "/custom/dir"
        finally:
            registry._current_load_source_dir = old

    def test_required_capabilities_stored(self):
        from app.domain.capability import Capability

        async def _f(**_):
            return "ok"

        registry.register(
            {"type": "function", "function": {"name": "needs_ephem", "parameters": {}}},
            required_capabilities=frozenset({Capability.EPHEMERAL}),
        )(_f)
        req_caps, req_ints = registry.get_tool_capability_requirements("needs_ephem")
        assert req_caps == frozenset({Capability.EPHEMERAL})
        assert req_ints is None

    def test_required_integrations_stored(self):
        async def _f(**_):
            return "ok"

        registry.register(
            {"type": "function", "function": {"name": "slack_only", "parameters": {}}},
            required_integrations=frozenset({"slack"}),
        )(_f)
        req_caps, req_ints = registry.get_tool_capability_requirements("slack_only")
        assert req_caps is None
        assert req_ints == frozenset({"slack"})

    def test_default_requirements_are_none(self):
        _register_dummy("unrestricted")
        req_caps, req_ints = registry.get_tool_capability_requirements("unrestricted")
        assert req_caps is None
        assert req_ints is None

    def test_unknown_tool_returns_none_tuple(self):
        req_caps, req_ints = registry.get_tool_capability_requirements("does_not_exist")
        assert (req_caps, req_ints) == (None, None)

    def test_context_requirements_default_false(self):
        _register_dummy("ctx_default")
        bot, channel = registry.get_tool_context_requirements("ctx_default")
        assert bot is False
        assert channel is False

    def test_context_requirements_round_trip(self):
        async def _f(**_):
            return "ok"

        registry.register(
            {"type": "function", "function": {"name": "needs_ctx", "parameters": {}}},
            requires_bot_context=True,
            requires_channel_context=True,
        )(_f)
        bot, channel = registry.get_tool_context_requirements("needs_ctx")
        assert bot is True
        assert channel is True

    def test_context_requirements_unknown_tool_false(self):
        bot, channel = registry.get_tool_context_requirements("nonexistent_tool")
        assert (bot, channel) == (False, False)


# ---------------------------------------------------------------------------
# iter_registered_tools()
# ---------------------------------------------------------------------------

class TestIterRegisteredTools:
    def test_returns_tuples(self):
        _register_dummy("tool_a")
        _register_dummy("tool_b")
        result = registry.iter_registered_tools()
        names = [r[0] for r in result]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_tuple_shape(self):
        _register_dummy("tool_x")
        for item in registry.iter_registered_tools():
            if item[0] == "tool_x":
                name, schema, source_dir, source_integration, source_file = item
                assert name == "tool_x"
                assert isinstance(schema, dict)
                break


# ---------------------------------------------------------------------------
# get_local_tool_schemas()
# ---------------------------------------------------------------------------

class TestGetLocalToolSchemas:
    def test_returns_matching(self):
        _register_dummy("foo")
        _register_dummy("bar")
        result = registry.get_local_tool_schemas(["foo"])
        assert len(result) == 1
        assert result[0]["function"]["name"] == "foo"

    def test_returns_empty_for_none(self):
        assert registry.get_local_tool_schemas(None) == []

    def test_returns_empty_for_empty_list(self):
        assert registry.get_local_tool_schemas([]) == []

    def test_skips_unknown(self):
        _register_dummy("foo")
        result = registry.get_local_tool_schemas(["foo", "nonexistent"])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# is_local_tool()
# ---------------------------------------------------------------------------

class TestIsLocalTool:
    def test_true_for_registered(self):
        _register_dummy("exists")
        assert registry.is_local_tool("exists") is True

    def test_false_for_unknown(self):
        assert registry.is_local_tool("no_such_tool") is False


# ---------------------------------------------------------------------------
# call_local_tool()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCallLocalTool:
    async def test_calls_function(self):
        async def my_tool(name: str = "world"):
            return f"Hello {name}"

        _register_dummy("greeter", func=my_tool)
        result = await registry.call_local_tool("greeter", '{"name": "Alice"}')
        assert result == "Hello Alice"

    async def test_unknown_tool(self):
        result = await registry.call_local_tool("nonexistent", "{}")
        parsed = json.loads(result)
        assert "error" in parsed

    async def test_handles_exception(self):
        async def bad_tool():
            raise ValueError("boom")

        _register_dummy("bad", func=bad_tool)
        result = await registry.call_local_tool("bad", "{}")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "boom" in parsed["error"]

    async def test_empty_arguments(self):
        async def simple():
            return "ok"

        _register_dummy("simple", func=simple)
        result = await registry.call_local_tool("simple", "")
        assert result == "ok"

    async def test_json_result(self):
        async def dict_tool():
            return {"key": "value"}

        _register_dummy("dict_tool", func=dict_tool)
        result = await registry.call_local_tool("dict_tool", "{}")
        assert json.loads(result) == {"key": "value"}

    async def test_unicode_preserved_in_dict_result(self):
        async def weather_like():
            return {"temp": "78.28°F", "loc": "Montréal", "emoji": "☀️"}

        _register_dummy("weather_like", func=weather_like)
        result = await registry.call_local_tool("weather_like", "{}")
        assert "°F" in result
        assert "Montréal" in result
        assert "☀️" in result
        assert "\\u00b0" not in result

    async def test_unicode_preserved_in_string_result(self):
        async def pre_serialized():
            return json.dumps({"temp": "78.28°F"}, ensure_ascii=False)

        _register_dummy("pre_serialized", func=pre_serialized)
        result = await registry.call_local_tool("pre_serialized", "{}")
        assert "°F" in result
        assert "\\u00b0" not in result

    async def test_unicode_preserved_in_error(self):
        async def bad():
            raise ValueError("temperature out of range — °F expected")

        _register_dummy("bad_unicode", func=bad)
        result = await registry.call_local_tool("bad_unicode", "{}")
        assert "°F" in result or "—" in result
        assert "\\u00b0" not in result

    async def test_bare_string_recovery_single_required_param(self):
        """Models sometimes send bare strings instead of JSON objects.

        When the tool has exactly one required string parameter, recover
        by mapping the raw string to that parameter.
        """
        async def echo(command: str):
            return f"got: {command}"

        schema = {
            "type": "function",
            "function": {
                "name": "echo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command"},
                    },
                    "required": ["command"],
                },
            },
        }
        registry.register(schema)(echo)
        result = await registry.call_local_tool("echo", "tasks +list")
        assert result == "got: tasks +list"

    async def test_bare_string_no_recovery_multi_params(self):
        """When there are multiple params, bare string should still error."""
        async def multi(a: str, b: str):
            return "nope"

        schema = {
            "type": "function",
            "function": {
                "name": "multi",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                    },
                    "required": ["a", "b"],
                },
            },
        }
        registry.register(schema)(multi)
        result = await registry.call_local_tool("multi", "bare string")
        parsed = json.loads(result)
        assert "error" in parsed
