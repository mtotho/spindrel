"""Tests for app/services/plan_board.py — parse/serialize round-trip + step parsing."""
from __future__ import annotations

import pytest

from app.services.plan_board import (
    generate_plan_id,
    parse_plans_md,
    parse_step_status,
    serialize_plans_md,
    STEP_MARKERS,
    STEP_MARKERS_REV,
)


SAMPLE_PLANS_MD = """\
# Plans

## Deploy v2 API [draft]
- **id**: plan-a1b2c3
- **created**: 2026-03-31

### Steps
1. [ ] Update configuration files
2. [ ] Run database migrations
3. [ ] Deploy to staging
4. [ ] Run integration tests
5. [ ] Deploy to production

### Notes
Migrating auth endpoints to v2 format. Estimated 2-3 hours.

## Refactor caching layer [executing]
- **id**: plan-d4e5f6
- **created**: 2026-03-29
- **approved**: 2026-03-30

### Steps
1. [x] Audit current cache usage
2. [x] Design Redis integration
3. [~] Implement cache middleware
4. [ ] Write integration tests
5. [ ] Deploy and monitor

### Notes
Switching from in-memory to Redis for shared state.
"""


class TestGeneratePlanId:
    def test_format(self):
        pid = generate_plan_id()
        assert pid.startswith("plan-")
        assert len(pid) == 11  # plan- + 6 hex chars

    def test_unique(self):
        ids = {generate_plan_id() for _ in range(100)}
        assert len(ids) == 100


class TestParseStepStatus:
    @pytest.mark.parametrize("marker,expected", [
        ("[ ]", "pending"),
        ("[x]", "done"),
        ("[~]", "in_progress"),
        ("[-]", "skipped"),
        ("[!]", "failed"),
    ])
    def test_known_markers(self, marker, expected):
        assert parse_step_status(marker) == expected

    def test_unknown_marker(self):
        assert parse_step_status("[?]") == "pending"


class TestParsePlansMd:
    def test_parses_two_plans(self):
        plans = parse_plans_md(SAMPLE_PLANS_MD)
        assert len(plans) == 2

    def test_first_plan_fields(self):
        plans = parse_plans_md(SAMPLE_PLANS_MD)
        p = plans[0]
        assert p["title"] == "Deploy v2 API"
        assert p["status"] == "draft"
        assert p["meta"]["id"] == "plan-a1b2c3"
        assert p["meta"]["created"] == "2026-03-31"
        assert len(p["steps"]) == 5
        assert p["steps"][0]["status"] == "pending"
        assert p["steps"][0]["content"] == "Update configuration files"
        assert "Migrating" in p["notes"]

    def test_second_plan_mixed_steps(self):
        plans = parse_plans_md(SAMPLE_PLANS_MD)
        p = plans[1]
        assert p["title"] == "Refactor caching layer"
        assert p["status"] == "executing"
        assert p["meta"]["approved"] == "2026-03-30"
        assert p["steps"][0]["status"] == "done"
        assert p["steps"][1]["status"] == "done"
        assert p["steps"][2]["status"] == "in_progress"
        assert p["steps"][3]["status"] == "pending"

    def test_empty_content(self):
        assert parse_plans_md("") == []

    def test_no_steps_section(self):
        md = "# Plans\n\n## My Plan [draft]\n- **id**: plan-000001\n"
        plans = parse_plans_md(md)
        assert len(plans) == 1
        assert plans[0]["steps"] == []

    def test_no_notes_section(self):
        md = "# Plans\n\n## My Plan [draft]\n- **id**: plan-000001\n\n### Steps\n1. [ ] Do something\n"
        plans = parse_plans_md(md)
        assert plans[0]["notes"] == ""

    def test_no_status_defaults_to_draft(self):
        md = "# Plans\n\n## My Plan\n- **id**: plan-000001\n"
        plans = parse_plans_md(md)
        assert plans[0]["status"] == "draft"

    def test_brackets_in_title_not_treated_as_status(self):
        """Brackets containing non-status words should be kept in the title."""
        md = "# Plans\n\n## Deploy [v2] API\n- **id**: plan-000001\n"
        plans = parse_plans_md(md)
        assert plans[0]["title"] == "Deploy [v2] API"
        assert plans[0]["status"] == "draft"

    def test_brackets_with_valid_status(self):
        """Valid status in brackets should be parsed correctly."""
        for status in ("draft", "approved", "executing", "complete", "abandoned"):
            md = f"# Plans\n\n## My Plan [{status}]\n- **id**: plan-000001\n"
            plans = parse_plans_md(md)
            assert plans[0]["status"] == status
            assert plans[0]["title"] == "My Plan"

    def test_multiple_brackets_only_trailing_status(self):
        """Only trailing brackets with valid status should be parsed."""
        md = "# Plans\n\n## Deploy [v2] API [executing]\n- **id**: plan-000001\n"
        plans = parse_plans_md(md)
        assert plans[0]["title"] == "Deploy [v2] API"
        assert plans[0]["status"] == "executing"


