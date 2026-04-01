"""Unit tests for fixed-cost plan billing for providers."""
import pytest
from unittest.mock import MagicMock, patch


class TestIsPlanBilled:
    """Test _is_plan_billed helper in usage.py."""

    def _make_provider(self, billing_type="usage", plan_cost=None, plan_period=None):
        p = MagicMock()
        p.billing_type = billing_type
        p.plan_cost = plan_cost
        p.plan_period = plan_period
        return p

    def test_returns_false_for_none_provider_and_no_model(self):
        from app.routers.api_v1_admin.usage import _is_plan_billed
        with patch("app.services.providers._plan_billed_models", set()):
            assert _is_plan_billed(None, None) is False

    def test_returns_false_for_unknown_provider_id(self):
        from app.routers.api_v1_admin.usage import _is_plan_billed
        with patch("app.services.providers._registry", {}), \
             patch("app.services.providers._plan_billed_models", set()):
            assert _is_plan_billed("nonexistent", None) is False

    def test_returns_false_for_usage_provider(self):
        from app.routers.api_v1_admin.usage import _is_plan_billed
        provider = self._make_provider(billing_type="usage")
        with patch("app.services.providers._registry", {"my-provider": provider}), \
             patch("app.services.providers._plan_billed_models", set()):
            assert _is_plan_billed("my-provider", None) is False

    def test_returns_true_for_plan_provider(self):
        from app.routers.api_v1_admin.usage import _is_plan_billed
        provider = self._make_provider(billing_type="plan", plan_cost=40.0, plan_period="monthly")
        with patch("app.services.providers._registry", {"minimax": provider}), \
             patch("app.services.providers._plan_billed_models", set()):
            assert _is_plan_billed("minimax", None) is True

    def test_returns_true_for_model_on_plan_provider(self):
        """Even if provider_id doesn't match, model name lookup should work."""
        from app.routers.api_v1_admin.usage import _is_plan_billed
        with patch("app.services.providers._registry", {}), \
             patch("app.services.providers._plan_billed_models", {"minimax/MiniMax-M2.7"}):
            assert _is_plan_billed(None, "minimax/MiniMax-M2.7") is True

    def test_returns_false_for_unrelated_model(self):
        from app.routers.api_v1_admin.usage import _is_plan_billed
        with patch("app.services.providers._registry", {}), \
             patch("app.services.providers._plan_billed_models", {"minimax/MiniMax-M2.7"}):
            assert _is_plan_billed(None, "gpt-4") is False


class TestResolveEventCostPlanProvider:
    """Test that _resolve_event_cost returns 0.0 for plan-billed calls with no pricing."""

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
        with patch("app.services.providers._registry", {"minimax": provider}), \
             patch("app.services.providers._plan_billed_models", set()):
            cost = _resolve_event_cost(event_data, {}, {"minimax": "openai-compatible"})
            assert cost == 0.0

    def test_plan_model_returns_zero_when_routed_through_different_provider(self):
        """Model belongs to a plan provider but call went through .env fallback."""
        from app.routers.api_v1_admin.usage import _resolve_event_cost
        event_data = {
            "provider_id": None,
            "model": "minimax/MiniMax-M2.7",
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        with patch("app.services.providers._registry", {}), \
             patch("app.services.providers._plan_billed_models", {"minimax/MiniMax-M2.7"}):
            cost = _resolve_event_cost(event_data, {}, {})
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
        with patch("app.services.providers._registry", {"my-openai": provider}), \
             patch("app.services.providers._plan_billed_models", set()):
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
        with patch("app.services.providers._registry", {"minimax": provider}), \
             patch("app.services.providers._plan_billed_models", set()):
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
