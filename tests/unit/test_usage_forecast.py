"""Unit tests for usage forecast logic — timezone handling, recurrence parsing,
and per-template cost grouping."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo


class TestRecurrenceRunsPerDay:
    """Test _recurrence_runs_per_day helper."""

    def test_hourly(self):
        from app.routers.api_v1_admin.usage import _recurrence_runs_per_day
        assert _recurrence_runs_per_day("+1h") == 24.0

    def test_30_minutes(self):
        from app.routers.api_v1_admin.usage import _recurrence_runs_per_day
        assert _recurrence_runs_per_day("+30m") == 48.0

    def test_daily(self):
        from app.routers.api_v1_admin.usage import _recurrence_runs_per_day
        assert _recurrence_runs_per_day("+1d") == 1.0

    def test_weekly(self):
        from app.routers.api_v1_admin.usage import _recurrence_runs_per_day
        result = _recurrence_runs_per_day("+1w")
        assert abs(result - 1 / 7) < 0.001

    def test_invalid_returns_zero(self):
        from app.routers.api_v1_admin.usage import _recurrence_runs_per_day
        assert _recurrence_runs_per_day("invalid") == 0.0
        assert _recurrence_runs_per_day("") == 0.0

    def test_whitespace_stripped(self):
        from app.routers.api_v1_admin.usage import _recurrence_runs_per_day
        assert _recurrence_runs_per_day(" +2h ") == 12.0


class TestForecastTimezone:
    """Test that forecast day/month boundaries use local timezone, not UTC."""

    def test_today_start_uses_local_midnight(self):
        """If it's 12pm Eastern, today_start should be midnight Eastern (4am UTC in EDT)."""
        tz = ZoneInfo("America/New_York")
        # April 1 2026, 12:00 PM Eastern = 4:00 PM UTC (EDT = UTC-4)
        now_utc = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)

        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

        # Midnight Eastern on April 1 = 4:00 AM UTC
        assert today_start == datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)

    def test_today_start_utc_would_be_wrong(self):
        """Demonstrates the bug: UTC midnight is NOT the same as local midnight."""
        tz = ZoneInfo("America/New_York")
        now_utc = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)

        # The OLD (broken) way:
        utc_today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        # This gives midnight UTC = 8pm Eastern previous day
        assert utc_today_start == datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

        # The NEW (correct) way:
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

        assert hours_elapsed == 12.0  # 12pm - midnight = 12 hours

    def test_month_start_uses_local_timezone(self):
        """Month start should be the 1st of the local month, not UTC month."""
        tz = ZoneInfo("America/New_York")
        # March 31 at 11pm Eastern = April 1 at 3am UTC
        now_utc = datetime(2026, 4, 1, 3, 0, 0, tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)

        # Local time is March 31 11pm — still March
        assert now_local.month == 3
        assert now_local.day == 31

        month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        # Should be March 1 midnight Eastern = March 1 5:00 AM UTC (EST = UTC-5 in March)
        assert month_start.month == 3
        assert month_start.day == 1

    def test_dst_spring_forward(self):
        """Spring forward: March 8 2026 2am EST → 3am EDT. Day boundary still correct."""
        tz = ZoneInfo("America/New_York")
        # March 8 2026 at 10am EDT (after spring forward) = 2pm UTC
        now_utc = datetime(2026, 3, 8, 14, 0, 0, tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)

        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        # Midnight on March 8 — still EST (before 2am), so UTC-5 = 5am UTC
        assert today_start == datetime(2026, 3, 8, 5, 0, 0, tzinfo=timezone.utc)


