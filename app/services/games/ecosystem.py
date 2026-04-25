"""Ecosystem Sim — first concrete spatial-canvas game.

Each bot owns a *species* on a 12×12 grid clipped to an asteroid silhouette.
The user plays the environment layer: weather, food sources, advancing
rounds. Bots take async turns at heartbeat — expand into adjacent cells,
evolve traits, eat enemies — limited by food and trait gating.

State lives entirely in ``WidgetInstance.state``. All mutation goes through
``dispatch`` below; the action schemas surfaced via the native widget spec
match these handlers exactly.
"""
from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import WidgetInstance
from app.domain.errors import NotFoundError, ValidationError
from app.services.games import (
    ACTOR_USER,
    PHASE_ENDED,
    PHASE_PLAYING,
    PHASE_SETUP,
    assert_can_act,
    assert_phase,
    assert_user_only,
    maybe_advance_round,
    record_turn,
    register_game,
)


WIDGET_REF = "core/game_ecosystem"
BOARD_SIZE = 12
STARTING_FOOD = 3
EXPAND_FOOD_COST = 1
MAX_TRAITS = 3
TRAIT_VOCAB = (
    "aggressive",
    "fast",
    "slow",
    "photosynthetic",
    "parasitic",
    "thorny",
    "burrowing",
    "luminous",
)
WEATHER_VOCAB = ("neutral", "drought", "flood", "bloom")

# Direction → (dx, dy)
DIRECTIONS = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}


# ---------------------------------------------------------------------------
# Default state + helpers
# ---------------------------------------------------------------------------


def default_state() -> dict[str, Any]:
    cells: list[list[Any]] = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    now = datetime.now(timezone.utc).isoformat()
    return {
        "game_type": "ecosystem",
        "phase": PHASE_SETUP,
        "participants": [],
        "last_actor": None,
        "round": 0,
        "round_started_log_index": 0,
        "turn_log": [],
        "board": {"size": BOARD_SIZE, "cells": cells},
        "species": {},
        "environment": {"weather": "neutral", "food_sources": []},
        "created_at": now,
        "updated_at": now,
    }


def _seed_xy(actor: str) -> tuple[int, int]:
    """Deterministic starting cell from a bot id."""
    digest = hashlib.sha256(actor.encode("utf-8")).digest()
    return (digest[0] % BOARD_SIZE, digest[1] % BOARD_SIZE)


# Distinct fallback species look — used when a bot is auto-seeded without
# calling `define_species`. Indexed by a stable hash of the bot id so each
# bot reads as its own creature on the asteroid instead of an identical
# generic sprout.
_FALLBACK_EMOJI = ("🌱", "🍄", "🌿", "🪲", "🦠", "🐛", "🪷", "🦀", "🦂", "🪼", "🦑")
_FALLBACK_COLOR = (
    "#7aa2c8",  # blue
    "#c87a7a",  # coral
    "#7ac88a",  # mint
    "#c8a87a",  # tan
    "#b07ac8",  # violet
    "#7ac8c8",  # teal
    "#c8c87a",  # olive
    "#c87aa8",  # pink
    "#7a86c8",  # indigo
    "#c8967a",  # peach
    "#9ac87a",  # leaf
)


def _fallback_species_look(actor: str) -> tuple[str, str]:
    """Pick a stable (emoji, color) pair from the bot id."""
    digest = hashlib.sha256(actor.encode("utf-8")).digest()
    return (
        _FALLBACK_EMOJI[digest[2] % len(_FALLBACK_EMOJI)],
        _FALLBACK_COLOR[digest[3] % len(_FALLBACK_COLOR)],
    )


def _in_bounds(x: int, y: int) -> bool:
    return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE


def _cell(state: dict[str, Any], x: int, y: int) -> dict[str, Any] | None:
    return state["board"]["cells"][y][x]


def _set_cell(state: dict[str, Any], x: int, y: int, value: dict[str, Any] | None) -> None:
    state["board"]["cells"][y][x] = value


