"""Unit tests for the games framework: directives, localizer registry,
and the pure-fn hint helpers."""
from __future__ import annotations

import pytest

from app.domain.errors import ValidationError
from app.services.games import (
    ACTOR_USER,
    DIRECTIVE_THEME_MAX_LEN,
    apply_directive,
    clear_directive,
    directive_block,
    localize_for_actor,
    register_game,
)
from app.services.games.hints import (
    bot_pacing_nudge,
    neighborhood_snapshot,
    notable_labels,
    recent_failures,
    unused_block_types,
)


# ── apply_directive / clear_directive / directive_block ─────────────────────


class TestDirective:
    def test_apply_directive_writes_state(self):
        state: dict = {}
        directive = apply_directive(state, theme="build a castle")
        assert directive["theme"] == "build a castle"
        assert directive["set_by"] == ACTOR_USER
        assert state["directive"] is directive

    def test_apply_directive_strips_whitespace(self):
        state: dict = {}
        apply_directive(state, theme="   castle   ")
        assert state["directive"]["theme"] == "castle"

    def test_apply_directive_rejects_empty(self):
        state: dict = {}
        with pytest.raises(ValidationError, match="theme is required"):
            apply_directive(state, theme="")

    def test_apply_directive_rejects_long_theme(self):
        state: dict = {}
        with pytest.raises(ValidationError, match="too long"):
            apply_directive(state, theme="x" * (DIRECTIVE_THEME_MAX_LEN + 1))

    def test_apply_directive_with_success_criteria(self):
        state: dict = {}
        apply_directive(state, theme="castle", success_criteria="ten blocks tall")
        assert state["directive"]["success_criteria"] == "ten blocks tall"

    def test_clear_directive_when_present(self):
        state: dict = {"directive": {"theme": "castle"}}
        assert clear_directive(state) is True
        assert "directive" not in state

    def test_clear_directive_when_absent(self):
        state: dict = {}
        assert clear_directive(state) is False

    def test_directive_block_renders_theme_only(self):
        state = {"directive": {"theme": "tower"}}
        text = directive_block(state)
        assert text == "Directive: tower"

    def test_directive_block_includes_success_criteria(self):
        state = {"directive": {"theme": "tower", "success_criteria": "ten tall"}}
        text = directive_block(state)
        assert "Directive: tower" in text
        assert "Success: ten tall" in text

    def test_directive_block_returns_none_when_absent(self):
        assert directive_block({}) is None
        assert directive_block({"directive": {}}) is None
        assert directive_block({"directive": "junk"}) is None


# ── Localizer registry ────────────────────────────────────────────────────


class TestLocalizerRegistry:
    def test_localize_returns_none_when_unregistered(self):
        assert localize_for_actor("core/game_nope", {}, "bot") is None

    def test_localize_returns_callback_output(self):
        async def _stub_dispatch(*args, **kwargs):  # pragma: no cover - registry only
            raise NotImplementedError

        register_game(
            "core/game_test_localize",
            dispatcher=_stub_dispatch,
            summarizer=lambda s: "summary",
            localize=lambda s, actor: f"hint for {actor}",
        )
        assert localize_for_actor("core/game_test_localize", {}, "rolland") == "hint for rolland"

    def test_localize_swallows_callback_exceptions(self):
        async def _stub_dispatch(*args, **kwargs):  # pragma: no cover
            raise NotImplementedError

        def _bad(state, actor):
            raise RuntimeError("boom")

        register_game(
            "core/game_test_localize_err",
            dispatcher=_stub_dispatch,
            summarizer=lambda s: "summary",
            localize=_bad,
        )
        assert localize_for_actor("core/game_test_localize_err", {}, "rolland") is None


# ── neighborhood_snapshot ─────────────────────────────────────────────────


