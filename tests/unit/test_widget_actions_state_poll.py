"""Tests for state_poll arg templating and per-args cache keying in the
widget-actions router. Exercises the behaviour the OpenWeather integration
relies on: each pinned widget re-polls with its own location (carried via
display_label) and cache entries don't collide across widgets."""
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services import widget_action_dispatch as dispatch_mod
from app.services import widget_action_state_poll as router_mod
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

    @pytest.mark.asyncio
    async def test_same_args_different_bot_context_do_not_share_cache(self):
        _register_weather_widget()
        poll_cfg = _widget_templates["get_weather"]["state_poll"]

        stub = AsyncMock(side_effect=[
            json.dumps({"location": "BOT_A"}),
            json.dumps({"location": "BOT_B"}),
        ])
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            env_a = await router_mod._do_state_poll(
                tool_name="get_weather",
                display_label="Paris, FR",
                poll_cfg=poll_cfg,
                bot_id="bot-a",
            )
            env_b = await router_mod._do_state_poll(
                tool_name="get_weather",
                display_label="Paris, FR",
                poll_cfg=poll_cfg,
                bot_id="bot-b",
            )

        assert stub.await_count == 2
        assert json.loads(env_a.body)["components"][0]["text"] == "BOT_A"
        assert json.loads(env_b.body)["components"][0]["text"] == "BOT_B"

    @pytest.mark.asyncio
    async def test_refresh_batch_coalesces_identical_state_poll_work(self):
        _register_weather_widget()

        stub = AsyncMock(return_value=json.dumps({"location": "Paris, FR"}))
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            resp = await router_mod.refresh_widget_states_batch(
                router_mod.WidgetRefreshBatchRequest(
                    requests=[
                        router_mod.WidgetRefreshBatchItem(
                            request_id="one",
                            tool_name="get_weather",
                            display_label="Paris, FR",
                        ),
                        router_mod.WidgetRefreshBatchItem(
                            request_id="two",
                            tool_name="get_weather",
                            display_label="Paris, FR",
                        ),
                    ],
                )
            )

        assert resp.ok is True
        assert stub.await_count == 1
        assert [item.request_id for item in resp.results] == ["one", "two"]
        assert all(item.ok for item in resp.results)
        assert json.loads(resp.results[0].envelope["body"])["components"][0]["text"] == "Paris, FR"

    @pytest.mark.asyncio
    async def test_refresh_batch_does_not_coalesce_different_bot_contexts(self):
        _register_weather_widget()

        stub = AsyncMock(side_effect=[
            json.dumps({"location": "BOT_A"}),
            json.dumps({"location": "BOT_B"}),
        ])
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            resp = await router_mod.refresh_widget_states_batch(
                router_mod.WidgetRefreshBatchRequest(
                    requests=[
                        router_mod.WidgetRefreshBatchItem(
                            request_id="one",
                            tool_name="get_weather",
                            display_label="Paris, FR",
                            bot_id="bot-a",
                        ),
                        router_mod.WidgetRefreshBatchItem(
                            request_id="two",
                            tool_name="get_weather",
                            display_label="Paris, FR",
                            bot_id="bot-b",
                        ),
                    ],
                )
            )

        assert resp.ok is True
        assert stub.await_count == 2
        bodies = [json.loads(item.envelope["body"]) for item in resp.results]
        assert bodies[0]["components"][0]["text"] == "BOT_A"
        assert bodies[1]["components"][0]["text"] == "BOT_B"


class TestInvalidatePollCache:
    def test_sweeps_all_arg_variants_for_tool(self):
        # Seed the cache with two variants for get_weather plus an unrelated entry.
        router_mod._poll_cache[("get_weather", '{"location":"Paris"}', None, None)] = (0.0, "x")
        router_mod._poll_cache[("get_weather", '{"location":"Tokyo"}', None, None)] = (0.0, "y")
        router_mod._poll_cache[("OtherTool", "{}", None, None)] = (0.0, "z")

        with patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            router_mod.invalidate_poll_cache_for({"tool": "get_weather"})

        remaining = set(router_mod._poll_cache.keys())
        assert remaining == {("OtherTool", "{}", None, None)}

    def test_no_op_when_tool_missing(self):
        router_mod._poll_cache[("OtherTool", "{}", None, None)] = (0.0, "z")
        router_mod.invalidate_poll_cache_for({})  # no 'tool' key
        assert ("OtherTool", "{}", None, None) in router_mod._poll_cache


