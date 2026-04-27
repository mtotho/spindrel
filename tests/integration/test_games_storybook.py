"""Integration tests for the Storybook 1v1 round-robin story completer."""
from __future__ import annotations

import uuid

import pytest

from app.db.models import WidgetInstance
from app.domain.errors import ValidationError
from app.services.dashboards import WORKSPACE_SPATIAL_DASHBOARD_KEY
from app.services.games import ACTOR_USER, PHASE_ENDED, PHASE_PLAYING
from app.services.games.storybook import (
    DEFAULT_SENTENCE_CAP,
    DEFAULT_STANZA_CAP,
    MAX_SENTENCE_CAP,
    MAX_STANZA_CAP,
    WIDGET_REF,
    _count_sentences,
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


async def _start(db_session, instance, *bot_ids: str) -> None:
    await _act(db_session, instance, "set_participants", {"bot_ids": list(bot_ids)})
    await _act(db_session, instance, "set_phase", {"phase": "playing"})


# ── Sentence counter heuristic ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", 0),
        ("Just one sentence.", 1),
        ("First. Second.", 2),
        ("First! Second? Third.", 3),
        ("No terminator", 1),
        ("Question without terminator?", 1),
    ],
)
def test_count_sentences(text, expected):
    assert _count_sentences(text) == expected


# ── Setters / setup phase ──────────────────────────────────────────────────


