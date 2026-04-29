"""Unit tests for usage forecast logic — timezone handling, recurrence parsing,
and model-based cost estimation."""
import ast
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


class TestRecurrenceRunsPerDay:
    """Test _recurrence_runs_per_day helper."""

    def test_hourly(self):
        from app.services.usage_forecast import _recurrence_runs_per_day
        assert _recurrence_runs_per_day("+1h") == 24.0

    def test_30_minutes(self):
        from app.services.usage_forecast import _recurrence_runs_per_day
        assert _recurrence_runs_per_day("+30m") == 48.0

    def test_daily(self):
        from app.services.usage_forecast import _recurrence_runs_per_day
        assert _recurrence_runs_per_day("+1d") == 1.0

    def test_weekly(self):
        from app.services.usage_forecast import _recurrence_runs_per_day
        result = _recurrence_runs_per_day("+1w")
        assert abs(result - 1 / 7) < 0.001

    def test_invalid_returns_zero(self):
        from app.services.usage_forecast import _recurrence_runs_per_day
        assert _recurrence_runs_per_day("invalid") == 0.0
        assert _recurrence_runs_per_day("") == 0.0

    def test_whitespace_stripped(self):
        from app.services.usage_forecast import _recurrence_runs_per_day
        assert _recurrence_runs_per_day(" +2h ") == 12.0


class TestForecastTimezone:
    """Test that forecast day/month boundaries use local timezone, not UTC."""

    def test_today_start_uses_local_midnight(self):
        """If it's 12pm Eastern, today_start should be midnight Eastern (4am UTC in EDT)."""
        tz = ZoneInfo("America/New_York")
        now_utc = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)

        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        assert today_start == datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)

    def test_today_start_utc_would_be_wrong(self):
        """Demonstrates the bug: UTC midnight is NOT the same as local midnight."""
        tz = ZoneInfo("America/New_York")
        now_utc = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)

        utc_today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        now_local = now_utc.astimezone(tz)
        local_today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

        # 4 hours difference in EDT
        diff = local_today_start - utc_today_start
        assert diff == timedelta(hours=4)

    def test_hours_elapsed_reflects_local_time(self):
        """hours_elapsed should reflect hours since local midnight."""
        tz = ZoneInfo("America/New_York")
        now_utc = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)

        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        hours_elapsed = (now_utc - today_start).total_seconds() / 3600
        assert hours_elapsed == 12.0

    def test_month_start_uses_local_timezone(self):
        """Month start should be the 1st of the local month, not UTC month."""
        tz = ZoneInfo("America/New_York")
        # March 31 at 11pm Eastern = April 1 at 3am UTC
        now_utc = datetime(2026, 4, 1, 3, 0, 0, tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)

        assert now_local.month == 3
        month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        assert month_start.month == 3
        assert month_start.day == 1

    def test_dst_spring_forward(self):
        """Spring forward: March 8 2026 2am EST → 3am EDT. Day boundary still correct."""
        tz = ZoneInfo("America/New_York")
        now_utc = datetime(2026, 3, 8, 14, 0, 0, tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)

        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        assert today_start == datetime(2026, 3, 8, 5, 0, 0, tzinfo=timezone.utc)


class TestForecastWindow:
    """Test the forecast service's timezone window helper."""

    def test_build_forecast_window_uses_local_boundaries(self, monkeypatch):
        from app.services import usage_forecast

        monkeypatch.setattr(usage_forecast.settings, "TIMEZONE", "America/New_York")
        now_utc = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)

        window = usage_forecast._build_forecast_window(now_utc)

        assert window.today_start == datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)
        assert window.month_start == datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)
        assert window.seven_days_ago == datetime(2026, 3, 25, 16, 0, 0, tzinfo=timezone.utc)
        assert window.hours_elapsed == 12.0
        assert window.days_elapsed == 0.5


