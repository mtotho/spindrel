"""Unit tests for timeline parsing and helper functions."""
import pytest

from integrations.mission_control.tools.mission_control import parse_timeline_md


class TestParseTimelineMd:
    def test_empty(self):
        assert parse_timeline_md("") == []

    def test_single_day(self):
        content = (
            "## 2026-03-28\n"
            "\n"
            "- 16:45 — Card mc-j0k1l2 moved to **Done**\n"
            "- 14:20 — Status changed\n"
        )
        events = parse_timeline_md(content)
        assert len(events) == 2
        assert events[0] == {
            "date": "2026-03-28",
            "time": "16:45",
            "event": "Card mc-j0k1l2 moved to **Done**",
        }
        assert events[1] == {
            "date": "2026-03-28",
            "time": "14:20",
            "event": "Status changed",
        }

    def test_multiple_days(self):
        content = (
            "## 2026-03-28\n"
            "\n"
            "- 16:45 — Event A\n"
            "\n"
            "## 2026-03-27\n"
            "\n"
            "- 10:00 — Event B\n"
        )
        events = parse_timeline_md(content)
        assert len(events) == 2
        assert events[0]["date"] == "2026-03-28"
        assert events[1]["date"] == "2026-03-27"

    def test_en_dash_separator(self):
        content = "## 2026-03-28\n\n- 09:00 – Event with en-dash\n"
        events = parse_timeline_md(content)
        assert len(events) == 1
        assert events[0]["event"] == "Event with en-dash"

    def test_hyphen_separator(self):
        content = "## 2026-03-28\n\n- 09:00 - Event with plain hyphen\n"
        events = parse_timeline_md(content)
        assert len(events) == 1
        assert events[0]["event"] == "Event with plain hyphen"

    def test_ignores_non_event_lines(self):
        content = (
            "## 2026-03-28\n"
            "\n"
            "Some random text\n"
            "- 16:45 — Valid event\n"
            "- not a valid entry\n"
        )
        events = parse_timeline_md(content)
        assert len(events) == 1
        assert events[0]["time"] == "16:45"

    def test_no_date_header(self):
        """Events without a preceding date header are ignored."""
        content = "- 16:45 — Orphaned event\n"
        events = parse_timeline_md(content)
        assert len(events) == 0

    def test_single_digit_hour(self):
        content = "## 2026-03-28\n\n- 9:00 — Early event\n"
        events = parse_timeline_md(content)
        assert len(events) == 1
        assert events[0]["time"] == "9:00"
