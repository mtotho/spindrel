"""Tests for usage spike detection, context gathering, message formatting, and dispatch."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.usage_spike import (
    check_for_spike,
    format_alert_message,
    _gather_context,
    _dispatch_alert,
)

# The dispatch function imports renderer_registry and get_integration_meta lazily,
# so we need to patch them at the correct location.
RENDERER_REGISTRY_PATH = "app.integrations.renderer_registry"
HOOKS_PATH = "app.agent.hooks"


def _make_config(**overrides):
    """Create a mock UsageSpikeConfig with sensible defaults."""
    config = MagicMock()
    config.id = uuid.uuid4()
    config.enabled = True
    config.window_minutes = overrides.get("window_minutes", 30)
    config.baseline_hours = overrides.get("baseline_hours", 24)
    config.relative_threshold = overrides.get("relative_threshold", 2.0)
    config.absolute_threshold_usd = overrides.get("absolute_threshold_usd", 0)
    config.cooldown_minutes = overrides.get("cooldown_minutes", 60)
    config.targets = overrides.get("targets", [])
    config.target_ids = overrides.get("target_ids", [])
    config.last_alert_at = overrides.get("last_alert_at", None)
    config.last_check_at = overrides.get("last_check_at", None)
    return config


def _make_event(cost=0.01, model="gpt-4", bot_id="bot1", correlation_id=None):
    """Create a mock TraceEvent."""
    ev = MagicMock()
    ev.id = uuid.uuid4()
    ev.bot_id = bot_id
    ev.correlation_id = correlation_id or uuid.uuid4()
    ev.data = {
        "model": model,
        "response_cost": cost,
        "prompt_tokens": 100,
        "completion_tokens": 50,
    }
    return ev


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

class TestFormatAlertMessage:
    def test_basic_format(self):
        msg = format_alert_message(
            window_rate=5.0,
            baseline_rate=1.0,
            spike_ratio=5.0,
            window_minutes=30,
            baseline_hours=24,
            context={
                "top_models": [{"model": "gpt-4", "cost": 3.5, "calls": 10}],
                "top_bots": [{"bot_id": "bot1", "cost": 2.5}],
                "recent_traces": [
                    {"correlation_id": "abc12345-1234", "model": "gpt-4", "bot_id": "bot1", "cost": 1.5}
                ],
            },
        )
        assert "USAGE SPIKE ALERT" in msg
        assert "$5.00/hr" in msg
        assert "$1.00/hr" in msg
        assert "5.0x baseline" in msg
        assert "gpt-4" in msg
        assert "bot1" in msg
        assert "abc12345" in msg

    def test_no_spike_ratio(self):
        msg = format_alert_message(
            window_rate=10.0, baseline_rate=0.0, spike_ratio=None,
            window_minutes=30, baseline_hours=24,
            context={"top_models": [], "top_bots": [], "recent_traces": []},
        )
        assert "USAGE SPIKE ALERT" in msg
        assert "$10.00/hr" in msg
        assert "baseline" not in msg.split("\n")[3] if len(msg.split("\n")) > 3 else True


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------

class TestGatherContext:
    def test_aggregates_correctly(self):
        events = [
            _make_event(cost=0.05, model="gpt-4", bot_id="bot1"),
            _make_event(cost=0.10, model="gpt-4", bot_id="bot1"),
            _make_event(cost=0.03, model="claude-3", bot_id="bot2"),
        ]
        pricing = {}
        ptype_map = {}
        with patch("app.services.usage_costs._resolve_event_cost", side_effect=lambda d, p, pt: d.get("response_cost", 0)):
            ctx = _gather_context(events, pricing, ptype_map)

        assert len(ctx["top_models"]) == 2
        # gpt-4 should be first (higher cost)
        assert ctx["top_models"][0]["model"] == "gpt-4"
        assert ctx["top_models"][0]["calls"] == 2

        assert len(ctx["top_bots"]) == 2
        assert ctx["top_bots"][0]["bot_id"] == "bot1"

        assert len(ctx["recent_traces"]) == 3


# ---------------------------------------------------------------------------
# Spike detection
# ---------------------------------------------------------------------------

class TestCheckForSpike:
    @pytest.mark.asyncio
    async def test_spike_detected_relative(self):
        """When window rate is 3x baseline, should fire alert."""
        config = _make_config(relative_threshold=2.0)

        with patch("app.services.usage_spike._compute_cost_in_range") as mock_cost, \
             patch("app.services.usage_spike._dispatch_alert", new_callable=AsyncMock, return_value=(1, 1, [])) as mock_dispatch, \
             patch("app.services.usage_spike.async_session") as mock_session, \
             patch("app.services.usage_costs._load_pricing_map", new_callable=AsyncMock, return_value={}), \
             patch("app.services.usage_costs._get_provider_type_map", return_value={}), \
             patch("app.services.usage_spike.load_spike_config", new_callable=AsyncMock):

            # Window: high cost, baseline: low cost
            mock_cost.side_effect = [
                (3.0, [_make_event(cost=3.0)]),  # window
                (1.0, [_make_event(cost=1.0)]),  # baseline
            ]

            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            alert = await check_for_spike(config)
            assert alert is not None
            assert alert.trigger_reason == "relative"
            mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_spike_detected_absolute(self):
        """When window rate exceeds absolute threshold, should fire alert."""
        config = _make_config(relative_threshold=0, absolute_threshold_usd=5.0)

        with patch("app.services.usage_spike._compute_cost_in_range") as mock_cost, \
             patch("app.services.usage_spike._dispatch_alert", new_callable=AsyncMock, return_value=(1, 1, [])), \
             patch("app.services.usage_spike.async_session") as mock_session, \
             patch("app.services.usage_costs._load_pricing_map", new_callable=AsyncMock, return_value={}), \
             patch("app.services.usage_costs._get_provider_type_map", return_value={}), \
             patch("app.services.usage_spike.load_spike_config", new_callable=AsyncMock):

            # Window cost = 5.0 over 30min = 10.0/hr > 5.0 threshold
            mock_cost.side_effect = [
                (5.0, [_make_event(cost=5.0)]),  # window
                (1.0, []),                        # baseline
            ]

            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            alert = await check_for_spike(config)
            assert alert is not None
            assert "absolute" in alert.trigger_reason

    @pytest.mark.asyncio
    async def test_no_spike_below_threshold(self):
        """When window rate is below thresholds, should return None."""
        config = _make_config(relative_threshold=2.0, absolute_threshold_usd=0)

        with patch("app.services.usage_spike._compute_cost_in_range") as mock_cost:
            # Window and baseline roughly equal (ratio < 2.0)
            mock_cost.side_effect = [
                (0.5, []),  # window: 0.5 over 30min = 1.0/hr
                (24.0, []),  # baseline: 24.0 over 24hr = 1.0/hr — ratio = 1.0
            ]

            alert = await check_for_spike(config)
            assert alert is None

    @pytest.mark.asyncio
    async def test_no_baseline_skips_relative(self):
        """When baseline rate is 0, relative check is skipped; absolute still works."""
        config = _make_config(relative_threshold=2.0, absolute_threshold_usd=5.0)

        with patch("app.services.usage_spike._compute_cost_in_range") as mock_cost, \
             patch("app.services.usage_spike._dispatch_alert", new_callable=AsyncMock, return_value=(0, 0, [])), \
             patch("app.services.usage_spike.async_session") as mock_session, \
             patch("app.services.usage_costs._load_pricing_map", new_callable=AsyncMock, return_value={}), \
             patch("app.services.usage_costs._get_provider_type_map", return_value={}), \
             patch("app.services.usage_spike.load_spike_config", new_callable=AsyncMock):

            mock_cost.side_effect = [
                (5.0, [_make_event(cost=5.0)]),  # window: 5.0/0.5hr = 10.0/hr
                (0.0, []),                        # baseline: 0
            ]

            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            alert = await check_for_spike(config)
            assert alert is not None
            assert alert.trigger_reason == "absolute"

    @pytest.mark.asyncio
    async def test_no_baseline_no_absolute_returns_none(self):
        """When baseline is 0 and no absolute threshold, should return None."""
        config = _make_config(relative_threshold=2.0, absolute_threshold_usd=0)

        with patch("app.services.usage_spike._compute_cost_in_range") as mock_cost:
            mock_cost.side_effect = [
                (1.0, []),  # window
                (0.0, []),  # baseline: 0 → relative skipped
            ]

            alert = await check_for_spike(config)
            assert alert is None

    @pytest.mark.asyncio
    async def test_cooldown_active_skips(self):
        """When cooldown is active, should skip even if spike detected."""
        config = _make_config(
            relative_threshold=2.0,
            cooldown_minutes=60,
            last_alert_at=datetime.now(timezone.utc) - timedelta(minutes=30),  # 30min ago, cooldown 60min
        )

        with patch("app.services.usage_spike._compute_cost_in_range") as mock_cost:
            mock_cost.side_effect = [
                (10.0, []),  # window: huge spike
                (1.0, []),   # baseline: normal
            ]

            alert = await check_for_spike(config)
            assert alert is None

    @pytest.mark.asyncio
    async def test_cooldown_expired_proceeds(self):
        """When cooldown has expired, should proceed with check."""
        config = _make_config(
            relative_threshold=2.0,
            cooldown_minutes=60,
            last_alert_at=datetime.now(timezone.utc) - timedelta(minutes=120),  # 120min ago, cooldown 60min
        )

        with patch("app.services.usage_spike._compute_cost_in_range") as mock_cost, \
             patch("app.services.usage_spike._dispatch_alert", new_callable=AsyncMock, return_value=(0, 0, [])), \
             patch("app.services.usage_spike.async_session") as mock_session, \
             patch("app.services.usage_costs._load_pricing_map", new_callable=AsyncMock, return_value={}), \
             patch("app.services.usage_costs._get_provider_type_map", return_value={}), \
             patch("app.services.usage_spike.load_spike_config", new_callable=AsyncMock):

            mock_cost.side_effect = [
                (10.0, [_make_event(cost=10.0)]),  # window: huge spike
                (1.0, []),                          # baseline: normal
            ]

            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            alert = await check_for_spike(config)
            assert alert is not None

    @pytest.mark.asyncio
    async def test_force_bypasses_threshold_and_cooldown(self):
        """Force mode (test alert) bypasses all checks."""
        config = _make_config(
            relative_threshold=100.0,  # impossibly high
            cooldown_minutes=9999,
            last_alert_at=datetime.now(timezone.utc),  # just fired
        )

        with patch("app.services.usage_spike._compute_cost_in_range") as mock_cost, \
             patch("app.services.usage_spike._dispatch_alert", new_callable=AsyncMock, return_value=(1, 1, [])), \
             patch("app.services.usage_spike.async_session") as mock_session, \
             patch("app.services.usage_costs._load_pricing_map", new_callable=AsyncMock, return_value={}), \
             patch("app.services.usage_costs._get_provider_type_map", return_value={}), \
             patch("app.services.usage_spike.load_spike_config", new_callable=AsyncMock):

            mock_cost.side_effect = [
                (0.01, []),  # window: tiny
                (0.01, []),  # baseline: tiny
            ]

            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            alert = await check_for_spike(config, force=True)
            assert alert is not None
            assert alert.trigger_reason == "test"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

class TestDispatchAlert:
    @pytest.mark.asyncio
    async def test_notification_target_ids_take_precedence(self):
        target_id = uuid.uuid4()
        config = _make_config(
            target_ids=[str(target_id)],
            targets=[{"type": "channel", "channel_id": str(uuid.uuid4())}],
        )

        with patch(
            "app.services.usage_spike.send_notification",
            new_callable=AsyncMock,
            return_value={
                "details": [{"target": {"id": str(target_id), "label": "Ops", "kind": "channel"}, "success": True}],
                "succeeded": 1,
            },
        ) as mock_send:
            attempted, succeeded, details = await _dispatch_alert(config, "test message")

        assert attempted == 1
        assert succeeded == 1
        assert details[0]["target"]["label"] == "Ops"
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_channel_target_success(self):
        """Dispatching to a channel target should call post_message."""
        channel_id = str(uuid.uuid4())
        config = _make_config(targets=[{"type": "channel", "channel_id": channel_id}])

        mock_channel = MagicMock()
        mock_channel.integration = "slack"
        mock_channel.dispatch_config = {"channel": "C123"}

        with patch("app.services.usage_spike.async_session") as mock_session, \
             patch("app.services.channel_events.publish_typed") as mock_publish:

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=mock_channel)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            attempted, succeeded, details = await _dispatch_alert(config, "test message")

            assert attempted == 1
            assert succeeded == 1
            mock_publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_integration_target_success(self):
        """Dispatching to an integration target resolves dispatch_config,
        looks up the integration's renderer, and calls render() inline.
        Phase G replaced the legacy dispatcher path with a direct render
        call against the renderer registry.
        """
        from app.integrations.renderer import DeliveryReceipt
        config = _make_config(targets=[{
            "type": "integration",
            "integration_type": "bluebubbles",
            "client_id": "bb:iMessage;-;+1555",
        }])

        mock_meta = MagicMock()
        mock_meta.resolve_dispatch_config = MagicMock(return_value={
            "chat_guid": "iMessage;-;+1555",
            "server_url": "http://localhost",
            "password": "x",
        })

        mock_renderer = AsyncMock()
        mock_renderer.render = AsyncMock(return_value=DeliveryReceipt.ok())

        with patch("app.agent.hooks.get_integration_meta", return_value=mock_meta), \
             patch("app.integrations.renderer_registry.get", return_value=mock_renderer), \
             patch("app.domain.dispatch_target.parse_dispatch_target", return_value=MagicMock()):

            attempted, succeeded, details = await _dispatch_alert(config, "test message")

            assert attempted == 1
            assert succeeded == 1
            mock_renderer.render.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        """Channel target publishes (succeeds); integration target's
        renderer returns failed (the renderer path is the Phase G
        replacement for the legacy dispatcher path). Both attempts are
        recorded.
        """
        from app.integrations.renderer import DeliveryReceipt
        channel_id = str(uuid.uuid4())
        config = _make_config(targets=[
            {"type": "channel", "channel_id": channel_id},
            {"type": "integration", "integration_type": "slack", "client_id": "slack:C456"},
        ])

        mock_channel = MagicMock()
        mock_channel.integration = "slack"
        mock_channel.dispatch_config = {"channel": "C123"}

        mock_renderer = AsyncMock()
        mock_renderer.render = AsyncMock(return_value=DeliveryReceipt.failed(
            "simulated", retryable=False,
        ))

        mock_meta = MagicMock()
        mock_meta.resolve_dispatch_config = MagicMock(return_value={
            "channel_id": "C456",
            "token": "xoxb-test",
        })

        with patch("app.services.usage_spike.async_session") as mock_session, \
             patch("app.services.channel_events.publish_typed") as mock_publish, \
             patch("app.integrations.renderer_registry.get", return_value=mock_renderer), \
             patch("app.agent.hooks.get_integration_meta", return_value=mock_meta), \
             patch("app.domain.dispatch_target.parse_dispatch_target", return_value=MagicMock()):

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=mock_channel)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            attempted, succeeded, details = await _dispatch_alert(config, "test message")

            assert attempted == 2
            assert succeeded == 1
            assert len(details) == 2
            mock_publish.assert_called_once()
            mock_renderer.render.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_channel_id(self):
        """Target with missing channel_id should be recorded as error."""
        config = _make_config(targets=[{"type": "channel"}])

        attempted, succeeded, details = await _dispatch_alert(config, "test")
        assert attempted == 1
        assert succeeded == 0
        assert details[0]["error"] == "missing channel_id"

    @pytest.mark.asyncio
    async def test_unknown_target_type(self):
        """Target with unknown type should be recorded as error."""
        config = _make_config(targets=[{"type": "smoke_signal"}])

        attempted, succeeded, details = await _dispatch_alert(config, "test")
        assert attempted == 1
        assert succeeded == 0
        assert "unknown target type" in details[0]["error"]


# ---------------------------------------------------------------------------
# start_spike_refresh_task
# ---------------------------------------------------------------------------

import app.services.usage_spike as _spike_mod


class TestStartSpikeRefreshTask:
    def setup_method(self):
        self._original = _spike_mod._refresh_task

    def teardown_method(self):
        _spike_mod._refresh_task = self._original

    def test_when_no_existing_task_then_creates_one(self):
        _spike_mod._refresh_task = None

        with patch("app.services.usage_spike._refresh_loop", MagicMock()), \
             patch("app.services.usage_spike.asyncio.create_task", return_value=MagicMock()) as mock_ct:
            _spike_mod.start_spike_refresh_task()

        mock_ct.assert_called_once()
        assert _spike_mod._refresh_task is not None

    def test_when_task_still_running_then_no_new_task(self):
        running = MagicMock()
        running.done.return_value = False
        _spike_mod._refresh_task = running

        with patch("app.services.usage_spike.asyncio.create_task") as mock_ct:
            _spike_mod.start_spike_refresh_task()

        mock_ct.assert_not_called()
        assert _spike_mod._refresh_task is running

    def test_when_task_done_then_replaces_it(self):
        done_task = MagicMock()
        done_task.done.return_value = True
        new_task = MagicMock()
        _spike_mod._refresh_task = done_task

        with patch("app.services.usage_spike._refresh_loop"), \
             patch("app.services.usage_spike.asyncio.create_task", return_value=new_task) as mock_ct:
            _spike_mod.start_spike_refresh_task()

        mock_ct.assert_called_once()
        assert _spike_mod._refresh_task is new_task
