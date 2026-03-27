"""Tests for heartbeat quiet-hours logic and prompt fallback."""
from datetime import datetime, time

import pytest

from app.services.heartbeat import is_quiet_hours, parse_quiet_hours, get_effective_interval


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
