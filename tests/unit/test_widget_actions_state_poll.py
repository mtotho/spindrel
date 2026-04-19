"""Tests for state_poll arg templating and per-args cache keying in the
widget-actions router. Exercises the behaviour the OpenWeather integration
relies on: each pinned widget re-polls with its own location (carried via
display_label) and cache entries don't collide across widgets."""
import json
import uuid
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


class TestStatePollAgentContext:
    @pytest.mark.asyncio
    async def test_bot_and_channel_context_set_during_call(self):
        """``_do_state_poll`` must set ContextVars before invoking the poll tool
        so dashboard-pinned tools that read ``current_bot_id`` / channel resolve
        identity from the pin's source instead of returning "No bot context"."""
        from app.agent.context import current_bot_id, current_channel_id

        _register_weather_widget()
        poll_cfg = _widget_templates["get_weather"]["state_poll"]
        captured: dict = {}

        async def _probe(_name, _args):
            captured["bot_id"] = current_bot_id.get()
            captured["channel_id"] = current_channel_id.get()
            return json.dumps({"location": "Boise, ID"})

        channel = uuid.uuid4()
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", side_effect=_probe), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            await router_mod._do_state_poll(
                tool_name="get_weather",
                display_label="Boise, ID",
                poll_cfg=poll_cfg,
                bot_id="weather-bot",
                channel_id=channel,
            )
        assert captured["bot_id"] == "weather-bot"
        assert captured["channel_id"] == channel

    @pytest.mark.asyncio
    async def test_context_unset_when_no_bot_passed(self):
        """When no bot/channel is provided, ContextVars stay at their defaults
        (None) — so a poll tool that doesn't need context isn't accidentally
        bound to a previous request's identity."""
        from app.agent.context import current_bot_id, current_channel_id

        _register_weather_widget()
        poll_cfg = _widget_templates["get_weather"]["state_poll"]
        captured: dict = {}

        async def _probe(_name, _args):
            captured["bot_id"] = current_bot_id.get()
            captured["channel_id"] = current_channel_id.get()
            return json.dumps({"location": "x"})

        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", side_effect=_probe), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            await router_mod._do_state_poll(
                tool_name="get_weather",
                display_label="x",
                poll_cfg=poll_cfg,
            )
        assert captured["bot_id"] is None
        assert captured["channel_id"] is None


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
        assert "dashboard_pin_id" in (resp.error or "")

    @pytest.mark.asyncio
    async def test_missing_config_returns_error(self):
        req = router_mod.WidgetActionRequest(
            dispatch="widget_config",
            channel_id="00000000-0000-0000-0000-000000000000",
            bot_id="b",
            dashboard_pin_id=uuid.uuid4(),
        )
        resp = await router_mod._dispatch_widget_config(req)
        assert resp.ok is False
        assert "config" in (resp.error or "")

    @pytest.mark.asyncio
    async def test_patches_pin_invalidates_cache_and_returns_refreshed_envelope(self):
        from app.services import dashboard_pins as pins_mod
        _register_weather_widget_with_config()

        # Pre-seed the cache so we can assert invalidation happens.
        stale_key = ("get_weather", '{"include_daily":false,"location":"Paris"}')
        router_mod._poll_cache[stale_key] = (0.0, "stale")

        pin_id = uuid.uuid4()
        patched_pin = {
            "id": str(pin_id),
            "tool_name": "get_weather",
            "widget_config": {"show_forecast": True},
            "envelope": {"display_label": "Paris, FR"},
        }

        # Stub the shared pin-patch helper (no DB in unit tests) and the poll tool call.
        patch_stub = AsyncMock(return_value=patched_pin)
        tool_stub = AsyncMock(return_value=json.dumps({"location": "Paris, FR"}))

        class FakeAsyncSessionCtx:
            async def __aenter__(self): return object()  # unused — helper is stubbed
            async def __aexit__(self, *a): return None

        with patch.object(pins_mod, "apply_dashboard_pin_config_patch", patch_stub), \
             patch("app.db.engine.async_session", lambda: FakeAsyncSessionCtx()), \
             patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", tool_stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            req = router_mod.WidgetActionRequest(
                dispatch="widget_config",
                channel_id="00000000-0000-0000-0000-000000000000",
                bot_id="b",
                dashboard_pin_id=pin_id,
                config={"show_forecast": True},
                display_label="Paris, FR",
            )
            resp = await router_mod._dispatch_widget_config(req)

        assert resp.ok is True
        assert resp.envelope is not None
        assert resp.api_response == patched_pin
        # Pin patch was invoked with the expected merge semantics. Signature:
        # (db, pin_id, patch, *, merge=True) — patch is positional arg 2.
        assert patch_stub.await_count == 1
        assert patch_stub.await_args.args[1] == pin_id
        assert patch_stub.await_args.args[2] == {"show_forecast": True}
        # Stale cache entry for get_weather was evicted by invalidate_poll_cache_for.
        assert stale_key not in router_mod._poll_cache
        # The poll tool was called with the patched config flag (include_daily=True).
        sent = json.loads(tool_stub.await_args.args[1])
        assert sent["include_daily"] is True


