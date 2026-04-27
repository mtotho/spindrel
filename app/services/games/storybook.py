"""Storybook — round-robin story completer (1v1 friendly, but supports N>=2).

Each turn, the active player adds 1..N sentences to a shared story. The
user sets a title, optional genre, optional directive, plus stanza_cap
and sentence_cap_per_turn. When the stanza count hits the cap, the game
auto-ends.

Renderer is a manuscript-style serif column — no canvas, no SVG. The
framework's heartbeat block carries the directive + the last few stanzas
to participating bots.
"""
from __future__ import annotations

import copy
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
    maybe_advance_round,
    record_turn,
    register_game,
)


WIDGET_REF = "core/game_storybook"
GAME_TYPE = "storybook"

DEFAULT_STANZA_CAP = 12
MAX_STANZA_CAP = 60
DEFAULT_SENTENCE_CAP = 3
MAX_SENTENCE_CAP = 6
MAX_TEXT_LEN = 1200
MAX_TITLE_LEN = 120
MAX_GENRE_LEN = 60

# Sentence-end heuristic: '.', '!', '?' followed by whitespace or string-end.
_SENTENCE_RE = re.compile(r"[.!?]+(?:\s|$)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict[str, Any]:
    now = _now_iso()
    return {
        "game_type": GAME_TYPE,
        "phase": PHASE_SETUP,
        "participants": [],
        "last_actor": None,
        "round": 0,
        "round_started_log_index": 0,
        "turn_log": [],
        "title": "",
        "genre": "",
        "stanza_cap": DEFAULT_STANZA_CAP,
        "sentence_cap_per_turn": DEFAULT_SENTENCE_CAP,
        "stanzas": [],
        "directive": None,
        "created_at": now,
        "updated_at": now,
    }


def _count_sentences(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    matches = _SENTENCE_RE.findall(text)
    if matches:
        # Strip trailing whitespace; matches count terminators that end a
        # sentence. If text doesn't end with a terminator, the trailing
        # fragment still counts as one sentence.
        ends_with_terminator = bool(_SENTENCE_RE.search(text + " ")) and text.rstrip()[-1] in ".!?"
        return len(matches) if ends_with_terminator else len(matches) + 1
    return 1


# ---------------------------------------------------------------------------
# Bot actions
# ---------------------------------------------------------------------------


def _action_add_stanza(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_phase(state, PHASE_PLAYING)
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValidationError("text is required (1+ sentences continuing the story).")
    if len(text) > MAX_TEXT_LEN:
        raise ValidationError(f"text too long (max {MAX_TEXT_LEN} chars).")
    cap = int(state.get("sentence_cap_per_turn") or DEFAULT_SENTENCE_CAP)
    sentences = _count_sentences(text)
    if sentences > cap:
        raise ValidationError(
            f"stanza has {sentences} sentences but the cap is {cap}; trim it down.",
        )
    stanzas = state.setdefault("stanzas", [])
    stanzas.append(
        {
            "actor": actor,
            "text": text,
            "ts": _now_iso(),
            "sentences": sentences,
        },
    )
    stanza_cap = int(state.get("stanza_cap") or DEFAULT_STANZA_CAP)
    auto_ended = False
    if len(stanzas) >= stanza_cap:
        state["phase"] = PHASE_ENDED
        auto_ended = True
    summary = f"added stanza ({sentences} sentence{'s' if sentences != 1 else ''})"
    return {
        "ok": True,
        "summary": summary,
        "stanza_index": len(stanzas) - 1,
        "stanzas_total": len(stanzas),
        "auto_ended": auto_ended,
    }


# ---------------------------------------------------------------------------
# User actions
# ---------------------------------------------------------------------------


def _action_set_title(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_title")
    title = str(args.get("title") or "").strip()
    if len(title) > MAX_TITLE_LEN:
        raise ValidationError(f"title too long (max {MAX_TITLE_LEN} chars).")
    state["title"] = title
    return {"ok": True, "title": title}


def _action_set_genre(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_genre")
    genre = str(args.get("genre") or "").strip()
    if len(genre) > MAX_GENRE_LEN:
        raise ValidationError(f"genre too long (max {MAX_GENRE_LEN} chars).")
    state["genre"] = genre
    return {"ok": True, "genre": genre}


def _action_set_stanza_cap(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_stanza_cap")
    try:
        value = int(args.get("count"))
    except (TypeError, ValueError):
        raise ValidationError("count must be an integer.") from None
    if value < 1 or value > MAX_STANZA_CAP:
        raise ValidationError(f"count must be between 1 and {MAX_STANZA_CAP}.")
    state["stanza_cap"] = value
    return {"ok": True, "stanza_cap": value}


def _action_set_sentence_cap(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_sentence_cap")
    try:
        value = int(args.get("count"))
    except (TypeError, ValueError):
        raise ValidationError("count must be an integer.") from None
    if value < 1 or value > MAX_SENTENCE_CAP:
        raise ValidationError(f"count must be between 1 and {MAX_SENTENCE_CAP}.")
    state["sentence_cap_per_turn"] = value
    return {"ok": True, "sentence_cap_per_turn": value}


def _action_set_participants(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "set_participants")
    raw = args.get("bot_ids") or []
    if not isinstance(raw, list):
        raise ValidationError("bot_ids must be an array of bot ids.")
    bot_ids = [str(b).strip() for b in raw if str(b).strip()]
    state["participants"] = bot_ids
    state["last_actor"] = None
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
    return {"ok": True, "phase": phase, "round": state.get("round", 0)}


def _action_set_directive(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
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


def _action_delete_last_stanza(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    """User-only escape hatch — pop the last stanza off if a bot wrote
    something the user wants gone."""
    assert_user_only(actor, "delete_last_stanza")
    stanzas = list(state.get("stanzas") or [])
    if not stanzas:
        raise ValidationError("no stanzas to delete.")
    removed = stanzas.pop()
    state["stanzas"] = stanzas
    # If we'd auto-ended the game, reopen it.
    if state.get("phase") == PHASE_ENDED and len(stanzas) < int(state.get("stanza_cap") or DEFAULT_STANZA_CAP):
        state["phase"] = PHASE_PLAYING
    return {
        "ok": True,
        "removed_actor": removed.get("actor"),
        "stanzas_total": len(stanzas),
    }


def _action_advance_round(state: dict[str, Any], actor: str, args: dict[str, Any]) -> dict[str, Any]:
    assert_user_only(actor, "advance_round")
    assert_phase(state, PHASE_PLAYING)
    state["round"] = int(state.get("round") or 0) + 1
    state["last_actor"] = None
    state["round_started_log_index"] = len(state.get("turn_log") or []) + 1
    return {"ok": True, "round": state["round"]}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_BOT_ACTIONS = {
    "add_stanza": _action_add_stanza,
}

_USER_ACTIONS = {
    "set_title": _action_set_title,
    "set_genre": _action_set_genre,
    "set_stanza_cap": _action_set_stanza_cap,
    "set_sentence_cap": _action_set_sentence_cap,
    "set_participants": _action_set_participants,
    "set_phase": _action_set_phase,
    "set_directive": _action_set_directive,
    "delete_last_stanza": _action_delete_last_stanza,
    "advance_round": _action_advance_round,
    # User can also play stanzas — they're just another participant.
    "add_stanza": _action_add_stanza,
}


async def dispatch(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
    *,
    actor: str,
) -> Any:
    state = copy.deepcopy(instance.state or {})
    if "stanzas" not in state or "title" not in state:
        # Defensive seeding for instances created before this module existed.
        seeded = default_state()
        seeded.update(state)
        state = seeded
        state.setdefault("stanzas", [])
    args = args or {}

    if actor == ACTOR_USER:
        handler = _USER_ACTIONS.get(action)
    else:
        handler = _BOT_ACTIONS.get(action)
    if handler is None:
        raise NotFoundError(f"Unsupported storybook action: {action!r}")

    is_bot_action = actor != ACTOR_USER
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


# ---------------------------------------------------------------------------
# State digest for heartbeat prompt
# ---------------------------------------------------------------------------


def summarize(state: dict[str, Any]) -> str:
    phase = state.get("phase") or PHASE_SETUP
    round_n = state.get("round") or 0
    title = (state.get("title") or "").strip() or "(untitled)"
    genre = (state.get("genre") or "").strip()
    stanza_cap = int(state.get("stanza_cap") or DEFAULT_STANZA_CAP)
    sentence_cap = int(state.get("sentence_cap_per_turn") or DEFAULT_SENTENCE_CAP)
    stanzas = list(state.get("stanzas") or [])
    parts: list[str] = [
        f"Storybook — \"{title}\"" + (f" ({genre})" if genre else ""),
        (
            f"Round {round_n}, phase={phase}, last actor: "
            f"{state.get('last_actor') or '—'}. "
            f"Stanzas: {len(stanzas)}/{stanza_cap}, sentence cap per turn: {sentence_cap}."
        ),
        (
            "Each turn, add 1.."
            f"{sentence_cap} sentence(s) that continue from the previous "
            "stanza. Pick up the tone, advance the story, leave a hook."
        ),
        'add_stanza args: {"text": "Your sentence(s).", "reasoning": "optional"}.',
    ]
    if stanzas:
        recent = stanzas[-3:]
        parts.append("Most recent stanzas (oldest → newest):")
        for stanza in recent:
            actor = stanza.get("actor") or "?"
            text = (stanza.get("text") or "").strip()
            parts.append(f"  [{actor}] {text}")
    else:
        parts.append("No stanzas yet — you're writing the opening.")
    return "\n".join(parts)


def available_actions(state: dict[str, Any], actor: str) -> list[str]:
    if actor == ACTOR_USER:
        return list(_USER_ACTIONS.keys())
    phase = state.get("phase") or PHASE_SETUP
    if phase != PHASE_PLAYING:
        return []
    return ["add_stanza"]


def localize(state: dict[str, Any], actor: str) -> str | None:
    if actor == ACTOR_USER or not actor:
        return None
    cap = int(state.get("sentence_cap_per_turn") or DEFAULT_SENTENCE_CAP)
    stanzas = list(state.get("stanzas") or [])
    stanza_cap = int(state.get("stanza_cap") or DEFAULT_STANZA_CAP)
    remaining = max(0, stanza_cap - len(stanzas))
    parts = [
        f"Your turn — write 1..{cap} sentence(s). "
        f"{remaining} stanza(s) remain before the story auto-ends.",
    ]
    if stanzas:
        last = stanzas[-1]
        parts.append(
            f"Continuation hook (last stanza by {last.get('actor')}): "
            f"\"{(last.get('text') or '').strip()}\"",
        )
    return "\n".join(parts)


register_game(
    WIDGET_REF,
    dispatcher=dispatch,
    summarizer=summarize,
    available_actions=available_actions,
    localize=localize,
)
