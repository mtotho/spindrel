"""Phase N.4 — session_plan_mode.py drift seams.

Scope: pure-python helpers that coerce, dedupe, clip, and advance the
plan/adherence metadata capsules. These are the quiet-failure corners —
they feed every runtime display and every mutation is JSONB on
``Session.metadata_`` where silent-default drift bites.

Drift seams pinned:
1. ``_normalize_planning_state`` recovers default when raw is non-dict,
   when list fields are scalars, or when keys are missing entirely.
2. ``_dedupe_recent_items`` is case-insensitive, last-wins (reverse
   iteration), skips empty/whitespace values, and caps the retained
   window at ``limit``.
3. ``update_planning_state`` respects ``_PLANNING_STATE_LIST_LIMIT`` (12)
   so runaway appends don't balloon the JSONB.
4. ``_clear_pending_turn_outcome`` wipes a malformed record with neither
   turn_id nor correlation_id, preserves one that doesn't match, and
   wipes on either-side match.
5. ``list_session_plan_revisions`` tolerates a missing on-disk snapshot
   for an earlier revision (orphan-pointer) and still returns the
   current-revision entry.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.models import Session
from app.services import session_plan_mode as spm


def _make_session() -> Session:
    return Session(
        id=uuid.uuid4(),
        client_id=f"client-{uuid.uuid4().hex[:6]}",
        bot_id="test-bot",
        channel_id=uuid.uuid4(),
        metadata_={},
    )


def _patch_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(spm, "get_bot", lambda _bot_id: SimpleNamespace(id="test-bot"))
    monkeypatch.setattr(spm, "ensure_channel_workspace", lambda _channel_id, _bot: str(tmp_path))


class TestNormalizePlanningState:
    def test_non_dict_raw_returns_clean_default(self):
        state = spm._normalize_planning_state("garbage-not-a-dict")

        assert state == spm._planning_state_default()
        # All list fields must be lists, not the scalar we passed.
        for field in ("decisions", "open_questions", "assumptions", "evidence"):
            assert state[field] == []

    def test_missing_fields_are_filled_from_default(self):
        raw = {"decisions": [{"text": "A"}]}

        state = spm._normalize_planning_state(raw)

        assert state["decisions"] == [{"text": "A"}]
        assert state["open_questions"] == []
        assert state["assumptions"] == []
        assert state["last_updated_at"] is None

    def test_scalar_value_in_list_field_is_coerced_to_empty_list(self):
        """Corrupt JSONB where a list field is a string → coerced to []."""
        raw = {"decisions": "not a list", "open_questions": 42}

        state = spm._normalize_planning_state(raw)

        assert state["decisions"] == []
        assert state["open_questions"] == []


class TestDedupeRecentItems:
    def test_case_insensitive_dedupe_keeps_last_occurrence(self):
        items = [
            {"text": "Decide on A", "created_at": "1"},
            {"text": "decide on a", "created_at": "2"},
            {"text": "DECIDE ON A", "created_at": "3"},
        ]

        result = spm._dedupe_recent_items(items, limit=10)

        assert len(result) == 1
        assert result[0]["created_at"] == "3"

    def test_empty_or_whitespace_text_items_are_dropped(self):
        items = [
            {"text": ""},
            {"text": "   "},
            {"text": "Keep me"},
        ]

        result = spm._dedupe_recent_items(items, limit=10)

        assert [i["text"] for i in result] == ["Keep me"]

    def test_limit_caps_output_to_most_recent(self):
        items = [{"text": f"item-{i}"} for i in range(20)]

        result = spm._dedupe_recent_items(items, limit=5)

        assert len(result) == 5
        assert [i["text"] for i in result] == ["item-15", "item-16", "item-17", "item-18", "item-19"]


class TestUpdatePlanningStateListLimit:
    def test_runaway_appends_are_capped_at_list_limit(self):
        session = _make_session()

        # Append twice the limit in distinct decisions to avoid dedupe.
        spm.update_planning_state(
            session,
            decisions=[f"decision-{i}" for i in range(spm._PLANNING_STATE_LIST_LIMIT * 2)],
        )

        state = spm.get_planning_state(session)
        assert len(state["decisions"]) == spm._PLANNING_STATE_LIST_LIMIT
        # last-N semantics: highest-numbered decisions survive
        texts = [d["text"] for d in state["decisions"]]
        assert texts[-1] == f"decision-{spm._PLANNING_STATE_LIST_LIMIT * 2 - 1}"

    def test_update_planning_state_marks_metadata_modified(self):
        """SQLAlchemy flag_modified is load-bearing for JSONB on Postgres.

        Without it, mutating ``metadata_['x']`` in place won't trigger an
        UPDATE. Pin that the service wraps mutations in
        ``flag_modified(session, 'metadata_')``.
        """
        from sqlalchemy.orm.attributes import flag_modified

        session = _make_session()
        calls: list[tuple[object, str]] = []
        original = flag_modified

        def spy(instance, key):
            calls.append((instance, key))
            return original(instance, key)

        # Patch the import the service uses.
        import app.services.session_plan_mode as target

        target.flag_modified = spy  # type: ignore[assignment]
        try:
            spm.update_planning_state(session, decisions=["x"])
        finally:
            target.flag_modified = original  # type: ignore[assignment]

        assert any(key == "metadata_" for _, key in calls)


class TestClearPendingTurnOutcome:
    def test_malformed_pending_without_ids_is_wiped_eagerly(self):
        runtime = {"pending_turn_outcome": {"summary": "no ids"}}

        spm._clear_pending_turn_outcome(runtime, turn_id="t-1", correlation_id=None)

        assert "pending_turn_outcome" not in runtime

    def test_non_matching_ids_preserve_pending(self):
        runtime = {
            "pending_turn_outcome": {"turn_id": "t-orig", "correlation_id": "c-orig"},
        }

        spm._clear_pending_turn_outcome(runtime, turn_id="t-other", correlation_id="c-other")

        assert runtime["pending_turn_outcome"] == {
            "turn_id": "t-orig",
            "correlation_id": "c-orig",
        }

    def test_correlation_id_match_wipes_pending(self):
        runtime = {
            "pending_turn_outcome": {"turn_id": None, "correlation_id": "c-1"},
        }

        spm._clear_pending_turn_outcome(runtime, turn_id=None, correlation_id="c-1")

        assert "pending_turn_outcome" not in runtime

    def test_non_dict_pending_is_popped(self):
        runtime = {"pending_turn_outcome": "stringly-typed-garbage"}

        spm._clear_pending_turn_outcome(runtime, turn_id="t-1", correlation_id=None)

        assert "pending_turn_outcome" not in runtime


class TestListRevisionsOrphanSnapshot:
    def test_missing_earlier_snapshot_does_not_crash_listing(self, monkeypatch, tmp_path):
        """Snapshot file for revision N-1 removed externally (FS GC, user rm) →
        list_session_plan_revisions still returns the current revision entry
        without raising.
        """
        _patch_workspace(monkeypatch, tmp_path)
        session = _make_session()

        plan = spm.create_session_plan(session, title="Orphan Revision Plan")
        # Bump to revision 2 by re-publishing under the same title.
        plan2 = spm.publish_session_plan(
            session,
            title="Orphan Revision Plan",
            summary="updated summary",
        )
        assert plan2.revision > plan.revision

        # Delete the revision-1 snapshot behind the service's back.
        snapshot_path = Path(
            spm.build_plan_snapshot_path(session, plan.task_slug, 1)
        )
        if snapshot_path.exists():
            snapshot_path.unlink()

        entries = spm.list_session_plan_revisions(session)

        assert entries, "expected at least the current-revision entry"
        current = next((e for e in entries if e.get("is_active")), None)
        assert current is not None
        assert current["revision"] == plan2.revision
