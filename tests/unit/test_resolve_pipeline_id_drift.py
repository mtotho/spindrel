"""Phase G.4 — pipelines::_resolve_pipeline_id resolution drift seams.

Seam class: orphan pointer + silent-UPDATE

_resolve_pipeline_id accepts input in three forms:
  1. Raw UUID — returned immediately with no task_type check.
  2. Slug → UUID5 derivation (pipeline_uuid) — if the derived row exists and
     has task_type='pipeline', return it; otherwise fall through.
  3. Title fallback — case-insensitive scan of all pipeline rows.

Drift seams:
- UUID input bypasses the task_type guard — a non-pipeline task UUID passes
  through the resolver; the error surfaces later in spawn_child_run as
  'not a task definition' rather than 'not found'. Different error class.
- UUID5 derivation shadows a user pipeline with the same title — the system
  pipeline occupies the slot; the user pipeline is unreachable by slug.
- System pipeline deleted → user pipeline with the same title silently takes
  over slug resolution (drift across the delete boundary).
"""
from __future__ import annotations

import uuid

import pytest

from app.db.models import Task
from app.services.task_seeding import pipeline_uuid
from app.tools.local.pipelines import _resolve_pipeline_id


def _make_pipeline(*, task_type: str = "pipeline", title: str | None = None,
                   source: str = "user", tid: uuid.UUID | None = None) -> Task:
    return Task(
        id=tid or uuid.uuid4(),
        bot_id="orchestrator",
        prompt="p",
        title=title,
        task_type=task_type,
        steps=[{"id": "s1", "type": "exec", "prompt": "x"}],
        source=source,
    )


# ---------------------------------------------------------------------------
# G.4.1 — UUID input bypasses task_type check
# ---------------------------------------------------------------------------


class TestUuidInputShortCircuit:
    @pytest.mark.asyncio
    async def test_uuid_of_non_pipeline_task_returned_without_type_check(
        self, db_session, patched_async_sessions
    ):
        """_resolve_pipeline_id returns any UUID; type guard lives in spawn_child_run.

        Drift pin: if caller assumes the returned UUID is a pipeline, it will
        hit a ValueError from spawn_child_run instead of the 'not found' path.
        The error surface is different — this documents the boundary.
        """
        agent_task = _make_pipeline(task_type="agent")
        db_session.add(agent_task)
        await db_session.commit()

        result = await _resolve_pipeline_id(str(agent_task.id), db_session)

        # Resolver returns the UUID — no pipeline type check here.
        assert result == agent_task.id

    @pytest.mark.asyncio
    async def test_uuid_of_pipeline_task_returned(self, db_session, patched_async_sessions):
        """Baseline: pipeline task UUID resolves immediately."""
        pipeline = _make_pipeline(task_type="pipeline")
        db_session.add(pipeline)
        await db_session.commit()

        result = await _resolve_pipeline_id(str(pipeline.id), db_session)
        assert result == pipeline.id


# ---------------------------------------------------------------------------
# G.4.2 — UUID5 derivation priority
# ---------------------------------------------------------------------------


