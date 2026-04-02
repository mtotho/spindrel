"""Tests for timeline event humanization."""
import pytest

from integrations.mission_control.helpers import humanize_event as _humanize_event


class TestHumanizeEvent:
    """Test all event format transformations + fallback."""

    def test_card_moved_to_in_progress(self):
        raw = 'Card mc-9ab1fb moved to **In Progress** (was: Backlog) — "Fix bug"'
        assert _humanize_event(raw) == "**Fix bug** was started"

    def test_card_moved_to_done(self):
        raw = 'Card mc-abc123 moved to **Done** (was: In Progress) — "Deploy v2"'
        assert _humanize_event(raw) == "**Deploy v2** was completed"

    def test_card_moved_to_review(self):
        raw = 'Card mc-def456 moved to **Review** (was: In Progress) — "Add tests"'
        assert _humanize_event(raw) == "**Add tests** moved to review"

    def test_card_moved_to_backlog(self):
        raw = 'Card mc-ghi789 moved to **Backlog** (was: In Progress) — "Cleanup"'
        assert _humanize_event(raw) == "**Cleanup** moved back to backlog"

    def test_card_moved_to_unknown_column(self):
        raw = 'Card mc-jkl012 moved to **Blocked** (was: In Progress) — "Refactor"'
        assert _humanize_event(raw) == "**Refactor** moved to Blocked"

    def test_new_card_created(self):
        raw = 'New card created: mc-abc "Task title" in **Backlog**'
        assert _humanize_event(raw) == "New task: **Task title** added to Backlog"

    def test_new_card_created_in_progress(self):
        raw = 'New card created: mc-xyz "Urgent fix" in **In Progress**'
        assert _humanize_event(raw) == "New task: **Urgent fix** added to In Progress"

    def test_plan_approved(self):
        raw = "Plan approved: **Migrate database** (plan-abc123)"
        assert _humanize_event(raw) == "Plan **Migrate database** was approved"

    def test_plan_rejected(self):
        raw = "Plan rejected: **Risky change** (plan-def456)"
        assert _humanize_event(raw) == "Plan **Risky change** was rejected"

    def test_fallback_returns_raw(self):
        raw = "Something unrecognized happened"
        assert _humanize_event(raw) == raw

    def test_empty_string_fallback(self):
        assert _humanize_event("") == ""

    def test_card_with_special_chars_in_title(self):
        raw = 'Card mc-001 moved to **Done** (was: Review) — "Fix ampersand & stuff"'
        assert _humanize_event(raw) == "**Fix ampersand & stuff** was completed"

    def test_case_insensitive_column_match(self):
        # Column verb lookup is case-insensitive
        raw = 'Card mc-x moved to **in progress** (was: Backlog) — "Test"'
        assert _humanize_event(raw) == "**Test** was started"
