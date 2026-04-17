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


def _register_weather_widget_with_config():
    """Weather widget whose state_poll args reference config.show_forecast.
    Mirrors the OpenWeather integration YAML."""
    _widget_templates["get_weather"] = {
        "content_type": "application/vnd.spindrel.components+json",
        "display": "inline",
        "template": {"v": 1, "components": []},
        "default_config": {"show_forecast": False},
        "state_poll": {
            "tool": "get_weather",
            "args": {
                "location": "{{display_label}}",
                "include_daily": "{{config.show_forecast}}",
            },
            "refresh_interval_seconds": 3600,
            "template": {
                "v": 1,
                "components": [{"type": "heading", "text": "{{location}}", "level": 3}],
            },
        },
        "source": "test",
    }


class TestStatePollConfigInArgs:
    @pytest.mark.asyncio
    async def test_widget_config_substitutes_into_poll_args(self):
        _register_weather_widget_with_config()
        poll_cfg = _widget_templates["get_weather"]["state_poll"]

        stub = AsyncMock(return_value=json.dumps({"location": "Paris, FR"}))
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            await router_mod._do_state_poll(
                tool_name="get_weather",
                display_label="Paris, FR",
                poll_cfg=poll_cfg,
                widget_config={"show_forecast": True},
            )

        sent_args = json.loads(stub.await_args.args[1])
        # include_daily must be a real bool (single-expression fast path preserves type)
        assert sent_args == {"location": "Paris, FR", "include_daily": True}
        assert isinstance(sent_args["include_daily"], bool)

    @pytest.mark.asyncio
    async def test_missing_widget_config_yields_empty_config_dict(self):
        """{{config.show_forecast}} with no widget_config and no default_config
        passthrough on the poll_cfg should resolve to None → JSON null in args."""
        _widget_templates["get_weather"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "state_poll": {
                "tool": "get_weather",
                "args": {"flag": "{{config.missing}}"},
                "template": {"v": 1, "components": []},
            },
            "source": "test",
        }
        poll_cfg = _widget_templates["get_weather"]["state_poll"]

        stub = AsyncMock(return_value="{}")
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            await router_mod._do_state_poll(
                tool_name="get_weather", display_label="x", poll_cfg=poll_cfg,
            )

        sent_args = json.loads(stub.await_args.args[1])
        assert sent_args == {"flag": None}

    @pytest.mark.asyncio
    async def test_different_configs_key_different_cache_entries(self):
        """Two widgets polling the same tool+location but with different
        configs must not share a cached result."""
        _register_weather_widget_with_config()
        poll_cfg = _widget_templates["get_weather"]["state_poll"]

        # Each call returns a distinct payload so we can tell which one the
        # template rendered from (cache hit vs miss).
        stub = AsyncMock(side_effect=[
            json.dumps({"location": "CURRENT_ONLY"}),
            json.dumps({"location": "WITH_FORECAST"}),
        ])
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            env_off = await router_mod._do_state_poll(
                tool_name="get_weather", display_label="Paris", poll_cfg=poll_cfg,
                widget_config={"show_forecast": False},
            )
            env_on = await router_mod._do_state_poll(
                tool_name="get_weather", display_label="Paris", poll_cfg=poll_cfg,
                widget_config={"show_forecast": True},
            )

        assert stub.await_count == 2
        assert json.loads(env_off.body)["components"][0]["text"] == "CURRENT_ONLY"
        assert json.loads(env_on.body)["components"][0]["text"] == "WITH_FORECAST"


class TestDispatchWidgetConfig:
    @pytest.mark.asyncio
    async def test_missing_pin_id_returns_error(self):
        req = router_mod.WidgetActionRequest(
            dispatch="widget_config",
            channel_id="00000000-0000-0000-0000-000000000000",
            bot_id="b",
            config={"show_forecast": True},
        )
        resp = await router_mod._dispatch_widget_config(req)
        assert resp.ok is False
        assert "pin_id" in (resp.error or "")

    @pytest.mark.asyncio
    async def test_missing_config_returns_error(self):
        req = router_mod.WidgetActionRequest(
            dispatch="widget_config",
            channel_id="00000000-0000-0000-0000-000000000000",
            bot_id="b",
            pin_id="pin1",
        )
        resp = await router_mod._dispatch_widget_config(req)
        assert resp.ok is False
        assert "config" in (resp.error or "")

    @pytest.mark.asyncio
    async def test_patches_pin_invalidates_cache_and_returns_refreshed_envelope(self):
        from app.routers import api_v1_channels as channels_mod
        _register_weather_widget_with_config()

        # Pre-seed the cache so we can assert invalidation happens.
        stale_key = ("get_weather", '{"include_daily":false,"location":"Paris"}')
        router_mod._poll_cache[stale_key] = (0.0, "stale")

        patched_pin = {
            "id": "pin1",
            "tool_name": "get_weather",
            "config": {"show_forecast": True},
            "envelope": {"display_label": "Paris, FR"},
        }

        # Stub the shared pin-patch helper (no DB in unit tests) and the poll tool call.
        patch_stub = AsyncMock(return_value=patched_pin)
        tool_stub = AsyncMock(return_value=json.dumps({"location": "Paris, FR"}))

        class FakeAsyncSessionCtx:
            async def __aenter__(self): return object()  # unused — helper is stubbed
            async def __aexit__(self, *a): return None

        with patch.object(channels_mod, "apply_widget_config_patch", patch_stub), \
             patch("app.db.engine.async_session", lambda: FakeAsyncSessionCtx()), \
             patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", tool_stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            req = router_mod.WidgetActionRequest(
                dispatch="widget_config",
                channel_id="00000000-0000-0000-0000-000000000000",
                bot_id="b",
                pin_id="pin1",
                config={"show_forecast": True},
                display_label="Paris, FR",
            )
            resp = await router_mod._dispatch_widget_config(req)

        assert resp.ok is True
        assert resp.envelope is not None
        assert resp.api_response == patched_pin
        # Pin patch was invoked with the expected merge semantics
        assert patch_stub.await_count == 1
        _args, kwargs = patch_stub.await_args
        # signature: (db, channel_id, pin_id, patch, merge=True) — patch is 4th positional
        assert patch_stub.await_args.args[2] == "pin1"
        assert patch_stub.await_args.args[3] == {"show_forecast": True}
        # Stale cache entry for get_weather was evicted by invalidate_poll_cache_for.
        assert stale_key not in router_mod._poll_cache
        # The poll tool was called with the patched config flag (include_daily=True).
        sent = json.loads(tool_stub.await_args.args[1])
        assert sent["include_daily"] is True