class TestSerializePlansMd:
    def test_round_trip(self):
        """Parse then serialize should produce parseable output with same data."""
        plans = parse_plans_md(SAMPLE_PLANS_MD)
        serialized = serialize_plans_md(plans)
        reparsed = parse_plans_md(serialized)

        assert len(reparsed) == len(plans)
        for orig, rt in zip(plans, reparsed):
            assert orig["title"] == rt["title"]
            assert orig["status"] == rt["status"]
            assert orig["meta"] == rt["meta"]
            assert len(orig["steps"]) == len(rt["steps"])
            for os, rs in zip(orig["steps"], rt["steps"]):
                assert os["position"] == rs["position"]
                assert os["status"] == rs["status"]
                assert os["content"] == rs["content"]
            assert orig["notes"] == rt["notes"]

    def test_empty_list(self):
        result = serialize_plans_md([])
        assert result.startswith("# Plans")

    def test_single_plan(self):
        plans = [{
            "title": "Test Plan",
            "status": "draft",
            "meta": {"id": "plan-abc123", "created": "2026-01-01"},
            "steps": [
                {"position": 1, "status": "pending", "content": "Step one"},
                {"position": 2, "status": "done", "content": "Step two"},
            ],
            "notes": "Some notes.",
        }]
        result = serialize_plans_md(plans)
        assert "## Test Plan [draft]" in result
        assert "- **id**: plan-abc123" in result
        assert "1. [ ] Step one" in result
        assert "2. [x] Step two" in result
        assert "### Notes" in result
        assert "Some notes." in result


class TestFailedStepStatus:
    """Tests for the [!] failed step marker."""

    def test_parse_failed_step(self):
        md = "# Plans\n\n## My Plan [executing]\n- **id**: plan-000001\n\n### Steps\n1. [x] First step\n2. [!] Failed step\n3. [ ] Pending step\n"
        plans = parse_plans_md(md)
        assert len(plans) == 1
        assert plans[0]["steps"][1]["status"] == "failed"
        assert plans[0]["steps"][1]["content"] == "Failed step"

    def test_serialize_failed_step(self):
        plans = [{
            "title": "Test",
            "status": "executing",
            "meta": {"id": "plan-fail01"},
            "steps": [
                {"position": 1, "status": "done", "content": "Step one"},
                {"position": 2, "status": "failed", "content": "Step two"},
            ],
            "notes": "",
        }]
        result = serialize_plans_md(plans)
        assert "2. [!] Step two" in result

    def test_round_trip_with_failed(self):
        md = (
            "# Plans\n\n"
            "## Deploy [executing]\n"
            "- **id**: plan-rt0001\n\n"
            "### Steps\n"
            "1. [x] Prepare\n"
            "2. [!] Deploy staging\n"
            "3. [-] Skipped\n"
            "4. [ ] Deploy prod\n"
        )
        plans = parse_plans_md(md)
        serialized = serialize_plans_md(plans)
        reparsed = parse_plans_md(serialized)
        assert reparsed[0]["steps"][1]["status"] == "failed"
        assert reparsed[0]["steps"][2]["status"] == "skipped"


class TestStepMarkerConsistency:
    def test_rev_maps_match(self):
        """STEP_MARKERS and STEP_MARKERS_REV should be inverses."""
        for marker, status in STEP_MARKERS.items():
            assert STEP_MARKERS_REV[status] == marker
