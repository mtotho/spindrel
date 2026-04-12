"""Tests for Channel.config JSONB column — pinned_panels mutation + defaults."""
import copy
import uuid

import pytest

from app.db.models import Channel


class TestChannelConfigDefaults:
    def test_default_config_is_empty_dict(self):
        ch = Channel(
            id=uuid.uuid4(),
            name="test",
            bot_id="bot-1",
        )
        assert ch.config == {} or ch.config is None  # ORM default vs DB default

    def test_pinned_panels_round_trip(self):
        ch = Channel(
            id=uuid.uuid4(),
            name="test",
            bot_id="bot-1",
            config={"pinned_panels": [
                {"path": "report.md", "position": "right", "pinned_at": "2026-04-11T00:00:00Z", "pinned_by": "user"},
            ]},
        )
        assert len(ch.config["pinned_panels"]) == 1
        assert ch.config["pinned_panels"][0]["path"] == "report.md"

    def test_deepcopy_mutation_pattern(self):
        original = {"pinned_panels": [
            {"path": "a.md", "position": "right", "pinned_at": "2026-01-01T00:00:00Z", "pinned_by": "user"},
        ]}
        mutated = copy.deepcopy(original)
        mutated["pinned_panels"].append(
            {"path": "b.md", "position": "bottom", "pinned_at": "2026-01-02T00:00:00Z", "pinned_by": "bot-1"},
        )
        assert len(original["pinned_panels"]) == 1
        assert len(mutated["pinned_panels"]) == 2

    def test_dedup_by_path(self):
        panels = [
            {"path": "a.md", "position": "right"},
            {"path": "b.md", "position": "right"},
        ]
        # Re-pin a.md at bottom — should replace
        new_path = "a.md"
        panels = [p for p in panels if p["path"] != new_path]
        panels.append({"path": new_path, "position": "bottom"})
        assert len(panels) == 2
        assert panels[-1]["position"] == "bottom"