class TestNeighborhoodSnapshot:
    def test_marks_anchor_with_X(self):
        text = neighborhood_snapshot({}, (5, 5, 0), radius=1)
        assert "X" in text

    def test_renders_block_initials(self):
        blocks = {
            "5,5,0": {"type": "stone", "bot": "a"},
            "6,5,0": {"type": "wood", "bot": "b"},
        }
        text = neighborhood_snapshot(blocks, (5, 5, 0), radius=1)
        # 'X' marks anchor; 'w' from wood appears
        assert "X" in text
        assert "w" in text

    def test_skips_negative_z_layers(self):
        text = neighborhood_snapshot({}, (5, 5, 0), radius=2)
        assert "z=-" not in text


# ── bot_pacing_nudge ──────────────────────────────────────────────────────


class TestPacingNudge:
    def test_returns_none_with_one_player(self):
        state = {"players": {"alice": {"block_count": 1}}}
        assert bot_pacing_nudge(state, "alice") is None

    def test_zero_blocks_when_others_have_blocks(self):
        state = {
            "players": {
                "alice": {"block_count": 0},
                "bob": {"block_count": 5},
            }
        }
        nudge = bot_pacing_nudge(state, "alice")
        assert nudge is not None
        assert "haven't placed" in nudge

    def test_balanced_returns_none(self):
        state = {
            "players": {
                "alice": {"block_count": 5},
                "bob": {"block_count": 4},
            }
        }
        assert bot_pacing_nudge(state, "alice") is None

    def test_far_ahead_warns(self):
        state = {
            "players": {
                "alice": {"block_count": 30},
                "bob": {"block_count": 5},
            }
        }
        nudge = bot_pacing_nudge(state, "alice")
        assert nudge is not None
        assert "lot of" in nudge

    def test_far_behind_warns(self):
        state = {
            "players": {
                "alice": {"block_count": 1},
                "bob": {"block_count": 10},
                "carla": {"block_count": 12},
            }
        }
        nudge = bot_pacing_nudge(state, "alice")
        assert nudge is not None
        assert "behind" in nudge


# ── unused_block_types ────────────────────────────────────────────────────


class TestUnusedBlockTypes:
    def test_lists_types_never_placed(self):
        state = {
            "blocks": {
                "0,0,0": {"type": "stone", "bot": "alice"},
                "1,0,0": {"type": "wood", "bot": "alice"},
            }
        }
        result = unused_block_types(state, "alice", ["stone", "wood", "glass", "brick"])
        assert "stone" not in result
        assert "wood" not in result
        assert "glass" in result
        assert "brick" in result

    def test_other_actors_dont_count(self):
        state = {
            "blocks": {
                "0,0,0": {"type": "stone", "bot": "bob"},
            }
        }
        result = unused_block_types(state, "alice", ["stone", "wood"])
        assert result == ["stone", "wood"]


# ── recent_failures ──────────────────────────────────────────────────────


class TestRecentFailures:
    def test_returns_only_actor_failures(self):
        state = {
            "turn_log": [
                {"actor": "alice", "summary": "failed: out of bounds", "args": {}},
                {"actor": "bob", "summary": "failed: x", "args": {}},
                {"actor": "alice", "summary": "placed wood", "args": {}},
            ]
        }
        result = recent_failures(state, "alice", limit=5)
        assert len(result) == 1
        assert "out of bounds" in result[0]


# ── notable_labels ────────────────────────────────────────────────────────


class TestNotableLabels:
    def test_returns_only_labeled_blocks(self):
        blocks = {
            "0,0,0": {"type": "stone", "bot": "a"},
            "1,0,0": {"type": "wood", "bot": "a", "label": "doorframe", "ts": "2026-04-26T10:00:00Z"},
        }
        result = notable_labels(blocks)
        assert len(result) == 1
        assert result[0]["label"] == "doorframe"

    def test_caps_total(self):
        blocks = {
            f"{i},0,0": {"type": "stone", "bot": "a", "label": f"l{i}", "ts": f"2026-04-26T10:{i:02d}:00Z"}
            for i in range(10)
        }
        result = notable_labels(blocks, cap=3)
        assert len(result) == 3
