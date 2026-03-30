"""Tests for heartbeat quiet-hours logic, prompt fallback, and repetition detection."""
import uuid
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.heartbeat import (
    is_quiet_hours,
    parse_quiet_hours,
    get_effective_interval,
    next_aligned_time,
    _detect_repetition,
)


class TestParseQuietHours:
    def test_valid_range(self):
        assert parse_quiet_hours("23:00-07:00") == (time(23, 0), time(7, 0))

    def test_same_day_range(self):
        assert parse_quiet_hours("01:00-05:00") == (time(1, 0), time(5, 0))

    def test_with_spaces(self):
        assert parse_quiet_hours(" 22:30 - 06:30 ") == (time(22, 30), time(6, 30))

    def test_empty_string(self):
        assert parse_quiet_hours("") is None

    def test_whitespace_only(self):
        assert parse_quiet_hours("   ") is None

    def test_invalid_format(self):
        assert parse_quiet_hours("not-a-time") is None

    def test_missing_separator(self):
        assert parse_quiet_hours("2300") is None

    def test_invalid_hour(self):
        assert parse_quiet_hours("25:00-07:00") is None


class TestIsQuietHours:
    def test_midnight_wrap_inside_before_midnight(self):
        quiet = (time(23, 0), time(7, 0))
        now = datetime(2026, 3, 22, 23, 30)
        assert is_quiet_hours(now, quiet) is True

    def test_midnight_wrap_inside_after_midnight(self):
        quiet = (time(23, 0), time(7, 0))
        now = datetime(2026, 3, 23, 3, 0)
        assert is_quiet_hours(now, quiet) is True

    def test_midnight_wrap_outside(self):
        quiet = (time(23, 0), time(7, 0))
        now = datetime(2026, 3, 22, 12, 0)
        assert is_quiet_hours(now, quiet) is False

    def test_midnight_wrap_at_boundary_start(self):
        quiet = (time(23, 0), time(7, 0))
        now = datetime(2026, 3, 22, 23, 0)
        assert is_quiet_hours(now, quiet) is True

    def test_midnight_wrap_at_boundary_end(self):
        quiet = (time(23, 0), time(7, 0))
        now = datetime(2026, 3, 23, 7, 0)
        assert is_quiet_hours(now, quiet) is False

    def test_same_day_range_inside(self):
        quiet = (time(1, 0), time(5, 0))
        now = datetime(2026, 3, 22, 3, 0)
        assert is_quiet_hours(now, quiet) is True

    def test_same_day_range_outside(self):
        quiet = (time(1, 0), time(5, 0))
        now = datetime(2026, 3, 22, 6, 0)
        assert is_quiet_hours(now, quiet) is False

    def test_same_day_at_start(self):
        quiet = (time(1, 0), time(5, 0))
        now = datetime(2026, 3, 22, 1, 0)
        assert is_quiet_hours(now, quiet) is True

    def test_same_day_at_end(self):
        quiet = (time(1, 0), time(5, 0))
        now = datetime(2026, 3, 22, 5, 0)
        assert is_quiet_hours(now, quiet) is False