def _register_weather_widget_with_config():
    """Weather widget whose state_poll args reference widget_config.show_forecast.
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
                "include_daily": "{{widget_config.show_forecast}}",
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
    async def test_state_poll_args_use_default_widget_config(self):
        """OpenWeather relies on default_config.units during inline refresh.

        Without this merge, ``{{widget_config.units}}`` resolves to JSON null,
        OpenWeather falls back to Kelvin values, and the HTML widget still
        renders the default Fahrenheit toggle.
        """
        _widget_templates["get_weather"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "default_config": {"units": "imperial", "show_forecast": False},
            "state_poll": {
                "tool": "get_weather",
                "args": {
                    "location": "{{display_label}}",
                    "units": "{{widget_config.units}}",
                    "include_daily": "{{widget_config.show_forecast}}",
                },
                "template": {"v": 1, "components": []},
            },
            "source": "test",
        }
        poll_cfg = _widget_templates["get_weather"]["state_poll"]

        stub = AsyncMock(return_value=json.dumps({"location": "Lambertville, NJ"}))
        with patch.object(router_mod, "is_local_tool", return_value=True), \
             patch.object(router_mod, "call_local_tool", stub), \
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n):
            await router_mod._do_state_poll(
                tool_name="get_weather",
                display_label="Lambertville, NJ",
                poll_cfg=poll_cfg,
            )

        sent_args = json.loads(stub.await_args.args[1])
        assert sent_args == {
            "location": "Lambertville, NJ",
            "units": "imperial",
            "include_daily": False,
        }

    @pytest.mark.asyncio
    async def test_missing_widget_config_yields_empty_config_dict(self):
        """{{widget_config.show_forecast}} with no widget_config and no default_config
        passthrough on the poll_cfg should resolve to None → JSON null in args."""
        _widget_templates["get_weather"] = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "template": {"v": 1, "components": []},
            "state_poll": {
                "tool": "get_weather",
                "args": {"flag": "{{widget_config.missing}}"},
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
        resp = await dispatch_mod._dispatch_widget_config(req)
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
        resp = await dispatch_mod._dispatch_widget_config(req)
        assert resp.ok is False
        assert "config" in (resp.error or "")

    @pytest.mark.asyncio
    async def test_patches_pin_invalidates_cache_and_returns_refreshed_envelope(self):
        from app.services import dashboard_pins as pins_mod
        _register_weather_widget_with_config()

        # Pre-seed the cache so we can assert invalidation happens.
        stale_key = ("get_weather", '{"include_daily":false,"location":"Paris"}', None, None)
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
             patch.object(router_mod, "_resolve_tool_name", side_effect=lambda n: n), \
             patch.object(dispatch_mod, "_resolve_tool_name", side_effect=lambda n: n), \
             patch.object(dispatch_mod, "get_state_poll_config", return_value=_widget_templates["get_weather"]["state_poll"]), \
             patch.object(dispatch_mod, "_do_state_poll", wraps=router_mod._do_state_poll), \
             patch.object(dispatch_mod, "invalidate_poll_cache_for", wraps=router_mod.invalidate_poll_cache_for):
            req = router_mod.WidgetActionRequest(
                dispatch="widget_config",
                channel_id="00000000-0000-0000-0000-000000000000",
                bot_id="b",
                dashboard_pin_id=pin_id,
                config={"show_forecast": True},
                display_label="Paris, FR",
            )
            resp = await dispatch_mod._dispatch_widget_config(req)

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


class TestDashboardPinnedToolActionRefresh:
    @pytest.mark.asyncio
    async def test_tool_action_refreshes_enclosing_pin_not_action_tool(self):
        """Dashboard-pinned actions should return the pin's state_poll output.

        A Home Assistant toggle action is rendered inside the GetLiveContext
        pin. Returning the action tool's envelope makes the tile briefly swap
        identity or disappear; the authoritative post-action envelope is the
        enclosing pin's poll result.
        """
        from app.services import dashboard_pins as pins_mod

        pin_id = uuid.uuid4()
        channel_id = uuid.uuid4()
        poll_cfg = {"tool": "get_live_context", "args": {}, "post_action_settle_ms": 0}

        class _FakePin:
            id = pin_id
            tool_name = "homeassistant-GetLiveContext"
            display_label = "Kitchen light"
            envelope = {"display_label": "Old Kitchen light"}
            widget_config = {"entity_id": "light.kitchen"}
            source_bot_id = "ha-bot"
            source_channel_id = channel_id

        captured: dict = {}

        async def _fake_get_pin(_db, _pin_id):
            captured["pin_id"] = _pin_id
            return _FakePin()

        async def _fake_update_pin_envelope(_db, _pin_id, env_dict):
            captured["persisted"] = env_dict
            return _FakePin()

        async def _fake_state_poll(**kwargs):
            captured["poll_kwargs"] = kwargs
            return router_mod.ToolResultEnvelope(
                content_type="application/vnd.spindrel.components+json",
                body=json.dumps({"v": 1, "components": [{"type": "status", "text": "On"}]}),
                display="inline",
                display_label="Kitchen light",
                tool_name=kwargs["tool_name"],
            )

        req = router_mod.WidgetActionRequest(
            dispatch="tool",
            tool="homeassistant-HassTurnOn",
            args={"name": "Kitchen light"},
            dashboard_pin_id=pin_id,
            display_label="Kitchen light",
            widget_config={"entity_id": "light.kitchen"},
        )

        with patch.object(dispatch_mod, "_resolve_tool_name", side_effect=lambda n: n), \
             patch.object(dispatch_mod, "is_local_tool", return_value=True), \
             patch.object(dispatch_mod, "call_local_tool", AsyncMock(return_value="{}")), \
             patch.object(dispatch_mod, "get_state_poll_config", return_value=poll_cfg), \
             patch.object(dispatch_mod, "_do_state_poll", side_effect=_fake_state_poll), \
             patch.object(pins_mod, "get_pin", side_effect=_fake_get_pin), \
             patch.object(pins_mod, "update_pin_envelope", side_effect=_fake_update_pin_envelope):
            resp = await dispatch_mod._dispatch_tool(req, db=object())

        assert resp.ok is True
        assert resp.envelope is not None
        assert resp.envelope["display_label"] == "Kitchen light"
        assert captured["pin_id"] == pin_id
        assert captured["poll_kwargs"]["tool_name"] == "homeassistant-GetLiveContext"
        assert captured["poll_kwargs"]["widget_config"] == {"entity_id": "light.kitchen"}
        assert captured["poll_kwargs"]["bot_id"] == "ha-bot"
        assert captured["poll_kwargs"]["channel_id"] == channel_id
        assert captured["persisted"]["source_bot_id"] == "ha-bot"
        assert captured["persisted"]["source_channel_id"] == str(channel_id)