class TestPeriodStartTimezone:
    """Test that _period_start in usage_limits respects configured timezone."""

    def test_daily_uses_local_midnight(self, monkeypatch):
        from app.config import settings
        from app.services.usage_limits import _period_start

        monkeypatch.setattr(settings, "TIMEZONE", "America/New_York")
        now_utc = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.usage_limits.datetime") as mock_dt:
            mock_dt.now.return_value = now_utc
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

            result = _period_start("daily")
            assert result == datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)

    def test_monthly_uses_local_first_of_month(self, monkeypatch):
        from app.config import settings
        from app.services.usage_limits import _period_start

        monkeypatch.setattr(settings, "TIMEZONE", "America/New_York")
        now_utc = datetime(2026, 4, 15, 16, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.usage_limits.datetime") as mock_dt:
            mock_dt.now.return_value = now_utc
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

            result = _period_start("monthly")
            assert result == datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)

    def test_invalid_period_raises(self, monkeypatch):
        from app.config import settings
        from app.services.usage_limits import _period_start

        monkeypatch.setattr(settings, "TIMEZONE", "America/New_York")
        with patch("app.services.usage_limits.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

            with pytest.raises(ValueError, match="Unknown period"):
                _period_start("yearly")


class TestProjectionPlanCosts:
    """Test that projected_daily always includes fixed plan costs."""

    def test_plan_cost_added_when_trajectory_wins(self):
        """Even when trajectory > scheduled variable costs, plan costs must be added."""
        trajectory_daily = 10.0
        variable_scheduled_daily = 2.0
        fixed_plan_daily = 1.33

        projected = max(trajectory_daily, variable_scheduled_daily) + fixed_plan_daily
        assert abs(projected - 11.33) < 0.01

    def test_plan_cost_added_when_scheduled_wins(self):
        variable_scheduled_daily = 8.0
        trajectory_daily = 2.0
        fixed_plan_daily = 1.33

        projected = max(trajectory_daily, variable_scheduled_daily) + fixed_plan_daily
        assert abs(projected - 9.33) < 0.01

    def test_no_plans_adds_zero(self):
        projected = max(5.0, 3.0) + 0.0
        assert projected == 5.0


class TestModelBasedTaskForecast:
    """Test the model-based recurring task cost estimation logic."""

    def test_plan_billed_model_contributes_zero(self):
        """Tasks using plan-billed models should not add to the forecast."""
        from app.services.usage_forecast import _recurrence_runs_per_day
        from app.services.usage_costs import _is_plan_billed

        runs_per_day = _recurrence_runs_per_day("+1h")
        assert runs_per_day == 24.0

        # Plan-billed model → skip
        with patch("app.services.providers._registry", {}), \
             patch("app.services.providers._plan_billed_models", {"minimax/MiniMax-M2.7"}):
            assert _is_plan_billed(None, "minimax/MiniMax-M2.7") is True
            # In the forecast, this means task_daily += 0 (skipped)

    def test_model_avg_cost_computation(self):
        """Average cost per model is total_cost / call_count."""
        from app.services.usage_forecast import _compute_model_average_costs

        events = [
            SimpleNamespace(data={"model": "gemini/gemini-2.0-flash", "response_cost": cost})
            for cost in [0.001, 0.002, 0.001]
        ]
        events.extend(
            SimpleNamespace(data={"model": "gpt-4o", "response_cost": cost})
            for cost in [0.05, 0.03]
        )

        model_avg_cost = _compute_model_average_costs(events, pricing={}, ptype_map={})

        assert abs(model_avg_cost["gemini/gemini-2.0-flash"] - 0.001333) < 0.001
        assert abs(model_avg_cost["gpt-4o"] - 0.04) < 0.001

    def test_task_daily_from_model_avg(self):
        """Daily cost = runs_per_day * avg_cost_per_call for the bot's model."""
        from app.services.usage_forecast import _recurrence_runs_per_day

        model_avg_cost = {"gemini/gemini-2.0-flash": 0.001}

        # Task runs every hour on gemini-flash
        runs_per_day = _recurrence_runs_per_day("+1h")
        avg_cost = model_avg_cost.get("gemini/gemini-2.0-flash", 0.0)
        daily = runs_per_day * avg_cost

        # 24 runs * $0.001 = $0.024/day
        assert abs(daily - 0.024) < 0.001

    def test_unknown_model_contributes_zero(self):
        """Tasks with models not seen in recent usage contribute $0."""
        model_avg_cost = {"gpt-4o": 0.04}
        avg_cost = model_avg_cost.get("some-unknown-model", 0.0)
        assert avg_cost == 0.0


class TestForecastProjectionHelpers:
    """Test component projection helpers."""

    def test_projected_totals_add_fixed_plans_after_max_variable_or_trajectory(self):
        from app.schemas.usage import ForecastComponent
        from app.services.usage_forecast import _compute_projected_totals

        components = [
            ForecastComponent(source="recurring_tasks", label="Recurring", daily_cost=2.0, monthly_cost=60.0),
            ForecastComponent(source="trajectory", label="Current pace", daily_cost=10.0, monthly_cost=300.0),
            ForecastComponent(source="fixed_plans", label="Fixed plans", daily_cost=1.33, monthly_cost=40.0),
        ]

        projected_daily, projected_monthly = _compute_projected_totals(components)

        assert projected_daily == 11.33
        assert projected_monthly == 340.0


class TestUsageForecastArchitecture:
    """Architecture guard for usage forecast read-model depth."""

    def test_build_usage_forecast_remains_coordinator_sized(self):
        repo_root = Path(__file__).resolve().parents[2]
        source = (repo_root / "app" / "services" / "usage_forecast.py").read_text()
        tree = ast.parse(source)

        node = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "build_usage_forecast"
        )

        assert node.end_lineno is not None
        assert node.end_lineno - node.lineno + 1 <= 60
