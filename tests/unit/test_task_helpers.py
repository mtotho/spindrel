"""Unit tests for recurrence parsing in app.agent.tasks."""
from datetime import timedelta

from app.agent.tasks import _parse_recurrence


class TestParseRecurrence:
    def test_hours(self):
        assert _parse_recurrence("+1h") == timedelta(hours=1)

    def test_minutes(self):
        assert _parse_recurrence("+30m") == timedelta(minutes=30)

    def test_days(self):
        assert _parse_recurrence("+1d") == timedelta(days=1)

    def test_seconds(self):
        assert _parse_recurrence("+5s") == timedelta(seconds=5)

    def test_invalid(self):
        assert _parse_recurrence("invalid") is None

    def test_zero(self):
        assert _parse_recurrence("+0h") == timedelta(0)

    def test_whitespace(self):
        assert _parse_recurrence("  +1h  ") == timedelta(hours=1)
