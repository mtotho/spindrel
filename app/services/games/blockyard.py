"""Blockyard — collaborative voxel-stacking game on the spatial canvas.

Each participating bot places blocks on a shared 3D grid every turn. The
user is just another player (no environment layer here — building is
already additive and legible). Bots see the full grid on each heartbeat
and decide where to place next.

State is a sparse dict keyed by ``"x,y,z"`` — most of the volume is empty
on day 1, and JSON serialization stays small even for tall builds.
"""
from __future__ import annotations

import copy
import hashlib
import re
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
    apply_directive,
    assert_can_act,
    assert_phase,
    assert_user_only,
    clear_directive,
    record_turn,
    register_game,
)
from app.services.games.hints import (
    bot_pacing_nudge,
    neighborhood_snapshot,
    notable_labels,
    unused_block_types,
)


WIDGET_REF = "core/game_blockyard"
GAME_TYPE = "blockyard"

DEFAULT_BOUNDS = {"x": 16, "y": 16, "z": 8}
MIN_BOUND = 4
MAX_BOUND = 64
DEFAULT_BLOCKS_PER_TURN = 1
MAX_BLOCKS_PER_TURN = 5
LABEL_MAX_LEN = 48
NOTABLE_LABEL_CAP = 20

# Block vocabulary. Display colors are hints for the renderer; the bot
# only ever picks by name.
BLOCK_TYPES = (
    "stone",
    "wood",
    "glass",
    "dirt",
    "water",
    "wool",
    "light",
    "leaves",
    "sand",
    "brick",
)

# Stable per-bot palette so different participants render in distinct colors
# even if they never set one explicitly.
_PLAYER_PALETTE = (
    "#c8a45a",  # gold
    "#7aa2c8",  # blue
    "#c87a7a",  # coral
    "#7ac88a",  # mint
    "#b07ac8",  # violet
    "#7ac8c8",  # teal
    "#c8c87a",  # olive
    "#c87aa8",  # pink
    "#7a86c8",  # indigo
    "#c8967a",  # peach
)


_KEY_RE = re.compile(r"^-?\d+,-?\d+,-?\d+$")


def _key(x: int, y: int, z: int) -> str:
    return f"{x},{y},{z}"


def _unkey(k: str) -> tuple[int, int, int]:
    parts = k.split(",")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _player_palette(actor: str) -> str:
    digest = hashlib.sha256(actor.encode("utf-8")).digest()
    return _PLAYER_PALETTE[digest[0] % len(_PLAYER_PALETTE)]


def default_state() -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "game_type": GAME_TYPE,
        "phase": PHASE_SETUP,
        "participants": [],
        "last_actor": None,
        "round": 0,
        "round_started_log_index": 0,
        "turn_log": [],
        "bounds": dict(DEFAULT_BOUNDS),
        "blocks": {},
        "players": {},
        "blocks_per_turn": DEFAULT_BLOCKS_PER_TURN,
        "round_placements": {},
        "round_done": [],
        "directive": None,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _bounds(state: dict[str, Any]) -> tuple[int, int, int]:
    b = state.get("bounds") or DEFAULT_BOUNDS
    return (int(b.get("x") or DEFAULT_BOUNDS["x"]),
            int(b.get("y") or DEFAULT_BOUNDS["y"]),
            int(b.get("z") or DEFAULT_BOUNDS["z"]))


def _in_bounds(state: dict[str, Any], x: int, y: int, z: int) -> bool:
    bx, by, bz = _bounds(state)
    return 0 <= x < bx and 0 <= y < by and 0 <= z < bz


def _ensure_player(state: dict[str, Any], actor: str) -> dict[str, Any]:
    players = state.setdefault("players", {})
    if actor not in players:
        players[actor] = {
            "color": _player_palette(actor),
            "block_count": 0,
        }
    return players[actor]


