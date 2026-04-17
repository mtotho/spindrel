"""Tests for state_poll arg templating and per-args cache keying in the
widget-actions router. Exercises the behaviour the OpenWeather integration
relies on: each pinned widget re-polls with its own location (carried via
display_label) and cache entries don't collide across widgets."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import api_v1_widget_actions as router_mod
from app.services.widget_templates import _widget_templates


@pytest.fixture(autouse=True)
def _reset_state():
    """Wipe module-level caches between tests so assertions are deterministic."""
    router_mod._poll_cache.clear()
    _widget_templates.clear()
    yield
    router_mod._poll_cache.clear()
    _widget_templates.clear()


def _register_weather_widget():
    """Minimal get_weather widget whose state_poll templates location from display_label."""
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
                "components": [{"type": "heading", "text": "{{location}}", "level": 3}],
            },
        },
        "source": "test",
    }


class TestStatePollArgSubstitution:
    @pytest.mark.asyncio
    async def test_display_label_substituted_into_args(self):
        _register_weather_widget()
        poll_cfg = _widget_templates["get_weather"]["state_poll"]

        # Stub the local tool call — capture args so we can assert substitution.
        stub = AsyncMock(return_value=json.dumps({"location": "Paris, FR"}))
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            env = await router_mod._do_state_poll(
                tool_name="get_weather",
                display_label="Paris, FR",
                poll_cfg=poll_cfg,
            )

        assert env is not None
        # The sent args must be the substituted JSON, not the raw template.
        sent_args = json.loads(stub.await_args.args[1])
        assert sent_args == {"location": "Paris, FR"}

    @pytest.mark.asyncio
    async def test_different_display_labels_do_not_share_cache(self):
        _register_weather_widget()
        poll_cfg = _widget_templates["get_weather"]["state_poll"]

        stub = AsyncMock(side_effect=[
            json.dumps({"location": "Paris, FR"}),
            json.dumps({"location": "Tokyo, JP"}),
        ])
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            env_paris = await router_mod._do_state_poll(
                tool_name="get_weather", display_label="Paris, FR", poll_cfg=poll_cfg,
            )
            env_tokyo = await router_mod._do_state_poll(
                tool_name="get_weather", display_label="Tokyo, JP", poll_cfg=poll_cfg,
            )

        # Each widget must have hit the tool — cache keyed by (tool, args).
        assert stub.await_count == 2
        assert json.loads(env_paris.body)["components"][0]["text"] == "Paris, FR"
        assert json.loads(env_tokyo.body)["components"][0]["text"] == "Tokyo, JP"

    @pytest.mark.asyncio
    async def test_same_display_label_reuses_cache_within_ttl(self):
        _register_weather_widget()
        poll_cfg = _widget_templates["get_weather"]["state_poll"]

        stub = AsyncMock(return_value=json.dumps({"location": "Paris, FR"}))
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            await router_mod._do_state_poll(
                tool_name="get_weather", display_label="Paris, FR", poll_cfg=poll_cfg,
            )
            await router_mod._do_state_poll(
                tool_name="get_weather", display_label="Paris, FR", poll_cfg=poll_cfg,
            )

        # Second call must hit the cache — not the tool.
        assert stub.await_count == 1


class TestInvalidatePollCache:
    def test_sweeps_all_arg_variants_for_tool(self):
        # Seed the cache with two variants for get_weather plus an unrelated entry.
        router_mod._poll_cache[("get_weather", '{"location":"Paris"}')] = (0.0, "x")
        router_mod._poll_cache[("get_weather", '{"location":"Tokyo"}')] = (0.0, "y")
        router_mod._poll_cache[("OtherTool", "{}")] = (0.0, "z")

        with patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            router_mod.invalidate_poll_cache_for({"tool": "get_weather"})

        remaining = set(router_mod._poll_cache.keys())
        assert remaining == {("OtherTool", "{}")}

    def test_no_op_when_tool_missing(self):
        router_mod._poll_cache[("OtherTool", "{}")] = (0.0, "z")
        router_mod.invalidate_poll_cache_for({})  # no 'tool' key
        assert ("OtherTool", "{}") in router_mod._poll_cache
