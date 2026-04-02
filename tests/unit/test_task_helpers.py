"""Unit tests for recurrence parsing in app.agent.tasks."""
from datetime import timedelta

import pytest

from app.agent.tasks import _parse_recurrence, validate_recurrence


class TestParseRecurrence:
    def test_hours(self):
        assert _parse_recurrence("+1h") == timedelta(hours=1)

    def test_minutes(self):
        assert _parse_recurrence("+30m") == timedelta(minutes=30)

    def test_days(self):
        assert _parse_recurrence("+1d") == timedelta(days=1)

    def test_seconds(self):
        assert _parse_recurrence("+5s") == timedelta(seconds=5)

    def test_weeks(self):
        assert _parse_recurrence("+1w") == timedelta(weeks=1)

    def test_weeks_multiple(self):
        assert _parse_recurrence("+2w") == timedelta(weeks=2)

    def test_invalid(self):
        assert _parse_recurrence("invalid") is None

    def test_zero(self):
        assert _parse_recurrence("+0h") == timedelta(0)

    def test_whitespace(self):
        assert _parse_recurrence("  +1h  ") == timedelta(hours=1)


class TestValidateRecurrence:
    def test_valid(self):
        assert validate_recurrence("+1h") == "+1h"
        assert validate_recurrence("+1w") == "+1w"
        assert validate_recurrence("+30m") == "+30m"

    def test_none(self):
        assert validate_recurrence(None) is None

    def test_empty(self):
        assert validate_recurrence("") == ""

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid recurrence"):
            validate_recurrence("+1x")

    def test_missing_plus_raises(self):
        with pytest.raises(ValueError, match="Invalid recurrence"):
            validate_recurrence("1w")