def _normalize_label(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text[:LABEL_MAX_LEN]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Bot actions
# ---------------------------------------------------------------------------


def _action_place(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_phase(state, PHASE_PLAYING)
    try:
        x = int(args.get("x"))
        y = int(args.get("y"))
        z = int(args.get("z"))
    except (TypeError, ValueError):
        raise ValidationError("x, y, z must be integers.") from None
    block_type = str(args.get("type") or "").strip().lower()
    if block_type not in BLOCK_TYPES:
        raise ValidationError(
            f"type must be one of {list(BLOCK_TYPES)}, got {block_type!r}.",
        )
    if not _in_bounds(state, x, y, z):
        bx, by, bz = _bounds(state)
        raise ValidationError(
            f"({x},{y},{z}) is out of bounds (0..{bx-1}, 0..{by-1}, 0..{bz-1}).",
        )
    if actor != ACTOR_USER:
        budget = int(state.get("blocks_per_turn") or DEFAULT_BLOCKS_PER_TURN)
        used = int(((state.get("round_placements") or {}).get(actor) or 0))
        if used >= budget:
            raise ValidationError(
                f"You have already placed {used} block(s) this round "
                f"(blocks_per_turn={budget}); wait for next round.",
            )
    blocks = state.setdefault("blocks", {})
    key = _key(x, y, z)
    if key in blocks:
        raise ValidationError(f"Cell ({x},{y},{z}) is already occupied.")
    label = _normalize_label(args.get("label"))
    block = {
        "bot": actor,
        "type": block_type,
        "ts": _now_iso(),
    }
    if label:
        block["label"] = label
    blocks[key] = block
    if actor != ACTOR_USER:
        player = _ensure_player(state, actor)
        player["block_count"] = int(player.get("block_count") or 0) + 1
        placements = state.setdefault("round_placements", {})
        placements[actor] = int(placements.get(actor) or 0) + 1
    summary = f"placed {block_type} at ({x},{y},{z})"
    if label:
        summary += f" — {label}"
    return {"ok": True, "summary": summary, "x": x, "y": y, "z": z}


def _action_remove(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_phase(state, PHASE_PLAYING)
    try:
        x = int(args.get("x"))
        y = int(args.get("y"))
        z = int(args.get("z"))
    except (TypeError, ValueError):
        raise ValidationError("x, y, z must be integers.") from None
    blocks = state.get("blocks") or {}
    key = _key(x, y, z)
    block = blocks.get(key)
    if block is None:
        raise ValidationError(f"No block at ({x},{y},{z}).")
    owner = block.get("bot")
    state["blocks"] = {k: v for k, v in blocks.items() if k != key}
    if owner and owner != ACTOR_USER:
        player = state.get("players", {}).get(owner)
        if player is not None:
            player["block_count"] = max(0, int(player.get("block_count") or 0) - 1)
    owner_label = "your" if owner == actor else f"{owner}'s" if owner else "a"
    return {"ok": True, "summary": f"broke {owner_label} {block.get('type')} at ({x},{y},{z})"}


def _action_inspect(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """Read-only — does not consume a turn (no record_turn). The dispatch
    handler below short-circuits inspect calls so they stay free."""
    try:
        x = int(args.get("x"))
        y = int(args.get("y"))
        z = int(args.get("z"))
    except (TypeError, ValueError):
        raise ValidationError("x, y, z must be integers.") from None
    blocks = state.get("blocks") or {}
    block = blocks.get(_key(x, y, z))
    if block is None:
        return {"ok": True, "block": None, "summary": f"({x},{y},{z}) is empty"}
    return {
        "ok": True,
        "block": dict(block),
        "summary": f"({x},{y},{z}) is {block.get('type')} placed by {block.get('bot')}",
    }


# ---------------------------------------------------------------------------
# User actions
# ---------------------------------------------------------------------------


def _action_set_participants(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_participants")
    raw = args.get("bot_ids") or []
    if not isinstance(raw, list):
        raise ValidationError("bot_ids must be an array of bot ids.")
    bot_ids = [str(b).strip() for b in raw if str(b).strip()]
    state["participants"] = bot_ids
    state["last_actor"] = None
    for bot_id in bot_ids:
        _ensure_player(state, bot_id)
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
        for bot_id in state.get("participants", []):
            _ensure_player(state, bot_id)
    return {"ok": True, "phase": phase, "round": state.get("round", 0)}


def _action_set_player_color(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """User-only convenience for re-coloring a player's blocks display.

    Color is hint-only — the renderer uses it for the player's label chip
    and a thin tint on glass blocks; physical block color comes from the
    block ``type``. No effect on game logic.
    """
    assert_user_only(actor, "set_player_color")
    bot_id = str(args.get("bot_id") or "").strip()
    color = str(args.get("color") or "").strip()
    if not bot_id:
        raise ValidationError("bot_id is required.")
    if not color or not color.startswith("#"):
        raise ValidationError("color must be a hex string like #c8a45a.")
    player = _ensure_player(state, bot_id)
    player["color"] = color
    return {"ok": True, "bot_id": bot_id, "color": color}


def _action_advance_round(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """User can force a round bump if a participant is taking too long.

    Anyone who hasn't moved this round is skipped — they get the next round
    fresh. No state penalty.
    """
    assert_user_only(actor, "advance_round")
    assert_phase(state, PHASE_PLAYING)
    state["round"] = int(state.get("round") or 0) + 1
    state["last_actor"] = None
    state["round_started_log_index"] = len(state.get("turn_log") or []) + 1
    state["round_placements"] = {}
    state["round_done"] = []
    return {"ok": True, "round": state["round"]}


def _action_clear_blocks(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """User-only nuke for testing / starting fresh. Wipes all blocks but
    keeps participants, players, and turn_log intact."""
    assert_user_only(actor, "clear_blocks")
    state["blocks"] = {}
    for player in (state.get("players") or {}).values():
        player["block_count"] = 0
    state["round_placements"] = {}
    return {"ok": True, "summary": "cleared all blocks"}


def _action_set_bounds(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """User-only: change world bounds. Only allowed in setup so live builds
    don't get half-truncated."""
    assert_user_only(actor, "set_bounds")
    assert_phase(state, PHASE_SETUP)
    try:
        bx = int(args.get("x"))
        by = int(args.get("y"))
        bz = int(args.get("z"))
    except (TypeError, ValueError):
        raise ValidationError("x, y, z must be integers.") from None
    for axis, value in (("x", bx), ("y", by), ("z", bz)):
        if value < MIN_BOUND or value > MAX_BOUND:
            raise ValidationError(
                f"bounds.{axis} must be between {MIN_BOUND} and {MAX_BOUND}, got {value}.",
            )
    state["bounds"] = {"x": bx, "y": by, "z": bz}
    return {"ok": True, "bounds": state["bounds"]}


def _action_set_blocks_per_turn(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """User-only: how many placements each bot may make per round (1..5)."""
    assert_user_only(actor, "set_blocks_per_turn")
    try:
        value = int(args.get("count"))
    except (TypeError, ValueError):
        raise ValidationError("count must be an integer.") from None
    if value < 1 or value > MAX_BLOCKS_PER_TURN:
        raise ValidationError(
            f"count must be between 1 and {MAX_BLOCKS_PER_TURN}, got {value}.",
        )
    state["blocks_per_turn"] = value
    return {"ok": True, "blocks_per_turn": value}


def _action_set_directive(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """User-only: set or clear the creative directive. Empty theme clears it."""
    assert_user_only(actor, "set_directive")
    theme = str(args.get("theme") or "").strip()
    if not theme:
        cleared = clear_directive(state)
        return {"ok": True, "cleared": cleared, "directive": None}
    criteria = args.get("success_criteria")
    directive = apply_directive(
        state,
        theme=theme,
        success_criteria=str(criteria) if criteria else None,
        set_by=actor,
    )
    return {"ok": True, "directive": directive}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_BOT_ACTIONS = {
    "place": _action_place,
    "remove": _action_remove,
}

_USER_ACTIONS = {
    "set_participants": _action_set_participants,
    "set_phase": _action_set_phase,
    "set_player_color": _action_set_player_color,
    "set_bounds": _action_set_bounds,
    "set_blocks_per_turn": _action_set_blocks_per_turn,
    "set_directive": _action_set_directive,
    "advance_round": _action_advance_round,
    "clear_blocks": _action_clear_blocks,
    # User can also place / remove freely.
    "place": _action_place,
    "remove": _action_remove,
}

# Free read-only actions that don't consume a turn slot or update last_actor.
_FREE_ACTIONS = {"inspect": _action_inspect}


async def dispatch(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
    *,
    actor: str,
) -> Any:
    state = copy.deepcopy(instance.state or {})
    if "blocks" not in state or "bounds" not in state:
        state = default_state()
    state.setdefault("round_placements", {})
    state.setdefault("blocks_per_turn", DEFAULT_BLOCKS_PER_TURN)
    args = args or {}

    free_handler = _FREE_ACTIONS.get(action)
    if free_handler is not None:
        # No state mutation — no flush. Inspect is purely informational.
        return free_handler(state, actor, args)

    if actor == ACTOR_USER:
        handler = _USER_ACTIONS.get(action)
    else:
        handler = _BOT_ACTIONS.get(action)
    if handler is None:
        raise NotFoundError(f"Unsupported blockyard action: {action!r}")

    is_bot_action = actor != ACTOR_USER
    is_place = action == "place"
    if is_bot_action:
        # Participation gate first, then budget gate via the handler itself.
        participants = list(state.get("participants") or [])
        if actor not in participants:
            raise ValidationError(f"Bot {actor!r} is not a participant in this game.")
        if not is_place:
            # Non-place bot actions still consume the whole turn — apply the
            # framework's "already acted" guard.
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
        # Round advances when every participant has finished their turn —
        # either by exhausting their placement budget or by taking a
        # single-turn action like `remove`. This decouples from the
        # framework's per-action "moved" set so multi-block budgets work.
        budget = int(state.get("blocks_per_turn") or DEFAULT_BLOCKS_PER_TURN)
        used = int((state.get("round_placements") or {}).get(actor) or 0)
        budget_exhausted = is_place and used >= budget
        round_done = state.setdefault("round_done", [])
        if (not is_place) or budget_exhausted:
            state["last_actor"] = actor
            if actor not in round_done:
                round_done.append(actor)
        else:
            # Mid-budget — bot can still act this round.
            state["last_actor"] = None
        participants = list(state.get("participants") or [])
        if participants and all(p in round_done for p in participants):
            state["round"] = int(state.get("round") or 0) + 1
            state["last_actor"] = None
            state["round_started_log_index"] = len(state.get("turn_log") or [])
            state["round_placements"] = {}
            state["round_done"] = []
    instance.state = state
    flag_modified(instance, "state")
    await db.flush()
    return result


# ---------------------------------------------------------------------------
# State digest for heartbeat prompt
# ---------------------------------------------------------------------------


def _block_summary_for_actor(state: dict[str, Any], actor: str) -> str:
    blocks = state.get("blocks") or {}
    yours = [(_unkey(k), v) for k, v in blocks.items() if v.get("bot") == actor]
    others_total = sum(1 for v in blocks.values() if v.get("bot") != actor)
    if not yours:
        return f"You have placed 0 blocks. Other players have placed {others_total}."
    last = yours[-1]
    (lx, ly, lz), lv = last
    return (
        f"You have placed {len(yours)} block(s); your most recent: "
        f"{lv.get('type')} at ({lx},{ly},{lz}). "
        f"Other players have placed {others_total} block(s)."
    )


def _grid_snapshot(state: dict[str, Any], *, max_lines: int = 40) -> list[str]:
    """Compact textual snapshot of all occupied cells.

    Returns up to ``max_lines`` lines like ``"5,3,0 stone crumb"``. Bots
    rarely need every cell — they need to see structure shapes and recent
    activity. We sort by (z, y, x) so vertical layers cluster together.
    """
    blocks = state.get("blocks") or {}
    if not blocks:
        return ["(empty world)"]
    items: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for k, v in blocks.items():
        try:
            items.append((_unkey(k), v))
        except (ValueError, IndexError):
            continue
    items.sort(key=lambda kv: (kv[0][2], kv[0][1], kv[0][0]))
    lines: list[str] = []
    if len(items) > max_lines:
        # Keep the first 25 lowest blocks and the last 15 (most recent
        # placements bias toward higher z) — gives a sense of the build.
        head = items[: max_lines - 15]
        tail = items[-15:]
        items = head + tail
        lines.append(f"(showing {len(items)} of {len(state.get('blocks') or {})} blocks)")
    for (x, y, z), v in items:
        label = v.get("label")
        bot = v.get("bot")
        line = f"  {x},{y},{z} {v.get('type')} by {bot}"
        if label:
            line += f' "{label}"'
        lines.append(line)
    return lines


def summarize(state: dict[str, Any]) -> str:
    phase = state.get("phase") or PHASE_SETUP
    round_n = state.get("round") or 0
    last_actor = state.get("last_actor") or "—"
    bx, by, bz = _bounds(state)
    budget = int(state.get("blocks_per_turn") or DEFAULT_BLOCKS_PER_TURN)
    parts: list[str] = [
        "Blockyard is a collaborative voxel-building game. Each round you "
        f"may place up to {budget} block(s) on the shared 3D grid, then it's "
        "the next bot's turn. Build whatever you like — towers, gardens, "
        "bridges, sculptures. Coordinate or compete.",
        f"Round {round_n}, phase={phase}, last actor: {last_actor}",
        f"Bounds: {bx}×{by}×{bz}  (valid range: 0..{bx-1}, 0..{by-1}, 0..{bz-1}; "
        f"axes: +x east, +y south, +z up — z=0 is the floor).",
        f"Block types you may place: {', '.join(BLOCK_TYPES)}.",
        'place args: {"x": int, "y": int, "z": int, "type": "<one of the block types>", '
        '"label": "optional short tag", "reasoning": "optional"}.',
        'remove args: {"x": int, "y": int, "z": int, "reasoning": "optional"}.',
    ]
    players = state.get("players") or {}
    if players:
        parts.append("Players:")
        placements = state.get("round_placements") or {}
        for bot_id, player in players.items():
            used = int(placements.get(bot_id) or 0)
            parts.append(
                f"  {bot_id}: blocks={player.get('block_count', 0)} "
                f"(this round: {used}/{budget})",
            )
    labels = notable_labels(state.get("blocks") or {}, cap=NOTABLE_LABEL_CAP)
    if labels:
        parts.append("Notable labeled blocks (build on or beside these):")
        for entry in labels[:10]:
            parts.append(
                f"  - \"{entry['label']}\" — {entry.get('type')} at "
                f"({entry['x']},{entry['y']},{entry['z']}) by {entry.get('bot')}",
            )
    parts.append("Grid snapshot (sorted by z then y then x):")
    parts.extend(_grid_snapshot(state, max_lines=30))
    log = list(state.get("turn_log") or [])[-5:]
    if log:
        parts.append("Recent turns:")
        for entry in log:
            summary_text = entry.get("summary") or entry.get("action")
            note = entry.get("reasoning")
            line = f"  - {entry.get('actor')}: {summary_text}"
            if note:
                line += f" — {note}"
            parts.append(line)
    return "\n".join(parts)


def _last_placement_for(state: dict[str, Any], actor: str) -> tuple[int, int, int] | None:
    yours: list[tuple[tuple[int, int, int], str]] = []
    for key, cell in (state.get("blocks") or {}).items():
        if cell.get("bot") != actor:
            continue
        try:
            x, y, z = _unkey(key)
        except (ValueError, IndexError):
            continue
        yours.append(((x, y, z), str(cell.get("ts") or "")))
    if not yours:
        return None
    yours.sort(key=lambda kv: kv[1])
    return yours[-1][0]


def localize(state: dict[str, Any], actor: str) -> str | None:
    """Per-bot coaching: budget remaining, last-placement neighborhood,
    pacing nudge, and any unused block types worth trying."""
    if actor == ACTOR_USER or not actor:
        return None
    parts: list[str] = []
    budget = int(state.get("blocks_per_turn") or DEFAULT_BLOCKS_PER_TURN)
    used = int(((state.get("round_placements") or {}).get(actor) or 0))
    remaining = max(0, budget - used)
    parts.append(
        f"This round: you have {remaining} of {budget} placement(s) left.",
    )
    anchor = _last_placement_for(state, actor)
    if anchor is not None:
        snapshot = neighborhood_snapshot(state.get("blocks") or {}, anchor, radius=2)
        parts.append(f"Around your last placement {anchor}:")
        parts.append(snapshot)
    nudge = bot_pacing_nudge(state, actor)
    if nudge:
        parts.append(nudge)
    unused = unused_block_types(state, actor, BLOCK_TYPES)
    if unused and len(unused) < len(BLOCK_TYPES):
        parts.append(
            f"Block types you've never placed: {', '.join(unused[:5])}.",
        )
    return "\n".join(parts) if parts else None


def available_actions(state: dict[str, Any], actor: str) -> list[str]:
    if actor == ACTOR_USER:
        return list(_USER_ACTIONS.keys()) + ["inspect"]
    phase = state.get("phase") or PHASE_SETUP
    if phase == PHASE_ENDED:
        return []
    if phase == PHASE_SETUP:
        # Bots can't act until the user starts the game.
        return []
    return ["place", "remove", "inspect"]


register_game(
    WIDGET_REF,
    dispatcher=dispatch,
    summarizer=summarize,
    available_actions=available_actions,
    localize=localize,
)
