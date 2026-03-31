"""Unit tests for app.services.task_board — parser/serializer."""
import pytest

from app.services.task_board import (
    default_columns,
    generate_card_id,
    parse_card,
    parse_tasks_md,
    serialize_card,
    serialize_tasks_md,
)


class TestGenerateCardId:
    def test_format(self):
        cid = generate_card_id()
        assert cid.startswith("mc-")
        assert len(cid) == 9  # "mc-" + 6 hex chars

    def test_uniqueness(self):
        ids = {generate_card_id() for _ in range(100)}
        assert len(ids) == 100


class TestParseCard:
    def test_basic(self):
        raw = (
            "Fix the login bug\n"
            "- **id**: mc-abc123\n"
            "- **priority**: high\n"
            "- **created**: 2026-01-15\n"
            "\nThe login page crashes on submit."
        )
        card = parse_card(raw)
        assert card["title"] == "Fix the login bug"
        assert card["meta"]["id"] == "mc-abc123"
        assert card["meta"]["priority"] == "high"
        assert card["meta"]["created"] == "2026-01-15"
        assert card["description"] == "The login page crashes on submit."

    def test_no_meta(self):
        raw = "Simple task\n\nJust a description."
        card = parse_card(raw)
        assert card["title"] == "Simple task"
        assert card["meta"] == {}
        assert card["description"] == "Just a description."

    def test_no_description(self):
        raw = "Title only\n- **id**: mc-000001\n- **priority**: low"
        card = parse_card(raw)
        assert card["title"] == "Title only"
        assert card["meta"]["id"] == "mc-000001"
        assert card["description"] == ""

    def test_empty(self):
        card = parse_card("")
        assert card == {"title": "", "meta": {}, "description": ""}


class TestSerializeCard:
    def test_roundtrip(self):
        card = {
            "title": "My Task",
            "meta": {"id": "mc-aaa111", "priority": "medium", "created": "2026-03-30"},
            "description": "A test task.",
        }
        md = serialize_card(card)
        assert "### My Task" in md
        assert "- **id**: mc-aaa111" in md
        assert "- **priority**: medium" in md
        assert "A test task." in md

    def test_no_description(self):
        card = {"title": "No Desc", "meta": {"id": "mc-b"}, "description": ""}
        md = serialize_card(card)
        assert "### No Desc" in md
        assert md.count("\n\n") == 0  # no blank line for empty description


class TestParseTasksMd:
    SAMPLE = (
        "# Tasks\n\n"
        "## Backlog\n\n"
        "### Fix bug\n"
        "- **id**: mc-111111\n"
        "- **priority**: high\n"
        "\nCrashes on load.\n\n"
        "### Add feature\n"
        "- **id**: mc-222222\n"
        "- **priority**: low\n"
        "\n"
        "## In Progress\n\n"
        "### Refactor auth\n"
        "- **id**: mc-333333\n"
        "- **priority**: medium\n"
        "\n"
        "## Done\n\n"
    )

    def test_parse_columns(self):
        columns = parse_tasks_md(self.SAMPLE)
        assert len(columns) == 3
        assert columns[0]["name"] == "Backlog"
        assert columns[1]["name"] == "In Progress"
        assert columns[2]["name"] == "Done"

    def test_parse_cards(self):
        columns = parse_tasks_md(self.SAMPLE)
        backlog = columns[0]
        assert len(backlog["cards"]) == 2
        assert backlog["cards"][0]["title"] == "Fix bug"
        assert backlog["cards"][0]["meta"]["priority"] == "high"
        assert backlog["cards"][1]["title"] == "Add feature"

    def test_in_progress_card(self):
        columns = parse_tasks_md(self.SAMPLE)
        ip = columns[1]
        assert len(ip["cards"]) == 1
        assert ip["cards"][0]["title"] == "Refactor auth"

    def test_empty_column(self):
        columns = parse_tasks_md(self.SAMPLE)
        done = columns[2]
        assert len(done["cards"]) == 0

    def test_empty_content(self):
        columns = parse_tasks_md("")
        assert columns == []


class TestSerializeTasksMd:
    def test_roundtrip(self):
        original = (
            "# Tasks\n\n"
            "## Backlog\n\n"
            "### Fix bug\n"
            "- **id**: mc-111111\n"
            "- **priority**: high\n"
            "\nCrashes on load.\n\n"
            "## Done\n\n"
        )
        columns = parse_tasks_md(original)
        serialized = serialize_tasks_md(columns)
        # Re-parse to check roundtrip
        columns2 = parse_tasks_md(serialized)
        assert len(columns2) == len(columns)
        assert columns2[0]["name"] == "Backlog"
        assert len(columns2[0]["cards"]) == 1
        assert columns2[0]["cards"][0]["title"] == "Fix bug"
        assert columns2[0]["cards"][0]["meta"]["priority"] == "high"
        assert "Crashes on load." in columns2[0]["cards"][0]["description"]

    def test_default_columns(self):
        cols = default_columns()
        md = serialize_tasks_md(cols)
        assert "## Backlog" in md
        assert "## In Progress" in md
        assert "## Review" in md
        assert "## Done" in md


class TestDefaultColumns:
    def test_four_columns(self):
        cols = default_columns()
        assert len(cols) == 4
        names = [c["name"] for c in cols]
        assert names == ["Backlog", "In Progress", "Review", "Done"]

    def test_all_empty(self):
        cols = default_columns()
        for col in cols:
            assert col["cards"] == []