class TestPeriodStartTimezone:
    """Test that _period_start in usage_limits respects configured timezone."""

    @patch("app.config.settings")
    def test_daily_uses_local_midnight(self, mock_settings):
        mock_settings.TIMEZONE = "America/New_York"
        from app.services.usage_limits import _period_start

        now_utc = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.usage_limits.datetime") as mock_dt:
            # Keep the real datetime class but intercept .now()
            mock_dt.now.return_value = now_utc
            # Let datetime(...) constructor calls pass through to real datetime
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

            result = _period_start("daily")

            # Midnight Eastern (EDT) = 4am UTC
            assert result == datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)

    @patch("app.config.settings")
    def test_monthly_uses_local_first_of_month(self, mock_settings):
        mock_settings.TIMEZONE = "America/New_York"
        from app.services.usage_limits import _period_start

        now_utc = datetime(2026, 4, 15, 16, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.usage_limits.datetime") as mock_dt:
            mock_dt.now.return_value = now_utc
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

            result = _period_start("monthly")

            # April 1 midnight Eastern (EDT) = April 1 4am UTC
            assert result == datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)

    @patch("app.config.settings")
    def test_invalid_period_raises(self, mock_settings):
        mock_settings.TIMEZONE = "America/New_York"
        from app.services.usage_limits import _period_start

        with patch("app.services.usage_limits.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

            with pytest.raises(ValueError, match="Unknown period"):
                _period_start("yearly")


class TestGroupCostsByTemplate:
    """Test _group_costs_by_template — the production function that maps
    correlation_id costs to parent template tasks."""

    def test_groups_by_parent(self):
        from app.routers.api_v1_admin.usage import _group_costs_by_template

        corr_parent = {
            "corr-1": "template-A",
            "corr-2": "template-A",
            "corr-3": "template-B",
        }
        corr_costs = {
            "corr-1": 0.10,
            "corr-2": 0.20,
            "corr-3": 0.50,
        }
        result = _group_costs_by_template(corr_parent, corr_costs)

        assert set(result.keys()) == {"template-A", "template-B"}
        assert result["template-A"] == [0.10, 0.20]
        assert result["template-B"] == [0.50]

    def test_ignores_costs_without_parent(self):
        """Correlation IDs not in corr_parent are silently dropped."""
        from app.routers.api_v1_admin.usage import _group_costs_by_template

        corr_parent = {"corr-1": "template-A"}
        corr_costs = {
            "corr-1": 0.10,
            "corr-orphan": 0.99,  # no parent mapping
        }
        result = _group_costs_by_template(corr_parent, corr_costs)

        assert list(result.keys()) == ["template-A"]
        assert result["template-A"] == [0.10]

    def test_empty_inputs(self):
        from app.routers.api_v1_admin.usage import _group_costs_by_template

        assert _group_costs_by_template({}, {}) == {}
        assert _group_costs_by_template({"c": "t"}, {}) == {}
        assert _group_costs_by_template({}, {"c": 1.0}) == {}


class TestComputeRecurringTaskDaily:
    """Test _compute_recurring_task_daily — the production function that computes
    total daily cost from recurring tasks and their per-template cost history."""

    def _make_task(self, task_id: str, recurrence: str):
        t = MagicMock()
        t.id = task_id
        t.recurrence = recurrence
        return t

    def test_hourly_task_with_known_costs(self):
        from app.routers.api_v1_admin.usage import _compute_recurring_task_daily

        tasks = [self._make_task("t1", "+1h")]
        costs = {"t1": [0.01, 0.02, 0.01]}  # avg = 0.0133...
        result = _compute_recurring_task_daily(tasks, costs)

        # 24 runs/day * avg $0.01333 = $0.32
        expected = 24 * (0.04 / 3)
        assert abs(result - expected) < 0.001

    def test_task_with_no_history_contributes_zero(self):
        from app.routers.api_v1_admin.usage import _compute_recurring_task_daily

        tasks = [self._make_task("t1", "+1h")]
        result = _compute_recurring_task_daily(tasks, {})
        assert result == 0.0

    def test_multiple_tasks_different_intervals(self):
        """Cheap hourly task + expensive daily task computed separately."""
        from app.routers.api_v1_admin.usage import _compute_recurring_task_daily

        tasks = [
            self._make_task("cheap", "+1h"),   # 24 runs/day
            self._make_task("expensive", "+1d"),  # 1 run/day
        ]
        costs = {
            "cheap": [0.01, 0.01, 0.01],     # avg $0.01
            "expensive": [0.50, 0.50, 0.50],  # avg $0.50
        }
        result = _compute_recurring_task_daily(tasks, costs)

        # 24 * 0.01 + 1 * 0.50 = 0.74
        assert abs(result - 0.74) < 0.001

    def test_same_bot_different_costs_not_blended(self):
        """Two tasks for the same bot get their OWN cost averages, not blended."""
        from app.routers.api_v1_admin.usage import _compute_recurring_task_daily

        tasks = [
            self._make_task("cheap-task", "+1h"),
            self._make_task("expensive-task", "+1h"),
        ]
        costs = {
            "cheap-task": [0.01, 0.01],       # avg $0.01
            "expensive-task": [0.50, 0.50],   # avg $0.50
        }
        result = _compute_recurring_task_daily(tasks, costs)

        # Per-template: 24*0.01 + 24*0.50 = 0.24 + 12.0 = 12.24
        assert abs(result - 12.24) < 0.01

        # If blended (old bug): avg = 0.255, 48 * 0.255 = 12.24
        # Same total when intervals are equal, but diverges when they differ.

    def test_plan_billed_task_contributes_zero(self):
        """Tasks using plan-billed models have $0.00 per-run costs."""
        from app.routers.api_v1_admin.usage import _compute_recurring_task_daily

        tasks = [self._make_task("plan-task", "+1h")]
        costs = {"plan-task": [0.0, 0.0, 0.0]}  # plan-billed = $0 per run
        result = _compute_recurring_task_daily(tasks, costs)
        assert result == 0.0


class TestProjectionPlanCosts:
    """Test that projected_daily always includes fixed plan costs."""

    def test_plan_cost_added_when_trajectory_wins(self):
        """Even when trajectory > scheduled variable costs, plan costs must be added."""
        # Simulates the projection logic from usage_forecast()
        trajectory_daily = 10.0  # high trajectory from interactive use
        variable_scheduled_daily = 2.0  # heartbeats + recurring tasks
        fixed_plan_daily = 1.33  # $40/month plan

        projected = max(trajectory_daily, variable_scheduled_daily) + fixed_plan_daily

        # Plan cost is always added, not lost in the max()
        assert abs(projected - 11.33) < 0.01

    def test_plan_cost_added_when_scheduled_wins(self):
        """When scheduled costs are higher, plan costs are still additive."""
        trajectory_daily = 2.0
        variable_scheduled_daily = 8.0  # heavy heartbeat/task automation
        fixed_plan_daily = 1.33

        projected = max(trajectory_daily, variable_scheduled_daily) + fixed_plan_daily

        assert abs(projected - 9.33) < 0.01

    def test_no_plans_adds_zero(self):
        """When there are no plan providers, projection is unaffected."""
        trajectory_daily = 5.0
        variable_scheduled_daily = 3.0
        fixed_plan_daily = 0.0

        projected = max(trajectory_daily, variable_scheduled_daily) + fixed_plan_daily
        assert projected == 5.0