class TestSetup:
    async def test_set_title_persists(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_title", {"title": "  Lighthouse  "})
        assert inst.state["title"] == "Lighthouse"

    async def test_set_genre_persists(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_genre", {"genre": "cozy mystery"})
        assert inst.state["genre"] == "cozy mystery"

    async def test_set_stanza_cap_validates_range(self, db_session):
        inst = await _make_instance(db_session)
        with pytest.raises(ValidationError):
            await _act(db_session, inst, "set_stanza_cap", {"count": 0})
        with pytest.raises(ValidationError):
            await _act(db_session, inst, "set_stanza_cap", {"count": MAX_STANZA_CAP + 1})

    async def test_set_sentence_cap_validates_range(self, db_session):
        inst = await _make_instance(db_session)
        with pytest.raises(ValidationError):
            await _act(db_session, inst, "set_sentence_cap", {"count": 0})
        with pytest.raises(ValidationError):
            await _act(db_session, inst, "set_sentence_cap", {"count": MAX_SENTENCE_CAP + 1})

    async def test_set_directive_persists_and_clears(self, db_session):
        inst = await _make_instance(db_session)
        await _act(
            db_session,
            inst,
            "set_directive",
            {"theme": "ends with a quiet reveal"},
        )
        assert inst.state["directive"]["theme"] == "ends with a quiet reveal"
        await _act(db_session, inst, "set_directive", {"theme": ""})
        assert inst.state.get("directive") is None


# ── add_stanza ─────────────────────────────────────────────────────────────


class TestAddStanza:
    async def test_bot_can_add_stanza_during_play(self, db_session):
        inst = await _make_instance(db_session)
        await _start(db_session, inst, "rolland")
        result = await _act(
            db_session,
            inst,
            "add_stanza",
            {"text": "The cat appeared on the third Tuesday."},
            bot_id="rolland",
        )
        assert result["ok"] is True
        assert len(inst.state["stanzas"]) == 1
        assert inst.state["stanzas"][0]["actor"] == "rolland"
        assert inst.state["stanzas"][0]["sentences"] == 1

    async def test_user_can_add_stanza(self, db_session):
        inst = await _make_instance(db_session)
        await _start(db_session, inst, "rolland")
        await _act(
            db_session,
            inst,
            "add_stanza",
            {"text": "Marta watched."},
        )
        assert inst.state["stanzas"][0]["actor"] == ACTOR_USER

    async def test_sentence_cap_enforced(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_sentence_cap", {"count": 2})
        await _start(db_session, inst, "rolland")
        with pytest.raises(ValidationError, match="cap is 2"):
            await _act(
                db_session,
                inst,
                "add_stanza",
                {"text": "One. Two. Three."},
                bot_id="rolland",
            )

    async def test_empty_text_rejected(self, db_session):
        inst = await _make_instance(db_session)
        await _start(db_session, inst, "rolland")
        with pytest.raises(ValidationError, match="text is required"):
            await _act(db_session, inst, "add_stanza", {"text": "   "}, bot_id="rolland")

    async def test_stanza_cap_auto_ends_game(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_stanza_cap", {"count": 2})
        await _start(db_session, inst, "rolland", "zeus")
        await _act(
            db_session,
            inst,
            "add_stanza",
            {"text": "First."},
            bot_id="rolland",
        )
        result = await _act(
            db_session,
            inst,
            "add_stanza",
            {"text": "Second."},
            bot_id="zeus",
        )
        assert result["auto_ended"] is True
        assert inst.state["phase"] == PHASE_ENDED

    async def test_setup_phase_rejects_add_stanza(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_participants", {"bot_ids": ["rolland"]})
        with pytest.raises(ValidationError, match="phase"):
            await _act(
                db_session,
                inst,
                "add_stanza",
                {"text": "Too early."},
                bot_id="rolland",
            )

    async def test_two_bot_alternation(self, db_session):
        inst = await _make_instance(db_session)
        await _start(db_session, inst, "rolland", "zeus")
        await _act(
            db_session,
            inst,
            "add_stanza",
            {"text": "Rolland opens."},
            bot_id="rolland",
        )
        # rolland already moved this round — framework rejects the second attempt.
        with pytest.raises(ValidationError, match="already acted"):
            await _act(
                db_session,
                inst,
                "add_stanza",
                {"text": "Rolland again."},
                bot_id="rolland",
            )
        # zeus may move; both having moved triggers a round bump.
        await _act(
            db_session,
            inst,
            "add_stanza",
            {"text": "Zeus replies."},
            bot_id="zeus",
        )
        assert inst.state["round"] == 2


# ── delete_last_stanza ─────────────────────────────────────────────────────


class TestDeleteLastStanza:
    async def test_user_only(self, db_session):
        inst = await _make_instance(db_session)
        await _start(db_session, inst, "rolland", "zeus")
        await _act(db_session, inst, "add_stanza", {"text": "First."}, bot_id="rolland")
        # delete_last_stanza is only registered as a user action — bots
        # can't even reach it, so dispatch raises NotFoundError.
        from app.domain.errors import NotFoundError
        with pytest.raises(NotFoundError, match="Unknown action|delete_last_stanza"):
            await _act(
                db_session,
                inst,
                "delete_last_stanza",
                {},
                bot_id="rolland",
            )

    async def test_pop_reopens_ended_game(self, db_session):
        inst = await _make_instance(db_session)
        await _act(db_session, inst, "set_stanza_cap", {"count": 1})
        await _start(db_session, inst, "rolland")
        await _act(db_session, inst, "add_stanza", {"text": "Done."}, bot_id="rolland")
        assert inst.state["phase"] == PHASE_ENDED
        await _act(db_session, inst, "delete_last_stanza", {})
        assert inst.state["phase"] == PHASE_PLAYING
        assert inst.state["stanzas"] == []

    async def test_delete_with_no_stanzas_rejected(self, db_session):
        inst = await _make_instance(db_session)
        await _start(db_session, inst, "rolland")
        with pytest.raises(ValidationError, match="no stanzas"):
            await _act(db_session, inst, "delete_last_stanza", {})


# ── localize() coaching ────────────────────────────────────────────────────


class TestLocalize:
    async def test_returns_none_for_user(self, db_session):
        inst = await _make_instance(db_session)
        assert localize(inst.state, ACTOR_USER) is None

    async def test_includes_continuation_hook_when_stanzas_exist(self, db_session):
        inst = await _make_instance(db_session)
        await _start(db_session, inst, "rolland", "zeus")
        await _act(db_session, inst, "add_stanza", {"text": "An opening line."})
        text = localize(inst.state, "rolland")
        assert text is not None
        assert "Continuation hook" in text
        assert "An opening line" in text

    async def test_summary_carries_directive_setup(self, db_session):
        inst = await _make_instance(db_session)
        text = summarize(inst.state)
        assert "Storybook" in text
        assert "untitled" in text
