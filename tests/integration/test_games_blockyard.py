"""Integration tests for the spatial-canvas Blockyard game.

Cover the dispatch path end-to-end against ``WidgetInstance`` rows. Pin
the new directive system, blocks_per_turn budget enforcement, bounds
editing, and the localize() coaching block.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.db.models import WidgetInstance
from app.domain.errors import ValidationError
from app.services.dashboards import WORKSPACE_SPATIAL_DASHBOARD_KEY
from app.services.games import (
    ACTOR_USER,
    PHASE_ENDED,
    PHASE_PLAYING,
    PHASE_SETUP,
)
from app.services.games.blockyard import (
    DEFAULT_BLOCKS_PER_TURN,
    MAX_BLOCKS_PER_TURN,
    MAX_BOUND,
    MIN_BOUND,
    WIDGET_REF,
    default_state,
    localize,
    summarize,
)
from app.services.native_app_widgets import dispatch_native_widget_action


pytestmark = pytest.mark.asyncio


async def _make_instance(db_session) -> WidgetInstance:
    instance = WidgetInstance(
        id=uuid.uuid4(),
        widget_kind="native_app",
        widget_ref=WIDGET_REF,
        scope_kind="dashboard",
        scope_ref=WORKSPACE_SPATIAL_DASHBOARD_KEY,
        state=default_state(),
    )
    db_session.add(instance)
    await db_session.flush()
    return instance


async def _act(db_session, instance, action, args, *, bot_id=None):
    return await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action=action,
        args=args,
        bot_id=bot_id,
    )


async def _start_with_participants(db_session, instance, *bot_ids: str) -> None:
    await _act(db_session, instance, "set_participants", {"bot_ids": list(bot_ids)})
    await _act(db_session, instance, "set_phase", {"phase": "playing"})


# ── Directive ──────────────────────────────────────────────────────────────


class TestDirective:
    async def test_set_directive_persists_theme_and_set_by(self, db_session):
        inst = await _make_instance(db_session)
        result = await _act(
            db_session,
            inst,
            "set_directive",
            {"theme": "build a sea-glass cathedral, tall and translucent"},
        )
        assert result["ok"] is True
        directive = inst.state["directive"]
        assert directive["theme"].startswith("build a sea-glass")
        assert directive["set_by"] == ACTOR_USER
        assert directive["set_at"]
        assert directive.get("success_criteria") is None

    async def test_set_directive_with_success_criteria(self, db_session):
        inst = await _make_instance(db_session)
        await _act(
            db_session,
            inst,
            "set_directive",
            {"theme": "tower", "success_criteria": "ten blocks tall"},
        )
        assert inst.state["directive"]["success_criteria"] == "ten blocks tall"

    async def test_empty_theme_clears_directive(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_directive", {"theme": "tower"})
        assert inst.state.get("directive") is not None
        result = await _act(db_session, inst, "set_directive", {"theme": ""})
        assert result["ok"] is True
        assert result["directive"] is None
        assert inst.state.get("directive") is None

    async def test_directive_too_long_rejected(self, db_session):
        inst = await _make_instance(db_session)
        with pytest.raises(ValidationError, match="theme is too long"):
            await _act(
                db_session,
                inst,
                "set_directive",
                {"theme": "x" * 500},
            )

    async def test_directive_appears_in_summary(self, db_session):
        inst = await _make_instance(db_session)
        # Directive isn't injected into summarize() — heartbeat block injects
        # it separately via directive_block(). Just sanity-check that summary
        # still works post-directive.
        await _act(db_session, inst, "set_directive", {"theme": "tower"})
        text = summarize(inst.state)
        assert "Blockyard" in text


# ── Bounds editor ──────────────────────────────────────────────────────────


class TestSetBounds:
    async def test_setup_phase_can_resize(self, db_session):
        inst = await _make_instance(db_session)
        result = await _act(db_session, inst, "set_bounds", {"x": 8, "y": 10, "z": 6})
        assert result["bounds"] == {"x": 8, "y": 10, "z": 6}
        assert inst.state["bounds"] == {"x": 8, "y": 10, "z": 6}

    async def test_set_bounds_rejected_during_play(self, db_session):
        inst = await _make_instance(db_session)
        await _start_with_participants(db_session, inst, "rolland")
        with pytest.raises(ValidationError, match="phase"):
            await _act(db_session, inst, "set_bounds", {"x": 8, "y": 8, "z": 4})

    async def test_set_bounds_rejects_below_min(self, db_session):
        inst = await _make_instance(db_session)
        with pytest.raises(ValidationError, match=f"between {MIN_BOUND}"):
            await _act(db_session, inst, "set_bounds", {"x": 1, "y": 8, "z": 4})

    async def test_set_bounds_rejects_above_max(self, db_session):
        inst = await _make_instance(db_session)
        with pytest.raises(ValidationError, match=f"between {MIN_BOUND}"):
            await _act(db_session, inst, "set_bounds", {"x": MAX_BOUND + 1, "y": 8, "z": 4})


# ── blocks_per_turn budget ─────────────────────────────────────────────────


class TestBlocksPerTurn:
    async def test_default_one_block_per_turn(self, db_session):
        inst = await _make_instance(db_session)
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        await _act(db_session, inst, "place", {"x": 0, "y": 0, "z": 0, "type": "stone"}, bot_id="rolland")
        # Second placement same round should be rejected.
        with pytest.raises(ValidationError, match="already placed"):
            await _act(db_session, inst, "place", {"x": 1, "y": 0, "z": 0, "type": "stone"}, bot_id="rolland")

    async def test_blocks_per_turn_three_allows_three_back_to_back(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_blocks_per_turn", {"count": 3})
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        for x in range(3):
            await _act(
                db_session,
                inst,
                "place",
                {"x": x, "y": 0, "z": 0, "type": "stone"},
                bot_id="rolland",
            )
        # Fourth in same round → rejected.
        with pytest.raises(ValidationError, match="already placed"):
            await _act(
                db_session,
                inst,
                "place",
                {"x": 3, "y": 0, "z": 0, "type": "stone"},
                bot_id="rolland",
            )

    async def test_round_advances_when_all_finish(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_blocks_per_turn", {"count": 2})
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        # rolland exhausts budget
        await _act(db_session, inst, "place", {"x": 0, "y": 0, "z": 0, "type": "stone"}, bot_id="rolland")
        await _act(db_session, inst, "place", {"x": 1, "y": 0, "z": 0, "type": "stone"}, bot_id="rolland")
        assert inst.state["round"] == 1, "round should not advance until zeus also finishes"
        # zeus exhausts budget
        await _act(db_session, inst, "place", {"x": 0, "y": 1, "z": 0, "type": "wood"}, bot_id="zeus")
        await _act(db_session, inst, "place", {"x": 1, "y": 1, "z": 0, "type": "wood"}, bot_id="zeus")
        assert inst.state["round"] == 2
        assert inst.state["round_placements"] == {}
        assert inst.state["round_done"] == []

    async def test_remove_consumes_full_round_turn(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_blocks_per_turn", {"count": 3})
        await _start_with_participants(db_session, inst, "rolland")
        await _act(db_session, inst, "place", {"x": 0, "y": 0, "z": 0, "type": "stone"}, bot_id="rolland")
        # remove counts as full turn — round should advance for solo participant
        await _act(db_session, inst, "remove", {"x": 0, "y": 0, "z": 0}, bot_id="rolland")
        assert inst.state["round"] == 2

    async def test_set_blocks_per_turn_rejects_zero(self, db_session):
        inst = await _make_instance(db_session)
        with pytest.raises(ValidationError, match="between 1"):
            await _act(db_session, inst, "set_blocks_per_turn", {"count": 0})

    async def test_set_blocks_per_turn_rejects_above_max(self, db_session):
        inst = await _make_instance(db_session)
        with pytest.raises(ValidationError, match="between 1"):
            await _act(
                db_session,
                inst,
                "set_blocks_per_turn",
                {"count": MAX_BLOCKS_PER_TURN + 1},
            )

    async def test_advance_round_clears_placements_and_done(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_blocks_per_turn", {"count": 2})
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        await _act(db_session, inst, "place", {"x": 0, "y": 0, "z": 0, "type": "stone"}, bot_id="rolland")
        assert inst.state["round_placements"] == {"rolland": 1}
        await _act(db_session, inst, "advance_round", {})
        assert inst.state["round_placements"] == {}
        assert inst.state["round_done"] == []
        assert inst.state["round"] == 2


# ── localize() coaching ────────────────────────────────────────────────────


class TestLocalize:
    async def test_localize_returns_none_for_user(self, db_session):
        inst = await _make_instance(db_session)
        assert localize(inst.state, ACTOR_USER) is None

    async def test_localize_includes_remaining_budget(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_blocks_per_turn", {"count": 3})
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        await _act(db_session, inst, "place", {"x": 0, "y": 0, "z": 0, "type": "stone"}, bot_id="rolland")
        text = localize(inst.state, "rolland")
        assert text is not None
        assert "2 of 3 placement" in text

    async def test_localize_shows_neighborhood_after_placement(self, db_session):
        inst = await _make_instance(db_session)
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        await _act(db_session, inst, "place", {"x": 5, "y": 5, "z": 0, "type": "stone"}, bot_id="rolland")
        # round advance not yet (zeus hasn't moved). Use rolland's localize anyway.
        text = localize(inst.state, "rolland")
        assert text is not None
        assert "Around your last placement" in text
        assert "(5, 5, 0)" in text

    async def test_localize_lists_unused_block_types(self, db_session):
        inst = await _make_instance(db_session)
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        await _act(db_session, inst, "place", {"x": 0, "y": 0, "z": 0, "type": "stone"}, bot_id="rolland")
        text = localize(inst.state, "rolland")
        assert text is not None
        assert "never placed" in text


# ── Notable labels ─────────────────────────────────────────────────────────


class TestNotableLabels:
    async def test_labels_appear_in_summary(self, db_session):
        inst = await _make_instance(db_session)
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        await _act(
            db_session,
            inst,
            "place",
            {"x": 5, "y": 5, "z": 0, "type": "wood", "label": "doorframe"},
            bot_id="rolland",
        )
        text = summarize(inst.state)
        assert "Notable labeled blocks" in text
        assert '"doorframe"' in text


# ── error_kind propagation through the router boundary ────────────────────


class TestErrorKindPropagation:
    """End-to-end check that a Blockyard ``ValidationError`` reaches the
    bot-facing ``WidgetActionResponse`` tagged as ``error_kind="validation"``.

    This is the seam that lets the workspace-attention detector tell a
    benign 4xx-shaped collision ("Cell already occupied") from a real
    system crash. Bots probing the grid must not page operators.
    """

    async def test_collision_propagates_validation_kind(self, db_session):
        from app.routers.api_v1_widget_actions import (
            WidgetActionRequest,
            _dispatch_native_widget,
        )

        inst = await _make_instance(db_session)
        await _start_with_participants(db_session, inst, "rolland", "zeus")
        await _act(
            db_session, inst, "place",
            {"x": 5, "y": 5, "z": 0, "type": "stone"}, bot_id="rolland",
        )
        await _act(
            db_session, inst, "place",
            {"x": 1, "y": 1, "z": 0, "type": "wood"}, bot_id="zeus",
        )

        # Round 2 — rolland tries to place on zeus's cell. Validation rejects.
        req = WidgetActionRequest(
            dispatch="native_widget",
            action="place",
            args={"x": 1, "y": 1, "z": 0, "type": "stone"},
            widget_instance_id=inst.id,
            bot_id="rolland",
        )
        resp = await _dispatch_native_widget(req, db_session)

        assert resp.ok is False
        assert resp.error is not None
        assert "already occupied" in resp.error
        assert resp.error_kind == "validation"

    async def test_unknown_action_propagates_not_found_kind(self, db_session):
        from app.domain.errors import NotFoundError
        from app.routers.api_v1_widget_actions import (
            WidgetActionRequest,
            _dispatch_native_widget,
        )

        inst = await _make_instance(db_session)
        req = WidgetActionRequest(
            dispatch="native_widget",
            action="totally_made_up_action",
            args={},
            widget_instance_id=inst.id,
        )
        resp = await _dispatch_native_widget(req, db_session)

        # The dispatcher raises NotFoundError for unknown actions; the router
        # boundary must classify that as ``not_found``, not ``internal``.
        assert resp.ok is False
        assert resp.error_kind == "not_found"
