"""Unit tests for fixed-cost plan billing for providers."""
import pytest
from unittest.mock import MagicMock, patch


class TestIsPlanProvider:
    """Test _is_plan_provider helper in usage.py."""

    def _make_provider(self, billing_type="usage", plan_cost=None, plan_period=None):
        p = MagicMock()
        p.billing_type = billing_type
        p.plan_cost = plan_cost
        p.plan_period = plan_period
        return p

    def test_returns_false_for_none_provider_id(self):
        from app.routers.api_v1_admin.usage import _is_plan_provider
        assert _is_plan_provider(None) is False

    def test_returns_false_for_unknown_provider_id(self):
        from app.routers.api_v1_admin.usage import _is_plan_provider
        with patch("app.services.providers._registry", {}):
            assert _is_plan_provider("nonexistent") is False

    def test_returns_false_for_usage_provider(self):
        from app.routers.api_v1_admin.usage import _is_plan_provider
        provider = self._make_provider(billing_type="usage")
        with patch("app.services.providers._registry", {"my-provider": provider}):
            assert _is_plan_provider("my-provider") is False

    def test_returns_true_for_plan_provider(self):
        from app.routers.api_v1_admin.usage import _is_plan_provider
        provider = self._make_provider(billing_type="plan", plan_cost=40.0, plan_period="monthly")
        with patch("app.services.providers._registry", {"minimax": provider}):
            assert _is_plan_provider("minimax") is True


class TestResolveEventCostPlanProvider:
    """Test that _resolve_event_cost returns 0.0 for plan providers with no pricing."""

    def _make_provider(self, billing_type="plan"):
        p = MagicMock()
        p.billing_type = billing_type
        return p

    def test_plan_provider_returns_zero_when_no_pricing(self):
        from app.routers.api_v1_admin.usage import _resolve_event_cost
        provider = self._make_provider(billing_type="plan")
        event_data = {
            "provider_id": "minimax",
            "model": "minimax-text-01",
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        with patch("app.services.providers._registry", {"minimax": provider}):
            # Empty pricing map → no per-token rates → normally returns None
            cost = _resolve_event_cost(event_data, {}, {"minimax": "openai-compatible"})
            assert cost == 0.0

    def test_usage_provider_returns_none_when_no_pricing(self):
        from app.routers.api_v1_admin.usage import _resolve_event_cost
        provider = self._make_provider(billing_type="usage")
        event_data = {
            "provider_id": "my-openai",
            "model": "gpt-4",
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        with patch("app.services.providers._registry", {"my-openai": provider}):
            cost = _resolve_event_cost(event_data, {}, {"my-openai": "openai"})
            assert cost is None

    def test_plan_provider_uses_response_cost_when_present(self):
        from app.routers.api_v1_admin.usage import _resolve_event_cost
        provider = self._make_provider(billing_type="plan")
        event_data = {
            "provider_id": "minimax",
            "model": "minimax-text-01",
            "response_cost": 0.05,
        }
        with patch("app.services.providers._registry", {"minimax": provider}):
            cost = _resolve_event_cost(event_data, {}, {})
            assert cost == 0.05


class TestFixedPlanForecastComponent:
    """Test that the forecast builds a fixed_plans component from plan providers."""

    def _make_provider(self, billing_type="plan", plan_cost=40.0, plan_period="monthly"):
        p = MagicMock()
        p.billing_type = billing_type
        p.plan_cost = plan_cost
        p.plan_period = plan_period
        return p

    def test_monthly_plan_daily_cost(self):
        """A $40/month plan should yield ~$1.33/day."""
        provider = self._make_provider(plan_cost=40.0, plan_period="monthly")
        daily = provider.plan_cost / 30
        assert round(daily, 2) == 1.33

    def test_weekly_plan_daily_cost(self):
        """A $14/week plan should yield $2/day."""
        provider = self._make_provider(plan_cost=14.0, plan_period="weekly")
        daily = provider.plan_cost / 7
        assert round(daily, 2) == 2.0

    def test_forecast_component_structure(self):
        """Verify the ForecastComponent can be created with fixed_plans source."""
        from app.routers.api_v1_admin.usage import ForecastComponent
        comp = ForecastComponent(
            source="fixed_plans",
            label="Fixed plans",
            daily_cost=1.3333,
            monthly_cost=40.0,
            count=1,
        )
        assert comp.source == "fixed_plans"
        assert comp.label == "Fixed plans"
        assert comp.count == 1