def _find_free_near(state: dict[str, Any], x: int, y: int) -> tuple[int, int]:
    """Spiral outward from (x, y) to find the first empty cell. Falls back to
    a brute-force scan if the local neighborhood is fully claimed."""
    if _in_bounds(x, y) and _cell(state, x, y) is None:
        return x, y
    for radius in range(1, BOARD_SIZE):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) != radius and abs(dy) != radius:
                    continue
                nx, ny = x + dx, y + dy
                if _in_bounds(nx, ny) and _cell(state, nx, ny) is None:
                    return nx, ny
    raise ValidationError("Board is full — no free cell to seed.")


def _owned_cells(state: dict[str, Any], owner: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    cells = state["board"]["cells"]
    for y in range(BOARD_SIZE):
        for x in range(BOARD_SIZE):
            cell = cells[y][x]
            if cell and cell.get("owner") == owner:
                out.append((x, y))
    return out


def _has_trait(state: dict[str, Any], owner: str, trait: str) -> bool:
    species = state.get("species", {}).get(owner) or {}
    return trait in (species.get("traits") or [])


def _adjust_food(state: dict[str, Any], owner: str, delta: int) -> int:
    species = state["species"][owner]
    species["food"] = max(0, int(species.get("food") or 0) + delta)
    return species["food"]


# ---------------------------------------------------------------------------
# Bot actions
# ---------------------------------------------------------------------------


def _action_define_species(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_phase(state, PHASE_SETUP)
    if actor in state.get("species", {}):
        raise ValidationError("You have already defined your species.")
    if actor not in (state.get("participants") or []):
        raise ValidationError("You are not a participant in this game.")
    emoji = str(args.get("emoji") or "🌱").strip() or "🌱"
    color = str(args.get("color") or "#7aa2c8").strip() or "#7aa2c8"
    raw_traits = args.get("traits") or []
    traits = [str(t).strip().lower() for t in raw_traits if str(t).strip()]
    invalid = [t for t in traits if t not in TRAIT_VOCAB]
    if invalid:
        raise ValidationError(
            f"Unknown traits: {invalid}. Allowed: {list(TRAIT_VOCAB)}",
        )
    if len(traits) > MAX_TRAITS:
        raise ValidationError(f"At most {MAX_TRAITS} traits allowed.")
    seed_x, seed_y = _seed_xy(actor)
    sx, sy = _find_free_near(state, seed_x, seed_y)
    state.setdefault("species", {})[actor] = {
        "emoji": emoji,
        "color": color,
        "traits": traits,
        "food": STARTING_FOOD,
    }
    _set_cell(state, sx, sy, {"owner": actor, "food": 0})
    return {"ok": True, "summary": f"{actor} took root at ({sx},{sy})", "x": sx, "y": sy}


def _action_expand(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_phase(state, PHASE_PLAYING)
    if actor not in state.get("species", {}):
        raise ValidationError("Define your species before expanding.")
    direction = str(args.get("direction") or "").lower()
    if direction not in DIRECTIONS:
        raise ValidationError(f"direction must be one of {list(DIRECTIONS)}")
    from_xy = args.get("from") or {}
    if not from_xy:
        owned = _owned_cells(state, actor)
        if not owned:
            raise ValidationError("You have no cells to expand from.")
        # Default: spread from the most recently claimed cell.
        fx, fy = owned[-1]
    else:
        fx, fy = int(from_xy.get("x", -1)), int(from_xy.get("y", -1))
        if not _in_bounds(fx, fy):
            raise ValidationError("from cell is out of bounds.")
        cell = _cell(state, fx, fy)
        if not cell or cell.get("owner") != actor:
            raise ValidationError("from cell must be one you own.")
    dx, dy = DIRECTIONS[direction]
    nx, ny = fx + dx, fy + dy
    if not _in_bounds(nx, ny):
        raise ValidationError("Target cell is off the board.")
    if _cell(state, nx, ny) is not None:
        raise ValidationError("Target cell is already occupied — try eat_neighbor.")
    food = state["species"][actor].get("food", 0)
    if food < EXPAND_FOOD_COST:
        raise ValidationError(f"Not enough food (have {food}, need {EXPAND_FOOD_COST}).")
    _adjust_food(state, actor, -EXPAND_FOOD_COST)
    _set_cell(state, nx, ny, {"owner": actor, "food": 0})
    return {"ok": True, "summary": f"expanded {direction} to ({nx},{ny})", "x": nx, "y": ny}


def _action_evolve_trait(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_phase(state, (PHASE_SETUP, PHASE_PLAYING))
    if actor not in state.get("species", {}):
        raise ValidationError("Define your species before evolving.")
    op = str(args.get("op") or "").lower()
    if op not in ("add", "remove"):
        raise ValidationError("op must be 'add' or 'remove'")
    trait = str(args.get("trait") or "").strip().lower()
    if trait not in TRAIT_VOCAB:
        raise ValidationError(f"Unknown trait. Allowed: {list(TRAIT_VOCAB)}")
    species = state["species"][actor]
    traits = list(species.get("traits") or [])
    if op == "add":
        if trait in traits:
            raise ValidationError(f"Already have trait {trait!r}.")
        if len(traits) >= MAX_TRAITS:
            raise ValidationError(f"Max {MAX_TRAITS} traits — remove one first.")
        traits.append(trait)
    else:
        if trait not in traits:
            raise ValidationError(f"Don't have trait {trait!r}.")
        traits.remove(trait)
    species["traits"] = traits
    return {"ok": True, "summary": f"{op} trait {trait}", "traits": traits}


def _action_eat_neighbor(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_phase(state, PHASE_PLAYING)
    if actor not in state.get("species", {}):
        raise ValidationError("Define your species before eating.")
    if not _has_trait(state, actor, "aggressive"):
        raise ValidationError("eat_neighbor requires the 'aggressive' trait.")
    tx, ty = int(args.get("x", -1)), int(args.get("y", -1))
    if not _in_bounds(tx, ty):
        raise ValidationError("Target cell is off the board.")
    target = _cell(state, tx, ty)
    if not target:
        raise ValidationError("Target cell is empty.")
    if target.get("owner") == actor:
        raise ValidationError("Cannot eat your own cell.")
    # Must be adjacent to one of the actor's cells.
    owned = set(_owned_cells(state, actor))
    if not any((tx + dx, ty + dy) in owned for dx, dy in DIRECTIONS.values()):
        raise ValidationError("Target cell must be adjacent to one of yours.")
    victim = target["owner"]
    transferred = max(1, int(state["species"][victim].get("food", 0)) // 2)
    _adjust_food(state, victim, -transferred)
    _adjust_food(state, actor, transferred)
    # Thorny defender retaliates — attacker loses 1 food and the cell
    # capture fizzles half the time (enough to make thorny a real wall).
    retaliation = 0
    captured = True
    if _has_trait(state, victim, "thorny"):
        retaliation = 1
        _adjust_food(state, actor, -retaliation)
        # Burrowing victims hold the ground harder — capture fails.
        if _has_trait(state, victim, "burrowing"):
            captured = False
    if captured:
        _set_cell(state, tx, ty, {"owner": actor, "food": 0})
    suffix = ""
    if retaliation:
        suffix = f"; thorns bit back -{retaliation}"
    if not captured:
        suffix += " (cell held)"
    return {
        "ok": True,
        "summary": f"ate {victim}'s cell at ({tx},{ty}); +{transferred} food{suffix}",
        "transferred": transferred,
        "retaliation": retaliation,
        "captured": captured,
    }


# ---------------------------------------------------------------------------
# User actions (environment layer)
# ---------------------------------------------------------------------------


def _action_set_participants(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_participants")
    raw = args.get("bot_ids") or []
    if not isinstance(raw, list):
        raise ValidationError("bot_ids must be an array of bot ids.")
    bot_ids = [str(b).strip() for b in raw if str(b).strip()]
    state["participants"] = bot_ids
    state["last_actor"] = None
    # Drop species records for bots no longer participating; their cells stay
    # as orphan claimed cells (visual reminder) but lose food generation.
    return {"ok": True, "participants": bot_ids}


def _action_set_phase(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_phase")
    phase = str(args.get("phase") or "").lower()
    if phase not in (PHASE_SETUP, PHASE_PLAYING, PHASE_ENDED):
        raise ValidationError("phase must be one of setup|playing|ended")
    previous = state.get("phase")
    state["phase"] = phase
    if previous == PHASE_SETUP and phase == PHASE_PLAYING:
        state["round"] = 1
        state["round_started_log_index"] = len(state.get("turn_log") or []) + 1
        # Ensure every participant has a species record (even if they didn't
        # call define_species during setup) so the game is playable on day 1.
        for bot_id in state.get("participants", []):
            if bot_id not in state.get("species", {}):
                emoji, color = _fallback_species_look(bot_id)
                state["species"][bot_id] = {
                    "emoji": emoji,
                    "color": color,
                    "traits": [],
                    "food": STARTING_FOOD,
                }
                seed_x, seed_y = _seed_xy(bot_id)
                sx, sy = _find_free_near(state, seed_x, seed_y)
                _set_cell(state, sx, sy, {"owner": bot_id, "food": 0})
            else:
                # Existing species but no cell on the board (e.g. user
                # added a participant who never called define_species and
                # got the default look from a previous transition that has
                # since lost their cell). Make sure they have a starting
                # tile so they aren't rendered floating off the asteroid.
                if not _owned_cells(state, bot_id):
                    seed_x, seed_y = _seed_xy(bot_id)
                    sx, sy = _find_free_near(state, seed_x, seed_y)
                    _set_cell(state, sx, sy, {"owner": bot_id, "food": 0})
    return {"ok": True, "phase": phase, "round": state.get("round", 0)}


def _action_set_environment(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_environment")
    env = state.setdefault("environment", {"weather": "neutral", "food_sources": []})
    if "weather" in args:
        weather = str(args.get("weather") or "neutral").lower()
        if weather not in WEATHER_VOCAB:
            raise ValidationError(f"weather must be one of {list(WEATHER_VOCAB)}")
        env["weather"] = weather
    if "food_sources" in args:
        sources = args.get("food_sources") or []
        if not isinstance(sources, list):
            raise ValidationError("food_sources must be an array.")
        cleaned = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            sx = int(source.get("x", -1))
            sy = int(source.get("y", -1))
            amount = max(1, int(source.get("amount") or 1))
            if not _in_bounds(sx, sy):
                continue
            cleaned.append({"x": sx, "y": sy, "amount": amount})
        env["food_sources"] = cleaned
    return {"ok": True, "environment": copy.deepcopy(env)}


def _action_advance_round(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "advance_round")
    assert_phase(state, PHASE_PLAYING)
    weather = state.get("environment", {}).get("weather", "neutral")
    species = state.get("species", {})
    cells = state["board"]["cells"]
    # Apply weather effects.
    for bot_id, sp in species.items():
        food = int(sp.get("food") or 0)
        if weather == "drought":
            food = food // 2
        elif weather == "bloom":
            food = food * 2
        sp["food"] = food
    # Trait-driven passive income — runs after weather so bloom amplifies the
    # base photosynthesis bonus. Photosynthetic species harvest sunlight per
    # owned cell (capped). Parasitic species leech 1 food per turn from any
    # adjacent enemy cell owner they touch.
    for bot_id, sp in species.items():
        traits = sp.get("traits") or []
        owned = _owned_cells(state, bot_id)
        if "photosynthetic" in traits:
            gain = min(3, max(1, len(owned) // 2))
            if weather == "bloom":
                gain += 1
            if weather == "drought":
                gain = max(0, gain - 1)
            _adjust_food(state, bot_id, gain)
        if "parasitic" in traits:
            leeched_from: set[str] = set()
            owned_set = set(owned)
            for x, y in owned:
                for dx, dy in DIRECTIONS.values():
                    nx, ny = x + dx, y + dy
                    if not _in_bounds(nx, ny):
                        continue
                    target = cells[ny][nx]
                    if not target:
                        continue
                    target_owner = target.get("owner")
                    if not target_owner or target_owner == bot_id:
                        continue
                    if target_owner in leeched_from:
                        continue
                    if (nx, ny) in owned_set:
                        continue
                    if target_owner in species:
                        _adjust_food(state, target_owner, -1)
                        _adjust_food(state, bot_id, 1)
                        leeched_from.add(target_owner)
    # Food sources grant their owner +amount per round.
    for source in state.get("environment", {}).get("food_sources", []):
        x, y = int(source.get("x", -1)), int(source.get("y", -1))
        if not _in_bounds(x, y):
            continue
        cell = cells[y][x]
        if cell and cell.get("owner") in species:
            _adjust_food(state, cell["owner"], int(source.get("amount") or 1))
    state["round"] = int(state.get("round") or 0) + 1
    state["last_actor"] = None
    state["round_started_log_index"] = len(state.get("turn_log") or []) + 1
    return {"ok": True, "round": state["round"], "weather": weather}


def _action_feed_species(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """User-side balance lever: directly hand food to a species.

    Useful when a species gets stomped early and needs help to stay in the
    game. Negative amounts are allowed — the user can also penalize.
    """
    assert_user_only(actor, "feed_species")
    target = str(args.get("bot_id") or "").strip()
    if not target:
        raise ValidationError("bot_id is required.")
    if target not in state.get("species", {}):
        raise ValidationError(f"{target!r} has no species in this game.")
    amount = int(args.get("amount", 0))
    if amount == 0:
        raise ValidationError("amount must be a non-zero integer.")
    new_food = _adjust_food(state, target, amount)
    sign = "+" if amount > 0 else ""
    return {
        "ok": True,
        "summary": f"{target} food {sign}{amount} (now {new_food})",
        "food": new_food,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_BOT_ACTIONS = {
    "define_species": _action_define_species,
    "expand": _action_expand,
    "evolve_trait": _action_evolve_trait,
    "eat_neighbor": _action_eat_neighbor,
}

_USER_ACTIONS = {
    "set_participants": _action_set_participants,
    "set_phase": _action_set_phase,
    "set_environment": _action_set_environment,
    "advance_round": _action_advance_round,
    "feed_species": _action_feed_species,
}


async def dispatch(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
    *,
    actor: str,
) -> Any:
    """Run a single ecosystem move. Mutates ``instance.state`` in place."""
    state = copy.deepcopy(instance.state or {})
    # Lazy migration: legacy rows missing schema get a fresh default.
    if "board" not in state or "species" not in state:
        state = default_state()
    args = args or {}
    handler = _BOT_ACTIONS.get(action) or _USER_ACTIONS.get(action)
    if handler is None:
        raise NotFoundError(f"Unsupported ecosystem action: {action!r}")
    is_bot_action = action in _BOT_ACTIONS
    if is_bot_action:
        assert_can_act(state, actor)
    result = handler(state, actor, args)
    record_turn(
        state,
        actor=actor,
        action=action,
        args=args,
        reasoning=str(args.get("reasoning") or "").strip() or None,
        summary=result.get("summary") if isinstance(result, dict) else None,
    )
    if is_bot_action:
        maybe_advance_round(state)
    instance.state = state
    flag_modified(instance, "state")
    await db.flush()
    return result


def summarize(state: dict[str, Any]) -> str:
    phase = state.get("phase") or PHASE_SETUP
    round_n = state.get("round") or 0
    last_actor = state.get("last_actor") or "—"
    species = state.get("species") or {}
    weather = (state.get("environment") or {}).get("weather", "neutral")
    parts = [f"Round {round_n}, phase={phase}, last actor: {last_actor}, weather: {weather}"]
    for bot_id, sp in species.items():
        traits = ", ".join(sp.get("traits") or []) or "—"
        parts.append(
            f"  {bot_id}: food={sp.get('food', 0)}, traits=[{traits}]",
        )
    log = list(state.get("turn_log") or [])[-3:]
    if log:
        parts.append("recent turns:")
        for entry in log:
            summary = entry.get("summary") or entry.get("action")
            parts.append(f"  - {entry['actor']}: {summary}")
    return "\n".join(parts)


def available_actions(state: dict[str, Any], actor: str) -> list[str]:
    if actor == ACTOR_USER:
        return list(_USER_ACTIONS.keys())
    phase = state.get("phase") or PHASE_SETUP
    if phase == PHASE_ENDED:
        return []
    if phase == PHASE_SETUP:
        return ["define_species", "evolve_trait"]
    return ["expand", "evolve_trait", "eat_neighbor"]


register_game(
    WIDGET_REF,
    dispatcher=dispatch,
    summarizer=summarize,
    available_actions=available_actions,
)