class TestGetEffectiveInterval:
    def test_no_quiet_hours_configured(self, monkeypatch):
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_HOURS", "")
        assert get_effective_interval(5) == 5

    def test_quiet_hours_active_returns_max(self, monkeypatch):
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_HOURS", "23:00-07:00")
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_INTERVAL_MINUTES", 60)
        monkeypatch.setattr("app.services.heartbeat.settings.TIMEZONE", "UTC")
        # Mock datetime.now to return a time inside quiet hours
        from unittest.mock import patch
        import zoneinfo
        fake_now = datetime(2026, 3, 22, 2, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        with patch("app.services.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_effective_interval(5)
        assert result == 60  # quiet interval is larger

    def test_quiet_hours_active_keeps_larger_hb_interval(self, monkeypatch):
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_HOURS", "23:00-07:00")
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_INTERVAL_MINUTES", 60)
        monkeypatch.setattr("app.services.heartbeat.settings.TIMEZONE", "UTC")
        from unittest.mock import patch
        import zoneinfo
        fake_now = datetime(2026, 3, 22, 2, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        with patch("app.services.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_effective_interval(120)
        assert result == 120  # hb interval is already larger

    def test_quiet_hours_disabled_returns_zero(self, monkeypatch):
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_HOURS", "23:00-07:00")
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_INTERVAL_MINUTES", 0)
        monkeypatch.setattr("app.services.heartbeat.settings.TIMEZONE", "UTC")
        from unittest.mock import patch
        import zoneinfo
        fake_now = datetime(2026, 3, 22, 2, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        with patch("app.services.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_effective_interval(5)
        assert result == 0

    def test_outside_quiet_hours_returns_hb_interval(self, monkeypatch):
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_HOURS", "23:00-07:00")
        monkeypatch.setattr("app.services.heartbeat.settings.HEARTBEAT_QUIET_INTERVAL_MINUTES", 60)
        monkeypatch.setattr("app.services.heartbeat.settings.TIMEZONE", "UTC")
        from unittest.mock import patch
        import zoneinfo
        fake_now = datetime(2026, 3, 22, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        with patch("app.services.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_effective_interval(5)
        assert result == 5


class TestNextAlignedTime:
    """next_aligned_time should snap to clock boundaries."""

    def test_30min_mid_slot(self):
        now = datetime(2026, 3, 28, 14, 47, 12, tzinfo=timezone.utc)
        result = next_aligned_time(now, 30)
        assert result == datetime(2026, 3, 28, 15, 0, 0, tzinfo=timezone.utc)

    def test_30min_exactly_on_boundary(self):
        now = datetime(2026, 3, 28, 15, 0, 0, tzinfo=timezone.utc)
        result = next_aligned_time(now, 30)
        assert result == datetime(2026, 3, 28, 15, 30, 0, tzinfo=timezone.utc)

    def test_30min_just_after_boundary(self):
        now = datetime(2026, 3, 28, 15, 0, 1, tzinfo=timezone.utc)
        result = next_aligned_time(now, 30)
        assert result == datetime(2026, 3, 28, 15, 30, 0, tzinfo=timezone.utc)

    def test_60min_interval(self):
        now = datetime(2026, 3, 28, 14, 15, 0, tzinfo=timezone.utc)
        result = next_aligned_time(now, 60)
        assert result == datetime(2026, 3, 28, 15, 0, 0, tzinfo=timezone.utc)

    def test_15min_interval(self):
        now = datetime(2026, 3, 28, 14, 47, 0, tzinfo=timezone.utc)
        result = next_aligned_time(now, 15)
        assert result == datetime(2026, 3, 28, 15, 0, 0, tzinfo=timezone.utc)

    def test_15min_early_in_slot(self):
        now = datetime(2026, 3, 28, 14, 31, 0, tzinfo=timezone.utc)
        result = next_aligned_time(now, 15)
        assert result == datetime(2026, 3, 28, 14, 45, 0, tzinfo=timezone.utc)

    def test_wraps_past_midnight(self):
        now = datetime(2026, 3, 28, 23, 45, 0, tzinfo=timezone.utc)
        result = next_aligned_time(now, 30)
        assert result == datetime(2026, 3, 29, 0, 0, 0, tzinfo=timezone.utc)

    def test_zero_interval_returns_safety_fallback(self):
        now = datetime(2026, 3, 28, 14, 0, 0, tzinfo=timezone.utc)
        result = next_aligned_time(now, 0)
        # Should not crash; returns now + 30 min
        assert result > now


class TestHeartbeatDefaultPrompt:
    """Verify the prompt fallback logic: hb.prompt or settings.HEARTBEAT_DEFAULT_PROMPT."""

    def test_empty_prompt_falls_back_to_default(self, monkeypatch):
        """When hb.prompt is empty/None, the `or` expression returns the default."""
        monkeypatch.setattr(
            "app.services.heartbeat.settings.HEARTBEAT_DEFAULT_PROMPT",
            "Check in on the user",
        )
        from app.services.heartbeat import settings
        # Simulate the inline_prompt expression from fire_heartbeat
        assert ("" or settings.HEARTBEAT_DEFAULT_PROMPT) == "Check in on the user"
        assert (None or settings.HEARTBEAT_DEFAULT_PROMPT) == "Check in on the user"

    def test_explicit_prompt_takes_precedence(self, monkeypatch):
        """When hb.prompt is set, it takes precedence over the default."""
        monkeypatch.setattr(
            "app.services.heartbeat.settings.HEARTBEAT_DEFAULT_PROMPT",
            "Check in on the user",
        )
        from app.services.heartbeat import settings
        assert ("My custom prompt" or settings.HEARTBEAT_DEFAULT_PROMPT) == "My custom prompt"

    def test_both_empty_returns_empty(self, monkeypatch):
        """When both hb.prompt and default are empty, result is empty string."""
        monkeypatch.setattr(
            "app.services.heartbeat.settings.HEARTBEAT_DEFAULT_PROMPT",
            "",
        )
        from app.services.heartbeat import settings
        assert ("" or settings.HEARTBEAT_DEFAULT_PROMPT) == ""

    def test_config_default_is_empty_string(self):
        """HEARTBEAT_DEFAULT_PROMPT should default to empty string."""
        from app.config import Settings
        assert Settings.model_fields["HEARTBEAT_DEFAULT_PROMPT"].default == ""


def _make_run(result=None, error=None, correlation_id=None, minutes_ago=0):
    """Create a fake HeartbeatRun-like object for testing."""
    return SimpleNamespace(
        result=result,
        error=error,
        correlation_id=correlation_id or uuid.uuid4(),
        completed_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


class TestDetectRepetition:
    """Tests for _detect_repetition() helper."""

    def test_no_runs_returns_false(self):
        assert _detect_repetition([], {}) is False

    def test_two_similar_runs_not_enough(self):
        runs = [
            _make_run(result="Hello world, nothing new."),
            _make_run(result="Hello world, nothing new."),
        ]
        assert _detect_repetition(runs, {}) is False

    def test_three_identical_results_detected(self):
        runs = [
            _make_run(result="Understood. I'll be judicious."),
            _make_run(result="Understood. I'll be judicious."),
            _make_run(result="Understood. I'll be judicious."),
        ]
        assert _detect_repetition(runs, {}) is True

    def test_three_similar_results_above_threshold(self):
        runs = [
            _make_run(result="The weather today is sunny and clear in the region."),
            _make_run(result="The weather today is sunny and clear in the area."),
            _make_run(result="The weather today is sunny and clear in the zone."),
        ]
        assert _detect_repetition(runs, {}, threshold=0.7) is True

    def test_three_different_results_not_detected(self):
        runs = [
            _make_run(result="Today I checked the weather: sunny."),
            _make_run(result="New deployment detected: v2.3.1 is live."),
            _make_run(result="No updates to report."),
        ]
        assert _detect_repetition(runs, {}) is False

    def test_identical_tool_calls_detected(self):
        cid1, cid2, cid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        runs = [
            _make_run(result="a", correlation_id=cid1),
            _make_run(result="b", correlation_id=cid2),
            _make_run(result="c", correlation_id=cid3),
        ]
        tool_calls = {
            cid1: ["web_search", "post_heartbeat_to_channel"],
            cid2: ["web_search", "post_heartbeat_to_channel"],
            cid3: ["web_search", "post_heartbeat_to_channel"],
        }
        assert _detect_repetition(runs, tool_calls) is True

    def test_different_tool_calls_not_detected(self):
        cid1, cid2, cid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        runs = [
            _make_run(result="a", correlation_id=cid1),
            _make_run(result="b", correlation_id=cid2),
            _make_run(result="c", correlation_id=cid3),
        ]
        tool_calls = {
            cid1: ["web_search", "post_heartbeat_to_channel"],
            cid2: ["get_weather"],
            cid3: ["web_search", "post_heartbeat_to_channel"],
        }
        assert _detect_repetition(runs, tool_calls) is False

    def test_empty_tool_calls_not_flagged(self):
        """Runs with no tool calls should not trigger action repetition."""
        cid1, cid2, cid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        runs = [
            _make_run(result="a", correlation_id=cid1),
            _make_run(result="b", correlation_id=cid2),
            _make_run(result="c", correlation_id=cid3),
        ]
        # All empty — identical but should NOT flag (the `and sequences[0]` guard)
        tool_calls = {cid1: [], cid2: [], cid3: []}
        assert _detect_repetition(runs, tool_calls) is False

    def test_old_repetitive_runs_dont_trigger_when_recent_differ(self):
        """Only the most recent 3 runs matter — old repetitive runs are ignored."""
        runs = [
            _make_run(result="Fresh new content today!", minutes_ago=0),
            _make_run(result="Another unique update.", minutes_ago=30),
            _make_run(result="Something completely different.", minutes_ago=60),
            _make_run(result="Understood. I'll be judicious.", minutes_ago=90),
            _make_run(result="Understood. I'll be judicious.", minutes_ago=120),
        ]
        # Most recent 3 are all different — should NOT trigger
        assert _detect_repetition(runs, {}) is False

    def test_mixed_results_with_none(self):
        """Runs with None results should be skipped in text comparison."""
        runs = [
            _make_run(result="Same output."),
            _make_run(result=None),
            _make_run(result="Same output."),
        ]
        assert _detect_repetition(runs, {}) is False

    def test_config_defaults(self):
        """Verify config defaults for repetition detection settings."""
        from app.config import Settings
        assert Settings.model_fields["HEARTBEAT_REPETITION_DETECTION"].default is True
        assert Settings.model_fields["HEARTBEAT_REPETITION_THRESHOLD"].default == 0.8
        assert "repetitive" in Settings.model_fields["HEARTBEAT_REPETITION_WARNING"].default.lower()