class TestRefreshIdentityGuard:
    """The pin row owns ``source_bot_id`` / ``source_channel_id``. Refresh
    must force-overwrite the re-polled envelope's identity fields from the
    pin row — otherwise a pin that ever held a bad bot_id would re-stamp
    itself forever (self-amplifying loop → mint 400 spam)."""

    @pytest.mark.asyncio
    async def test_refresh_does_not_rewrite_pin_source_bot_id_from_envelope(self):
        from app.services import dashboard_pins as pins_mod

        # Register a widget whose state_poll returns an envelope trying to
        # claim source_bot_id="default" (the self-amplifying poison value).
        _widget_templates["poisoned_tool"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "state_poll": {
                "tool": "poisoned_tool",
                "args": {},
                "template": {"v": 1, "components": []},
            },
            "source": "test",
        }
        poll_cfg = _widget_templates["poisoned_tool"]["state_poll"]

        pin_id = uuid.uuid4()
        pin_channel = uuid.uuid4()

        class _FakePin:
            source_bot_id = "qa-bot"
            source_channel_id = pin_channel

        class _FakeSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def get(self, _model, _id): return _FakePin()

        captured: dict = {}

        async def _fake_update_pin_envelope(_db, _pin_id, env_dict):
            captured["env_dict"] = env_dict
            return None

        # Poll tool returns an envelope that TRIES to rewrite identity.
        poisoned_body = {
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "<div>x</div>",
            "display_label": "x",
            "source_bot_id": "default",
            "source_channel_id": str(uuid.uuid4()),
        }
        tool_stub = AsyncMock(return_value=json.dumps(poisoned_body))

        req = router_mod.WidgetRefreshRequest(
            tool_name="poisoned_tool",
            display_label="x",
            dashboard_pin_id=pin_id,
        )

        with patch.object(router_mod, "get_state_poll_config", return_value=poll_cfg), \
             patch("app.db.engine.async_session", lambda: _FakeSession()), \
             patch.object(pins_mod, "update_pin_envelope", side_effect=_fake_update_pin_envelope), \
             patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", tool_stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            # apply_state_poll's default path: register a template that
            # renders the incoming payload through — but the poll returns
            # HTML content, so apply_state_poll delegates through
            # apply_widget_template. The returned envelope still carries
            # whatever source_bot_id the HTML payload declared — which is
            # exactly the circular loop we're testing the guard against.
            resp = await router_mod.refresh_widget_state(req)

        # Refresh overwrote env_dict with the PIN row's identity before
        # persisting — regardless of what the poll envelope claimed.
        assert resp.ok is True
        assert "env_dict" in captured, "update_pin_envelope was never called"
        assert captured["env_dict"]["source_bot_id"] == "qa-bot"
        assert captured["env_dict"]["source_channel_id"] == str(pin_channel)
        # Returned envelope has the same correction so the UI sees the
        # correct bot identity on the wire too.
        assert resp.envelope["source_bot_id"] == "qa-bot"
        assert resp.envelope["source_channel_id"] == str(pin_channel)

    @pytest.mark.asyncio
    async def test_refresh_strips_identity_when_pin_has_null_bot(self):
        """If the pin row has source_bot_id=None, refresh strips the field
        from the persisted envelope rather than letting a polled value
        silently populate it."""
        from app.services import dashboard_pins as pins_mod

        _widget_templates["null_bot_tool"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "state_poll": {
                "tool": "null_bot_tool",
                "args": {},
                "template": {"v": 1, "components": []},
            },
            "source": "test",
        }
        poll_cfg = _widget_templates["null_bot_tool"]["state_poll"]

        pin_id = uuid.uuid4()

        class _FakePin:
            source_bot_id = None
            source_channel_id = None

        class _FakeSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def get(self, _model, _id): return _FakePin()

        captured: dict = {}

        async def _fake_update_pin_envelope(_db, _pin_id, env_dict):
            captured["env_dict"] = env_dict
            return None

        # Poll tool tries to inject a bot id; refresh must strip it.
        tool_stub = AsyncMock(return_value=json.dumps({
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "<div>x</div>",
            "display_label": "x",
            "source_bot_id": "sneaky-bot",
        }))

        req = router_mod.WidgetRefreshRequest(
            tool_name="null_bot_tool",
            display_label="x",
            dashboard_pin_id=pin_id,
        )

        with patch.object(router_mod, "get_state_poll_config", return_value=poll_cfg), \
             patch("app.db.engine.async_session", lambda: _FakeSession()), \
             patch.object(pins_mod, "update_pin_envelope", side_effect=_fake_update_pin_envelope), \
             patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", tool_stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            resp = await router_mod.refresh_widget_state(req)

        assert resp.ok is True
        assert "source_bot_id" not in captured["env_dict"]
        assert "source_channel_id" not in captured["env_dict"]
