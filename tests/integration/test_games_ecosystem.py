"""Integration tests for the spatial-canvas Ecosystem Sim game.

Exercises the dispatch path end to end against ``WidgetInstance`` rows so
we cover the JSONB persistence + game rules + framework gating in one go.
The heartbeat-prompt block is exercised via a focused helper test that
seeds two participants and asserts the formatted output.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.db.models import WidgetInstance
from app.domain.errors import ValidationError
from app.services.dashboards import WORKSPACE_SPATIAL_DASHBOARD_KEY
from app.services.games import ACTOR_USER, PHASE_ENDED, PHASE_PLAYING, PHASE_SETUP
from app.services.games.ecosystem import (
    BOARD_SIZE,
    EXPAND_FOOD_COST,
    STARTING_FOOD,
    WIDGET_REF,
    default_state,
)
from app.services.native_app_widgets import dispatch_native_widget_action


pytestmark = pytest.mark.asyncio


async def _make_instance(db_session, *, with_spatial_pin: bool = False) -> WidgetInstance:
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
    if with_spatial_pin:
        from app.db.models import WidgetDashboardPin

        pin = WidgetDashboardPin(
            id=uuid.uuid4(),
            dashboard_key=WORKSPACE_SPATIAL_DASHBOARD_KEY,
            widget_instance_id=instance.id,
            position=0,
            source_kind="dashboard",
            tool_name="native_app",
            envelope={},
        )
        db_session.add(pin)
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


def _owned_count(state: dict[str, Any], bot_id: str) -> int:
    cells = state["board"]["cells"]
    return sum(
        1 for row in cells for cell in row if cell and cell.get("owner") == bot_id
    )


def _valid_move(state: dict[str, Any], bot_id: str) -> tuple[dict[str, int], str]:
    """Pick (from cell, direction) for a legal expand. Test helper to dodge
    deterministic-seed edge cases and round-2 crowding where the default
    ``from`` (most recently claimed cell) has no free neighbor."""
    cells = state["board"]["cells"]
    size = state["board"]["size"]
    for y in range(size):
        for x in range(size):
            cell = cells[y][x]
            if not cell or cell.get("owner") != bot_id:
                continue
            for direction, (dx, dy) in (
                ("east", (1, 0)),
                ("west", (-1, 0)),
                ("south", (0, 1)),
                ("north", (0, -1)),
            ):
                nx, ny = x + dx, y + dy
                if 0 <= nx < size and 0 <= ny < size and cells[ny][nx] is None:
                    return {"x": x, "y": y}, direction
    raise AssertionError(f"No valid move for {bot_id}")


def _valid_direction(state: dict[str, Any], bot_id: str) -> str:
    return _valid_move(state, bot_id)[1]


class TestSetupAndPhase:
    async def test_default_state_is_setup_with_empty_board(self, db_session):
        instance = await _make_instance(db_session)
        assert instance.state["phase"] == PHASE_SETUP
        assert instance.state["round"] == 0
        assert instance.state["board"]["size"] == BOARD_SIZE
        assert all(cell is None for row in instance.state["board"]["cells"] for cell in row)

    async def test_user_sets_participants_and_starts_game(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb", "zymia"]})
        assert instance.state["participants"] == ["crumb", "zymia"]
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        assert instance.state["phase"] == PHASE_PLAYING
        assert instance.state["round"] == 1
        # Auto-seeded species records for participants who didn't define their own.
        assert "crumb" in instance.state["species"]
        assert "zymia" in instance.state["species"]
        assert instance.state["species"]["crumb"]["food"] == STARTING_FOOD
        assert _owned_count(instance.state, "crumb") == 1
        assert _owned_count(instance.state, "zymia") == 1


class TestBotMoves:
    async def test_define_species_claims_starting_cell(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb"]})
        await _act(
            db_session,
            instance,
            "define_species",
            {"emoji": "🦊", "color": "#aa3344", "traits": ["aggressive"]},
            bot_id="crumb",
        )
        species = instance.state["species"]["crumb"]
        assert species["emoji"] == "🦊"
        assert species["traits"] == ["aggressive"]
        assert _owned_count(instance.state, "crumb") == 1

    async def test_expand_consumes_food_and_claims_adjacent(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        food_before = instance.state["species"]["crumb"]["food"]
        owned_before = _owned_count(instance.state, "crumb")
        direction = _valid_direction(instance.state, "crumb")
        await _act(
            db_session,
            instance,
            "expand",
            {"direction": direction, "reasoning": "spreading toward food"},
            bot_id="crumb",
        )
        assert instance.state["species"]["crumb"]["food"] == food_before - EXPAND_FOOD_COST
        assert _owned_count(instance.state, "crumb") == owned_before + 1

    async def test_double_move_in_same_round_rejected(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb", "zymia"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        d1 = _valid_direction(instance.state, "crumb")
        await _act(db_session, instance, "expand", {"direction": d1}, bot_id="crumb")
        # crumb has acted; can't act again until other participants move.
        with pytest.raises(ValidationError):
            await _act(db_session, instance, "expand", {"direction": d1}, bot_id="crumb")

    async def test_non_participant_rejected(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        with pytest.raises(ValidationError):
            await _act(db_session, instance, "expand", {"direction": "north"}, bot_id="trespasser")

    async def test_round_advances_when_all_participants_move(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb", "zymia"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        round_before = instance.state["round"]
        from_xy, direction = _valid_move(instance.state, "crumb")
        await _act(
            db_session, instance, "expand",
            {"direction": direction, "from": from_xy}, bot_id="crumb",
        )
        # zymia hasn't moved yet — round still the same.
        assert instance.state["round"] == round_before
        from_xy, direction = _valid_move(instance.state, "zymia")
        await _act(
            db_session, instance, "expand",
            {"direction": direction, "from": from_xy}, bot_id="zymia",
        )
        # both moved → round bumped, last_actor reset.
        assert instance.state["round"] == round_before + 1
        assert instance.state["last_actor"] is None
        # crumb can now act again.
        from_xy, direction = _valid_move(instance.state, "crumb")
        await _act(
            db_session, instance, "expand",
            {"direction": direction, "from": from_xy}, bot_id="crumb",
        )

    async def test_eat_neighbor_requires_aggressive_trait(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb", "zymia"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        # Place zymia adjacent to crumb's first cell.
        cells = instance.state["board"]["cells"]
        crumb_xy = next(
            (x, y)
            for y in range(BOARD_SIZE)
            for x in range(BOARD_SIZE)
            if cells[y][x] and cells[y][x]["owner"] == "crumb"
        )
        # Find a neighbor cell that's empty or zymia's, otherwise pick adjacent.
        nx, ny = crumb_xy[0] + 1, crumb_xy[1]
        if 0 <= nx < BOARD_SIZE:
            instance.state["board"]["cells"][ny][nx] = {"owner": "zymia", "food": 0}
        else:
            nx, ny = crumb_xy[0] - 1, crumb_xy[1]
            instance.state["board"]["cells"][ny][nx] = {"owner": "zymia", "food": 0}
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(instance, "state")
        await db_session.flush()
        with pytest.raises(ValidationError):
            await _act(
                db_session,
                instance,
                "eat_neighbor",
                {"x": nx, "y": ny},
                bot_id="crumb",
            )


class TestEnvironment:
    async def test_drought_halves_food_on_advance_round(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        instance.state["species"]["crumb"]["food"] = 10
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(instance, "state")
        await db_session.flush()
        await _act(db_session, instance, "set_environment", {"weather": "drought"})
        await _act(db_session, instance, "advance_round", {})
        assert instance.state["species"]["crumb"]["food"] == 5

    async def test_food_source_grants_owner_bonus(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        cells = instance.state["board"]["cells"]
        crumb_xy = next(
            (x, y)
            for y in range(BOARD_SIZE)
            for x in range(BOARD_SIZE)
            if cells[y][x] and cells[y][x]["owner"] == "crumb"
        )
        food_before = instance.state["species"]["crumb"]["food"]
        await _act(
            db_session,
            instance,
            "set_environment",
            {"food_sources": [{"x": crumb_xy[0], "y": crumb_xy[1], "amount": 4}]},
        )
        await _act(db_session, instance, "advance_round", {})
        assert instance.state["species"]["crumb"]["food"] == food_before + 4


class TestUserOnlyGating:
    async def test_bot_cannot_call_user_actions(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb"]})
        with pytest.raises(ValidationError):
            await _act(
                db_session,
                instance,
                "set_phase",
                {"phase": "playing"},
                bot_id="crumb",
            )


class TestEndedPhase:
    async def test_ended_blocks_bot_moves(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        await _act(db_session, instance, "set_phase", {"phase": "ended"})
        assert instance.state["phase"] == PHASE_ENDED
        with pytest.raises(ValidationError):
            await _act(
                db_session,
                instance,
                "expand",
                {"direction": "east"},
                bot_id="crumb",
            )


class TestHeartbeatBlock:
    async def test_no_block_when_not_a_participant(self, db_session):
        instance = await _make_instance(db_session)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["other"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        from app.services.games.heartbeat import build_active_games_block

        block = await build_active_games_block(
            db_session, channel_id=None, bot_id="not-in-game",
        )
        assert block is None

    async def test_block_lists_pending_games(self, db_session):
        instance = await _make_instance(db_session, with_spatial_pin=True)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        from app.services.games.heartbeat import build_active_games_block

        block = await build_active_games_block(
            db_session, channel_id=None, bot_id="crumb",
        )
        assert block is not None
        assert "[active_games]" in block
        assert "Available actions" in block
        assert "expand" in block

    async def test_block_omits_after_actor_moves(self, db_session):
        instance = await _make_instance(db_session, with_spatial_pin=True)
        await _act(db_session, instance, "set_participants", {"bot_ids": ["crumb", "zymia"]})
        await _act(db_session, instance, "set_phase", {"phase": "playing"})
        d = _valid_direction(instance.state, "crumb")
        await _act(db_session, instance, "expand", {"direction": d}, bot_id="crumb")
        from app.services.games.heartbeat import build_active_games_block

        # crumb just moved; their next heartbeat shouldn't see the same game.
        block = await build_active_games_block(
            db_session, channel_id=None, bot_id="crumb",
        )
        assert block is None
        # zymia hasn't moved yet — should still see it.
        block = await build_active_games_block(
            db_session, channel_id=None, bot_id="zymia",
        )
        assert block is not None
