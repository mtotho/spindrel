"""Spatial-canvas turn-based games framework.

Games are a class of native widgets pinned to ``workspace:spatial``. State
lives in ``WidgetInstance.state`` (JSONB) — no new tables. Bots make moves
via the existing ``invoke_widget_action`` tool; handlers in this package
enforce participation and turn order, then mutate state in place.

Each concrete game lives in its own submodule (e.g. ``ecosystem.py``) and
exposes:

- ``dispatch(db, instance, action, args, *, actor)`` — runs a single move.
- ``summarize(state)`` — short text digest for the heartbeat prompt.

The shared helpers below keep games consistent on participant gating,
turn-log shape, and round bookkeeping. They are deliberately small —
games carry their own rules; the framework only owns the cross-cutting
turn protocol.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.domain.errors import ValidationError


GAME_WIDGET_PREFIX = "core/game_"

PHASE_SETUP = "setup"
PHASE_PLAYING = "playing"
PHASE_ENDED = "ended"

ACTOR_USER = "__user__"
"""Sentinel for moves originating from the workspace user (no bot_id)."""

USER_ONLY_ACTIONS_KEY = "__user_only_actions__"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def assert_phase(state: dict[str, Any], expected: str | tuple[str, ...]) -> None:
    phase = state.get("phase") or PHASE_SETUP
    expected_set = (expected,) if isinstance(expected, str) else tuple(expected)
    if phase not in expected_set:
        raise ValidationError(
            f"This action is not allowed during phase {phase!r}; "
            f"expected one of {expected_set}.",
        )


def assert_can_act(state: dict[str, Any], actor: str) -> None:
    """Reject moves from non-participants or repeat actors mid-round.

    User moves (``actor == ACTOR_USER``) are exempt — the user plays the
    environment layer and can intervene any time.
    """
    if actor == ACTOR_USER:
        return
    participants = list(state.get("participants") or [])
    if actor not in participants:
        raise ValidationError(
            f"Bot {actor!r} is not a participant in this game.",
        )
    last_actor = state.get("last_actor")
    if last_actor == actor:
        raise ValidationError(
            "You have already acted this round; waiting on other participants.",
        )


def assert_user_only(actor: str, action: str) -> None:
    if actor != ACTOR_USER:
        raise ValidationError(
            f"Action {action!r} is reserved for the user (environment layer).",
        )


def record_turn(
    state: dict[str, Any],
    *,
    actor: str,
    action: str,
    args: dict[str, Any] | None,
    reasoning: str | None,
    summary: str | None = None,
) -> None:
    """Append a canonical turn-log entry and update last_actor.

    The turn log is intentionally rich (args + reasoning + summary) so
    bots reading the state on a future heartbeat can understand the game's
    history without a separate fetch.
    """
    log = list(state.get("turn_log") or [])
    log.append({
        "actor": actor,
        "ts": _now_iso(),
        "action": action,
        "args": args or {},
        "reasoning": (reasoning or "").strip() or None,
        "summary": summary,
    })
    state["turn_log"] = log
    state["updated_at"] = log[-1]["ts"]
    if actor != ACTOR_USER:
        state["last_actor"] = actor


def all_participants_have_moved(state: dict[str, Any]) -> bool:
    """True when every participant has moved at least once since the last
    round bump. Game handlers can use this to auto-advance ``round``.
    """
    participants = list(state.get("participants") or [])
    if not participants:
        return False
    round_start = int(state.get("round_started_log_index") or 0)
    log = list(state.get("turn_log") or [])[round_start:]
    moved = {entry["actor"] for entry in log if entry.get("actor") != ACTOR_USER}
    return all(p in moved for p in participants)


def maybe_advance_round(state: dict[str, Any]) -> bool:
    """Bump the round counter when every participant has acted.

    Resets ``last_actor`` so the new round starts with everyone eligible.
    Returns True if the round was advanced.
    """
    if not all_participants_have_moved(state):
        return False
    state["round"] = int(state.get("round") or 0) + 1
    state["last_actor"] = None
    state["round_started_log_index"] = len(state.get("turn_log") or [])
    return True


# ---------------------------------------------------------------------------
# Directive (creative objective / theme) helpers
# ---------------------------------------------------------------------------


DIRECTIVE_THEME_MAX_LEN = 240
DIRECTIVE_CRITERIA_MAX_LEN = 240


def apply_directive(
    state: dict[str, Any],
    *,
    theme: str,
    success_criteria: str | None = None,
    set_by: str = ACTOR_USER,
) -> dict[str, Any]:
    """Set the user-authored creative directive on a game's state.

    The directive is a free-text objective that surfaces in the heartbeat
    prompt and the settings drawer. Games are expected to expose a
    ``set_directive`` user-only action that delegates here.
    """
    cleaned_theme = (theme or "").strip()
    if not cleaned_theme:
        raise ValidationError("theme is required for set_directive")
    if len(cleaned_theme) > DIRECTIVE_THEME_MAX_LEN:
        raise ValidationError(
            f"theme is too long (max {DIRECTIVE_THEME_MAX_LEN} chars)",
        )
    cleaned_criteria = (success_criteria or "").strip() or None
    if cleaned_criteria and len(cleaned_criteria) > DIRECTIVE_CRITERIA_MAX_LEN:
        raise ValidationError(
            f"success_criteria is too long (max {DIRECTIVE_CRITERIA_MAX_LEN} chars)",
        )
    directive = {
        "theme": cleaned_theme,
        "success_criteria": cleaned_criteria,
        "set_by": set_by,
        "set_at": _now_iso(),
    }
    state["directive"] = directive
    return directive


def clear_directive(state: dict[str, Any]) -> bool:
    """Remove any existing directive. Returns True if one was present."""
    if "directive" in state:
        state.pop("directive", None)
        return True
    return False


def directive_block(state: dict[str, Any]) -> str | None:
    """Render the directive as a one-or-two-line prompt block, or None."""
    directive = state.get("directive")
    if not isinstance(directive, dict):
        return None
    theme = str(directive.get("theme") or "").strip()
    if not theme:
        return None
    line = f"Directive: {theme}"
    criteria = directive.get("success_criteria")
    if criteria:
        line += f"\nSuccess: {criteria}"
    return line


# ---------------------------------------------------------------------------
# Dispatch registry
# ---------------------------------------------------------------------------


GameDispatcher = Callable[..., Any]
GameSummarizer = Callable[[dict[str, Any]], str]
GameLocalizer = Callable[[dict[str, Any], str], str | None]


_DISPATCHERS: dict[str, GameDispatcher] = {}
_SUMMARIZERS: dict[str, GameSummarizer] = {}
_AVAILABLE_ACTIONS: dict[str, Callable[[dict[str, Any], str], list[str]]] = {}
_LOCALIZERS: dict[str, GameLocalizer] = {}


def register_game(
    widget_ref: str,
    *,
    dispatcher: GameDispatcher,
    summarizer: GameSummarizer,
    available_actions: Callable[[dict[str, Any], str], list[str]] | None = None,
    localize: GameLocalizer | None = None,
) -> None:
    _DISPATCHERS[widget_ref] = dispatcher
    _SUMMARIZERS[widget_ref] = summarizer
    if available_actions is not None:
        _AVAILABLE_ACTIONS[widget_ref] = available_actions
    if localize is not None:
        _LOCALIZERS[widget_ref] = localize


def localize_for_actor(
    widget_ref: str,
    state: dict[str, Any],
    actor: str,
) -> str | None:
    """Return per-bot coaching text for the heartbeat block, or None.

    Each game registers an optional ``localize(state, actor)`` callback;
    when present, the heartbeat block uses its return value to replace
    most of the raw state dump with bot-aware hints.
    """
    fn = _LOCALIZERS.get(widget_ref)
    if fn is None:
        return None
    try:
        return fn(state, actor)
    except Exception:
        return None


def get_dispatcher(widget_ref: str) -> GameDispatcher | None:
    return _DISPATCHERS.get(widget_ref)


def summarize_state_for_prompt(widget_ref: str, state: dict[str, Any]) -> str:
    summarizer = _SUMMARIZERS.get(widget_ref)
    if summarizer is None:
        phase = state.get("phase") or "?"
        return f"({widget_ref}: phase={phase})"
    try:
        return summarizer(state)
    except Exception:
        return f"({widget_ref}: state digest unavailable)"


def available_actions_for(widget_ref: str, state: dict[str, Any], actor: str) -> list[str]:
    fn = _AVAILABLE_ACTIONS.get(widget_ref)
    if fn is None:
        return []
    try:
        return list(fn(state, actor))
    except Exception:
        return []


def is_game_widget(widget_ref: str | None) -> bool:
    return bool(widget_ref) and widget_ref.startswith(GAME_WIDGET_PREFIX)


# Eagerly import concrete games so their ``register_game`` calls run.
# Keep imports at the bottom to avoid circular-dep issues with shared helpers.
from app.services.games import ecosystem  # noqa: E402,F401
from app.services.games import blockyard  # noqa: E402,F401
from app.services.games import storybook  # noqa: E402,F401