class TestUuid5Derivation:
    @pytest.mark.asyncio
    async def test_uuid5_slug_wins_over_user_pipeline_with_same_title(
        self, db_session, patched_async_sessions
    ):
        """When a system pipeline occupies the UUID5 slot, user pipeline is shadowed.

        Drift pin: user creates a pipeline titled "sys.audit"; a system pipeline
        also exists with id=pipeline_uuid("sys.audit"). Slug resolution returns
        the system pipeline, not the user pipeline — UUID5 derivation fires first.
        """
        slug = "sys.audit"
        system_pipeline = _make_pipeline(
            title="Sys Audit", source="system", tid=pipeline_uuid(slug)
        )
        user_pipeline = _make_pipeline(title=slug, source="user")  # same title as slug
        db_session.add_all([system_pipeline, user_pipeline])
        await db_session.commit()

        result = await _resolve_pipeline_id(slug, db_session)

        # System pipeline wins via UUID5 derivation
        assert result == system_pipeline.id
        assert result != user_pipeline.id

    @pytest.mark.asyncio
    async def test_uuid5_row_absent_falls_through_to_title_match(
        self, db_session, patched_async_sessions
    ):
        """When UUID5 derivation has no matching row, title fallback fires.

        Drift pin: user-created pipeline "my-pipeline" is reachable by that string
        even though it has no slug (no system UUID5 row).
        """
        user_pipeline = _make_pipeline(title="my-pipeline", source="user")
        db_session.add(user_pipeline)
        await db_session.commit()

        result = await _resolve_pipeline_id("my-pipeline", db_session)

        assert result == user_pipeline.id

    @pytest.mark.asyncio
    async def test_uuid5_row_with_wrong_task_type_falls_through(
        self, db_session, patched_async_sessions
    ):
        """UUID5 match with task_type != 'pipeline' is skipped; title fallback fires.

        Edge: a UUID5 collision with a non-pipeline task type doesn't block resolution.
        """
        slug = "collision.slug"
        wrong_type_task = _make_pipeline(
            task_type="agent", source="system", tid=pipeline_uuid(slug)
        )
        correct_pipeline = _make_pipeline(title=slug, source="user")
        db_session.add_all([wrong_type_task, correct_pipeline])
        await db_session.commit()

        result = await _resolve_pipeline_id(slug, db_session)

        # UUID5 match exists but has wrong type → falls through to title match
        assert result == correct_pipeline.id


# ---------------------------------------------------------------------------
# G.4.3 — Title fallback properties
# ---------------------------------------------------------------------------


class TestTitleFallback:
    @pytest.mark.asyncio
    async def test_title_match_is_case_insensitive(
        self, db_session, patched_async_sessions
    ):
        """Title fallback normalises to lower before comparing — 'MyPipeline'
        resolves 'mypipeline'."""
        pipeline = _make_pipeline(title="MyPipeline")
        db_session.add(pipeline)
        await db_session.commit()

        result = await _resolve_pipeline_id("mypipeline", db_session)
        assert result == pipeline.id

    @pytest.mark.asyncio
    async def test_unknown_slug_returns_none(
        self, db_session, patched_async_sessions
    ):
        """No UUID5 match, no title match → None.  run_pipeline wraps this as an error."""
        result = await _resolve_pipeline_id("does.not.exist", db_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_db_returns_none(self, db_session, patched_async_sessions):
        """No pipelines in DB at all → None (not an exception)."""
        result = await _resolve_pipeline_id("anything", db_session)
        assert result is None


# ---------------------------------------------------------------------------
# G.4.4 — Silent resolution drift across delete boundary
# ---------------------------------------------------------------------------


class TestDeleteBoundaryDrift:
    @pytest.mark.asyncio
    async def test_deleted_system_pipeline_falls_back_to_user_pipeline_with_same_title(
        self, db_session, patched_async_sessions
    ):
        """Drift pin: after the system pipeline row is deleted, the slug resolves
        to a user pipeline with the same title via title fallback.

        Before delete: "sys.slug" → system pipeline (UUID5 derivation).
        After delete:  "sys.slug" → user pipeline (title fallback).

        This is intentional behaviour, but is a silent drift across the delete
        boundary — callers cannot distinguish which pipeline they got.
        """
        slug = "sys.slug"
        system_pipeline = _make_pipeline(
            title="Sys Slug", source="system", tid=pipeline_uuid(slug)
        )
        user_pipeline = _make_pipeline(title=slug, source="user")
        db_session.add_all([system_pipeline, user_pipeline])
        await db_session.commit()

        # Before delete: system pipeline wins.
        before = await _resolve_pipeline_id(slug, db_session)
        assert before == system_pipeline.id

        # Delete the system pipeline row.
        await db_session.delete(system_pipeline)
        await db_session.commit()

        # After delete: user pipeline wins via title fallback.
        after = await _resolve_pipeline_id(slug, db_session)
        assert after == user_pipeline.id
        assert after != system_pipeline.id
